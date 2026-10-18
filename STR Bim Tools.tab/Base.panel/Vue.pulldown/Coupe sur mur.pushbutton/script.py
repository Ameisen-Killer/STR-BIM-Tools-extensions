# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "4.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Coupe sur mur lie"
# =============================================================================
# Cree une vue de coupe (ViewSection) parallele a la face d'un mur dans un lien.
#
# Workflow :
#   1. Clic sur un mur dans un lien Revit
#   2. La face est determinee automatiquement par la position du curseur
#   3. Propagation en chaine : tous les murs colineaires en contact (gap<10cm)
#   4. La ViewSection est creee :
#        - type de vue    : ABI_Coupe
#        - gabarit        : ABI_Coupe_STR+RES
#        - plan de coupe  : sur la face choisie (axe de trace + demi-ep)
#        - depth_min      : -5 cm (cote curseur)
#        - depth_max      : +ep + 5 cm (au-dela de la face opposee)
#        - marge V        : 50 cm haut/bas
#   5. Nommage ABI_Coupe_Mur_XXX (XXX = 001, 002, ...)
#
# Constantes (modifiables) :
#   SECTION_OFFSET_FT  5 cm  retrait devant la face (cote curseur)
#   DEPTH_BEYOND_FT    5 cm  profondeur au-dela de la face opposee
#   CROP_OFFSET_V_FT  50 cm  marge haut/bas
#   ANGLE_TOL_DEG      2.0   tolerance angulaire pour murs colineaires
#   SECTION_TYPE_NAME        nom du type de vue Section a utiliser
#   VIEW_TEMPLATE_NAME       nom du gabarit de vue a appliquer
# =============================================================================

import traceback
import re
import math
import System
import System.IO
import System.Text

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows          import Window, GridLength, GridUnitType, Thickness
from System.Windows.Controls import Grid, StackPanel, TextBlock, Button, Border, RowDefinition
from System.Windows.Media    import SolidColorBrush, Color
from System.Windows.Markup   import XamlReader

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, TransactionStatus,
    XYZ, Transform, BoundingBoxXYZ,
    ViewFamilyType, ViewFamily, ViewSection,
    RevitLinkInstance, Wall, View,
    BuiltInCategory, ElementId
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from pyrevit import revit, script, forms

# ---------------------------------------------------------------------------
# Contexte Revit
# ---------------------------------------------------------------------------
uidoc       = __revit__.ActiveUIDocument
doc         = uidoc.Document
active_view = uidoc.ActiveView

# ---------------------------------------------------------------------------
# Constantes geometriques  (pieds — 1 m = 3.28084 ft)
# ---------------------------------------------------------------------------
M2FT               = 3.28084
SECTION_OFFSET_FT  = 0.05 * M2FT   # 5 cm retrait cote curseur
DEPTH_BEYOND_FT    = 0.05 * M2FT   # 5 cm au-dela face opposee
CROP_OFFSET_H_FT   = 0.50 * M2FT   # 50 cm marge gauche/droite au-dela des extremites
CROP_OFFSET_V_FT   = 0.50 * M2FT   # 50 cm marge haut/bas
ANGLE_TOL_DEG      = 2.0
ANGLE_TOL_RAD      = ANGLE_TOL_DEG * math.pi / 180.0
SECTION_TYPE_NAME  = u"ABI_Coupe"          # type de vue Section a utiliser
VIEW_TEMPLATE_NAME = u"ABI_Coupe_STR+RES"  # gabarit de vue a appliquer

# ---------------------------------------------------------------------------
# Filtre selection : liens Revit
# ---------------------------------------------------------------------------
class LinkedElementFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)
    def AllowReference(self, ref, point):
        return True

# ---------------------------------------------------------------------------
# Geometrie
# ---------------------------------------------------------------------------

def get_wall_endpoints(wall, transform):
    """
    Retourne (p0, p1, direction) du mur dans le repere hote.
    p0, p1 : extremites de la courbe de trace transformees.
    direction : vecteur unitaire p0->p1 dans le plan XY.
    """
    loc = wall.Location
    if loc is None:
        return None
    try:
        curve = loc.Curve
    except Exception:
        return None
    p0 = transform.OfPoint(curve.GetEndPoint(0))
    p1 = transform.OfPoint(curve.GetEndPoint(1))
    d  = p1 - p0
    if d.GetLength() < 1e-6:
        return None
    return p0, p1, d.Normalize()


