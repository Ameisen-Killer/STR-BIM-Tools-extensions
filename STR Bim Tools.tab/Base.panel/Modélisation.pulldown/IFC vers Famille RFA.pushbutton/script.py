# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.3.1"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "IFC vers Famille RFA"
# =============================================================================
#
# Conversion : app.OpenIFCDocument(ifc) -> export SAT -> import SAT
# dans une famille vierge (.rft) -> sauvegarde .rfa
#
# Double-clic sur une ligne ERREUR affiche le detail complet.
#

import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()

try:
    import os, io, json, tempfile
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")
    import System, System.IO, System.Text, System.Windows.Markup
    import System.Windows as SW
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, DataGridCheckBoxColumn,
                                         RowDefinition, ColumnDefinition, Orientation,
                                         TextBox, ProgressBar)
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Threading import DispatcherPriority
    from Microsoft.Win32 import OpenFileDialog
    from System.Windows.Forms import FolderBrowserDialog, DialogResult as WFDialogResult
    from System.Collections.Generic import List

    from Autodesk.Revit.DB import (
        FilteredElementCollector, Transaction, ElementId,
        SaveAsOptions, SATExportOptions, SATImportOptions,
        View, View3D, ViewType, ViewFamilyType, ViewFamily,
        ImportPlacement, Options, ViewDetailLevel,
        Solid, GeometryInstance, FreeFormElement, SolidUtils
    )

    app     = __revit__.Application
    doc     = __revit__.ActiveUIDocument.Document
    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # -------------------------------------------------------------------------
    # Helpers UI
    # -------------------------------------------------------------------------
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    def do_events(dispatcher):
        try:
            dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
        except Exception:
            pass

    def browse_folder(initial=u""):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Selectionner un dossier"
        if initial and os.path.isdir(initial):
            dlg.SelectedPath = initial
        if dlg.ShowDialog() == WFDialogResult.OK:
            return dlg.SelectedPath
        return None

    def browse_rft(initial=u""):
        dlg = OpenFileDialog()
        dlg.Title  = u"Selectionner un gabarit de famille (.rft)"
        dlg.Filter = u"Gabarit famille Revit (*.rft)|*.rft"
        if initial and os.path.isfile(initial):
            dlg.InitialDirectory = os.path.dirname(initial)
        if dlg.ShowDialog():
            return dlg.FileName
        return None

    def show_error_detail(name, detail):
        td = TaskDialog(u"Detail erreur : " + name)
        td.MainContent     = u"La conversion de ce fichier a echoue."
        td.ExpandedContent = detail
        td.CommonButtons   = TaskDialogCommonButtons.Close
        td.Show()

    # -------------------------------------------------------------------------
    # Prefs
    # -------------------------------------------------------------------------
    _PREFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    def load_prefs():
        try:
            with io.open(_PREFS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_prefs(data):
        try:
            with io.open(_PREFS, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Logique de conversion
    # -------------------------------------------------------------------------
    def _get_first_3d_view(a_doc):
        for v in FilteredElementCollector(a_doc).OfClass(View3D).ToElements():
            try:
                if not v.IsTemplate:
                    return v
            except Exception:
                pass
        return None

    def _get_or_create_3d_view(a_doc, log_cb):
        """Retourne une vue 3D existante, ou en cree une (les docs issus
        de OpenIFCDocument n'ont souvent aucune vue 3D)."""
        v = _get_first_3d_view(a_doc)
        if v is not None:
            return v
        log_cb(u"Creation vue 3D...")
        vft_3d = None
        for vft in FilteredElementCollector(a_doc).OfClass(ViewFamilyType).ToElements():
            try:
                if vft.ViewFamily == ViewFamily.ThreeDimensional:
                    vft_3d = vft
                    break
            except Exception:
                pass
        if vft_3d is None:
            raise Exception(u"Aucun type de vue 3D disponible dans le document IFC.")
        t = Transaction(a_doc, u"STR - Creation vue 3D")
        t.Start()
        try:
            v = View3D.CreateIsometric(a_doc, vft_3d.Id)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        return v

    def _get_plan_view(a_doc):
        for v in FilteredElementCollector(a_doc).OfClass(View).ToElements():
            try:
                if v.ViewType == ViewType.FloorPlan and not v.IsTemplate:
                    return v
            except Exception:
                pass
        return None

    def _open_family(rft_template, log_cb):
        log_cb(u"Creation famille depuis gabarit...")
        fam_doc   = app.NewFamilyDocument(rft_template)
        plan_view = _get_plan_view(fam_doc)
        if plan_view is None:
            fam_doc.Close(False)
            raise Exception(u"Aucune vue plan dans le gabarit famille.")
        return fam_doc, plan_view

    def _collect_solids(geom_elem):
        """Extrait recursivement tous les solides non vides d'un GeometryElement."""
        solids = []
        if geom_elem is None:
            return solids
        for g in geom_elem:
            try:
                if isinstance(g, Solid):
                    if g.Volume > 1e-9:
                        # Un Solid importe peut contenir N volumes disjoints
                        # (multi-coques) -> les separer en solides individuels
                        try:
                            split = SolidUtils.SplitVolumes(g)
                            solids.extend([s for s in split if s.Volume > 1e-9])
                        except Exception:
                            solids.append(g)
                elif isinstance(g, GeometryInstance):
                    solids.extend(_collect_solids(g.GetInstanceGeometry()))
            except Exception:
                pass
        return solids

    def _save_rfa(fam_doc, rfa_path, log_cb):
        log_cb(u"Sauvegarde RFA...")
        save_opts = SaveAsOptions()
        save_opts.OverwriteExistingFile = True
        fam_doc.SaveAs(rfa_path, save_opts)
        fam_doc.Close(False)

    # -- Conversion : IFC -> projet Revit -> SAT -> famille ------------------
    def _strategy_via_sat(ifc_path, rft_template, rfa_path, log_cb):
        """
        Ouvre le fichier IFC via OpenIFCDocument (lien/import IFC natif),
        exporte la geometrie en SAT, puis importe le SAT dans une famille vierge.
        """
        name     = os.path.splitext(os.path.basename(ifc_path))[0]
        tmp_dir  = tempfile.gettempdir()
        sat_base = u"STR_tmp_" + name
        sat_path = os.path.join(tmp_dir, sat_base + u".sat")

        # Ouverture IFC via la methode API dediee (cree un cache .ifc.RVT a cote)
        log_cb(u"Ouverture IFC (OpenIFCDocument)...")
        ifc_doc = app.OpenIFCDocument(ifc_path)

        try:
            # Export SAT depuis la vue 3D
            log_cb(u"Export geometrie SAT...")
            view3d = _get_or_create_3d_view(ifc_doc, log_cb)

            view_ids = List[ElementId]()
            view_ids.Add(view3d.Id)
            sat_opts = SATExportOptions()
            exported = ifc_doc.Export(tmp_dir, sat_base, view_ids, sat_opts)
            ifc_doc.Close(False)
            ifc_doc = None

            if not exported:
                raise Exception(u"Document.Export() a retourne False.")

            # Revit peut ou non ajouter l'extension .sat
            if not os.path.isfile(sat_path):
                alt = os.path.join(tmp_dir, sat_base)
                if os.path.isfile(alt):
                    sat_path = alt
                else:
                    # Chercher tout fichier correspondant dans tmp
                    candidates = [f for f in os.listdir(tmp_dir)
                                  if f.startswith(sat_base) and f.endswith(u".sat")]
                    if candidates:
                        sat_path = os.path.join(tmp_dir, candidates[0])
                    else:
                        raise Exception(u"Fichier SAT introuvable apres export dans : " + tmp_dir)

            # Import SAT dans famille puis eclatement en FreeFormElements
            fam_doc, plan_view = _open_family(rft_template, log_cb)
            sat_imp_opts           = SATImportOptions()
            sat_imp_opts.Placement = ImportPlacement.Origin
            log_cb(u"Import SAT dans famille...")
            t = Transaction(fam_doc, u"STR - Import geometrie IFC")
            t.Start()
            try:
                imp_id = fam_doc.Import(sat_path, sat_imp_opts, plan_view)

                # Eclatement : un FreeFormElement natif par solide
                log_cb(u"Eclatement en solides natifs...")
                nb_ff = 0
                imp_el = fam_doc.GetElement(imp_id)
                if imp_el is not None:
                    g_opts             = Options()
                    g_opts.DetailLevel = ViewDetailLevel.Fine
                    solids = _collect_solids(imp_el.get_Geometry(g_opts))
                    for idx, solid in enumerate(solids):
                        try:
                            FreeFormElement.Create(fam_doc, solid)
                            nb_ff += 1
                        except Exception:
                            pass  # solide non convertible -> reste dans l'import
                        if idx % 10 == 0:
                            log_cb(u"Eclatement... {}/{} solides".format(idx + 1, len(solids)))

                # Supprimer l'import fige seulement si TOUT a ete converti
                # (sinon on garderait les deux et les solides rates seraient perdus)
                if nb_ff > 0 and nb_ff == len(solids):
                    fam_doc.Delete(imp_id)
                log_cb(u"{} solide(s) natif(s) cree(s)".format(nb_ff))

                t.Commit()
            except Exception:
                t.RollBack()
                fam_doc.Close(False)
                raise
            _save_rfa(fam_doc, rfa_path, log_cb)

        finally:
            try:
                if ifc_doc is not None:
                    ifc_doc.Close(False)
            except Exception:
                pass
            try:
                if os.path.isfile(sat_path):
                    os.remove(sat_path)
            except Exception:
                pass
            # OpenIFCDocument cree un cache "fichier.ifc.RVT" a cote de l'IFC
            for cache_ext in (u".ifc.RVT", u".ifc.rvt"):
                cache = os.path.splitext(ifc_path)[0] + cache_ext
                try:
                    if os.path.isfile(cache):
                        os.remove(cache)
                except Exception:
                    pass

    def convert_ifc_to_rfa(ifc_path, rft_template, output_folder, log_cb):
        """
        Convertit un fichier IFC en RFA via OpenIFCDocument + SAT intermediaire.
        Retourne (True, rfa_path) ou (False, detail_erreur_complet).
        """
        name     = os.path.splitext(os.path.basename(ifc_path))[0]
        rfa_path = os.path.join(output_folder, name + u".rfa")
        try:
            _strategy_via_sat(ifc_path, rft_template, rfa_path, log_cb)
            return True, rfa_path
        except Exception as ex:
            return False, u"{}\n\n{}".format(str(ex), traceback.format_exc())

    # -------------------------------------------------------------------------
    # Modele de donnees
    # -------------------------------------------------------------------------
    class IfcRow(object):
        def __init__(self, ifc_path):
            self.IsSelected = True
            self.Nom        = os.path.splitext(os.path.basename(ifc_path))[0]
            self.Taille     = u"{:.1f} Ko".format(os.path.getsize(ifc_path) / 1024.0)
            self.Statut     = u"En attente"
            self._path      = ifc_path
            self._error     = u""  # detail complet en cas d'erreur

        def toggle(self):
            self.IsSelected = not self.IsSelected

    # -------------------------------------------------------------------------
    # XAML (ASCII strict -- accents assignes apres chargement)
    # -------------------------------------------------------------------------
    XAML = """<Window
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="900" Height="620" MinWidth="720" MinHeight="480"
        WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
          <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
        </Border>

        <Border Grid.Row="1" Background="#F0F6FF" BorderBrush="#C0D0E0"
                BorderThickness="0,0,0,1" Padding="10,8">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="110"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="85"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>

            <TextBlock x:Name="lbl_src" Grid.Row="0" Grid.Column="0"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,3,8,3"/>
            <TextBox x:Name="txt_src" Grid.Row="0" Grid.Column="1"
                     Height="24" FontSize="11" IsReadOnly="True"
                     Background="White" BorderBrush="#C0D0E0" Padding="4,2" Margin="0,3,4,3"
                     VerticalContentAlignment="Center"/>
            <Button x:Name="btn_src" Grid.Row="0" Grid.Column="2"
                    Height="24" FontSize="11"
                    Background="#3498DB" Foreground="White" BorderThickness="0" Margin="0,3,0,3"/>

            <TextBlock x:Name="lbl_out" Grid.Row="1" Grid.Column="0"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,3,8,3"/>
            <TextBox x:Name="txt_out" Grid.Row="1" Grid.Column="1"
                     Height="24" FontSize="11" IsReadOnly="True"
                     Background="White" BorderBrush="#C0D0E0" Padding="4,2" Margin="0,3,4,3"
                     VerticalContentAlignment="Center"/>
            <Button x:Name="btn_out" Grid.Row="1" Grid.Column="2"
                    Height="24" FontSize="11"
                    Background="#3498DB" Foreground="White" BorderThickness="0" Margin="0,3,0,3"/>

            <TextBlock x:Name="lbl_rft" Grid.Row="2" Grid.Column="0"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,3,8,3"/>
            <TextBox x:Name="txt_rft" Grid.Row="2" Grid.Column="1"
                     Height="24" FontSize="11" IsReadOnly="True"
                     Background="White" BorderBrush="#C0D0E0" Padding="4,2" Margin="0,3,4,3"
                     VerticalContentAlignment="Center"/>
            <Button x:Name="btn_rft" Grid.Row="2" Grid.Column="2"
                    Height="24" FontSize="11"
                    Background="#3498DB" Foreground="White" BorderThickness="0" Margin="0,3,0,3"/>
          </Grid>
        </Border>

        <Grid Grid.Row="2">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <Border Grid.Row="0" Background="#F5F5F5" BorderBrush="#C0D0E0"
                  BorderThickness="0,0,0,1" Padding="8,5">
            <StackPanel Orientation="Horizontal">
              <Button x:Name="btn_all" Width="90" Height="22" FontSize="11"
                      Background="#2ECC71" Foreground="White" BorderThickness="0" Margin="0,0,6,0"/>
              <Button x:Name="btn_none" Width="100" Height="22" FontSize="11"
                      Background="#E74C3C" Foreground="White" BorderThickness="0" Margin="0,0,12,0"/>
              <TextBlock x:Name="lbl_count" FontSize="11" VerticalAlignment="Center"
                         Foreground="#2F6496" FontWeight="SemiBold"/>
              <TextBlock x:Name="lbl_hint" FontSize="10" VerticalAlignment="Center"
                         Foreground="#888888" Margin="16,0,0,0"/>
            </StackPanel>
          </Border>
          <DataGrid x:Name="dg_main" Grid.Row="1"
                    AutoGenerateColumns="False" IsReadOnly="False"
                    AlternatingRowBackground="#E8F0FA" RowBackground="White"
                    GridLinesVisibility="Horizontal" BorderThickness="0"
                    HeadersVisibility="Column" CanUserResizeColumns="True" CanUserSortColumns="True"
                    FontSize="12" SelectionMode="Single">
            <DataGrid.ColumnHeaderStyle>
              <Style TargetType="DataGridColumnHeader">
                <Setter Property="Background" Value="#D0E4F7"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
                <Setter Property="Padding" Value="6,3"/>
              </Style>
            </DataGrid.ColumnHeaderStyle>
            <DataGrid.Columns>
              <DataGridCheckBoxColumn x:Name="col_sel" Binding="{Binding IsSelected}"
                                      Width="36" SortMemberPath="IsSelected"/>
              <DataGridTextColumn x:Name="col_nom" Binding="{Binding Nom}"
                                  Width="*" IsReadOnly="True"/>
              <DataGridTextColumn x:Name="col_taille" Binding="{Binding Taille}"
                                  Width="90" IsReadOnly="True"/>
              <DataGridTextColumn x:Name="col_statut" Binding="{Binding Statut}"
                                  Width="130" IsReadOnly="True"/>
            </DataGrid.Columns>
          </DataGrid>
        </Grid>

        <Border Grid.Row="3" Background="#F0F6FF" BorderBrush="#C0D0E0"
                BorderThickness="0,1,0,0" Padding="10,6">
          <StackPanel>
            <TextBlock x:Name="lbl_prog" FontSize="11" Foreground="#2F6496" Margin="0,0,0,4"/>
            <ProgressBar x:Name="pb_main" Height="10" Minimum="0" Maximum="100" Value="0"
                         Background="#E0E0E0" Foreground="#2ECC71"/>
          </StackPanel>
        </Border>

        <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,6">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="8,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
              <Button x:Name="btn_convert" Width="110" Height="28"
                      Background="#2ECC71" Foreground="White" FontWeight="SemiBold"
                      BorderThickness="0" Margin="0,0,6,0" IsEnabled="False"/>
              <Button x:Name="btn_close" Width="90" Height="28"
                      Background="#E74C3C" Foreground="White" FontWeight="SemiBold"
                      BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    # -------------------------------------------------------------------------
    # Main
    # -------------------------------------------------------------------------
    def main():
        prefs = load_prefs()
        rows  = []

        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        win    = System.Windows.Markup.XamlReader.Load(stream)
        win.Title = TOOL_NAME

        win.FindName("lbl_titre").Text   = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        win.FindName("lbl_footer").Text  = _FOOTER
        win.FindName("lbl_src").Text     = u"Dossier IFC :"
        win.FindName("lbl_out").Text     = u"Dossier sortie :"
        win.FindName("lbl_rft").Text     = u"Gabarit (.rft) :"
        win.FindName("lbl_hint").Text    = u"Double-clic sur ERREUR pour voir le detail"
        win.FindName("btn_src").Content  = u"Parcourir..."
        win.FindName("btn_out").Content  = u"Parcourir..."
        win.FindName("btn_rft").Content  = u"Parcourir..."
        win.FindName("btn_all").Content  = u"Tout cocher"
        win.FindName("btn_none").Content = u"Tout decocher"
        win.FindName("btn_convert").Content = u"Convertir"
        win.FindName("btn_close").Content   = u"Fermer"

        col_sel    = win.FindName("col_sel")
        col_nom    = win.FindName("col_nom")
        col_taille = win.FindName("col_taille")
        col_statut = win.FindName("col_statut")
        if col_sel    is not None: col_sel.Header    = u""
        if col_nom    is not None: col_nom.Header    = u"Nom du fichier IFC"
        if col_taille is not None: col_taille.Header = u"Taille"
        if col_statut is not None: col_statut.Header = u"Statut"

        txt_src     = win.FindName("txt_src")
        txt_out     = win.FindName("txt_out")
        txt_rft     = win.FindName("txt_rft")
        dg          = win.FindName("dg_main")
        lbl_count   = win.FindName("lbl_count")
        btn_convert = win.FindName("btn_convert")
        lbl_prog    = win.FindName("lbl_prog")
        pb          = win.FindName("pb_main")

        if prefs.get("src_folder"):    txt_src.Text = prefs["src_folder"]
        if prefs.get("out_folder"):    txt_out.Text = prefs["out_folder"]
        if prefs.get("rft_template"):  txt_rft.Text = prefs["rft_template"]

        def _refresh_dg():
            dg.ItemsSource = None
            dg.ItemsSource = rows

        def _update_count():
            sel = sum(1 for r in rows if r.IsSelected)
            lbl_count.Text = u"{} fichier(s) IFC  |  {} selectionne(s)".format(len(rows), sel)

        def _update_btn():
            ok = (bool(txt_src.Text.strip()) and
                  bool(txt_out.Text.strip()) and
                  bool(txt_rft.Text.strip()) and
                  any(r.IsSelected for r in rows))
            btn_convert.IsEnabled = ok

        def _scan_ifc():
            src = txt_src.Text.strip()
            rows[:] = []
            if src and os.path.isdir(src):
                for f in sorted(os.listdir(src)):
                    if f.lower().endswith(u".ifc"):
                        rows.append(IfcRow(os.path.join(src, f)))
            _refresh_dg()
            _update_count()
            _update_btn()

        def on_src(s, e):
            folder = browse_folder(txt_src.Text)
            if folder:
                txt_src.Text = folder
                prefs["src_folder"] = folder
                save_prefs(prefs)
                _scan_ifc()

        def on_out(s, e):
            folder = browse_folder(txt_out.Text)
            if folder:
                txt_out.Text = folder
                prefs["out_folder"] = folder
                save_prefs(prefs)
                _update_btn()

        def on_rft(s, e):
            rft = browse_rft(txt_rft.Text)
            if rft:
                txt_rft.Text = rft
                prefs["rft_template"] = rft
                save_prefs(prefs)
                _update_btn()

        def on_all(s, e):
            for r in rows: r.IsSelected = True
            _refresh_dg(); _update_count(); _update_btn()

        def on_none(s, e):
            for r in rows: r.IsSelected = False
            _refresh_dg(); _update_count(); _update_btn()

        def on_cell_changed(s, e):
            if dg.CurrentColumn and dg.CurrentColumn.DisplayIndex == 0:
                if dg.CurrentItem:
                    dg.CurrentItem.toggle()
                _refresh_dg(); _update_count(); _update_btn()

        def on_double_click(s, e):
            row = dg.SelectedItem
            if row is None:
                return
            if row.Statut == u"ERREUR" and row._error:
                show_error_detail(row.Nom, row._error)

        def on_convert(s, e):
            selected = [r for r in rows if r.IsSelected]
            if not selected:
                return

            rft   = txt_rft.Text.strip()
            out   = txt_out.Text.strip()
            total = len(selected)

            if not os.path.isfile(rft):
                MessageBox.Show(u"Gabarit .rft introuvable :\n" + rft,
                                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
                return

            if not os.path.isdir(out):
                try:
                    os.makedirs(out)
                except Exception as ex_mkdir:
                    MessageBox.Show(u"Impossible de creer le dossier de sortie :\n" + str(ex_mkdir),
                                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
                    return

            btn_convert.IsEnabled               = False
            win.FindName("btn_close").IsEnabled = False
            nb_ok  = 0
            nb_err = 0
            dispatcher = win.Dispatcher

            for i, row in enumerate(selected):
                pb.Value      = int(100.0 * i / total)
                lbl_prog.Text = u"[{}/{}]  {}".format(i + 1, total, row.Nom)
                row.Statut    = u"En cours..."
                row._error    = u""
                _refresh_dg()
                do_events(dispatcher)

                def _log(msg, _row=row, _i=i, _total=total):
                    lbl_prog.Text = u"[{}/{}]  {}  --  {}".format(_i + 1, _total, _row.Nom, msg)
                    do_events(dispatcher)

                ok, result = convert_ifc_to_rfa(row._path, rft, out, _log)

                if ok:
                    row.Statut = u"OK"
                    nb_ok += 1
                else:
                    row.Statut = u"ERREUR"
                    row._error = result
                    nb_err += 1
                    lbl_prog.Text = u"Erreur sur {} (double-clic pour details)".format(row.Nom)

                _refresh_dg()
                do_events(dispatcher)

            pb.Value      = 100
            lbl_prog.Text = u"Termine : {} OK  |  {} erreur(s)".format(nb_ok, nb_err)
            win.FindName("btn_close").IsEnabled = True
            _update_btn()

            icon = MessageBoxImage.Information if nb_err == 0 else MessageBoxImage.Warning
            hint = u"\nDouble-cliquez sur une ligne ERREUR pour voir le detail." if nb_err > 0 else u""
            MessageBox.Show(
                u"Conversion terminee !\n\n{} famille(s) creee(s)\n{} erreur(s){}".format(
                    nb_ok, nb_err, hint),
                TOOL_NAME, MessageBoxButton.OK, icon)

        win.FindName("btn_src").Click         += on_src
        win.FindName("btn_out").Click         += on_out
        win.FindName("btn_rft").Click         += on_rft
        win.FindName("btn_all").Click         += on_all
        win.FindName("btn_none").Click        += on_none
        btn_convert.Click                     += on_convert
        win.FindName("btn_close").Click       += lambda s, e: win.Close()
        dg.CurrentCellChanged                 += on_cell_changed
        dg.MouseDoubleClick                   += on_double_click

        _scan_ifc()
        win.ShowDialog()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} -- Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
