# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Purge Reservations Supprimees"
# =============================================================================
__title__ = "Purge\nReservations"
__doc__   = "Affiche et supprime physiquement les reservations FGH_RES* marquees Supprime dans la maquette STR."

# =============================================================================
# IMPORTS — tous en tete, obligatoire IronPython
# =============================================================================
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
import System.IO
import System.Text
import System.Windows.Markup
import System.Windows.Media
import os
import re
import traceback
import xlsxwriter

from System.Collections.ObjectModel import ObservableCollection

from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    StorageType,
    ElementId,
    BuiltInParameter,
    View3D,
    ViewFamilyType,
    ViewFamily,
    BoundingBoxXYZ,
    XYZ,
)

doc   = revit.doc
uidoc = revit.uidoc

# =============================================================================
# CONSTANTES METIER
# =============================================================================
FAMILY_PREFIX = "FGH_RES"

PARAM_NUM         = "PVA_RES_DEM_NumReservation"
PARAM_DEMANDEUR   = "PVA_RES_DEM_Demandeur"
PARAM_DATE        = "PVA_RES_DEM_Date"
PARAM_COMMENTAIRE = "PVA_RES_DEM_Commentaire"
PARAM_NIVEAU      = "WSP_NiveauAssocie"
PARAM_VAL_STATUT  = "PVA_RES_VAL_Statut"
PARAM_RES_DEM     = "RES_Demandeur"
PARAM_RES_RESP    = "RES_Responsable"

STATUT_SUPPRIMEE  = "SUPPRIMEE"   # valeur ecrite dans PVA_RES_VAL_Statut par le Sync

VIEW_3D_NAME     = "STR_Purge_Reservations"
VIEW_3D_TEMPLATE = "3D_STR+RES"
VIEW_3D_MARGIN_M = 0.5

# =============================================================================
# LABELS LOCALISES — accents ecrits directement en UTF-8 (encoding declare ligne 1)
# =============================================================================
LBL_WINDOW = u"{}  [v{}]"
LBL_FOOTER = u"v{} | STR BIM Tools by Tony Varin"
LBL_TITRE  = u"Réservations marquées Supprimé dans la maquette STR : {} élément(s)"

LBL_TOTAL     = u"Total supprimées : {}"
LBL_SEL_COUNT = u"{} sélectionnée(s)"

HDR_SEL         = u""
HDR_NUM         = u"N° Réservation"
HDR_FAMILLE     = u"Famille"
HDR_NIVEAU      = u"Niveau"
HDR_VAL_STATUT  = u"Statut VAL"
HDR_DEMANDEUR   = u"Demandeur"
HDR_DATE_DEM    = u"Date dem."
HDR_DATE_SUPP   = u"Date suppression"
HDR_COMMENTAIRE = u"Commentaire"
HDR_RES_DEM     = u"RES Dem."
HDR_RES_RESP    = u"Responsable"

LBL_BTN_PURGE     = u"Purger"
LBL_BTN_VIEW3D    = u"Vue 3D"
LBL_BTN_EXCEL     = u"Exporter Excel"
LBL_BTN_CLOSE     = u"Fermer"
LBL_BTN_CHECK_ALL = u"Tout cocher"
LBL_BTN_UNCHECK   = u"Tout décocher"