def walls_are_collinear(dir_ref, p0_ref, dir_cand, p0_cand, p1_cand, angle_tol):
    """
    Verifie que le mur candidat est colineaire au mur de reference.
    Criteres :
      1. Directions paralleles (angle < angle_tol, modulo 180 deg)
      2. p0_cand et p1_cand se projettent sur l'axe du mur de reference
         a une distance transversale < 2 * epaisseur max (on utilise 50 cm)
    """
    # 1 — parallelisme
    cross = dir_ref.CrossProduct(dir_cand)
    sin_a = cross.GetLength()   # |sin(angle)|
    if sin_a > math.sin(angle_tol):
        return False

    # 2 — coaxialite : distance de p0_cand a la droite portee par p0_ref/dir_ref
    v = p0_cand - p0_ref
    # Composante transversale (perpendiculaire a dir_ref dans le plan XY)
    dot_long = v.X * dir_ref.X + v.Y * dir_ref.Y
    proj     = XYZ(dir_ref.X * dot_long, dir_ref.Y * dot_long, 0.0)
    transv   = XYZ(v.X - proj.X, v.Y - proj.Y, 0.0)
    dist_t   = transv.GetLength()

    # Tolerance transversale : 10 cm (on veut les murs dans le meme axe)
    MAX_TRANSV_FT = 0.10 * M2FT
    if dist_t > MAX_TRANSV_FT:
        return False

    return True


def project_on_axis(point, origin, direction):
    """
    Retourne la coordonnee scalaire de la projection de 'point'
    sur l'axe defini par (origin, direction).
    """
    v = point - origin
    return v.X * direction.X + v.Y * direction.Y


def find_collinear_chain(ref_wall, ref_transform, link_doc, angle_tol):
    """
    Trouve tous les murs colineaires au mur de reference ET en contact
    ou gap < GAP_MAX_FT sur l'axe longitudinal (propagation en chaine).

    Algorithme :
      1. Collecte tous les murs colineaires du lien (angle + coaxialite)
      2. Projette leurs extremites sur l'axe dir_ref => segments scalaires
      3. Propagation depuis le mur de reference (BFS/flood-fill) :
         - a chaque iteration, etend la chaine si un segment non-visite
           est a moins de GAP_MAX_FT du bord courant (gauche ou droite)
      4. Retourne la liste des segments valides

    Retourne : (dir_ref, origin, [(p0,p1), ...]) ou None en cas d'erreur.
    """
    GAP_MAX_FT  = 0.10 * M2FT   # 10 cm gap max entre deux murs
    FACE_TOL_FT = 0.02 * M2FT   # 2 cm tolerance coaxialite (plan de face)

    ref_pts = get_wall_endpoints(ref_wall, ref_transform)
    if ref_pts is None:
        return None
    p0_ref, p1_ref, dir_ref = ref_pts

    # --- Etape 1 : collecter tous les murs colineaires (angle + plan de face) ---
    all_walls = FilteredElementCollector(link_doc)\
                    .OfCategory(BuiltInCategory.OST_Walls)\
                    .WhereElementIsNotElementType()\
                    .ToElements()

    # Chaque candidat = (s_min, s_max) sur l'axe dir_ref depuis p0_ref
    # s_min < s_max par construction
    candidates = []   # liste de (s_min, s_max, p0_world, p1_world)

    for w in all_walls:
        if not isinstance(w, Wall):
            continue
        pts = get_wall_endpoints(w, ref_transform)
        if pts is None:
            continue
        p0c, p1c, dirc = pts

        # Test colineaire (angle + distance transversale)
        if not walls_are_collinear(dir_ref, p0_ref, dirc, p0c, p1c, angle_tol):
            continue

        # Test coaxialite stricte sur le plan de face :
        # distance transversale de p0c par rapport a l'axe p0_ref/dir_ref
        v     = XYZ(p0c.X - p0_ref.X, p0c.Y - p0_ref.Y, 0.0)
        d_lon = v.X * dir_ref.X + v.Y * dir_ref.Y
        proj  = XYZ(dir_ref.X * d_lon, dir_ref.Y * d_lon, 0.0)
        transv_len = XYZ(v.X - proj.X, v.Y - proj.Y, 0.0).GetLength()
        if transv_len > FACE_TOL_FT:
            continue

        sa = project_on_axis(p0c, p0_ref, dir_ref)
        sb = project_on_axis(p1c, p0_ref, dir_ref)
        s_lo = min(sa, sb)
        s_hi = max(sa, sb)
        candidates.append((s_lo, s_hi))

    # Ajouter le mur de reference lui-meme
    s_ref_a = project_on_axis(p0_ref, p0_ref, dir_ref)   # = 0.0
    s_ref_b = project_on_axis(p1_ref, p0_ref, dir_ref)
    s_ref_lo = min(s_ref_a, s_ref_b)
    s_ref_hi = max(s_ref_a, s_ref_b)
    candidates.append((s_ref_lo, s_ref_hi))

    # --- Etape 2 : propagation en chaine depuis le mur de reference ---
    # Chaine courante definie par [chain_lo, chain_hi]
    chain_lo = s_ref_lo
    chain_hi = s_ref_hi

    visited = set()
    visited.add(len(candidates) - 1)   # index du mur de reference

    changed = True
    while changed:
        changed = False
        for i, (s_lo, s_hi) in enumerate(candidates):
            if i in visited:
                continue
            # Contact a gauche : s_hi du candidat proche de chain_lo
            # Contact a droite : s_lo du candidat proche de chain_hi
            touches_left  = (chain_lo - s_hi) <= GAP_MAX_FT and s_hi <= chain_lo + GAP_MAX_FT
            touches_right = (s_lo - chain_hi) <= GAP_MAX_FT and s_lo >= chain_hi - GAP_MAX_FT
            # Ou chevauchement (s_lo < chain_hi et s_hi > chain_lo)
            overlaps = s_lo < chain_hi + GAP_MAX_FT and s_hi > chain_lo - GAP_MAX_FT

            if touches_left or touches_right or overlaps:
                visited.add(i)
                if s_lo < chain_lo:
                    chain_lo = s_lo
                if s_hi > chain_hi:
                    chain_hi = s_hi
                changed = True

    # --- Etape 3 : reconstruire les points world pour les segments retenus ---
    retained_segments = []
    for i in visited:
        s_lo, s_hi = candidates[i]
        p0_world = XYZ(
            p0_ref.X + dir_ref.X * s_lo,
            p0_ref.Y + dir_ref.Y * s_lo,
            p0_ref.Z
        )
        p1_world = XYZ(
            p0_ref.X + dir_ref.X * s_hi,
            p0_ref.Y + dir_ref.Y * s_hi,
            p0_ref.Z
        )
        retained_segments.append((p0_world, p1_world))

    return dir_ref, p0_ref, retained_segments


