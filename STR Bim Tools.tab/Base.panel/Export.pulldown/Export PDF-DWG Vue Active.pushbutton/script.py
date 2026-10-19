# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.7.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Export PDF-DWG Vue Active"

# Taille de la fenetre de progression (unites WPF). Propre a cet outil : les
# libelles affiches sont des noms de fichiers et de feuilles longs, la taille
# standard de str_progress_sta les tronque. Mettre a None pour revenir a la
# taille partagee par les autres outils.
PROG_LARGEUR = 800
PROG_HAUTEUR = None
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
    Grid, StackPanel, Border, TextBlock, TextBox, Button, Label,
    CheckBox, GroupBox, DockPanel, ScrollViewer, ProgressBar,
    RowDefinition, ColumnDefinition, Orientation, ComboBox,
)
from System.Windows.Media import SolidColorBrush, Color, FontFamily
from System.Windows.Threading import DispatcherPriority

from Autodesk.Revit.DB import (
    BuiltInParameter,
    PDFExportOptions,
    DWGExportOptions,
    ExportDWGSettings,
    FilteredElementCollector,
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

def _load_prefs():
    """Helpers generiques : un seul prefs.json, plusieurs cles (dossier,
    configuration DWG...). Ecrire une cle ne doit jamais effacer les autres."""
    try:
        if os.path.isfile(_PREFS_FILE):
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_pref(key, value):
    d = _load_prefs()
    d[key] = value
    try:
        with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass

def load_last_folder():
    folder = _load_prefs().get("last_folder", u"")
    if folder and os.path.isdir(folder):
        return folder
    return None

def save_last_folder(folder):
    _save_pref("last_folder", folder)

def load_last_dwg_setup():
    return _load_prefs().get("last_dwg_setup", u"") or u""

def save_last_dwg_setup(name):
    _save_pref("last_dwg_setup", name or u"")

# =============================================================================
# Configurations d'export DWG nommees du projet (ExportDWGSettings)
# =============================================================================
DWG_SETUP_DEFAUT = u"(par défaut — AutoCAD 2018)"

def get_dwg_setups():
    """[(nom, ElementId), ...] des configurations DWG enregistrees dans le
    projet, triees par nom. Liste vide si le projet n'en definit aucune."""
    out = []
    try:
        for s in FilteredElementCollector(doc).OfClass(ExportDWGSettings):
            try:
                if s.Name:
                    out.append((s.Name, s.Id))
            except Exception:
                pass
    except Exception:
        pass
    out.sort(key=lambda t: t[0].lower())
    return out

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

# =============================================================================
# Ordre des segments GED dans le nom de fichier (feuille)
# =============================================================================
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

def build_filename_sheet(sheet):
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

def build_filename_view(view):
    """
    Retourne le nom de fichier pour une vue (pas une feuille).
    Utilise directement le nom de la vue, caracteres speciaux remplacés.
    """
    name = view.Name or u"Vue_sans_nom"
    # Remplacer les caracteres interdits dans un nom de fichier
    for ch in u'\\/:*?"<>|':
        name = name.replace(ch, u"_")
    # Nettoyer les doubles espaces/underscores
    while u"  " in name:
        name = name.replace(u"  ", u" ")
    return name.strip()

# =============================================================================
# Validation du nom de fichier saisi
# =============================================================================
# Le nom est libre a la saisie : c'est ici, et seulement ici, qu'on refuse ce
# qui ferait echouer doc.Export en cours de route, sans message exploitable.
# Le '?' est volontairement absent de la liste : c'est le marqueur des
# parametres non renseignes dans le nom suggere. Il declenche l'avertissement
# de l'export, pas un blocage, pour ne pas changer le comportement existant.
CHARS_INTERDITS = u'\\/:*"<>|'

def valider_nom_fichier(nom):
    """Retourne (nom_nettoye, message_erreur_ou_None).

    Ne corrige rien tout seul : un nom invalide doit etre montre a
    l'utilisateur, pas silencieusement reecrit sous son nez."""
    nom = (nom or u"").strip()
    if not nom:
        return nom, u"Le nom du fichier est vide."

    mauvais = sorted(set(c for c in nom if c in CHARS_INTERDITS))
    if mauvais:
        return nom, u"Caractères interdits dans un nom de fichier :  {}".format(
            u"   ".join(mauvais))

    if nom.endswith(u"."):
        return nom, u"Le nom ne peut pas se terminer par un point."

    # Noms reserves DOS : Revit echoue sans expliquer pourquoi.
    racine = nom.split(u".")[0].upper()
    if racine in (u"CON", u"PRN", u"AUX", u"NUL"):
        return nom, u"« {} » est un nom réservé par Windows.".format(racine)
    if len(racine) == 4 and racine[:3] in (u"COM", u"LPT") and racine[3].isdigit():
        return nom, u"« {} » est un nom réservé par Windows.".format(racine)

    return nom, None

# =============================================================================
# Fenetre WPF
# =============================================================================
class ExportDialog(Window):

    def __init__(self, active_view):
        self._view     = active_view
        self._is_sheet = isinstance(active_view, ViewSheet)
        self._result   = None
        self._dwg_setups = get_dwg_setups()   # [(nom, ElementId), ...]

        if self._is_sheet:
            self._filename, self._missing = build_filename_sheet(active_view)
        else:
            self._filename = build_filename_view(active_view)
            self._missing  = []

        # Le nom construit a partir des attributs reste la suggestion de
        # reference : le bouton « Réinitialiser » y revient apres une saisie.
        self._filename_suggere = self._filename

        self.Title     = TOOL_NAME
        self.Width     = 900
        self.Height    = 620
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
        root.RowDefinitions.Add(self._rd("Auto"))
        root.RowDefinitions.Add(self._rd("*"))
        root.RowDefinitions.Add(self._rd("Auto"))
        self.Content = root

        # ── Barre titre ──────────────────────────────────────────────────────
        title_bar             = Border()
        title_bar.Background  = hex_brush("#2F6496")
        title_bar.Padding     = Thickness(14, 9, 14, 9)
        Grid.SetRow(title_bar, 0)
        root.Children.Add(title_bar)

        sp_title = StackPanel()
        sp_title.Orientation = Orientation.Horizontal

        tb_icon            = TextBlock()
        tb_icon.Text       = (u"\U0001f4c4  " if self._is_sheet else u"\U0001f5bc  ")
        tb_icon.FontSize   = 15
        tb_icon.Foreground = hex_brush("#FFFFFF")
        tb_icon.VerticalAlignment = SW.VerticalAlignment.Center
        sp_title.Children.Add(tb_icon)

        mode_label = u"Feuille active" if self._is_sheet else u"Vue active"
        tb_title            = TextBlock()
        tb_title.Text       = u"Export PDF / DWG — {}  |  Revit {}".format(
            mode_label, app.VersionNumber)
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

        # ── Section : info vue / feuille ─────────────────────────────────────
        section_label = u"Feuille active" if self._is_sheet else u"Vue active"
        sp_main.Children.Add(self._section_hdr(section_label))

        grp_info = self._group_box()
        sp_info  = StackPanel()

        if self._is_sheet:
            sheet_num  = get_bip_str(self._view, BuiltInParameter.SHEET_NUMBER) or u""
            sheet_name = get_bip_str(self._view, BuiltInParameter.SHEET_NAME)   or u""
            sp_info.Children.Add(self._info_row(u"N° feuille", sheet_num))
            sp_info.Children.Add(self._info_row(u"Nom",              sheet_name))
        else:
            view_type  = str(self._view.ViewType).replace("ViewType.", "")
            view_name  = self._view.Name or u""
            sp_info.Children.Add(self._info_row(u"Type",   view_type))
            sp_info.Children.Add(self._info_row(u"Nom",    view_name))

        grp_info.Child = sp_info
        sp_main.Children.Add(grp_info)

        # ── Section : Nom du fichier genere ──────────────────────────────────
        # Le nom reste suggere a partir des attributs de la feuille, mais il est
        # modifiable : un export ponctuel ne doit pas obliger a toucher aux
        # parametres de la feuille. Rien n'est reecrit dans le modele.
        hdr_fname = DockPanel()
        hdr_fname.LastChildFill = True

        btn_reset = Button()
        btn_reset.Content         = u"Réinitialiser"
        btn_reset.Height          = 20
        btn_reset.Padding         = Thickness(8, 0, 8, 0)
        btn_reset.FontSize        = 10
        btn_reset.Background      = hex_brush("#7F8C8D")
        btn_reset.Foreground      = hex_brush("#FFFFFF")
        btn_reset.FontWeight      = SW.FontWeights.SemiBold
        btn_reset.BorderThickness = Thickness(0)
        btn_reset.Margin          = Thickness(6, 4, 0, 3)
        btn_reset.ToolTip         = u"Revenir au nom suggéré par les attributs de la feuille"
        btn_reset.Click          += self._on_reset_nom
        DockPanel.SetDock(btn_reset, SWC.Dock.Right)
        hdr_fname.Children.Add(btn_reset)

        hdr_fname.Children.Add(
            self._section_hdr(u"Nom du fichier généré  (modifiable)"))
        sp_main.Children.Add(hdr_fname)

        grp_fname = self._group_box()
        sp_fname  = StackPanel()

        self.txt_fname = TextBox()
        self.txt_fname.Text          = self._filename
        self.txt_fname.FontSize      = 11
        self.txt_fname.FontFamily    = FontFamily("Consolas")
        self.txt_fname.FontWeight    = SW.FontWeights.SemiBold
        self.txt_fname.Foreground    = hex_brush("#1a3a5c")
        self.txt_fname.TextWrapping  = SW.TextWrapping.Wrap
        self.txt_fname.AcceptsReturn = False
        self.txt_fname.MinHeight     = 34
        self.txt_fname.Padding       = Thickness(4, 3, 4, 3)
        self.txt_fname.BorderThickness = Thickness(1)
        sp_fname.Children.Add(self.txt_fname)

        # Retour visuel sous le champ : fichiers produits, ou motif du refus.
        self.tb_fname_info              = TextBlock()
        self.tb_fname_info.FontSize     = 10
        self.tb_fname_info.TextWrapping = SW.TextWrapping.Wrap
        self.tb_fname_info.Margin       = Thickness(0, 5, 0, 0)
        sp_fname.Children.Add(self.tb_fname_info)

        # Branche apres coup : le handler lit tb_fname_info, qui doit exister.
        self.txt_fname.TextChanged += self._on_nom_change

        grp_fname.Child = sp_fname
        sp_main.Children.Add(grp_fname)

        self._rafraichir_info_nom()

        # ── Section : Parametres manquants (feuille seulement) ───────────────
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
                tb_m            = TextBlock()
                tb_m.Text       = u"•  {}".format(m)
                tb_m.FontSize   = 11
                tb_m.Foreground = hex_brush("#7D3C00")
                tb_m.Margin     = Thickness(0, 1, 0, 1)
                sp_warn.Children.Add(tb_m)

            warn_brd.Child = sp_warn
            sp_main.Children.Add(warn_brd)

        # ── Section : Dossier de destination ─────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Dossier de destination"))

        grp_folder              = self._group_box()
        dp_folder               = DockPanel()
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
        sp_main.Children.Add(self._section_hdr(u"Format d'export"))

        grp_fmt    = self._group_box()
        sp_fmt     = StackPanel()
        sp_fmt.Orientation = Orientation.Horizontal

        self.chk_pdf           = CheckBox()
        self.chk_pdf.IsChecked = True
        self.chk_pdf.Content   = u"PDF"
        self.chk_pdf.FontSize  = 13
        self.chk_pdf.FontWeight = SW.FontWeights.SemiBold
        self.chk_pdf.Margin    = Thickness(0, 0, 30, 0)
        self.chk_pdf.VerticalAlignment = SW.VerticalAlignment.Center
        sp_fmt.Children.Add(self.chk_pdf)

        self.chk_dwg           = CheckBox()
        self.chk_dwg.IsChecked = True
        self.chk_dwg.Content   = u"DWG"
        self.chk_dwg.FontSize  = 13
        self.chk_dwg.FontWeight = SW.FontWeights.SemiBold
        self.chk_dwg.VerticalAlignment = SW.VerticalAlignment.Center
        sp_fmt.Children.Add(self.chk_dwg)

        grp_fmt.Child = sp_fmt
        sp_main.Children.Add(grp_fmt)

        # ── Section : Configuration DWG ───────────────────────────────────────
        sp_main.Children.Add(self._section_hdr(u"Configuration d'export DWG"))

        grp_dwg  = self._group_box()
        sp_dwg   = StackPanel()

        sp_cbo   = StackPanel()
        sp_cbo.Orientation = Orientation.Horizontal

        tb_cbo            = TextBlock()
        tb_cbo.Text       = u"Configuration : "
        tb_cbo.FontSize   = 11
        tb_cbo.FontWeight = SW.FontWeights.SemiBold
        tb_cbo.Foreground = hex_brush("#555555")
        tb_cbo.VerticalAlignment = SW.VerticalAlignment.Center
        sp_cbo.Children.Add(tb_cbo)

        self.cbo_dwg        = ComboBox()
        self.cbo_dwg.Width  = 340
        self.cbo_dwg.Height = 24
        self.cbo_dwg.VerticalContentAlignment = SW.VerticalAlignment.Center
        self.cbo_dwg.Items.Add(DWG_SETUP_DEFAUT)
        for nm, _eid in self._dwg_setups:
            self.cbo_dwg.Items.Add(nm)
        # re-selection de la derniere configuration utilisee si elle existe
        # encore dans ce projet, sinon repli sur la configuration par defaut.
        last = load_last_dwg_setup()
        idx = 0
        if last:
            for i, (nm, _eid) in enumerate(self._dwg_setups):
                if nm == last:
                    idx = i + 1
                    break
        self.cbo_dwg.SelectedIndex = idx
        sp_cbo.Children.Add(self.cbo_dwg)
        sp_dwg.Children.Add(sp_cbo)

        tb_hint            = TextBlock()
        tb_hint.FontSize   = 10
        tb_hint.TextWrapping = SW.TextWrapping.Wrap
        tb_hint.Foreground = hex_brush("#888888")
        tb_hint.Margin     = Thickness(0, 6, 0, 0)
        if self._dwg_setups:
            tb_hint.Text = (u"Configurations enregistrées dans le projet "
                            u"(Exporter > Options d'export CAO). La version de "
                            u"fichier de la configuration choisie est utilisée ; "
                            u"les vues de la feuille sont toujours fusionnées en "
                            u"un seul DWG pour respecter le nom de fichier.")
        else:
            tb_hint.Text = (u"Aucune configuration DWG enregistrée dans ce projet : "
                            u"seul l'export par défaut (AutoCAD 2018) est disponible. "
                            u"Créez-en une via Exporter > Options d'export CAO.")
        sp_dwg.Children.Add(tb_hint)

        grp_dwg.Child = sp_dwg
        sp_main.Children.Add(grp_dwg)

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

    def _on_reset_nom(self, s, e):
        self.txt_fname.Text = self._filename_suggere
        self.txt_fname.CaretIndex = len(self.txt_fname.Text)

    def _on_nom_change(self, s, e):
        self._rafraichir_info_nom()

    def _rafraichir_info_nom(self):
        """Retour immediat sous le champ : fichiers produits, ou motif du refus.
        L'export revalide de son cote ; ceci n'est que de l'affichage."""
        nom, err = valider_nom_fichier(self.txt_fname.Text)

        if err:
            self.txt_fname.BorderBrush    = hex_brush("#C0392B")
            self.tb_fname_info.Foreground = hex_brush("#C0392B")
            self.tb_fname_info.Text       = u"⚠  " + err
            return

        self.txt_fname.BorderBrush = hex_brush("#C0D0E0")
        if u"?" in nom:
            self.tb_fname_info.Foreground = hex_brush("#C0392B")
            self.tb_fname_info.Text = (
                u"⚠  Des « ? » subsistent : corrigez-les ici, ou renseignez "
                u"les paramètres de la feuille.")
        else:
            self.tb_fname_info.Foreground = hex_brush("#888888")
            self.tb_fname_info.Text = (
                u"Suggéré d'après les attributs de la feuille. Les extensions "
                u".pdf / .dwg sont ajoutées à l'export ; le modèle n'est pas "
                u"modifié.")

    def _on_export(self, s, e):
        export_pdf = bool(self.chk_pdf.IsChecked)
        export_dwg = bool(self.chk_dwg.IsChecked)

        if not export_pdf and not export_dwg:
            MessageBox.Show(
                u"Sélectionnez au moins un format d'export (PDF ou DWG).",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        # Nom de fichier : suggere a partir des attributs, mais modifiable.
        # C'est la saisie qui fait foi, pas la suggestion memorisee.
        nom, err = valider_nom_fichier(self.txt_fname.Text)
        if err:
            MessageBox.Show(
                err, TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            self.txt_fname.Focus()
            self.txt_fname.SelectAll()
            return

        folder = self.tb_folder.Text.strip()
        if not os.path.isdir(folder):
            MessageBox.Show(
                u"Le dossier spécifié n'existe pas :\n{}".format(folder),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        # Chemin complet trop long : Revit echoue en silence sur les
        # arborescences profondes (OneDrive + sous-dossiers de phase).
        longueur = max(len(os.path.join(folder, nom + ext))
                       for ext in (u".pdf", u".dwg"))
        if longueur > 255:
            MessageBox.Show(
                u"Le chemin complet ferait {} caractères (limite Windows : 255).\n\n"
                u"Raccourcissez le nom du fichier ou choisissez un dossier "
                u"moins profond.".format(longueur),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            self.txt_fname.Focus()
            return

        # Avertissement : le nom retenu porte encore des '?'. On teste le nom
        # final, pas self._missing : un parametre vide corrige a la main dans le
        # champ ne doit plus declencher d'alerte.
        if u"?" in nom:
            msg = u"Le nom du fichier contient encore des « ? » :\n\n    {}\n".format(nom)
            if self._missing:
                msg += (u"\nParamètres non renseignés sur la feuille :\n"
                        + u"\n".join(u"  •  " + m for m in self._missing) + u"\n")
            msg += u"\nContinuer quand même ?"
            res = MessageBox.Show(
                msg, u"Nom de fichier incomplet",
                MessageBoxButton.YesNo, MessageBoxImage.Warning)
            if str(res) != "Yes":
                return

        # Verification fichiers existants
        to_check = []
        if export_pdf:
            to_check.append((os.path.join(folder, nom + ".pdf"), "PDF"))
        if export_dwg:
            to_check.append((os.path.join(folder, nom + ".dwg"), "DWG"))

        existing = [lbl for path, lbl in to_check if os.path.isfile(path)]
        if existing:
            if not _confirm_overwrite(existing):
                return

        # configuration DWG choisie (None = export par defaut AutoCAD 2018)
        dwg_setup_name = None
        dwg_setup_id   = None
        idx = self.cbo_dwg.SelectedIndex
        if idx > 0 and (idx - 1) < len(self._dwg_setups):
            dwg_setup_name, dwg_setup_id = self._dwg_setups[idx - 1]

        save_last_folder(folder)
        save_last_dwg_setup(dwg_setup_name or u"")
        self._result = {
            "folder"     : folder,
            "filename"   : nom,
            "export_pdf" : export_pdf,
            "export_dwg" : export_dwg,
            "view_id"    : self._view.Id,
            "dwg_setup_id"   : dwg_setup_id,
            "dwg_setup_name" : dwg_setup_name,
        }
        self.Close()

    @property
    def result(self):
        return self._result

# =============================================================================
# Export PDF (API native Revit 2024)
# =============================================================================
def do_export_pdf(folder, filename, view_id):
    opts                    = PDFExportOptions()
    opts.FileName           = filename
    opts.Combine            = True   # force l'usage de FileName meme sur une seule vue
    opts.HideCropBoundaries = False  # afficher les limites de cadrage
    view_ids = List[ElementId]()
    view_ids.Add(view_id)
    return doc.Export(folder, view_ids, opts)

# =============================================================================
# Export DWG (AutoCAD 2018)
# =============================================================================
def do_export_dwg(folder, filename, view_id, setup_id=None):
    """setup_id = ElementId d'une ExportDWGSettings du projet, ou None pour
    l'export par defaut (AutoCAD 2018)."""
    opts = None
    if setup_id is not None:
        try:
            st = doc.GetElement(setup_id)
            if st is not None:
                opts = st.GetDWGExportOptions()
        except Exception:
            opts = None   # configuration illisible -> repli sur le defaut
    if opts is None:
        opts             = DWGExportOptions()
        opts.FileVersion = ACADVersion.R2018
    # Toujours force, meme avec une configuration nommee : sans fusion, Revit
    # eclate la feuille en plusieurs DWG suffixes et le nom de fichier impose
    # par l'outil (et le controle d'ecrasement) ne tient plus.
    opts.MergedViews = True
    view_ids = List[ElementId]()
    view_ids.Add(view_id)
    result = doc.Export(folder, filename, view_ids, opts)
    # Revit génère automatiquement un .pcp — on le supprime
    pcp = os.path.join(folder, filename + ".pcp")
    try:
        if os.path.isfile(pcp):
            os.remove(pcp)
    except Exception:
        pass
    return result

# =============================================================================
# Fenetre confirmation ecrasement
# =============================================================================
def _confirm_overwrite(existing_labels):
    """Retourne True si l'utilisateur confirme l'ecrasement."""
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

# =============================================================================
# Fenetre de resultat
# =============================================================================
def show_result(successes, errors, folder=None):
    win = Window()
    win.Title  = TOOL_NAME
    win.Width  = 800
    win.SizeToContent = SW.SizeToContent.Height
    win.MinHeight = 140
    win.ResizeMode = SW.ResizeMode.NoResize
    win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    root.RowDefinitions.Add(_rd_auto())
    root.RowDefinitions.Add(_rd_auto())
    win.Content = root

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
            tb.Text         = u"   " + s
            tb.FontSize     = 11
            tb.Foreground   = hex_brush("#333333")
            tb.TextWrapping = SW.TextWrapping.Wrap
            tb.Margin       = Thickness(0, 1, 0, 1)
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
            tb.Text         = u"   " + err
            tb.FontSize     = 11
            tb.Foreground   = hex_brush("#333333")
            tb.TextWrapping = SW.TextWrapping.Wrap
            tb.Margin       = Thickness(0, 1, 0, 1)
            sp.Children.Add(tb)

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

    sp_btns_r = StackPanel()
    sp_btns_r.Orientation = Orientation.Horizontal
    sp_btns_r.HorizontalAlignment = SW.HorizontalAlignment.Right
    sp_btns_r.Margin = Thickness(0, 0, 10, 0)

    if folder and os.path.isdir(folder):
        btn_open = Button()
        btn_open.Content         = u"Ouvrir le dossier"
        btn_open.Height          = 26
        btn_open.Padding         = Thickness(10, 0, 10, 0)
        btn_open.Margin          = Thickness(0, 0, 6, 0)
        btn_open.Background      = hex_brush("#2ECC71")
        btn_open.Foreground      = hex_brush("#FFFFFF")
        btn_open.FontWeight      = SW.FontWeights.SemiBold
        btn_open.BorderThickness = Thickness(0)
        def on_open(s, e): open_folder(folder); win.Close()
        btn_open.Click += on_open
        sp_btns_r.Children.Add(btn_open)

    btn_ok = Button()
    btn_ok.Content         = u"OK"
    btn_ok.Width           = 80
    btn_ok.Height          = 26
    btn_ok.Background      = hex_brush("#3498DB")
    btn_ok.Foreground      = hex_brush("#FFFFFF")
    btn_ok.FontWeight      = SW.FontWeights.SemiBold
    btn_ok.BorderThickness = Thickness(0)
    btn_ok.Click          += lambda s, e: win.Close()
    sp_btns_r.Children.Add(btn_ok)

    grid_f.Children.Add(sp_btns_r)

    footer.Child = grid_f
    win.ShowDialog()


def _rd_auto():
    rd = RowDefinition()
    rd.Height = GridLength.Auto
    return rd

def open_folder(folder):
    try:
        import subprocess
        subprocess.Popen(u'explorer "{}"'.format(folder))
    except Exception:
        pass

def do_events(dispatcher):
    try:
        dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
    except Exception:
        pass

# La fenetre de progression est fournie par str_progress_sta : elle vit sur
# son propre thread STA et reste peinte pendant doc.Export, qui bloque le
# thread de Revit. str_progress_revit y ajoute l'avancement reel de 0 a 100 %.

# =============================================================================
# POINT D'ENTREE
# =============================================================================
def main():
    active_view = uidoc.ActiveView

    # Vues non exportables (gabarits, legendes non imprimables, etc.)
    if active_view is None:
        MessageBox.Show(
            u"Aucune vue active détectée.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    if active_view.IsTemplate:
        MessageBox.Show(
            u"La vue active est un gabarit de vue.\n\n"
            u"Ouvrez une feuille ou une vue normale avant de lancer cet outil.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    if not active_view.CanBePrinted:
        MessageBox.Show(
            u"La vue active ({}) ne peut pas être imprimée / exportée.".format(
                active_view.Name),
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    dlg = ExportDialog(active_view)
    dlg.ShowDialog()
    params = dlg.result
    dlg    = None

    if params is None:
        return

    folder   = params["folder"]
    filename = params["filename"]
    view_id  = params["view_id"]
    successes = []
    errors    = []

    total = sum([params["export_pdf"], params["export_dwg"]])
    # Progression sur thread STA + avancement reel publie par Revit : doc.Export
    # bloque le thread principal, une fenetre construite dessus resterait figee
    # pendant tout l'export.
    prog = str_progress_sta.ProgressionSTA(total, TOOL_NAME, SCRIPT_VERSION,
                                           annulable=False,
                                           largeur=PROG_LARGEUR,
                                           hauteur=PROG_HAUTEUR)
    suivi = str_progress_revit.SuiviProgressionRevit(prog, app)
    suivi.brancher()
    faits = 0

    try:
        if params["export_pdf"]:
            prog.debut_element(u"Export PDF  —  " + filename, faits)
            try:
                ok = do_export_pdf(folder, filename, view_id)
                if ok:
                    successes.append(
                        u"PDF : {}".format(os.path.join(folder, filename + ".pdf")))
                else:
                    errors.append(u"PDF : l'export a retourné False (vérifiez les droits du dossier).")
            except Exception as ex:
                errors.append(u"PDF : " + str(ex))
                print(traceback.format_exc())
            faits += 1
            prog.fin_element(faits)

        if params["export_dwg"]:
            prog.debut_element(u"Export DWG  —  " + filename, faits)
            try:
                ok = do_export_dwg(folder, filename, view_id,
                                   params.get("dwg_setup_id"))
                if ok:
                    setup_lbl = params.get("dwg_setup_name")
                    successes.append(
                        u"DWG : {}{}".format(
                            os.path.join(folder, filename + ".dwg"),
                            u"   [config. « {} »]".format(setup_lbl) if setup_lbl else u""))
                else:
                    errors.append(u"DWG : l'export a retourné False (vérifiez les droits du dossier).")
            except Exception as ex:
                errors.append(u"DWG : " + str(ex))
                print(traceback.format_exc())
            faits += 1
            prog.fin_element(faits)

    finally:
        suivi.debrancher()
        prog.fermer()

    show_result(successes, errors, folder=folder)


main()
