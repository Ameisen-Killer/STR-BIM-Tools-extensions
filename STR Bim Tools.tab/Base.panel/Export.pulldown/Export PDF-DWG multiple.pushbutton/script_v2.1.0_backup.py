# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Export PDF / DWG"
# =============================================================================
#  v2.1.0 — HideCropBoundaries = False : limites de cadrage visibles dans le PDF
#  v2.0.0 — Selection multiple de feuilles avec filtre SPVA_GED_H-NUMERO
#           Vue simple : nommage par nom de vue (comportement v1.1.0)
# =============================================================================

import clr, os, io, json, traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
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
    CheckBox, DockPanel, ScrollViewer,
    RowDefinition, ColumnDefinition, Orientation,
    TextBox,
)
from System.Windows.Data  import Binding
from System.Windows.Media import SolidColorBrush, Color, FontFamily

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInParameter,
    PDFExportOptions,
    DWGExportOptions,
    ACADVersion,
    ElementId,
    ViewSheet,
    View,
)

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app   = __revit__.Application

# =============================================================================
# Persistance du dernier dossier utilise
# =============================================================================
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

# =============================================================================
# Helpers couleur / UI
# =============================================================================
def hex_brush(h):
    h = h.lstrip("#")
    return SolidColorBrush(Color.FromRgb(
        int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ))

def _rd_auto():
    rd = RowDefinition(); rd.Height = GridLength.Auto; return rd

def _rd_star():
    rd = RowDefinition(); rd.Height = GridLength(1, GridUnitType.Star); return rd

def do_events(dispatcher):
    try:
        dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
    except Exception:
        pass

# =============================================================================
# Lecture des parametres
# =============================================================================
def get_param_str(elem, name):
    p = elem.LookupParameter(name)
    if p and p.HasValue:
        v = p.AsString()
        return v.strip() if v and v.strip() else None
    return None

def get_bip_str(elem, bip):
    p = elem.get_Parameter(bip)
    if p and p.HasValue:
        v = p.AsString()
        return v.strip() if v and v.strip() else None
    return None

# =============================================================================
# Nommage des fichiers
# =============================================================================
GED_PARAMS = [
    ("SPVA_GED_A-PROJET",          u"A - Projet"),
    ("SPVA_GED_B-DISCIPLINE",      u"B - Discipline"),
    ("SPVA_GED_C-EMMETEUR",        u"C - Emetteur"),
    ("SPVA_GED_D-PHASE SIA",       u"D - Phase SIA"),
    ("SPVA_GED_E-TYPE",            u"E - Type"),
    ("SPVA_GED_F-CODE ETAGE",      u"F - Code Etage"),
    ("SPVA_GED_G-ZONE IMPRESSION", u"G - Zone Impression"),
    ("SPVA_GED_H-NUMERO",          u"H - Numero"),
]

def build_filename_sheet(sheet):
    """Retourne (filename_sans_ext, liste_params_manquants)."""
    vals    = {}
    missing = []
    for pname, label in GED_PARAMS:
        v = get_param_str(sheet, pname)
        if v:  vals[pname] = v
        else:  missing.append(label); vals[pname] = u"???"
    rev = get_bip_str(sheet, BuiltInParameter.SHEET_CURRENT_REVISION)
    if not rev: missing.append(u"Revision actuelle"); rev = u"??"
    sheet_name = get_bip_str(sheet, BuiltInParameter.SHEET_NAME)
    if not sheet_name: missing.append(u"Nom de la feuille"); sheet_name = u"???"
    desc = get_param_str(sheet, u"#STR_CAR_Description du plan")
    if not desc: missing.append(u"#STR_CAR_Description du plan"); desc = u"???"
    prefix = u"{}-{}-{}-{}-{}-{}-{}-{}-{}".format(
        vals["SPVA_GED_A-PROJET"],   vals["SPVA_GED_B-DISCIPLINE"],
        vals["SPVA_GED_C-EMMETEUR"], vals["SPVA_GED_D-PHASE SIA"],
        vals["SPVA_GED_E-TYPE"],     vals["SPVA_GED_F-CODE ETAGE"],
        vals["SPVA_GED_G-ZONE IMPRESSION"], vals["SPVA_GED_H-NUMERO"], rev,
    )
    return u"{}_{} - {}".format(prefix, sheet_name, desc), missing

def build_filename_view(view):
    """Nom de fichier pour une vue simple."""
    name = view.Name or u"Vue_sans_nom"
    for ch in u'\\/:*?"<>|':
        name = name.replace(ch, u"_")
    while u"  " in name:
        name = name.replace(u"  ", u" ")
    return name.strip()

# =============================================================================
# Export PDF / DWG
# =============================================================================
def do_export_pdf(folder, filename, view_id):
    opts                    = PDFExportOptions()
    opts.FileName           = filename
    opts.Combine            = True
    opts.HideCropBoundaries = False  # afficher les limites de cadrage
    ids = List[ElementId](); ids.Add(view_id)
    return doc.Export(folder, ids, opts)

def do_export_dwg(folder, filename, view_id):
    opts = DWGExportOptions()
    opts.FileVersion = ACADVersion.R2018
    opts.MergedViews = True
    ids = List[ElementId](); ids.Add(view_id)
    result = doc.Export(folder, filename, ids, opts)
    # Revit génère automatiquement un .pcp — on le supprime
    pcp = os.path.join(folder, filename + ".pcp")
    try:
        if os.path.isfile(pcp):
            os.remove(pcp)
    except Exception:
        pass
    return result