def compute_chain_extent(dir_ref, origin, segments):
    """
    Calcule les coordonnees scalaires min et max sur l'axe dir_ref
    pour tous les segments (p0, p1) de la chaine.
    Retourne (s_min, s_max) en pieds.
    """
    all_scalars = []
    for p0, p1 in segments:
        all_scalars.append(project_on_axis(p0, origin, dir_ref))
        all_scalars.append(project_on_axis(p1, origin, dir_ref))
    return min(all_scalars), max(all_scalars)


def transform_bbox_to_host(wall, transform):
    """Bounding box du mur dans le repere hote."""
    bb = wall.get_BoundingBox(None)
    if bb is None:
        return None
    corners = [
        XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
    ]
    hc = [transform.OfPoint(c) for c in corners]
    result = BoundingBoxXYZ()
    result.Min = XYZ(min(c.X for c in hc), min(c.Y for c in hc), min(c.Z for c in hc))
    result.Max = XYZ(max(c.X for c in hc), max(c.Y for c in hc), max(c.Z for c in hc))
    return result


def get_section_view_type(document, type_name):
    """
    Retourne le ViewFamilyType Section dont le nom correspond a type_name.
    Si non trouve, retourne le premier type Section disponible.
    """
    first_section = None
    for vft in FilteredElementCollector(document).OfClass(ViewFamilyType):
        try:
            if vft.ViewFamily != ViewFamily.Section:
                continue
            if first_section is None:
                first_section = vft
            if vft.Name == type_name:
                return vft
        except Exception:
            continue
    return first_section   # fallback


def get_view_template_id(document, template_name):
    """
    Retourne l'ElementId du gabarit de vue dont le nom correspond a template_name.
    Retourne ElementId.InvalidElementId si non trouve.
    """
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            if v.IsTemplate and v.Name == template_name:
                return v.Id
        except Exception:
            pass
    return ElementId.InvalidElementId


