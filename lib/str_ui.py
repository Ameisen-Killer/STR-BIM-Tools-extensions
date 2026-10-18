# -*- coding: utf-8 -*-
# =============================================================================
# str_ui.py - Helpers WPF communs a l'extension STR Bim Tools.
#
# Charte graphique unique : couleurs, barre de titre bleue, boites de section,
# bande footer. Les scripts construits en WPF imperatif (sans XAML) doivent
# utiliser ces helpers au lieu de recopier les memes fonctions localement.
#
# Ce module DEPEND de WPF uniquement (pas de l'API Revit).
# Compatible IronPython 2.7 (Revit 2024) et IronPython 3.4 (Revit 2025+).
# =============================================================================

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System.Windows as SW
from System.Windows import Thickness, GridLength, GridUnitType
from System.Windows.Controls import (
    Border, Button, CheckBox, ComboBox, ComboBoxItem, ColumnDefinition,
    Grid, Orientation, RowDefinition, StackPanel, TextBlock, TextBox,
)
from System.Windows.Media import SolidColorBrush, Color


# -----------------------------------------------------------------------------
# Palette (charte STR BIM Tools)
# -----------------------------------------------------------------------------
COULEURS = {
    "fond":            "#FFFFFF",
    "titre":           "#2F6496",   # barre de titre + libelles de section
    "bordure":         "#C0D0E0",
    "fond_section":    "#FAFCFF",
    "fond_filtre":     "#F0F6FF",
    "fond_footer":     "#F5F5F5",
    "texte_footer":    "#888888",
    "texte":           "#333333",
    "texte_gris":      "#666666",
    "ligne_alternee":  "#E8F0FA",
    "entete":          "#D0E4F7",
    "appliquer":       "#2ECC71",
    "annuler":         "#E74C3C",
    "fermer":          "#3498DB",
    "exporter":        "#E67E22",
    "secondaire":      "#E0E0E0",
    "ok":              "#1a7c3e",
    "avertissement":   "#b85c00",
    "erreur":          "#cc0000",
}


def hex_brush(hex_str):
    """'#RRGGBB' ou '#AARRGGBB' -> SolidColorBrush."""
    hex_str = hex_str.lstrip("#")
    a = 255
    if len(hex_str) == 8:
        a = int(hex_str[0:2], 16)
        hex_str = hex_str[2:]
    return SolidColorBrush(Color.FromArgb(a,
                                          int(hex_str[0:2], 16),
                                          int(hex_str[2:4], 16),
                                          int(hex_str[4:6], 16)))


def couleur(cle):
    """Brush de la palette par nom logique (voir COULEURS)."""
    return hex_brush(COULEURS[cle])


# -----------------------------------------------------------------------------
# Grille
# -----------------------------------------------------------------------------
def rd(h):
    """RowDefinition : '*' = etoile, un nombre = pixels, autre = Auto."""
    d = RowDefinition()
    d.Height = _longueur(h)
    return d


def cd(w):
    """ColumnDefinition : '*' = etoile, un nombre = pixels, autre = Auto."""
    d = ColumnDefinition()
    d.Width = _longueur(w)
    return d


def _longueur(v):
    if v == "*":
        return GridLength(1, GridUnitType.Star)
    if isinstance(v, (int, float)):
        return GridLength(float(v))
    return GridLength.Auto


# -----------------------------------------------------------------------------
# Blocs de base
# -----------------------------------------------------------------------------
def barre_titre(texte, icone=None):
    """Bande de titre bleue #2F6496 (ligne 0 de la fenetre)."""
    brd = Border()
    brd.Background = couleur("titre")
    brd.Padding = Thickness(14, 9, 14, 9)
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    if icone:
        ic = TextBlock()
        ic.Text = icone + u"  "
        ic.FontSize = 15
        ic.Foreground = hex_brush("#FFFFFF")
        ic.VerticalAlignment = SW.VerticalAlignment.Center
        sp.Children.Add(ic)
    tb = TextBlock()
    tb.Text = texte
    tb.FontSize = 13
    tb.FontWeight = SW.FontWeights.SemiBold
    tb.Foreground = hex_brush("#FFFFFF")
    tb.VerticalAlignment = SW.VerticalAlignment.Center
    sp.Children.Add(tb)
    brd.Child = sp
    return brd


def section_hdr(texte):
    """Libelle de section bleu - separateur visuel entre les groupes."""
    tb = TextBlock()
    tb.Text = texte
    tb.FontSize = 11
    tb.FontWeight = SW.FontWeights.SemiBold
    tb.Foreground = couleur("titre")
    tb.Margin = Thickness(0, 8, 0, 3)
    return tb


def group_box(stretch=False):
    """Boite de groupe : bordure #C0D0E0 + fond #FAFCFF."""
    gb = Border()
    gb.BorderBrush = couleur("bordure")
    gb.BorderThickness = Thickness(1)
    gb.Background = couleur("fond_section")
    gb.Padding = Thickness(10, 8, 10, 8)
    gb.Margin = Thickness(0, 0, 0, 0 if stretch else 8)
    return gb


def texte(contenu, taille=11, gras=False, brush=None, marge=None):
    """TextBlock courant."""
    tb = TextBlock()
    tb.Text = contenu
    tb.FontSize = taille
    if gras:
        tb.FontWeight = SW.FontWeights.SemiBold
    tb.Foreground = brush if brush is not None else couleur("texte")
    tb.VerticalAlignment = SW.VerticalAlignment.Center
    if marge is not None:
        tb.Margin = marge
    return tb


