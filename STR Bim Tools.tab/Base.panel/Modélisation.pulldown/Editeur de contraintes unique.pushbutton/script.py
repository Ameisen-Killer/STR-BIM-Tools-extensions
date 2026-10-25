# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Editeur de contraintes"
# =============================================================================
__doc__ = "Modifie les contraintes haute et basse d'un élément."

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, BuiltInCategory,
    Level, Wall, Floor, FamilyInstance, Transaction, ElementId, StorageType,
)
from Autodesk.Revit.UI import TaskDialog

import System
import System.IO
import System.Text
import System.Windows.Markup

from System.Windows import (
    Window, GridLength, GridUnitType, Thickness,
    HorizontalAlignment, VerticalAlignment, WindowStartupLocation,
)
from System.Windows.Controls import (
    Grid, StackPanel, Border, TextBlock, Button, Label,
    ComboBox, RowDefinition, ColumnDefinition,
)
from System.Windows.Media import SolidColorBrush, Color

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


# =============================================================================
# HELPERS
# =============================================================================
def ft_to_cm(ft): return ft * 30.48
def cm_to_ft(cm): return cm / 30.48

def get_all_levels():
    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    sorted_pairs = sorted(levels, key=lambda l: l.Elevation)
    d = {}
    for lvl in sorted_pairs:
        d[lvl.Name] = lvl
    return d

def get_level_names_sorted(levels_dict):
    return sorted(levels_dict.keys(), key=lambda n: levels_dict[n].Elevation, reverse=True)

def get_bounds_cm(elem):
    bb = elem.get_BoundingBox(None)
    if bb is None:
        raise Exception("Impossible d'obtenir la bounding box.")
    return ft_to_cm(bb.Min.Z), ft_to_cm(bb.Max.Z)

def get_param_level_name(elem, bip):
    p = elem.get_Parameter(bip)
    if p and p.AsElementId().IntegerValue != -1:
        lvl = doc.GetElement(p.AsElementId())
        return lvl.Name if lvl else None
    return None

def detect_type(elem):
    if isinstance(elem, Wall):  return "wall"
    if isinstance(elem, Floor): return "floor"
    if isinstance(elem, FamilyInstance):
        cat = elem.Category
        if cat is None: return None
        cid = cat.Id.IntegerValue
        if cid == int(BuiltInCategory.OST_StructuralColumns): return "column"
        if cid == int(BuiltInCategory.OST_StructuralFraming): return "framing"
        if cid == int(BuiltInCategory.OST_GenericModel):      return "generic"
    return None

def get_floor_z_ref(floor):
    p_lvl = floor.get_Parameter(BuiltInParameter.LEVEL_PARAM)
    p_off = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    if p_lvl and p_lvl.AsElementId().IntegerValue != -1 and p_off:
        lvl = doc.GetElement(p_lvl.AsElementId())
        if lvl: return lvl.Elevation + p_off.AsDouble()
    bb = floor.get_BoundingBox(None)
    if bb: return bb.Max.Z
    raise Exception("Impossible de determiner le Z de reference du sol.")

_GENERIC_OFFSET_BIPS = [
    BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
    BuiltInParameter.INSTANCE_ELEVATION_PARAM,
    BuiltInParameter.SCHEDULE_BASE_LEVEL_OFFSET_PARAM,
]

def _find_generic_level_param(elem, writable_only=True):
    for p in elem.Parameters:
        if writable_only and p.IsReadOnly: continue
        if p.StorageType != StorageType.ElementId: continue
        eid = p.AsElementId()
        if eid is None or eid.IntegerValue == -1: continue
        el = doc.GetElement(eid)
        if isinstance(el, Level): return p
    return None

def _get_generic_offset_param(elem):
    for bip in _GENERIC_OFFSET_BIPS:
        p = elem.get_Parameter(bip)
        if p is not None and not p.IsReadOnly: return p
    return None

def _get_generic_level_name(elem):
    p = _find_generic_level_param(elem, writable_only=False)
    if p:
        lvl = doc.GetElement(p.AsElementId())
        return lvl.Name if lvl else None
    return None


