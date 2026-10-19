# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_dashboard.py - Fenetre de resultats du controle de conformite BEP.
#
# Trois zones de lecture, de la vue d'ensemble au detail :
#   - cartes KPI (elements analyses, regles conformes, ecarts, taux) ;
#   - bande de taux par categorie, avec barre proportionnelle ;
#   - deux tableaux lies : les regles a gauche, les ecarts de la regle
#     selectionnee a droite, avec selection directe dans Revit.
#
# Construite en WPF imperatif sur les helpers de lib/str_ui.py (charte STR).
# Ce module DEPEND de WPF et de l'API Revit (selection). IronPython 2.7.
# =============================================================================

import os

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
import System.Windows as SW
from System.Windows import (Window, Thickness, GridLength, GridUnitType,
                            WindowStartupLocation, ResizeMode, Style, Setter,
                            TextWrapping, TextTrimming, FontWeights,
                            HorizontalAlignment, VerticalAlignment,
                            MessageBox, MessageBoxButton, MessageBoxImage,
                            MessageBoxResult, Visibility)
from System.Windows.Controls import (Border, CheckBox, ColumnDefinition,
                                     Control, DataGrid,
                                     DataGridCheckBoxColumn,
                                     DataGridEditingUnit,
                                     DataGridGridLinesVisibility,
                                     DataGridHeadersVisibility,
                                     DataGridLength, DataGridLengthUnitType,
                                     DataGridRow, DataGridSelectionMode,
                                     DataGridTextColumn, Grid, GridSplitter,
                                     Orientation, StackPanel, TextBlock)
from System.Windows.Controls.Primitives import DataGridColumnHeader
from System.Windows.Data import Binding, BindingMode
from System.Collections.Generic import List as NetList

from Autodesk.Revit.DB import ElementId

import str_ui as UI
import fgh_bep_regles as R

LARGEUR = 1280
HAUTEUR = 860


# =============================================================================
# Modeles de lignes (attributs simples : le binding WPF les lit directement)
# =============================================================================
class LigneRegle(object):
    def __init__(self, d):
        self.data = d
        self.Id = d["id"]
        self.Categorie = d["categorie"]
        self.Regle = d["libelle"]
        self.Severite = d["severite"]
        self.Article = d["reference"]
        self.Statut = d["statut"]
        self.Ecarts = d["nb"] if d["statut"] == R.STATUT_NON_CONFORME else 0
        self.EcartsTexte = u"{0}".format(self.Ecarts) if self.Ecarts else u"-"
        if d["statut"] == R.STATUT_NON_CONFORME:
            self.RowFg = UI.couleur("erreur")
            self.RowWeight = FontWeights.SemiBold
        elif d["statut"] == R.STATUT_CONFORME:
            self.RowFg = UI.couleur("ok")
            self.RowWeight = FontWeights.Normal
        else:
            self.RowFg = UI.couleur("texte_gris")
            self.RowWeight = FontWeights.Normal


class LigneConstat(object):
    """Une ligne du tableau de detail.

    `Correction` et `Appliquer` sont lies en TwoWay : WPF ecrit directement
    dans l'objet Python quand l'utilisateur edite la cellule ou coche la
    case. Aucune notification en retour n'est necessaire, la lecture se fait
    au moment de l'enregistrement.
    """

    def __init__(self, cst):
        self.Objet = cst.objet
        self.TypeObjet = cst.type_objet
        self.Ecart = cst.detail
        self.Attendu = cst.attendu
        self.eid = cst.eid
        self.ElementId = _eid_texte(cst.eid)
        # La regle propose, l'utilisateur dispose : case decochee au depart,
        # rien n'est ecrit dans la maquette sans un geste explicite.
        self.Correction = cst.correction or u""
        self.Appliquer = False
        self.Corrigeable = cst.correction is not None


def _eid_texte(eid):
    if eid is None:
        return u""
    for attr in ("IntegerValue", "Value"):
        try:
            return u"{0}".format(getattr(eid, attr))
        except Exception:
            pass
    return u""


# =============================================================================
# Petits blocs visuels
# =============================================================================
def _carte(titre, valeur, cle_couleur="titre", largeur=150):
    """Carte KPI : libelle discret au-dessus, valeur en gros chiffre colore."""
    brd = UI.group_box()
    brd.Width = largeur
    brd.Margin = Thickness(0, 0, 8, 0)
    brd.Background = UI.hex_brush("#F0F6FF")
    sp = StackPanel()
    lbl = TextBlock()
    lbl.Text = titre
    lbl.FontSize = 10
    lbl.Foreground = UI.couleur("texte_gris")
    lbl.TextWrapping = TextWrapping.Wrap
    sp.Children.Add(lbl)
    val = TextBlock()
    val.Text = valeur
    val.FontSize = 22
    val.FontWeight = FontWeights.Bold
    val.Foreground = UI.couleur(cle_couleur)
    val.Margin = Thickness(0, 2, 0, 0)
    sp.Children.Add(val)
    brd.Child = sp
    return brd