MSG_NO_SUPPRIME = (
    u"Aucun élément FGH_RES* marqué Supprimé dans la maquette STR.\n\n"
    u"Rien à purger — la maquette est propre."
)
MSG_NOTHING_SEL = (
    u"Aucun élément sélectionné.\n\n"
    u"Cochez les réservations à supprimer définitivement."
)
MSG_CONFIRM_PURGE = (
    u"⚠  ATTENTION — Suppression physique irréversible\n\n"
    u"Vous êtes sur le point de supprimer définitivement {} réservation(s)\n"
    u"de la maquette STR.\n\n"
    u"Les éléments seront désépinglés puis supprimés.\n"
    u"Cette action ne peut pas être annulée.\n\n"
    u"Confirmer la suppression ?"
)
MSG_PURGE_RESULT = (
    u"Purge terminée :\n\n"
    u"  {} élément(s) supprimé(s)\n"
    u"  {} échec(s)"
)
MSG_PURGE_ERR      = u"Erreur lors de la suppression :\n\n{}"
MSG_ALL_PURGED     = u"Toutes les réservations supprimées ont été purgées.\n\nFermeture de l'outil."
MSG_VIEW3D_NONE    = u"Aucune réservation sélectionnée à visualiser."
MSG_VIEW3D_ERR     = u"Erreur lors de la création de la vue 3D :\n\n{}"
MSG_VIEW3D_OK      = u"Vue 3D '{}' ouverte autour de {} élément(s)."
MSG_VIEW3D_NOTPL   = u"Gabarit '{}' introuvable. La vue est créée sans gabarit."

EXCEL_COLUMNS = [
    (u"N° Réservation",   "Num",         18),
    (u"Famille",          "Famille",     28),
    (u"Niveau",           "Niveau",      14),
    (u"Statut VAL",       "ValStatut",   12),
    (u"Demandeur",        "Demandeur",   16),
    (u"Date dem.",        "DateDem",     12),
    (u"Date suppression", "DateSupp",    16),
    (u"Commentaire",      "Commentaire", 36),
    (u"RES Dem.",         "ResDem",      14),
    (u"Responsable",      "ResResp",     18),
]
LBL_EXCEL_OK  = u"Export Excel réussi :\n{}"
LBL_EXCEL_ERR = u"Erreur export Excel :\n{}"

# =============================================================================
# SECTION : LECTURE PARAMETRES REVIT
# =============================================================================

def _get_param_str(element, param_name):
    """Lit un parametre texte, retourne string ou None."""
    try:
        p = element.LookupParameter(param_name)
        if p and p.HasValue:
            if p.StorageType == StorageType.String:
                v = p.AsString()
                return v if v and v.strip() else None
            vs = p.AsValueString()
            return vs if vs and vs.strip() else None
    except Exception:
        pass
    return None


def _get_param_int(element, param_name):
    """Lit un parametre Integer, retourne int ou None."""
    try:
        p = element.LookupParameter(param_name)
        if p and p.HasValue and p.StorageType == StorageType.Integer:
            return p.AsInteger()
    except Exception:
        pass
    return None


def _get_family_name(element):
    try:
        return element.Symbol.Family.Name
    except Exception:
        return ""


def _date_to_sort_key(date_str):
    """
    Convertit une date DD/MM/YYYY en YYYYMMDD pour un tri chronologique correct.
    Retourne '00000000' si la date est vide ou non parseable.
    """
    if not date_str:
        return "00000000"
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return "{}{}{}".format(parts[2], parts[1].zfill(2), parts[0].zfill(2))
    except Exception:
        pass
    return "00000000"


def _extract_suppression_date(commentaire):
    """
    Extrait la date DD/MM/YYYY du commentaire 'Supprime le : DD/MM/YYYY'
    ecrit par le Sync lors du marquage Supprime.
    Retourne '' si non trouve.
    """
    if not commentaire:
        return ""
    try:
        m = re.search(r'(\d{2}/\d{2}/\d{4})', commentaire)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


# =============================================================================
# SECTION : COLLECTE DES ELEMENTS
# =============================================================================

def collect_supprime_reservations():
    """
    Collecte les FamilyInstance FGH_RES* dont PVA_RES_VAL_Statut == 'SUPPRIMEE'
    dans la maquette hote.
    Ce sont les elements marques par l'outil Sync (Cas B ancien, Cas C, Cas D).
    """
    result = []
    for e in FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements():
        try:
            if e.Symbol.Family.Name.startswith(FAMILY_PREFIX):
                if _get_param_str(e, PARAM_VAL_STATUT) == STATUT_SUPPRIMEE:
                    result.append(e)
        except Exception:
            pass
    return result


# =============================================================================
# SECTION : VUE 3D (elements hote uniquement — pas de lien necessaire)
# =============================================================================

