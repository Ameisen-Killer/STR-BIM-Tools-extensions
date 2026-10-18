# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Surfaces de Pochages"
# =============================================================================
__title__   = "Surface de Pochage"
__doc__     = "Détail des surfaces des zones de pochage sélectionnées + total."
__author__  = "Tony VARIN"
__version__ = "1.0.0"

# ─── Références CLR ──────────────────────────────────────────────────────────
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

# ─── Imports Revit ────────────────────────────────────────────────────────────
from Autodesk.Revit.DB import FilledRegion, BuiltInParameter
from pyrevit import revit, forms

# ─── Imports Python standard ──────────────────────────────────────────────────
import sys
from collections import OrderedDict

# ─── Imports WPF / System ─────────────────────────────────────────────────────
import System
from System.Windows import (
    Window, Thickness, HorizontalAlignment, VerticalAlignment,
    GridLength, GridUnitType
)
from System.Windows.Controls import (
    DataGrid, DataGridTextColumn, DataGridLength, DataGridLengthUnitType,
    DataGridRow, TextBlock, StackPanel, Button, Separator, Border,
    Grid, RowDefinition, ColumnDefinition, ScrollViewer, ScrollBarVisibility
)
from System.Windows.Controls.Primitives import DataGridColumnHeader
from System.Windows.Media import SolidColorBrush, Color, Brushes
from System.Windows.Data import Binding
from System.Collections.ObjectModel import ObservableCollection

# ─── Constantes plug-in ───────────────────────────────────────────────────────
PLUGIN_VERSION = "v1.0.0"
PLUGIN_SUITE   = "STR BIM Tools"
PLUGIN_AUTHOR  = "Tony VARIN"

# ─── Conversion interne Revit → m² ───────────────────────────────────────────
def sqft_to_sqm(sqft):
    return sqft * 0.09290304

# ─── Récupération de la sélection ────────────────────────────────────────────
doc   = revit.doc
uidoc = revit.uidoc

sel_ids = uidoc.Selection.GetElementIds()

if not sel_ids:
    forms.alert(
        "Aucun élément sélectionné.\n"
        "Sélectionne des zones de pochage avant de lancer le script.",
        title="Surface Pochage",
        warn_icon=True
    )
    sys.exit()

# Filtre : garder uniquement les FilledRegion
regions = []
skipped = 0
for eid in sel_ids:
    el = doc.GetElement(eid)
    if isinstance(el, FilledRegion):
        regions.append(el)
    else:
        skipped += 1

if not regions:
    forms.alert(
        "Aucune zone de pochage (FilledRegion) dans la sélection.\n"
        "({} élément(s) ignoré(s))".format(skipped),
        title="Surface Pochage",
        warn_icon=True
    )
    sys.exit()

# ─── Calcul de surface par Shoelace ──────────────────────────────────────────
def loop_area_sqft(curve_loop):
    """Aire signée d'un CurveLoop (formule de Shoelace, plan XY)."""
    pts = []
    for curve in curve_loop:
        tess = curve.Tessellate()
        for pt in tess[:-1]:
            pts.append((pt.X, pt.Y))
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += (x1 * y2) - (x2 * y1)
    return area / 2.0

def get_area_m2(reg):
    """Surface nette en m² d'une FilledRegion."""
    loops = reg.GetBoundaries()
    if not loops:
        return 0.0
    total_sqft = sum(loop_area_sqft(lp) for lp in loops)
    return sqft_to_sqm(abs(total_sqft))

def get_type_name(reg):
    """Nom du type de la FilledRegion."""
    frt = doc.GetElement(reg.GetTypeId())
    if frt is None:
        return "(inconnu)"
    p = frt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else frt.Name

# ─── Groupement par type ──────────────────────────────────────────────────────
groups = OrderedDict()
for reg in regions:
    tname = get_type_name(reg)
    area  = get_area_m2(reg)
    groups.setdefault(tname, []).append(area)

# ─── Modèle de données ────────────────────────────────────────────────────────
CLR_DETAIL   = SolidColorBrush(Color.FromRgb(30,  30,  30))   # texte normal
CLR_SUBTOTAL = SolidColorBrush(Color.FromRgb(0,   0,   0))   # texte noir gras
BG_SUBTOTAL  = SolidColorBrush(Color.FromRgb(210, 225, 242)) # fond bleu très clair