# =============================================================================
# Collecte des feuilles du projet
# =============================================================================
def collect_all_sheets():
    sheets = list(
        FilteredElementCollector(doc)
        .OfClass(ViewSheet)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    sheets.sort(key=lambda s: (
        get_param_str(s, "SPVA_GED_H-NUMERO") or u"",
        get_bip_str(s, BuiltInParameter.SHEET_NUMBER) or u"",
    ))
    return sheets

# =============================================================================
# Modele de donnee — ligne du DataGrid
# =============================================================================
class SheetRow(object):
    def __init__(self, sheet):
        self._sheet      = sheet
        self.IsSelected  = False
        self.SheetNum    = get_bip_str(sheet, BuiltInParameter.SHEET_NUMBER)            or u""
        self.SheetName   = get_bip_str(sheet, BuiltInParameter.SHEET_NAME)             or u""
        self.NumeroGED   = get_param_str(sheet, "SPVA_GED_H-NUMERO")                   or u""
        self.Description = get_param_str(sheet, "#STR_CAR_Description du plan")        or u""
        self.Revision    = get_bip_str(sheet, BuiltInParameter.SHEET_CURRENT_REVISION) or u""
        self.Status      = u""

    def toggle(self):
        self.IsSelected = not self.IsSelected

# =============================================================================
# XAML — fenetre multi-selection (ASCII strict, accents assignes apres Load)
# =============================================================================
XAML_MULTI = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1060" Height="700"
    MinWidth="820" MinHeight="500"
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

    <!-- BARRE TITRE -->
    <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
      <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
    </Border>

    <!-- BARRE FILTRES -->
    <Border Grid.Row="1" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="8,7">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="170"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" x:Name="lbl_filter"
                   VerticalAlignment="Center" Margin="0,0,8,0" FontWeight="SemiBold"/>
        <TextBox Grid.Column="1" x:Name="txt_numero" Height="26" Margin="0,0,16,0"
                 VerticalContentAlignment="Center" Padding="4,0"
                 BorderBrush="#A0B8D0"/>
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

    <!-- DATAGRID -->
    <DataGrid x:Name="dg_sheets" Grid.Row="2" Margin="8,8,8,4"
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
        <DataGridTextColumn x:Name="col_num"  Binding="{Binding SheetNum}"    Width="100" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_name" Binding="{Binding SheetName}"   Width="*"   IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_ged"  Binding="{Binding NumeroGED}"   Width="80"  IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_desc" Binding="{Binding Description}" Width="200" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_rev"  Binding="{Binding Revision}"    Width="55"  IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_stat" Binding="{Binding Status}"      Width="120" IsReadOnly="True"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- OPTIONS : DOSSIER + FORMAT -->
    <Border Grid.Row="3" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,1,0,1" Padding="8,7">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" x:Name="lbl_folder_lbl"
                   VerticalAlignment="Center" FontWeight="SemiBold" Margin="0,0,8,0"/>
        <TextBlock Grid.Column="1" x:Name="lbl_folder"
                   VerticalAlignment="Center" FontSize="11"
                   Foreground="#333333" TextWrapping="NoWrap" TextTrimming="CharacterEllipsis"/>
        <Button Grid.Column="2" x:Name="btn_browse"
                Height="26" Width="100" Margin="6,0,24,0"
                Background="#3498DB" Foreground="White"
                FontWeight="SemiBold" BorderThickness="0"/>
        <CheckBox Grid.Column="3" x:Name="chk_pdf" IsChecked="True"
                  VerticalAlignment="Center" FontSize="13" FontWeight="SemiBold"
                  Margin="0,0,20,0"/>
        <CheckBox Grid.Column="4" x:Name="chk_dwg" IsChecked="True"
                  VerticalAlignment="Center" FontSize="13" FontWeight="SemiBold"/>
      </Grid>
    </Border>

    <!-- FOOTER -->
    <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,6">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="10,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,10,0">
          <Button x:Name="btn_cancel" Width="90" Height="28" Margin="0,0,6,0"
                  Background="#E74C3C" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_export" Width="150" Height="28"
                  Background="#E67E22" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

# =============================================================================
# Fenetre de selection multiple (feuilles)
# =============================================================================
def show_multi_export_dialog(all_sheets, active_sheet_id=None):
    """
    Affiche la fenetre de selection multiple.
    Retourne un dict {folder, rows_to_export, export_pdf, export_dwg}
    ou None si annule.
    """
    # ── Construction des lignes ──────────────────────────────────────────────
    all_rows = [SheetRow(s) for s in all_sheets]

    # (plus de liste de valeurs uniques — filtre textuel libre)

    # ── Chargement XAML ──────────────────────────────────────────────────────
    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML_MULTI))
    window = System.Windows.Markup.XamlReader.Load(stream)
    window.Title = TOOL_NAME

    # ── Accents apres chargement ─────────────────────────────────────────────
    window.FindName("lbl_titre").Text      = u"Export PDF / DWG — Selection multiple  |  Revit {}".format(app.VersionNumber)
    window.FindName("lbl_filter").Text     = u"N° GED :"
    window.FindName("btn_all").Content     = u"Tout cocher"
    window.FindName("btn_none").Content    = u"Tout décocher"
    window.FindName("lbl_folder_lbl").Text = u"Dossier :"
    window.FindName("btn_browse").Content  = u"Parcourir..."
    window.FindName("btn_cancel").Content  = u"Annuler"
    window.FindName("btn_export").Content  = u"Exporter la sélection"
    window.FindName("chk_pdf").Content     = u"PDF"
    window.FindName("chk_dwg").Content     = u"DWG (AutoCAD 2018)"
    window.FindName("lbl_footer").Text     = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # En-tetes colonnes DataGrid
    dg = window.FindName("dg_sheets")
    dg.FindName("col_sel").Header   = u""
    dg.FindName("col_num").Header   = u"N° Feuille"
    dg.FindName("col_name").Header  = u"Nom"
    dg.FindName("col_ged").Header   = u"N° GED"
    dg.FindName("col_desc").Header  = u"Description"
    dg.FindName("col_rev").Header   = u"Rév."
    dg.FindName("col_stat").Header  = u"Statut"

    # ── TextBox filtre NUMERO ────────────────────────────────────────────────
    txt_numero = window.FindName("txt_numero")

    # ── Dossier par defaut ───────────────────────────────────────────────────
    lbl_folder = window.FindName("lbl_folder")
    lbl_folder.Text = load_last_folder() or (
        os.path.dirname(doc.PathName) if doc.PathName else
        System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)
    )

    # ── Etat interne ─────────────────────────────────────────────────────────
    state        = {"result": None, "busy": False}
    filtered_src = {"rows": list(all_rows)}   # lignes visibles

    def get_checked_rows():
        return [r for r in all_rows if r.IsSelected]

    def update_labels():
        nb_vis = len(filtered_src["rows"])
        nb_sel = len(get_checked_rows())
        window.FindName("lbl_visible").Text = u"{} feuille(s)".format(nb_vis)
        window.FindName("lbl_sel").Text     = u"{} sélectionnée(s)".format(nb_sel)

    def refresh_grid():
        src = filtered_src["rows"]
        dg.ItemsSource = None
        dg.ItemsSource = src
        update_labels()

    # Chargement initial
    refresh_grid()

    # ── Filtre TextBox — recherche partielle en temps reel ───────────────────
    def on_filter_changed(s, e):
        query = txt_numero.Text.strip().lower()
        if not query:
            filtered_src["rows"] = list(all_rows)
        else:
            filtered_src["rows"] = [r for r in all_rows
                                    if query in r.NumeroGED.lower()]
        refresh_grid()

    txt_numero.TextChanged += on_filter_changed

    # ── Tout cocher / decocher (sur le filtre actif) ──────────────────────────
    def on_all(s, e):
        for r in filtered_src["rows"]:
            r.IsSelected = True
        refresh_grid()

    def on_none(s, e):
        for r in filtered_src["rows"]:
            r.IsSelected = False
        refresh_grid()

    window.FindName("btn_all").Click  += on_all
    window.FindName("btn_none").Click += on_none

    # ── Checkbox DataGrid — CurrentCellChanged (pattern fiable IronPython) ───
    def on_cell_changed(s, e):
        if state["busy"]:
            return
        if dg.CurrentColumn is None:
            return
        if dg.CurrentColumn.DisplayIndex == 0 and dg.CurrentItem is not None:
            state["busy"] = True
            try:
                dg.CurrentItem.toggle()
                src = dg.ItemsSource; dg.ItemsSource = None; dg.ItemsSource = src
            finally:
                state["busy"] = False
        update_labels()

    dg.CurrentCellChanged += on_cell_changed

    # ── Parcourir ────────────────────────────────────────────────────────────
    def on_browse(s, e):
        dlg = FolderBrowserDialog()
        dlg.SelectedPath = lbl_folder.Text
        dlg.Description  = u"Choisir le dossier de destination"
        if dlg.ShowDialog() == DialogResult.OK:
            lbl_folder.Text = dlg.SelectedPath

    window.FindName("btn_browse").Click += on_browse

    # ── Exporter ─────────────────────────────────────────────────────────────
    def on_export(s, e):
        rows_to_export = get_checked_rows()
        if not rows_to_export:
            MessageBox.Show(
                u"Aucune feuille sélectionnée.\nCochez au moins une feuille avant d'exporter.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        export_pdf = bool(window.FindName("chk_pdf").IsChecked)
        export_dwg = bool(window.FindName("chk_dwg").IsChecked)
        if not export_pdf and not export_dwg:
            MessageBox.Show(
                u"Sélectionnez au moins un format (PDF ou DWG).",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        folder = lbl_folder.Text.strip()
        if not os.path.isdir(folder):
            MessageBox.Show(
                u"Le dossier spécifié n'existe pas :\n{}".format(folder),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        # Avertissement parametres manquants
        rows_missing = []
        for r in rows_to_export:
            _, missing = build_filename_sheet(r._sheet)
            if missing:
                rows_missing.append(r.SheetNum or r.SheetName)

        if rows_missing:
            msg = (u"Des paramètres GED sont manquants sur {} feuille(s) :\n\n"
                   + u"\n".join(u"  •  " + n for n in rows_missing[:10])
                   + (u"\n  ..." if len(rows_missing) > 10 else u"")
                   + u"\n\nLes noms de fichiers contiendront des '???'.\nContinuer quand même ?")
            res = MessageBox.Show(
                msg.format(len(rows_missing)),
                u"Paramètres manquants",
                MessageBoxButton.YesNo, MessageBoxImage.Warning)
            if str(res) != "Yes":
                return

        save_last_folder(folder)
        state["result"] = {
            "folder"     : folder,
            "rows"       : rows_to_export,
            "export_pdf" : export_pdf,
            "export_dwg" : export_dwg,
        }
        window.Close()

    window.FindName("btn_export").Click += on_export
    window.FindName("btn_cancel").Click += lambda s, e: window.Close()

    window.ShowDialog()
    return state["result"]

# =============================================================================
# Fenetre de confirmation ecrasement
# =============================================================================
def _confirm_overwrite(existing_labels):
    state = {"ok": False}
    win   = Window()
    win.Title  = u"Fichier(s) existant(s)"
    win.Width  = 420
    win.SizeToContent = SW.SizeToContent.Height
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid(); root.RowDefinitions.Add(_rd_auto()); root.RowDefinitions.Add(_rd_auto())
    win.Content = root

    sp = StackPanel(); sp.Margin = Thickness(18, 16, 18, 12)
    Grid.SetRow(sp, 0); root.Children.Add(sp)

    tb_msg = TextBlock()
    tb_msg.Text = u"Le(s) fichier(s) suivant(s) existe(nt) déjà :"
    tb_msg.FontSize = 12; tb_msg.FontWeight = SW.FontWeights.SemiBold
    tb_msg.Foreground = hex_brush("#333333"); tb_msg.TextWrapping = SW.TextWrapping.Wrap
    tb_msg.Margin = Thickness(0, 0, 0, 8); sp.Children.Add(tb_msg)
    for lbl in existing_labels:
        tb = TextBlock(); tb.Text = u"•  " + lbl; tb.FontSize = 12
        tb.Foreground = hex_brush("#555555"); tb.Margin = Thickness(8, 1, 0, 1)
        sp.Children.Add(tb)
    tb_q = TextBlock(); tb_q.Text = u"Écraser ?"; tb_q.FontSize = 12
    tb_q.FontWeight = SW.FontWeights.SemiBold; tb_q.Foreground = hex_brush("#E67E22")
    tb_q.Margin = Thickness(0, 10, 0, 0); sp.Children.Add(tb_q)

    footer = Border(); footer.BorderThickness = Thickness(0, 1, 0, 0)
    footer.BorderBrush = hex_brush("#C0D0E0"); footer.Background = hex_brush("#F5F5F5")
    footer.Padding = Thickness(0, 6, 0, 6); Grid.SetRow(footer, 1); root.Children.Add(footer)
    grid_f = Grid()
    lbl_f = TextBlock(); lbl_f.Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    lbl_f.FontSize = 10; lbl_f.Foreground = hex_brush("#888888")
    lbl_f.VerticalAlignment = SW.VerticalAlignment.Center; lbl_f.Margin = Thickness(10, 0, 0, 0)
    grid_f.Children.Add(lbl_f)
    sp_btns = StackPanel(); sp_btns.Orientation = Orientation.Horizontal
    sp_btns.HorizontalAlignment = SW.HorizontalAlignment.Right; sp_btns.Margin = Thickness(0, 0, 10, 0)
    btn_no = Button(); btn_no.Content = u"Non"; btn_no.Width = 70; btn_no.Height = 26
    btn_no.Margin = Thickness(0, 0, 6, 0); btn_no.Background = hex_brush("#E74C3C")
    btn_no.Foreground = hex_brush("#FFFFFF"); btn_no.FontWeight = SW.FontWeights.SemiBold
    btn_no.BorderThickness = Thickness(0); btn_no.Click += lambda s, e: win.Close()
    sp_btns.Children.Add(btn_no)
    btn_yes = Button(); btn_yes.Content = u"Oui"; btn_yes.Width = 70; btn_yes.Height = 26
    btn_yes.Background = hex_brush("#2ECC71"); btn_yes.Foreground = hex_brush("#FFFFFF")
    btn_yes.FontWeight = SW.FontWeights.SemiBold; btn_yes.BorderThickness = Thickness(0)
    def on_yes(s, e): state["ok"] = True; win.Close()
    btn_yes.Click += on_yes; sp_btns.Children.Add(btn_yes)
    grid_f.Children.Add(sp_btns); footer.Child = grid_f
    win.ShowDialog()
    return state["ok"]

# =============================================================================
# Fenetre de resultats
# =============================================================================
def open_folder(folder):
    try:
        import subprocess
        subprocess.Popen(u'explorer "{}"'.format(folder))
    except Exception:
        pass


def show_result(successes, errors, skipped=None, folder=None):
    win = Window(); win.Title = TOOL_NAME; win.Width = 520
    win.SizeToContent = SW.SizeToContent.Height; win.MinHeight = 140
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")
    root = Grid(); root.RowDefinitions.Add(_rd_auto()); root.RowDefinitions.Add(_rd_auto())
    win.Content = root
    sp = StackPanel(); sp.Margin = Thickness(18, 14, 18, 10)
    Grid.SetRow(sp, 0); root.Children.Add(sp)

    def _add_section(title, items, color):
        tb_hdr = TextBlock(); tb_hdr.Text = title; tb_hdr.FontSize = 12
        tb_hdr.FontWeight = SW.FontWeights.SemiBold
        tb_hdr.Foreground = hex_brush(color); tb_hdr.Margin = Thickness(0, 6, 0, 4)
        sp.Children.Add(tb_hdr)
        for item in items:
            tb = TextBlock(); tb.Text = u"   " + item; tb.FontSize = 11
            tb.Foreground = hex_brush("#333333"); tb.TextWrapping = SW.TextWrapping.Wrap
            tb.Margin = Thickness(0, 1, 0, 1); sp.Children.Add(tb)

    if successes:
        _add_section(u"✔  Export réussi :", successes, "#1a7c3e")
    if skipped:
        _add_section(u"⚠  Ignoré(s) (fichier existant refusé) :", skipped, "#E67E22")
    if errors:
        _add_section(u"✘  Erreur(s) :", errors, "#C0392B")

    footer = Border(); footer.BorderThickness = Thickness(0, 1, 0, 0)
    footer.BorderBrush = hex_brush("#C0D0E0"); footer.Background = hex_brush("#F5F5F5")
    footer.Padding = Thickness(0, 6, 0, 6); Grid.SetRow(footer, 1); root.Children.Add(footer)
    grid_f = Grid()
    lbl_f = TextBlock(); lbl_f.Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    lbl_f.FontSize = 10; lbl_f.Foreground = hex_brush("#888888")
    lbl_f.VerticalAlignment = SW.VerticalAlignment.Center; lbl_f.Margin = Thickness(10, 0, 0, 0)
    grid_f.Children.Add(lbl_f)
    btn_ok = Button(); btn_ok.Content = u"OK"; btn_ok.Width = 80; btn_ok.Height = 26
    btn_ok.Margin = Thickness(0, 0, 10, 0); btn_ok.Background = hex_brush("#3498DB")
    btn_ok.Foreground = hex_brush("#FFFFFF"); btn_ok.FontWeight = SW.FontWeights.SemiBold
    btn_ok.BorderThickness = Thickness(0)
    btn_ok.HorizontalAlignment = SW.HorizontalAlignment.Right
    btn_ok.Click += lambda s, e: win.Close()

    sp_btns_r = StackPanel(); sp_btns_r.Orientation = Orientation.Horizontal
    sp_btns_r.HorizontalAlignment = SW.HorizontalAlignment.Right
    sp_btns_r.Margin = Thickness(0, 0, 10, 0)

    if folder and os.path.isdir(folder):
        btn_open = Button(); btn_open.Content = u"Ouvrir le dossier"
        btn_open.Height = 26; btn_open.Padding = Thickness(10, 0, 10, 0)
        btn_open.Margin = Thickness(0, 0, 6, 0)
        btn_open.Background = hex_brush("#2ECC71"); btn_open.Foreground = hex_brush("#FFFFFF")
        btn_open.FontWeight = SW.FontWeights.SemiBold; btn_open.BorderThickness = Thickness(0)
        def on_open(s, e): open_folder(folder); win.Close()
        btn_open.Click += on_open
        sp_btns_r.Children.Add(btn_open)

    sp_btns_r.Children.Add(btn_ok)
    grid_f.Children.Add(sp_btns_r); footer.Child = grid_f
    win.ShowDialog()

# =============================================================================
# Fenetre de progression (export multiple)
# =============================================================================
def make_progress_win(total):
    win = Window(); win.Title = TOOL_NAME; win.Width = 400; win.Height = 130
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")
    sp = StackPanel(); sp.Margin = Thickness(16, 14, 16, 10); win.Content = sp
    lbl = TextBlock(); lbl.FontSize = 11; lbl.Margin = Thickness(0, 0, 0, 6); sp.Children.Add(lbl)
    from System.Windows.Controls import ProgressBar
    pb = ProgressBar(); pb.Minimum = 0; pb.Maximum = total; pb.Value = 0
    pb.Height = 18; pb.Margin = Thickness(0, 0, 0, 6); sp.Children.Add(pb)
    lbl_prog = TextBlock(); lbl_prog.FontSize = 10
    lbl_prog.Foreground = hex_brush("#555555"); sp.Children.Add(lbl_prog)
    ftr = TextBlock()
    ftr.Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    ftr.FontSize = 9; ftr.Foreground = hex_brush("#888888")
    ftr.Margin = Thickness(0, 6, 0, 0)
    ftr.HorizontalAlignment = SW.HorizontalAlignment.Right; sp.Children.Add(ftr)
    win.Show()
    return win, lbl, pb, lbl_prog

# =============================================================================
# POINT D'ENTREE
# =============================================================================
def main():
    active_view = uidoc.ActiveView

    if active_view is None or active_view.IsTemplate:
        MessageBox.Show(
            u"La vue active est invalide ou est un gabarit.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    # ── CAS 1 : Vue simple (non-feuille) — comportement v1.1.0 ───────────────
    if not isinstance(active_view, ViewSheet):
        if not active_view.CanBePrinted:
            MessageBox.Show(
                u"La vue active ({}) ne peut pas être exportée.".format(active_view.Name),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        _export_single_view(active_view)
        return

    # ── CAS 2 : Feuille active — fenetre multi-selection ────────────────────
    all_sheets = collect_all_sheets()
    if not all_sheets:
        MessageBox.Show(
            u"Aucune feuille trouvée dans le projet.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)
        return

    params = show_multi_export_dialog(all_sheets, active_view.Id)
    if params is None:
        return

    _export_multiple(params)


# =============================================================================
# Export vue simple (comportement v1.1.0)
# =============================================================================
def _export_single_view(view):
    from _single_view_dialog import ExportSingleDialog  # inline ci-dessous
    pass  # remplace par la logique inline


# Classe dialog vue simple (inlinee pour eviter les imports croisés)
class ExportSingleDialog(Window):
    def __init__(self, view):
        self._view     = view
        self._is_sheet = isinstance(view, ViewSheet)
        self._result   = None
        if self._is_sheet:
            self._filename, self._missing = build_filename_sheet(view)
        else:
            self._filename = build_filename_view(view)
            self._missing  = []
        self.Title  = TOOL_NAME
        self.Width  = 720; self.Height = 540
        self.MinWidth = 580; self.MinHeight = 440
        self.ResizeMode = SW.ResizeMode.CanResizeWithGrip
        self.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        self.Background = hex_brush("#FFFFFF")
        self._build_ui()

    def _build_ui(self):
        root = Grid()
        root.RowDefinitions.Add(self._rd("Auto"))
        root.RowDefinitions.Add(self._rd("*"))
        root.RowDefinitions.Add(self._rd("Auto"))
        self.Content = root

        # Barre titre
        title_bar = Border(); title_bar.Background = hex_brush("#2F6496")
        title_bar.Padding = Thickness(14, 9, 14, 9)
        Grid.SetRow(title_bar, 0); root.Children.Add(title_bar)
        sp_t = StackPanel(); sp_t.Orientation = Orientation.Horizontal
        icon = TextBlock()
        icon.Text = (u"\U0001f4c4  " if self._is_sheet else u"\U0001f5bc  ")
        icon.FontSize = 15; icon.Foreground = hex_brush("#FFFFFF")
        icon.VerticalAlignment = SW.VerticalAlignment.Center; sp_t.Children.Add(icon)
        mode = u"Feuille active" if self._is_sheet else u"Vue active"
        tb_t = TextBlock()
        tb_t.Text = u"Export PDF / DWG — {}  |  Revit {}".format(mode, app.VersionNumber)
        tb_t.FontSize = 13; tb_t.FontWeight = SW.FontWeights.SemiBold
        tb_t.Foreground = hex_brush("#FFFFFF")
        tb_t.VerticalAlignment = SW.VerticalAlignment.Center; sp_t.Children.Add(tb_t)
        title_bar.Child = sp_t

        # Corps scrollable
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility   = SWC.ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = SWC.ScrollBarVisibility.Disabled
        scroll.Padding = Thickness(14, 10, 14, 6)
        Grid.SetRow(scroll, 1); root.Children.Add(scroll)
        sp = StackPanel(); scroll.Content = sp

        # Info vue / feuille
        lbl_sec = u"Feuille active" if self._is_sheet else u"Vue active"
        sp.Children.Add(self._hdr(lbl_sec))
        grp = self._grpbox(); sp_info = StackPanel()
        if self._is_sheet:
            sp_info.Children.Add(self._row(u"N° feuille",
                get_bip_str(self._view, BuiltInParameter.SHEET_NUMBER) or u""))
            sp_info.Children.Add(self._row(u"Nom",
                get_bip_str(self._view, BuiltInParameter.SHEET_NAME) or u""))
        else:
            sp_info.Children.Add(self._row(u"Type", str(self._view.ViewType)))
            sp_info.Children.Add(self._row(u"Nom", self._view.Name or u""))
        grp.Child = sp_info; sp.Children.Add(grp)

        # Nom du fichier
        sp.Children.Add(self._hdr(u"Nom du fichier généré"))
        grp2 = self._grpbox()
        tb_f = TextBlock(); tb_f.Text = self._filename; tb_f.FontSize = 11
        tb_f.FontFamily = FontFamily("Consolas"); tb_f.TextWrapping = SW.TextWrapping.Wrap
        tb_f.Foreground = hex_brush("#C0392B") if self._missing else hex_brush("#1a3a5c")
        tb_f.FontWeight = SW.FontWeights.SemiBold; grp2.Child = tb_f; sp.Children.Add(grp2)

        # Parametres manquants
        if self._missing:
            sp.Children.Add(self._hdr(u"⚠  Paramètres non renseignés", warn=True))
            wb = Border(); wb.Background = hex_brush("#FFF3CD")
            wb.BorderBrush = hex_brush("#E67E22"); wb.BorderThickness = Thickness(1)
            wb.Padding = Thickness(10, 8, 10, 8); wb.Margin = Thickness(0, 0, 0, 10)
            spw = StackPanel()
            for m in self._missing:
                t = TextBlock(); t.Text = u"•  " + m; t.FontSize = 11
                t.Foreground = hex_brush("#7D3C00"); t.Margin = Thickness(0, 1, 0, 1)
                spw.Children.Add(t)
            wb.Child = spw; sp.Children.Add(wb)

        # Dossier
        sp.Children.Add(self._hdr(u"Dossier de destination"))
        grp3 = self._grpbox(); dp = DockPanel(); dp.LastChildFill = True
        btn_br = Button(); btn_br.Content = u"Parcourir..."; btn_br.Width = 100
        btn_br.Height = 26; btn_br.Margin = Thickness(6, 0, 0, 0)
        btn_br.Background = hex_brush("#3498DB"); btn_br.Foreground = hex_brush("#FFFFFF")
        btn_br.FontWeight = SW.FontWeights.SemiBold; btn_br.BorderThickness = Thickness(0)
        btn_br.Click += self._on_browse
        DockPanel.SetDock(btn_br, SWC.Dock.Right); dp.Children.Add(btn_br)
        self.tb_folder = TextBlock(); self.tb_folder.FontSize = 11
        self.tb_folder.TextWrapping = SW.TextWrapping.Wrap
        self.tb_folder.VerticalAlignment = SW.VerticalAlignment.Center
        self.tb_folder.Text = self._default_folder()
        self.tb_folder.Foreground = hex_brush("#333333"); self.tb_folder.Margin = Thickness(0, 2, 0, 2)
        dp.Children.Add(self.tb_folder); grp3.Child = dp; sp.Children.Add(grp3)

        # Format
        sp.Children.Add(self._hdr(u"Format d'export"))
        grp4 = self._grpbox(); spf = StackPanel(); spf.Orientation = Orientation.Horizontal
        self.chk_pdf = CheckBox(); self.chk_pdf.IsChecked = True
        self.chk_pdf.Content = u"PDF"; self.chk_pdf.FontSize = 13
        self.chk_pdf.FontWeight = SW.FontWeights.SemiBold; self.chk_pdf.Margin = Thickness(0, 0, 30, 0)
        self.chk_pdf.VerticalAlignment = SW.VerticalAlignment.Center; spf.Children.Add(self.chk_pdf)
        self.chk_dwg = CheckBox(); self.chk_dwg.IsChecked = True
        self.chk_dwg.Content = u"DWG (AutoCAD 2018)"; self.chk_dwg.FontSize = 13
        self.chk_dwg.FontWeight = SW.FontWeights.SemiBold
        self.chk_dwg.VerticalAlignment = SW.VerticalAlignment.Center; spf.Children.Add(self.chk_dwg)
        grp4.Child = spf; sp.Children.Add(grp4)

        # Footer
        footer = Border(); footer.BorderThickness = Thickness(0, 1, 0, 0)
        footer.BorderBrush = hex_brush("#C0D0E0"); footer.Background = hex_brush("#F5F5F5")
        footer.Padding = Thickness(0, 6, 0, 6); Grid.SetRow(footer, 2); root.Children.Add(footer)
        gf = Grid()
        lf = TextBlock(); lf.Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
        lf.FontSize = 10; lf.Foreground = hex_brush("#888888")
        lf.VerticalAlignment = SW.VerticalAlignment.Center; lf.Margin = Thickness(10, 0, 0, 0)
        gf.Children.Add(lf)
        spb = StackPanel(); spb.Orientation = Orientation.Horizontal
        spb.HorizontalAlignment = SW.HorizontalAlignment.Right; spb.Margin = Thickness(0, 0, 10, 0)
        bc = self._btn(u"Annuler", "#E74C3C", 90, lambda s, e: self.Close())
        bc.Margin = Thickness(0, 0, 6, 0); spb.Children.Add(bc)
        spb.Children.Add(self._btn(u"Exporter", "#E67E22", 100, self._on_export))
        gf.Children.Add(spb); footer.Child = gf

    def _rd(self, h):
        rd = RowDefinition()
        rd.Height = GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto
        return rd

    def _hdr(self, text, warn=False):
        tb = TextBlock(); tb.Text = text; tb.FontSize = 11; tb.FontWeight = SW.FontWeights.SemiBold
        tb.Foreground = hex_brush("#E67E22") if warn else hex_brush("#2F6496")
        tb.Margin = Thickness(0, 6, 0, 3); return tb

    def _grpbox(self):
        gb = Border(); gb.BorderBrush = hex_brush("#C0D0E0"); gb.BorderThickness = Thickness(1)
        gb.Background = hex_brush("#FAFCFF"); gb.Padding = Thickness(10, 8, 10, 8)
        gb.Margin = Thickness(0, 0, 0, 8); return gb

    def _row(self, label, value):
        sp = StackPanel(); sp.Orientation = Orientation.Horizontal; sp.Margin = Thickness(0, 1, 0, 1)
        tl = TextBlock(); tl.Text = label + u" : "; tl.FontSize = 11
        tl.FontWeight = SW.FontWeights.SemiBold; tl.Foreground = hex_brush("#555555"); tl.Width = 90
        sp.Children.Add(tl)
        tv = TextBlock(); tv.Text = value; tv.FontSize = 11; tv.Foreground = hex_brush("#111111")
        sp.Children.Add(tv); return sp

    def _btn(self, text, color, width, handler):
        b = Button(); b.Content = text; b.Width = width; b.Height = 28
        b.Background = hex_brush(color); b.Foreground = hex_brush("#FFFFFF")
        b.FontWeight = SW.FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler; return b

    def _default_folder(self):
        last = load_last_folder()
        if last: return last
        if doc.PathName: return os.path.dirname(doc.PathName)
        return System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)

    def _on_browse(self, s, e):
        dlg = FolderBrowserDialog()
        dlg.SelectedPath = self.tb_folder.Text; dlg.Description = u"Dossier de destination"
        if dlg.ShowDialog() == DialogResult.OK: self.tb_folder.Text = dlg.SelectedPath

    def _on_export(self, s, e):
        export_pdf = bool(self.chk_pdf.IsChecked)
        export_dwg = bool(self.chk_dwg.IsChecked)
        if not export_pdf and not export_dwg:
            MessageBox.Show(u"Sélectionnez au moins un format.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Warning); return
        folder = self.tb_folder.Text.strip()
        if not os.path.isdir(folder):
            MessageBox.Show(u"Dossier invalide :\n{}".format(folder), TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error); return
        if self._missing:
            res = MessageBox.Show(
                u"Paramètres manquants, le nom contiendra '???'.\nContinuer ?",
                u"Paramètres manquants", MessageBoxButton.YesNo, MessageBoxImage.Warning)
            if str(res) != "Yes": return
        to_check = []
        if export_pdf: to_check.append((os.path.join(folder, self._filename + ".pdf"), "PDF"))
        if export_dwg: to_check.append((os.path.join(folder, self._filename + ".dwg"), "DWG"))
        existing = [lbl for path, lbl in to_check if os.path.isfile(path)]
        if existing and not _confirm_overwrite(existing): return
        save_last_folder(folder)
        self._result = {"folder": folder, "filename": self._filename,
                        "export_pdf": export_pdf, "export_dwg": export_dwg,
                        "view_id": self._view.Id}
        self.Close()

    @property
    def result(self): return self._result


def _export_single_view(view):
    dlg = ExportSingleDialog(view)
    dlg.ShowDialog()
    params = dlg.result; dlg = None
    if params is None: return

    folder = params["folder"]; filename = params["filename"]
    view_id = params["view_id"]; successes = []; errors = []

    if params["export_pdf"]:
        try:
            if do_export_pdf(folder, filename, view_id):
                successes.append(u"PDF : {}".format(os.path.join(folder, filename + ".pdf")))
            else:
                errors.append(u"PDF : export a retourné False.")
        except Exception as ex:
            errors.append(u"PDF : " + str(ex)); print(traceback.format_exc())

    if params["export_dwg"]:
        try:
            if do_export_dwg(folder, filename, view_id):
                successes.append(u"DWG : {}".format(os.path.join(folder, filename + ".dwg")))
            else:
                errors.append(u"DWG : export a retourné False.")
        except Exception as ex:
            errors.append(u"DWG : " + str(ex)); print(traceback.format_exc())

    show_result(successes, errors, folder=folder)


# =============================================================================
# Export multiple feuilles avec progression
# =============================================================================
def _export_multiple(params):
    folder     = params["folder"]
    rows       = params["rows"]
    export_pdf = params["export_pdf"]
    export_dwg = params["export_dwg"]

    successes = []
    errors    = []
    skipped   = []

    prog_win, lbl_prog, pb_prog, lbl_detail = make_progress_win(len(rows))
    disp = prog_win.Dispatcher

    try:
        for idx, row in enumerate(rows):
            filename, _ = build_filename_sheet(row._sheet)
            lbl_prog.Text  = u"Export {}/{}  —  {}".format(idx + 1, len(rows), row.SheetName)
            lbl_detail.Text = filename
            pb_prog.Value   = idx
            do_events(disp)

            # Verifier ecrasement (traitement silencieux en mode batch)
            to_check = []
            if export_pdf: to_check.append((os.path.join(folder, filename + ".pdf"), "PDF"))
            if export_dwg: to_check.append((os.path.join(folder, filename + ".dwg"), "DWG"))
            existing = [lbl for path, lbl in to_check if os.path.isfile(path)]
            if existing:
                if not _confirm_overwrite(existing):
                    skipped.append(u"{} ({}) — ignorée".format(
                        row.SheetNum, row.SheetName))
                    row.Status = u"⚠ Ignorée"
                    continue

            sheet_ok = True
            if export_pdf:
                try:
                    if do_export_pdf(folder, filename, row._sheet.Id):
                        successes.append(u"PDF : {}".format(filename))
                    else:
                        errors.append(u"PDF [{}] : False".format(row.SheetNum))
                        sheet_ok = False
                except Exception as ex:
                    errors.append(u"PDF [{}] : {}".format(row.SheetNum, str(ex)))
                    sheet_ok = False

            if export_dwg:
                try:
                    if do_export_dwg(folder, filename, row._sheet.Id):
                        successes.append(u"DWG : {}".format(filename))
                    else:
                        errors.append(u"DWG [{}] : False".format(row.SheetNum))
                        sheet_ok = False
                except Exception as ex:
                    errors.append(u"DWG [{}] : {}".format(row.SheetNum, str(ex)))
                    sheet_ok = False

            row.Status = u"✔ Exporté" if sheet_ok else u"✘ Erreur"
            pb_prog.Value = idx + 1
            do_events(disp)

    finally:
        prog_win.Close()

    show_result(successes, errors, skipped, folder=folder)


main()