def _get_or_create_3d_view(view_name):
    """Retourne la vue 3D nommee view_name ou la cree en isometrique."""
    existing = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v in existing:
        if not v.IsTemplate and v.Name == view_name:
            return v, False

    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if t.ViewFamily == ViewFamily.ThreeDimensional:
            vft = t
            break

    if vft is None:
        return None, False

    with revit.Transaction(u"STR - Creer vue 3D purge reservations"):
        view = View3D.CreateIsometric(doc, vft.Id)
        view.Name = view_name

    return view, True


def _find_view_template(template_name):
    """Recherche un gabarit de vue 3D par son nom exact."""
    for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
        if v.IsTemplate and v.Name == template_name:
            return v.Id
    return ElementId.InvalidElementId


def _compute_bounding_box(elements, margin_ft):
    """Bounding box englobant tous les elements, avec marge en pieds."""
    min_x = min_y = min_z =  1e18
    max_x = max_y = max_z = -1e18
    found = False

    for e in elements:
        try:
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            corners = [
                XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
                XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
                XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
                XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
            ]
            for c in corners:
                found = True
                if c.X < min_x: min_x = c.X
                if c.Y < min_y: min_y = c.Y
                if c.Z < min_z: min_z = c.Z
                if c.X > max_x: max_x = c.X
                if c.Y > max_y: max_y = c.Y
                if c.Z > max_z: max_z = c.Z
        except Exception:
            pass

    if not found:
        return None

    bb_out = BoundingBoxXYZ()
    bb_out.Min = XYZ(min_x - margin_ft, min_y - margin_ft, min_z - margin_ft)
    bb_out.Max = XYZ(max_x + margin_ft, max_y + margin_ft, max_z + margin_ft)
    return bb_out


def open_3d_cropbox(rows):
    """
    Ouvre la vue 3D VIEW_3D_NAME avec une zone de coupe autour
    des elements selectionnes dans le DataGrid (host uniquement).
    Retourne (view_or_None, message_str).
    """
    selected_elems = [r._element for r in rows if r.IsSelected and r._element is not None]
    if not selected_elems:
        return None, MSG_VIEW3D_NONE

    try:
        margin_ft = VIEW_3D_MARGIN_M * 3.28084
        crop_box  = _compute_bounding_box(selected_elems, margin_ft)
        if crop_box is None:
            return None, u"Impossible de calculer le bounding box des éléments sélectionnés."

        view, _created = _get_or_create_3d_view(VIEW_3D_NAME)
        if view is None:
            return None, u"Impossible de trouver ou créer un type de vue 3D isométrique."

        template_id  = _find_view_template(VIEW_3D_TEMPLATE)
        has_template = (template_id != ElementId.InvalidElementId)
        warn_tpl     = (u"\n\n" + MSG_VIEW3D_NOTPL.format(VIEW_3D_TEMPLATE)) if not has_template else ""

        with revit.Transaction(u"STR - Vue 3D purge reservations"):
            if has_template:
                view.ViewTemplateId = template_id
            view.IsSectionBoxActive = True
            view.SetSectionBox(crop_box)

        uidoc.ActiveView = view
        uidoc.RequestViewChange(view)
        return view, MSG_VIEW3D_OK.format(VIEW_3D_NAME, len(selected_elems)) + warn_tpl

    except Exception:
        return None, MSG_VIEW3D_ERR.format(traceback.format_exc())


# =============================================================================
# SECTION : OBJET DE DONNEE
# =============================================================================

