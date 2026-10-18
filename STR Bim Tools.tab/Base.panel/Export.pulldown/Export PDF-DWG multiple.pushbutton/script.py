# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.4.2"
SCRIPT_AUTHOR  = "Tony Varin"
TOOL_NAME      = "Export PDF-DWG multiple"
# =============================================================================
#  v2.3.0 — Ouvre TOUJOURS la fenetre multi-selection (le fallback vue simple
#           est supprime : il faisait double emploi avec Export PDF-DWG Vue
#           Active et donnait l'impression de lancer le mauvais script).
#  v2.2.0 — Option PDF combine : toutes les feuilles selectionnees en un seul PDF,
#           nom saisi dans une fenetre dediee.
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

import str_progress_revit
import str_progress_sta

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

def do_export_pdf_combined(folder, filename, view_ids):
    """Exporte plusieurs feuilles en un seul fichier PDF combine."""
    opts                    = PDFExportOptions()
    opts.FileName           = filename
    opts.Combine            = True
    opts.HideCropBoundaries = False
    ids = List[ElementId]()
    for vid in view_ids:
        ids.Add(vid)
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
        <StackPanel Grid.Column="3" Orientation="Horizontal" VerticalAlignment="Center">
          <CheckBox x:Name="chk_pdf" IsChecked="True"
                    VerticalAlignment="Center" FontSize="13" FontWeight="SemiBold"
                    Margin="0,0,10,0"/>
          <CheckBox x:Name="chk_pdf_combine" IsChecked="False"
                    VerticalAlignment="Center" FontSize="11"
                    Margin="0,0,20,0"/>
        </StackPanel>
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
    window.FindName("chk_pdf").Content         = u"PDF"
    window.FindName("chk_pdf_combine").Content = u"(combiner en 1 fichier)"
    window.FindName("chk_dwg").Content         = u"DWG (AutoCAD 2018)"

    chk_pdf         = window.FindName("chk_pdf")
    chk_pdf_combine = window.FindName("chk_pdf_combine")

    def update_combine_state(s=None, e=None):
        chk_pdf_combine.IsEnabled = bool(chk_pdf.IsChecked)
        if not bool(chk_pdf.IsChecked):
            chk_pdf_combine.IsChecked = False

    chk_pdf.Checked   += update_combine_state
    chk_pdf.Unchecked += update_combine_state
    update_combine_state()
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

        export_pdf     = bool(window.FindName("chk_pdf").IsChecked)
        export_dwg     = bool(window.FindName("chk_dwg").IsChecked)
        pdf_combine    = bool(window.FindName("chk_pdf_combine").IsChecked)
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
            "folder"      : folder,
            "rows"        : rows_to_export,
            "export_pdf"  : export_pdf,
            "export_dwg"  : export_dwg,
            "pdf_combine" : pdf_combine,
        }
        window.Close()

    window.FindName("btn_export").Click += on_export
    window.FindName("btn_cancel").Click += lambda s, e: window.Close()

    window.ShowDialog()
    return state["result"]

