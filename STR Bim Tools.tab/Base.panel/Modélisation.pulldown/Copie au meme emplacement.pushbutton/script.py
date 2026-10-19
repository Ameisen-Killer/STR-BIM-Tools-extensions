# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.4.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Copie au meme emplacement"
TOOL_LABEL     = u"Copie au même emplacement"   # libelle accentue pour l'UI
# =============================================================================

# --- Hors filet : strict minimum pour pouvoir afficher une erreur fatale ---
import clr
import traceback
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
    clr.AddReference("System")
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")

    import System
    import System.IO
    import System.Text
    import System.Windows.Markup
    from System.Collections.Generic import List
    from System.Windows import Thickness, FontWeights
    from System.Windows.Controls import (DataGridCell, DataGridRow, Button, CheckBox,
                                         StackPanel, Border, ScrollViewer, TextBlock,
                                         Orientation, ScrollBarVisibility)
    from System.Windows.Controls.Primitives import Popup, PlacementMode
    from System.Windows.Input import Key
    from System.Windows.Media import VisualTreeHelper, SolidColorBrush, Color

    from pyrevit import revit, forms

    from Autodesk.Revit.DB import (
        ElementId,
        XYZ,
        Outline,
        Transform,
        Level,
        Group,
        Sketch,
        SketchPlane,
        SpatialElement,
        InternalOrigin,
        BasePoint,
        CurtainGridLine,
        View3D,
        ViewPlan,
        ViewSection,
        PlanViewPlane,
        PlanViewRange,
        CategoryType,
        FilteredElementCollector,
        BoundingBoxIntersectsFilter,
        ElementMulticategoryFilter,
        RevitLinkInstance,
        ElementTransformUtils,
        CopyPasteOptions,
        DuplicateTypeAction,
        IDuplicateTypeNamesHandler,
        FamilyInstance,
        BuiltInCategory,
        BuiltInParameter,
        TransactionGroup,
        Options,
        ViewDetailLevel,
        GeometryInstance,
        Solid,
        SolidUtils,
        DirectShape,
        GeometryObject,
    )
    from Autodesk.Revit.UI.Selection import ObjectType, PickBoxStyle

    doc   = revit.doc
    uidoc = revit.uidoc
    app   = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    TOL         = 1e-4      # tolerance geometrique (pieds)
    PREFILTER_D = 5000.0    # demi-profondeur du prefiltre le long de l'axe de vue (pieds)

    # -----------------------------------------------------------------------
    # Categories ecartees de la selection par fenetre
    # -----------------------------------------------------------------------
    _SKIP_BIC = [
        "OST_Cameras", "OST_SectionBox", "OST_ProjectBasePoint", "OST_SharedBasePoint",
        "OST_IOSModelGroups", "OST_RvtLinks", "OST_Parts",
        "OST_CurtainWallPanels", "OST_CurtainWallMullions",
        "OST_StairsRuns", "OST_StairsLandings", "OST_StairsSupports",
        "OST_RailingHandRail", "OST_RailingTopRail",
        # Pochages / habillage 2D et elements spatiaux : jamais copiables utilement
        "OST_FilledRegion", "OST_MaskingRegion", "OST_DetailComponents",
        "OST_Rooms", "OST_Areas", "OST_MEPSpaces",
        "OST_AreaSchemeLines", "OST_ColorFillLegends", "OST_Matchline",
    ]
    # Reperes : masques par defaut, reintegres via la case a cocher
    _DATUM_BIC = ["OST_Levels", "OST_Grids", "OST_CLines", "OST_VolumeOfInterest"]

    # Classes jamais copiables seules : conteneurs, esquisses, elements spatiaux,
    # points de repere et lignes de quadrillage de mur-rideau.
    SKIP_CLASSES = (Group, RevitLinkInstance, Sketch, SketchPlane, SpatialElement,
                    InternalOrigin, BasePoint, CurtainGridLine)

    # -----------------------------------------------------------------------
    # Helpers generiques
    # -----------------------------------------------------------------------

    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16),
                                             int(h[4:6], 16)))

    def eid_int(eid):
        """Valeur entiere d'un ElementId (Value en 2024+, IntegerValue avant)."""
        try:
            return eid.Value
        except AttributeError:
            return eid.IntegerValue

    def _bic_ids(names):
        out = set()
        for n in names:
            try:
                out.add(eid_int(ElementId(getattr(BuiltInCategory, n))))
            except Exception:
                pass
        return out

    SKIP_CAT_IDS  = _bic_ids(_SKIP_BIC)
    DATUM_CAT_IDS = _bic_ids(_DATUM_BIC)

    def _bic_list(names):
        out = List[BuiltInCategory]()
        for n in names:
            try:
                out.Add(getattr(BuiltInCategory, n))
            except Exception:
                pass
        return out

    DATUM_BICS = _bic_list(_DATUM_BIC)

    def safe_name(el):
        try:
            return el.Name or u""
        except Exception:
            return u""

    def cat_name(el):
        try:
            c = el.Category
            return c.Name if c is not None else u"(sans categorie)"
        except Exception:
            return u"(sans categorie)"

    def type_names(link_doc, el):
        """Retourne (famille, type). Une lecture API = un try."""
        fam = u""
        typ = u""
        try:
            et = link_doc.GetElement(el.GetTypeId())
        except Exception:
            et = None
        if et is None:
            return fam, typ
        try:
            typ = et.Name or u""
        except Exception:
            try:
                p = et.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                typ = (p.AsString() or u"") if p else u""
            except Exception:
                typ = u""
        try:
            fam = et.FamilyName or u""
        except Exception:
            try:
                p = et.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                fam = (p.AsString() or u"") if p else u""
            except Exception:
                fam = u""
        return fam, typ

    def elem_name(el, typ):
        """Nom de l'element (zone de definition, niveau, quadrillage...). Vide s'il
        repete simplement le nom du type, cas de la plupart des elements modeles."""
        nom = safe_name(el)
        return u"" if nom == typ else nom

    def workset_name(link_doc, el, cache):
        """Nom du sous-projet dans la maquette liee. Vide si non partagee."""
        try:
            if not link_doc.IsWorkshared:
                return u""
            wid = el.WorksetId
            k = wid.IntegerValue
        except Exception:
            return u""
        if k in cache:
            return cache[k]
        try:
            nom = link_doc.GetWorksetTable().GetWorkset(wid).Name or u""
        except Exception:
            nom = u""
        cache[k] = nom
        return nom

    def is_in_place(element):
        try:
            return isinstance(element, FamilyInstance) and element.Symbol.Family.IsInPlace
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Geometrie : projection sur le plan ecran de la vue active
    # -----------------------------------------------------------------------

    def _proj_range(points, axis):
        vals = [p.DotProduct(axis) for p in points]
        return min(vals), max(vals)

    def bbox_corners_host(el, link_tf):
        """8 coins de la boite englobante de l'element, en coordonnees hote."""
        try:
            bb = el.get_BoundingBox(None)
        except Exception:
            return None
        if bb is None:
            return None
        tf = link_tf
        try:
            if bb.Transform is not None and not bb.Transform.IsIdentity:
                tf = link_tf.Multiply(bb.Transform)
        except Exception:
            pass
        mn, mx = bb.Min, bb.Max
        pts = []
        for x in (mn.X, mx.X):
            for y in (mn.Y, mx.Y):
                for z in (mn.Z, mx.Z):
                    pts.append(tf.OfPoint(XYZ(x, y, z)))
        return pts

    def datum_corners_host(el, link_tf):
        """
        Coins d'un repere en coordonnees hote. Les zones de definition, niveaux et
        quadrillages n'ont pas toujours de boite englobante exploitable : repli sur
        les extremites de leur geometrie (lignes de la zone, axe du quadrillage).
        """
        pts = bbox_corners_host(el, link_tf)
        if pts:
            return pts
        pts = []
        try:
            opt = Options()
            opt.ComputeReferences = False
            geo = el.get_Geometry(opt)
        except Exception:
            geo = None
        if geo is not None:
            for g in geo:
                try:
                    pts.append(link_tf.OfPoint(g.GetEndPoint(0)))
                    pts.append(link_tf.OfPoint(g.GetEndPoint(1)))
                except Exception:
                    continue
        if not pts:
            try:
                crv = el.Curve      # quadrillage
                pts = [link_tf.OfPoint(crv.GetEndPoint(0)),
                       link_tf.OfPoint(crv.GetEndPoint(1))]
            except Exception:
                pts = []
        return pts or None

    def rect_test(pts, right, up, u0, u1, v0, v1):
        """Retourne (croise_la_fenetre, entierement_dedans)."""
        eu0, eu1 = _proj_range(pts, right)
        ev0, ev1 = _proj_range(pts, up)
        crossing = (eu0 <= u1 + TOL and eu1 >= u0 - TOL and
                    ev0 <= v1 + TOL and ev1 >= v0 - TOL)
        enclosed = (eu0 >= u0 - TOL and eu1 <= u1 + TOL and
                    ev0 >= v0 - TOL and ev1 <= v1 + TOL)
        return crossing, enclosed

    # -----------------------------------------------------------------------
    # Limitation en profondeur selon le type de vue
    # -----------------------------------------------------------------------

    def _plan_plane_z(view, vr, plane):
        """Altitude hote d'un plan de la plage de vue. None = illimite."""
        try:
            lid = vr.GetLevelId(plane)
            off = vr.GetOffset(plane)
        except Exception:
            return None
        try:
            if lid == PlanViewRange.Unlimited:
                return None
        except Exception:
            pass
        lvl = None
        try:
            lvl = doc.GetElement(lid)
        except Exception:
            lvl = None
        if not isinstance(lvl, Level):
            base = None
            try:
                base = view.GenLevel
            except Exception:
                base = None
            if base is None:
                return None
            try:
                lvls = sorted(
                    [l for l in FilteredElementCollector(doc).OfClass(Level)],
                    key=lambda l: l.Elevation)
                if lid == PlanViewRange.LevelBelow:
                    below = [l for l in lvls if l.Elevation < base.Elevation - TOL]
                    lvl = below[-1] if below else base
                elif lid == PlanViewRange.LevelAbove:
                    above = [l for l in lvls if l.Elevation > base.Elevation + TOL]
                    lvl = above[0] if above else base
                else:
                    lvl = base
            except Exception:
                lvl = base
        try:
            return lvl.Elevation + off
        except Exception:
            return None

    def plan_z_range(view):
        """(z_bas, z_haut) en coordonnees hote, None si non applicable."""
        try:
            vr = view.GetViewRange()
        except Exception:
            return None
        top = _plan_plane_z(view, vr, PlanViewPlane.TopClipPlane)
        bot = _plan_plane_z(view, vr, PlanViewPlane.ViewDepthPlane)
        if top is None and bot is None:
            return None
        return (bot, top)

    def _far_clip_active(view):
        """Plan de coupe eloigne actif sur une coupe / elevation."""
        try:
            p = view.get_Parameter(BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING)
            return bool(p) and p.AsInteger() != 0
        except Exception:
            return False

    def make_depth_filter(view, z_range):
        """fn(coins_hote) -> bool, ou None si la vue n'impose pas de profondeur."""
        # Vue 3D avec boite de coupe : test complet dans le repere de la boite
        try:
            if isinstance(view, View3D) and view.IsSectionBoxActive:
                sb  = view.GetSectionBox()
                inv = sb.Transform.Inverse
                mn, mx = sb.Min, sb.Max

                def f_3d(pts):
                    lp = [inv.OfPoint(p) for p in pts]
                    for lo, hi, get in ((mn.X, mx.X, lambda q: q.X),
                                        (mn.Y, mx.Y, lambda q: q.Y),
                                        (mn.Z, mx.Z, lambda q: q.Z)):
                        vals = [get(q) for q in lp]
                        if min(vals) > hi + TOL or max(vals) < lo - TOL:
                            return False
                    return True
                return f_3d
        except Exception:
            pass

        # Vue en plan : plage de vue (plan de coupe haut / profondeur)
        if isinstance(view, ViewPlan) and z_range is not None:
            zlo, zhi = z_range

            def f_plan(pts):
                zs = [p.Z for p in pts]
                if zlo is not None and max(zs) < zlo - TOL:
                    return False
                if zhi is not None and min(zs) > zhi + TOL:
                    return False
                return True
            return f_plan

        # Coupe / elevation : profondeur de la zone de cadrage,
        # uniquement si le plan de coupe eloigne est actif (sinon la vue voit derriere)
        try:
            if isinstance(view, ViewSection) and _far_clip_active(view):
                cb  = view.CropBox
                inv = cb.Transform.Inverse
                zlo, zhi = cb.Min.Z, cb.Max.Z

                def f_sec(pts):
                    zs = [inv.OfPoint(p).Z for p in pts]
                    if max(zs) < zlo - TOL or min(zs) > zhi + TOL:
                        return False
                    return True
                return f_sec
        except Exception:
            pass

        return None

    def build_link_outline(picked, view, link_tf, z_range):
        """Prefiltre : boite englobante du prisme de selection, en coords du lien."""
        right = view.RightDirection
        up    = view.UpDirection
        vd    = view.ViewDirection
        corners = [picked.Min, picked.Max]
        u0, u1 = _proj_range(corners, right)
        v0, v1 = _proj_range(corners, up)
        w = (picked.Min.DotProduct(vd) + picked.Max.DotProduct(vd)) * 0.5

        pts = []
        for u in (u0, u1):
            for v in (v0, v1):
                for d in (w - PREFILTER_D, w + PREFILTER_D):
                    pts.append(right.Multiply(u).Add(up.Multiply(v)).Add(vd.Multiply(d)))

        xs = [p.X for p in pts]
        ys = [p.Y for p in pts]
        zs = [p.Z for p in pts]
        zlo, zhi = min(zs), max(zs)
        if z_range is not None:
            czlo, czhi = z_range
            nlo = max(zlo, czlo - 1.0) if czlo is not None else zlo
            nhi = min(zhi, czhi + 1.0) if czhi is not None else zhi
            if nlo < nhi:
                zlo, zhi = nlo, nhi

        world = []
        for x in (min(xs), max(xs)):
            for y in (min(ys), max(ys)):
                for z in (zlo, zhi):
                    world.append(XYZ(x, y, z))

        inv = link_tf.Inverse
        lp  = [inv.OfPoint(p) for p in world]
        mn  = XYZ(min(p.X for p in lp), min(p.Y for p in lp), min(p.Z for p in lp))
        mx  = XYZ(max(p.X for p in lp), max(p.Y for p in lp), max(p.Z for p in lp))
        return Outline(mn, mx)

    # -----------------------------------------------------------------------
    # Modele de ligne (aucun appel API lourd ici)
    # -----------------------------------------------------------------------

    class ElemRow(object):
        def __init__(self, link_id, link_name, elem_id, categorie, famille, type_nom,
                     enclosed, is_datum, nom=u"", sous_projet=u""):
            self.LinkId     = link_id
            self.LinkName   = link_name
            self.ElemId     = elem_id
            self.Categorie  = categorie
            self.Famille    = famille
            self.TypeNom    = type_nom
            self.Nom        = nom
            self.SousProjet = sous_projet
            self.IdStr      = u"{}".format(eid_int(elem_id))
            self.Enclosed   = enclosed
            self.EncStr     = u"Entier" if enclosed else u"Partiel"
            self.IsDatum    = is_datum
            self.IsSelected = True
            self.SearchKey  = u" ".join([categorie, nom, famille, type_nom, sous_projet,
                                         link_name, self.IdStr]).lower()

        def toggle(self):
            self.IsSelected = not self.IsSelected

        @property
        def key(self):
            return (eid_int(self.LinkId), eid_int(self.ElemId))

    # -----------------------------------------------------------------------
    # Collecte par fenetre
    # -----------------------------------------------------------------------

    def get_link_instances():
        out = []
        for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
            try:
                if li.GetLinkDocument() is None:
                    continue
            except Exception:
                continue
            try:
                if li.IsHidden(doc.ActiveView):
                    continue
            except Exception:
                pass
            out.append(li)
        return out

    def rows_from_box(picked, view):
        """Tous les elements de maquettes liees traverses par la fenetre."""
        right = view.RightDirection
        up    = view.UpDirection
        corners = [picked.Min, picked.Max]
        u0, u1 = _proj_range(corners, right)
        v0, v1 = _proj_range(corners, up)
        if (u1 - u0) < TOL or (v1 - v0) < TOL:
            return []      # simple clic : fenetre degeneree

        z_range   = plan_z_range(view) if isinstance(view, ViewPlan) else None
        depth_ok  = make_depth_filter(view, z_range)

        rows = []
        for li in get_link_instances():
            link_doc  = li.GetLinkDocument()
            link_tf   = li.GetTotalTransform()
            link_name = safe_name(li)
            ws_cache  = {}
            try:
                outline = build_link_outline(picked, view, link_tf, z_range)
                col = (FilteredElementCollector(link_doc)
                       .WhereElementIsNotElementType()
                       .WherePasses(BoundingBoxIntersectsFilter(outline)))
                candidates = list(col)
            except Exception:
                candidates = []
            # Reperes collectes a part : le prefiltre par boite englobante ne les
            # renvoie pas de facon fiable (zones de definition notamment).
            try:
                seen_ids = set(eid_int(c.Id) for c in candidates)
                for d in (FilteredElementCollector(link_doc)
                          .WhereElementIsNotElementType()
                          .WherePasses(ElementMulticategoryFilter(DATUM_BICS))):
                    if eid_int(d.Id) not in seen_ids:
                        candidates.append(d)
            except Exception:
                pass

            for el in candidates:
                try:
                    if isinstance(el, SKIP_CLASSES):
                        continue
                    # Element appartenant a une vue du lien (region de pochage, composant
                    # de detail, lignes de detail...) : leur boite englobante est en
                    # coordonnees modele, donc un prisme de selection 3D les traverse.
                    # Rien de tout cela n'a de sens dans la maquette hote.
                    try:
                        if el.ViewSpecific:
                            continue
                    except Exception:
                        pass
                    try:
                        if el.OwnerViewId != ElementId.InvalidElementId:
                            continue
                    except Exception:
                        pass
                    cat = el.Category
                    if cat is None:
                        continue
                    cid = eid_int(cat.Id)
                    # Les reperes (niveaux, quadrillages, plans de reference, zones de
                    # definition) sont des categories d'annotation pour Revit : on les
                    # garde ici, la case "Inclure les reperes" decide de leur affichage.
                    if cid not in DATUM_CAT_IDS:
                        try:
                            if cat.CategoryType != CategoryType.Model:
                                continue
                        except Exception:
                            continue    # categorie illisible : on ecarte par prudence
                    # Categories internes Revit : <Esquisse>, <Separation de pieces>...
                    # Ces elements appartiennent a un parent, on ne les copie jamais seuls.
                    if (cat.Name or u"").startswith(u"<"):
                        continue
                    # Sous-categorie (Category.Parent renseigne) = sous-partie d'un
                    # element hote : barreaux et supports de garde-corps, lignes de
                    # trajectoire, quadrillage de mur-rideau... Elles sont copiees avec
                    # leur parent, jamais seules. Regle independante de la langue.
                    try:
                        if cat.Parent is not None:
                            continue
                    except Exception:
                        pass
                    if cid in SKIP_CAT_IDS:
                        continue
                    is_datum = cid in DATUM_CAT_IDS
                    if is_datum:
                        # Pas de filtre de profondeur : un repere traverse la vue
                        pts = datum_corners_host(el, link_tf)
                        if not pts:
                            continue
                    else:
                        pts = bbox_corners_host(el, link_tf)
                        if not pts:
                            continue
                        if depth_ok is not None and not depth_ok(pts):
                            continue
                    crossing, enclosed = rect_test(pts, right, up, u0, u1, v0, v1)
                    if not crossing:
                        continue
                    fam, typ = type_names(link_doc, el)
                    rows.append(ElemRow(li.Id, link_name, el.Id, cat.Name, fam, typ,
                                        enclosed, is_datum, elem_name(el, typ),
                                        workset_name(link_doc, el, ws_cache)))
                except Exception:
                    continue
        return rows

    def rows_from_refs(refs):
        """Lignes construites depuis des references choisies au clic."""
        rows = []
        ws_caches = {}
        for ref in refs:
            try:
                li = doc.GetElement(ref.ElementId)
                if not isinstance(li, RevitLinkInstance):
                    continue
                link_doc = li.GetLinkDocument()
                if link_doc is None:
                    continue
                el = link_doc.GetElement(ref.LinkedElementId)
                if el is None:
                    continue
                cat = el.Category
                cid = eid_int(cat.Id) if cat is not None else -1
                fam, typ = type_names(link_doc, el)
                ws_cache = ws_caches.setdefault(eid_int(li.Id), {})
                rows.append(ElemRow(li.Id, safe_name(li), el.Id,
                                    cat.Name if cat is not None else u"(sans categorie)",
                                    fam, typ, True, cid in DATUM_CAT_IDS,
                                    elem_name(el, typ),
                                    workset_name(link_doc, el, ws_cache)))
            except Exception:
                continue
        return rows

    def merge_rows(existing, new_rows):
        seen = set(r.key for r in existing)
        for r in new_rows:
            if r.key in seen:
                continue
            seen.add(r.key)
            existing.append(r)
        existing.sort(key=lambda r: (r.Categorie, r.Famille, r.TypeNom, r.Nom, r.IdStr))
        return existing

    # -----------------------------------------------------------------------
    # Phases
    # -----------------------------------------------------------------------

    def get_phase_by_name(target_doc, phase_name):
        for phase in target_doc.Phases:
            try:
                if phase.Name == phase_name:
                    return phase
            except Exception:
                continue
        return None

    def read_phases(linked_element, linked_doc):
        """(nom_phase_creation, nom_phase_demolition) lus dans la maquette liee."""
        created_name    = None
        demolished_name = None
        try:
            c_id = linked_element.CreatedPhaseId
            if c_id and c_id != ElementId.InvalidElementId:
                phase = linked_doc.GetElement(c_id)
                if phase:
                    created_name = phase.Name
        except Exception:
            pass
        try:
            d_id = linked_element.DemolishedPhaseId
            if d_id and d_id != ElementId.InvalidElementId:
                phase = linked_doc.GetElement(d_id)
                if phase:
                    demolished_name = phase.Name
        except Exception:
            pass
        return created_name, demolished_name

    def apply_phases(new_ids, created_name, demolished_name, missing):
        """Applique les phases aux elements copies (correspondance par nom)."""
        if not created_name:
            return
        host_created    = get_phase_by_name(doc, created_name)
        host_demolished = get_phase_by_name(doc, demolished_name) if demolished_name else None
        if not host_created:
            missing.add(created_name)
        if demolished_name and not host_demolished:
            missing.add(demolished_name)
        if not host_created and not host_demolished:
            return
        with revit.Transaction("Appliquer phases"):
            for eid in new_ids:
                elem = doc.GetElement(eid)
                if not elem:
                    continue
                if host_created:
                    p = elem.get_Parameter(BuiltInParameter.PHASE_CREATED)
                    if p and not p.IsReadOnly:
                        try:
                            p.Set(host_created.Id)
                        except Exception:
                            pass
                if host_demolished:
                    p = elem.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED)
                    if p and not p.IsReadOnly:
                        try:
                            p.Set(host_demolished.Id)
                        except Exception:
                            pass

    # -----------------------------------------------------------------------
    # Copie
    # -----------------------------------------------------------------------

    class _DupTypeHandler(IDuplicateTypeNamesHandler):
        """Evite la boite de dialogue Revit sur les types deja presents."""
        def OnDuplicateTypeNamesFound(self, args):
            return DuplicateTypeAction.UseDestinationTypes

    def make_copy_options():
        opts = CopyPasteOptions()
        try:
            opts.SetDuplicateTypeNamesHandler(_DupTypeHandler())
        except Exception:
            pass
        return opts

    def copy_batch(link_doc, elem_ids, transform, tx_name):
        """CopyElements sur un lot. Retourne la liste d'ids ou None si echec."""
        ids = List[ElementId]()
        for eid in elem_ids:
            ids.Add(eid)
        with revit.Transaction(tx_name):
            new_ids = ElementTransformUtils.CopyElements(
                link_doc, ids, doc, transform, make_copy_options())
        return list(new_ids) if new_ids else []

    def extract_solids(element, link_transform):
        opt = Options()
        opt.ComputeReferences = False
        opt.DetailLevel       = ViewDetailLevel.Fine
        geo_elem = element.get_Geometry(opt)
        if not geo_elem:
            return []
        solids = []
        for geo_obj in geo_elem:
            if isinstance(geo_obj, Solid) and geo_obj.Volume > 1e-9:
                solids.append(SolidUtils.CreateTransformed(geo_obj, link_transform))
            elif isinstance(geo_obj, GeometryInstance):
                for inner in geo_obj.GetInstanceGeometry():
                    if isinstance(inner, Solid) and inner.Volume > 1e-9:
                        solids.append(SolidUtils.CreateTransformed(inner, link_transform))
        return solids

    def copy_as_directshape(linked_element, link_transform):
        """Dernier recours : geometrie seule, non editable. Hors transaction."""
        solids = extract_solids(linked_element, link_transform)
        if not solids:
            return []
        try:
            cat_id = linked_element.Category.Id
        except Exception:
            cat_id = ElementId(BuiltInCategory.OST_GenericModel)
        shape_list = List[GeometryObject]()
        for s in solids:
            shape_list.Add(s)
        ds = DirectShape.CreateElement(doc, cat_id)
        ds.SetShape(shape_list)
        return [ds.Id] if ds and ds.IsValidObject else []

    def run_copy(rows):
        """
        Regroupe par (lien, in-situ, phase creation, phase demolition) puis copie.
        Retourne (new_ids, stats, echecs, phases_manquantes).
        """
        groups  = {}
        failed  = []       # (row, motif)
        for r in rows:
            try:
                li = doc.GetElement(r.LinkId)
                link_doc = li.GetLinkDocument() if li else None
                if link_doc is None:
                    failed.append((r, u"maquette liee inaccessible"))
                    continue
                el = link_doc.GetElement(r.ElemId)
                if el is None:
                    failed.append((r, u"element introuvable dans le lien"))
                    continue
                cph, dph = read_phases(el, link_doc)
                key = (eid_int(r.LinkId), is_in_place(el), cph, dph)
                g = groups.get(key)
                if g is None:
                    g = {"link": li, "doc": link_doc, "inplace": is_in_place(el),
                         "created": cph, "demolished": dph, "ids": [], "rows": []}
                    groups[key] = g
                g["ids"].append(r.ElemId)
                g["rows"].append(r)
            except Exception:
                failed.append((r, u"lecture impossible"))

        all_new  = []
        missing  = set()
        n_native = 0
        n_ds     = 0
        ds_pending = []    # (row, link_instance)

        tg = TransactionGroup(doc, "STR - Copier depuis maquette liee")
        tg.Start()
        try:
            for key in sorted(groups.keys(), key=lambda k: (k[0], k[1])):
                g = groups[key]
                link_tf = (Transform.Identity if g["inplace"]
                           else g["link"].GetTotalTransform())
                tx_name = ("Copier famille in-situ" if g["inplace"]
                           else "Copier elements depuis maquette liee")

                new_ids = None
                try:
                    new_ids = copy_batch(g["doc"], g["ids"], link_tf, tx_name)
                except Exception:
                    new_ids = None

                # Certains elements refusent la transformation du lien
                if not new_ids and not g["inplace"]:
                    try:
                        new_ids = copy_batch(g["doc"], g["ids"], Transform.Identity, tx_name)
                    except Exception:
                        new_ids = None

                # Lot en echec (exception ou retour vide) : on isole element par element
                if not new_ids:
                    new_ids = []
                    for r in g["rows"]:
                        one = None
                        try:
                            one = copy_batch(g["doc"], [r.ElemId], link_tf, tx_name)
                        except Exception:
                            one = None
                        if one is None and not g["inplace"]:
                            try:
                                one = copy_batch(g["doc"], [r.ElemId],
                                                 Transform.Identity, tx_name)
                            except Exception:
                                one = None
                        if one:
                            new_ids.extend(one)
                        else:
                            ds_pending.append((r, g["link"]))

                if new_ids:
                    n_native += len(new_ids)
                    all_new.extend(new_ids)
                    try:
                        apply_phases(new_ids, g["created"], g["demolished"], missing)
                    except Exception:
                        pass

            # Repli DirectShape pour les elements non copiables
            if ds_pending:
                use_ds = forms.alert(
                    u"{} element(s) n'ont pas pu etre copies via l'API Revit.\n\n"
                    u"Voulez-vous extraire leur geometrie en DirectShape ?\n"
                    u"(non editable, mais positionne correctement)".format(len(ds_pending)),
                    title=u"Copie impossible", yes=True, no=True)
                if use_ds:
                    with revit.Transaction("Copier -> DirectShape"):
                        for r, li in ds_pending:
                            try:
                                link_doc = li.GetLinkDocument()
                                el = link_doc.GetElement(r.ElemId)
                                ids = copy_as_directshape(el, li.GetTotalTransform())
                                if ids:
                                    all_new.extend(ids)
                                    n_ds += len(ids)
                                else:
                                    failed.append((r, u"aucune geometrie solide"))
                            except Exception:
                                failed.append((r, u"DirectShape impossible"))
                else:
                    for r, li in ds_pending:
                        failed.append((r, u"copie API impossible"))

            tg.Assimilate()
        except Exception:
            try:
                tg.RollBack()
            except Exception:
                pass
            raise

        return all_new, {"natif": n_native, "directshape": n_ds}, failed, missing

    # -----------------------------------------------------------------------
    # Fenetre de revue (XAML en ASCII strict)
    # -----------------------------------------------------------------------

    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1240" Height="620" MinWidth="900" MinHeight="460"
    WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
      <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
    </Border>

    <Border Grid.Row="1" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="8,7">
      <StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
          <TextBlock x:Name="lbl_filtre" VerticalAlignment="Center" FontSize="11"
                     Margin="0,0,6,0"/>
          <TextBox x:Name="tb_filter" Width="230" Height="24" FontSize="11"
                   VerticalContentAlignment="Center"/>
          <Button x:Name="btn_cats" Height="24" MinWidth="180" FontSize="11"
                  Margin="10,0,0,0" Padding="8,0" Background="White"
                  BorderBrush="#C0D0E0" BorderThickness="1"
                  HorizontalContentAlignment="Left"/>
          <Button x:Name="btn_types" Height="24" MinWidth="180" FontSize="11"
                  Margin="6,0,0,0" Padding="8,0" Background="White"
                  BorderBrush="#C0D0E0" BorderThickness="1"
                  HorizontalContentAlignment="Left"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
          <CheckBox x:Name="cb_enclosed" VerticalAlignment="Center" FontSize="11"/>
          <CheckBox x:Name="cb_datum" VerticalAlignment="Center" FontSize="11"
                    Margin="20,0,0,0"/>
        </StackPanel>
        <Grid>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
            <Button x:Name="btn_all" Height="24" FontSize="11" Padding="8,0"
                    Margin="0,0,6,0" Background="#2ECC71" Foreground="White"
                    BorderThickness="0"/>
            <Button x:Name="btn_none" Height="24" FontSize="11" Padding="8,0"
                    Margin="0,0,6,0" Background="#E74C3C" Foreground="White"
                    BorderThickness="0"/>
            <Button x:Name="btn_sel_check" Height="24" FontSize="11" Padding="8,0"
                    Margin="14,0,6,0" Background="#E0E0E0" BorderThickness="0"/>
            <Button x:Name="btn_sel_uncheck" Height="24" FontSize="11" Padding="8,0"
                    Margin="0,0,6,0" Background="#E0E0E0" BorderThickness="0"/>
          </StackPanel>
          <TextBlock x:Name="lbl_count" HorizontalAlignment="Right"
                     VerticalAlignment="Center" FontSize="11" FontWeight="SemiBold"
                     Foreground="#2F6496"/>
        </Grid>
      </StackPanel>
    </Border>

    <DataGrid x:Name="dg_main" Grid.Row="2" Margin="8,8,8,4"
              AutoGenerateColumns="False" IsReadOnly="True"
              SelectionMode="Extended" SelectionUnit="FullRow"
              AlternatingRowBackground="#E8F0FA" RowBackground="White"
              GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
              HeadersVisibility="Column" CanUserResizeColumns="True"
              CanUserSortColumns="True" FontSize="12">
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,3"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <DataGridCheckBoxColumn x:Name="col_chk" Binding="{Binding IsSelected}"
                                Width="42" SortMemberPath="IsSelected"/>
        <DataGridTextColumn x:Name="col_cat" Binding="{Binding Categorie}" Width="160"/>
        <DataGridTextColumn x:Name="col_nom" Binding="{Binding Nom}" Width="130"/>
        <DataGridTextColumn x:Name="col_fam" Binding="{Binding Famille}" Width="180"/>
        <DataGridTextColumn x:Name="col_typ" Binding="{Binding TypeNom}" Width="*"/>
        <DataGridTextColumn x:Name="col_wks" Binding="{Binding SousProjet}" Width="170"/>
        <DataGridTextColumn x:Name="col_lnk" Binding="{Binding LinkName}" Width="180"/>
        <DataGridTextColumn x:Name="col_enc" Binding="{Binding EncStr}" Width="105"/>
        <DataGridTextColumn x:Name="col_id"  Binding="{Binding IdStr}" Width="85"/>
      </DataGrid.Columns>
    </DataGrid>

    <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_add_box" Width="120" Height="28" Margin="4,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0"/>
          <Button x:Name="btn_add_click" Width="120" Height="28" Margin="4,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0"/>
          <Button x:Name="btn_cancel" Width="90" Height="28" Margin="12,0,0,0"
                  Background="#E74C3C" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0"/>
          <Button x:Name="btn_copy" Width="120" Height="28" Margin="4,0,0,0"
                  Background="#2ECC71" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

    def show_review(all_rows):
        """Retourne (action, lignes_retenues). action : copy / add_box / add_click / cancel."""
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)

        window.Title = TOOL_LABEL
        window.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(
            TOOL_LABEL, app.VersionNumber)
        window.FindName("lbl_footer").Text = _FOOTER
        window.FindName("lbl_filtre").Text = u"Filtre :"

        tb_filter   = window.FindName("tb_filter")
        cb_enclosed = window.FindName("cb_enclosed")
        cb_datum    = window.FindName("cb_datum")
        dg          = window.FindName("dg_main")
        lbl_count   = window.FindName("lbl_count")
        btn_cats    = window.FindName("btn_cats")
        btn_types   = window.FindName("btn_types")

        cb_enclosed.Content = u"Uniquement les éléments entièrement dans la fenêtre"
        n_datum = len([r for r in all_rows if r.IsDatum])
        cb_datum.Content    = (u"Inclure niveaux / quadrillages / plans de référence / "
                               u"zones de définition  ({} trouvé(s))".format(n_datum))

        for name, txt in (("btn_all",          u"Tout cocher"),
                          ("btn_none",         u"Tout décocher"),
                          ("btn_sel_check",    u"Cocher la sélection"),
                          ("btn_sel_uncheck",  u"Décocher la sélection"),
                          ("btn_add_box",      u"+ Fenêtre"),
                          ("btn_add_click",    u"+ Clics"),
                          ("btn_cancel",       u"Annuler"),
                          ("btn_copy",         u"Copier")):
            window.FindName(name).Content = txt

        for name, hdr in (("col_chk", u""),
                          ("col_cat", u"Catégorie"),
                          ("col_nom", u"Nom"),
                          ("col_wks", u"Sous-projet"),
                          ("col_fam", u"Famille"),
                          ("col_typ", u"Type"),
                          ("col_lnk", u"Maquette liée"),
                          ("col_enc", u"Dans la fenêtre"),
                          ("col_id",  u"Id lien")):
            col = window.FindName(name)
            if col is not None:
                col.Header = hdr

        _hint = (u"Sélectionnez plusieurs lignes (Maj ou Ctrl + clic), puis cliquez "
                 u"une coche ou appuyez sur la barre d'espace : toute la sélection bascule.")
        window.FindName("dg_main").ToolTip         = _hint
        window.FindName("btn_sel_check").ToolTip   = _hint
        window.FindName("btn_sel_uncheck").ToolTip = _hint

        # "off" = libelles explicitement decoches. Vide = aucun filtre, et un libelle
        # apparu apres coup (ajout d'une fenetre) est visible par defaut.
        state = {"action": "cancel", "visible": [], "busy": False,
                 "off": {"cat": set(), "typ": set()},
                 "avail": {"cat": [], "typ": []},
                 "closed": {"cat": None, "typ": None}}

        _GETTER = {"cat": lambda r: r.Categorie or u"(sans catégorie)",
                   "typ": lambda r: r.TypeNom or u"(sans type)"}

        def update_counter():
            vis = state["visible"]
            n   = len([r for r in vis if r.IsSelected])
            lbl_count.Text = u"{} coché(s) sur {} affiché(s)  |  {} trouvé(s)".format(
                n, len(vis), len(all_rows))

        def base_rows():
            """Lignes retenues par les cases a cocher, avant filtres texte / listes."""
            inc_dat  = bool(cb_datum.IsChecked)
            only_enc = bool(cb_enclosed.IsChecked)
            out = []
            for r in all_rows:
                if r.IsDatum and not inc_dat:
                    continue
                if only_enc and not r.Enclosed:
                    continue
                out.append(r)
            return out

        def label_counts(key, rows):
            counts = {}
            get = _GETTER[key]
            for r in rows:
                lbl = get(r)
                counts[lbl] = counts.get(lbl, 0) + 1
            return counts

        def update_caption(key, btn, mot, tous):
            labels = state["avail"][key]
            off    = state["off"][key]
            n_on   = len([l for l in labels if l not in off])
            if not labels or n_on == len(labels):
                btn.Content = u"{} : {}".format(mot, tous)
            else:
                btn.Content = u"{} : {} / {}".format(mot, n_on, len(labels))

        def refresh(*args):
            if state["busy"]:
                return
            txt  = (tb_filter.Text or u"").strip().lower()
            rows = base_rows()

            state["avail"]["cat"] = sorted(label_counts("cat", rows).keys())
            state["avail"]["typ"] = sorted(label_counts("typ", rows).keys())

            off_cat = state["off"]["cat"]
            off_typ = state["off"]["typ"]
            vis = []
            for r in rows:
                if _GETTER["cat"](r) in off_cat:
                    continue
                if _GETTER["typ"](r) in off_typ:
                    continue
                if txt and txt not in r.SearchKey:
                    continue
                vis.append(r)

            state["visible"] = vis
            state["busy"] = True
            dg.ItemsSource = None
            dg.ItemsSource = vis
            state["busy"] = False
            update_caption("cat", btn_cats,  u"Catégories", u"toutes")
            update_caption("typ", btn_types, u"Types",      u"tous")
            update_counter()

        def _popup_btn(text, handler):
            b = Button()
            b.Content         = text
            b.Height          = 22
            b.FontSize        = 11
            b.Padding         = Thickness(8, 0, 8, 0)
            b.Margin          = Thickness(0, 0, 6, 0)
            b.Background      = hex_brush("#E0E0E0")
            b.BorderThickness = Thickness(0)
            b.Click          += handler
            return b

        def make_filter_popup(key, btn, titre):
            """Liste deroulante a cases cochables, reconstruite a chaque ouverture."""
            popup             = Popup()
            popup.StaysOpen   = False
            popup.Placement   = PlacementMode.Bottom
            popup.PlacementTarget = btn

            def set_all_labels(off):
                if off:
                    state["off"][key] = set(state["avail"][key])
                else:
                    state["off"][key] = set()
                refresh()
                build()

            def build():
                rows   = base_rows()
                counts = label_counts(key, rows)
                labels = sorted(counts.keys())
                state["avail"][key] = labels
                off = state["off"][key]

                outer                 = Border()
                outer.Background      = hex_brush("#FFFFFF")
                outer.BorderBrush     = hex_brush("#C0D0E0")
                outer.BorderThickness = Thickness(1)
                outer.Padding         = Thickness(8, 6, 8, 8)
                try:
                    outer.MinWidth = max(200.0, btn.ActualWidth)
                except Exception:
                    outer.MinWidth = 200.0

                sp = StackPanel()
                outer.Child = sp

                hdr            = TextBlock()
                hdr.Text       = titre
                hdr.FontSize   = 11
                hdr.FontWeight = FontWeights.SemiBold
                hdr.Foreground = hex_brush("#2F6496")
                hdr.Margin     = Thickness(0, 0, 0, 5)
                sp.Children.Add(hdr)

                bar             = StackPanel()
                bar.Orientation = Orientation.Horizontal
                bar.Margin      = Thickness(0, 0, 0, 6)
                bar.Children.Add(_popup_btn(u"Tout",   lambda s, e: set_all_labels(False)))
                bar.Children.Add(_popup_btn(u"Aucun",  lambda s, e: set_all_labels(True)))
                sp.Children.Add(bar)

                sv                          = ScrollViewer()
                sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
                sv.MaxHeight                = 320
                inner                       = StackPanel()
                sv.Content                  = inner
                sp.Children.Add(sv)

                def make_handler(lbl):
                    def h(s, e):
                        if state["busy"]:
                            return
                        if s.IsChecked:
                            state["off"][key].discard(lbl)
                        else:
                            state["off"][key].add(lbl)
                        refresh()
                    return h

                for lbl in labels:
                    cb           = CheckBox()
                    cb.Content   = u"{}  ({})".format(lbl, counts[lbl])
                    cb.IsChecked = (lbl not in off)
                    cb.FontSize  = 11
                    cb.Margin    = Thickness(0, 3, 0, 3)
                    handler      = make_handler(lbl)
                    cb.Checked   += handler
                    cb.Unchecked += handler
                    inner.Children.Add(cb)

                if not labels:
                    empty          = TextBlock()
                    empty.Text     = u"(aucun élément)"
                    empty.FontSize = 11
                    empty.Foreground = hex_brush("#888888")
                    inner.Children.Add(empty)

                popup.Child = outer

            def on_closed(s, e):
                state["closed"][key] = System.DateTime.Now

            def on_click(s, e):
                # Avec StaysOpen=False, le clic sur le bouton ferme d'abord le popup :
                # sans ce garde-fou il se rouvrirait aussitot.
                last = state["closed"][key]
                if last is not None:
                    try:
                        if (System.DateTime.Now - last).TotalMilliseconds < 250:
                            return
                    except Exception:
                        pass
                build()
                popup.IsOpen = True

            popup.Closed += on_closed
            btn.Click    += on_click
            return popup

        # Conserver une reference : un Popup non reference peut etre ramasse par le GC
        state["popups"] = [
            make_filter_popup("cat", btn_cats,  u"Filtrer par catégorie"),
            make_filter_popup("typ", btn_types, u"Filtrer par type"),
        ]

        def selected_rows():
            try:
                return [r for r in dg.SelectedItems]
            except Exception:
                return []

        def redraw():
            """Re-bind pour rafraichir les coches, en conservant les lignes surlignees."""
            keep = selected_rows()
            state["busy"] = True
            try:
                src = dg.ItemsSource
                dg.ItemsSource = None
                dg.ItemsSource = src
                dg.SelectedItems.Clear()
                for r in keep:
                    dg.SelectedItems.Add(r)
            finally:
                state["busy"] = False
            update_counter()

        def toggle_rows(clicked):
            """Bascule la ligne cliquee, ou toute la selection si elle en fait partie."""
            sel = selected_rows()
            if clicked is not None and clicked in sel and len(sel) > 1:
                new_val = not clicked.IsSelected
                for r in sel:
                    r.IsSelected = new_val
            elif clicked is not None:
                clicked.toggle()
            elif sel:
                new_val = not sel[0].IsSelected
                for r in sel:
                    r.IsSelected = new_val
            else:
                return
            redraw()

        def _visual_ancestor(node, target_type):
            guard = 0
            while node is not None and guard < 40:
                if isinstance(node, target_type):
                    return node
                try:
                    node = VisualTreeHelper.GetParent(node)
                except Exception:
                    return None
                guard += 1
            return None

        def on_preview_click(s, e):
            """Clic dans la colonne des coches : bascule sans casser la selection."""
            if state["busy"]:
                return
            try:
                cell = _visual_ancestor(e.OriginalSource, DataGridCell)
                if cell is None or cell.Column is None:
                    return
                if cell.Column.DisplayIndex != 0:
                    return
                row = _visual_ancestor(cell, DataGridRow)
                item = row.Item if row is not None else None
                if item is None:
                    return
                toggle_rows(item)
                e.Handled = True      # la selection multiple reste intacte
            except Exception:
                pass

        def on_key_down(s, e):
            """Barre d'espace : bascule toutes les lignes surlignees."""
            if state["busy"]:
                return
            try:
                if e.Key == Key.Space:
                    toggle_rows(None)
                    e.Handled = True
            except Exception:
                pass

        def set_all(value):
            for r in state["visible"]:
                r.IsSelected = value
            redraw()

        def set_selection(value):
            for r in selected_rows():
                r.IsSelected = value
            redraw()

        def close_with(action):
            state["action"] = action
            window.Close()

        dg.PreviewMouseLeftButtonDown += on_preview_click
        dg.PreviewKeyDown            += on_key_down
        tb_filter.TextChanged += refresh
        cb_enclosed.Checked   += refresh
        cb_enclosed.Unchecked += refresh
        cb_datum.Checked      += refresh
        cb_datum.Unchecked    += refresh
        window.FindName("btn_all").Click         += lambda s, e: set_all(True)
        window.FindName("btn_none").Click        += lambda s, e: set_all(False)
        window.FindName("btn_sel_check").Click   += lambda s, e: set_selection(True)
        window.FindName("btn_sel_uncheck").Click += lambda s, e: set_selection(False)
        window.FindName("btn_add_box").Click     += lambda s, e: close_with("add_box")
        window.FindName("btn_add_click").Click   += lambda s, e: close_with("add_click")
        window.FindName("btn_cancel").Click      += lambda s, e: close_with("cancel")
        window.FindName("btn_copy").Click        += lambda s, e: close_with("copy")

        refresh()
        window.ShowDialog()

        retenues = [r for r in state["visible"] if r.IsSelected]
        return state["action"], retenues

    # -----------------------------------------------------------------------
    # Selections Revit
    # -----------------------------------------------------------------------

    def _visible_diagonal(view):
        """Diagonale de la zone visible a l'ecran, en pieds. None si indisponible."""
        try:
            for uv in uidoc.GetOpenUIViews():
                if uv.ViewId == view.Id:
                    c = uv.GetZoomCorners()
                    return (c[1] - c[0]).GetLength()
        except Exception:
            pass
        return None

    def is_click_not_drag(picked, view):
        """
        Vrai si l'utilisateur a clique au lieu de glisser. Le seuil est pris
        relativement a la zone visible : un vrai trace le depasse toujours,
        le tremblement d'un clic jamais, quel que soit le niveau de zoom.
        """
        right = view.RightDirection
        up    = view.UpDirection
        corners = [picked.Min, picked.Max]
        u0, u1 = _proj_range(corners, right)
        v0, v1 = _proj_range(corners, up)
        diag = _visible_diagonal(view)
        seuil = (diag * 0.005) if diag else TOL
        return (u1 - u0) < seuil and (v1 - v0) < seuil

    def pick_box(view):
        """Retourne (statut, lignes). statut : cancel / click / box."""
        try:
            picked = uidoc.Selection.PickBox(
                PickBoxStyle.Crossing,
                u"Tracez une fenêtre sur les éléments de la maquette liée, "
                u"ou cliquez sans glisser pour sélectionner élément par élément "
                u"(Échap pour annuler).")
        except Exception:
            return "cancel", None
        if picked is None:
            return "cancel", None
        if is_click_not_drag(picked, view):
            return "click", None
        return "box", rows_from_box(picked, view)

    def pick_clicks():
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.LinkedElement,
                u"Cliquez les éléments dans la maquette liée (Tab pour cycler), "
                u"puis Terminer (Échap pour annuler).")
        except Exception:
            return None
        if refs is None:
            return None
        return rows_from_refs(refs)

    # -----------------------------------------------------------------------
    # Point d'entree
    # -----------------------------------------------------------------------

    def run():
        view = doc.ActiveView
        try:
            view.RightDirection
        except Exception:
            forms.alert(u"Placez-vous dans une vue graphique (plan, coupe, élévation ou 3D).",
                        title=TOOL_LABEL)
            return
        perspective = False
        try:
            perspective = isinstance(view, View3D) and view.IsPerspective
        except Exception:
            pass

        if not get_link_instances():
            forms.alert(u"Aucune maquette liée chargée et visible dans cette vue.",
                        title=TOOL_LABEL)
            return

        if perspective:
            # La projection sur le plan ecran suppose une vue orthogonale :
            # en perspective seule la selection par clics est fiable.
            forms.alert(u"Vue en perspective : la sélection par fenêtre n'y est pas "
                        u"fiable.\nPassage en sélection par clics.",
                        title=TOOL_LABEL)
            statut, all_rows = "click", None
        else:
            statut, all_rows = pick_box(view)

        if statut == "cancel":
            return
        if statut == "click":
            # Clic sans glisser : bascule en selection element par element
            all_rows = pick_clicks()
            if all_rows is None:
                return
            if not all_rows:
                forms.alert(u"Aucun élément de maquette liée sélectionné.",
                            title=TOOL_LABEL)
                return
        elif not all_rows:
            forms.alert(u"Aucun élément de maquette liée dans cette fenêtre.",
                        title=TOOL_LABEL)
            return
        all_rows.sort(key=lambda r: (r.Categorie, r.Famille, r.TypeNom, r.Nom, r.IdStr))

        # Boucle de revue : ajout par fenetre / par clics jusqu'a validation
        while True:
            action, retenues = show_review(all_rows)
            if action == "cancel":
                return
            if action == "add_box":
                if perspective:
                    extra = pick_clicks()
                else:
                    st, extra = pick_box(view)
                    if st == "click":
                        extra = pick_clicks()  # meme repli qu'au demarrage
                if extra:
                    merge_rows(all_rows, extra)
                continue
            if action == "add_click":
                extra = pick_clicks()
                if extra:
                    merge_rows(all_rows, extra)
                continue
            if not retenues:
                forms.alert(u"Aucun élément coché.", title=TOOL_LABEL)
                continue
            break

        # Copie
        try:
            new_ids, stats, failed, missing = run_copy(retenues)
        except Exception:
            forms.alert(u"Erreur pendant la copie :\n\n{}".format(traceback.format_exc()),
                        title=u"Erreur")
            return

        if not new_ids:
            forms.alert(u"Aucun élément copié.", title=u"Aucun élément copié")
            return

        try:
            sel = List[ElementId]()
            for eid in new_ids:
                sel.Add(eid)
            uidoc.Selection.SetElementIds(sel)
        except Exception:
            pass

        msg = [u"{} élément(s) demandé(s), {} élément(s) créé(s).".format(
            len(retenues), len(new_ids))]
        msg.append(u"- copie native : {}".format(stats["natif"]))
        if stats["directshape"]:
            msg.append(u"- DirectShape (géométrie seule) : {}".format(stats["directshape"]))
        if missing:
            msg.append(u"")
            msg.append(u"Phases absentes de la maquette hôte : {}".format(
                u", ".join(sorted(missing))))
        if failed:
            msg.append(u"")
            msg.append(u"{} élément(s) non copié(s) :".format(len(failed)))
            for r, why in failed[:15]:
                msg.append(u"  - {} / {} (Id {}) : {}".format(
                    r.Categorie, r.Nom or r.TypeNom, r.IdStr, why))
            if len(failed) > 15:
                msg.append(u"  ... et {} autre(s).".format(len(failed) - 15))

        forms.alert(u"\n".join(msg), title=u"Copie terminée")

    run()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