class PurgeRow(object):
    """Objet de donnee pour une ligne du DataGrid — reservation marquee Supprime."""

    def __init__(self, element):
        self._element = element

        commentaire      = _get_param_str(element, PARAM_COMMENTAIRE) or ""
        date_suppression = _extract_suppression_date(commentaire)
        date_dem         = _get_param_str(element, PARAM_DATE)        or ""

        self.Num         = _get_param_str(element, PARAM_NUM)        or ""
        self.Famille     = _get_family_name(element)
        self.Niveau      = _get_param_str(element, PARAM_NIVEAU)     or ""
        self.ValStatut   = _get_param_str(element, PARAM_VAL_STATUT) or ""
        self.Demandeur   = _get_param_str(element, PARAM_DEMANDEUR)  or ""
        self.DateDem     = date_dem
        self.DateSupp    = date_suppression
        self.Commentaire = commentaire
        self.ResDem      = _get_param_str(element, PARAM_RES_DEM)    or ""
        self.ResResp     = _get_param_str(element, PARAM_RES_RESP)   or ""

        # Cles de tri chronologique pour les colonnes dates
        self.DateDemSort  = _date_to_sort_key(date_dem)
        self.DateSuppSort = _date_to_sort_key(date_suppression)

        # Toutes les lignes sont cochees et actionnables par defaut
        self.IsSelected   = True
        self.IsSelectable = True

        # Fond rose pale uniforme — signal visuel "element marque pour suppression"
        self.RowBg = "#FEE8E8"


def _build_rows(elements):
    """
    Construit la liste de PurgeRow.
    Tri : par date de suppression decroissante (plus recentes en premier),
          puis par numero de reservation.
    """
    rows = [PurgeRow(e) for e in elements]
    rows.sort(key=lambda r: (r.DateSuppSort, r.Num), reverse=True)
    return rows


# =============================================================================
# SECTION : SUPPRESSION PHYSIQUE
# =============================================================================

def purge_reservations(elements):
    """
    Supprime physiquement les elements Revit fournis.
    Procedure :
      1. Depingler (les copies du Sync sont toutes epinglees)
      2. doc.Delete(element.Id)
    Retourne (nb_ok, nb_err, err_detail_str_or_None).
    """
    nb_ok     = 0
    nb_err    = 0
    err_lines = []

    try:
        with revit.Transaction(u"STR - Purge Reservations Supprimees"):
            for e in elements:
                try:
                    # Depingler si necessaire — prerequis a la suppression
                    if e.Pinned:
                        e.Pinned = False
                    doc.Delete(e.Id)
                    nb_ok += 1
                except Exception as ex:
                    nb_err += 1
                    num = _get_param_str(e, PARAM_NUM) or str(e.Id.IntegerValue)
                    err_lines.append(u"  {} : {}".format(num, str(ex)))

    except Exception:
        # Echec au niveau de la transaction (rollback complet)
        return 0, len(elements), traceback.format_exc()

    return nb_ok, nb_err, (u"\n".join(err_lines) if err_lines else None)