class RegionRow(object):
    """Ligne détail ou ligne sous-total dans le DataGrid."""
    def __init__(self, num, type_name, area_str, is_subtotal=False):
        self.Num        = num
        self.TypeName   = type_name
        self.Area       = area_str
        self.IsSubtotal = is_subtotal
        # Propriétés visuelles bindées directement
        if is_subtotal:
            self.RowFg     = CLR_SUBTOTAL
            self.RowBg     = BG_SUBTOTAL
            self.RowWeight = System.Windows.FontWeights.Bold
        else:
            self.RowFg     = CLR_DETAIL
            self.RowBg     = Brushes.Transparent
            self.RowWeight = System.Windows.FontWeights.Normal

rows       = ObservableCollection[object]()
total_area = 0.0

for tname, areas in groups.items():
    for idx, a in enumerate(areas, start=1):
        rows.Add(RegionRow(str(idx), tname, "{:.3f}".format(a), is_subtotal=False))
    subtotal    = sum(areas)
    total_area += subtotal
    rows.Add(RegionRow(
        "", "Sous-total  « {} »".format(tname),
        "{:.3f}".format(subtotal),
        is_subtotal=True
    ))

# ─── Fenêtre WPF ─────────────────────────────────────────────────────────────
win = Window()
win.Title         = TOOL_NAME
win.Width         = 600
win.Height        = 520
win.MinWidth      = 420
win.MinHeight     = 380
win.ResizeMode    = System.Windows.ResizeMode.CanResize
win.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
win.Background    = SolidColorBrush(Color.FromRgb(255, 255, 255))

# ── Grid racine : corps extensible / footer fixe ─────────────────────────────
root_grid = Grid()
r0 = RowDefinition(); r0.Height = GridLength(1, GridUnitType.Star)
r1 = RowDefinition(); r1.Height = GridLength.Auto
root_grid.RowDefinitions.Add(r0)
root_grid.RowDefinitions.Add(r1)
win.Content = root_grid

# ── Ligne 0 : corps dans ScrollViewer ────────────────────────────────────────
body = StackPanel()
body.Margin = Thickness(12, 10, 12, 6)

scroll = ScrollViewer()
scroll.Content                       = body
scroll.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
Grid.SetRow(scroll, 0)
root_grid.Children.Add(scroll)

# Info sélection
lbl_info = TextBlock()
lbl_info.Text       = "{} zone(s) de pochage sélectionnée(s){}".format(
    len(regions),
    "   |   {} élément(s) ignoré(s)".format(skipped) if skipped else ""
)
lbl_info.Foreground = SolidColorBrush(Color.FromRgb(50, 50, 50))
lbl_info.FontSize   = 12
lbl_info.Margin     = Thickness(0, 0, 0, 10)
body.Children.Add(lbl_info)

# ── DataGrid ──────────────────────────────────────────────────────────────────
dg = DataGrid()
dg.AutoGenerateColumns      = False
dg.IsReadOnly               = True
dg.CanUserSortColumns       = False
dg.HeadersVisibility        = System.Windows.Controls.DataGridHeadersVisibility.Column
dg.AlternatingRowBackground = SolidColorBrush(Color.FromRgb(232, 240, 250))
dg.RowBackground            = SolidColorBrush(Color.FromRgb(255, 255, 255))
dg.BorderBrush              = SolidColorBrush(Color.FromRgb(200, 210, 220))
dg.BorderThickness          = Thickness(1)
dg.GridLinesVisibility      = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
dg.HorizontalGridLinesBrush = SolidColorBrush(Color.FromRgb(220, 228, 238))
dg.Margin                   = Thickness(0, 0, 0, 10)
dg.ItemsSource              = rows

# Style row : fond via binding RowBg
row_style = System.Windows.Style(DataGridRow)
row_style.Setters.Add(System.Windows.Setter(
    DataGridRow.BackgroundProperty, Binding("RowBg")
))
dg.RowStyle = row_style

# Helper : ElementStyle avec Foreground et FontWeight bindés sur la ligne
def make_cell_style(align=System.Windows.TextAlignment.Left):
    s = System.Windows.Style(TextBlock)
    s.Setters.Add(System.Windows.Setter(TextBlock.TextAlignmentProperty, align))
    s.Setters.Add(System.Windows.Setter(TextBlock.ForegroundProperty,  Binding("RowFg")))
    s.Setters.Add(System.Windows.Setter(TextBlock.FontWeightProperty,  Binding("RowWeight")))
    return s