# =============================================================================
# XAML BUILDER
# =============================================================================
def load_xaml(xaml_str):
    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(xaml_str))
    return System.Windows.Markup.XamlReader.Load(stream)

FOOTER_TEXT = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

# XAML de base commun -- tous les textes avec accents assignes apres chargement
XAML_BASE = '''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Background="White" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen" SizeToContent="Height">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <!-- CORPS -->
    <StackPanel x:Name="body" Grid.Row="0" Margin="16,12,16,8"/>
    <!-- FOOTER -->
    <Border Grid.Row="1" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,6">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel x:Name="btn_bar" HorizontalAlignment="Right"
                    Orientation="Horizontal" Margin="0,0,8,0"/>
      </Grid>
    </Border>
  </Grid>
</Window>'''


def make_btn(text, bg, hover, width=90):
    """Cree un bouton WPF stylise."""
    b = Button()
    b.Content  = text
    b.Width    = width
    b.Height   = 28
    b.Margin   = Thickness(6, 0, 0, 0)
    b.Background = SolidColorBrush(Color.FromRgb(
        int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)))
    b.Foreground = SolidColorBrush(Color.FromRgb(255, 255, 255))
    b.BorderThickness = Thickness(0)
    # Hover via tag — style inline non supporte proprement en IronPython 2.7,
    # on simule avec MouseEnter/Leave
    _bg  = b.Background
    _hov = SolidColorBrush(Color.FromRgb(
        int(hover[1:3], 16), int(hover[3:5], 16), int(hover[5:7], 16)))
    b.MouseEnter += lambda s, e: setattr(s, 'Background', _hov)
    b.MouseLeave += lambda s, e: setattr(s, 'Background', _bg)
    return b

def add_row(parent, label_text, ctrl, margin_top=6):
    """Ajoute une ligne label + controle dans le StackPanel body."""
    row = Grid()
    row.Margin = Thickness(0, margin_top, 0, 0)
    row.ColumnDefinitions.Add(ColumnDefinition())
    col2 = ColumnDefinition()
    col2.Width = GridLength(230)
    row.ColumnDefinitions.Add(col2)
    lbl = TextBlock()
    lbl.Text = label_text
    lbl.VerticalAlignment = VerticalAlignment.Center
    Grid.SetColumn(lbl, 0)
    Grid.SetColumn(ctrl, 1)
    row.Children.Add(lbl)
    row.Children.Add(ctrl)
    parent.Children.Add(row)
    return row

def make_combo(items, selected_name):
    cb = ComboBox()
    cb.Height = 24
    for it in items:
        cb.Items.Add(it)
    cb.SelectedItem = selected_name
    if cb.SelectedIndex == -1 and cb.Items.Count > 0:
        cb.SelectedIndex = 0
    return cb

def make_info_lbl(text, color="#1A237E"):
    t = TextBlock()
    t.Text       = text
    t.Foreground = SolidColorBrush(Color.FromRgb(
        int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)))
    t.Margin     = Thickness(0, 2, 0, 0)
    return t

def make_result_lbl():
    t = TextBlock()
    t.Foreground = SolidColorBrush(Color.FromRgb(26, 35, 126))
    t.FontWeight = System.Windows.FontWeights.SemiBold
    return t

def tooltip_hauteur(z_bot_cm, z_top_cm):
    """Retourne un tooltip texte indiquant la hauteur de l'element."""
    h = z_top_cm - z_bot_cm
    return u"Hauteur : {:.1f} cm".format(h)