def next_abi_coupe_mur_name(document):
    """
    Retourne le prochain nom ABI_Coupe_Mur_XXX disponible.
    XXX est sur 3 chiffres, incremente depuis le max existant.
    Ex : ABI_Coupe_Mur_001, ABI_Coupe_Mur_002, ...
    """
    pattern   = re.compile(r'^ABI_Coupe_Mur_(\d+)$')
    max_index = 0
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            m = pattern.match(v.Name)
            if m:
                idx = int(m.group(1))
                if idx > max_index:
                    max_index = idx
        except Exception:
            pass
    return u"ABI_Coupe_Mur_{:03d}".format(max_index + 1)

# ---------------------------------------------------------------------------
# Fenetre WPF de confirmation
# ---------------------------------------------------------------------------

XAML_CONFIRM = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Width="460" Height="270"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize"
    Background="White">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Margin="16,16,16,8" VerticalAlignment="Center">
      <TextBlock x:Name="lbl_titre"
                 FontSize="14" FontWeight="SemiBold" Foreground="#2C3E50"
                 TextWrapping="Wrap" Margin="0,0,0,10"/>
      <TextBlock x:Name="lbl_info"
                 FontSize="12" Foreground="#555555"
                 TextWrapping="Wrap"/>
    </StackPanel>
    <Border Grid.Row="1" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer"
                   FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_ok"
                  Width="120" Height="28" Margin="0,0,6,0"
                  FontSize="12" FontWeight="SemiBold" Foreground="White"
                  Background="#2ECC71" BorderThickness="0" Cursor="Hand"/>
          <Button x:Name="btn_cancel"
                  Width="90" Height="28"
                  FontSize="12" FontWeight="SemiBold" Foreground="White"
                  Background="#E74C3C" BorderThickness="0" Cursor="Hand"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""