# =============================================================================
# SECTION : INTERFACE WPF
# REGLE : XAML en ASCII strict — accents assignes via .Text / .Header en Python
# =============================================================================

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="" Width="1280" Height="680"
    ResizeMode="CanResize" Background="White"
    WindowStartupLocation="CenterScreen">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Titre -->
    <TextBlock x:Name="lbl_titre" Grid.Row="0"
               FontSize="13" FontWeight="SemiBold"
               Foreground="#C0392B"
               Margin="10,10,10,4"/>

    <!-- Barre de statistiques -->
    <Border Grid.Row="1" Background="#FDF0F0"
            BorderBrush="#E8C0C0" BorderThickness="0,0,0,1"
            Padding="10,6" Margin="0,0,0,4">
      <StackPanel Orientation="Horizontal">
        <Border Background="#FDDEDE" CornerRadius="4" Padding="10,3" Margin="0,0,14,0">
          <TextBlock x:Name="lbl_total" FontSize="12" FontWeight="SemiBold" Foreground="#C0392B"/>
        </Border>
        <Separator Width="1" Background="#E8C0C0" Margin="0,2,14,2"/>
        <Border Background="#E8F0FA" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_sel_count" FontSize="12" FontWeight="SemiBold"
                     Foreground="#2980B9"/>
        </Border>
        <Button x:Name="btn_check_all" Content="Tout cocher"
                Width="95" Height="24" Margin="0,0,4,0"
                Background="#BDC3C7" Foreground="#333333"
                BorderThickness="0" FontSize="11"/>
        <Button x:Name="btn_uncheck_all" Content="Tout decocher"
                Width="105" Height="24"
                Background="#BDC3C7" Foreground="#333333"
                BorderThickness="0" FontSize="11"/>
      </StackPanel>
    </Border>

    <!-- DataGrid -->
    <DataGrid x:Name="dg_main" Grid.Row="2"
              Margin="8,0,8,4"
              AutoGenerateColumns="False"
              IsReadOnly="False"
              GridLinesVisibility="Horizontal"
              BorderBrush="#E8C0C0" BorderThickness="1"
              HeadersVisibility="Column"
              SelectionMode="Single"
              CanUserResizeColumns="True"
              CanUserSortColumns="True"
              FontSize="12"
              RowBackground="#FEE8E8"
              AlternatingRowBackground="#FDDEDE">
      <DataGrid.RowStyle>
        <Style TargetType="DataGridRow">
          <Setter Property="Background" Value="{Binding RowBg}"/>
        </Style>
      </DataGrid.RowStyle>
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#F5CECE"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,4"/>
          <Setter Property="BorderBrush" Value="#E8C0C0"/>
          <Setter Property="BorderThickness" Value="0,0,1,1"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <!-- Colonne checkbox -->
        <DataGridCheckBoxColumn Header="" Binding="{Binding IsSelected, Mode=TwoWay}"
                                Width="34" IsReadOnly="False" SortMemberPath="IsSelected"/>
        <!-- Donnees element -->
        <DataGridTextColumn Header="Numero"      Binding="{Binding Num}"         Width="100" IsReadOnly="True"/>
        <DataGridTextColumn Header="Famille"     Binding="{Binding Famille}"     Width="165" IsReadOnly="True"/>
        <DataGridTextColumn Header="Niveau"      Binding="{Binding Niveau}"      Width="85"  IsReadOnly="True"/>
        <DataGridTextColumn Header="StatutVAL"   Binding="{Binding ValStatut}"   Width="80"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Demandeur"   Binding="{Binding Demandeur}"   Width="90"  IsReadOnly="True"/>
        <DataGridTextColumn Header="DateDem"     Binding="{Binding DateDem}"     Width="80"  IsReadOnly="True" SortMemberPath="DateDemSort"/>
        <DataGridTextColumn Header="DateSupp"    Binding="{Binding DateSupp}"    Width="95"  IsReadOnly="True" SortMemberPath="DateSuppSort"/>
        <DataGridTextColumn Header="Commentaire" Binding="{Binding Commentaire}" Width="200" IsReadOnly="True"/>
        <DataGridTextColumn Header="RESDem"      Binding="{Binding ResDem}"      Width="80"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Responsable" Binding="{Binding ResResp}"     Width="*"   IsReadOnly="True"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Footer -->
    <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#E8C0C0"
            Background="#FDF5F5" Padding="0,5">
      <Grid Margin="8,0">
        <TextBlock x:Name="footer_label"
                   FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal">
          <Button x:Name="btn_view3d" Content="Vue 3D"
                  Width="80" Height="28" Margin="0,0,6,0"
                  Background="#8E44AD" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_purge" Content="Purger"
                  Width="100" Height="28" Margin="0,0,6,0"
                  Background="#E74C3C" Foreground="White"
                  BorderThickness="0" FontSize="12" FontWeight="SemiBold"/>
          <Button x:Name="btn_export" Content="Exporter CSV"
                  Width="110" Height="28" Margin="0,0,6,0"
                  Background="#E67E22" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_close" Content="Fermer"
                  Width="80" Height="28"
                  Background="#3498DB" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>