def checkbox(libelle, coche=False, infobulle=None):
    cb = CheckBox()
    cb.Content = libelle
    cb.IsChecked = coche
    cb.FontSize = 11
    cb.Margin = Thickness(0, 2, 0, 2)
    if infobulle:
        cb.ToolTip = infobulle
    return cb


def zone_texte(largeur=210, valeur=u""):
    tb = TextBox()
    tb.Width = largeur
    tb.Height = 24
    tb.FontSize = 11
    tb.Text = valeur
    tb.Padding = Thickness(4, 2, 4, 2)
    tb.BorderBrush = hex_brush("#AAAAAA")
    return tb


def combo(items, index=0, largeur=210, infobulle=None):
    """
    ComboBox alimentee par une liste de (libelle, valeur).
    La valeur est stockee dans ComboBoxItem.Tag ; utiliser valeur_combo().
    """
    cb = ComboBox()
    cb.Width = largeur
    cb.FontSize = 11
    for libelle, valeur in items:
        it = ComboBoxItem()
        it.Content = libelle
        it.Tag = valeur
        cb.Items.Add(it)
    if cb.Items.Count:
        cb.SelectedIndex = max(0, min(index, cb.Items.Count - 1))
    if infobulle:
        cb.ToolTip = infobulle
    return cb


def valeur_combo(cb, defaut=None):
    """Valeur (Tag) de l'element selectionne d'un combo cree par combo()."""
    it = cb.SelectedItem
    return it.Tag if it is not None else defaut


def selectionner_valeur(cb, valeur):
    """Selectionne l'element dont le Tag vaut `valeur`. True si trouve."""
    for i in range(cb.Items.Count):
        if cb.Items[i].Tag == valeur:
            cb.SelectedIndex = i
            return True
    return False


def ligne_champ(libelle, controle, largeur_libelle=150):
    """Ligne 'libelle : controle' alignee horizontalement."""
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    sp.Margin = Thickness(0, 0, 0, 5)
    lbl = texte(libelle, marge=Thickness(0))
    lbl.Width = largeur_libelle
    sp.Children.Add(lbl)
    sp.Children.Add(controle)
    return sp


# -----------------------------------------------------------------------------
# Boutons
# -----------------------------------------------------------------------------
def small_btn(libelle, handler, infobulle=None):
    """Bouton secondaire gris (Tout selectionner, Effacer le filtre...)."""
    b = Button()
    b.Content = libelle
    b.Height = 24
    b.FontSize = 11
    b.Padding = Thickness(8, 0, 8, 0)
    b.Margin = Thickness(0, 0, 6, 0)
    b.Background = couleur("secondaire")
    b.BorderThickness = Thickness(0)
    b.Click += handler
    if infobulle:
        b.ToolTip = infobulle
    return b


def footer_btn(libelle, cle_couleur, largeur, handler):
    """Bouton colore de la bande footer. cle_couleur = nom dans COULEURS."""
    b = Button()
    b.Content = libelle
    b.Width = largeur
    b.Height = 28
    b.Background = couleur(cle_couleur)
    b.Foreground = hex_brush("#FFFFFF")
    b.FontWeight = SW.FontWeights.SemiBold
    b.BorderThickness = Thickness(0)
    b.Click += handler
    return b


def make_footer(version):
    """
    Bande footer standard : separateur + version a gauche + boutons a droite.
    Retourne (border, stackpanel_boutons, grid_interne).

        footer, sp_btns, grid_f = make_footer(SCRIPT_VERSION)
        Grid.SetRow(footer, N); root.Children.Add(footer)
        sp_btns.Children.Add(footer_btn(...))
        grid_f.Children.Add(sp_btns)
    """
    brd = Border()
    brd.BorderThickness = Thickness(0, 1, 0, 0)
    brd.BorderBrush = couleur("bordure")
    brd.Background = couleur("fond_footer")
    brd.Padding = Thickness(0, 6, 0, 6)
    g = Grid()
    lbl = TextBlock()
    lbl.Text = u"v{0} | STR BIM Tools by Tony Varin".format(version)
    lbl.FontSize = 10
    lbl.Foreground = couleur("texte_footer")
    lbl.VerticalAlignment = SW.VerticalAlignment.Center
    lbl.Margin = Thickness(10, 0, 0, 0)
    g.Children.Add(lbl)
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    sp.HorizontalAlignment = SW.HorizontalAlignment.Right
    sp.Margin = Thickness(0, 0, 10, 0)
    brd.Child = g
    return brd, sp, g


# -----------------------------------------------------------------------------
# Formatage
# -----------------------------------------------------------------------------
def fmt_duree(secondes):
    """Secondes -> 'MM:SS', ou 'H:MM:SS' au-dela d'une heure."""
    s = int(secondes if secondes and secondes > 0 else 0)
    h, reste = divmod(s, 3600)
    m, sec = divmod(reste, 60)
    if h:
        return u"{0}:{1:02d}:{2:02d}".format(h, m, sec)
    return u"{0:02d}:{1:02d}".format(m, sec)


def fmt_taille(octets):
    """Octets -> 'x.y Mo' / 'x Ko' / 'x o'."""
    try:
        o = float(octets)
    except (TypeError, ValueError):
        return u"-"
    if o >= 1048576.0:
        return u"{0:.1f} Mo".format(o / 1048576.0)
    if o >= 1024.0:
        return u"{0:.0f} Ko".format(o / 1024.0)
    return u"{0:.0f} o".format(o)
