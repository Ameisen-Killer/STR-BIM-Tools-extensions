# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Export PDF / DWG"
# =============================================================================

import clr, os, io, json, traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")

import System
from System.Collections.Generic import List
from System.Windows.Forms import FolderBrowserDialog, DialogResult
import System.Windows as SW
import System.Windows.Controls as SWC
from System.Windows import (
    Thickness, GridLength, GridUnitType, Window,
    MessageBox, MessageBoxButton, MessageBoxImage,
)
from System.Windows.Controls import (
    Grid, StackPanel, Border, TextBlock, Button, Label,
    CheckBox, GroupBox, DockPanel, ScrollViewer,
    RowDefinition, ColumnDefinition, Orientation,
)
from System.Windows.Media import SolidColorBrush, Color, FontFamily

from Autodesk.Revit.DB import (
    BuiltInParameter,
    PDFExportOptions,
    DWGExportOptions,
    ACADVersion,
    ElementId,
    ViewSheet,
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
# Helpers couleur
# =============================================================================
def hex_brush(h):
    h = h.lstrip("#")
    return SolidColorBrush(Color.FromRgb(
        int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ))

# =============================================================================
# Lecture des parametres de la feuille
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

# Ordre des segments GED dans le nom de fichier
GED_PARAMS = [
    ("SPVA_GED_A-PROJET",          u"A – Projet"),
    ("SPVA_GED_B-DISCIPLINE",      u"B – Discipline"),
    ("SPVA_GED_C-EMMETEUR",        u"C – Emetteur"),
    ("SPVA_GED_D-PHASE SIA",       u"D – Phase SIA"),
    ("SPVA_GED_E-TYPE",            u"E – Type"),
    ("SPVA_GED_F-CODE ETAGE",      u"F – Code Etage"),
    ("SPVA_GED_G-ZONE IMPRESSION", u"G – Zone Impression"),
    ("SPVA_GED_H-NUMERO",          u"H – Numéro"),
]

def build_filename(sheet):
    """
    Retourne (filename_sans_ext, liste_params_manquants).
    Format : {A}-{B}-{C}-{D}-{E}-{F}-{G}-{H}-{Rev}_{NomFeuille} - {Description}
    """
    vals = {}
    missing = []

    for pname, label in GED_PARAMS:
        v = get_param_str(sheet, pname)
        if v:
            vals[pname] = v
        else:
            missing.append(label)
            vals[pname] = u"???"

    rev = get_bip_str(sheet, BuiltInParameter.SHEET_CURRENT_REVISION)
    if not rev:
        missing.append(u"Révision actuelle")
        rev = u"??"

    sheet_name = get_bip_str(sheet, BuiltInParameter.SHEET_NAME)
    if not sheet_name:
        missing.append(u"Nom de la feuille")
        sheet_name = u"???"

    desc = get_param_str(sheet, u"#STR_CAR_Description du plan")
    if not desc:
        missing.append(u"#STR_CAR_Description du plan")
        desc = u"???"

    prefix = u"{}-{}-{}-{}-{}-{}-{}-{}-{}".format(
        vals["SPVA_GED_A-PROJET"],
        vals["SPVA_GED_B-DISCIPLINE"],
        vals["SPVA_GED_C-EMMETEUR"],
        vals["SPVA_GED_D-PHASE SIA"],
        vals["SPVA_GED_E-TYPE"],
        vals["SPVA_GED_F-CODE ETAGE"],
        vals["SPVA_GED_G-ZONE IMPRESSION"],
        vals["SPVA_GED_H-NUMERO"],
        rev,
    )
    filename = u"{}_{} - {}".format(prefix, sheet_name, desc)
    return filename, missing

# =============================================================================
# Fenetre WPF
# =============================================================================
class ExportDialog(Window):

    def __init__(self, sheet):
        self._sheet    = sheet
        self._result   = None
        self._filename, self._missing = build_filename(sheet)

        self.Title    = TOOL_NAME
        self.Width    = 720
        self.Height   = 560
        self.MinWidth  = 580
        self.MinHeight = 460
        self.ResizeMode = SW.ResizeMode.CanResizeWithGrip
        self.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        self.Background = hex_brush("#FFFFFF")

        self._build_ui()

    # -------------------------------------------------------------------------
    # Construction UI
    # -------------------------------------------------------------------------
    def _build_ui(self):
        root = Grid()
        root.RowDefinitions.Add(self._rd("Auto"))   # barre titre
        root.RowDefinitions.Add(self._rd("*"))       # contenu scroll
        root.RowDefinitions.Add(self._rd("Auto"))   # footer
        self.Content = root

        # ── Barre titre ──────────────────────────────────────────────────────
        title_bar         = Border()
        title_bar.Background  = hex_brush("#2F6496")
        title_bar.Padding     = Thickness(14, 9, 14, 9)
        Grid.SetRow(title_bar, 0)
        root.Children.Add(title_bar)

        sp_title = StackPanel()
        sp_title.Orientation = Orientation.Horizontal

        tb_icon = TextBlock()
        tb_icon.Text       = u"\U0001f4c4  "
        tb_icon.FontSize   = 15
        tb_icon.Foreground = hex_brush("#FFFFFF")
        tb_icon.VerticalAlignment = SW.VerticalAlignment.Center
        sp_title.Children.Add(tb_icon)

        tb_title = TextBlock()
        tb_title.Text       = u"Export PDF / DWG — Feuille active  |  Revit {}".format(
            app.VersionNumber)
        tb_title.FontSize   = 13
        tb_title.FontWeight = SW.FontWeights.SemiBold
        tb_title.Foreground = hex_brush("#FFFFFF")
        tb_title.VerticalAlignment = SW.VerticalAlignment.Center
        sp_title.Children.Add(tb_title)

        title_bar.Child = sp_title

        # ── Contenu (scrollable) ─────────────────────────────────────────────
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility   = SWC.ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = SWC.ScrollBarVisibility.Disabled
        scroll.Padding = Thickness(14, 10, 14, 6)
        Grid.SetRow(scroll, 1)
        root.Children.Add(scroll)

        sp_main = StackPanel()
        scroll.Content = sp_main

        # ── Section : Feuille active ─────────────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Feuille active"))

        grp_sheet = self._group_box()
        sp_sheet  = StackPanel()

        sheet_num  = get_bip_str(self._sheet, BuiltInParameter.SHEET_NUMBER) or u""
        sheet_name = get_bip_str(self._sheet, BuiltInParameter.SHEET_NAME)   or u""

        row_num  = self._info_row(u"N° feuille", sheet_num)
        row_name = self._info_row(u"Nom",            sheet_name)
        sp_sheet.Children.Add(row_num)
        sp_sheet.Children.Add(row_name)
        grp_sheet.Child = sp_sheet
        sp_main.Children.Add(grp_sheet)

        # ── Section : Nom du fichier genere ──────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Nom du fichier généré"))

        grp_fname     = self._group_box()
        tb_fname      = TextBlock()
        tb_fname.Text = self._filename
        tb_fname.FontSize    = 11
        tb_fname.FontFamily  = FontFamily("Consolas")
        tb_fname.TextWrapping = SW.TextWrapping.Wrap
        tb_fname.Foreground  = (hex_brush("#C0392B") if self._missing
                                else hex_brush("#1a3a5c"))
        tb_fname.FontWeight  = SW.FontWeights.SemiBold
        grp_fname.Child      = tb_fname
        sp_main.Children.Add(grp_fname)

        # ── Section : Parametres manquants (conditionnelle) ──────────────────
        if self._missing:
            sp_main.Children.Add(
                self._section_hdr(u"⚠  Paramètres non renseignés", warn=True))

            warn_brd = Border()
            warn_brd.Background      = hex_brush("#FFF3CD")
            warn_brd.BorderBrush     = hex_brush("#E67E22")
            warn_brd.BorderThickness = Thickness(1)
            warn_brd.Padding         = Thickness(10, 8, 10, 8)
            warn_brd.Margin          = Thickness(0, 0, 0, 10)

            sp_warn = StackPanel()
            for m in self._missing:
                tb_m           = TextBlock()
                tb_m.Text      = u"•  {}".format(m)
                tb_m.FontSize  = 11
                tb_m.Foreground = hex_brush("#7D3C00")
                tb_m.Margin    = Thickness(0, 1, 0, 1)
                sp_warn.Children.Add(tb_m)

            warn_brd.Child = sp_warn
            sp_main.Children.Add(warn_brd)

        # ── Section : Dossier de destination ─────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Dossier de destination"))

        grp_folder    = self._group_box()
        dp_folder     = DockPanel()
        dp_folder.LastChildFill = True

        btn_browse = Button()
        btn_browse.Content         = u"Parcourir..."
        btn_browse.Width           = 100
        btn_browse.Height          = 26
        btn_browse.Margin          = Thickness(6, 0, 0, 0)
        btn_browse.Background      = hex_brush("#3498DB")
        btn_browse.Foreground      = hex_brush("#FFFFFF")
        btn_browse.FontWeight      = SW.FontWeights.SemiBold
        btn_browse.BorderThickness = Thickness(0)
        btn_browse.Click          += self._on_browse
        DockPanel.SetDock(btn_browse, SWC.Dock.Right)
        dp_folder.Children.Add(btn_browse)

        self.tb_folder              = TextBlock()
        self.tb_folder.FontSize     = 11
        self.tb_folder.TextWrapping = SW.TextWrapping.Wrap
        self.tb_folder.VerticalAlignment = SW.VerticalAlignment.Center
        self.tb_folder.Text         = self._default_folder()
        self.tb_folder.Foreground   = hex_brush("#333333")
        self.tb_folder.Margin       = Thickness(0, 2, 0, 2)
        dp_folder.Children.Add(self.tb_folder)

        grp_folder.Child = dp_folder
        sp_main.Children.Add(grp_folder)

        # ── Section : Format d'export ─────────────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Format d’export"))

        grp_fmt    = self._group_box()
        sp_fmt     = StackPanel()
        sp_fmt.Orientation = Orientation.Horizontal

        self.chk_pdf          = CheckBox()
        self.chk_pdf.IsChecked = True
        self.chk_pdf.Content  = u"PDF"
        self.chk_pdf.FontSize = 13
        self.chk_pdf.FontWeight = SW.FontWeights.SemiBold
        self.chk_pdf.Margin   = Thickness(0, 0, 30, 0)
        self.chk_pdf.VerticalAlignment = SW.VerticalAlignment.Center
        sp_fmt.Children.Add(self.chk_pdf)

        self.chk_dwg           = CheckBox()
        self.chk_dwg.IsChecked = True
        self.chk_dwg.Content   = u"DWG (AutoCAD 2018)"
        self.chk_dwg.FontSize  = 13
        self.chk_dwg.FontWeight = SW.FontWeights.SemiBold
        self.chk_dwg.VerticalAlignment = SW.VerticalAlignment.Center
        sp_fmt.Children.Add(self.chk_dwg)

        grp_fmt.Child = sp_fmt
        sp_main.Children.Add(grp_fmt)

        # ── Footer ────────────────────────────────────────────────────────────
        footer_brd = Border()
        footer_brd.BorderThickness = Thickness(0, 1, 0, 0)
        footer_brd.BorderBrush     = hex_brush("#C0D0E0")
        footer_brd.Background      = hex_brush("#F5F5F5")
        footer_brd.Padding         = Thickness(0, 6, 0, 6)
        Grid.SetRow(footer_brd, 2)
        root.Children.Add(footer_brd)

        grid_footer = Grid()

        lbl_footer            = TextBlock()
        lbl_footer.Text       = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
        lbl_footer.FontSize   = 10
        lbl_footer.Foreground = hex_brush("#888888")
        lbl_footer.VerticalAlignment = SW.VerticalAlignment.Center
        lbl_footer.Margin    = Thickness(10, 0, 0, 0)
        grid_footer.Children.Add(lbl_footer)

        sp_btns = StackPanel()
        sp_btns.Orientation = Orientation.Horizontal
        sp_btns.HorizontalAlignment = SW.HorizontalAlignment.Right
        sp_btns.Margin = Thickness(0, 0, 10, 0)

        btn_cancel = self._button(
            u"Annuler", "#E74C3C", 90, lambda s, e: self.Close())
        btn_cancel.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(btn_cancel)

        btn_export = self._button(
            u"Exporter", "#E67E22", 100, self._on_export)
        sp_btns.Children.Add(btn_export)

        grid_footer.Children.Add(sp_btns)
        footer_brd.Child = grid_footer

    # -------------------------------------------------------------------------
    # Helpers UI
    # -------------------------------------------------------------------------
    def _rd(self, h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star)
                     if h == "*" else GridLength.Auto)
        return rd

    def _section_hdr(self, text, warn=False):
        tb            = TextBlock()
        tb.Text       = text
        tb.FontSize   = 11
        tb.FontWeight = SW.FontWeights.SemiBold
        tb.Foreground = hex_brush("#E67E22") if warn else hex_brush("#2F6496")
        tb.Margin     = Thickness(0, 6, 0, 3)
        return tb

    def _group_box(self):
        gb              = Border()
        gb.BorderBrush  = hex_brush("#C0D0E0")
        gb.BorderThickness = Thickness(1)
        gb.Background   = hex_brush("#FAFCFF")
        gb.Padding      = Thickness(10, 8, 10, 8)
        gb.Margin       = Thickness(0, 0, 0, 8)
        return gb

    def _info_row(self, label, value):
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Margin      = Thickness(0, 1, 0, 1)

        tb_lbl            = TextBlock()
        tb_lbl.Text       = label + u" : "
        tb_lbl.FontSize   = 11
        tb_lbl.FontWeight = SW.FontWeights.SemiBold
        tb_lbl.Foreground = hex_brush("#555555")
        tb_lbl.Width      = 90
        sp.Children.Add(tb_lbl)

        tb_val            = TextBlock()
        tb_val.Text       = value
        tb_val.FontSize   = 11
        tb_val.Foreground = hex_brush("#111111")
        sp.Children.Add(tb_val)

        return sp

    def _button(self, text, color, width, handler):
        b = Button()
        b.Content         = text
        b.Width           = width
        b.Height          = 28
        b.Background      = hex_brush(color)
        b.Foreground      = hex_brush("#FFFFFF")
        b.FontWeight      = SW.FontWeights.SemiBold
        b.BorderThickness = Thickness(0)
        b.Click          += handler
        return b

    def _default_folder(self):
        last = load_last_folder()
        if last:
            return last
        path = doc.PathName
        if path:
            return os.path.dirname(path)
        import System.Environment as Env
        return Env.GetFolderPath(Env.SpecialFolder.Desktop)

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------
    def _on_browse(self, s, e):
        dlg = FolderBrowserDialog()
        dlg.SelectedPath = self.tb_folder.Text or self._default_folder()
        dlg.Description  = u"Choisir le dossier de destination des fichiers"
        if dlg.ShowDialog() == DialogResult.OK:
            self.tb_folder.Text = dlg.SelectedPath

    def _on_export(self, s, e):
        export_pdf = bool(self.chk_pdf.IsChecked)
        export_dwg = bool(self.chk_dwg.IsChecked)

        if not export_pdf and not export_dwg:
            MessageBox.Show(
                u"Sélectionnez au moins un format d’export (PDF ou DWG).",
                u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
                MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        folder = self.tb_folder.Text.strip()
        if not os.path.isdir(folder):
            MessageBox.Show(
                u"Le dossier spécifié n’existe pas :\n{}".format(folder),
                u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
                MessageBoxButton.OK, MessageBoxImage.Error)
            return

        # Avertissement parametres manquants
        if self._missing:
            res = MessageBox.Show(
                u"Certains paramètres ne sont pas renseignés :\n\n"
                + u"\n".join(u"  •  " + m for m in self._missing)
                + u"\n\nLe nom du fichier contiendra des ‘???’.\nContinuer quand même ?",
                u"Paramètres manquants",
                MessageBoxButton.YesNo, MessageBoxImage.Warning)
            if str(res) != "Yes":
                return

        # Verification fichiers existants
        to_check = []
        if export_pdf:
            to_check.append((
                os.path.join(folder, self._filename + ".pdf"), "PDF"))
        if export_dwg:
            to_check.append((
                os.path.join(folder, self._filename + ".dwg"), "DWG"))

        existing = [lbl for path, lbl in to_check if os.path.isfile(path)]
        if existing:
            if not _confirm_overwrite(existing):
                return

        save_last_folder(folder)
        self._result = {
            "folder"     : folder,
            "filename"   : self._filename,
            "export_pdf" : export_pdf,
            "export_dwg" : export_dwg,
            "sheet_id"   : self._sheet.Id,
        }
        self.Close()

    @property
    def result(self):
        return self._result

# =============================================================================
# Export PDF (API native Revit 2024)
# =============================================================================
def do_export_pdf(folder, filename, sheet_id):
    opts          = PDFExportOptions()
    opts.FileName = filename
    opts.Combine  = True   # seule feuille : Combine=True force l'usage de FileName
    view_ids = List[ElementId]()
    view_ids.Add(sheet_id)
    return doc.Export(folder, view_ids, opts)

# =============================================================================
# Export DWG (AutoCAD 2018)
# =============================================================================
def do_export_dwg(folder, filename, sheet_id):
    opts             = DWGExportOptions()
    opts.FileVersion = ACADVersion.R2018
    opts.MergedViews = True
    view_ids = List[ElementId]()
    view_ids.Add(sheet_id)
    return doc.Export(folder, filename, view_ids, opts)

# =============================================================================
# Fenetre de resultat
# =============================================================================
def _confirm_overwrite(existing_labels):
    """Retourne True si l'utilisateur confirme l'écrasement."""
    state = {"ok": False}

    win = Window()
    win.Title  = u"Fichier(s) existant(s)"
    win.Width  = 420
    win.SizeToContent = SW.SizeToContent.Height
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    root.RowDefinitions.Add(_rd_auto())
    root.RowDefinitions.Add(_rd_auto())
    win.Content = root

    # ── Contenu ──
    sp = StackPanel()
    sp.Margin = Thickness(18, 16, 18, 12)
    Grid.SetRow(sp, 0)
    root.Children.Add(sp)

    tb_msg = TextBlock()
    tb_msg.Text        = u"Le(s) fichier(s) suivant(s) existe(nt) déjà :"
    tb_msg.FontSize    = 12
    tb_msg.FontWeight  = SW.FontWeights.SemiBold
    tb_msg.Foreground  = hex_brush("#333333")
    tb_msg.TextWrapping = SW.TextWrapping.Wrap
    tb_msg.Margin      = Thickness(0, 0, 0, 8)
    sp.Children.Add(tb_msg)

    for lbl in existing_labels:
        tb = TextBlock()
        tb.Text       = u"•  " + lbl
        tb.FontSize   = 12
        tb.Foreground = hex_brush("#555555")
        tb.Margin     = Thickness(8, 1, 0, 1)
        sp.Children.Add(tb)

    tb_q = TextBlock()
    tb_q.Text       = u"Écraser ?"
    tb_q.FontSize   = 12
    tb_q.FontWeight = SW.FontWeights.SemiBold
    tb_q.Foreground = hex_brush("#E67E22")
    tb_q.Margin     = Thickness(0, 10, 0, 0)
    sp.Children.Add(tb_q)

    # ── Footer ──
    footer = Border()
    footer.BorderThickness = Thickness(0, 1, 0, 0)
    footer.BorderBrush     = hex_brush("#C0D0E0")
    footer.Background      = hex_brush("#F5F5F5")
    footer.Padding         = Thickness(0, 6, 0, 6)
    Grid.SetRow(footer, 1)
    root.Children.Add(footer)

    grid_f = Grid()

    lbl_f            = TextBlock()
    lbl_f.Text       = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    lbl_f.FontSize   = 10
    lbl_f.Foreground = hex_brush("#888888")
    lbl_f.VerticalAlignment = SW.VerticalAlignment.Center
    lbl_f.Margin    = Thickness(10, 0, 0, 0)
    grid_f.Children.Add(lbl_f)

    sp_btns = StackPanel()
    sp_btns.Orientation = Orientation.Horizontal
    sp_btns.HorizontalAlignment = SW.HorizontalAlignment.Right
    sp_btns.Margin = Thickness(0, 0, 10, 0)

    btn_no = Button()
    btn_no.Content         = u"Non"
    btn_no.Width           = 70
    btn_no.Height          = 26
    btn_no.Margin          = Thickness(0, 0, 6, 0)
    btn_no.Background      = hex_brush("#E74C3C")
    btn_no.Foreground      = hex_brush("#FFFFFF")
    btn_no.FontWeight      = SW.FontWeights.SemiBold
    btn_no.BorderThickness = Thickness(0)
    btn_no.Click          += lambda s, e: win.Close()
    sp_btns.Children.Add(btn_no)

    btn_yes = Button()
    btn_yes.Content         = u"Oui"
    btn_yes.Width           = 70
    btn_yes.Height          = 26
    btn_yes.Background      = hex_brush("#2ECC71")
    btn_yes.Foreground      = hex_brush("#FFFFFF")
    btn_yes.FontWeight      = SW.FontWeights.SemiBold
    btn_yes.BorderThickness = Thickness(0)
    def on_yes(s, e):
        state["ok"] = True
        win.Close()
    btn_yes.Click += on_yes
    sp_btns.Children.Add(btn_yes)

    grid_f.Children.Add(sp_btns)
    footer.Child = grid_f

    win.ShowDialog()
    return state["ok"]


def show_result(successes, errors):
    win = Window()
    win.Title  = TOOL_NAME
    win.Width  = 480
    win.SizeToContent = SW.SizeToContent.Height
    win.MinHeight = 140
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    root.RowDefinitions.Add(_rd_auto())
    root.RowDefinitions.Add(_rd_auto())
    win.Content = root

    # ── Contenu ──
    sp = StackPanel()
    sp.Margin = Thickness(18, 14, 18, 10)
    Grid.SetRow(sp, 0)
    root.Children.Add(sp)

    if successes:
        tb_ok = TextBlock()
        tb_ok.Text       = u"✔  Export réussi :"
        tb_ok.FontSize   = 12
        tb_ok.FontWeight = SW.FontWeights.SemiBold
        tb_ok.Foreground = hex_brush("#1a7c3e")
        tb_ok.Margin     = Thickness(0, 0, 0, 6)
        sp.Children.Add(tb_ok)
        for s in successes:
            tb = TextBlock()
            tb.Text        = u"   " + s
            tb.FontSize    = 11
            tb.Foreground  = hex_brush("#333333")
            tb.TextWrapping = SW.TextWrapping.Wrap
            tb.Margin      = Thickness(0, 1, 0, 1)
            sp.Children.Add(tb)

    if errors:
        tb_ko = TextBlock()
        tb_ko.Text       = u"✘  Erreur(s) :"
        tb_ko.FontSize   = 12
        tb_ko.FontWeight = SW.FontWeights.SemiBold
        tb_ko.Foreground = hex_brush("#C0392B")
        tb_ko.Margin     = Thickness(0, 10 if successes else 0, 0, 6)
        sp.Children.Add(tb_ko)
        for err in errors:
            tb = TextBlock()
            tb.Text        = u"   " + err
            tb.FontSize    = 11
            tb.Foreground  = hex_brush("#333333")
            tb.TextWrapping = SW.TextWrapping.Wrap
            tb.Margin      = Thickness(0, 1, 0, 1)
            sp.Children.Add(tb)

    # ── Footer ──
    footer = Border()
    footer.BorderThickness = Thickness(0, 1, 0, 0)
    footer.BorderBrush     = hex_brush("#C0D0E0")
    footer.Background      = hex_brush("#F5F5F5")
    footer.Padding         = Thickness(0, 6, 0, 6)
    Grid.SetRow(footer, 1)
    root.Children.Add(footer)

    grid_f = Grid()

    lbl_f            = TextBlock()
    lbl_f.Text       = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    lbl_f.FontSize   = 10
    lbl_f.Foreground = hex_brush("#888888")
    lbl_f.VerticalAlignment = SW.VerticalAlignment.Center
    lbl_f.Margin    = Thickness(10, 0, 0, 0)
    grid_f.Children.Add(lbl_f)

    btn_ok = Button()
    btn_ok.Content         = u"OK"
    btn_ok.Width           = 80
    btn_ok.Height          = 26
    btn_ok.Margin          = Thickness(0, 0, 10, 0)
    btn_ok.Background      = hex_brush("#3498DB")
    btn_ok.Foreground      = hex_brush("#FFFFFF")
    btn_ok.FontWeight      = SW.FontWeights.SemiBold
    btn_ok.BorderThickness = Thickness(0)
    btn_ok.HorizontalAlignment = SW.HorizontalAlignment.Right
    btn_ok.Click          += lambda s, e: win.Close()
    grid_f.Children.Add(btn_ok)

    footer.Child = grid_f
    win.ShowDialog()


def _rd_auto():
    rd = RowDefinition()
    rd.Height = GridLength.Auto
    return rd

# =============================================================================
# POINT D'ENTREE
# =============================================================================
def main():
    active_view = uidoc.ActiveView
    if not isinstance(active_view, ViewSheet):
        MessageBox.Show(
            u"La vue active n’est pas une feuille.\n\n"
            u"Ouvrez une feuille avant de lancer cet outil.",
            u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
            MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    dlg = ExportDialog(active_view)
    dlg.ShowDialog()
    params = dlg.result
    dlg    = None

    if params is None:
        return

    folder   = params["folder"]
    filename = params["filename"]
    sheet_id = params["sheet_id"]
    successes = []
    errors    = []

    if params["export_pdf"]:
        try:
            ok = do_export_pdf(folder, filename, sheet_id)
            if ok:
                successes.append(
                    u"PDF : {}".format(os.path.join(folder, filename + ".pdf")))
            else:
                errors.append(u"PDF : l’export a retouré False (vérifiez les droits du dossier).")
        except Exception as ex:
            errors.append(u"PDF : " + str(ex))
            print(traceback.format_exc())

    if params["export_dwg"]:
        try:
            ok = do_export_dwg(folder, filename, sheet_id)
            if ok:
                successes.append(
                    u"DWG : {}".format(os.path.join(folder, filename + ".dwg")))
            else:
                errors.append(u"DWG : l’export a retouré False (vérifiez les droits du dossier).")
        except Exception as ex:
            errors.append(u"DWG : " + str(ex))
            print(traceback.format_exc())

    show_result(successes, errors)


main()
