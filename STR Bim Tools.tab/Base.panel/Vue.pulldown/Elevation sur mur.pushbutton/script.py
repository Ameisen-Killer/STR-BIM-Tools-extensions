# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Elevation sur mur"
# =============================================================================
# Cree une vraie vue d'elevation Revit sur un mur du modele courant, cadree
# automatiquement en fonction des elements structurels qui le touchent.
#
# L'elevation est portee par un repere d'elevation (ElevationMarker) pose dans
# une vue en plan, comme une elevation creee a la main : elle se classe donc
# sous "Elevations" dans l'arborescence. L'orientation n'etant pas pilotable a
# la creation (l'index de CreateElevation donne une direction cardinale), le
# repere est cree puis tourne pour aligner le regard sur la face choisie, ce
# qui fonctionne aussi sur un mur en biais.
#
# Workflow :
#   1. Mur presetectionne (avant lancement) OU clic sur un mur
#      - presetection  : la face de regard est choisie dans la fenetre
#      - clic direct   : la face est deduite de la position du curseur
#   2. Analyse des voisins en contact (dalles, radiers, murs, poteaux)
#   3. Calcul du cadrage :
#        - haut / bas      : 50 cm au-dela de la dalle en pied et en tete
#        - gauche / droite : 50 cm au-dela du mur en continuite / du poteau
#        - sans voisin     : 50 cm au-dela du mur lui-meme
#        - chaque extension est bridee (voir CLAMP_H_FT / CLAMP_V_FT) pour
#          qu'une dalle de 20 m ne fasse pas exploser le cadre
#   4. Profondeur de vue :
#        - plan de vue   : 10 cm devant la face selectionnee
#        - fond de vue   : 10 cm au-dela de la face opposee
#   5. Gabarit de vue choisi dans la fenetre (memorise dans prefs.json).
#      Sans gabarit, la vue est creee en 1:50, niveau de detail Eleve,
#      affichage en ligne cachee.
#   6. Nommage STR_Elevation_Mur_XXX (XXX = 001, 002, ...)
#
# Constantes principales (modifiables juste en dessous des imports) :
#   MARGE_CADRE_FT     50 cm  marge autour des elements voisins
#   ELEV_OFFSET_FT     10 cm  retrait du plan de vue devant la face choisie
#   DEPTH_BEYOND_FT    10 cm  profondeur au-dela de la face opposee
#   CLAMP_H_FT        200 cm  extension horizontale max due a un voisin
#   CLAMP_V_FT        100 cm  extension verticale max due a un voisin
#   TOL_CONTACT_FT      5 cm  tolerance de detection du contact
#   ELEVATION_TYPE_NAME       nom du type de vue Elevation a utiliser
#   DEFAUT_ECHELLE / DEFAUT_DETAIL / DEFAUT_STYLE   reglages hors gabarit
# =============================================================================

# Hors filet — strict minimum pour pouvoir afficher une erreur fatale
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