# =============================================================================
# Fenetre saisie nom PDF combine
# =============================================================================
def ask_combined_pdf_name(folder, nb_sheets):
    """Demande le nom du PDF combine. Retourne le chemin complet ou None si annule."""
    default_name = (doc.Title or u"Projet").replace(u" ", u"_") + u"_Plans"

    XAML_NAME = """<Window
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="480" SizeToContent="Height"
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
        <StackPanel Grid.Row="1" Margin="18,16,18,12">
          <TextBlock x:Name="lbl_info" FontSize="11" Foreground="#555555"
                     TextWrapping="Wrap" Margin="0,0,0,14"/>
          <TextBlock x:Name="lbl_name_lbl" FontSize="11" FontWeight="SemiBold"
                     Margin="0,0,0,5"/>
          <TextBox x:Name="txt_name" Height="30" FontSize="12"
                   VerticalContentAlignment="Center" Padding="6,0"
                   BorderBrush="#A0B8D0" Margin="0,0,0,5"/>
          <TextBlock x:Name="lbl_preview" FontSize="10" Foreground="#2F6496"
                     TextWrapping="Wrap"/>
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
              <Button x:Name="btn_ok" Width="130" Height="28"
                      Background="#E67E22" Foreground="White"
                      FontWeight="SemiBold" BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML_NAME))
    win    = System.Windows.Markup.XamlReader.Load(stream)
    win.Title = TOOL_NAME

    win.FindName("lbl_titre").Text    = u"Nom du PDF combine"
    win.FindName("lbl_info").Text     = (
        u"{} feuille(s) selectionnee(s) seront combinees en un seul fichier PDF.\n"
        u"Dossier de destination : {}".format(nb_sheets, folder)
    )
    win.FindName("lbl_name_lbl").Text = u"Nom du fichier (sans extension) :"
    win.FindName("lbl_footer").Text   = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    win.FindName("btn_cancel").Content = u"Annuler"
    win.FindName("btn_ok").Content     = u"Exporter"

    txt_name   = win.FindName("txt_name")
    lbl_preview = win.FindName("lbl_preview")
    txt_name.Text = default_name

    def update_preview(s=None, e=None):
        n = txt_name.Text.strip()
        if n:
            lbl_preview.Text = u"Fichier : {}.pdf".format(n)
        else:
            lbl_preview.Text = u"Entrez un nom valide."

    txt_name.TextChanged += update_preview
    update_preview()

    state = {"path": None}

    def on_ok(s, e):
        name = txt_name.Text.strip()
        if not name:
            MessageBox.Show(u"Le nom ne peut pas etre vide.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        for ch in ['\\', '/', '*', '?', ':', '"', '<', '>', '|']:
            name = name.replace(ch, u'_')
        output_path = os.path.join(folder, name + u".pdf")
        if os.path.isfile(output_path):
            res = MessageBox.Show(
                u"Le fichier suivant existe deja :\n{}\n\nL'ecraser ?".format(output_path),
                TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Warning)
            from System.Windows import MessageBoxResult
            if res != MessageBoxResult.Yes:
                return
        state["path"] = output_path
        win.Close()

    win.FindName("btn_ok").Click     += on_ok
    win.FindName("btn_cancel").Click += lambda s, e: win.Close()

    # Valider avec Entree
    txt_name.KeyDown += lambda s, e: (on_ok(s, e) if str(e.Key) == "Return" else None)

    win.ShowDialog()
    return state["path"]

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
# La progression passe par str_progress_sta : la fenetre vit sur son propre
# thread STA et reste donc peinte pendant doc.Export, qui bloque le thread de
# Revit. L'ancienne fenetre construite ici tournait sur le thread principal avec
# do_events() : elle se figeait a chaque feuille, precisement pendant le temps
# qu'il fallait afficher.
#
# str_progress_revit y ajoute la progression REELLE de 0 a 100 % publiee par
# l'exporteur, et la fenetre apporte un bouton Annuler.

# =============================================================================
# POINT D'ENTREE
# =============================================================================
def main():
    # Toujours la fenetre multi-selection, quelle que soit la vue active
    # (l'export de la vue courante a son propre bouton : Export PDF-DWG Vue Active)
    all_sheets = collect_all_sheets()
    if not all_sheets:
        MessageBox.Show(
            u"Aucune feuille trouvée dans le projet.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)
        return

    params = show_multi_export_dialog(all_sheets)
    if params is None:
        return

    _export_multiple(params)


# =============================================================================
# Export multiple feuilles avec progression
# =============================================================================
def _export_multiple(params):
    folder      = params["folder"]
    rows        = params["rows"]
    export_pdf  = params["export_pdf"]
    export_dwg  = params["export_dwg"]
    pdf_combine = params.get("pdf_combine", False)

    successes = []
    errors    = []
    skipped   = []

    # Mode PDF combine : demander le nom avant de lancer
    combined_pdf_path = None
    if export_pdf and pdf_combine:
        combined_pdf_path = ask_combined_pdf_name(folder, len(rows))
        if combined_pdf_path is None:
            return  # annule par l'utilisateur

    # topmost=False : ce script demande confirmation d'ecrasement PENDANT la
    # boucle. Une fenetre au premier plan appartenant a un autre thread masque
    # la MessageBox modale, et l'export parait fige alors qu'il attend un clic.
    prog = str_progress_sta.ProgressionSTA(len(rows), TOOL_NAME, SCRIPT_VERSION,
                                           topmost=False)
    suivi = str_progress_revit.SuiviProgressionRevit(prog, app)
    suivi.brancher()

    try:
        # PDF COMBINE : un seul export pour toutes les feuilles
        if export_pdf and pdf_combine:
            prog.debut_element(
                u"PDF combine ({} feuilles) - {}".format(
                    len(rows), os.path.basename(combined_pdf_path)), 0)
            try:
                view_ids      = [r._sheet.Id for r in rows]
                combined_name = os.path.splitext(os.path.basename(combined_pdf_path))[0]
                if do_export_pdf_combined(folder, combined_name, view_ids):
                    successes.append(u"PDF combine : {}".format(combined_pdf_path))
                    for r in rows:
                        r.Status = u"✔ Dans PDF combine"
                else:
                    errors.append(u"PDF combine : l'export a retourne False.")
                    for r in rows:
                        r.Status = u"✘ Erreur PDF"
            except Exception as ex:
                errors.append(u"PDF combine : {}".format(str(ex)))
                print(traceback.format_exc())
                for r in rows:
                    r.Status = u"✘ Erreur PDF"
            prog.fin_element(len(rows))

        # DWG + PDF individuel (si mode non-combine)
        for idx, row in enumerate(rows):
            if prog.annulation_demandee:
                for reste in rows[idx:]:
                    if not reste.Status:
                        reste.Status = u"⚠ Annulée"
                    skipped.append(u"{} ({}) — annulée".format(
                        reste.SheetNum, reste.SheetName))
                break

            filename, _ = build_filename_sheet(row._sheet)
            prog.debut_element(u"{}  —  {}".format(row.SheetNum, row.SheetName),
                               idx)

            sheet_ok = True

            if export_pdf and not pdf_combine:
                to_check = [(os.path.join(folder, filename + ".pdf"), "PDF")]
                if export_dwg:
                    to_check.append((os.path.join(folder, filename + ".dwg"), "DWG"))
                existing = [lbl for path, lbl in to_check if os.path.isfile(path)]
                if existing:
                    if not _confirm_overwrite(existing):
                        skipped.append(u"{} ({}) — ignorée".format(
                            row.SheetNum, row.SheetName))
                        row.Status = u"⚠ Ignorée"
                        prog.fin_element(idx + 1)
                        continue
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
                if pdf_combine:
                    dwg_path = os.path.join(folder, filename + ".dwg")
                    if os.path.isfile(dwg_path):
                        if not _confirm_overwrite([u"DWG : " + filename]):
                            skipped.append(u"{} ({}) — DWG ignoré".format(
                                row.SheetNum, row.SheetName))
                            row.Status = u"⚠ DWG ignoré"
                            prog.fin_element(idx + 1)
                            continue
                try:
                    if do_export_dwg(folder, filename, row._sheet.Id):
                        successes.append(u"DWG : {}".format(filename))
                    else:
                        errors.append(u"DWG [{}] : False".format(row.SheetNum))
                        sheet_ok = False
                except Exception as ex:
                    errors.append(u"DWG [{}] : {}".format(row.SheetNum, str(ex)))
                    sheet_ok = False

            if not pdf_combine:
                row.Status = u"✔ Exporté" if sheet_ok else u"✘ Erreur"
            elif export_dwg:
                row.Status = u"✔ DWG exporté" if sheet_ok else u"✘ Erreur DWG"
            prog.fin_element(idx + 1)

    finally:
        suivi.debrancher()
        prog.fermer()

    show_result(successes, errors, skipped, folder=folder)


main()