# =============================================================================
# FORMULAIRE MUR
# =============================================================================
def run_wall_form(elem, levels_dict, z_bot_cm, z_top_cm):

    def _rlvl(bip):
        p = elem.get_Parameter(bip)
        if p and p.AsElementId().IntegerValue != -1:
            return doc.GetElement(p.AsElementId())
        return None
    def _roff(bip):
        p = elem.get_Parameter(bip)
        return p.AsDouble() if p else 0.0

    cur_base_lvl    = _rlvl(BuiltInParameter.WALL_BASE_CONSTRAINT)
    cur_base_off_ft = _roff(BuiltInParameter.WALL_BASE_OFFSET)
    cur_top_lvl     = _rlvl(BuiltInParameter.WALL_HEIGHT_TYPE)
    cur_top_off_ft  = _roff(BuiltInParameter.WALL_TOP_OFFSET)
    cur_uncon_h_ft  = _roff(BuiltInParameter.WALL_USER_HEIGHT_PARAM)

    if cur_base_lvl:
        z_bot_cm = ft_to_cm(cur_base_lvl.Elevation + cur_base_off_ft)
    if cur_top_lvl:
        z_top_cm = ft_to_cm(cur_top_lvl.Elevation + cur_top_off_ft)
    elif cur_base_lvl:
        z_top_cm = ft_to_cm(cur_base_lvl.Elevation + cur_base_off_ft + cur_uncon_h_ft)

    win = load_xaml(XAML_BASE)
    win.Title = TOOL_NAME
    win.Width = 520
    win.FindName("lbl_footer").Text = FOOTER_TEXT

    body = win.FindName("body")
    lvl_names = get_level_names_sorted(levels_dict)

    # Titre
    t = TextBlock()
    t.Text       = u"Mur sélectionné  –  Position réelle :"
    t.FontWeight = System.Windows.FontWeights.SemiBold
    t.Margin     = Thickness(0, 0, 0, 2)
    body.Children.Add(t)

    info = make_info_lbl(u"  Bas : {:.1f} cm    Haut : {:.1f} cm".format(z_bot_cm, z_top_cm), "#455A64")
    body.Children.Add(info)

    sep = Border()
    sep.Height = 1
    sep.Background = SolidColorBrush(Color.FromRgb(192, 208, 224))
    sep.Margin = Thickness(0, 8, 0, 4)
    body.Children.Add(sep)

    # Contrainte basse
    cb_base = make_combo(lvl_names, get_param_level_name(elem, BuiltInParameter.WALL_BASE_CONSTRAINT))
    cb_base.ToolTip = tooltip_hauteur(z_bot_cm, z_top_cm)
    add_row(body, u"Contrainte basse (niveau) :", cb_base)
    lbl_ob = make_result_lbl()
    add_row(body, u"Décalage bas calculé (cm) :", lbl_ob, 2)

    # Contrainte haute
    cb_top = make_combo([u"— Non contraint —"] + lvl_names,
                        get_param_level_name(elem, BuiltInParameter.WALL_HEIGHT_TYPE))
    cb_top.ToolTip = tooltip_hauteur(z_bot_cm, z_top_cm)
    add_row(body, u"Contrainte haute (niveau) :", cb_top, 10)
    lbl_ot = make_result_lbl()
    add_row(body, u"Décalage haut calculé (cm) :", lbl_ot, 2)
    lbl_h  = make_result_lbl()
    lbl_h.Foreground = SolidColorBrush(Color.FromRgb(46, 125, 50))
    add_row(body, u"Hauteur non contraint (cm) :", lbl_h, 2)

    # Hauteur calculée (contrainte ou non)
    lbl_hw = make_result_lbl()
    lbl_hw.Foreground = SolidColorBrush(Color.FromRgb(46, 125, 50))
    lbl_hw.FontWeight = System.Windows.FontWeights.Bold
    add_row(body, u"Hauteur (cm) :", lbl_hw, 6)

    state = {"ok": False, "base_off_ft": 0.0, "top_off_ft": None, "uncon_h_ft": None}

    def update(s=None, e=None):
        base_name = cb_base.SelectedItem
        top_item  = cb_top.SelectedItem
        if base_name and base_name in levels_dict:
            new_base = levels_dict[base_name]
            delta = (cur_base_lvl.Elevation - new_base.Elevation) if cur_base_lvl else 0.0
            state["base_off_ft"] = cur_base_off_ft + delta
            lbl_ob.Text = u"{:.1f} cm".format(ft_to_cm(state["base_off_ft"]))
        else:
            lbl_ob.Text = u"—"; state["base_off_ft"] = 0.0

        unconstrained = (top_item == u"— Non contraint —" or top_item not in levels_dict)
        if not unconstrained:
            new_top = levels_dict[top_item]
            delta = (cur_top_lvl.Elevation - new_top.Elevation) if cur_top_lvl else 0.0
            state["top_off_ft"] = cur_top_off_ft + delta
            lbl_ot.Text = u"{:.1f} cm".format(ft_to_cm(state["top_off_ft"]))
            lbl_h.Text  = u"—"; state["uncon_h_ft"] = None
        else:
            lbl_ot.Text = u"—"; state["top_off_ft"] = None
            state["uncon_h_ft"] = cur_uncon_h_ft
            lbl_h.Text = u"{:.1f} cm".format(ft_to_cm(cur_uncon_h_ft))

        # Hauteur totale affichee en vert gras
        base_name2 = cb_base.SelectedItem
        top_item2  = cb_top.SelectedItem
        unconstrained2 = (top_item2 == u"— Non contraint —" or top_item2 not in levels_dict)
        if base_name2 and base_name2 in levels_dict:
            z_b = ft_to_cm(levels_dict[base_name2].Elevation) + ft_to_cm(state["base_off_ft"])
            if not unconstrained2 and top_item2 in levels_dict:
                z_t = ft_to_cm(levels_dict[top_item2].Elevation) + ft_to_cm(state["top_off_ft"])
                lbl_hw.Text = u"{:.1f} cm".format(z_t - z_b)
            elif state["uncon_h_ft"] is not None:
                lbl_hw.Text = u"{:.1f} cm".format(ft_to_cm(state["uncon_h_ft"]))
            else:
                lbl_hw.Text = u"—"
        else:
            lbl_hw.Text = u"—"

    cb_base.SelectionChanged += update
    cb_top.SelectionChanged  += update
    update()

    btn_bar = win.FindName("btn_bar")
    btn_ok  = make_btn(u"Appliquer", "#2ECC71", "#27AE60")
    btn_nok = make_btn(u"Annuler",   "#E74C3C", "#C0392B")

    def on_ok(s, e):  state["ok"] = True;  win.Close()
    def on_nok(s, e): state["ok"] = False; win.Close()
    btn_ok.Click  += on_ok
    btn_nok.Click += on_nok
    btn_bar.Children.Add(btn_ok)
    btn_bar.Children.Add(btn_nok)

    win.ShowDialog()

    if not state["ok"]: return None
    return {
        "base_level":    levels_dict.get(cb_base.SelectedItem),
        "base_off_ft":   state["base_off_ft"],
        "top_level":     levels_dict.get(cb_top.SelectedItem),
        "top_off_ft":    state["top_off_ft"],
        "uncon_h_ft":    state["uncon_h_ft"],
    }