def _carte_depot(depot, largeur=270):
    """Carte de statut : bandeau colore, verdict en capitales, phrase en clair.

    Volontairement plus large et plus haute que les cartes chiffrees : le taux
    de conformite pondere toutes les regles a egalite et ne dit pas si la
    maquette est deposable. Le lire en premier a induit en erreur, d'ou cette
    carte en tete de bande."""
    code, phrase, couleur = depot["code"], depot["phrase"], depot["couleur"]
    brd = UI.group_box()
    brd.Width = largeur
    brd.Margin = Thickness(0, 0, 8, 0)
    brd.Background = UI.hex_brush("#FFFFFF")
    brd.BorderBrush = UI.couleur(couleur)
    brd.BorderThickness = Thickness(1, 1, 1, 3)

    sp = StackPanel()
    lbl = TextBlock()
    lbl.Text = u"Aptitude au dépôt"
    lbl.FontSize = 10
    lbl.Foreground = UI.couleur("texte_gris")
    sp.Children.Add(lbl)
    val = TextBlock()
    val.Text = code
    val.FontSize = 20
    val.FontWeight = FontWeights.Bold
    val.Foreground = UI.couleur(couleur)
    val.Margin = Thickness(0, 2, 0, 1)
    sp.Children.Add(val)
    det = TextBlock()
    det.Text = phrase
    det.FontSize = 9
    det.Foreground = UI.couleur("texte_gris")
    det.TextWrapping = TextWrapping.Wrap
    sp.Children.Add(det)
    brd.Child = sp
    brd.ToolTip = u"{0} — {1}".format(code, phrase)
    return brd


def _couleur_taux(taux):
    if taux >= 95.0:
        return "appliquer"
    if taux >= 70.0:
        return "avertissement"
    return "erreur"


def _bloc_categorie(cat):
    """Nom de la categorie, barre proportionnelle et taux."""
    brd = UI.group_box()
    brd.Margin = Thickness(0, 0, 8, 0)
    brd.Padding = Thickness(8, 6, 8, 6)
    sp = StackPanel()

    titre = TextBlock()
    titre.Text = cat["nom"]
    titre.FontSize = 10
    titre.FontWeight = FontWeights.SemiBold
    titre.Foreground = UI.couleur("titre")
    titre.TextTrimming = TextTrimming.CharacterEllipsis
    sp.Children.Add(titre)

    # Barre en deux colonnes etoilees : elle suit le redimensionnement de la
    # fenetre sans aucun calcul de pixels.
    taux = float(cat.get("taux") or 0.0)
    barre = Grid()
    barre.Height = 8
    barre.Margin = Thickness(0, 5, 0, 4)
    c1 = ColumnDefinition()
    c1.Width = GridLength(max(taux, 0.001), GridUnitType.Star)
    c2 = ColumnDefinition()
    c2.Width = GridLength(max(100.0 - taux, 0.001), GridUnitType.Star)
    barre.ColumnDefinitions.Add(c1)
    barre.ColumnDefinitions.Add(c2)
    plein = Border()
    plein.Background = UI.couleur(_couleur_taux(taux))
    Grid.SetColumn(plein, 0)
    barre.Children.Add(plein)
    vide = Border()
    vide.Background = UI.hex_brush("#ECF0F3")
    Grid.SetColumn(vide, 1)
    barre.Children.Add(vide)
    sp.Children.Add(barre)

    detail = TextBlock()
    detail.Text = u"{0:.0f} %   {1}/{2}   {3} écarts".format(
        taux, cat["conformes"], max(cat["regles"] - cat["na"], 0), cat["constats"])
    detail.FontSize = 9
    detail.Foreground = UI.couleur("texte_gris")
    detail.TextTrimming = TextTrimming.CharacterEllipsis
    detail.ToolTip = u"{0} : {1} règle(s), {2} conforme(s), {3} non conforme(s), " \
                     u"{4} non applicable(s), {5} écart(s)".format(
                         cat["nom"], cat["regles"], cat["conformes"],
                         cat["non_conformes"], cat["na"], cat["constats"])
    sp.Children.Add(detail)

    brd.Child = sp
    return brd