"""

# Ordre identique aux colonnes XAML
COLUMN_HEADERS = [
    HDR_SEL,
    HDR_NUM, HDR_FAMILLE, HDR_NIVEAU,
    HDR_VAL_STATUT, HDR_DEMANDEUR, HDR_DATE_DEM,
    HDR_DATE_SUPP, HDR_COMMENTAIRE,
    HDR_RES_DEM, HDR_RES_RESP,
]


def _update_sel_count(window, rows):
    """Met a jour le compteur de selection et l'etat du bouton Purger."""
    nb_sel    = sum(1 for r in rows if r.IsSelected)
    btn_purge = window.FindName("btn_purge")
    window.FindName("lbl_sel_count").Text = LBL_SEL_COUNT.format(nb_sel)
    btn_purge.IsEnabled = nb_sel > 0
    if nb_sel > 0:
        btn_purge.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(231, 76, 60)
        )
    else:
        btn_purge.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(170, 170, 170)
        )


def _reload_grid(window, rows):
    """Recharge le DataGrid et met a jour le titre et les compteurs."""
    dg   = window.FindName("dg_main")
    coll = ObservableCollection[object]()
    for r in rows:
        coll.Add(r)
    dg.ItemsSource = coll

    nb = len(rows)
    window.FindName("lbl_titre").Text = LBL_TITRE.format(nb)
    window.FindName("lbl_total").Text = LBL_TOTAL.format(nb)
    _update_sel_count(window, rows)


