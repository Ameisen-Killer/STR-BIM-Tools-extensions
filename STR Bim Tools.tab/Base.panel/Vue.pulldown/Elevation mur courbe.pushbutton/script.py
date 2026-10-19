# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Elevation mur courbe"
# =============================================================================
# Cree l'elevation DEVELOPPEE d'un mur courbe, sous forme d'une vue de dessin
# (drafting view) remplie de lignes de detail.
#
# Pourquoi une vue de dessin et pas une vraie vue Revit :
#   l'API Revit ne sait creer ni elevation developpee ni coupe segmentee. Une
#   vraie vue sur un mur courbe montrerait l'arc en raccourci. On deroule donc
#   la face regardee a plat et on dessine le resultat en 2D strict.
#   Le dessin est fige : il ne suit pas le modele. L'outil relance sur sa
#   propre vue la REGENERE (efface et redessine), cf. marqueur ci-dessous.
#
# Repere developpe (u, v) :
#   u = abscisse curviligne le long de la FACE REGARDEE, croissante vers la
#       droite telle que la voit l'observateur (u = signe_ext * R_face * angle)
#   v = altitude Z absolue du modele
#   d = distance signee a l'axe du mur, positive vers l'observateur.
#       La face regardee est donc a d = +epaisseur/2.
#   Le dessin est translate pour que le coin bas-gauche du cadre soit en (0,0).
#
# Le PLAN DE VUE est le cylindre de la face regardee, cale sur la geometrie
# reelle du mur (pas sur epaisseur/2 : la ligne de trace n'est pas forcement
# au milieu du mur). Il se comporte comme le plan de coupe d'une vraie
# elevation, d'ou le classement des traits :
#
#   - LIGNE VUE     : le mur lui-meme. Le plan de vue lui est TANGENT, il ne
#                     le coupe pas : le mur est donc vu, jamais coupe. Il ne
#                     contribue que sa face regardee — contour exterieur,
#                     portes, fenetres, reservations. Une elevation de mur
#                     courbe isole ne contient donc QUE des lignes vues.
#                     Sont aussi en ligne vue les voisins situes derriere le
#                     plan de vue mais que le mur ne masque pas : dalle qui
#                     depasse un about, element vu au travers d'une porte.
#
#   - LIGNE COUPEE  : uniquement un voisin que le plan de vue TRAVERSE
#                     reellement — mur qui bute sur la face regardee et
#                     repart vers l'observateur, dalle traversante. Sa vraie
#                     section est calculee par intersection booleenne avec le
#                     demi-espace arriere.
#
#   - LIGNE CACHEE  : ce que le mur masque. Un voisin qui touche la face
#                     OPPOSEE, ou plus generalement toute geometrie situee
#                     derriere le plan de vue et dont la projection tombe
#                     dans la matiere du mur. L'occultation se teste dans le
#                     plan developpe, par la regle pair-impair sur les
#                     contours de la face regardee (cf. construire_masque) :
#                     un point vu au travers d'une porte en ressort
#                     naturellement visible.
#
# Ce qui est DEVANT le plan de vue n'est pas dessine : hors champ, comme dans
# une vraie elevation. Le fond de vue est a DEPTH_BEYOND_FT au-dela de la
# face opposee.
#
# DECALAGE DU PLAN DE VUE (saisi dans la fenetre, en cm, memorise) : porte le
# plan en avant de la face regardee. A zero, un element plaque contre la face
# sort du champ ; l'augmenter le fait apparaitre, et coupe ce que le plan
# traverse alors. Le mur, lui, reste toujours vu : il est en arriere du plan.
# C'est pourquoi le code distingue d_mur (face du mur, ce qui masque) de
# d_plan (limite de champ et surface de section).
#
# LIGNES DE NIVEAUX : chaque niveau du projet compris dans la hauteur du
# cadre recoit une ligne horizontale traversant tout le dessin, avec son nom
# et son altitude poses au-dessus a gauche. Sous-categorie STR_Ligne niveau.
#
# Cadrage (regles reprises telles quelles de "Elevation sur mur") :
#   - une dalle / un radier ne contraint que le cadrage VERTICAL
#   - un mur / un poteau ne contraint que le cadrage HORIZONTAL
#   - chaque extension est bridee par CLAMP_H_FT / CLAMP_V_FT
#   - marge MARGE_CADRE_FT au-dela du voisin le plus eloigne, ou du mur seul
#
# Regeneration : le parametre "Description de la vue" porte le marqueur
#   STR_ELEV_COURBE|<UniqueId du mur>|<+1 ou -1>
# Lancer l'outil depuis une vue qui le porte propose de la redessiner.
#
# Constantes principales (modifiables juste sous les imports) :
#   MARGE_CADRE_FT     50 cm  marge autour des elements voisins
#   DEPTH_BEYOND_FT    10 cm  profondeur au-dela de la face opposee
#   CLAMP_H_FT        200 cm  extension horizontale max due a un voisin
#   CLAMP_V_FT        100 cm  extension verticale max due a un voisin
#   TOL_CONTACT_FT      5 cm  tolerance de detection du contact
#   TOL_FACE_FT         2 mm  appartenance a la surface de coupe
#   SIMPLIFY_TOL_FT     2 mm  simplification des polylignes developpees
#   MAX_SEGMENTS      20000   garde-fou sur le nombre de lignes de detail
#   DEFAUT_ECHELLE / DEFAUT_DETAIL   reglages hors gabarit
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

    from System.Collections.Generic import List
    from System.Windows import (
        MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult
    )
    from System.Windows.Controls import ComboBoxItem

    from Autodesk.Revit.DB import (
        FilteredElementCollector, Transaction, TransactionStatus,
        XYZ, UV, BoundingBoxXYZ, Outline, BoundingBoxIntersectsFilter,
        ViewFamilyType, ViewFamily, View, ViewDrafting, ViewType,
        ViewDetailLevel, Element, ElementId, Color,
        Wall, Line, Arc, Curve, CurveLoop, CurveArray, CurveElement,
        Options, GeometryInstance, Solid, Face,
        GeometryCreationUtilities, BooleanOperationsUtils,
        BooleanOperationsType,
        FilledRegion, TextNote, TextNoteType, Level,
        LinePatternElement, GraphicsStyleType,
        BuiltInCategory, BuiltInParameter
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
    DEPTH_BEYOND_FT  = 0.10 * M2FT   # 10 cm au-dela de la face opposee

    CLAMP_H_FT       = 2.00 * M2FT   # extension H max due a un voisin
    CLAMP_V_FT       = 1.00 * M2FT   # extension V max due a un voisin
    TOL_CONTACT_FT   = 0.05 * M2FT   # 5 cm : tolerance de contact

    TOL_FACE_FT      = 0.002 * M2FT  # 2 mm : appartenance a la surface de coupe
    SIMPLIFY_TOL_FT  = 0.002 * M2FT  # 2 mm : simplification des polylignes
    EXT_DEMI_ESPACE  = 5.00 * M2FT   # debord du demi-espace de part et d'autre
    ANGLE_MAX_RAD    = math.radians(350.0)   # balayage max du demi-espace

    MAX_SEGMENTS     = 20000         # garde-fou lignes de detail

    DRAFTING_TYPE_NAME = u"STR_Elevation_Courbe"
    VIEW_NAME_PREFIX   = u"STR_Elevation_Mur_Courbe_"
    MARQUEUR           = u"STR_ELEV_COURBE"

    # Sous-categories de lignes creees si absentes.
    # (cle, nom, epaisseur de trait, motif recherche, couleur RVB)
    SUBCAT_SPECS = [
        ("coupe",  u"STR_Ligne coupée",  5, None,     (0, 0, 0)),
        ("vue",    u"STR_Ligne vue",     3, None,     (0, 0, 0)),
        ("cachee", u"STR_Ligne cachée",  1, u"tiret", (128, 128, 128)),
        ("niveau", u"STR_Ligne niveau",  1, u"axe",   (0, 100, 160)),
    ]

    # Decalage du plan de vue en avant de la face regardee, en centimetres.
    # A zero, le plan est pose sur la face : ce qui est devant elle sort du
    # champ. L'augmenter fait apparaitre ce qui est plaque contre la face
    # (poteau, nez de dalle) et coupe ce que le plan traverse alors.
    # Valeur de depart de la fenetre, ensuite memorisee dans prefs.json.
    DECALAGE_DEFAUT_CM = 0.0
    DECALAGE_MAX_CM    = 200.0

    # Reglages appliques quand AUCUN gabarit de vue n'est choisi.
    DEFAUT_ECHELLE = 50                      # 1:50
    DEFAUT_DETAIL  = ViewDetailLevel.Fine    # niveau de detail : Eleve

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

    def wrap_pi(a):
        """Ramene un angle dans (-pi, pi]."""
        while a > math.pi:
            a -= 2.0 * math.pi
        while a <= -math.pi:
            a += 2.0 * math.pi
        return a

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
    # DEVELOPPEE — mise a plat de la face regardee
    # =======================================================================

    class Developpee(object):
        """
        Convertit un point du modele en coordonnees developpees (u, v, d).

        La mise a plat se fait par projection RADIALE sur le cylindre de la
        face regardee : deux points de meme position angulaire tombent au
        meme u, quelle que soit leur profondeur. C'est ce qui fait qu'un
        percement traversant donne deux contours superposes en u, l'un
        coupe (face vue) et l'autre cache (face opposee).

        Trois modes selon la courbe de trace du mur :
          "arc"  : mapping analytique exact, valable meme au-dela des
                   extremites du mur (indispensable pour cadrer sur un
                   voisin qui deborde).
          "line" : mur droit — l'outil fonctionne mais "Elevation sur mur"
                   donne une vraie vue Revit, bien meilleure.
          "gen"  : autre courbe (spline, ellipse). Mapping par projection
                   sur la courbe de trace, donc BRIDE aux extremites : un
                   voisin qui deborde s'y ecrase. Signale a l'utilisateur.
        """

        def __init__(self, axis_curve, epaisseur, point_cote, decalage=0.0):
            self.e        = epaisseur
            self.demi     = epaisseur / 2.0
            self.decalage = decalage
            # Valeurs d'amorce : caler_sur_geometrie() les remplace par les
            # profondeurs reellement mesurees sur le mur.
            #   d_mur  face regardee du mur — sert a trouver son contour et
            #          a savoir ce qu'il masque
            #   d_plan plan de vue, en avant de d_mur du decalage demande —
            #          sert de limite de champ et de surface de section
            self.d_mur     = self.demi
            self.d_plan    = self.demi + decalage
            self.d_arriere = -self.demi              # face opposee
            self.d_fond    = -self.demi - DEPTH_BEYOND_FT
            self.courbe = axis_curve
            self.mode   = None

            pc = XYZ(point_cote.X, point_cote.Y, 0.0)

            if isinstance(axis_curve, Arc):
                self._init_arc(axis_curve, pc)
            elif isinstance(axis_curve, Line):
                self._init_line(axis_curve, pc)
            else:
                self._init_generique(axis_curve, pc)

        # ------------------------------------------------------------- arc
        def _init_arc(self, arc, pc):
            self.mode = "arc"
            c = arc.Center
            self.centre = XYZ(c.X, c.Y, 0.0)
            self.R      = arc.Radius

            a0 = self._angle(arc.GetEndPoint(0))
            a1 = self._angle(arc.GetEndPoint(1))
            am = self._angle(arc.Evaluate(0.5, True))
            d1 = wrap_pi(a1 - a0)
            dm = wrap_pi(am - a0)
            # Un arc de plus d'un demi-tour "repasse" par le wrap : le point
            # milieu tranche sans ambiguite le sens et l'amplitude reels.
            if (d1 >= 0.0) != (dm >= 0.0) or abs(dm) > abs(d1):
                d1 = d1 - (2.0 * math.pi if d1 >= 0.0 else -2.0 * math.pi)
            self.a0      = a0
            self.balayage = d1                     # signe
            self.mi      = d1 / 2.0

            r_cote = math.sqrt((pc.X - self.centre.X) ** 2 +
                               (pc.Y - self.centre.Y) ** 2)
            self.signe_ext = 1 if r_cote >= self.R else -1
            self.R_face    = self.R + self.signe_ext * self.demi
            self.longueur  = abs(self.balayage) * self.R_face

        def _angle(self, p):
            return math.atan2(p.Y - self.centre.Y, p.X - self.centre.X)

        # ------------------------------------------------------------ line
        def _init_line(self, ln, pc):
            self.mode = "line"
            p0 = ln.GetEndPoint(0)
            p1 = ln.GetEndPoint(1)
            self.p0 = XYZ(p0.X, p0.Y, 0.0)
            dv = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0).Normalize()
            n  = XYZ(-dv.Y, dv.X, 0.0)
            v  = pc - self.p0
            if (v.X * n.X + v.Y * n.Y) < 0.0:
                n = XYZ(-n.X, -n.Y, 0.0)
            self.n_out   = n
            # droite de l'observateur = Z ^ n_out
            self.t_right = XYZ(-n.Y, n.X, 0.0)
            self.signe_ext = 1
            self.R_face    = 0.0
            self.longueur  = ln.Length

        # ------------------------------------------------------- generique
        def _init_generique(self, cv, pc):
            self.mode = "gen"
            self.plat = self._aplatir(cv)
            self.longueur = self.plat.Length
            # Sens de la normale, teste au milieu de la courbe
            der = self.plat.ComputeDerivatives(0.5, True)
            t   = XYZ(der.BasisX.X, der.BasisX.Y, 0.0).Normalize()
            n   = XYZ(-t.Y, t.X, 0.0)
            pm  = self.plat.Evaluate(0.5, True)
            v   = XYZ(pc.X - pm.X, pc.Y - pm.Y, 0.0)
            self.gen_signe = 1.0 if (v.X * n.X + v.Y * n.Y) >= 0.0 else -1.0
            self.signe_ext = 1
            self.R_face    = 0.0
            # Table d'abscisses : parametre brut -> longueur cumulee
            self.stations = []
            n_ech = 200
            cum   = 0.0
            prev  = None
            for i in range(n_ech + 1):
                s  = float(i) / n_ech
                pt = self.plat.Evaluate(s, True)
                if prev is not None:
                    cum += pt.DistanceTo(prev)
                self.stations.append((s, cum, pt))
                prev = pt
            self.longueur = cum

        def _aplatir(self, cv):
            """
            Courbe de reference du mode generique. La courbe de trace d'un
            mur est a altitude constante : on la garde telle quelle et on
            ramene les points a SON altitude au moment de la projection.
            """
            return cv

        # --------------------------------------------------------- mapping
        def map(self, p):
            """Point du modele -> (u, v, d)."""
            if self.mode == "arc":
                dx = p.X - self.centre.X
                dy = p.Y - self.centre.Y
                r  = math.sqrt(dx * dx + dy * dy)
                a  = math.atan2(dy, dx)
                dth = self.mi + wrap_pi((a - self.a0) - self.mi)
                u   = self.signe_ext * self.R_face * dth
                d   = self.signe_ext * (r - self.R)
                return (u, p.Z, d)

            if self.mode == "line":
                vx = p.X - self.p0.X
                vy = p.Y - self.p0.Y
                u  = vx * self.t_right.X + vy * self.t_right.Y
                d  = vx * self.n_out.X + vy * self.n_out.Y
                return (u, p.Z, d)

            # generique : projection sur la courbe de trace (bride aux bouts)
            pf = XYZ(p.X, p.Y, self.stations[0][2].Z)
            try:
                res = self.plat.Project(pf)
                s   = self.plat.ComputeNormalizedParameter(res.Parameter)
                pp  = res.XYZ
            except Exception:
                return (0.0, p.Z, 0.0)
            if s < 0.0:
                s = 0.0
            elif s > 1.0:
                s = 1.0
            u = self._abscisse(s)
            der = self.plat.ComputeDerivatives(s, True)
            t   = XYZ(der.BasisX.X, der.BasisX.Y, 0.0).Normalize()
            n   = XYZ(-t.Y * self.gen_signe, t.X * self.gen_signe, 0.0)
            d   = (p.X - pp.X) * n.X + (p.Y - pp.Y) * n.Y
            return (u, p.Z, d)

        def _abscisse(self, s):
            st = self.stations
            lo, hi = 0, len(st) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if st[mid][0] <= s:
                    lo = mid
                else:
                    hi = mid
            s0, c0, _ = st[lo]
            s1, c1, _ = st[hi]
            if abs(s1 - s0) < 1e-12:
                return c0
            return c0 + (c1 - c0) * (s - s0) / (s1 - s0)

        def depth(self, p):
            return self.map(p)[2]

        def caler_sur_geometrie(self, solides):
            """
            Recale le plan de vue sur la vraie face du mur.

            d_mur valait epaisseur/2, ce qui suppose que la ligne de trace
            passe au milieu du mur. C'est faux des que la ligne de
            justification est un nu de face ou un nu de noyau, et faux aussi
            sur un mur multicouche dont Width ne decrit pas la position des
            couches. On prend donc la profondeur reellement atteinte par la
            matiere, ce qui est vrai dans tous les cas.
            """
            d_max = None
            d_min = None
            for s in solides:
                try:
                    aretes = s.Edges
                except Exception:
                    continue
                for ed in aretes:
                    try:
                        tess = ed.AsCurve().Tessellate()
                    except Exception:
                        continue
                    for p in tess:
                        d = self.map(p)[2]
                        if d_max is None or d > d_max:
                            d_max = d
                        if d_min is None or d < d_min:
                            d_min = d
            if d_max is None or d_max - d_min < 1e-6:
                return False
            self.d_mur     = d_max
            self.d_plan    = d_max + self.decalage
            self.d_arriere = d_min
            self.d_fond    = d_min - DEPTH_BEYOND_FT
            return True

        # ------------------------------------- courbes a profondeur donnee
        def supporte_demi_espace(self):
            return self.mode in ("arc", "line")

        def courbe_a_profondeur(self, d_val, u_lo, u_hi, z):
            """
            Courbe des points de profondeur d_val, entre les abscisses
            developpees u_lo et u_hi, a l'altitude z. Sert a fabriquer le
            demi-espace arriere utilise pour sectionner les voisins.
            """
            if self.mode == "arc":
                r = self.R + self.signe_ext * d_val
                if r < 1e-6:
                    return None
                th_lo = self.a0 + (u_lo / (self.signe_ext * self.R_face))
                th_hi = self.a0 + (u_hi / (self.signe_ext * self.R_face))
                if th_hi < th_lo:
                    th_lo, th_hi = th_hi, th_lo
                if th_hi - th_lo > ANGLE_MAX_RAD:
                    mi = (th_lo + th_hi) / 2.0
                    th_lo = mi - ANGLE_MAX_RAD / 2.0
                    th_hi = mi + ANGLE_MAX_RAD / 2.0
                c = XYZ(self.centre.X, self.centre.Y, z)
                return Arc.Create(c, r, th_lo, th_hi, XYZ.BasisX, XYZ.BasisY)

            if self.mode == "line":
                a = XYZ(self.p0.X + self.t_right.X * u_lo + self.n_out.X * d_val,
                        self.p0.Y + self.t_right.Y * u_lo + self.n_out.Y * d_val,
                        z)
                b = XYZ(self.p0.X + self.t_right.X * u_hi + self.n_out.X * d_val,
                        self.p0.Y + self.t_right.Y * u_hi + self.n_out.Y * d_val,
                        z)
                if a.DistanceTo(b) < 1e-6:
                    return None
                return Line.CreateBound(a, b)

            return None

    # =======================================================================
    # GEOMETRIE DU MUR
    # =======================================================================

    def get_wall_curve(wall):
        """Courbe de trace du mur, ou None."""
        loc = wall.Location
        if loc is None:
            return None
        try:
            return loc.Curve
        except Exception:
            return None

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

    def cote_du_clic(courbe, pt):
        """
        Cote du mur designe par un clic : +1 = face A, -1 = face B.
        Face A = l'extrados pour un arc, le cote +normale pour une droite.
        """
        if isinstance(courbe, Arc):
            c = courbe.Center
            r = math.sqrt((pt.X - c.X) ** 2 + (pt.Y - c.Y) ** 2)
            return 1 if r >= courbe.Radius else -1
        pm  = courbe.Evaluate(0.5, True)
        der = courbe.ComputeDerivatives(0.5, True)
        t   = XYZ(der.BasisX.X, der.BasisX.Y, 0.0).Normalize()
        n   = XYZ(-t.Y, t.X, 0.0)
        return 1 if ((pt.X - pm.X) * n.X + (pt.Y - pm.Y) * n.Y) >= 0.0 else -1

    def point_du_cote(courbe, cote):
        """
        Point franchement situe du cote demande. Sert a amorcer la
        developpee quand il n'y a pas de clic : mur preselectionne, ou
        regeneration ou le cote vient du marqueur de la vue.
        """
        pm = courbe.Evaluate(0.5, True)
        if isinstance(courbe, Arc):
            c  = courbe.Center
            vx, vy = pm.X - c.X, pm.Y - c.Y
            ln = math.sqrt(vx * vx + vy * vy) or 1.0
            r  = courbe.Radius + (1.0 if cote > 0 else -1.0) * \
                 min(1.0, courbe.Radius * 0.5)
            return XYZ(c.X + vx / ln * r, c.Y + vy / ln * r, pm.Z)
        der = courbe.ComputeDerivatives(0.5, True)
        t   = XYZ(der.BasisX.X, der.BasisX.Y, 0.0).Normalize()
        k   = 1.0 if cote > 0 else -1.0
        return XYZ(pm.X - t.Y * k, pm.Y + t.X * k, pm.Z)

    # =======================================================================
    # EXTRACTION DE GEOMETRIE
    # =======================================================================

    def _geom_options():
        o = Options()
        o.DetailLevel           = ViewDetailLevel.Fine
        o.ComputeReferences     = False
        o.IncludeNonVisibleObjects = False
        return o

    def collect_solids(elem):
        """
        Solides d'un element, instances imbriquees comprises. Les solides
        de volume nul (esquisses, plans de reference) sont ecartes.
        """
        out = []

        def _walk(geo):
            if geo is None:
                return
            for g in geo:
                if isinstance(g, Solid):
                    try:
                        if g.Volume > 1e-9 and g.Faces.Size > 0:
                            out.append(g)
                    except Exception:
                        pass
                elif isinstance(g, GeometryInstance):
                    # GetInstanceGeometry rend la geometrie deja placee en
                    # coordonnees projet : pas de transformation a appliquer.
                    try:
                        _walk(g.GetInstanceGeometry())
                    except Exception:
                        pass

        try:
            _walk(elem.get_Geometry(_geom_options()))
        except Exception:
            pass
        return out

    def faces_sur_surface(solid, dev, d_cible, tol):
        """
        Faces du solide entierement contenues dans la surface de profondeur
        d_cible (a tol pres). Sur le mur, c'est exactement la face regardee
        avec ses reservations ; sur un solide deja intersecte par le
        demi-espace arriere, c'est la section coupee.
        """
        retenues = []
        for f in solid.Faces:
            try:
                bb = f.GetBoundingBox()
            except Exception:
                continue
            ok    = True
            testes = 0
            for i in range(3):
                for j in range(3):
                    uu = bb.Min.U + (bb.Max.U - bb.Min.U) * (i + 0.5) / 3.0
                    vv = bb.Min.V + (bb.Max.V - bb.Min.V) * (j + 0.5) / 3.0
                    try:
                        uv = UV(uu, vv)
                        if not f.IsInside(uv):
                            continue
                        p = f.Evaluate(uv)
                    except Exception:
                        continue
                    testes += 1
                    if abs(dev.depth(p) - d_cible) > tol:
                        ok = False
                        break
                if not ok:
                    break
            if ok and testes > 0:
                retenues.append(f)
        return retenues

    # =======================================================================
    # DEVELOPPEMENT DES COURBES
    # =======================================================================

    def developper_courbe(cv, dev):
        """Courbe 3D -> polyligne [(u, v, d), ...] simplifiee."""
        try:
            tess = cv.Tessellate()
        except Exception:
            return []
        pts = []
        for p in tess:
            pts.append(dev.map(p))
        return simplifier(pts)

    def simplifier(pts):
        """
        Supprime les points intermediaires alignes, en (u, v) comme en
        profondeur. La tessellation Revit d'un arc porte par la surface de
        coupe produit des dizaines de points qui retombent tous sur une
        droite une fois deroules : sans ce filtrage, le dessin explose en
        nombre de lignes de detail.
        """
        if len(pts) < 3:
            return pts
        for _ in range(2):
            sortie = [pts[0]]
            i = 1
            while i < len(pts) - 1:
                a, b, c = sortie[-1], pts[i], pts[i + 1]
                if _aligne(a, b, c):
                    i += 1
                    continue
                sortie.append(b)
                i += 1
            sortie.append(pts[-1])
            if len(sortie) == len(pts):
                break
            pts = sortie
        return pts

    def _aligne(a, b, c):
        ax, ay, ad = a
        bx, by, bd = b
        cx, cy, cd = c
        vx, vy = cx - ax, cy - ay
        ln = math.sqrt(vx * vx + vy * vy)
        if ln < 1e-9:
            return (abs(bx - ax) < SIMPLIFY_TOL_FT and
                    abs(by - ay) < SIMPLIFY_TOL_FT)
        # distance du point b a la droite (a, c)
        dist = abs((bx - ax) * vy - (by - ay) * vx) / ln
        if dist > SIMPLIFY_TOL_FT:
            return False
        # la profondeur doit rester interpolable, sinon un croisement de la
        # surface de coupe serait gomme
        t  = ((bx - ax) * vx + (by - ay) * vy) / (ln * ln)
        di = ad + (cd - ad) * t
        return abs(bd - di) < 0.005 * M2FT

    # =======================================================================
    # CLASSEMENT DES SEGMENTS
    # =======================================================================

    def _interp(p0, p1, t):
        return (p0[0] + (p1[0] - p0[0]) * t,
                p0[1] + (p1[1] - p0[1]) * t)

    def construire_masque(contours):
        """
        Test d'occultation dans le plan developpe : le point (u, v) est-il
        masque par la matiere du mur ?

        Regle pair-impair sur TOUS les contours de la face regardee. Elle
        traite les reservations sans cas particulier : un point situe dans
        une porte traverse le contour exterieur puis le contour de la porte,
        donc un nombre pair de fois, donc il est declare visible — ce qui
        est exact, on voit bien a travers l'ouverture.

        Retourne une fonction (u, v) -> bool, ou None si le mur n'a pas
        livre de contour exploitable (tout est alors considere visible).
        """
        aretes = []
        u_lo = v_lo = u_hi = v_hi = None
        for grp in contours:
            for pts in grp:
                n = len(pts)
                if n < 3:
                    continue
                for k in range(n):
                    ax, ay = pts[k]
                    bx, by = pts[(k + 1) % n]
                    if u_lo is None:
                        u_lo = u_hi = ax
                        v_lo = v_hi = ay
                    u_lo = min(u_lo, ax); u_hi = max(u_hi, ax)
                    v_lo = min(v_lo, ay); v_hi = max(v_hi, ay)
                    # Une arete horizontale n'est jamais traversee par le
                    # rayon horizontal du test : l'ecarter evite une
                    # division par zero.
                    if abs(ay - by) < 1e-12:
                        continue
                    aretes.append((ax, ay, bx, by))
        if not aretes:
            return None

        def masque(u, v):
            # Rejet par boite englobante : sur un modele charge, la grande
            # majorite des points testes sont hors du mur.
            if u < u_lo or u > u_hi or v < v_lo or v > v_hi:
                return False
            n = 0
            for (ax, ay, bx, by) in aretes:
                if (ay > v) != (by > v):
                    if ax + (v - ay) * (bx - ax) / (by - ay) > u:
                        n += 1
            return (n % 2) == 1

        return masque

    NB_ECH_MASQUE = 12

    def _runs_masque(p0, p1, ta, tb, masque):
        """
        Classe un morceau de segment en 'vue' / 'cachee' selon qu'il est
        masque par le mur, en le decoupant aux changements. L'echantillonnage
        suffit ici : apres simplification, un segment traverse rarement plus
        d'une fois le bord du mur ou d'une reservation.
        """
        if masque is None:
            return [("vue", _interp(p0, p1, ta), _interp(p0, p1, tb))]
        out     = []
        n       = NB_ECH_MASQUE
        courant = None
        debut   = ta
        for k in range(n):
            t1 = ta + (tb - ta) * k / float(n)
            t2 = ta + (tb - ta) * (k + 1) / float(n)
            pm = _interp(p0, p1, (t1 + t2) / 2.0)
            cl = "cachee" if masque(pm[0], pm[1]) else "vue"
            if courant is None:
                courant, debut = cl, t1
            elif cl != courant:
                out.append((courant, _interp(p0, p1, debut),
                            _interp(p0, p1, t1)))
                courant, debut = cl, t1
        if courant is not None:
            out.append((courant, _interp(p0, p1, debut),
                        _interp(p0, p1, tb)))
        return out

    def decouper_segment(p0, p1, d0, d1, d_plan, d_mur, d_fond, tol, masque):
        """
        Decoupe un segment developpe et le classe. Retourne une liste de
        (classe, (u,v), (u,v)).

        Comme dans une vraie elevation :
          - ce qui est DEVANT le plan de vue est hors champ, pas dessine ;
          - ce qui est entre le plan de vue et la face du mur est devant le
            mur, donc toujours VU — c'est ce que le decalage fait apparaitre
            (poteau plaque contre la face, nez de dalle en saillie) ;
          - ce qui est en arriere de la face du mur est vu ou cache selon
            que le mur le masque ou non.
        La section proprement dite (trait coupe) n'est pas produite ici :
        elle vient de l'intersection booleenne, dans section_voisin().
        """
        ts = [0.0, 1.0]
        if abs(d1 - d0) > 1e-12:
            for dv in (d_plan, d_mur, d_fond):
                t = (dv - d0) / (d1 - d0)
                if 1e-9 < t < 1.0 - 1e-9:
                    ts.append(t)
        ts.sort()
        out = []
        for i in range(len(ts) - 1):
            ta, tb = ts[i], ts[i + 1]
            if tb - ta < 1e-9:
                continue
            dm = d0 + (d1 - d0) * (ta + tb) / 2.0
            if dm > d_plan + tol:
                continue                      # devant le plan de vue
            if dm < d_fond:
                continue                      # au-dela du fond de vue
            if dm > d_mur - tol:
                # devant la face du mur : rien ne peut le masquer
                out.append(("vue", _interp(p0, p1, ta), _interp(p0, p1, tb)))
            else:
                out.extend(_runs_masque(p0, p1, ta, tb, masque))
        return out

    def segments_du_solide(solid, dev, sac, masque):
        """
        Developpe toutes les aretes d'un solide et range les segments
        classes dans 'sac' (dict classe -> liste de segments).

        Retourne (nuage, d_min, d_max) :
          nuage        points developpes retenus, c'est-a-dire dans la
                       profondeur de vue — c'est lui qui sert au cadrage ;
          d_min, d_max amplitude BRUTE en profondeur, avant tout filtrage.
                       Elle dit si le solide traverse la surface de coupe,
                       et evite ainsi de lancer une intersection booleenne
                       sur un voisin qui est tout entier d'un seul cote.
        """
        nuage = []
        d_min = None
        d_max = None
        try:
            aretes = solid.Edges
        except Exception:
            return nuage, d_min, d_max
        for ed in aretes:
            try:
                cv = ed.AsCurve()
            except Exception:
                continue
            pts = developper_courbe(cv, dev)
            if len(pts) < 2:
                continue
            for p in pts:
                if d_min is None or p[2] < d_min:
                    d_min = p[2]
                if d_max is None or p[2] > d_max:
                    d_max = p[2]
            for k in range(len(pts) - 1):
                a, b = pts[k], pts[k + 1]
                for cl, pa, pb in decouper_segment(
                        (a[0], a[1]), (b[0], b[1]), a[2], b[2],
                        dev.d_plan, dev.d_mur, dev.d_fond,
                        TOL_FACE_FT, masque):
                    sac[cl].append((pa, pb))
                    nuage.append(pa)
                    nuage.append(pb)
        return nuage, d_min, d_max

    def ajouter_loops(loops, dev, sac, classe):
        """Developpe des CurveLoop 3D et les range en tant que 'classe'."""
        sortie = []
        for lp in loops:
            pts = []
            for cv in lp:
                dpts = developper_courbe(cv, dev)
                for p in dpts:
                    if not pts or abs(p[0] - pts[-1][0]) > 1e-9 \
                               or abs(p[1] - pts[-1][1]) > 1e-9:
                        pts.append(p)
            if len(pts) < 3:
                continue
            pts = simplifier(pts)
            for k in range(len(pts) - 1):
                sac[classe].append(((pts[k][0], pts[k][1]),
                                    (pts[k + 1][0], pts[k + 1][1])))
            # fermeture explicite
            if abs(pts[0][0] - pts[-1][0]) > 1e-9 or \
               abs(pts[0][1] - pts[-1][1]) > 1e-9:
                sac[classe].append(((pts[-1][0], pts[-1][1]),
                                    (pts[0][0], pts[0][1])))
            sortie.append([(p[0], p[1]) for p in pts])
        return sortie

    # =======================================================================
    # DETECTION DES VOISINS
    # =======================================================================

    def collect_neighbours(wall):
        """
        Elements du modele courant dont la bounding box touche (a
        TOL_CONTACT_FT pres) celle du mur, dans les categories analysees.
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
        vus     = {}
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
                k = e.Id.IntegerValue
                if k in vus:
                    continue
                vus[k] = True
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

    def influence_voisin(elem, nuage, u_min, u_max, z_bas, z_haut):
        """
        Contribution d'un voisin au cadrage, a partir de son nuage de points
        developpes (deja filtre par la profondeur de vue).

        Regle metier reprise de "Elevation sur mur" :
          - une dalle / un radier ne contraint que le cadrage VERTICAL
          - un mur / un poteau ne contraint que le cadrage HORIZONTAL
        Chaque extension est bridee par CLAMP_H_FT / CLAMP_V_FT.
        Retourne (ext_g, ext_d, ext_b, ext_h, texte_influence).
        """
        if not nuage:
            return 0.0, 0.0, 0.0, 0.0, u"hors profondeur de vue"

        if is_dalle(elem):
            z_lo = min(p[1] for p in nuage)
            z_hi = max(p[1] for p in nuage)
            d_bas  = min(max(0.0, z_bas - z_lo),  CLAMP_V_FT)
            d_haut = min(max(0.0, z_hi - z_haut), CLAMP_V_FT)
            inf = []
            if d_bas > 1e-6:
                inf.append(u"bas {:.2f} m".format(ft_to_m(d_bas)))
            if d_haut > 1e-6:
                inf.append(u"haut {:.2f} m".format(ft_to_m(d_haut)))
            return 0.0, 0.0, d_bas, d_haut, \
                   (u" + ".join(inf) if inf else u"aucune")

        u_lo = min(p[0] for p in nuage)
        u_hi = max(p[0] for p in nuage)
        d_g = min(max(0.0, u_min - u_lo), CLAMP_H_FT)
        d_d = min(max(0.0, u_hi - u_max), CLAMP_H_FT)
        inf = []
        if d_g > 1e-6:
            inf.append(u"gauche {:.2f} m".format(ft_to_m(d_g)))
        if d_d > 1e-6:
            inf.append(u"droite {:.2f} m".format(ft_to_m(d_d)))
        return d_g, d_d, 0.0, 0.0, \
               (u" + ".join(inf) if inf else u"aucune")

    # =======================================================================
    # DEMI-ESPACE ARRIERE (section des voisins traversants)
    # =======================================================================

    def construire_demi_espace(dev, z_lo, z_hi, u_lo, u_hi):
        """
        Solide occupant tout ce qui est DERRIERE la surface de coupe, sur
        l'etendue utile. Intersecter un voisin avec ce solide isole sa
        partie cachee ; les faces du resultat qui retombent sur la surface
        de coupe sont exactement sa section.
        Retourne None si la courbe de trace ne le permet pas (mode "gen").
        """
        if not dev.supporte_demi_espace():
            return None
        prof = (dev.d_plan - dev.d_arriere) + 1.0 * M2FT
        c_face = dev.courbe_a_profondeur(dev.d_plan, u_lo, u_hi, z_lo)
        c_fond = dev.courbe_a_profondeur(dev.d_plan - prof, u_lo, u_hi, z_lo)
        if c_face is None or c_fond is None:
            return None
        try:
            loop = CurveLoop()
            loop.Append(c_face)
            loop.Append(Line.CreateBound(c_face.GetEndPoint(1),
                                         c_fond.GetEndPoint(1)))
            loop.Append(c_fond.CreateReversed())
            loop.Append(Line.CreateBound(c_fond.GetEndPoint(0),
                                         c_face.GetEndPoint(0)))
            lst = List[CurveLoop]()
            lst.Add(loop)
            return GeometryCreationUtilities.CreateExtrusionGeometry(
                lst, XYZ.BasisZ, max(z_hi - z_lo, 1.0))
        except Exception:
            return None

    def section_voisin(solid, demi_espace, dev):
        """Section d'un voisin sur la surface de coupe, ou [] si impossible."""
        if demi_espace is None:
            return []
        try:
            inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                solid, demi_espace, BooleanOperationsType.Intersect)
        except Exception:
            return []
        if inter is None:
            return []
        try:
            if inter.Volume < 1e-9:
                return []
        except Exception:
            return []
        loops = []
        for f in faces_sur_surface(inter, dev, dev.d_plan, TOL_FACE_FT):
            try:
                for lp in f.GetEdgesAsCurveLoops():
                    loops.append(lp)
            except Exception:
                pass
        return loops

    # =======================================================================
    # SOUS-CATEGORIES DE LIGNES
    # =======================================================================

    def trouver_motif(nom_partiel):
        if not nom_partiel:
            return None
        cible = nom_partiel.lower()
        for lp in FilteredElementCollector(doc).OfClass(LinePatternElement):
            try:
                if cible in elem_name(lp).lower():
                    return lp.Id
            except Exception:
                pass
        return None

    def assurer_sous_categories(rapport_ko):
        """
        Cree si besoin les sous-categories de lignes et retourne
        {cle: GraphicsStyle}. A appeler dans une transaction ouverte.
        """
        cats  = doc.Settings.Categories
        lignes = cats.get_Item(BuiltInCategory.OST_Lines)
        existantes = {}
        try:
            for c in lignes.SubCategories:
                existantes[elem_name(c)] = c
        except Exception:
            pass

        styles = {}
        for cle, nom, poids, motif, rvb in SUBCAT_SPECS:
            sub = existantes.get(nom)
            neuve = False
            if sub is None:
                try:
                    sub = cats.NewSubcategory(lignes, nom)
                    neuve = True
                except Exception:
                    rapport_ko.append(u"sous-categorie '{}'".format(nom))
                    styles[cle] = None
                    continue
            if neuve:
                # Les reglages ne sont poses qu'a la creation : une
                # sous-categorie deja presente appartient au projet, on ne
                # touche pas aux choix graphiques de l'utilisateur.
                try:
                    sub.SetLineWeight(poids, GraphicsStyleType.Projection)
                except Exception:
                    rapport_ko.append(u"epaisseur de '{}'".format(nom))
                try:
                    sub.LineColor = Color(rvb[0], rvb[1], rvb[2])
                except Exception:
                    pass
                pid = trouver_motif(motif)
                if pid is not None:
                    try:
                        sub.SetLinePatternId(pid, GraphicsStyleType.Projection)
                    except Exception:
                        pass
            try:
                styles[cle] = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
            except Exception:
                styles[cle] = None
        return styles

    # =======================================================================
    # TYPE DE VUE / GABARIT / NOMMAGE
    # =======================================================================

    def get_drafting_view_type(document):
        """ViewFamilyType de vue de dessin : nom prioritaire, sinon premier."""
        premier = None
        par_nom = {}
        for vft in FilteredElementCollector(document).OfClass(ViewFamilyType):
            try:
                if vft.ViewFamily != ViewFamily.Drafting:
                    continue
            except Exception:
                continue
            if premier is None:
                premier = vft
            nom = elem_name(vft)
            if nom:
                par_nom[nom] = vft
        if DRAFTING_TYPE_NAME in par_nom:
            return par_nom[DRAFTING_TYPE_NAME]
        return premier

    def list_view_templates(document):
        """
        Gabarits applicables a une vue de dessin, tries par nom.
        Revit refuse un gabarit d'un autre type de vue : la liste ne peut
        donc pas contenir les gabarits d'elevation de l'outil "Elevation
        sur mur".
        """
        retenus = []
        for v in FilteredElementCollector(document).OfClass(View):
            try:
                if not v.IsTemplate:
                    continue
                if v.ViewType != ViewType.DraftingView:
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

    def view_name_exists(document, name, sauf_id=None):
        for v in FilteredElementCollector(document).OfClass(View):
            try:
                if v.IsTemplate:
                    continue
                if sauf_id is not None and v.Id == sauf_id:
                    continue
                if elem_name(v) == name:
                    return True
            except Exception:
                pass
        return False

    def lire_marqueur(vue):
        """(mur, cote) si la vue porte le marqueur de l'outil."""
        if not isinstance(vue, ViewDrafting):
            return None, None
        try:
            p = vue.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
            txt = p.AsString() if p is not None else None
        except Exception:
            return None, None
        if not txt or not txt.startswith(MARQUEUR + u"|"):
            return None, None
        bouts = txt.split(u"|")
        if len(bouts) < 3:
            return None, None
        try:
            mur = doc.GetElement(bouts[1])
        except Exception:
            mur = None
        if not isinstance(mur, Wall):
            return None, None
        try:
            signe = int(bouts[2])
        except Exception:
            return None, None
        return mur, (1 if signe >= 0 else -1)

    def ecrire_marqueur(vue, wall, cote):
        try:
            p = vue.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
            if p is not None and not p.IsReadOnly:
                p.Set(u"{}|{}|{}".format(MARQUEUR, wall.UniqueId, cote))
                return True
        except Exception:
            pass
        return False

    def vider_vue(vue):
        """Efface le contenu dessine d'une vue de dessin (regeneration)."""
        ids = List[ElementId]()
        for e in FilteredElementCollector(doc, vue.Id).ToElements():
            if isinstance(e, (CurveElement, FilledRegion, TextNote)):
                ids.Add(e.Id)
        if ids.Count:
            doc.Delete(ids)
        return ids.Count

    # =======================================================================
    # SELECTION
    # =======================================================================

    class WallFilter(ISelectionFilter):
        def AllowElement(self, elem):
            return isinstance(elem, Wall)
        def AllowReference(self, ref, point):
            return True

    def get_preselected_wall():
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
                u"Cliquez sur la face du mur courbe depuis laquelle regarder")
        except Exception:
            return None, None
        el = doc.GetElement(ref.ElementId)
        if not isinstance(el, Wall):
            return None, None
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
        Width="760" Height="720" MinWidth="640" MinHeight="600"
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
            <TextBlock x:Name="lbl_face_info" FontSize="10"
                       Foreground="#7F8C8D" TextWrapping="Wrap"
                       Margin="0,5,0,0"/>
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
                                  Binding="{Binding Categorie}" Width="140"/>
              <DataGridTextColumn x:Name="col_elem"
                                  Binding="{Binding Element}"
                                  Width="*" MinWidth="230"/>
              <DataGridTextColumn x:Name="col_pos"
                                  Binding="{Binding Position}" Width="120"/>
              <DataGridTextColumn x:Name="col_infl"
                                  Binding="{Binding Influence}" Width="160"/>
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
            <TextBlock Grid.Row="1" Grid.Column="0" x:Name="lbl_decalage"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <StackPanel Grid.Row="1" Grid.Column="1" Orientation="Horizontal">
              <TextBox x:Name="txt_decalage" Width="70" Height="24"
                       FontSize="12" VerticalContentAlignment="Center"/>
              <Button x:Name="btn_appliquer" Height="24" Padding="10,0"
                      Margin="8,0,0,0" FontSize="11" Cursor="Hand"/>
            </StackPanel>
            <TextBlock Grid.Row="2" Grid.Column="1" x:Name="lbl_decalage_info"
                       FontSize="10" Foreground="#7F8C8D" TextWrapping="Wrap"
                       Margin="0,3,0,6"/>
            <TextBlock Grid.Row="3" Grid.Column="0" x:Name="lbl_gabarit"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <ComboBox Grid.Row="3" Grid.Column="1" x:Name="cmb_gabarit"
                      Height="24" FontSize="12" VerticalContentAlignment="Center"/>
            <TextBlock Grid.Row="4" Grid.Column="1" x:Name="lbl_gabarit_info"
                       FontSize="10" Foreground="#7F8C8D" TextWrapping="Wrap"
                       Margin="0,3,0,6"/>
            <TextBlock Grid.Row="5" Grid.Column="0" x:Name="lbl_nom"
                       FontSize="11" FontWeight="SemiBold"
                       VerticalAlignment="Center" Margin="0,0,8,0"/>
            <TextBox Grid.Row="5" Grid.Column="1" x:Name="txt_nom"
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
              <Button x:Name="btn_ok" Width="170" Height="28" Margin="0,0,6,0"
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
        def __init__(self, cat, elem, position, influence):
            self.Categorie = cat
            self.Element   = elem
            self.Position  = position
            self.Influence = influence

    def lire_decalage(txt, defaut):
        """Decalage saisi, en centimetres. Virgule acceptee, valeur bridee."""
        try:
            v = float((txt or u"").strip().replace(u",", u"."))
        except Exception:
            return defaut
        if v < 0.0:
            v = 0.0                       # en arriere, le mur serait coupe
        if v > DECALAGE_MAX_CM:
            v = DECALAGE_MAX_CM
        return v

    def show_confirm_window(info_mur, label_face_a, label_face_b,
                            face_index_defaut, info_face, rows, info_cadre,
                            nom_propose, gabarits, gabarit_defaut, mode_regen,
                            decalage_cm):
        """
        Retourne (action, index_face, nom_vue, (template_id, template_nom),
        decalage_cm) avec action dans :
          "ok"       valider et dessiner
          "recalcul" refaire l'analyse avec la face / le decalage saisis
          "annule"   ne rien faire
        index_face : 0 = face A (extrados / face +), 1 = face B
        """
        win = load_xaml(XAML_CONFIRM)

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text = u"{}  |  Revit {}".format(
            TOOL_NAME + (u" — regeneration" if mode_regen else u""),
            app.VersionNumber)
        win.FindName("lbl_footer").Text        = _FOOTER
        win.FindName("lbl_mur").Text           = info_mur
        win.FindName("lbl_face_titre").Text    = u"Face depuis laquelle regarder"
        win.FindName("rb_face_a").Content      = label_face_a
        win.FindName("rb_face_b").Content      = label_face_b
        win.FindName("lbl_face_info").Text     = info_face
        win.FindName("lbl_voisins_titre").Text = \
            u"Elements en contact analyses ({})".format(len(rows))
        win.FindName("lbl_cadre").Text         = info_cadre
        win.FindName("lbl_decalage").Text      = u"Decalage du plan de vue :"
        win.FindName("txt_decalage").Text      = u"{:.0f}".format(decalage_cm)
        win.FindName("btn_appliquer").Content  = u"Appliquer"
        win.FindName("lbl_decalage_info").Text = (
            u"En centimetres, en avant de la face regardee. A 0, le plan est "
            u"pose sur la face : ce qui est devant elle sort du champ. "
            u"L'augmenter fait apparaitre ce qui est plaque contre la face "
            u"et coupe ce que le plan traverse alors. Changer cette valeur "
            u"ou la face refait toute l'analyse.")
        win.FindName("lbl_gabarit").Text       = u"Gabarit de vue :"
        win.FindName("lbl_nom").Text           = u"Nom de la vue :"
        win.FindName("txt_nom").Text           = nom_propose
        win.FindName("btn_ok").Content         = (
            u"Regenerer le dessin" if mode_regen else u"Creer l'elevation")
        win.FindName("btn_cancel").Content     = u"Annuler"

        win.FindName("col_cat").Header  = u"Categorie"
        win.FindName("col_elem").Header = u"Element"
        win.FindName("col_pos").Header  = u"Position"
        win.FindName("col_infl").Header = u"Influence sur le cadre"

        win.FindName("dg_voisins").ItemsSource = rows

        if mode_regen:
            win.FindName("txt_nom").IsEnabled     = False
            win.FindName("rb_face_a").IsEnabled   = False
            win.FindName("rb_face_b").IsEnabled   = False

        if face_index_defaut == 1:
            win.FindName("rb_face_b").IsChecked = True
        else:
            win.FindName("rb_face_a").IsChecked = True

        # --- Combo gabarits : "(aucun)" en premier, puis les gabarits ---
        cmb      = win.FindName("cmb_gabarit")
        lbl_info = win.FindName("lbl_gabarit_info")

        item_aucun         = ComboBoxItem()
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
            u"Seuls les gabarits de VUE DE DESSIN sont proposables ici : "
            u"Revit refuse un gabarit d'elevation sur une vue de dessin. "
            u"Sans gabarit, la vue est creee en 1:{}, niveau de detail "
            u"Eleve.".format(DEFAUT_ECHELLE)
        )

        def maj_info(s=None, e=None):
            sel = cmb.SelectedItem
            if sel is None or sel.Tag is None:
                lbl_info.Text = txt_defauts
            else:
                lbl_info.Text = (
                    u"Le gabarit pilote l'echelle et le niveau de detail "
                    u"de la vue.")

        cmb.SelectionChanged += maj_info
        cmb.SelectedIndex     = index_defaut
        maj_info()

        etat = {"action": "annule"}

        def on_ok(s, e):
            etat["action"] = "ok"
            win.Close()

        def on_appliquer(s, e):
            etat["action"] = "recalcul"
            win.Close()

        def on_cancel(s, e):
            win.Close()

        win.FindName("btn_ok").Click        += on_ok
        win.FindName("btn_appliquer").Click += on_appliquer
        win.FindName("btn_cancel").Click    += on_cancel
        win.ShowDialog()

        # La face et le decalage se relisent meme sur "Annuler" : la boucle
        # appelante en a besoin pour savoir quoi recalculer.
        idx = 1 if win.FindName("rb_face_b").IsChecked else 0
        nom = (win.FindName("txt_nom").Text or u"").strip()
        dec = lire_decalage(win.FindName("txt_decalage").Text, decalage_cm)

        sel     = cmb.SelectedItem
        tpl_id  = sel.Tag if (sel is not None and sel.Tag is not None) \
                  else ElementId.InvalidElementId
        tpl_nom = sel.Content if (sel is not None and sel.Tag is not None) else u""
        return etat["action"], idx, nom, (tpl_id, tpl_nom), dec

    # =======================================================================
    # DESSIN
    # =======================================================================

    def dedupe(segments, du, dv_):
        """
        Translate les segments dans le repere du dessin et elimine les
        doublons. La projection radiale superpose systematiquement des
        aretes (face vue et face opposee d'un percement traversant se
        confondent en u), sans quoi le dessin porte deux fois les memes
        lignes.
        """
        vus = {}
        out = []
        court = doc.Application.ShortCurveTolerance * 1.5
        for (a, b) in segments:
            ax, ay = a[0] - du, a[1] - dv_
            bx, by = b[0] - du, b[1] - dv_
            if math.sqrt((bx - ax) ** 2 + (by - ay) ** 2) < court:
                continue
            ka = (round(ax, 4), round(ay, 4))
            kb = (round(bx, 4), round(by, 4))
            cle = (ka, kb) if ka <= kb else (kb, ka)
            if cle in vus:
                continue
            vus[cle] = True
            out.append(((ax, ay), (bx, by)))
        return out

    def tracer(vue, segments, style, rapport_ko):
        """Cree les lignes de detail d'une classe. Retourne le nombre pose."""
        if not segments:
            return 0
        arr = CurveArray()
        for (a, b) in segments:
            try:
                arr.Append(Line.CreateBound(XYZ(a[0], a[1], 0.0),
                                            XYZ(b[0], b[1], 0.0)))
            except Exception:
                pass
        if arr.Size == 0:
            return 0
        try:
            crees = doc.Create.NewDetailCurveArray(vue, arr)
        except Exception:
            rapport_ko.append(u"lignes de detail")
            return 0
        if style is not None:
            for dc in crees:
                try:
                    dc.LineStyle = style
                except Exception:
                    pass
        return arr.Size


    def niveaux_du_cadre(v_lo, v_hi):
        """
        Niveaux du projet compris dans la hauteur du cadre, du bas vers le
        haut. Retourne une liste de (nom, altitude en pieds).
        """
        out = []
        for lv in FilteredElementCollector(doc).OfClass(Level):
            try:
                z = lv.Elevation
            except Exception:
                continue
            if v_lo - 1e-6 <= z <= v_hi + 1e-6:
                out.append((elem_name(lv), z))
        out.sort(key=lambda x: x[1])
        return out

    def hauteur_texte(vue, tnt):
        """
        Hauteur d'une ligne de texte en coordonnees modele. Un texte est
        dimensionne sur le papier : sa taille dans la vue depend donc de
        l'echelle, qui doit deja etre posee quand on appelle ceci.
        """
        try:
            echelle = float(vue.Scale)
        except Exception:
            echelle = float(DEFAUT_ECHELLE)
        if tnt is not None:
            try:
                p = tnt.get_Parameter(BuiltInParameter.TEXT_SIZE)
                if p is not None and p.AsDouble() > 1e-9:
                    return p.AsDouble() * echelle
            except Exception:
                pass
        return 0.0025 * M2FT * echelle        # repli : texte 2.5 mm

    def poser_niveaux(vue, niveaux, largeur, v_lo, style, rapport_ko):
        """
        Une ligne horizontale par niveau, traversant tout le cadre, avec le
        nom du niveau et son altitude poses juste au-dessus, a gauche.
        Retourne le nombre de niveaux traces.
        """
        if not niveaux:
            return 0

        arr = CurveArray()
        for (nom, z) in niveaux:
            v = z - v_lo
            try:
                arr.Append(Line.CreateBound(XYZ(0.0, v, 0.0),
                                            XYZ(largeur, v, 0.0)))
            except Exception:
                pass
        if arr.Size == 0:
            return 0
        try:
            crees = doc.Create.NewDetailCurveArray(vue, arr)
        except Exception:
            rapport_ko.append(u"lignes de niveaux")
            return 0
        if style is not None:
            for dc in crees:
                try:
                    dc.LineStyle = style
                except Exception:
                    pass

        tnt = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
        if tnt is None:
            rapport_ko.append(u"etiquettes de niveaux (aucun type de texte)")
            return arr.Size
        h = hauteur_texte(vue, tnt)
        for (nom, z) in niveaux:
            try:
                TextNote.Create(
                    doc, vue.Id,
                    XYZ(0.05 * M2FT, (z - v_lo) + h * 1.35, 0.0),
                    u"{}   {:+.3f}".format(nom, ft_to_m(z)),
                    tnt.Id)
            except Exception:
                rapport_ko.append(u"etiquettes de niveaux")
                break
        return arr.Size

    def poser_annotation(vue, texte, rapport_ko):
        tnt = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
        if tnt is None:
            rapport_ko.append(u"annotation (aucun type de texte)")
            return
        try:
            TextNote.Create(doc, vue.Id,
                            XYZ(0.0, -0.30 * M2FT, 0.0), texte, tnt.Id)
        except Exception:
            rapport_ko.append(u"annotation")

    # =======================================================================
    # ANALYSE
    # =======================================================================

    def analyser(wall, courbe, epaisseur, cote, decalage_cm,
                 z_bas, z_haut, solides_mur):
        """
        Met le mur a plat sur le cote demande et classe toute la geometrie.
        Isolee dans sa propre fonction parce qu'elle depend entierement du
        cote regarde : changer de face dans la fenetre la relance.

        Retourne un dictionnaire, ou None si la mise a plat n'a rien donne.
        """
        dev = Developpee(courbe, epaisseur, point_du_cote(courbe, cote),
                         decalage_cm / 100.0 * M2FT)
        sac = {"coupe": [], "vue": [], "cachee": []}

        # Plan de vue recale sur la vraie face du mur (cf. la methode).
        dev.caler_sur_geometrie(solides_mur)

        # Le mur est le SUJET de l'elevation : son plan de vue lui est
        # tangent, il ne le coupe pas. Le mur est donc VU, pas coupe, et il
        # ne contribue que sa face regardee : contour exterieur, portes,
        # fenetres et reservations. Le reste de son volume est derriere
        # cette face, donc cache par lui-meme : le dessiner ne ferait que
        # doubler les traits, la projection radiale ramenant la face
        # opposee au meme endroit.
        contours_mur = []
        for s in solides_mur:
            for f in faces_sur_surface(s, dev, dev.d_mur, TOL_FACE_FT):
                try:
                    loops = list(f.GetEdgesAsCurveLoops())
                except Exception:
                    continue
                grp = ajouter_loops(loops, dev, sac, "vue")
                if grp:
                    contours_mur.append(grp)

        if not contours_mur:
            return None

        # Ce meme contour sert de masque d'occultation pour les voisins.
        masque = construire_masque(contours_mur)

        # Etendue du mur seul, en abscisse developpee
        u_mur = []
        for grp in contours_mur:
            for pts in grp:
                u_mur.extend([p[0] for p in pts])
        u_min = min(u_mur)
        u_max = max(u_mur)

        # --- Demi-espace arriere, pour sectionner les voisins traversants --
        demi = construire_demi_espace(
            dev,
            z_bas - EXT_DEMI_ESPACE, z_haut + EXT_DEMI_ESPACE,
            u_min - EXT_DEMI_ESPACE, u_max + EXT_DEMI_ESPACE)

        # --- Voisins ---
        ext_g = ext_d = ext_b = ext_h = 0.0
        rows      = []
        nb_coupes = 0
        for e in collect_neighbours(wall):
            solides = collect_solids(e)
            if not solides:
                rows.append(VoisinRow(category_label(e), elem_label(e),
                                      u"—", u"geometrie illisible"))
                continue
            nuage       = []
            loops_coupe = []
            d_lo = d_hi = None
            for s in solides:
                n, dmin, dmax = segments_du_solide(s, dev, sac, masque)
                nuage.extend(n)
                if dmin is None:
                    continue
                d_lo = dmin if d_lo is None else min(d_lo, dmin)
                d_hi = dmax if d_hi is None else max(d_hi, dmax)
                # Section booleenne seulement si le solide traverse
                # reellement la surface de coupe : sur un modele charge, la
                # lancer sur chaque voisin couterait beaucoup pour rien.
                if dmin < dev.d_plan - TOL_FACE_FT < dmax:
                    loops_coupe.extend(section_voisin(s, demi, dev))

            if loops_coupe:
                grp = ajouter_loops(loops_coupe, dev, sac, "coupe")
                if grp:
                    nb_coupes += 1
                    for pts in grp:
                        nuage.extend([(p[0], p[1]) for p in pts])

            g, d_, b, h, infl = influence_voisin(
                e, nuage, u_min, u_max, z_bas, z_haut)
            ext_g = max(ext_g, g)
            ext_d = max(ext_d, d_)
            ext_b = max(ext_b, b)
            ext_h = max(ext_h, h)

            if d_lo is None:
                pos = u"illisible"
            elif d_lo < dev.d_plan - TOL_FACE_FT < d_hi:
                pos = u"coupe"            # traverse le plan de vue
            elif d_lo >= dev.d_plan - TOL_FACE_FT:
                pos = u"hors champ"
            elif not nuage:
                pos = u"hors profondeur"
            else:
                pos = u"derriere"
            rows.append(VoisinRow(category_label(e), elem_label(e), pos, infl))

        # La marge de 50 cm s'ajoute a la distance au voisin le plus eloigne ;
        # sans voisin dans une direction, elle s'applique au mur lui-meme.
        ext_g += MARGE_CADRE_FT
        ext_d += MARGE_CADRE_FT
        ext_b += MARGE_CADRE_FT
        ext_h += MARGE_CADRE_FT

        rows.sort(key=lambda r: (r.Categorie, r.Element))

        u_lo = u_min - ext_g
        u_hi = u_max + ext_d
        v_lo = z_bas - ext_b
        v_hi = z_haut + ext_h

        return {
            "dev": dev, "sac": sac, "contours_mur": contours_mur,
            "rows": rows, "nb_coupes": nb_coupes,
            "ext": (ext_g, ext_d, ext_b, ext_h),
            "u_lo": u_lo, "v_lo": v_lo,
            "larg": u_hi - u_lo, "haut": v_hi - v_lo,
            "nb_seg": sum([len(sac[k]) for k in sac]),
        }

    def analyser_et_confirmer(wall, courbe, epaisseur, cote, decalage_cm,
                              z_bas, z_haut, solides_mur, mode_regen,
                              gabarits, prefs, type_mur, nom_propose):
        """
        Boucle analyse -> fenetre. Changer de face dans la fenetre relance
        une analyse complete sur l'autre cote, au lieu de renvoyer
        l'utilisateur relancer l'outil.
        Retourne (res, cote, nom_vue, gabarit, decalage_cm) ou None si
        annulation.
        """
        while True:
            res = analyser(wall, courbe, epaisseur, cote, decalage_cm,
                           z_bas, z_haut, solides_mur)
            if res is None:
                MessageBox.Show(
                    u"La face regardee de ce mur n'a pas pu etre isolee "
                    u"dans sa geometrie.\n\n"
                    u"Cela arrive sur un mur empile, un mur-rideau, ou un "
                    u"mur dont la face est fragmentee par des jonctions. "
                    u"Sans ce contour, ni le dessin du mur ni le calcul de "
                    u"ce qu'il masque ne sont possibles.",
                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
                return None

            dev = res["dev"]
            sac = res["sac"]
            ext_g, ext_d, ext_b, ext_h = res["ext"]

            if dev.mode == "arc":
                geom_txt = (
                    u"Rayon d'axe {:.2f} m   |   Rayon de la face vue "
                    u"{:.2f} m   |   Angle balaye {:.1f} deg   |   "
                    u"Longueur developpee {:.2f} m"
                ).format(ft_to_m(dev.R), ft_to_m(dev.R_face),
                         abs(math.degrees(dev.balayage)),
                         ft_to_m(dev.longueur))
                label_a = u"Face exterieure (extrados)"
                label_b = u"Face interieure (intrados)"
            else:
                geom_txt = u"Longueur {:.2f} m".format(ft_to_m(dev.longueur))
                label_a  = u"Face A (cote +normale au trace)"
                label_b  = u"Face B (cote oppose)"

            info_mur = (
                u"Mur : {}   [Id {}]\n{}\n"
                u"Epaisseur {:.0f} cm   |   Hauteur {:.2f} m  "
                u"(de {:+.2f} m a {:+.2f} m)"
            ).format(type_mur, wall.Id.IntegerValue, geom_txt,
                     ft_to_m(epaisseur) * 100.0,
                     ft_to_m(z_haut - z_bas), ft_to_m(z_bas), ft_to_m(z_haut))

            if mode_regen:
                info_face = (
                    u"Regeneration : la face est celle memorisee dans la "
                    u"vue et ne peut pas etre changee ici. Pour l'autre "
                    u"face, creez une nouvelle elevation.")
            else:
                info_face = (
                    u"La developpee est deroulee sur la face choisie : "
                    u"c'est sa longueur qui est portee au dessin. Changer "
                    u"de face relance l'analyse et change la longueur "
                    u"developpee.")
            if dev.mode == "gen":
                info_face += (
                    u"\nCourbe de trace non circulaire : les elements qui "
                    u"depassent les extremites du mur y sont ecrases.")

            info_cadre = (
                u"Cadre : {:.2f} m x {:.2f} m   (marges  gauche {:.2f}  "
                u"droite {:.2f}  bas {:.2f}  haut {:.2f}  m)\n"
                u"Plan de vue {}, fond de vue a "
                u"{:.0f} cm au-dela de la face opposee.\n"
                u"A dessiner : {} segments  (coupe {} | vue {} | cachee {}){}"
            ).format(ft_to_m(res["larg"]), ft_to_m(res["haut"]),
                     ft_to_m(ext_g), ft_to_m(ext_d),
                     ft_to_m(ext_b), ft_to_m(ext_h),
                     (u"sur la face regardee" if decalage_cm < 1e-9 else
                      u"a {:.0f} cm en avant de la face regardee".format(
                          decalage_cm)),
                     ft_to_m(DEPTH_BEYOND_FT) * 100.0,
                     res["nb_seg"], len(sac["coupe"]), len(sac["vue"]),
                     len(sac["cachee"]),
                     u"" if res["nb_seg"] <= MAX_SEGMENTS else
                     u"\nATTENTION : au-dela de {} segments, le dessin sera "
                     u"tronque.".format(MAX_SEGMENTS))

            face_courante = 0 if cote > 0 else 1

            action, face_idx, nom_vue, gabarit, dec = show_confirm_window(
                info_mur, label_a, label_b, face_courante, info_face,
                res["rows"], info_cadre, nom_propose,
                gabarits, prefs.get("dernier_gabarit", u""), mode_regen,
                decalage_cm)
            if action == "annule":
                return None

            # La face et le decalage sont des entrees de l'analyse : les
            # changer oblige a tout refaire avant de pouvoir dessiner.
            change = False
            if not mode_regen and face_idx != face_courante:
                cote   = -cote
                change = True
            if abs(dec - decalage_cm) > 1e-9:
                decalage_cm = dec
                change = True

            if change or action == "recalcul":
                continue

            return res, cote, nom_vue, gabarit, decalage_cm

    # =======================================================================
    # MAIN
    # =======================================================================

    def main():

        # ---------------------------------------------------------------- #
        # 1. Mode : regeneration d'une vue existante, ou creation           #
        # ---------------------------------------------------------------- #
        vue_cible  = None
        mode_regen = False
        cote_force  = None
        wall       = None
        click_pt   = None

        try:
            active = uidoc.ActiveView
        except Exception:
            active = None
        mur_marque, signe_marque = lire_marqueur(active)
        if mur_marque is not None:
            rep = MessageBox.Show(
                u"La vue active est une elevation developpee creee par cet "
                u"outil.\n\nLa regenerer a partir du modele actuel ?\n"
                u"(le contenu dessine sera efface puis redessine)\n\n"
                u"Non = creer une nouvelle elevation sur un autre mur.",
                TOOL_NAME, MessageBoxButton.YesNoCancel,
                MessageBoxImage.Question)
            if rep == MessageBoxResult.Cancel:
                return
            if rep == MessageBoxResult.Yes:
                vue_cible   = active
                mode_regen  = True
                wall        = mur_marque
                cote_force = signe_marque

        if wall is None:
            wall = get_preselected_wall()
            if wall is None:
                wall, click_pt = pick_wall()
                if wall is None:
                    return          # annule par l'utilisateur

        # ---------------------------------------------------------------- #
        # 2. Geometrie de base                                              #
        # ---------------------------------------------------------------- #
        courbe = get_wall_curve(wall)
        if courbe is None:
            MessageBox.Show(
                u"Ce mur n'a pas de courbe de trace exploitable.\n"
                u"Les murs-rideaux et les murs sur esquisse libre ne sont "
                u"pas geres.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        est_droit = isinstance(courbe, Line)
        if est_droit and not mode_regen:
            rep = MessageBox.Show(
                u"Ce mur est DROIT.\n\n"
                u"Pour un mur droit, l'outil \"Elevation sur mur\" cree une "
                u"vraie vue Revit, liee au modele et bien preferable a ce "
                u"dessin 2D fige.\n\n"
                u"Continuer quand meme avec la developpee ?",
                TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Question)
            if rep != MessageBoxResult.Yes:
                return

        z_range = get_wall_z_range(wall)
        if z_range is None:
            MessageBox.Show(u"Impossible de determiner l'altitude du mur.",
                            TOOL_NAME, MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return
        z_bas, z_haut = z_range

        epaisseur = get_wall_thickness(wall)

        # Cote regarde : +1 = face A (extrados pour un arc, cote +normale
        # au trace pour une droite), -1 = face B. Le clic tranche ; en
        # regeneration, c'est le marqueur de la vue qui impose.
        if cote_force is not None:
            cote = cote_force
        elif click_pt is not None:
            cote = cote_du_clic(courbe, click_pt)
        else:
            cote = 1

        solides_mur = collect_solids(wall)
        if not solides_mur:
            MessageBox.Show(
                u"Aucune geometrie solide lisible sur ce mur.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        # ---------------------------------------------------------------- #
        # 3-5. Analyse et confirmation                                      #
        # ---------------------------------------------------------------- #
        type_mur    = elem_name(doc.GetElement(wall.GetTypeId()))
        nom_propose = (elem_name(vue_cible) if mode_regen
                       else next_view_name(doc))
        gabarits    = list_view_templates(doc)
        prefs       = load_prefs()
        try:
            decalage_cm = float(prefs.get("dernier_decalage",
                                          DECALAGE_DEFAUT_CM))
        except Exception:
            decalage_cm = DECALAGE_DEFAUT_CM

        issue = analyser_et_confirmer(
            wall, courbe, epaisseur, cote, decalage_cm,
            z_bas, z_haut, solides_mur,
            mode_regen, gabarits, prefs, type_mur, nom_propose)
        if issue is None:
            return
        res, cote, nom_vue, gabarit, decalage_cm = issue

        dev          = res["dev"]
        sac          = res["sac"]
        contours_mur = res["contours_mur"]
        rows         = res["rows"]
        nb_coupes    = res["nb_coupes"]
        u_lo         = res["u_lo"]
        v_lo         = res["v_lo"]
        larg_cadre   = res["larg"]
        haut_cadre   = res["haut"]

        template_id, template_nom = gabarit
        prefs["dernier_gabarit"]  = template_nom
        prefs["dernier_decalage"] = decalage_cm
        save_prefs(prefs)

        if not nom_vue:
            nom_vue = nom_propose
        if view_name_exists(doc, nom_vue,
                            vue_cible.Id if vue_cible is not None else None):
            MessageBox.Show(
                u"Une vue nommee '{}' existe deja.\n"
                u"Choisissez un autre nom.".format(nom_vue),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        vft = None
        if not mode_regen:
            vft = get_drafting_view_type(doc)
            if vft is None:
                MessageBox.Show(
                    u"Aucun type de vue de dessin trouve dans le projet.",
                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
                return

        # ---------------------------------------------------------------- #
        # 6. Creation / regeneration                                        #
        # ---------------------------------------------------------------- #
        rapport_ko = []
        t = Transaction(doc, u"STR - Elevation mur courbe")
        t.Start()
        try:
            styles = assurer_sous_categories(rapport_ko)

            if mode_regen:
                vue = vue_cible
                vider_vue(vue)
            else:
                vue = ViewDrafting.Create(doc, vft.Id)
                vue.Name = nom_vue

            # Echelle posee AVANT de dessiner : la taille d'un texte est une
            # taille papier, donc son encombrement dans la vue en depend, et
            # les etiquettes de niveaux se placent par rapport a lui.
            gabarit_applique = False
            if template_id.IntegerValue != -1:
                # Un echec ici ne doit pas faire perdre la vue : on retombe
                # sur les reglages par defaut.
                try:
                    vue.ViewTemplateId = template_id
                    gabarit_applique = True
                except Exception:
                    rapport_ko.append(u"gabarit refuse par Revit")

            if not gabarit_applique:
                for prop, valeur in (("Scale",       DEFAUT_ECHELLE),
                                     ("DetailLevel", DEFAUT_DETAIL)):
                    try:
                        setattr(vue, prop, valeur)
                    except Exception:
                        rapport_ko.append(prop)

            poses = {}
            total = 0
            # Ordre volontaire : si le garde-fou MAX_SEGMENTS tronque le
            # dessin, ce sont les lignes cachees qui sautent, jamais le
            # contour du mur ni les sections.
            for cle in ("coupe", "vue", "cachee"):
                segs = dedupe(sac[cle], u_lo, v_lo)
                reste = MAX_SEGMENTS - total
                if reste <= 0:
                    poses[cle] = 0
                    continue
                if len(segs) > reste:
                    segs = segs[:reste]
                n = tracer(vue, segs, styles.get(cle), rapport_ko)
                poses[cle] = n
                total += n

            niveaux = niveaux_du_cadre(v_lo, v_lo + haut_cadre)
            nb_niveaux = poser_niveaux(vue, niveaux, larg_cadre, v_lo,
                                       styles.get("niveau"), rapport_ko)

            txt_annot = (
                u"{}\n"
                u"Mur Id {} — {}\n"
                u"Longueur developpee sur la face vue : {:.3f} m\n"
                u"{}"
                u"Epaisseur : {:.0f} cm   |   Altitudes : {:+.3f} m a {:+.3f} m\n"
                u"Developpee 2D — dessin fige, relancer l'outil pour le "
                u"regenerer."
            ).format(
                nom_vue, wall.Id.IntegerValue, type_mur,
                ft_to_m(dev.longueur),
                (u"Rayon de la face vue : {:.3f} m   |   Angle : {:.2f} deg\n"
                 .format(ft_to_m(dev.R_face),
                         abs(math.degrees(dev.balayage)))
                 if dev.mode == "arc" else u""),
                ft_to_m(epaisseur) * 100.0, ft_to_m(z_bas), ft_to_m(z_haut))
            poser_annotation(vue, txt_annot, rapport_ko)

            # --- Cadrage de la vue de dessin ---
            try:
                pad = 0.10 * M2FT
                bb  = BoundingBoxXYZ()
                bb.Min = XYZ(-pad, -0.80 * M2FT, -1.0)
                bb.Max = XYZ(larg_cadre + pad, haut_cadre + pad, 1.0)
                vue.CropBox       = bb
                vue.CropBoxActive = True
            except Exception:
                rapport_ko.append(u"cadrage de la vue")
            try:
                vue.CropBoxVisible = True
            except Exception:
                pass

            ecrire_marqueur(vue, wall, cote)

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

        try:
            uidoc.ActiveView = vue
        except Exception:
            pass

        if gabarit_applique:
            ligne_reglages = u"Gabarit : {}".format(template_nom)
        else:
            ligne_reglages = (
                u"Gabarit : (aucun)\n"
                u"Reglages : 1:{}, detail Eleve".format(DEFAUT_ECHELLE))
        if rapport_ko:
            ligne_reglages += u"\nNon applique(s) : {}".format(
                u", ".join(sorted(set(rapport_ko))))

        MessageBox.Show(
            u"{}\n\n"
            u"Nom : {}\n"
            u"{}\n"
            u"Cadre : {:.2f} m x {:.2f} m\n"
            u"Longueur developpee : {:.3f} m\n"
            u"Decalage du plan de vue : {:.0f} cm\n"
            u"Lignes posees : coupee {} | vue {} | cachee {}\n"
            u"Niveaux traces : {}\n"
            u"Voisins analyses : {}  (dont {} sectionnes par le plan)".format(
                u"Dessin regenere." if mode_regen
                else u"Elevation developpee creee.",
                nom_vue, ligne_reglages,
                ft_to_m(larg_cadre), ft_to_m(haut_cadre),
                ft_to_m(dev.longueur), decalage_cm,
                poses.get("coupe", 0), poses.get("vue", 0),
                poses.get("cachee", 0), nb_niveaux,
                len(rows), nb_coupes),
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)


    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(
        TOOL_NAME, SCRIPT_VERSION), _ex)