def _grille(colonnes, lecture_seule=True):
    """DataGrid a la charte, colonnes = [(entete, propriete, largeur)].

    `lecture_seule` porte sur la grille entiere. Les colonnes creees ici sont
    toujours en lecture seule : une grille editable n'ouvre a l'edition que
    les colonnes ajoutees ensuite et declarees telles."""
    dg = DataGrid()
    dg.AutoGenerateColumns = False
    dg.IsReadOnly = lecture_seule
    dg.HeadersVisibility = DataGridHeadersVisibility.Column
    dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
    dg.AlternatingRowBackground = UI.couleur("ligne_alternee")
    dg.RowBackground = UI.hex_brush("#FFFFFF")
    dg.BorderBrush = UI.couleur("bordure")
    dg.CanUserResizeColumns = True
    dg.CanUserSortColumns = True
    dg.FontSize = 11
    dg.SelectionMode = DataGridSelectionMode.Extended

    entete = Style(clr.GetClrType(DataGridColumnHeader))
    entete.Setters.Add(Setter(
        Control.BackgroundProperty, UI.couleur("entete")))
    entete.Setters.Add(Setter(
        Control.FontWeightProperty, FontWeights.SemiBold))
    entete.Setters.Add(Setter(
        Control.PaddingProperty, Thickness(6, 3, 6, 3)))
    dg.ColumnHeaderStyle = entete

    for entete_txt, propriete, largeur in colonnes:
        col = DataGridTextColumn()
        col.Header = entete_txt
        col.Binding = Binding(propriete)
        col.IsReadOnly = True
        # "*" ou "1.4*" = colonne etoilee (part de l'espace restant),
        # un nombre = largeur fixe en pixels.
        if isinstance(largeur, str) and largeur.endswith("*"):
            part = float(largeur[:-1] or 1)
            col.Width = DataGridLength(part, DataGridLengthUnitType.Star)
        else:
            col.Width = DataGridLength(float(largeur))
        dg.Columns.Add(col)
    return dg


def _style_ligne_coloree():
    """Couleur et graisse portees par la ligne elle-meme (RowFg/RowWeight)."""
    st = Style(clr.GetClrType(DataGridRow))
    st.Setters.Add(Setter(Control.ForegroundProperty, Binding("RowFg")))
    st.Setters.Add(Setter(Control.FontWeightProperty, Binding("RowWeight")))
    return st


