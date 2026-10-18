# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.6.0"
SCRIPT_AUTHOR  = "Tony Varin"
TOOL_NAME      = u"Export Nomenclatures"
# =============================================================================
#  v2.6.0 — Avertissement si fichier existant : propose d'ecraser ou de renommer.
#  v2.5.0 — Valeurs numeriques ecrites comme nombres dans Excel (pas comme texte).
#  v2.4.1 — Titre fenetre OS = TOOL_NAME uniquement (version dans footer uniquement).
#  v2.4.0 — Filtre nomenclatures systeme (noms commencant par "<" : revisions, legendes).
#  v2.3.0 — Suppression NbCols dans ScheduleRow.__init__ : GetTableData() sur
#           chaque nomenclature au chargement du dialog causait crash sur gros projets.
#  v2.2.0 — Filet de securite global via TaskDialog (natif Revit, sans WPF),
#           suppression nowindow, tous les imports dans le try/except principal.
#  v2.1.0 — FindName colonnes via window, try/except global.
#  v2.0.0 — Refonte WPF complete (charte STR BIM Tools), prefs.json.
#  v1.4.0 — Export Excel xlsxwriter, ProgressBar pyRevit natif.
# =============================================================================

# Seuls imports hors du filet — indispensables pour afficher l'erreur de chargement
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent       = u"Erreur : " + str(ex)
    td.ExpandedContent   = traceback.format_exc()
    td.CommonButtons     = TaskDialogCommonButtons.Close
    td.Show()