try:
    import math
    import re
    import os
    import io
    import json

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")

    import System
    import System.IO
    import System.Text
    import System.Windows.Markup

    from System.Windows import (
        MessageBox, MessageBoxButton, MessageBoxImage
    )
    from System.Windows.Controls import ComboBoxItem

    from Autodesk.Revit.DB import (
        FilteredElementCollector, Transaction, TransactionStatus,
        XYZ, BoundingBoxXYZ, Outline, BoundingBoxIntersectsFilter,
        ViewFamilyType, ViewFamily, View, ViewPlan, ViewType,
        ElevationMarker, ElementTransformUtils,
        ViewDetailLevel, DisplayStyle, Element,
        Wall, Line, BuiltInCategory, BuiltInParameter, ElementId
    )
    from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

    # -----------------------------------------------------------------------
    # Contexte Revit
    # -----------------------------------------------------------------------
    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # -----------------------------------------------------------------------
    # Constantes geometriques (pieds — 1 m = 3.28084 ft)
    # -----------------------------------------------------------------------
    M2FT             = 3.28084

    MARGE_CADRE_FT   = 0.50 * M2FT   # 50 cm autour des voisins / du mur
    ELEV_OFFSET_FT   = 0.10 * M2FT   # 10 cm devant la face selectionnee
    DEPTH_BEYOND_FT  = 0.10 * M2FT   # 10 cm au-dela de la face opposee

    CLAMP_H_FT       = 2.00 * M2FT   # extension H max due a un voisin
    CLAMP_V_FT       = 1.00 * M2FT   # extension V max due a un voisin
    TOL_CONTACT_FT   = 0.05 * M2FT   # 5 cm : tolerance de contact

    # Type de vue de la famille Elevation (pas Section : l'outil cree une
    # vraie vue d'elevation, portee par un repere dans une vue en plan).
    ELEVATION_TYPE_NAME = u"STR_Elevation"
    ELEVATION_TYPE_ALT  = u"STR_Elevation interieure"
    VIEW_NAME_PREFIX    = u"STR_Elevation_Mur_"

    # Reglages appliques quand AUCUN gabarit de vue n'est choisi.
    # Avec un gabarit, c'est lui qui pilote ces trois proprietes.
    DEFAUT_ECHELLE = 50                          # 1:50
    DEFAUT_DETAIL  = ViewDetailLevel.Fine        # niveau de detail : Eleve
    DEFAUT_STYLE   = DisplayStyle.HLR            # affichage : ligne cachee

    _PREFS_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    # Categories analysees comme voisins
    CATS_DALLES = [
        BuiltInCategory.OST_Floors,
        BuiltInCategory.OST_StructuralFoundation,
    ]
    CATS_VERTICAUX = [
        BuiltInCategory.OST_Walls,
        BuiltInCategory.OST_StructuralColumns,
        BuiltInCategory.OST_Columns,
    ]

    # =======================================================================
    # HELPERS GENERIQUES
    # =======================================================================

    def ft_to_m(v):
        return v / M2FT

    def load_xaml(xaml_str):
        stream = System.IO.MemoryStream(
            System.Text.Encoding.UTF8.GetBytes(xaml_str))
        return System.Windows.Markup.XamlReader.Load(stream)

    def elem_name(e):
        """
        Nom d'un element, robuste aux types ou la propriete .Name est
        ambigue sous IronPython (ViewFamilyType, WallType... : l'acces
        direct a .Name y leve AttributeError).
        """
        if e is None:
            return u""
        try:
            return Element.Name.GetValue(e)
        except Exception:
            pass
        for bip in (BuiltInParameter.SYMBOL_NAME_PARAM,
                    BuiltInParameter.ALL_MODEL_TYPE_NAME):
            try:
                p = e.get_Parameter(bip)
                if p is not None:
                    s = p.AsString()
                    if s:
                        return s
            except Exception:
                pass
        try:
            return e.Name
        except Exception:
            return u"?"

    def load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_prefs(data):
        try:
            txt = json.dumps(data, ensure_ascii=False)
            if isinstance(txt, bytes):        # IronPython 2.7 : json rend un str
                txt = txt.decode("utf-8")
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                f.write(txt)
        except Exception:
            pass

    def cardinal_label(vec):
        """Orientation cardinale (repere projet) d'un vecteur du plan XY."""
        ang = math.degrees(math.atan2(vec.Y, vec.X)) % 360.0
        secteurs = [
            (22.5,  u"Est"),        (67.5,  u"Nord-Est"),
            (112.5, u"Nord"),       (157.5, u"Nord-Ouest"),
            (202.5, u"Ouest"),      (247.5, u"Sud-Ouest"),
            (292.5, u"Sud"),        (337.5, u"Sud-Est"),
        ]
        for limite, nom in secteurs:
            if ang < limite:
                return nom
        return u"Est"

    def category_label(elem):
        try:
            return elem.Category.Name
        except Exception:
            return u"(sans categorie)"

    def elem_label(elem):
        """Type + Id, lisible dans le tableau des voisins."""
        nom = u"?"
        try:
            et = doc.GetElement(elem.GetTypeId())
            nom = elem_name(et) if et is not None else elem_name(elem)
        except Exception:
            pass
        return u"{}  [{}]".format(nom or u"?", elem.Id.IntegerValue)

    # =======================================================================
    # GEOMETRIE DU MUR
    # =======================================================================

    def get_wall_axis(wall):
        """
        Retourne (p0, p1, direction) de l'axe de trace du mur.
        Retourne None si le mur n'a pas de courbe exploitable ou est courbe.
        """
        loc = wall.Location
        if loc is None:
            return None
        try:
            curve = loc.Curve
        except Exception:
            return None
        if not isinstance(curve, Line):
            return None            # mur courbe : non gere en v1
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        d  = p1 - p0
        if d.GetLength() < 1e-6:
            return None
        return p0, p1, XYZ(d.X, d.Y, 0.0).Normalize()

    def get_wall_thickness(wall):
        """Epaisseur du mur en pieds, avec repli sur le parametre de type."""
        try:
            w = wall.Width
            if w and w > 1e-6:
                return w
        except Exception:
            pass
        try:
            et = doc.GetElement(wall.GetTypeId())
            p  = et.get_Parameter(BuiltInParameter.WALL_ATTR_WIDTH_PARAM)
            if p is not None:
                return p.AsDouble()
        except Exception:
            pass
        return 0.20 * M2FT         # repli : 20 cm

    def get_wall_z_range(wall):
        """
        (z_bas, z_haut) du mur en pieds, via les contraintes de niveau
        (cf. regle projet : ne pas se fier a la bounding box, qui inclut
        les jonctions et les elements attaches).
        """
        z_bas = None
        z_haut = None
        try:
            p_base = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
            p_boff = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
            if p_base is not None and p_base.AsElementId().IntegerValue != -1:
                lvl = doc.GetElement(p_base.AsElementId())
                if lvl is not None:
                    z_bas = lvl.Elevation + (p_boff.AsDouble() if p_boff else 0.0)
        except Exception:
            pass

        try:
            p_top = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
            p_toff = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
            if p_top is not None and p_top.AsElementId().IntegerValue != -1:
                lvl = doc.GetElement(p_top.AsElementId())
                if lvl is not None:
                    z_haut = lvl.Elevation + (p_toff.AsDouble() if p_toff else 0.0)
        except Exception:
            pass

        if z_haut is None and z_bas is not None:
            try:
                p_h = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
                if p_h is not None:
                    z_haut = z_bas + p_h.AsDouble()
            except Exception:
                pass

        if z_bas is None or z_haut is None:
            bb = wall.get_BoundingBox(None)
            if bb is None:
                return None
            if z_bas is None:
                z_bas = bb.Min.Z
            if z_haut is None:
                z_haut = bb.Max.Z

        if z_haut < z_bas:
            z_bas, z_haut = z_haut, z_bas
        return z_bas, z_haut

    def bbox_corners(bb):
        return [
            XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
            XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
            XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
            XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z), XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
        ]

    def project_on_axis(point, origin, direction):
        """Abscisse de la projection de 'point' sur l'axe (origin, direction)."""
        v = point - origin
        return v.X * direction.X + v.Y * direction.Y

    # =======================================================================
    # DETECTION DES VOISINS
    # =======================================================================

    def collect_neighbours(wall):
        """
        Elements du modele courant dont la bounding box touche (a
        TOL_CONTACT_FT pres) celle du mur, dans les categories analysees.
        Retourne une liste d'elements, le mur lui-meme exclu.
        """
        bb = wall.get_BoundingBox(None)
        if bb is None:
            return []
        t = TOL_CONTACT_FT
        outline = Outline(
            XYZ(bb.Min.X - t, bb.Min.Y - t, bb.Min.Z - t),
            XYZ(bb.Max.X + t, bb.Max.Y + t, bb.Max.Z + t))
        bb_filter = BoundingBoxIntersectsFilter(outline)

        voisins = []
        for bic in CATS_DALLES + CATS_VERTICAUX:
            try:
                found = FilteredElementCollector(doc) \
                            .OfCategory(bic) \
                            .WhereElementIsNotElementType() \
                            .WherePasses(bb_filter) \
                            .ToElements()
            except Exception:
                continue
            for e in found:
                if e.Id == wall.Id:
                    continue
                voisins.append(e)
        return voisins

    def is_dalle(elem):
        try:
            bic_id = elem.Category.Id.IntegerValue
        except Exception:
            return False
        for bic in CATS_DALLES:
            if bic_id == ElementId(bic).IntegerValue:
                return True
        return False

    def analyse_neighbours(voisins, axis_dir, axis_origin,
                           s_min_wall, s_max_wall, z_bas_wall, z_haut_wall):
        """
        Repartit l'influence de chaque voisin sur le cadrage.

        Regle metier :
          - une dalle / un radier ne contraint que le cadrage VERTICAL
            (dalle en pied -> borne basse, dalle en tete -> borne haute) ;
          - un mur ou un poteau ne contraint que le cadrage HORIZONTAL,
            et seulement s'il depasse une extremite du mur analyse.

        Chaque extension est bridee par CLAMP_H_FT / CLAMP_V_FT pour qu'un
        element tres etendu (grande dalle, long mur en continuite) ne fasse
        pas exploser le cadre.

        Retourne (ext_gauche, ext_droite, ext_bas, ext_haut, lignes_rapport)
        toutes exprimees en pieds, marge MARGE_CADRE_FT deja incluse.
        """
        ext_g = ext_d = ext_b = ext_h = 0.0
        rapport = []

        for e in voisins:
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            coins = bbox_corners(bb)

            if is_dalle(e):
                z_lo = min(c.Z for c in coins)
                z_hi = max(c.Z for c in coins)
                # Dalle en pied : elle descend sous la base du mur
                d_bas  = max(0.0, z_bas_wall - z_lo)
                # Dalle en tete : elle monte au-dessus du sommet du mur
                d_haut = max(0.0, z_hi - z_haut_wall)
                d_bas  = min(d_bas,  CLAMP_V_FT)
                d_haut = min(d_haut, CLAMP_V_FT)
                influences = []
                if d_bas > 1e-6:
                    ext_b = max(ext_b, d_bas)
                    influences.append(u"bas {:.2f} m".format(ft_to_m(d_bas)))
                if d_haut > 1e-6:
                    ext_h = max(ext_h, d_haut)
                    influences.append(u"haut {:.2f} m".format(ft_to_m(d_haut)))
                infl_txt = u" + ".join(influences) if influences else u"aucune"
            else:
                s_vals = [project_on_axis(c, axis_origin, axis_dir) for c in coins]
                s_lo = min(s_vals)
                s_hi = max(s_vals)
                d_g = max(0.0, s_min_wall - s_lo)
                d_d = max(0.0, s_hi - s_max_wall)
                d_g = min(d_g, CLAMP_H_FT)
                d_d = min(d_d, CLAMP_H_FT)
                influences = []
                if d_g > 1e-6:
                    ext_g = max(ext_g, d_g)
                    influences.append(u"gauche {:.2f} m".format(ft_to_m(d_g)))
                if d_d > 1e-6:
                    ext_d = max(ext_d, d_d)
                    influences.append(u"droite {:.2f} m".format(ft_to_m(d_d)))
                infl_txt = u" + ".join(influences) if influences else u"aucune"

            rapport.append((category_label(e), elem_label(e), infl_txt))

        # La marge de 50 cm s'ajoute a la distance au voisin le plus eloigne ;
        # sans voisin dans une direction, elle s'applique au mur lui-meme.
        return (ext_g + MARGE_CADRE_FT,
                ext_d + MARGE_CADRE_FT,
                ext_b + MARGE_CADRE_FT,
                ext_h + MARGE_CADRE_FT,
                rapport)

    # =======================================================================
    # TYPE DE VUE / GABARIT / NOMMAGE
    # =======================================================================

    def get_elevation_view_type(document):
        """
        ViewFamilyType d'elevation : nom prioritaire, puis alternatif, puis
        le premier trouve. Une vraie vue Elevation exige un type de la
        famille Elevation — un type Section ne convient pas ici.
        """
        premier = None
        par_nom = {}
        for vft in FilteredElementCollector(document).OfClass(ViewFamilyType):
            try:
                if vft.ViewFamily != ViewFamily.Elevation:
                    continue
            except Exception:
                continue
            if premier is None:
                premier = vft
            nom = elem_name(vft)
            if nom:
                par_nom[nom] = vft
        if ELEVATION_TYPE_NAME in par_nom:
            return par_nom[ELEVATION_TYPE_NAME]
        if ELEVATION_TYPE_ALT in par_nom:
            return par_nom[ELEVATION_TYPE_ALT]
        return premier

    def get_owner_plan_view(document, z_ref):
        """
        Vue en plan qui portera le repere d'elevation.

        CreateElevation exige une vue en plan hote. On privilegie, dans
        l'ordre : la vue active si c'est un plan, une vue non recadree du
        niveau le plus proche de z_ref, puis n'importe quelle vue en plan.
        Une vue recadree risquerait d'exclure le repere de sa zone de
        cadrage.
        """
        try:
            active = uidoc.ActiveView
            if isinstance(active, ViewPlan) and not active.IsTemplate:
                return active
        except Exception:
            pass

        candidates = []
        for v in FilteredElementCollector(document).OfClass(ViewPlan):
            try:
                if v.IsTemplate:
                    continue
                if v.ViewType not in (ViewType.FloorPlan,
                                      ViewType.EngineeringPlan):
                    continue
                niveau = v.GenLevel
                if niveau is None:
                    continue
                recadree = False
                try:
                    recadree = bool(v.CropBoxActive)
                except Exception:
                    pass
                candidates.append(
                    (recadree, abs(niveau.Elevation - z_ref), v))
            except Exception:
                pass

        if not candidates:
            return None
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates[0][2]

    def list_view_templates(document):
        """
        Gabarits de vue applicables a une elevation, tries par nom.
        Retourne une liste de (nom, ElementId).

        Le filtre est strict : Revit refuse d'affecter a une elevation un
        gabarit d'un autre type de vue. Si le projet n'en contient aucun,
        la liste est vide et seul "(aucun gabarit)" reste proposable.
        """
        retenus = []
        for v in FilteredElementCollector(document).OfClass(View):
            try:
                if not v.IsTemplate:
                    continue
                if v.ViewType != ViewType.Elevation:
                    continue
                retenus.append((elem_name(v), v.Id))
            except Exception:
                pass
        retenus.sort(key=lambda x: x[0])
        return retenus

    def next_view_name(document):
        pattern = re.compile(u"^" + VIEW_NAME_PREFIX + u"(\\d+)$")
        maxi = 0
        for v in FilteredElementCollector(document).OfClass(View):
            try:
                m = pattern.match(elem_name(v))
                if m:
                    idx = int(m.group(1))
                    if idx > maxi:
                        maxi = idx
            except Exception:
                pass
        return u"{}{:03d}".format(VIEW_NAME_PREFIX, maxi + 1)

    def view_name_exists(document, name):
        for v in FilteredElementCollector(document).OfClass(View):
            try:
                if not v.IsTemplate and elem_name(v) == name:
                    return True
            except Exception:
                pass
        return False

    # =======================================================================
    # SELECTION
    # =======================================================================

    class WallFilter(ISelectionFilter):
        def AllowElement(self, elem):
            return isinstance(elem, Wall)
        def AllowReference(self, ref, point):
            return True

    def get_preselected_wall():
        """Retourne le mur presetectionne s'il y en a exactement un."""
        try:
            ids = list(uidoc.Selection.GetElementIds())
        except Exception:
            return None
        murs = []
        for eid in ids:
            e = doc.GetElement(eid)
            if isinstance(e, Wall):
                murs.append(e)
        if len(murs) == 1:
            return murs[0]
        return None

    def pick_wall():
        """Clic sur un mur. Retourne (mur, point_clic) ou (None, None)."""
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element, WallFilter(),
                u"Cliquez sur la face du mur depuis laquelle regarder")
        except Exception:
            return None, None
        el = doc.GetElement(ref.ElementId)
        if not isinstance(el, Wall):
            return None, None
        pt = None
        try:
            pt = ref.GlobalPoint
        except Exception:
            pt = None
        return el, pt

    # =======================================================================
    # FENETRE DE CONFIRMATION (XAML en ASCII strict)
    # =======================================================================

    XAML_CONFIRM = """<Window
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Width="720" Height="620" MinWidth="620" MinHeight="520"
        WindowStartupLocation="CenterScreen"
        Background="White" ResizeMode="CanResize">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- BARRE TITRE -->
        <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
          <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold"
                     Foreground="White"/>
        </Border>

        <!-- INFOS MUR -->
        <Border Grid.Row="1" Background="#FAFCFF" BorderBrush="#C0D0E0"
                BorderThickness="0,0,0,1" Padding="12,8">
          <TextBlock x:Name="lbl_mur" FontSize="12" Foreground="#2C3E50"
                     TextWrapping="Wrap"/>
        </Border>

        <!-- CHOIX DE FACE -->
        <Border Grid.Row="2" Background="#F0F6FF" BorderBrush="#C0D0E0"
                BorderThickness="0,0,0,1" Padding="12,8">
          <StackPanel Orientation="Vertical">
            <TextBlock x:Name="lbl_face_titre" FontSize="11"
                       FontWeight="SemiBold" Foreground="#2F6496"
                       Margin="0,0,0,5"/>
            <StackPanel Orientation="Horizontal">
              <RadioButton x:Name="rb_face_a" GroupName="face"
                           VerticalAlignment="Center" Margin="0,0,20,0"/>
              <RadioButton x:Name="rb_face_b" GroupName="face"
                           VerticalAlignment="Center"/>
            </StackPanel>
          </StackPanel>
        </Border>

        <!-- VOISINS -->
        <Grid Grid.Row="3" Margin="12,8,12,4">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row="0" x:Name="lbl_voisins_titre" FontSize="11"
                     FontWeight="SemiBold" Foreground="#2F6496"
                     Margin="0,0,0,4"/>
          <DataGrid Grid.Row="1" x:Name="dg_voisins"
                    AutoGenerateColumns="False" IsReadOnly="True"
                    AlternatingRowBackground="#E8F0FA" RowBackground="White"
                    GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
                    HeadersVisibility="Column" CanUserResizeColumns="True"
                    CanUserSortColumns="True" CanUserAddRows="False"
                    FontSize="11">
            <DataGrid.ColumnHeaderStyle>
              <Style TargetType="DataGridColumnHeader">
                <Setter Property="Background" Value="#D0E4F7"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
                <Setter Property="Padding" Value="6,3"/>
              </Style>
            </DataGrid.ColumnHeaderStyle>
            <DataGrid.Columns>
              <DataGridTextColumn x:Name="col_cat"
                                  Binding="{Binding Categorie}" Width="150"/>
              <DataGridTextColumn x:Name="col_elem"
                                  Binding="{Binding Element}" Width="*"/>
              <DataGridTextColumn x:Name="col_infl"
                                  Binding="{Binding Influence}" Width="200"/>
            </DataGrid.Columns>
          </DataGrid>
        </Grid>

        <!-- RESUME CADRE + GABARIT + NOM -->
        <Border Grid.Row="4" Background="#FAFCFF" BorderBrush="#C0D0E0"
                BorderThickness="0,1,0,1" Padding="12,8">
          <Grid>
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <TextBlock Grid.Row="0" Grid.ColumnSpan="2" x:Name="lbl_cadre"
                       FontSize="11" Foreground="#2C3E50" TextWrapping="Wrap"
                       Margin="0,0,0,6"/>
            <TextBlock Grid.Row="1" Grid.Column="0" x:Name="lbl_gabarit"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <ComboBox Grid.Row="1" Grid.Column="1" x:Name="cmb_gabarit"
                      Height="24" FontSize="12" VerticalContentAlignment="Center"/>
            <TextBlock Grid.Row="2" Grid.Column="1" x:Name="lbl_gabarit_info"
                       FontSize="10" Foreground="#7F8C8D" TextWrapping="Wrap"
                       Margin="0,3,0,6"/>
            <TextBlock Grid.Row="3" Grid.Column="0" x:Name="lbl_nom"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <TextBox Grid.Row="3" Grid.Column="1" x:Name="txt_nom"
                     Height="24" FontSize="12" VerticalContentAlignment="Center"/>
          </Grid>
        </Border>

        <!-- FOOTER -->
        <Border Grid.Row="5" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,4">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="8,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal"
                        Margin="0,0,8,0">
              <Button x:Name="btn_ok" Width="150" Height="28" Margin="0,0,6,0"
                      FontSize="12" FontWeight="SemiBold" Foreground="White"
                      Background="#2ECC71" BorderThickness="0" Cursor="Hand"/>
              <Button x:Name="btn_cancel" Width="90" Height="28"
                      FontSize="12" FontWeight="SemiBold" Foreground="White"
                      Background="#E74C3C" BorderThickness="0" Cursor="Hand"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    class VoisinRow(object):
        """Ligne du tableau des voisins — que des chaines deja calculees."""
        def __init__(self, cat, elem, influence):
            self.Categorie = cat
            self.Element   = elem
            self.Influence = influence

    def show_confirm_window(info_mur, label_face_a, label_face_b,
                            face_index_defaut, rows, info_cadre, nom_propose,
                            gabarits, gabarit_defaut):
        """
        Retourne (True, index_face, nom_vue, template_id) si l'utilisateur
        valide, (False, None, None, None) sinon.
          index_face  : 0 = face A, 1 = face B
          template_id : ElementId du gabarit, ou InvalidElementId si aucun
        """
        win = load_xaml(XAML_CONFIRM)

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text = u"{}  |  Revit {}".format(
            TOOL_NAME, app.VersionNumber)
        win.FindName("lbl_footer").Text       = _FOOTER
        win.FindName("lbl_mur").Text          = info_mur
        win.FindName("lbl_face_titre").Text   = u"Face depuis laquelle regarder"
        win.FindName("rb_face_a").Content     = label_face_a
        win.FindName("rb_face_b").Content     = label_face_b
        win.FindName("lbl_voisins_titre").Text = \
            u"Elements en contact analyses ({})".format(len(rows))
        win.FindName("lbl_cadre").Text        = info_cadre
        win.FindName("lbl_gabarit").Text      = u"Gabarit de vue :"
        win.FindName("lbl_nom").Text          = u"Nom de la vue :"
        win.FindName("txt_nom").Text          = nom_propose
        win.FindName("btn_ok").Content        = u"Creer l'elevation"
        win.FindName("btn_cancel").Content    = u"Annuler"

        win.FindName("col_cat").Header  = u"Categorie"
        win.FindName("col_elem").Header = u"Element"
        win.FindName("col_infl").Header = u"Influence sur le cadre"

        win.FindName("dg_voisins").ItemsSource = rows

        if face_index_defaut == 1:
            win.FindName("rb_face_b").IsChecked = True
        else:
            win.FindName("rb_face_a").IsChecked = True

        # --- Combo gabarits : "(aucun)" en premier, puis les gabarits ---
        cmb      = win.FindName("cmb_gabarit")
        lbl_info = win.FindName("lbl_gabarit_info")

        item_aucun     = ComboBoxItem()
        item_aucun.Content = u"(aucun gabarit)"
        item_aucun.Tag     = None
        cmb.Items.Add(item_aucun)

        index_defaut = 0
        for i, (nom_gab, gab_id) in enumerate(gabarits):
            it         = ComboBoxItem()
            it.Content = nom_gab
            it.Tag     = gab_id
            cmb.Items.Add(it)
            if gabarit_defaut and nom_gab == gabarit_defaut:
                index_defaut = i + 1

        txt_defauts = (
            u"Sans gabarit, la vue est creee en 1:{}, niveau de detail Eleve, "
            u"affichage en ligne cachee.".format(DEFAUT_ECHELLE)
        )

        def maj_info(s=None, e=None):
            sel = cmb.SelectedItem
            if sel is None or sel.Tag is None:
                lbl_info.Text = txt_defauts
            else:
                lbl_info.Text = (
                    u"Le gabarit pilote l'echelle, le niveau de detail et "
                    u"l'affichage de la vue.")

        cmb.SelectionChanged += maj_info
        cmb.SelectedIndex     = index_defaut
        maj_info()

        etat = {"ok": False}

        def on_ok(s, e):
            etat["ok"] = True
            win.Close()

        def on_cancel(s, e):
            win.Close()

        win.FindName("btn_ok").Click     += on_ok
        win.FindName("btn_cancel").Click += on_cancel
        win.ShowDialog()

        if not etat["ok"]:
            return False, None, None, None

        idx = 1 if win.FindName("rb_face_b").IsChecked else 0
        nom = (win.FindName("txt_nom").Text or u"").strip()

        sel = cmb.SelectedItem
        tpl_id  = sel.Tag if (sel is not None and sel.Tag is not None) \
                  else ElementId.InvalidElementId
        tpl_nom = sel.Content if (sel is not None and sel.Tag is not None) else u""
        return True, idx, nom, (tpl_id, tpl_nom)

    # =======================================================================
    # MAIN
    # =======================================================================

    def main():

        # ---------------------------------------------------------------- #
        # 1. Recuperation du mur                                            #
        # ---------------------------------------------------------------- #
        wall      = get_preselected_wall()
        click_pt  = None
        if wall is None:
            wall, click_pt = pick_wall()
            if wall is None:
                return          # annule par l'utilisateur

        # ---------------------------------------------------------------- #
        # 2. Geometrie de base                                              #
        # ---------------------------------------------------------------- #
        axe = get_wall_axis(wall)
        if axe is None:
            MessageBox.Show(
                u"Ce mur n'a pas d'axe rectiligne exploitable.\n"
                u"Les murs courbes et les murs-rideaux ne sont pas geres "
                u"par cette version.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        p0, p1, dir_wall = axe

        z_range = get_wall_z_range(wall)
        if z_range is None:
            MessageBox.Show(u"Impossible de determiner l'altitude du mur.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        z_bas, z_haut = z_range

        epaisseur = get_wall_thickness(wall)
        longueur  = (p1 - p0).GetLength()

        # Normale au mur (rotation +90 de dir_wall dans le plan XY)
        normal_ref = XYZ(-dir_wall.Y, dir_wall.X, 0.0)

        centre = XYZ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0, 0.0)

        # Face par defaut : deduite du clic si disponible, sinon face +N
        face_defaut = 0
        if click_pt is not None:
            v_clic = XYZ(click_pt.X - centre.X, click_pt.Y - centre.Y, 0.0)
            dot    = v_clic.X * normal_ref.X + v_clic.Y * normal_ref.Y
            face_defaut = 0 if dot >= 0.0 else 1

        normal_a = normal_ref
        normal_b = XYZ(-normal_ref.X, -normal_ref.Y, 0.0)
        label_a  = u"Face {}".format(cardinal_label(normal_a))
        label_b  = u"Face {}".format(cardinal_label(normal_b))

        # ---------------------------------------------------------------- #
        # 3. Analyse des voisins                                            #
        # ---------------------------------------------------------------- #
        voisins = collect_neighbours(wall)

        s_min_wall = project_on_axis(p0, p0, dir_wall)   # = 0.0
        s_max_wall = project_on_axis(p1, p0, dir_wall)
        if s_max_wall < s_min_wall:
            s_min_wall, s_max_wall = s_max_wall, s_min_wall

        ext_g, ext_d, ext_b, ext_h, rapport = analyse_neighbours(
            voisins, dir_wall, p0, s_min_wall, s_max_wall, z_bas, z_haut)

        rows = [VoisinRow(c, e, i) for (c, e, i) in rapport]
        rows.sort(key=lambda r: (r.Categorie, r.Element))

        # ---------------------------------------------------------------- #
        # 4. Confirmation                                                   #
        # ---------------------------------------------------------------- #
        type_mur = elem_name(doc.GetElement(wall.GetTypeId()))

        info_mur = (
            u"Mur : {}   [Id {}]\n"
            u"Longueur {:.2f} m   |   Epaisseur {:.0f} cm   |   "
            u"Hauteur {:.2f} m  (de {:+.2f} m a {:+.2f} m)"
        ).format(type_mur, wall.Id.IntegerValue,
                 ft_to_m(longueur), ft_to_m(epaisseur) * 100.0,
                 ft_to_m(z_haut - z_bas), ft_to_m(z_bas), ft_to_m(z_haut))

        larg_cadre = longueur + ext_g + ext_d
        haut_cadre = (z_haut - z_bas) + ext_b + ext_h
        info_cadre = (
            u"Cadre : {:.2f} m x {:.2f} m   "
            u"(marges  gauche {:.2f}  droite {:.2f}  bas {:.2f}  haut {:.2f}  m)\n"
            u"Profondeur : plan de vue a {:.0f} cm devant la face choisie, "
            u"fond a {:.0f} cm au-dela de la face opposee."
        ).format(ft_to_m(larg_cadre), ft_to_m(haut_cadre),
                 ft_to_m(ext_g), ft_to_m(ext_d), ft_to_m(ext_b), ft_to_m(ext_h),
                 ft_to_m(ELEV_OFFSET_FT) * 100.0,
                 ft_to_m(DEPTH_BEYOND_FT) * 100.0)

        nom_propose = next_view_name(doc)
        gabarits    = list_view_templates(doc)
        prefs       = load_prefs()

        ok, face_idx, nom_vue, gabarit = show_confirm_window(
            info_mur, label_a, label_b, face_defaut,
            rows, info_cadre, nom_propose,
            gabarits, prefs.get("dernier_gabarit", u""))
        if not ok:
            return

        template_id, template_nom = gabarit
        prefs["dernier_gabarit"] = template_nom
        save_prefs(prefs)

        if not nom_vue:
            nom_vue = nom_propose
        if view_name_exists(doc, nom_vue):
            MessageBox.Show(
                u"Une vue nommee '{}' existe deja.\n"
                u"Choisissez un autre nom.".format(nom_vue),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        normal_out = normal_a if face_idx == 0 else normal_b

        # ---------------------------------------------------------------- #
        # 5. Type de vue Elevation et vue plan hote                         #
        # ---------------------------------------------------------------- #
        elev_type = get_elevation_view_type(doc)
        if elev_type is None:
            MessageBox.Show(
                u"Aucun type de vue Elevation trouve dans le projet.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        plan_hote = get_owner_plan_view(doc, z_bas)
        if plan_hote is None:
            MessageBox.Show(
                u"Aucune vue en plan disponible pour porter le repere "
                u"d'elevation.\nUne vraie vue Elevation ne peut pas etre "
                u"creee sans vue en plan hote.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return

        # ---------------------------------------------------------------- #
        # 6. Geometrie cible, en coordonnees monde                          #
        #                                                                    #
        # Contrairement a une coupe, l'orientation d'une elevation n'est pas #
        # pilotee par une Transform : elle vient de l'orientation du repere  #
        # d'elevation. On prepare donc des points monde, qui seront projetes #
        # dans le repere de la vue une fois celle-ci creee et tournee.       #
        # ---------------------------------------------------------------- #
        demi_ep = epaisseur / 2.0

        # Extremites du cadre le long de l'axe du mur, extensions comprises.
        # ext_g = cote des abscisses decroissantes, ext_d = cote croissantes.
        s_lo = s_min_wall - ext_g
        s_hi = s_max_wall + ext_d
        pt_lo = XYZ(p0.X + dir_wall.X * s_lo, p0.Y + dir_wall.Y * s_lo, 0.0)
        pt_hi = XYZ(p0.X + dir_wall.X * s_hi, p0.Y + dir_wall.Y * s_hi, 0.0)

        z_cadre_bas  = z_bas  - ext_b
        z_cadre_haut = z_haut + ext_h

        coins_cadre = [
            XYZ(pt_lo.X, pt_lo.Y, z_cadre_bas),
            XYZ(pt_lo.X, pt_lo.Y, z_cadre_haut),
            XYZ(pt_hi.X, pt_hi.Y, z_cadre_bas),
            XYZ(pt_hi.X, pt_hi.Y, z_cadre_haut),
        ]

        # Repere d'elevation : sur l'axe du mur, decale de la demi-epaisseur
        # (face choisie) plus le retrait de 10 cm. Le plan de vue de
        # l'elevation passe par le centre du repere.
        s_centre = (s_min_wall + s_max_wall) / 2.0
        pt_centre = XYZ(p0.X + dir_wall.X * s_centre,
                        p0.Y + dir_wall.Y * s_centre, 0.0)
        recul = demi_ep + ELEV_OFFSET_FT
        marker_origin = XYZ(pt_centre.X + normal_out.X * recul,
                            pt_centre.Y + normal_out.Y * recul,
                            (z_bas + z_haut) / 2.0)

        # Profondeur totale depuis le plan de vue : 10 cm de retrait
        # + epaisseur du mur + 10 cm au-dela de la face opposee.
        far_offset = ELEV_OFFSET_FT + epaisseur + DEPTH_BEYOND_FT

        # ---------------------------------------------------------------- #
        # 7. Creation de l'elevation                                        #
        # ---------------------------------------------------------------- #
        reglages_ko = []
        t = Transaction(doc, u"STR - Elevation sur mur")
        t.Start()
        try:
            marker = ElevationMarker.CreateElevationMarker(
                doc, elev_type.Id, marker_origin, DEFAUT_ECHELLE)
            vue = marker.CreateElevation(doc, plan_hote.Id, 0)
            doc.Regenerate()

            # --- Orientation : aligner le regard sur la face choisie ---
            # View.ViewDirection pointe vers l'observateur : c'est donc
            # normal_out qu'il faut viser. L'index passe a CreateElevation
            # donne une direction cardinale arbitraire, on corrige par
            # rotation du repere plutot que par pari sur cet index.
            dir_actuelle = vue.ViewDirection
            a_cible = math.atan2(normal_out.Y, normal_out.X)
            a_reel  = math.atan2(dir_actuelle.Y, dir_actuelle.X)
            angle   = a_cible - a_reel
            while angle > math.pi:
                angle -= 2.0 * math.pi
            while angle < -math.pi:
                angle += 2.0 * math.pi

            if abs(angle) > 1e-6:
                axe = Line.CreateBound(
                    marker_origin,
                    XYZ(marker_origin.X, marker_origin.Y,
                        marker_origin.Z + 1.0))
                ElementTransformUtils.RotateElement(
                    doc, marker.Id, axe, angle)
                doc.Regenerate()

            # --- Cadrage : projeter les coins cibles dans le repere final --
            cb  = vue.CropBox
            inv = cb.Transform.Inverse
            locaux = [inv.OfPoint(c) for c in coins_cadre]
            nouveau           = BoundingBoxXYZ()
            nouveau.Transform = cb.Transform
            nouveau.Min = XYZ(min(p.X for p in locaux),
                              min(p.Y for p in locaux), cb.Min.Z)
            nouveau.Max = XYZ(max(p.X for p in locaux),
                              max(p.Y for p in locaux), cb.Max.Z)
            vue.CropBox       = nouveau
            vue.CropBoxActive = True
            try:
                vue.CropBoxVisible = True
            except Exception:
                pass

            # --- Profondeur de vue ---
            for bip, valeur in (
                    (BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING, 2),
                    (BuiltInParameter.VIEWER_BOUND_OFFSET_FAR, far_offset)):
                try:
                    p = vue.get_Parameter(bip)
                    if p is not None and not p.IsReadOnly:
                        p.Set(valeur)
                except Exception:
                    reglages_ko.append(u"profondeur de vue")

            vue.Name = nom_vue

            gabarit_applique = False
            if template_id.IntegerValue != -1:
                # Gabarit applique en dernier : il pilote echelle, niveau de
                # detail et affichage, et ecraserait des reglages poses avant.
                # Un echec ici ne doit pas faire perdre la vue : on retombe
                # sur les reglages par defaut.
                try:
                    vue.ViewTemplateId = template_id
                    gabarit_applique = True
                except Exception:
                    reglages_ko.append(u"gabarit refuse par Revit")

            if not gabarit_applique:
                # Aucun gabarit : reglages par defaut de l'agence.
                for prop, valeur in (("Scale",        DEFAUT_ECHELLE),
                                     ("DetailLevel",  DEFAUT_DETAIL),
                                     ("DisplayStyle", DEFAUT_STYLE)):
                    try:
                        setattr(vue, prop, valeur)
                    except Exception:
                        reglages_ko.append(prop)

            t.Commit()
        except Exception as ex_creation:
            try:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
            except Exception:
                pass
            _show_fatal(u"{} — Creation impossible".format(TOOL_NAME),
                        ex_creation)
            return

        uidoc.ActiveView = vue

        if gabarit_applique:
            ligne_reglages = u"Gabarit : {}".format(template_nom)
        else:
            ligne_reglages = (
                u"Gabarit : (aucun)\n"
                u"Reglages : 1:{}, detail Eleve, ligne cachee".format(
                    DEFAUT_ECHELLE))
        if reglages_ko:
            ligne_reglages += u"\nNon applique(s) : {}".format(
                u", ".join(sorted(set(reglages_ko))))

        MessageBox.Show(
            u"Elevation creee.\n\n"
            u"Nom : {}\n"
            u"Type de vue : {}\n"
            u"Repere pose dans la vue en plan : {}\n"
            u"{}\n"
            u"Cadre : {:.2f} m x {:.2f} m\n"
            u"Voisins analyses : {}".format(
                nom_vue, elem_name(elev_type), elem_name(plan_hote),
                ligne_reglages,
                ft_to_m(larg_cadre), ft_to_m(haut_cadre), len(rows)),
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(
        TOOL_NAME, SCRIPT_VERSION), _ex)
