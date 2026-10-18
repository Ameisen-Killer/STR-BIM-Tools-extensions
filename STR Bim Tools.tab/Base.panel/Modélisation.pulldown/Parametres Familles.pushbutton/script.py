# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Parametres Familles"
# =============================================================================

import re, sys, os, io, json, traceback, clr
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
    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase"); clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")
    import System, System.IO, System.Text, System.Windows.Markup, System.Diagnostics
    import System.Windows.Forms as WinForms
    import System.Windows.Controls as WpfControls
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode, TextWrapping,
                                FontWeights)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, RowDefinition,
                                         DataGridSelectionMode, TextBox, Orientation)
    from System.Windows.Data  import Binding
    from System.Windows.Media import SolidColorBrush, Color
    from System.Collections.ObjectModel import ObservableCollection
    from Autodesk.Revit.DB import (Family, FamilyInstance, FamilySymbol, StorageType,
                                   UnitUtils, ElementId, Element, Transaction, TransactionStatus)

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app   = __revit__.Application

    _FOOTER    = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    # =========================================================================
    # Helpers export
    # =========================================================================
    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return {}

    def _save_prefs(data):
        try:
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception: pass

    def pick_folder(title=u"Choisir un dossier"):
        try:
            prefs = _load_prefs()
            dlg = WinForms.FolderBrowserDialog(); dlg.Description = title
            last = prefs.get("last_export_folder", u"")
            if last and os.path.isdir(last): dlg.SelectedPath = last
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                prefs["last_export_folder"] = dlg.SelectedPath
                _save_prefs(prefs)
                return dlg.SelectedPath
        except Exception: pass
        return None

    def _hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)))

    def _footer_btn(text, color, width, handler):
        b = Button(); b.Content = text; b.Width = width; b.Height = 28
        b.Background = _hex_brush(color); b.Foreground = _hex_brush("#FFFFFF")
        b.FontWeight = FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler; return b

    def _make_footer_brd(version):
        brd = Border(); brd.BorderThickness = Thickness(0,1,0,0)
        brd.BorderBrush = _hex_brush("#C0D0E0"); brd.Background = _hex_brush("#F5F5F5")
        brd.Padding = Thickness(0,6,0,6)
        g = Grid()
        lbl = TextBlock(); lbl.Text = u"v{} | STR BIM Tools by Tony Varin".format(version)
        lbl.FontSize = 10; lbl.Foreground = _hex_brush("#888888")
        lbl.VerticalAlignment = VerticalAlignment.Center; lbl.Margin = Thickness(10,0,0,0)
        g.Children.Add(lbl)
        sp = StackPanel(); sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Right; sp.Margin = Thickness(0,0,10,0)
        brd.Child = g; return brd, sp, g

    def _rd_local(h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto)
        return rd

    def _ask_filename(folder, default_name):
        result = {"path": None}
        d = Window(); d.Title = TOOL_NAME; d.Width = 460; d.Height = 195
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = _hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]: droot.RowDefinitions.Add(_rd_local(h))
        d.Content = droot
        hdr = Border(); hdr.Background = _hex_brush("#2F6496"); hdr.Padding = Thickness(14,7,14,7)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        hdr_tb = TextBlock(); hdr_tb.Text = u"Fichier existant — choisir un nom"
        hdr_tb.FontSize = 12; hdr_tb.FontWeight = FontWeights.SemiBold
        hdr_tb.Foreground = _hex_brush("#FFFFFF"); hdr.Child = hdr_tb
        body = StackPanel(); body.Margin = Thickness(16,12,16,8)
        Grid.SetRow(body, 1); droot.Children.Add(body)
        lbl_w = TextBlock()
        lbl_w.Text = u"Le fichier \"{}\" existe déjà dans ce dossier.".format(default_name)
        lbl_w.FontSize = 11; lbl_w.Foreground = _hex_brush("#E74C3C")
        lbl_w.TextWrapping = TextWrapping.Wrap; lbl_w.Margin = Thickness(0,0,0,8)
        body.Children.Add(lbl_w)
        lbl_h = TextBlock(); lbl_h.Text = u"Nouveau nom de fichier (sans extension) :"
        lbl_h.FontSize = 10; lbl_h.Foreground = _hex_brush("#555555"); lbl_h.Margin = Thickness(0,0,0,4)
        body.Children.Add(lbl_h)
        txt = TextBox(); txt.FontSize = 11; txt.Height = 26; txt.Padding = Thickness(4,2,4,2)
        txt.BorderBrush = _hex_brush("#C0D0E0"); txt.BorderThickness = Thickness(1)
        txt.Text = os.path.splitext(default_name)[0] + u"_1"; txt.SelectAll()
        body.Children.Add(txt)
        lbl_err = TextBlock(); lbl_err.FontSize = 10; lbl_err.Foreground = _hex_brush("#E74C3C")
        lbl_err.Margin = Thickness(0,3,0,0); body.Children.Add(lbl_err)
        dfooter, dsp, dgf = _make_footer_brd(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)
        def _on_ok(s, e):
            name = txt.Text.strip()
            if not name: lbl_err.Text = u"Le nom ne peut pas être vide."; return
            final = name if name.lower().endswith(".xlsx") else name + ".xlsx"
            final_path = os.path.join(folder, final)
            if os.path.exists(final_path): lbl_err.Text = u"Ce fichier existe aussi. Choisissez un autre nom."; return
            result["path"] = final_path; d.Close()
        btn_c = _footer_btn(u"Annuler", "#E74C3C", 90, lambda s,e: d.Close())
        btn_o = _footer_btn(u"Exporter", "#E67E22", 90, _on_ok)
        btn_c.Margin = Thickness(0,0,6,0)
        dsp.Children.Add(btn_c); dsp.Children.Add(btn_o); dgf.Children.Add(dsp)
        txt.KeyDown += lambda s,e: (_on_ok(s,e) if e.Key == System.Windows.Input.Key.Return else None)
        d.ShowDialog()
        return result["path"]

    def _show_export_success(path):
        d = Window(); d.Title = TOOL_NAME; d.Width = 400; d.Height = 155
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = _hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["*", "Auto"]: droot.RowDefinitions.Add(_rd_local(h))
        d.Content = droot
        body = StackPanel(); body.Margin = Thickness(16,14,16,8)
        Grid.SetRow(body, 0); droot.Children.Add(body)
        tb1 = TextBlock(); tb1.Text = u"Export réussi :"
        tb1.FontSize = 11; tb1.FontWeight = FontWeights.SemiBold
        tb1.Foreground = _hex_brush("#2F6496"); tb1.Margin = Thickness(0,0,0,4)
        body.Children.Add(tb1)
        tb2 = TextBlock(); tb2.Text = path; tb2.FontSize = 10
        tb2.Foreground = _hex_brush("#444444"); tb2.TextWrapping = TextWrapping.Wrap
        body.Children.Add(tb2)
        dfooter, dsp, dgf = _make_footer_brd(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 1); droot.Children.Add(dfooter)
        def _open_folder(s, e):
            try:
                psi = System.Diagnostics.ProcessStartInfo()
                psi.FileName = "explorer.exe"
                psi.Arguments = u'"{}"'.format(os.path.dirname(path))
                System.Diagnostics.Process.Start(psi)
            except Exception: pass
            d.Close()
        btn_open = _footer_btn(u"Ouvrir le dossier", "#E67E22", 130, _open_folder)
        btn_ok   = _footer_btn(u"OK",                "#3498DB",  60, lambda s,e: d.Close())
        btn_open.Margin = Thickness(0,0,6,0)
        dsp.Children.Add(btn_open); dsp.Children.Add(btn_ok); dgf.Children.Add(dsp)
        d.ShowDialog()

    # =========================================================================
    # Configuration des paramètres
    # =========================================================================
    EDITABLE_PARAM_NAMES = [
        u"Modèle",
        u"#STR_Masse linéaire",
        u"#STR_Masse volumique",
        u"#STR_Nuance acier",
    ]
    READONLY_PARAM_NAMES = [
        u"Hauteur",
        u"Largeur",
    ]

    # =========================================================================
    # XAML — ASCII strict, accents assignés après XamlReader.Load()
    # =========================================================================
    XAML = """<Window
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="1020" Height="600"
        MinWidth="700" MinHeight="380"
        WindowStartupLocation="CenterScreen"
        Background="White" ResizeMode="CanResize">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Barre titre bleue -->
        <Border Grid.Row="0" Background="#2F6496" Padding="14,9,14,9">
          <StackPanel>
            <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold"
                       Foreground="White"/>
            <TextBlock x:Name="lbl_family" FontSize="10" Foreground="#C8DFF0"
                       Margin="0,3,0,0"/>
          </StackPanel>
        </Border>

        <!-- DataGrid -->
        <DataGrid x:Name="dg_main" Grid.Row="1" Margin="8,8,8,4"
                  AutoGenerateColumns="False" IsReadOnly="False"
                  AlternatingRowBackground="#E8F0FA" RowBackground="White"
                  GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
                  HeadersVisibility="Column"
                  CanUserResizeColumns="True" CanUserSortColumns="True"
                  SelectionMode="Single" FontSize="12">
          <DataGrid.ColumnHeaderStyle>
            <Style TargetType="DataGridColumnHeader">
              <Setter Property="Background" Value="#D0E4F7"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
              <Setter Property="Padding" Value="6,3"/>
            </Style>
          </DataGrid.ColumnHeaderStyle>
        </DataGrid>

        <!-- Footer -->
        <Border Grid.Row="2" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,4">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="8,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal"
                        Margin="0,0,8,0">
              <Button x:Name="btn_cancel" Width="90" Height="26" Margin="4,0,0,0"
                      Background="#E74C3C" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
              <Button x:Name="btn_apply"  Width="90" Height="26" Margin="4,0,0,0"
                      Background="#2ECC71" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
              <Button x:Name="btn_xlsx"   Width="115" Height="26" Margin="4,0,0,0"
                      Background="#E67E22" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
              <Button x:Name="btn_close"  Width="90" Height="26" Margin="4,0,0,0"
                      Background="#3498DB" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    # =========================================================================
    # Helpers Revit
    # =========================================================================
    def get_selected_family_symbol():
        sel_ids = uidoc.Selection.GetElementIds()
        if not sel_ids: return None
        for eid in sel_ids:
            elem = doc.GetElement(eid)
            if not elem: continue
            if isinstance(elem, FamilyInstance):
                sym = doc.GetElement(elem.GetTypeId())
                if sym and isinstance(sym, FamilySymbol): return sym
            if isinstance(elem, FamilySymbol): return elem
        return None

    def get_elem_name(elem):
        try: return Element.Name.GetValue(elem) or u""
        except: return u""

    def get_param_value(symbol, param_name):
        p = symbol.LookupParameter(param_name)
        if p is None: return u"-"
        st = p.StorageType
        if st == StorageType.Double:
            try:
                val = UnitUtils.ConvertFromInternalUnits(p.AsDouble(), p.GetUnitTypeId())
                return u"{:.4g}".format(val)
            except: return u"{:.4g}".format(p.AsDouble())
        elif st == StorageType.Integer: return str(p.AsInteger())
        elif st == StorageType.String:
            v = p.AsString(); return v if v else u"-"
        elif st == StorageType.ElementId:
            eid = p.AsElementId()
            if eid == ElementId.InvalidElementId: return u"-"
            e = doc.GetElement(eid)
            if e is None: return str(eid.IntegerValue)
            try: return e.Name
            except: return str(eid.IntegerValue)
        return u"-"

    def validate_and_convert(symbol, param_name, str_value):
        p = symbol.LookupParameter(param_name)
        if p is None:
            return False, u"Paramètre '{}' introuvable sur ce type.".format(param_name)
        if p.IsReadOnly:
            return False, u"Paramètre '{}' est en lecture seule.".format(param_name)
        st = p.StorageType
        str_value = str_value.strip()
        if st == StorageType.Double:
            str_value = str_value.replace(u",", u".")
            try: display_val = float(str_value)
            except ValueError:
                return False, u"'{}' n'est pas un nombre valide pour '{}'.".format(str_value, param_name)
            try: internal_val = UnitUtils.ConvertToInternalUnits(display_val, p.GetUnitTypeId())
            except: internal_val = display_val
            return True, internal_val
        elif st == StorageType.Integer:
            try: return True, int(str_value)
            except ValueError:
                return False, u"'{}' n'est pas un entier valide pour '{}'.".format(str_value, param_name)
        elif st == StorageType.String:
            return True, str_value
        return False, u"Type de stockage non supporté pour '{}'.".format(param_name)

    def set_param_value(symbol, param_name, internal_value):
        p = symbol.LookupParameter(param_name)
        st = p.StorageType
        if   st == StorageType.Double:  p.Set(internal_value)
        elif st == StorageType.Integer: p.Set(internal_value)
        elif st == StorageType.String:  p.Set(internal_value)

    def natural_sort_key(elem):
        name  = get_elem_name(elem)
        parts = re.split(r'([\d]+(?:[.,][\d]+)?)', name)
        key   = []
        for part in parts:
            if part == u'': continue
            try:
                fval     = float(part.replace(u',', u'.'))
                int_part = int(fval)
                dec_part = int(round((fval - int_part) * 1e9))
                key.append(u'N' + str(int_part).zfill(20) + str(dec_part).zfill(9))
            except ValueError:
                key.append(u'T' + part.upper())
        return key

    def get_all_types_for_family(family):
        symbols = []
        for sid in family.GetFamilySymbolIds():
            sym = doc.GetElement(sid)
            if sym: symbols.append(sym)
        symbols.sort(key=natural_sort_key)
        return symbols

    # =========================================================================
    # Modèle de données
    # =========================================================================
    def param_attr(pname):
        return pname.replace(u"#", u"").replace(u" ", u"_")

    class TypeRow(object):
        def __init__(self, symbol):
            self.ElementId = symbol.Id
            self.TypeName  = get_elem_name(symbol) or u"Inconnu"
            for pname in READONLY_PARAM_NAMES + EDITABLE_PARAM_NAMES:
                setattr(self, param_attr(pname), get_param_value(symbol, pname))

    # =========================================================================
    # Point d'entrée
    # =========================================================================
    def main():
        sym = get_selected_family_symbol()
        if not sym:
            MessageBox.Show(
                u"Sélectionne un élément structurel dans le modèle\n"
                u"(Poutre, Poteau, etc.) puis relance l'outil.",
                u"Aucune sélection", MessageBoxButton.OK, MessageBoxImage.Information)
            return

        family  = sym.Family
        f_name  = get_elem_name(family) or u"Famille sans nom"
        symbols = get_all_types_for_family(family)

        rows = []
        for s in symbols:
            try: rows.append(TypeRow(s))
            except Exception: pass

        if not rows:
            MessageBox.Show(
                u"Aucun type trouvé pour la famille : {}".format(f_name),
                u"Famille vide", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        # --- Chargement XAML ---
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)

        # --- Titre, sous-titre, footer ---
        window.Title = TOOL_NAME
        window.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        window.FindName("lbl_family").Text = u"Famille : {}   •   {} type(s)".format(f_name, len(rows))
        window.FindName("lbl_footer").Text = _FOOTER
        window.FindName("btn_apply").Content  = u"Appliquer"
        window.FindName("btn_cancel").Content = u"Annuler"
        window.FindName("btn_xlsx").Content   = u"Exporter XLSX"
        window.FindName("btn_close").Content  = u"Fermer"

        # --- Construction colonnes DataGrid ---
        dg = window.FindName("dg_main")

        col_name = DataGridTextColumn()
        col_name.Header     = u"Nom du type"
        col_name.Binding    = Binding(u"TypeName")
        col_name.IsReadOnly = True
        col_name.Width      = WpfControls.DataGridLength(200, WpfControls.DataGridLengthUnitType.Pixel)
        dg.Columns.Add(col_name)

        editable_set = set(EDITABLE_PARAM_NAMES)
        col_order    = EDITABLE_PARAM_NAMES[:1] + READONLY_PARAM_NAMES + EDITABLE_PARAM_NAMES[1:]
        for pname in col_order:
            is_edit = pname in editable_set
            col = DataGridTextColumn()
            col.Header     = u"[Edit] {}".format(pname) if is_edit else pname
            col.Binding    = Binding(param_attr(pname))
            col.IsReadOnly = not is_edit
            col.Width      = WpfControls.DataGridLength(1, WpfControls.DataGridLengthUnitType.Star)
            dg.Columns.Add(col)

        items = ObservableCollection[object]()
        for row in rows: items.Add(row)
        dg.ItemsSource = items

        lbl_footer = window.FindName("lbl_footer")

        # --- Appliquer ---
        def on_apply(sender, e):
            dg.CommitEdit(WpfControls.DataGridEditingUnit.Row, True)
            sym_map = {s.Id: s for s in symbols}
            errors, writes = [], []
            for row in list(dg.ItemsSource):
                s = sym_map.get(row.ElementId)
                if s is None: continue
                for pname in EDITABLE_PARAM_NAMES:
                    new_str  = getattr(row, param_attr(pname), u"")
                    orig_str = get_param_value(s, pname)
                    if new_str == orig_str: continue
                    ok, result = validate_and_convert(s, pname, new_str)
                    if not ok: errors.append(u"[{}] {} : {}".format(row.TypeName, pname, result))
                    else:      writes.append((s, pname, result))

            if errors:
                MessageBox.Show(
                    u"Correction requise avant d'appliquer :\n\n" + u"\n".join(errors),
                    u"Valeurs invalides", MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            if not writes:
                lbl_footer.Text      = u"Aucune modification détectée."
                lbl_footer.Foreground = SolidColorBrush(Color.FromRgb(136, 136, 136))
                return

            t = Transaction(doc, u"STR - Edition paramètres types [v{}]".format(SCRIPT_VERSION))
            try:
                t.Start()
                for s, pname, val in writes:
                    set_param_value(s, pname, val)
                if t.GetStatus() == TransactionStatus.Started: t.Commit()
                lbl_footer.Text = u"{} modification(s) appliquée(s)  ✓  |  {}".format(len(writes), _FOOTER)
                lbl_footer.Foreground = SolidColorBrush(Color.FromRgb(0, 130, 60))
            except Exception as ex:
                if t.GetStatus() == TransactionStatus.Started: t.RollBack()
                MessageBox.Show(
                    u"Erreur — transaction annulée.\n\n{}".format(str(ex)),
                    u"Rollback", MessageBoxButton.OK, MessageBoxImage.Error)

        # --- Annuler ---
        def on_cancel(sender, e):
            sym_map = {s.Id: s for s in symbols}
            for row in list(dg.ItemsSource):
                s = sym_map.get(row.ElementId)
                if s is None: continue
                for pname in EDITABLE_PARAM_NAMES:
                    setattr(row, param_attr(pname), get_param_value(s, pname))
            src = ObservableCollection[object]()
            for row in rows: src.Add(row)
            dg.ItemsSource = src
            lbl_footer.Text      = u"Modifications annulées.  |  {}".format(_FOOTER)
            lbl_footer.Foreground = SolidColorBrush(Color.FromRgb(180, 40, 40))

        # --- Exporter XLSX ---
        def on_xlsx(sender, e):
            folder = pick_folder(u"Dossier pour l'export XLSX")
            if not folder: return
            try: import xlsxwriter
            except Exception:
                MessageBox.Show(u"Le module xlsxwriter n'est pas disponible.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Error); return
            default_name = u"parametres_familles_{}.xlsx".format(
                re.sub(r'[\\/:*?"<>|]', u"_", f_name))
            if os.path.exists(os.path.join(folder, default_name)):
                path = _ask_filename(folder, default_name)
                if not path: return
            else:
                path = os.path.join(folder, default_name)
            try:
                wb  = xlsxwriter.Workbook(path)
                ws  = wb.add_worksheet(u"Parametres")
                fmt_hdr = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                          "font_color": "#FFFFFF", "border": 1,
                                          "font_name": "Calibri", "align": "center"})
                fmt_ro  = wb.add_format({"bg_color": "#EEF2F7", "font_name": "Calibri",
                                          "border": 1, "italic": True})
                fmt_edit= wb.add_format({"font_name": "Calibri", "border": 1})
                fmt_alt = wb.add_format({"bg_color": "#E8F0FA", "font_name": "Calibri", "border": 1})
                fmt_alt_ro = wb.add_format({"bg_color": "#DDE5F0", "font_name": "Calibri",
                                             "border": 1, "italic": True})

                col_order = [u"Nom du type"] + EDITABLE_PARAM_NAMES[:1] + READONLY_PARAM_NAMES + EDITABLE_PARAM_NAMES[1:]
                ws.write_row(0, 0, col_order, fmt_hdr)
                ws.set_column(0, 0, 28)
                for ci in range(1, len(col_order)):
                    ws.set_column(ci, ci, 20)
                ws.freeze_panes(1, 1)

                editable_set = set(EDITABLE_PARAM_NAMES)
                for ri, row in enumerate(list(dg.ItemsSource), start=1):
                    alt = (ri % 2 == 0)
                    ws.write(ri, 0, row.TypeName, fmt_alt if alt else fmt_edit)
                    for ci, pname in enumerate(col_order[1:], start=1):
                        raw = getattr(row, param_attr(pname), u"-")
                        is_ro = pname not in editable_set
                        fmt = (fmt_alt_ro if alt else fmt_ro) if is_ro else (fmt_alt if alt else fmt_edit)
                        # Convertir en nombre si possible
                        cell_val = raw
                        if raw and raw != u"-":
                            clean = raw.strip().replace(u" ", u"").replace(u" ", u"")
                            try: cell_val = int(clean)
                            except (ValueError, TypeError):
                                try: cell_val = float(clean.replace(u",", u"."))
                                except (ValueError, TypeError): pass
                        ws.write(ri, ci, cell_val, fmt)

                wb.close()
                _show_export_success(path)
            except Exception as ex:
                MessageBox.Show(u"Export XLSX échoué :\n{}".format(ex), TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Error)

        window.FindName("btn_apply").Click  += on_apply
        window.FindName("btn_cancel").Click += on_cancel
        window.FindName("btn_xlsx").Click   += on_xlsx
        window.FindName("btn_close").Click  += lambda s, e: window.Close()

        window.ShowDialog()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