def show_confirm_window(info_text):
    stream = System.IO.MemoryStream(
        System.Text.Encoding.UTF8.GetBytes(XAML_CONFIRM))
    win = XamlReader.Load(stream)

    win.Title = TOOL_NAME
    win.FindName("lbl_titre").Text     = u"Creer la coupe ?"
    win.FindName("lbl_info").Text      = info_text
    win.FindName("lbl_footer").Text    = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    win.FindName("btn_ok").Content     = u"Creer la coupe"
    win.FindName("btn_cancel").Content = u"Annuler"

    result = [False]

    def on_ok(s, e):
        result[0] = True
        win.Close()

    def on_cancel(s, e):
        win.Close()

    win.FindName("btn_ok").Click     += on_ok
    win.FindName("btn_cancel").Click += on_cancel
    win.ShowDialog()
    return result[0]

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():

    # -------------------------------------------------------------- #
    # 1. Selection du mur dans un lien                                #
    # -------------------------------------------------------------- #
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            LinkedElementFilter(),
            u"Cliquez sur un mur dans un lien Revit"
        )
    except Exception:
        return

    # -------------------------------------------------------------- #
    # 2. Validation                                                   #
    # -------------------------------------------------------------- #
    link_instance = doc.GetElement(ref.ElementId)
    if not isinstance(link_instance, RevitLinkInstance):
        forms.alert(u"L'element selectionne n'est pas dans un lien Revit.", exitscript=True)
        return

    link_doc  = link_instance.GetLinkDocument()
    transform = link_instance.GetTotalTransform()
    wall      = link_doc.GetElement(ref.LinkedElementId)

    if not isinstance(wall, Wall):
        forms.alert(u"L'element selectionne n'est pas un mur.", exitscript=True)
        return

    # -------------------------------------------------------------- #
    # 3. Geometrie de base du mur de reference                        #
    # -------------------------------------------------------------- #
    ref_pts = get_wall_endpoints(wall, transform)
    if ref_pts is None:
        forms.alert(u"Impossible de lire la geometrie du mur.", exitscript=True)
        return
    p0_ref, p1_ref, dir_ref = ref_pts

    # Normale (+N = rotation +90 de dir_ref dans le plan XY)
    normal_ref = XYZ(-dir_ref.Y, dir_ref.X, 0.0)

    # Centre du mur de reference (pour detection de la face)
    center_ref = XYZ(
        (p0_ref.X + p1_ref.X) / 2.0,
        (p0_ref.Y + p1_ref.Y) / 2.0,
        (p0_ref.Z + p1_ref.Z) / 2.0
    )

    # Bounding box du mur de reference (Z min/max/hauteur)
    bbox_ref = transform_bbox_to_host(wall, transform)
    if bbox_ref is None:
        forms.alert(u"Impossible de calculer la boite englobante du mur.", exitscript=True)
        return

    wall_height    = bbox_ref.Max.Z - bbox_ref.Min.Z
    wall_z_min     = bbox_ref.Min.Z
    wall_thickness = wall.Width   # en pieds

    # -------------------------------------------------------------- #
    # 4. Detection automatique de la face via le point de clic        #
    # -------------------------------------------------------------- #
    click_pt  = ref.GlobalPoint
    vec_click = XYZ(click_pt.X - center_ref.X, click_pt.Y - center_ref.Y, 0.0)
    dot       = vec_click.X * normal_ref.X + vec_click.Y * normal_ref.Y
    sign      = 1.0 if dot >= 0.0 else -1.0
    normal_out = XYZ(normal_ref.X * sign, normal_ref.Y * sign, 0.0)

    # -------------------------------------------------------------- #
    # 5. Propagation : trouver tous les murs colineaires              #
    # -------------------------------------------------------------- #
    chain_result = find_collinear_chain(wall, transform, link_doc, ANGLE_TOL_RAD)
    if chain_result is None:
        forms.alert(u"Impossible de calculer la chaine de murs.", exitscript=True)
        return
    dir_chain, origin_chain, segments = chain_result

    # Etendue totale en coordonnees scalaires sur l'axe dir_chain
    s_min, s_max = compute_chain_extent(dir_chain, origin_chain, segments)
    chain_length = s_max - s_min

    nb_collinear = len(segments) - 1   # sans le mur de reference

    # -------------------------------------------------------------- #
    # 6. Confirmation                                                  #
    # -------------------------------------------------------------- #
    wall_type_name = u""
    try:
        wt = link_doc.GetElement(wall.GetTypeId())
        if wt:
            wall_type_name = wt.Name
    except Exception:
        pass

    face_label = u"Face +N" if sign > 0 else u"Face -N"
    info_txt = (
        u"Mur : {}\n"
        u"Lien : {}\n"
        u"Face detectee : {}\n\n"
        u"Murs colineaires trouves : {}\n"
        u"Longueur totale de la coupe : {:.2f} m\n\n"
        u"Decalage coupe : 5 cm | Profondeur : ep. + 5 cm"
    ).format(
        wall_type_name,
        link_instance.Name,
        face_label,
        nb_collinear,
        chain_length / M2FT
    )

    if not show_confirm_window(info_txt):
        return

    # -------------------------------------------------------------- #
    # 7. Type de vue Section                                          #
    # -------------------------------------------------------------- #
    section_type = get_section_view_type(doc, SECTION_TYPE_NAME)
    if section_type is None:
        forms.alert(u"Aucun type de vue Section trouve dans le projet.", exitscript=True)
        return

    # Gabarit de vue
    template_id = get_view_template_id(doc, VIEW_TEMPLATE_NAME)
    if template_id.IntegerValue == -1:
        forms.alert(
            u"Gabarit de vue '{}' introuvable.\nLa vue sera creee sans gabarit.".format(
                VIEW_TEMPLATE_NAME),
            title=u"STR BIM Tools — Avertissement"
        )

    # -------------------------------------------------------------- #
    # 8. Construction du Transform orthonormal                        #
    #                                                                  #
    # BasisX  = dir_chain  (axe horizontal, longueur de la chaine)   #
    # BasisY  = Z monde    (axe vertical)                             #
    # BasisZ  = dir de regard = OPPOSE a normal_out (vers le mur)     #
    # Origin  = point a s_min sur l'axe + offset lateral face + z_min#
    # -------------------------------------------------------------- #
    basis_x     = dir_chain.Normalize()
    basis_y_raw = XYZ.BasisZ

    cross_test = basis_x.CrossProduct(basis_y_raw)
    if cross_test.GetLength() < 1e-6:
        basis_y_raw = XYZ.BasisY

    basis_z_raw = basis_x.CrossProduct(basis_y_raw).Normalize()

    # basis_z doit pointer vers l'interieur du mur (OPPOSE a normal_out)
    dot_check = basis_z_raw.X * normal_out.X + basis_z_raw.Y * normal_out.Y
    if dot_check > 0.0:
        basis_z = XYZ(-basis_z_raw.X, -basis_z_raw.Y, -basis_z_raw.Z)
        # Recalculer basis_x coherent avec le nouveau basis_z
        basis_x = basis_y_raw.CrossProduct(basis_z).Normalize()
    else:
        basis_z = basis_z_raw

    basis_y = basis_z.CrossProduct(basis_x).Normalize()

    # --- Origin ---
    # On recalcule le point world correspondant a s_min sur l'axe FINAL basis_x.
    # On re-projette toutes les extremites sur basis_x (qui a pu etre inverse)
    # pour obtenir les scalaires coherents avec le repere de la vue.
    all_scalars_final = []
    for seg_p0, seg_p1 in segments:
        all_scalars_final.append(project_on_axis(seg_p0, origin_chain, basis_x))
        all_scalars_final.append(project_on_axis(seg_p1, origin_chain, basis_x))
    s_min_final = min(all_scalars_final)
    s_max_final = max(all_scalars_final)
    chain_length_final = s_max_final - s_min_final

    # Point world au debut de la chaine (s_min) sur basis_x
    pt_start = XYZ(
        origin_chain.X + basis_x.X * s_min_final,
        origin_chain.Y + basis_x.Y * s_min_final,
        0.0
    )

    # --- Calcul de l'origin ---
    # On positionne l'origin exactement sur la face exterieure du mur
    # (axe de trace + demi-epaisseur dans la direction normal_out).
    # Le plan de coupe se trouve SUR la face — la CropBox gere le retrait
    # de 5 cm cote curseur (Min.Z negatif).
    #
    #   axe trace
    #      |
    #      |<-- demi-ep -->| face ext. = origin (plan de coupe)
    #                       |<-- -5 cm --|--- ep + 5 cm -->|
    #                       Min.Z        0                 Max.Z
    #
    half_thickness = wall_thickness / 2.0
    origin = XYZ(
        pt_start.X + normal_out.X * half_thickness,
        pt_start.Y + normal_out.Y * half_thickness,
        wall_z_min
    )

    t_section        = Transform.CreateTranslation(XYZ.Zero)
    t_section.Origin = origin
    t_section.BasisX = basis_x
    t_section.BasisY = basis_y
    t_section.BasisZ = basis_z

    # CropBox en coordonnees locales de la vue
    # X : [-50cm, chaine + 50cm]  — marges gauche/droite au-dela des extremites
    # Y : [-50cm, hauteur + 50cm] — marges haut/bas
    # Z : [-5cm,  ep + 5cm]       — retrait curseur / profondeur mur
    depth_min = -SECTION_OFFSET_FT
    depth_max =  wall_thickness + DEPTH_BEYOND_FT

    crop           = BoundingBoxXYZ()
    crop.Transform = t_section
    crop.Min       = XYZ(-CROP_OFFSET_H_FT,                    -CROP_OFFSET_V_FT,               depth_min)
    crop.Max       = XYZ( chain_length_final + CROP_OFFSET_H_FT, wall_height + CROP_OFFSET_V_FT, depth_max)

    # -------------------------------------------------------------- #
    # 9. Creation de la ViewSection                                   #
    # -------------------------------------------------------------- #

    # Calculer le nom AVANT d'ouvrir la transaction (evite les conflits
    # de lecture de vues pendant une transaction ouverte)
    final_name = next_abi_coupe_mur_name(doc)

    t = Transaction(doc, u"STR - Coupe sur mur lie")
    t.Start()
    try:
        section_view = ViewSection.CreateSection(doc, section_type.Id, crop)

        section_view.Name = final_name

        # Forcer le type de vue ABI_Coupe (ChangeTypeId est la seule methode
        # fiable — CreateSection n'applique pas toujours le bon type)
        section_view.ChangeTypeId(section_type.Id)

        # Application du gabarit de vue
        if template_id.IntegerValue != -1:
            section_view.ViewTemplateId = template_id

        t.Commit()

        uidoc.ActiveView = section_view
        try:
            type_name_str = section_type.Name
        except Exception:
            type_name_str = u"(inconnu)"
        forms.alert(
            u"Coupe creee avec succes !\n\nNom : {}\nType : {}\nGabarit : {}\nLongueur : {:.2f} m ({} mur(s))".format(
                final_name,
                type_name_str,
                VIEW_TEMPLATE_NAME if template_id.IntegerValue != -1 else u"(aucun)",
                chain_length_final / M2FT,
                len(segments)
            ),
            title=u"STR BIM Tools"
        )

    except Exception:
        try:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
        except Exception:
            pass
        forms.alert(
            u"Erreur lors de la creation de la coupe :\n\n{}".format(
                traceback.format_exc()),
            title=u"Erreur — STR BIM Tools"
        )

# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------
main()