# =============================================================================
# FORMULAIRE SOL
# =============================================================================
def run_floor_form(elem, levels_dict, z_bot_cm):
    z_ref_ft = get_floor_z_ref(elem)
    z_ref_cm = ft_to_cm(z_ref_ft)

    win = load_xaml(XAML_BASE)
    win.Title = TOOL_NAME
    win.Width = 520
    win.FindName("lbl_footer").Text = FOOTER_TEXT

    body = win.FindName("body")
    lvl_names = get_level_names_sorted(levels_dict)

    t = TextBlock()
    t.Text       = u"Sol sélectionné  –  Position réelle :"
    t.FontWeight = System.Windows.FontWeights.SemiBold
    t.Margin     = Thickness(0, 0, 0, 2)
    body.Children.Add(t)
    body.Children.Add(make_info_lbl(
        u"  Z réf. (niv.+offset) : {:.1f} cm    Z face inf. : {:.1f} cm".format(z_ref_cm, z_bot_cm), "#455A64"))

    sep = Border(); sep.Height = 1
    sep.Background = SolidColorBrush(Color.FromRgb(192, 208, 224))
    sep.Margin = Thickness(0, 8, 0, 4)
    body.Children.Add(sep)

    cb_level = make_combo(lvl_names, get_param_level_name(elem, BuiltInParameter.LEVEL_PARAM))
    add_row(body, u"Niveau de référence :", cb_level)
    lbl_off = make_result_lbl()
    add_row(body, u"Décalage calculé (cm) :", lbl_off, 2)

    state = {"ok": False, "off_ft": 0.0}

    def update(s=None, e=None):
        name = cb_level.SelectedItem
        if name and name in levels_dict:
            off_cm = z_ref_cm - ft_to_cm(levels_dict[name].Elevation)
            lbl_off.Text = u"{:.1f} cm".format(off_cm)
            state["off_ft"] = cm_to_ft(off_cm)
        else:
            lbl_off.Text = u"—"; state["off_ft"] = 0.0

    cb_level.SelectionChanged += update
    update()

    btn_bar = win.FindName("btn_bar")
    btn_ok  = make_btn(u"Appliquer", "#2ECC71", "#27AE60")
    btn_nok = make_btn(u"Annuler",   "#E74C3C", "#C0392B")

    def on_ok(s, e):  state["ok"] = True;  win.Close()
    def on_nok(s, e): state["ok"] = False; win.Close()
    btn_ok.Click += on_ok; btn_nok.Click += on_nok
    btn_bar.Children.Add(btn_ok); btn_bar.Children.Add(btn_nok)

    win.ShowDialog()
    if not state["ok"]: return None
    return {"level": levels_dict.get(cb_level.SelectedItem), "off_ft": state["off_ft"]}