# Colonnes
col_num = DataGridTextColumn()
col_num.Header       = "#"
col_num.Binding      = Binding("Num")
col_num.Width        = DataGridLength(30)
col_num.ElementStyle = make_cell_style(System.Windows.TextAlignment.Left)

col_type = DataGridTextColumn()
col_type.Header       = "Type de pochage"
col_type.Binding      = Binding("TypeName")
col_type.Width        = DataGridLength(1, DataGridLengthUnitType.Star)
col_type.ElementStyle = make_cell_style(System.Windows.TextAlignment.Left)

col_area = DataGridTextColumn()
col_area.Header       = "Surface (m²)"
col_area.Binding      = Binding("Area")
col_area.Width        = DataGridLength(110)
col_area.ElementStyle = make_cell_style(System.Windows.TextAlignment.Right)

style_header_right = System.Windows.Style(DataGridColumnHeader)
style_header_right.Setters.Add(System.Windows.Setter(
    DataGridColumnHeader.HorizontalContentAlignmentProperty, HorizontalAlignment.Right
))
col_area.HeaderStyle = style_header_right

dg.Columns.Add(col_num)
dg.Columns.Add(col_type)
dg.Columns.Add(col_area)
body.Children.Add(dg)

# ── Séparateur + Total ────────────────────────────────────────────────────────
sep = Separator()
sep.Margin = Thickness(0, 0, 0, 8)
body.Children.Add(sep)

pnl_total = StackPanel()
pnl_total.Orientation         = System.Windows.Controls.Orientation.Horizontal
pnl_total.HorizontalAlignment = HorizontalAlignment.Right
pnl_total.Margin              = Thickness(0, 0, 0, 6)

lbl_total_txt = TextBlock()
lbl_total_txt.Text              = "TOTAL : "
lbl_total_txt.FontWeight        = System.Windows.FontWeights.Bold
lbl_total_txt.FontSize          = 13
lbl_total_txt.VerticalAlignment = VerticalAlignment.Center
lbl_total_txt.Foreground        = SolidColorBrush(Color.FromRgb(50, 50, 50))

lbl_total_val = TextBlock()
lbl_total_val.Text              = "{:.3f} m²".format(total_area)
lbl_total_val.FontWeight        = System.Windows.FontWeights.Bold
lbl_total_val.FontSize          = 13
lbl_total_val.Foreground        = SolidColorBrush(Color.FromRgb(31, 73, 125))
lbl_total_val.VerticalAlignment = VerticalAlignment.Center

pnl_total.Children.Add(lbl_total_txt)
pnl_total.Children.Add(lbl_total_val)
body.Children.Add(pnl_total)

# ── Ligne 1 : footer blanc — identité gauche + bouton Fermer droite ───────────
footer = Border()
footer.Background = SolidColorBrush(Color.FromRgb(245, 245, 245))
footer.BorderBrush = SolidColorBrush(Color.FromRgb(210, 210, 210))
footer.BorderThickness = Thickness(0, 1, 0, 0)
footer.Padding    = Thickness(10, 6, 10, 6)
Grid.SetRow(footer, 1)
root_grid.Children.Add(footer)

footer_grid = Grid()
fc0 = ColumnDefinition(); fc0.Width = GridLength(1, GridUnitType.Star)
fc1 = ColumnDefinition(); fc1.Width = GridLength.Auto
footer_grid.ColumnDefinitions.Add(fc0)
footer_grid.ColumnDefinitions.Add(fc1)
footer.Child = footer_grid

lbl_footer = TextBlock()
lbl_footer.Text              = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
lbl_footer.FontSize          = 10
lbl_footer.Foreground        = SolidColorBrush(Color.FromRgb(140, 140, 140))
lbl_footer.VerticalAlignment = VerticalAlignment.Center
Grid.SetColumn(lbl_footer, 0)
footer_grid.Children.Add(lbl_footer)

btn = Button()
btn.Content             = "Fermer"
btn.Width               = 90
btn.Padding             = Thickness(8, 4, 8, 4)
btn.HorizontalAlignment = HorizontalAlignment.Right
btn.VerticalAlignment   = VerticalAlignment.Center
btn.Background          = SolidColorBrush(Color.FromRgb(41, 128, 185))
btn.Foreground          = SolidColorBrush(Color.FromRgb(255, 255, 255))
btn.FontWeight          = System.Windows.FontWeights.Bold
btn.BorderThickness     = Thickness(0)
btn.Click              += lambda s, e: win.Close()
Grid.SetColumn(btn, 1)
footer_grid.Children.Add(btn)

win.ShowDialog()