def build_and_show(rows):

    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
    window = System.Windows.Markup.XamlReader.Load(stream)

    window.Title = TOOL_NAME

    # En-tetes colonnes (accents assignes apres chargement XAML)
    dg = window.FindName("dg_main")
    for i, hdr in enumerate(COLUMN_HEADERS):
        if i < dg.Columns.Count:
            dg.Columns[i].Header = hdr

    # Libelles boutons
    window.FindName("btn_purge").Content       = LBL_BTN_PURGE
    window.FindName("btn_view3d").Content      = LBL_BTN_VIEW3D
    window.FindName("btn_export").Content      = LBL_BTN_EXCEL
    window.FindName("btn_close").Content       = LBL_BTN_CLOSE
    window.FindName("btn_check_all").Content   = LBL_BTN_CHECK_ALL
    window.FindName("btn_uncheck_all").Content = LBL_BTN_UNCHECK

    # Footer
    window.FindName("footer_label").Text = LBL_FOOTER.format(SCRIPT_VERSION)

    # Chargement initial
    _reload_grid(window, rows)

    # Etat mutable partage entre les callbacks
    state = {"rows": rows}

    # -------------------------------------------------------------------------
    # CHECKBOX : CurrentCellChanged — event le plus fiable pour DataGridCheckBoxColumn
    # -------------------------------------------------------------------------
    def on_cell_changed(s, e):
        _update_sel_count(window, state["rows"])

    dg.CurrentCellChanged += on_cell_changed

    # -------------------------------------------------------------------------
    # BOUTONS TOUT COCHER / TOUT DECOCHER
    # -------------------------------------------------------------------------
    def on_check_all(s, e):
        for r in state["rows"]:
            r.IsSelected = True
        cur = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = cur
        _update_sel_count(window, state["rows"])

    def on_uncheck_all(s, e):
        for r in state["rows"]:
            r.IsSelected = False
        cur = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = cur
        _update_sel_count(window, state["rows"])

    window.FindName("btn_check_all").Click   += on_check_all
    window.FindName("btn_uncheck_all").Click += on_uncheck_all

    # -------------------------------------------------------------------------
    # BOUTON VUE 3D
    # -------------------------------------------------------------------------
    def on_view3d(s, e):
        _view, msg = open_3d_cropbox(state["rows"])
        forms.alert(msg, title=u"Vue 3D")
        if _view is not None:
            window.Close()

    window.FindName("btn_view3d").Click += on_view3d

    # -------------------------------------------------------------------------
    # BOUTON PURGER — suppression physique irreversible
    # -------------------------------------------------------------------------
    def on_purge(s, e):
        selected_rows = [r for r in state["rows"] if r.IsSelected]
        if not selected_rows:
            forms.alert(MSG_NOTHING_SEL, title=u"Purge")
            return

        nb = len(selected_rows)
        confirmed = forms.alert(
            MSG_CONFIRM_PURGE.format(nb),
            title=u"Confirmer la purge",
            yes=True, no=True
        )
        if not confirmed:
            return

        elements_to_delete = [r._element for r in selected_rows]
        nb_ok, nb_err, err_detail = purge_reservations(elements_to_delete)

        # Affichage du resultat
        result_msg = MSG_PURGE_RESULT.format(nb_ok, nb_err)
        if err_detail:
            result_msg += u"\n\nDétail des échecs :\n" + err_detail
        forms.alert(result_msg, title=u"Purge terminée")

        # Rafraichissement : recollecte les Supprime restants
        new_elements = collect_supprime_reservations()
        if not new_elements:
            forms.alert(MSG_ALL_PURGED, title=u"Purge terminee")
            window.Close()
            return

        new_rows      = _build_rows(new_elements)
        state["rows"] = new_rows
        _reload_grid(window, new_rows)

    window.FindName("btn_purge").Click += on_purge

    # -------------------------------------------------------------------------
    # BOUTON EXPORTER EXCEL — xlsxwriter natif pyRevit
    # -------------------------------------------------------------------------
    def on_export(s, e):
        desktop   = os.path.join(os.path.expanduser("~"), "Desktop")
        xlsx_path = os.path.join(desktop, "STR_Reservations_Supprimees.xlsx")
        rows_data = state["rows"]
        try:
            wb = xlsxwriter.Workbook(xlsx_path)
            ws = wb.add_worksheet(u"Reservations supprimees")

            # --- Formats ---
            fmt_hdr = wb.add_format({
                "bold": True, "bg_color": "#C0392B", "font_color": "#FFFFFF",
                "border": 1, "align": "center", "valign": "vcenter",
                "text_wrap": True,
            })
            fmt_row = wb.add_format({
                "border": 1, "valign": "vcenter",
                "bg_color": "#FEE8E8",
            })
            fmt_row_alt = wb.add_format({
                "border": 1, "valign": "vcenter",
                "bg_color": "#FDDEDE",
            })
            fmt_date = wb.add_format({
                "border": 1, "valign": "vcenter",
                "bg_color": "#FEE8E8", "align": "center",
            })
            fmt_date_alt = wb.add_format({
                "border": 1, "valign": "vcenter",
                "bg_color": "#FDDEDE", "align": "center",
            })

            # --- En-tetes ---
            ws.set_row(0, 22)
            ws.freeze_panes(1, 0)
            for col_idx, (header, _attr, col_width) in enumerate(EXCEL_COLUMNS):
                ws.set_column(col_idx, col_idx, col_width)
                ws.write(0, col_idx, header, fmt_hdr)

            # --- Donnees ---
            DATE_COLS = {"DateDem", "DateSupp"}   # colonnes centrees
            for row_idx, r in enumerate(rows_data):
                is_alt = (row_idx % 2 == 1)
                for col_idx, (_hdr, attr, _w) in enumerate(EXCEL_COLUMNS):
                    val  = getattr(r, attr, u"") or u""
                    is_date_col = attr in DATE_COLS
                    if is_date_col:
                        fmt = fmt_date_alt if is_alt else fmt_date
                    else:
                        fmt = fmt_row_alt if is_alt else fmt_row
                    ws.write(row_idx + 1, col_idx, val, fmt)

            wb.close()  # OBLIGATOIRE avec xlsxwriter (pas wb.save())
            forms.alert(LBL_EXCEL_OK.format(xlsx_path), title=u"Export Excel")

        except Exception as ex:
            forms.alert(LBL_EXCEL_ERR.format(str(ex)), title=u"Erreur")

    window.FindName("btn_export").Click += on_export

    # -------------------------------------------------------------------------
    # BOUTON FERMER
    # -------------------------------------------------------------------------
    window.FindName("btn_close").Click += lambda s, e: window.Close()

    window.ShowDialog()


# =============================================================================
# POINT D'ENTREE
# =============================================================================

def run():
    elements = collect_supprime_reservations()
    if not elements:
        forms.alert(MSG_NO_SUPPRIME, title=TOOL_NAME)
        return
    rows = _build_rows(elements)
    build_and_show(rows)


run()