# =============================================================================
# FORMULAIRE POTEAU
# =============================================================================
def run_column_form(elem, levels_dict, z_bot_cm, z_top_cm):

    def _rlvl(bip):
        p = elem.get_Parameter(bip)
        if p and p.AsElementId().IntegerValue != -1:
            return doc.GetElement(p.AsElementId())
        return None
    def _roff(bip):
        p = elem.get_Parameter(bip); return p.AsDouble() if p else 0.0

    cur_base_lvl    = _rlvl(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    cur_base_off_ft = _roff(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
    cur_top_lvl     = _rlvl(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
    cur_top_off_ft  = _roff(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)

    if cur_base_lvl: z_bot_cm = ft_to_cm(cur_base_lvl.Elevation + cur_base_off_ft)
    if cur_top_lvl:  z_top_cm = ft_to_cm(cur_top_lvl.Elevation  + cur_top_off_ft)

    win = load_xaml(XAML_BASE)
    win.Title = TOOL_NAME
    win.Width = 520
    win.FindName("lbl_footer").Text = FOOTER_TEXT

    body = win.FindName("body")
    lvl_names = get_level_names_sorted(levels_dict)

    t = TextBlock()
    t.Text       = u"Poteau sélectionné  –  Position réelle :"
    t.FontWeight = System.Windows.FontWeights.SemiBold
    t.Margin     = Thickness(0, 0, 0, 2)
    body.Children.Add(t)
    body.Children.Add(make_info_lbl(
        u"  Bas : {:.1f} cm    Haut : {:.1f} cm".format(z_bot_cm, z_top_cm), "#455A64"))

    sep = Border(); sep.Height = 1
    sep.Background = SolidColorBrush(Color.FromRgb(192, 208, 224))
    sep.Margin = Thickness(0, 8, 0, 4)
    body.Children.Add(sep)

    cb_base = make_combo(lvl_names, get_param_level_name(elem, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM))
    cb_top  = make_combo(lvl_names, get_param_level_name(elem, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM))
    add_row(body, u"Niveau bas :", cb_base)
    lbl_ob = make_result_lbl()
    add_row(body, u"Décalage bas calculé (cm) :", lbl_ob, 2)

    # Hauteur calculée dynamiquement
    lbl_h = make_result_lbl()
    lbl_h.Foreground = SolidColorBrush(Color.FromRgb(46, 125, 50))
    lbl_h.FontWeight = System.Windows.FontWeights.Bold
    add_row(body, u"Hauteur (cm) :", lbl_h, 6)

    add_row(body, u"Niveau haut :", cb_top, 10)
    lbl_ot = make_result_lbl()
    add_row(body, u"Décalage haut calculé (cm) :", lbl_ot, 2)

    state = {"ok": False, "base_off_ft": 0.0, "top_off_ft": 0.0}

    def update(s=None, e=None):
        bn = cb_base.SelectedItem
        tn = cb_top.SelectedItem
        z_base_cm = None
        z_top_cm2 = None
        if bn and bn in levels_dict:
            delta = (cur_base_lvl.Elevation - levels_dict[bn].Elevation) if cur_base_lvl else 0.0
            state["base_off_ft"] = cur_base_off_ft + delta
            lbl_ob.Text = u"{:.1f} cm".format(ft_to_cm(state["base_off_ft"]))
            z_base_cm = ft_to_cm(levels_dict[bn].Elevation) + ft_to_cm(state["base_off_ft"])
        else:
            lbl_ob.Text = u"—"; state["base_off_ft"] = 0.0
        if tn and tn in levels_dict:
            delta = (cur_top_lvl.Elevation - levels_dict[tn].Elevation) if cur_top_lvl else 0.0
            state["top_off_ft"] = cur_top_off_ft + delta
            lbl_ot.Text = u"{:.1f} cm".format(ft_to_cm(state["top_off_ft"]))
            z_top_cm2 = ft_to_cm(levels_dict[tn].Elevation) + ft_to_cm(state["top_off_ft"])
        else:
            lbl_ot.Text = u"—"; state["top_off_ft"] = 0.0
        if z_base_cm is not None and z_top_cm2 is not None:
            lbl_h.Text = u"{:.1f} cm".format(z_top_cm2 - z_base_cm)
        else:
            lbl_h.Text = u"—"

    cb_base.SelectionChanged += update
    cb_top.SelectionChanged  += update
    update()

    btn_bar = win.FindName("btn_bar")
    btn_ok  = make_btn(u"Appliquer", "#2ECC71", "#27AE60")
    btn_nok = make_btn(u"Annuler",   "#E74C3C", "#C0392B")

    def on_ok(s, e):  state["ok"] = True;  win.Close()
    def on_nok(s, e): state["ok"] = False; win.Close()
    btn_ok.Click += on_ok; btn_nok.Click += on_nok
    btn_bar.Children.Add(btn_ok); btn_bar.Children.Add(btn_nok)

    win.ShowDialog()
    if not state["ok"]: return None
    return {
        "base_level":  levels_dict.get(cb_base.SelectedItem),
        "base_off_ft": state["base_off_ft"],
        "top_level":   levels_dict.get(cb_top.SelectedItem),
        "top_off_ft":  state["top_off_ft"],
    }


# =============================================================================
# FORMULAIRE OSSATURE
# =============================================================================
def run_framing_form(elem, levels_dict, z_bot_cm, z_top_cm):
    p_lvl = elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
    p_off = elem.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM)
    cur_lvl    = doc.GetElement(p_lvl.AsElementId())                  if p_lvl and p_lvl.AsElementId().IntegerValue != -1 else None
    cur_off_ft = p_off.AsDouble() if p_off else 0.0
    z_cm = ft_to_cm(cur_lvl.Elevation + cur_off_ft) if cur_lvl else (z_bot_cm + z_top_cm) / 2.0

    win = load_xaml(XAML_BASE)
    win.Title = TOOL_NAME
    win.Width = 520
    win.FindName("lbl_footer").Text = FOOTER_TEXT

    body = win.FindName("body")
    lvl_names = get_level_names_sorted(levels_dict)

    t = TextBlock()
    t.Text       = u"Ossature sélectionnée  –  Position réelle :"
    t.FontWeight = System.Windows.FontWeights.SemiBold
    t.Margin     = Thickness(0, 0, 0, 2)
    body.Children.Add(t)
    body.Children.Add(make_info_lbl(u"  Z (axe) : {:.1f} cm".format(z_cm), "#455A64"))

    sep = Border(); sep.Height = 1
    sep.Background = SolidColorBrush(Color.FromRgb(192, 208, 224))
    sep.Margin = Thickness(0, 8, 0, 4)
    body.Children.Add(sep)

    cb_level = make_combo(lvl_names, get_param_level_name(elem, BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM))
    add_row(body, u"Niveau de référence :", cb_level)
    lbl_off = make_result_lbl()
    add_row(body, u"Décalage calculé (cm) :", lbl_off, 2)

    state = {"ok": False, "off_ft": 0.0}

    def update(s=None, e=None):
        name = cb_level.SelectedItem
        if name and name in levels_dict:
            delta = (cur_lvl.Elevation - levels_dict[name].Elevation) if cur_lvl else 0.0
            state["off_ft"] = cur_off_ft + delta
            lbl_off.Text = u"{:.1f} cm".format(ft_to_cm(state["off_ft"]))
        else:
            lbl_off.Text = u"—"; state["off_ft"] = 0.0

    cb_level.SelectionChanged += update
    update()

    btn_bar = win.FindName("btn_bar")
    btn_ok  = make_btn(u"Appliquer", "#2ECC71", "#27AE60")
    btn_nok = make_btn(u"Annuler",   "#E74C3C", "#C0392B")

    def on_ok(s, e):  state["ok"] = True;  win.Close()
    def on_nok(s, e): state["ok"] = False; win.Close()
    btn_ok.Click += on_ok; btn_nok.Click += on_nok
    btn_bar.Children.Add(btn_ok); btn_bar.Children.Add(btn_nok)

    win.ShowDialog()
    if not state["ok"]: return None
    return {"level": levels_dict.get(cb_level.SelectedItem), "off_ft": state["off_ft"]}


# =============================================================================
# FORMULAIRE MODELE GENERIQUE
# =============================================================================
def run_generic_form(elem, levels_dict, z_bot_cm):
    level_param  = _find_generic_level_param(elem, writable_only=True)
    offset_param = _get_generic_offset_param(elem)
    p_lvl_ro = _find_generic_level_param(elem, writable_only=False)
    cur_lvl    = doc.GetElement(p_lvl_ro.AsElementId()) if p_lvl_ro else None
    cur_off_ft = offset_param.AsDouble() if offset_param else 0.0
    z_cm = ft_to_cm(cur_lvl.Elevation + cur_off_ft) if cur_lvl else z_bot_cm

    win = load_xaml(XAML_BASE)
    win.Title = TOOL_NAME
    win.Width = 520
    win.FindName("lbl_footer").Text = FOOTER_TEXT

    body = win.FindName("body")
    lvl_names = get_level_names_sorted(levels_dict)

    t = TextBlock()
    t.Text       = u"Modèle générique sélectionné  –  Position réelle :"
    t.FontWeight = System.Windows.FontWeights.SemiBold
    t.Margin     = Thickness(0, 0, 0, 2)
    body.Children.Add(t)
    body.Children.Add(make_info_lbl(u"  Z base : {:.1f} cm".format(z_cm), "#455A64"))

    if level_param is None:
        w = TextBlock()
        w.Text = u"⚠ Paramètre de niveau introuvable ou non modifiable."
        w.Foreground = SolidColorBrush(Color.FromRgb(198, 40, 40))
        w.Margin = Thickness(0, 4, 0, 0)
        body.Children.Add(w)
    if offset_param is None:
        w = TextBlock()
        w.Text = u"⚠ Paramètre d'offset introuvable sur cette famille."
        w.Foreground = SolidColorBrush(Color.FromRgb(198, 40, 40))
        w.Margin = Thickness(0, 2, 0, 0)
        body.Children.Add(w)

    sep = Border(); sep.Height = 1
    sep.Background = SolidColorBrush(Color.FromRgb(192, 208, 224))
    sep.Margin = Thickness(0, 8, 0, 4)
    body.Children.Add(sep)

    cb_level = make_combo(lvl_names, _get_generic_level_name(elem))
    add_row(body, u"Niveau de référence :", cb_level)
    lbl_off = make_result_lbl()
    add_row(body, u"Décalage calculé (cm) :", lbl_off, 2)

    state = {"ok": False, "off_ft": 0.0}

    def update(s=None, e=None):
        name = cb_level.SelectedItem
        if name and name in levels_dict:
            delta = (cur_lvl.Elevation - levels_dict[name].Elevation) if cur_lvl else 0.0
            state["off_ft"] = cur_off_ft + delta
            lbl_off.Text = u"{:.1f} cm".format(ft_to_cm(state["off_ft"]))
        else:
            lbl_off.Text = u"—"; state["off_ft"] = 0.0

    cb_level.SelectionChanged += update
    update()

    btn_bar = win.FindName("btn_bar")
    btn_ok  = make_btn(u"Appliquer", "#2ECC71", "#27AE60")
    btn_nok = make_btn(u"Annuler",   "#E74C3C", "#C0392B")

    def on_ok(s, e):  state["ok"] = True;  win.Close()
    def on_nok(s, e): state["ok"] = False; win.Close()
    btn_ok.Click += on_ok; btn_nok.Click += on_nok
    btn_bar.Children.Add(btn_ok); btn_bar.Children.Add(btn_nok)

    win.ShowDialog()
    if not state["ok"]: return None
    return {"level": levels_dict.get(cb_level.SelectedItem), "off_ft": state["off_ft"],
            "level_param": level_param, "offset_param": offset_param}


# =============================================================================
# POINT D'ENTREE
# =============================================================================
selection = uidoc.Selection.GetElementIds()
elem = None; elem_type = None

for eid in selection:
    el = doc.GetElement(eid)
    t  = detect_type(el)
    if t: elem = el; elem_type = t; break

if elem is None:
    TaskDialog.Show(u"Erreur",
        u"Aucun élément compatible sélectionné.\n"
        u"Supporte : mur, sol, poteau structurel, ossature structurelle, modèle générique.")
    import sys; sys.exit()

levels_dict        = get_all_levels()
z_bot_cm, z_top_cm = get_bounds_cm(elem)

# --- Ouverture du formulaire --------------------------------------------------
if elem_type == "wall":
    res = run_wall_form(elem, levels_dict, z_bot_cm, z_top_cm)
elif elem_type == "floor":
    res = run_floor_form(elem, levels_dict, z_bot_cm)
elif elem_type == "column":
    res = run_column_form(elem, levels_dict, z_bot_cm, z_top_cm)
elif elem_type == "framing":
    res = run_framing_form(elem, levels_dict, z_bot_cm, z_top_cm)
else:
    res = run_generic_form(elem, levels_dict, z_bot_cm)

if res is None:
    import sys; sys.exit()

# --- Application --------------------------------------------------------------
if elem_type == "wall":
    with Transaction(doc, u"Modifier contraintes mur") as t:
        t.Start()
        if res["base_level"]:
            elem.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).Set(res["base_level"].Id)
            elem.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).Set(res["base_off_ft"])
        p_top = elem.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if res["top_level"]:
            p_top.Set(res["top_level"].Id)
            elem.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(res["top_off_ft"])
        else:
            p_top.Set(ElementId.InvalidElementId)
            if res["uncon_h_ft"] is not None:
                elem.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(res["uncon_h_ft"])
        t.Commit()
    msg = u"Contraintes du mur mises à jour."