try:
    import os, io, json, datetime, subprocess

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System.Windows.Forms")

    import System
    import System.IO
    import System.Text
    import System.Windows.Markup
    from System.Collections.Generic import List
    from System.Windows.Forms import FolderBrowserDialog, DialogResult
    from System.Windows.Threading import DispatcherPriority
    import System.Windows as SW
    import System.Windows.Controls as SWC
    from System.Windows import (
        Thickness, GridLength, GridUnitType, Window,
        MessageBox, MessageBoxButton, MessageBoxImage,
    )
    from System.Windows.Controls import (
        Grid, StackPanel, Border, TextBlock, Button,
        ScrollViewer, ProgressBar,
        RowDefinition, ColumnDefinition, Orientation,
        TextBox,
    )
    from System.Windows.Media import SolidColorBrush, Color, FontFamily

    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        ViewSchedule,
        SectionType,
    )

    import xlsxwriter  # natif pyRevit

    doc = __revit__.ActiveUIDocument.Document
    app = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # Persistance du dernier dossier
    # =========================================================================
    _PREFS_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    def load_last_folder():
        try:
            if os.path.isfile(_PREFS_FILE):
                with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                folder = data.get("last_folder", u"")
                if folder and os.path.isdir(folder):
                    return folder
        except Exception:
            pass
        return None

    def save_last_folder(folder):
        try:
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_folder": folder}, f, ensure_ascii=False)
        except Exception:
            pass

    # =========================================================================
    # Helpers couleur / UI
    # =========================================================================
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        ))

    def _rd_auto():
        rd = RowDefinition(); rd.Height = GridLength.Auto; return rd

    def do_events(dispatcher):
        try:
            dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
        except Exception:
            pass

    # =========================================================================
    # Collecte des nomenclatures
    # =========================================================================
    def get_all_schedules():
        collector = FilteredElementCollector(doc).OfClass(ViewSchedule)
        result = []
        for vs in collector:
            try:
                if vs.IsTemplate:
                    continue
                if vs.Definition.IsKeySchedule:
                    continue
                if vs.Name.startswith(u"<"):  # nomenclatures systeme (revisions, legendes...)
                    continue
                result.append(vs)
            except Exception:
                pass
        return sorted(result, key=lambda x: x.Name)

    # =========================================================================
    # Extraction des donnees
    # =========================================================================
    def schedule_to_data(schedule):
        table_data   = schedule.GetTableData()
        section_data = table_data.GetSectionData(SectionType.Body)
        n_rows = section_data.NumberOfRows
        n_cols = section_data.NumberOfColumns
        headers = []
        rows    = []
        for r in range(n_rows):
            row = []
            for c in range(n_cols):
                try:
                    cell_text = schedule.GetCellText(SectionType.Body, r, c)
                except Exception:
                    cell_text = u""
                row.append(cell_text)
            if r == 0:
                headers = row
            else:
                rows.append(row)
        return headers, rows

    # =========================================================================
    # Export Excel
    # =========================================================================
    def _cell_value(text):
        """Convertit une chaine en nombre si possible, sinon retourne le texte."""
        if not text:
            return u""
        # Normaliser separateur decimal (espace milliers + virgule decimale)
        clean = text.strip().replace(u" ", u"").replace(u"\xa0", u"").replace(u" ", u"")
        # Essai entier
        try:
            return int(clean)
        except (ValueError, TypeError):
            pass
        # Essai float (virgule ou point comme separateur decimal)
        try:
            return float(clean.replace(u",", u"."))
        except (ValueError, TypeError):
            pass
        return text

    def sanitize_sheet_name(name):
        for ch in ['\\', '/', '*', '?', ':', '[', ']']:
            name = name.replace(ch, '_')
        return name[:31]

    def export_to_excel(schedules_data, output_path):
        wb = xlsxwriter.Workbook(output_path)
        fmt_hdr = wb.add_format({
            "bold": True, "bg_color": "#2F6496", "font_color": "#FFFFFF",
            "border": 1, "align": "center", "valign": "vcenter",
            "text_wrap": True, "font_name": "Arial", "font_size": 9,
        })
        fmt_cell = wb.add_format({
            "border": 1, "valign": "vcenter",
            "font_name": "Arial", "font_size": 9,
        })
        fmt_alt = wb.add_format({
            "border": 1, "valign": "vcenter", "bg_color": "#E8F0FA",
            "font_name": "Arial", "font_size": 9,
        })
        fmt_sum_lbl = wb.add_format({"bold": True,  "font_name": "Arial", "font_size": 10})
        fmt_sum_val = wb.add_format({"font_name": "Arial", "font_size": 10})

        ws_sum = wb.add_worksheet(u"Resume")
        ws_sum.set_column(0, 0, 28)
        ws_sum.set_column(1, 1, 55)
        infos = [
            (u"Projet",                  doc.Title or u""),
            (u"Fichier Revit",           doc.PathName or u"Non sauvegarde"),
            (u"Nomenclatures exportees", str(len(schedules_data))),
            (u"Date export",             datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
            (u"Version script",          SCRIPT_VERSION),
        ]
        for r, (lbl, val) in enumerate(infos):
            ws_sum.write(r, 0, lbl, fmt_sum_lbl)
            ws_sum.write(r, 1, val, fmt_sum_val)

        used_names = {}
        for name, headers, rows in schedules_data:
            sheet_name = sanitize_sheet_name(name)
            if sheet_name in used_names:
                used_names[sheet_name] += 1
                sheet_name = u"{}_{:02d}".format(sheet_name[:28], used_names[sheet_name])
            else:
                used_names[sheet_name] = 0
            ws = wb.add_worksheet(sheet_name)
            ws.freeze_panes(1, 0)
            ws.set_row(0, 30)
            for col_idx, header in enumerate(headers):
                ws.write(0, col_idx, header, fmt_hdr)
            for row_idx, row in enumerate(rows, start=1):
                fmt = fmt_alt if row_idx % 2 == 0 else fmt_cell
                for col_idx, value in enumerate(row):
                    ws.write(row_idx, col_idx, _cell_value(value), fmt)
            for col_idx, header in enumerate(headers):
                max_len = len(str(header))
                for row in rows:
                    if col_idx < len(row) and row[col_idx]:
                        max_len = max(max_len, len(str(row[col_idx])))
                ws.set_column(col_idx, col_idx, min(max_len + 4, 50))

        wb.close()

    # =========================================================================
    # Modele de donnee — ligne du DataGrid
    # =========================================================================
    class ScheduleRow(object):
        def __init__(self, vs):
            self._schedule  = vs
            self.IsSelected = False
            self.Name       = vs.Name or u""

        def toggle(self):
            self.IsSelected = not self.IsSelected

    # =========================================================================
    # XAML (ASCII strict)
    # =========================================================================
    XAML = """<Window
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="780" Height="620"
        MinWidth="600" MinHeight="450"
        WindowStartupLocation="CenterScreen"
        Background="White" ResizeMode="CanResize">
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
                BorderThickness="0,0,0,1" Padding="8,7">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="200"/>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" x:Name="lbl_filter"
                       VerticalAlignment="Center" Margin="0,0,8,0" FontWeight="SemiBold"/>
            <TextBox Grid.Column="1" x:Name="txt_filter" Height="26" Margin="0,0,16,0"
                     VerticalContentAlignment="Center" Padding="4,0" BorderBrush="#A0B8D0"/>
            <TextBlock Grid.Column="2" x:Name="lbl_visible"
                       VerticalAlignment="Center" Margin="0,0,16,0"
                       Foreground="#555555" FontSize="11"/>
            <StackPanel Grid.Column="3"/>
            <Button Grid.Column="4" x:Name="btn_all"
                    Height="26" Padding="10,0" Margin="0,0,6,0"
                    Background="#2ECC71" Foreground="White"
                    FontWeight="SemiBold" BorderThickness="0"/>
            <Button Grid.Column="5" x:Name="btn_none"
                    Height="26" Padding="10,0" Margin="0,0,16,0"
                    Background="#E74C3C" Foreground="White"
                    FontWeight="SemiBold" BorderThickness="0"/>
            <TextBlock Grid.Column="6" x:Name="lbl_sel"
                       VerticalAlignment="Center"
                       FontWeight="SemiBold" Foreground="#2F6496" FontSize="12"/>
          </Grid>
        </Border>
        <DataGrid x:Name="dg" Grid.Row="2" Margin="8,8,8,4"
                  AutoGenerateColumns="False" IsReadOnly="False"
                  AlternatingRowBackground="#E8F0FA" RowBackground="White"
                  GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
                  HeadersVisibility="Column"
                  CanUserResizeColumns="True" CanUserSortColumns="True"
                  CanUserAddRows="False" CanUserDeleteRows="False"
                  SelectionMode="Single" FontSize="12">
          <DataGrid.ColumnHeaderStyle>
            <Style TargetType="DataGridColumnHeader">
              <Setter Property="Background" Value="#D0E4F7"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
              <Setter Property="Padding"    Value="6,3"/>
            </Style>
          </DataGrid.ColumnHeaderStyle>
          <DataGrid.Columns>
            <DataGridCheckBoxColumn x:Name="col_sel"
                Binding="{Binding IsSelected, Mode=TwoWay}"
                Width="36" SortMemberPath="IsSelected"/>
            <DataGridTextColumn x:Name="col_name" Binding="{Binding Name}" Width="*" IsReadOnly="True"/>
          </DataGrid.Columns>
        </DataGrid>
        <Border Grid.Row="3" Background="#F0F6FF" BorderBrush="#C0D0E0"
                BorderThickness="0,1,0,1" Padding="8,7">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Column="0" x:Name="lbl_folder_lbl"
                       VerticalAlignment="Center" FontWeight="SemiBold" Margin="0,0,8,0"/>
            <TextBlock Grid.Column="1" x:Name="lbl_folder"
                       VerticalAlignment="Center" FontSize="11"
                       Foreground="#333333" TextWrapping="NoWrap" TextTrimming="CharacterEllipsis"/>
            <Button Grid.Column="2" x:Name="btn_browse"
                    Height="26" Width="110" Margin="6,0,0,0"
                    Background="#3498DB" Foreground="White"
                    FontWeight="SemiBold" BorderThickness="0"/>
          </Grid>
        </Border>
        <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,6">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="10,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,10,0">
              <Button x:Name="btn_cancel" Width="90" Height="28" Margin="0,0,6,0"
                      Background="#E74C3C" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
              <Button x:Name="btn_export" Width="170" Height="28"
                      Background="#E67E22" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    # =========================================================================
    # Fenetre principale
    # =========================================================================
    def show_export_dialog(all_schedules):
        all_rows = [ScheduleRow(vs) for vs in all_schedules]

        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)
        window.Title = TOOL_NAME  # version uniquement dans le footer

        window.FindName("lbl_titre").Text      = u"Export Nomenclatures Excel  |  Revit {}".format(app.VersionNumber)
        window.FindName("lbl_filter").Text     = u"Recherche :"
        window.FindName("btn_all").Content     = u"Tout cocher"
        window.FindName("btn_none").Content    = u"Tout decocher"
        window.FindName("lbl_folder_lbl").Text = u"Dossier :"
        window.FindName("btn_browse").Content  = u"Parcourir..."
        window.FindName("btn_cancel").Content  = u"Annuler"
        window.FindName("btn_export").Content  = u"Exporter la selection"
        window.FindName("lbl_footer").Text     = _FOOTER

        col_sel  = window.FindName("col_sel")
        col_name = window.FindName("col_name")
        if col_sel  is not None: col_sel.Header  = u""
        if col_name is not None: col_name.Header = u"Nom de la nomenclature"

        dg = window.FindName("dg")
        lbl_folder = window.FindName("lbl_folder")
        lbl_folder.Text = load_last_folder() or (
            os.path.dirname(doc.PathName) if doc.PathName else
            System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)
        )

        txt_filter   = window.FindName("txt_filter")
        state        = {"result": None, "busy": False}
        filtered_src = {"rows": list(all_rows)}

        def get_checked_rows():
            return [r for r in all_rows if r.IsSelected]

        def update_labels():
            nb_vis = len(filtered_src["rows"])
            nb_sel = len(get_checked_rows())
            window.FindName("lbl_visible").Text = u"{} nomenclature(s)".format(nb_vis)
            window.FindName("lbl_sel").Text     = u"{} selectionnee(s)".format(nb_sel)

        def refresh_grid():
            dg.ItemsSource = None
            dg.ItemsSource = filtered_src["rows"]
            update_labels()

        refresh_grid()

        def on_filter_changed(s, e):
            query = txt_filter.Text.strip().lower()
            filtered_src["rows"] = (
                list(all_rows) if not query
                else [r for r in all_rows if query in r.Name.lower()]
            )
            refresh_grid()

        txt_filter.TextChanged += on_filter_changed

        def on_all(s, e):
            for r in filtered_src["rows"]: r.IsSelected = True
            refresh_grid()

        def on_none(s, e):
            for r in filtered_src["rows"]: r.IsSelected = False
            refresh_grid()

        window.FindName("btn_all").Click  += on_all
        window.FindName("btn_none").Click += on_none

        def on_cell_changed(s, e):
            if state["busy"]: return
            if dg.CurrentColumn is None: return
            if dg.CurrentColumn.DisplayIndex == 0 and dg.CurrentItem is not None:
                state["busy"] = True
                try:
                    dg.CurrentItem.toggle()
                    src = dg.ItemsSource; dg.ItemsSource = None; dg.ItemsSource = src
                finally:
                    state["busy"] = False
            update_labels()

        dg.CurrentCellChanged += on_cell_changed

        def on_browse(s, e):
            dlg = FolderBrowserDialog()
            dlg.SelectedPath = lbl_folder.Text
            dlg.Description  = u"Choisir le dossier de destination"
            if dlg.ShowDialog() == DialogResult.OK:
                lbl_folder.Text = dlg.SelectedPath

        window.FindName("btn_browse").Click += on_browse

        def on_export(s, e):
            rows_to_export = get_checked_rows()
            if not rows_to_export:
                MessageBox.Show(
                    u"Aucune nomenclature selectionnee.\nCochez au moins une nomenclature.",
                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            folder = lbl_folder.Text.strip()
            if not os.path.isdir(folder):
                MessageBox.Show(
                    u"Le dossier specifie n'existe pas :\n{}".format(folder),
                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
                return
            save_last_folder(folder)
            state["result"] = {
                "folder"    : folder,
                "schedules" : [r._schedule for r in rows_to_export],
            }
            window.Close()

        window.FindName("btn_export").Click += on_export
        window.FindName("btn_cancel").Click += lambda s, e: window.Close()

        window.ShowDialog()
        return state["result"]

    # =========================================================================
    # Progression
    # =========================================================================
    def make_progress_win(total):
        win = Window(); win.Title = TOOL_NAME; win.Width = 420; win.Height = 145
        win.ResizeMode = SW.ResizeMode.NoResize
        win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        win.Background = hex_brush("#FFFFFF")
        sp = StackPanel(); sp.Margin = Thickness(16, 14, 16, 10); win.Content = sp
        lbl = TextBlock(); lbl.FontSize = 11; lbl.Margin = Thickness(0, 0, 0, 6)
        sp.Children.Add(lbl)
        pb = ProgressBar(); pb.Minimum = 0; pb.Maximum = total; pb.Value = 0
        pb.Height = 18; pb.Margin = Thickness(0, 0, 0, 4); sp.Children.Add(pb)
        lbl_det = TextBlock(); lbl_det.FontSize = 10
        lbl_det.Foreground = hex_brush("#555555"); lbl_det.Margin = Thickness(0, 0, 0, 4)
        sp.Children.Add(lbl_det)
        ftr = TextBlock(); ftr.Text = _FOOTER; ftr.FontSize = 9
        ftr.Foreground = hex_brush("#888888")
        ftr.HorizontalAlignment = SW.HorizontalAlignment.Right
        sp.Children.Add(ftr)
        win.Show()
        return win, lbl, pb, lbl_det

    # =========================================================================
    # Dialog fichier existant
    # =========================================================================
    def ask_overwrite_or_rename(existing_path):
        """Affiche une dialog si le fichier existe deja.
        Retourne le chemin final choisi, ou None si l'utilisateur annule."""
        folder   = os.path.dirname(existing_path)
        basename = os.path.basename(existing_path)          # ex. Projet_Nomenclatures.xlsx
        name_no_ext = basename[:-5] if basename.lower().endswith(".xlsx") else basename

        XAML_OW = """<Window
            xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
            xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
            Title="PLACEHOLDER" Width="500" SizeToContent="Height"
            WindowStartupLocation="CenterScreen"
            Background="White" ResizeMode="NoResize">
          <Grid>
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
              <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
            </Border>
            <StackPanel Grid.Row="1" Margin="18,14,18,10">
              <TextBlock x:Name="lbl_msg" FontSize="11" TextWrapping="Wrap"
                         Foreground="#333333" Margin="0,0,0,12"/>
              <TextBlock x:Name="lbl_name_lbl" FontSize="11" FontWeight="SemiBold"
                         Margin="0,0,0,4"/>
              <TextBox x:Name="txt_name" Height="28" FontSize="11"
                       VerticalContentAlignment="Center" Padding="6,0"
                       BorderBrush="#A0B8D0" Margin="0,0,0,4"/>
              <TextBlock x:Name="lbl_ext" FontSize="10" Foreground="#888888"/>
            </StackPanel>
            <Border Grid.Row="2" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                    Background="#F5F5F5" Padding="0,6">
              <Grid Margin="10,0">
                <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                           VerticalAlignment="Center"/>
                <StackPanel HorizontalAlignment="Right" Orientation="Horizontal">
                  <Button x:Name="btn_cancel" Width="90" Height="28" Margin="0,0,6,0"
                          Background="#E74C3C" Foreground="White"
                          FontWeight="SemiBold" BorderThickness="0"/>
                  <Button x:Name="btn_overwrite" Width="110" Height="28" Margin="0,0,6,0"
                          Background="#E67E22" Foreground="White"
                          FontWeight="SemiBold" BorderThickness="0"/>
                  <Button x:Name="btn_rename" Width="110" Height="28"
                          Background="#2ECC71" Foreground="White"
                          FontWeight="SemiBold" BorderThickness="0"/>
                </StackPanel>
              </Grid>
            </Border>
          </Grid>
        </Window>"""

        stream  = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML_OW))
        win_ow  = System.Windows.Markup.XamlReader.Load(stream)
        win_ow.Title = TOOL_NAME

        win_ow.FindName("lbl_titre").Text     = u"Fichier existant"
        win_ow.FindName("lbl_msg").Text       = (
            u"Le fichier suivant existe deja :\n{}\n\n"
            u"Voulez-vous l'ecraser ou lui donner un nouveau nom ?".format(existing_path)
        )
        win_ow.FindName("lbl_name_lbl").Text  = u"Nouveau nom (sans extension) :"
        win_ow.FindName("txt_name").Text      = name_no_ext
        win_ow.FindName("lbl_ext").Text       = u"Le fichier sera enregistre sous : <nom>.xlsx"
        win_ow.FindName("lbl_footer").Text    = _FOOTER
        win_ow.FindName("btn_cancel").Content    = u"Annuler"
        win_ow.FindName("btn_overwrite").Content = u"Ecraser"
        win_ow.FindName("btn_rename").Content    = u"Nouveau nom"

        txt_name = win_ow.FindName("txt_name")
        lbl_ext  = win_ow.FindName("lbl_ext")

        def on_txt_changed(s, e):
            n = txt_name.Text.strip()
            lbl_ext.Text = (u"Le fichier sera enregistre sous : {}.xlsx".format(n)
                            if n else u"Entrez un nom valide.")
        txt_name.TextChanged += on_txt_changed

        state_ow = {"path": None}

        def on_overwrite(s, e):
            state_ow["path"] = existing_path
            win_ow.Close()

        def on_rename(s, e):
            new_name = txt_name.Text.strip()
            if not new_name:
                MessageBox.Show(u"Le nom ne peut pas etre vide.",
                                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            # Nettoyer les caracteres interdits
            for ch in ['\\', '/', '*', '?', ':', '"', '<', '>', '|']:
                new_name = new_name.replace(ch, '_')
            new_path = os.path.join(folder, new_name + u".xlsx")
            # Si le nouveau nom existe aussi, on redemande
            if os.path.isfile(new_path) and new_path != existing_path:
                res = MessageBox.Show(
                    u"Le fichier '{}' existe aussi.\nL'ecraser ?".format(new_name + u".xlsx"),
                    TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Warning)
                from System.Windows import MessageBoxResult
                if res != MessageBoxResult.Yes:
                    return
            state_ow["path"] = new_path
            win_ow.Close()

        win_ow.FindName("btn_overwrite").Click += on_overwrite
        win_ow.FindName("btn_rename").Click    += on_rename
        win_ow.FindName("btn_cancel").Click    += lambda s, e: win_ow.Close()

        win_ow.ShowDialog()
        return state_ow["path"]

    # =========================================================================
    # Resultat
    # =========================================================================
    def show_result(successes, errors, folder=None, output_path=None):
        win = Window(); win.Title = TOOL_NAME; win.Width = 540
        win.SizeToContent = SW.SizeToContent.Height; win.MinHeight = 140
        win.ResizeMode = SW.ResizeMode.NoResize
        win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        win.Background = hex_brush("#FFFFFF")
        root = Grid()
        root.RowDefinitions.Add(_rd_auto()); root.RowDefinitions.Add(_rd_auto())
        win.Content = root
        sp = StackPanel(); sp.Margin = Thickness(18, 14, 18, 10)
        Grid.SetRow(sp, 0); root.Children.Add(sp)

        if successes:
            tb_ok = TextBlock()
            tb_ok.Text = u"Export reussi — {} nomenclature(s) :".format(len(successes))
            tb_ok.FontSize = 12; tb_ok.FontWeight = SW.FontWeights.SemiBold
            tb_ok.Foreground = hex_brush("#1a7c3e"); tb_ok.Margin = Thickness(0, 0, 0, 4)
            sp.Children.Add(tb_ok)
            for s in successes:
                tb = TextBlock(); tb.Text = u"   " + s; tb.FontSize = 11
                tb.Foreground = hex_brush("#333333"); tb.Margin = Thickness(0, 1, 0, 1)
                sp.Children.Add(tb)

        if output_path:
            tb_path = TextBlock()
            tb_path.Text = u"Fichier : " + output_path
            tb_path.FontSize = 10; tb_path.FontFamily = FontFamily("Consolas")
            tb_path.TextWrapping = SW.TextWrapping.Wrap
            tb_path.Foreground = hex_brush("#1a3a5c"); tb_path.Margin = Thickness(0, 8, 0, 0)
            sp.Children.Add(tb_path)

        if errors:
            tb_ko = TextBlock(); tb_ko.Text = u"Erreur(s) :"
            tb_ko.FontSize = 12; tb_ko.FontWeight = SW.FontWeights.SemiBold
            tb_ko.Foreground = hex_brush("#C0392B")
            tb_ko.Margin = Thickness(0, 10 if successes else 0, 0, 4)
            sp.Children.Add(tb_ko)
            for err in errors:
                tb = TextBlock(); tb.Text = u"   " + err; tb.FontSize = 11
                tb.Foreground = hex_brush("#333333")
                tb.TextWrapping = SW.TextWrapping.Wrap; tb.Margin = Thickness(0, 1, 0, 1)
                sp.Children.Add(tb)

        footer = Border(); footer.BorderThickness = Thickness(0, 1, 0, 0)
        footer.BorderBrush = hex_brush("#C0D0E0"); footer.Background = hex_brush("#F5F5F5")
        footer.Padding = Thickness(0, 6, 0, 6); Grid.SetRow(footer, 1); root.Children.Add(footer)
        grid_f = Grid()
        lbl_f = TextBlock(); lbl_f.Text = _FOOTER; lbl_f.FontSize = 10
        lbl_f.Foreground = hex_brush("#888888"); lbl_f.VerticalAlignment = SW.VerticalAlignment.Center
        lbl_f.Margin = Thickness(10, 0, 0, 0); grid_f.Children.Add(lbl_f)
        sp_btns = StackPanel(); sp_btns.Orientation = Orientation.Horizontal
        sp_btns.HorizontalAlignment = SW.HorizontalAlignment.Right
        sp_btns.Margin = Thickness(0, 0, 10, 0)

        if folder and os.path.isdir(folder):
            btn_open = Button(); btn_open.Content = u"Ouvrir le dossier"
            btn_open.Height = 26; btn_open.Padding = Thickness(10, 0, 10, 0)
            btn_open.Margin = Thickness(0, 0, 6, 0)
            btn_open.Background = hex_brush("#2ECC71"); btn_open.Foreground = hex_brush("#FFFFFF")
            btn_open.FontWeight = SW.FontWeights.SemiBold; btn_open.BorderThickness = Thickness(0)
            _f = folder
            def on_open(s, e):
                try: subprocess.Popen(u'explorer "{}"'.format(_f))
                except Exception: pass
                win.Close()
            btn_open.Click += on_open
            sp_btns.Children.Add(btn_open)

        btn_ok = Button(); btn_ok.Content = u"OK"; btn_ok.Width = 80; btn_ok.Height = 26
        btn_ok.Background = hex_brush("#3498DB"); btn_ok.Foreground = hex_brush("#FFFFFF")
        btn_ok.FontWeight = SW.FontWeights.SemiBold; btn_ok.BorderThickness = Thickness(0)
        btn_ok.Click += lambda s, e: win.Close()
        sp_btns.Children.Add(btn_ok)
        grid_f.Children.Add(sp_btns); footer.Child = grid_f
        win.ShowDialog()

    # =========================================================================
    # MAIN
    # =========================================================================
    all_schedules = get_all_schedules()
    if not all_schedules:
        MessageBox.Show(
            u"Aucune nomenclature trouvee dans le projet.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)
    else:
        params = show_export_dialog(all_schedules)
        if params is not None:
            folder    = params["folder"]
            schedules = params["schedules"]

            prog_win, lbl_prog, pb_prog, lbl_det = make_progress_win(len(schedules))
            disp = prog_win.Dispatcher
            schedules_data = []
            errors         = []

            try:
                for idx, vs in enumerate(schedules):
                    lbl_prog.Text = u"Extraction {}/{}...".format(idx + 1, len(schedules))
                    lbl_det.Text  = vs.Name
                    pb_prog.Value = idx
                    do_events(disp)
                    try:
                        headers, rows = schedule_to_data(vs)
                        schedules_data.append((vs.Name, headers, rows))
                    except Exception as ex:
                        errors.append(u"{} : {}".format(vs.Name, str(ex)))
                pb_prog.Value = len(schedules)
                do_events(disp)
            finally:
                prog_win.Close()

            if not schedules_data:
                show_result([], errors)
            else:
                project_name   = (doc.Title or u"Projet").replace(u" ", u"_")
                output_path    = os.path.join(folder, u"{}_Nomenclatures.xlsx".format(project_name))

                # Avertissement si le fichier existe deja
                if os.path.isfile(output_path):
                    output_path = ask_overwrite_or_rename(output_path)

                if output_path is None:
                    pass  # annule par l'utilisateur
                else:
                    try:
                        export_to_excel(schedules_data, output_path)
                        successes = [name for name, _, _ in schedules_data]
                    except Exception as ex:
                        errors.append(u"Erreur ecriture Excel : {}".format(str(ex)))
                        print(traceback.format_exc())
                        successes   = []
                        output_path = None
                    show_result(successes, errors, folder=folder, output_path=output_path)

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