# =============================================================================
# Fenetre
# =============================================================================
class Dashboard(Window):

    def __init__(self, uidoc, resultat, version, tool_name):
        self.uidoc = uidoc
        self.resultat = resultat
        self.version = version
        self.tool_name = tool_name
        self._lignes = [LigneRegle(d) for d in resultat["regles"]]
        self._courante = None
        # Passe a True quand la fenetre se ferme pour relancer l'analyse
        # apres un changement de configuration (voir _on_configuration).
        self.relancer = False

        self.Title = tool_name
        self.Width = LARGEUR
        self.Height = HAUTEUR
        # Le footer porte cinq boutons et deux compteurs : sous 1200 px ils se
        # chevauchent.
        self.MinWidth = 1200
        self.MinHeight = 620
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.CanResize
        self.Background = UI.couleur("fond")
        self._construire()
        self._rafraichir()

    # -- construction ---------------------------------------------------------
    def _construire(self):
        root = Grid()
        for h in ["Auto", "Auto", "Auto", "Auto", "*", "Auto"]:
            root.RowDefinitions.Add(UI.rd(h))
        self.Content = root

        c = self.resultat["contexte"]
        titre = UI.barre_titre(u"{0}  |  {1}  |  Revit {2}".format(
            self.tool_name, c.get("titre", u""), c.get("version_revit", u"")))
        Grid.SetRow(titre, 0)
        root.Children.Add(titre)

        for rang, fabrique in ((1, self._bande_kpi),
                               (2, self._bande_categories),
                               (3, self._barre_filtres)):
            bloc = fabrique()
            Grid.SetRow(bloc, rang)
            root.Children.Add(bloc)

        corps = self._corps()
        Grid.SetRow(corps, 4)
        root.Children.Add(corps)

        footer, sp_btns, grid_f = UI.make_footer(self.version)
        Grid.SetRow(footer, 5)
        root.Children.Add(footer)
        self.lbl_corrections = UI.texte(u"", 10, brush=UI.couleur("ok"),
                                        marge=Thickness(0, 0, 12, 0))
        sp_btns.Children.Add(self.lbl_corrections)
        self.lbl_selection = UI.texte(u"", 10, brush=UI.couleur("texte_gris"),
                                      marge=Thickness(0, 0, 12, 0))
        sp_btns.Children.Add(self.lbl_selection)
        b_cfg = UI.footer_btn(u"Configuration", "titre", 120,
                              self._on_configuration)
        b_cfg.Margin = Thickness(0, 0, 6, 0)
        b_cfg.ToolTip = (u"Exceptions du projet : familles tolérées dans les "
                        u"catégories interdites, etc.")
        sp_btns.Children.Add(b_cfg)
        b_sel = UI.footer_btn(u"Sélectionner dans Revit", "fermer", 170,
                              self._on_selectionner)
        b_sel.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(b_sel)
        self.btn_corriger = UI.footer_btn(u"Enregistrer les corrections",
                                          "appliquer", 190,
                                          self._on_corriger)
        self.btn_corriger.Margin = Thickness(0, 0, 6, 0)
        self.btn_corriger.IsEnabled = False
        self.btn_corriger.ToolTip = (
            u"Renomme dans la maquette les objets dont la case « Appliquer » "
            u"est cochée. Une seule transaction, annulable par Ctrl+Z.")
        sp_btns.Children.Add(self.btn_corriger)
        b_exp = UI.footer_btn(u"Export XLSX", "exporter", 120, self._on_export)
        b_exp.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(b_exp)
        sp_btns.Children.Add(UI.footer_btn(u"Fermer", "annuler", 90,
                                           lambda s, e: self.Close()))
        grid_f.Children.Add(sp_btns)

    def _bande_kpi(self):
        k = self.resultat["kpi"]
        brd = Border()
        brd.Background = UI.hex_brush("#FAFCFF")
        brd.BorderBrush = UI.couleur("bordure")
        brd.BorderThickness = Thickness(0, 0, 0, 1)
        brd.Padding = Thickness(12, 10, 12, 4)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal

        sp.Children.Add(_carte_depot(self.resultat.get("depot") or {
            "code": u"?", "phrase": u"", "couleur": "texte_gris"}))
        cle_taux = _couleur_taux(k["taux"])
        sp.Children.Add(_carte(u"Taux de conformité",
                               u"{0:.0f} %".format(k["taux"]), cle_taux, 125))
        sp.Children.Add(_carte(u"Règles conformes",
                               u"{0}/{1}".format(k["conformes"], k["applicables"]),
                               "ok", 130))
        sp.Children.Add(_carte(u"Règles non conformes",
                               u"{0}".format(k["non_conformes"]), "erreur", 135))
        sp.Children.Add(_carte(u"Écarts relevés",
                               u"{0}".format(k["constats"]),
                               "erreur" if k["constats"] else "ok", 135))
        sp.Children.Add(_carte(u"Éléments analysés",
                               u"{0}".format(k["elements"]), "titre", 135))
        sp.Children.Add(_carte(u"Règles non applicables",
                               u"{0}".format(k["non_applicables"]),
                               "texte_gris", 135))
        brd.Child = sp
        return brd

    def _bande_categories(self):
        brd = Border()
        brd.Background = UI.hex_brush("#FAFCFF")
        brd.BorderBrush = UI.couleur("bordure")
        brd.BorderThickness = Thickness(0, 0, 0, 1)
        brd.Padding = Thickness(12, 4, 12, 10)
        # Colonnes egales plutot qu'une bande a largeur fixe : le nombre de
        # categories grandit avec le referentiel, les blocs se repartissent
        # toute la largeur au lieu de deborder.
        g = Grid()
        cats = self.resultat["categories"]
        for i, cat in enumerate(cats):
            cdef = ColumnDefinition()
            cdef.Width = GridLength(1, GridUnitType.Star)
            g.ColumnDefinitions.Add(cdef)
            bloc = _bloc_categorie(cat)
            if i == len(cats) - 1:
                bloc.Margin = Thickness(0)
            Grid.SetColumn(bloc, i)
            g.Children.Add(bloc)
        brd.Child = g
        return brd

    def _barre_filtres(self):
        brd = Border()
        brd.Background = UI.couleur("fond_filtre")
        brd.BorderBrush = UI.couleur("bordure")
        brd.BorderThickness = Thickness(0, 0, 0, 1)
        brd.Padding = Thickness(12, 7, 12, 7)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal

        sp.Children.Add(UI.texte(u"Catégorie :", marge=Thickness(0, 0, 6, 0)))
        items = [(u"Toutes", None)]
        for cat in self.resultat["categories"]:
            items.append((cat["nom"], cat["nom"]))
        self.cb_categorie = UI.combo(items, 0, 190)
        self.cb_categorie.SelectionChanged += self._on_filtre
        sp.Children.Add(self.cb_categorie)

        self.chk_ko = CheckBox()
        self.chk_ko.Content = u"Uniquement les non conformes"
        self.chk_ko.IsChecked = True
        self.chk_ko.FontSize = 11
        self.chk_ko.Margin = Thickness(14, 0, 0, 0)
        self.chk_ko.VerticalAlignment = VerticalAlignment.Center
        self.chk_ko.Checked += self._on_filtre
        self.chk_ko.Unchecked += self._on_filtre
        sp.Children.Add(self.chk_ko)

        sp.Children.Add(UI.texte(u"Recherche :", marge=Thickness(18, 0, 6, 0)))
        self.tb_recherche = UI.zone_texte(200)
        self.tb_recherche.TextChanged += self._on_filtre
        sp.Children.Add(self.tb_recherche)

        self.lbl_compte = UI.texte(u"", 11, brush=UI.couleur("texte_gris"),
                                   marge=Thickness(14, 0, 0, 0))
        sp.Children.Add(self.lbl_compte)

        brd.Child = sp
        return brd

    def _corps(self):
        g = Grid()
        g.Margin = Thickness(10, 8, 10, 6)
        # Le detail recoit un peu plus de place que la liste des regles : il
        # porte cinq colonnes de texte, dont deux longues.
        for part in (0.9, None, 1.1):
            cdef = ColumnDefinition()
            cdef.Width = (GridLength(6.0) if part is None
                          else GridLength(part, GridUnitType.Star))
            g.ColumnDefinitions.Add(cdef)

        # --- Gauche : les regles
        gauche = Grid()
        gauche.RowDefinitions.Add(UI.rd("Auto"))
        gauche.RowDefinitions.Add(UI.rd("*"))
        t = UI.section_hdr(u"Règles contrôlées")
        Grid.SetRow(t, 0)
        gauche.Children.Add(t)
        self.dg_regles = _grille([
            (u"ID", "Id", 46),
            (u"Catégorie", "Categorie", 105),
            (u"Règle", "Regle", "*"),
            (u"Sévérité", "Severite", 66),
            (u"Art.", "Article", 48),
            (u"Statut", "Statut", 86),
            (u"Écarts", "EcartsTexte", 50),
        ])
        self.dg_regles.RowStyle = _style_ligne_coloree()
        self.dg_regles.SelectionChanged += self._on_regle_selectionnee
        Grid.SetRow(self.dg_regles, 1)
        gauche.Children.Add(self.dg_regles)
        Grid.SetColumn(gauche, 0)
        g.Children.Add(gauche)

        split = GridSplitter()
        split.Width = 6
        split.HorizontalAlignment = HorizontalAlignment.Stretch
        split.Background = UI.hex_brush("#00000000")
        Grid.SetColumn(split, 1)
        g.Children.Add(split)

        # --- Droite : le detail de la regle selectionnee
        droite = Grid()
        droite.RowDefinitions.Add(UI.rd("Auto"))
        droite.RowDefinitions.Add(UI.rd("Auto"))
        droite.RowDefinitions.Add(UI.rd("*"))

        # Ligne d'entete : titre a gauche, cochage en masse a droite. Avec
        # plusieurs centaines d'ecarts par regle, cocher a la main ligne a
        # ligne ne serait pas tenable.
        entete = Grid()
        self.lbl_detail = UI.section_hdr(u"Détail")
        entete.Children.Add(self.lbl_detail)
        self.sp_cochage = StackPanel()
        self.sp_cochage.Orientation = Orientation.Horizontal
        self.sp_cochage.HorizontalAlignment = HorizontalAlignment.Right
        self.sp_cochage.Children.Add(UI.small_btn(
            u"Tout cocher", self._on_tout_cocher,
            u"Coche les lignes qui portent une correction proposée"))
        b_dec = UI.small_btn(u"Tout décocher", self._on_tout_decocher)
        b_dec.Margin = Thickness(0)
        self.sp_cochage.Children.Add(b_dec)
        entete.Children.Add(self.sp_cochage)
        Grid.SetRow(entete, 0)
        droite.Children.Add(entete)

        self.lbl_attendu = UI.texte(u"", 10, brush=UI.couleur("texte_gris"),
                                    marge=Thickness(0, 0, 0, 4))
        self.lbl_attendu.TextWrapping = TextWrapping.Wrap
        Grid.SetRow(self.lbl_attendu, 1)
        droite.Children.Add(self.lbl_attendu)

        self.dg_constats = _grille([
            (u"Objet", "Objet", "1.8*"),
            (u"Type", "TypeObjet", 90),
            (u"Écart constaté", "Ecart", "1.2*"),
            # « Attendu » repete le meme texte sur toutes les lignes d'une
            # regle : la colonne la plus sacrifiable quand la place manque.
            (u"Attendu (BEP)", "Attendu", "0.9*"),
        ], lecture_seule=False)

        # Les deux colonnes de correction n'existent que pour les regles qui
        # savent proposer un nom ; _afficher_detail les masque ailleurs.
        self.col_correction = DataGridTextColumn()
        self.col_correction.Header = u"Correction proposée"
        b = Binding("Correction")
        b.Mode = BindingMode.TwoWay
        self.col_correction.Binding = b
        self.col_correction.IsReadOnly = False
        self.col_correction.Width = DataGridLength(1.5,
                                                   DataGridLengthUnitType.Star)
        self.dg_constats.Columns.Add(self.col_correction)

        self.col_appliquer = DataGridCheckBoxColumn()
        self.col_appliquer.Header = u"Appliquer"
        b2 = Binding("Appliquer")
        b2.Mode = BindingMode.TwoWay
        self.col_appliquer.Binding = b2
        self.col_appliquer.IsReadOnly = False
        self.col_appliquer.SortMemberPath = "Appliquer"
        self.col_appliquer.Width = DataGridLength(64.0)
        self.dg_constats.Columns.Add(self.col_appliquer)

        col_eid = DataGridTextColumn()
        col_eid.Header = u"ElementId"
        col_eid.Binding = Binding("ElementId")
        col_eid.IsReadOnly = True
        col_eid.Width = DataGridLength(70.0)
        self.dg_constats.Columns.Add(col_eid)

        self.dg_constats.SelectionChanged += self._on_constat_selectionne
        # CurrentCellChanged est l'evenement fiable pour suivre une case a
        # cocher dans un DataGrid : Checked/Unchecked ne remontent pas.
        self.dg_constats.CurrentCellChanged += self._on_cellule_changee
        Grid.SetRow(self.dg_constats, 2)
        droite.Children.Add(self.dg_constats)
        Grid.SetColumn(droite, 2)
        g.Children.Add(droite)
        return g

    # -- comportement ---------------------------------------------------------
    def _lignes_filtrees(self):
        cat = UI.valeur_combo(self.cb_categorie)
        seulement_ko = bool(self.chk_ko.IsChecked)
        recherche = (self.tb_recherche.Text or u"").strip().lower()
        out = []
        for l in self._lignes:
            if cat and l.Categorie != cat:
                continue
            if seulement_ko and l.Statut != R.STATUT_NON_CONFORME:
                continue
            if recherche and recherche not in u"{0} {1} {2}".format(
                    l.Id, l.Regle, l.Categorie).lower():
                continue
            out.append(l)
        return out

    def _rafraichir(self, *_):
        lignes = self._lignes_filtrees()
        self.dg_regles.ItemsSource = None
        self.dg_regles.ItemsSource = lignes
        self.lbl_compte.Text = u"{0} règle(s) affichée(s) sur {1}".format(
            len(lignes), len(self._lignes))
        if lignes:
            self.dg_regles.SelectedIndex = 0
        else:
            self._afficher_detail(None)

    def _on_filtre(self, sender, e):
        self._rafraichir()

    def _on_regle_selectionnee(self, sender, e):
        self._afficher_detail(self.dg_regles.SelectedItem)

    def _afficher_detail(self, ligne):
        self._courante = ligne
        if ligne is None:
            self.lbl_detail.Text = u"Détail"
            self.lbl_attendu.Text = u""
            self.dg_constats.ItemsSource = None
            self._basculer_correction(False)
            self._maj_corrections()
            self._maj_selection()
            return
        d = ligne.data
        self.lbl_detail.Text = u"{0} - {1}".format(d["id"], d["libelle"])
        info = u"Article BEP {0}  |  sévérité {1}  |  {2}".format(
            d["reference"], d["severite"], d["statut"])
        if d["statut"] == R.STATUT_NA and d.get("motif_na"):
            info += u"  ({0})".format(d["motif_na"])
        if d.get("erreur"):
            info += u"  |  contrôle interrompu : {0}".format(d["erreur"])
        if d.get("tronque"):
            info += (u"  |  ATTENTION : {0} écarts, garde-fou mémoire "
                     u"atteint, {1} conservés".format(
                         d["nb"], len(d["constats"])))
        constats = d["constats"]
        limite = self._limite_affichage()
        if limite and len(constats) > limite:
            info += (u"  |  {0} écarts, {1} affichés ici — l'export "
                     u"XLSX les contient tous".format(
                         len(constats), limite))
            constats = constats[:limite]
        lignes = [LigneConstat(c) for c in constats]
        corrigeables = len([l for l in lignes if l.Corrigeable])
        if corrigeables:
            info += (u"  |  {0} correction(s) proposée(s) : cochez « Appliquer » "
                     u"puis « Enregistrer les corrections »".format(corrigeables))
        self.lbl_attendu.Text = info
        self.dg_constats.ItemsSource = None
        self.dg_constats.ItemsSource = lignes
        self._basculer_correction(corrigeables > 0)
        self._maj_corrections()
        self._maj_selection()

    def _limite_affichage(self):
        """Nombre d'écarts montrés par règle. Au-delà, la grille deviendrait
        inutilisable ; l'export reste complet."""
        try:
            return int(self.resultat["contexte"].get("limite_affichage") or 0)
        except (TypeError, ValueError, KeyError):
            return 2000

    def _basculer_correction(self, visible):
        """Les colonnes de correction n'apparaissent que sur les regles qui
        savent proposer un nom : ailleurs, deux colonnes vides ne feraient
        que voler de la place aux quatre autres."""
        etat = Visibility.Visible if visible else Visibility.Collapsed
        self.col_correction.Visibility = etat
        self.col_appliquer.Visibility = etat
        self.sp_cochage.Visibility = etat

    def _on_constat_selectionne(self, sender, e):
        self._maj_selection()

    def _on_cellule_changee(self, sender, e):
        self._maj_corrections()

    def _lignes_constats(self):
        src = self.dg_constats.ItemsSource
        return list(src) if src is not None else []

    def _valider_edition(self):
        """Une cellule en cours d'edition n'a pas encore ecrit dans l'objet
        Python : sans ce commit, la derniere saisie serait perdue au moment
        de lire les lignes."""
        for unite in (DataGridEditingUnit.Cell, DataGridEditingUnit.Row):
            try:
                self.dg_constats.CommitEdit(unite, True)
            except Exception:
                pass

    def _rafraichir_constats(self):
        self._valider_edition()
        try:
            self.dg_constats.Items.Refresh()
        except Exception:
            # Repli si la grille refuse le rafraichissement (edition en cours) :
            # on la realimente, les lignes etant les memes objets.
            lignes = self._lignes_constats()
            self.dg_constats.ItemsSource = None
            self.dg_constats.ItemsSource = lignes
        self._maj_corrections()

    def _on_tout_cocher(self, sender, e):
        for l in self._lignes_constats():
            if l.Corrigeable:
                l.Appliquer = True
        self._rafraichir_constats()

    def _on_tout_decocher(self, sender, e):
        for l in self._lignes_constats():
            l.Appliquer = False
        self._rafraichir_constats()

    def _cochees(self):
        return [l for l in self._lignes_constats() if l.Appliquer]

    def _maj_corrections(self):
        n = len(self._cochees())
        self.lbl_corrections.Text = (u"{0} à corriger".format(n) if n else u"")
        self.btn_corriger.IsEnabled = bool(n)

    def _maj_selection(self):
        n = 0
        try:
            n = self.dg_constats.SelectedItems.Count
        except Exception:
            pass
        total = 0
        try:
            src = self.dg_constats.ItemsSource
            total = len(src) if src is not None else 0
        except Exception:
            pass
        if n:
            self.lbl_selection.Text = u"{0} écart(s) sélectionné(s)".format(n)
        elif total:
            self.lbl_selection.Text = u"sélection vide : les {0} écarts".format(total)
        else:
            self.lbl_selection.Text = u""

    # -- actions --------------------------------------------------------------
    def _elements_cibles(self):
        """Constats selectionnes, ou tous ceux de la regle affichee."""
        lignes = []
        try:
            for it in self.dg_constats.SelectedItems:
                lignes.append(it)
        except Exception:
            pass
        if not lignes:
            src = self.dg_constats.ItemsSource
            lignes = list(src) if src is not None else []
        ids = NetList[ElementId]()
        for l in lignes:
            if l.eid is not None:
                ids.Add(l.eid)
        return ids

    def _on_selectionner(self, sender, e):
        ids = self._elements_cibles()
        if ids.Count == 0:
            MessageBox.Show(
                u"Aucun élément de la maquette n'est associé à ces écarts "
                u"(règle portant sur le projet lui-même, ou objet non "
                u"selectionnable).",
                self.tool_name, MessageBoxButton.OK,
                MessageBoxImage.Information)
            return
        try:
            self.uidoc.Selection.SetElementIds(ids)
            self.uidoc.ShowElements(ids)
        except Exception as ex:
            MessageBox.Show(u"Sélection impossible : {0}".format(ex),
                               self.tool_name, MessageBoxButton.OK,
                               MessageBoxImage.Warning)

    def _on_configuration(self, sender, e):
        # Import tardif : la fenetre de reglages ne doit peser ni sur
        # l'ouverture du dashboard, ni la faire tomber si elle manque.
        try:
            import fgh_bep_reglages
        except Exception as ex:
            MessageBox.Show(
                u"Configuration indisponible : {0}".format(ex),
                self.tool_name, MessageBoxButton.OK, MessageBoxImage.Error)
            return
        if not fgh_bep_reglages.afficher(self, self.tool_name, self.version):
            return
        # Les resultats affiches datent d'avant le changement : ils ne
        # peuvent pas etre corriges a la volee, seule une nouvelle analyse
        # dit la verite. On la propose plutot que de laisser un ecran perime.
        reponse = MessageBox.Show(
            u"Configuration enregistrée.\n\nLes résultats affichés ont ete "
            u"calculés avec l'ancienne configuration.\n\nRelancer l'analyse "
            u"maintenant ?",
            self.tool_name, MessageBoxButton.YesNo,
            MessageBoxImage.Question)
        if reponse == MessageBoxResult.Yes:
            self.relancer = True
            self.Close()

    def _on_corriger(self, sender, e):
        self._valider_edition()
        cochees = self._cochees()
        if not cochees:
            MessageBox.Show(
                u"Aucune ligne n'est cochée.\n\nCochez la case « Appliquer » "
                u"des lignes à renommer, ou utilisez « Tout cocher ».",
                self.tool_name, MessageBoxButton.OK,
                MessageBoxImage.Information)
            return

        apercu = u"\n".join([u"  {0}   ->   {1}".format(l.Objet, l.Correction)
                             for l in cochees[:12]])
        if len(cochees) > 12:
            apercu += u"\n  ... et {0} autre(s)".format(len(cochees) - 12)
        reponse = MessageBox.Show(
            u"{0} objet(s) vont être renommés dans la maquette :\n\n{1}\n\n"
            u"L'operation forme une seule transaction, annulable par Ctrl+Z."
            u"\n\nContinuer ?".format(len(cochees), apercu),
            self.tool_name, MessageBoxButton.YesNo, MessageBoxImage.Question)
        if reponse != MessageBoxResult.Yes:
            return

        # Import tardif : l'ecriture dans la maquette ne doit pas peser sur
        # l'ouverture de la fenetre, ni son absence la faire tomber.
        try:
            import fgh_bep_correction
        except Exception as ex:
            MessageBox.Show(u"Correction indisponible : {0}".format(ex),
                            self.tool_name, MessageBoxButton.OK,
                            MessageBoxImage.Error)
            return

        motifs = {}
        try:
            motifs = self.resultat["contexte"].get("motifs_nommage") or {}
        except Exception:
            pass
        corrections = [
            fgh_bep_correction.Correction(l.TypeObjet, l.eid, l.Objet,
                                          l.Correction)
            for l in cochees]
        try:
            reussis, echecs = fgh_bep_correction.appliquer(
                self.uidoc.Document, corrections, motifs)
        except Exception as ex:
            MessageBox.Show(
                u"Renommage impossible : {0}\n\nAucune modification n'a ete "
                u"conservee.".format(ex),
                self.tool_name, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        msg = u"{0} objet(s) renommé(s).".format(reussis)
        if echecs:
            detail = u"\n".join([u"  {0} -> {1} : {2}".format(a, b, m)
                                 for a, b, m in echecs[:12]])
            if len(echecs) > 12:
                detail += u"\n  ... et {0} autre(s)".format(len(echecs) - 12)
            msg += u"\n\n{0} refus :\n{1}".format(len(echecs), detail)
        if not reussis:
            MessageBox.Show(msg, self.tool_name, MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return

        reponse = MessageBox.Show(
            u"{0}\n\nLes résultats affichés datent d'avant le renommage."
            u"\n\nRelancer l'analyse maintenant ?".format(msg),
            self.tool_name, MessageBoxButton.YesNo, MessageBoxImage.Information)
        if reponse == MessageBoxResult.Yes:
            self.relancer = True
            self.Close()

    def _on_export(self, sender, e):
        # Imports tardifs : xlsxwriter ne doit peser sur l'ouverture de la
        # fenetre, et son absence doit se dire, pas faire tomber le handler.
        try:
            import fgh_bep_export
            from Microsoft.Win32 import SaveFileDialog
        except Exception as ex:
            MessageBox.Show(
                u"Export indisponible : {0}\n\nLe module xlsxwriter fourni "
                u"avec pyRevit est introuvable.".format(ex),
                self.tool_name, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        titre = self.resultat["contexte"].get("titre") or u"Maquette"
        defaut = u"{0}_Controle_BEP.xlsx".format(
            u"".join(ch if (ch.isalnum() or ch in u"_-") else u"_" for ch in titre))
        dlg = SaveFileDialog()
        dlg.Title = u"Exporter le contrôle de conformité BEP"
        dlg.Filter = u"Classeur Excel (*.xlsx)|*.xlsx"
        dlg.FileName = defaut
        if not dlg.ShowDialog():
            return
        chemin = dlg.FileName
        try:
            onglets, constats = fgh_bep_export.exporter(chemin, self.resultat,
                                                        self.version)
        except Exception as ex:
            MessageBox.Show(
                u"Export impossible : {0}\n\nSi le fichier est déjà ouvert "
                u"dans Excel, fermez-le puis relancez l'export.".format(ex),
                self.tool_name, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        reponse = MessageBox.Show(
            u"Export terminé.\n\n{0}\n\n{1} onglet(s), {2} écart(s) détaillés."
            u"\n\nOuvrir le fichier ?".format(chemin, onglets, constats),
            self.tool_name, MessageBoxButton.YesNo,
            MessageBoxImage.Information)
        if reponse == MessageBoxResult.Yes:
            _ouvrir(chemin)


def _ouvrir(chemin):
    try:
        os.startfile(chemin)
        return
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", chemin], shell=False)
    except Exception:
        pass


def afficher(uidoc, resultat, version, tool_name):
    """Affiche les resultats. Retourne True si l'utilisateur a change la
    configuration et demande une nouvelle analyse : c'est l'appelant qui
    relance, lui seul dispose de la fenetre de progression."""
    w = Dashboard(uidoc, resultat, version, tool_name)
    w.ShowDialog()
    return w.relancer