elif elem_type == "floor":
    with Transaction(doc, u"Modifier niveau sol") as t:
        t.Start()
        if res["level"]:
            elem.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(res["off_ft"])
            elem.get_Parameter(BuiltInParameter.LEVEL_PARAM).Set(res["level"].Id)
        t.Commit()
    msg = u"Niveau du sol mis à jour."

elif elem_type == "column":
    with Transaction(doc, u"Modifier contraintes poteau") as t:
        t.Start()
        if res["base_level"]:
            elem.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).Set(res["base_level"].Id)
            elem.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(res["base_off_ft"])
        if res["top_level"]:
            elem.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM).Set(res["top_level"].Id)
            elem.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(res["top_off_ft"])
        t.Commit()
    msg = u"Contraintes du poteau mises à jour."

elif elem_type == "framing":
    with Transaction(doc, u"Modifier niveau ossature") as t:
        t.Start()
        if res["level"]:
            elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM).Set(res["level"].Id)
            elem.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM).Set(res["off_ft"])
        t.Commit()
    msg = u"Niveau de l'ossature mis à jour."

else:  # generic
    if res["level_param"] is None and res["offset_param"] is None:
        TaskDialog.Show(u"Erreur",
            u"Cette famille ne possède aucun paramètre de niveau ou d'offset modifiable.")
        import sys; sys.exit()
    with Transaction(doc, u"Modifier niveau modèle générique") as t:
        t.Start()
        if res["level"]:
            if res["offset_param"] is not None: res["offset_param"].Set(res["off_ft"])
            if res["level_param"]  is not None: res["level_param"].Set(res["level"].Id)
        t.Commit()
    msg = u"Niveau du modèle générique mis à jour."

TaskDialog.Show(u"Succès", msg + u"\nPosition géométrique inchangée.")