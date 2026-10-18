# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Quantification Platines"
# =============================================================================

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
    import os, io, json, time, datetime

    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase");           clr.AddReference("System.Windows.Forms")
    import System, System.IO, System.Diagnostics
    import System.Windows.Forms as WinForms
    import System.Windows as SW
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode,
                                FontWeights, TextWrapping, Clipboard)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, RowDefinition,
                                         ColumnDefinition, ScrollViewer, ScrollBarVisibility,
                                         DataGridLength, DataGridLengthUnitType, DataGridRow,
                                         Orientation, DataGridHeadersVisibility,
                                         DataGridGridLinesVisibility, DataGridSelectionMode,
                                         TextBox, CheckBox, ProgressBar)
    from System.Windows.Controls.Primitives import DataGridColumnHeader
    from System.Windows.Threading import DispatcherPriority
    from System.Windows.Media import SolidColorBrush, Color, FontFamily
    from System.Windows.Data import Binding
    from System.Collections.ObjectModel import ObservableCollection
    from System.Collections.Generic import List as NetList

    from Autodesk.Revit.DB import (
        FilteredElementCollector, BuiltInCategory, BuiltInParameter,
        UnitUtils, UnitTypeId, ElementId, Options, ViewDetailLevel,
        Solid, PlanarFace, GeometryInstance, UV, View3D,
        FamilyInstance, DirectShape, RevitLinkInstance,
    )

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app   = __revit__.Application

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")
    _FOOTER     = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    FT_TO_MM          = 304.8
    DENSITY_FT3_TO_M3 = 35.3147          # valide acier : 222.287 * 35.3147 = 7850 kg/m3
    DEFAULT_KEYWORDS  = u"platine"
    ACIER_DEFAUT      = 7850.0           # kg/m3 si materiau acier sans asset structurel
    ACIER_HINTS       = [u"acier", u"steel", u"s235", u"s275", u"s355", u"inox", u"stahl"]

    # Criteres de reconnaissance d'un solide "plat" extrait d'un assemblage.
    # Ecarte les boulons (petite section), les soudures et les profiles.
    EP_MAX_MM   = 80.0     # epaisseur maximale d'une platine
    DIM_MIN_MM  = 60.0     # plus petite dimension de la face principale
    RATIO_MAX   = 0.5      # epaisseur / largeur

    PROV_PLAQUE = u"Plaque d'assemblage"
    PROV_ASSEMB = u"Assemblage (geometrie)"
    PROV_FAM    = u"Famille"

    # =========================================================================
    # Helpers UI
    # =========================================================================
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    def rgb(r, g, b):
        return SolidColorBrush(Color.FromRgb(r, g, b))

    def _rd(h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto)
        return rd

    def _footer_btn(text, color, width, handler):
        b = Button()
        b.Content = text; b.Width = width; b.Height = 28
        b.Background = hex_brush(color); b.Foreground = hex_brush("#FFFFFF")
        b.FontWeight = FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler
        return b

    def _make_footer(version):
        brd = Border()
        brd.BorderThickness = Thickness(0, 1, 0, 0)
        brd.BorderBrush = hex_brush("#C0D0E0")
        brd.Background  = hex_brush("#F5F5F5")
        brd.Padding = Thickness(0, 6, 0, 6)
        g = Grid()
        lbl = TextBlock()
        lbl.Text = _FOOTER
        lbl.FontSize = 10; lbl.Foreground = hex_brush("#888888")
        lbl.VerticalAlignment = VerticalAlignment.Center
        lbl.Margin = Thickness(10, 0, 0, 0)
        g.Children.Add(lbl)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Right
        sp.Margin = Thickness(0, 0, 10, 0)
        brd.Child = g
        return brd, sp, g

    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(data):
        try:
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def pick_folder():
        try:
            prefs = _load_prefs()
            dlg = WinForms.FolderBrowserDialog()
            dlg.Description = u"Choisir le dossier d'export"
            last = prefs.get("last_export_folder", u"")
            if last and os.path.isdir(last):
                dlg.SelectedPath = last
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                folder = dlg.SelectedPath
                prefs["last_export_folder"] = folder
                _save_prefs(prefs)
                return folder
        except Exception:
            pass
        return None

    def make_progress_window(title):
        w = Window()
        w.Title = title; w.Width = 420; w.Height = 140
        w.ResizeMode = ResizeMode.NoResize
        w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        w.Background = hex_brush("#FFFFFF")
        sp = StackPanel(); sp.Margin = Thickness(16, 14, 16, 10); w.Content = sp
        lbl = TextBlock(); lbl.FontSize = 11; lbl.Margin = Thickness(0, 0, 0, 8)
        sp.Children.Add(lbl)
        pb = ProgressBar(); pb.Height = 16; pb.Minimum = 0; pb.Maximum = 100
        pb.IsIndeterminate = True
        sp.Children.Add(pb)
        ftr = TextBlock(); ftr.Text = _FOOTER
        ftr.FontSize = 9; ftr.Foreground = hex_brush("#888888")
        ftr.Margin = Thickness(0, 8, 0, 0)
        ftr.HorizontalAlignment = HorizontalAlignment.Right
        sp.Children.Add(ftr)
        return w, lbl, pb

    def do_events(dispatcher):
        try:
            dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
        except Exception:
            pass

    # =========================================================================
    # Helpers metier
    # =========================================================================
    _ACCENTS = [(u"é", u"e"), (u"è", u"e"), (u"ê", u"e"), (u"ë", u"e"),
                (u"à", u"a"), (u"â", u"a"), (u"ä", u"a"),
                (u"î", u"i"), (u"ï", u"i"),
                (u"ô", u"o"), (u"ö", u"o"),
                (u"û", u"u"), (u"ù", u"u"), (u"ü", u"u"),
                (u"ç", u"c")]

    def _norm(s):
        s = (s or u"").lower()
        for a, b in _ACCENTS:
            s = s.replace(a, b)
        return s

    def parse_keywords(txt):
        raw = (txt or u"").replace(u",", u";").split(u";")
        return [_norm(k.strip()) for k in raw if k.strip()]

    def to_m3(val):
        try:
            return float(UnitUtils.ConvertFromInternalUnits(val, UnitTypeId.CubicMeters))
        except Exception:
            return float(val) * 0.0283168466

    def fmt_mm(v):
        try:
            return u"{:.1f}".format(float(v))
        except Exception:
            return u"—"

    def fmt_kg(v):
        if v is None or v <= 0:
            return u"—"
        return u"{:,.1f}".format(float(v)).replace(u",", u"'")

    _TYPE_NAME_CACHE = {}

    def get_family_type_names(el, d):
        """(famille, type) — resultat mis en cache par identifiant de type."""
        try:
            tid = el.GetTypeId()
            key = (d.Title, tid.IntegerValue)
        except Exception:
            tid, key = None, None
        if key is not None and key in _TYPE_NAME_CACHE:
            return _TYPE_NAME_CACHE[key]

        # Les deux noms sont completes independamment : sur un assemblage
        # structurel le parametre de famille repond mais pas celui de type.
        fam = typ = None
        try:
            p_fam = el.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
            if p_fam:
                fam = p_fam.AsString() or None
            p_typ = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if p_typ:
                typ = p_typ.AsString() or None
        except Exception:
            pass
        if (fam is None or typ is None) and tid is not None:
            try:
                et = d.GetElement(tid)
                if et is not None:
                    fam = fam or getattr(et, "FamilyName", None) or None
                    typ = typ or getattr(et, "Name", None) or None
            except Exception:
                pass
        if typ is None:
            try:
                typ = el.Name or None
            except Exception:
                pass

        res = (fam or u"—", typ or u"—")
        if key is not None:
            _TYPE_NAME_CACHE[key] = res
        return res

    def get_category_name(el):
        try:
            if el.Category is not None:
                return el.Category.Name
        except Exception:
            pass
        return u"—"

    def get_level_name(el, d):
        for bip_name in ["FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
                         "INSTANCE_REFERENCE_LEVEL_PARAM", "FAMILY_BASE_LEVEL_PARAM",
                         "LEVEL_PARAM"]:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            try:
                p = el.get_Parameter(bip)
                if p and p.AsElementId() != ElementId.InvalidElementId:
                    lvl = d.GetElement(p.AsElementId())
                    if lvl:
                        return lvl.Name
            except Exception:
                pass
        return u"—"

    # ---------------------------------------------------------------- geometrie
    def _find_view3d():
        """Vue 3D utilisable pour lire une geometrie dependante de la vue."""
        try:
            av = doc.ActiveView
            if isinstance(av, View3D) and not av.IsTemplate:
                return av
        except Exception:
            pass
        try:
            for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
                if not v.IsTemplate:
                    return v
        except Exception:
            pass
        return None

    VIEW3D = _find_view3d()

    STRAT_LABELS = {
        0: u"modele, objets visibles",
        1: u"modele, objets non visibles inclus",
        2: u"vue 3D",
    }

    def _geo_options(strategy, view3d):
        o = Options()
        o.ComputeReferences = False
        if strategy == 2:
            if view3d is None:
                return None
            o.IncludeNonVisibleObjects = True
            try:
                o.View = view3d
            except Exception:
                return None
            return o
        o.IncludeNonVisibleObjects = (strategy == 1)
        try:
            o.DetailLevel = ViewDetailLevel.Fine
        except Exception:
            pass
        return o

    def _collect_solids(geo_elem, top, use_instance, depth, out):
        if geo_elem is None or depth > 4:
            return
        for g in geo_elem:
            try:
                if isinstance(g, Solid):
                    if g.Volume > 1e-9 and g.Faces.Size > 0:
                        out.append(g)
                elif isinstance(g, GeometryInstance):
                    if top and not use_instance:
                        sub = g.GetSymbolGeometry()      # repere local de la famille
                    else:
                        sub = g.GetInstanceGeometry()    # repere du parent
                    _collect_solids(sub, False, use_instance, depth + 1, out)
            except Exception:
                pass

    def get_solids(el, use_instance=False, allow_view=True):
        """
        Solides d'un element, en essayant successivement plusieurs modes de lecture.
        Les objets acier des assemblages ne repondent pas tous au mode par defaut.
        Retourne (solides, strategie_utilisee) — strategie -1 si rien trouve.
        """
        view3d = VIEW3D if allow_view else None
        for strat in (0, 1, 2):
            o = _geo_options(strat, view3d)
            if o is None:
                continue
            out = []
            try:
                _collect_solids(el.get_Geometry(o), True, use_instance, 0, out)
            except Exception:
                out = []
            if out:
                return out, strat
        return [], -1

    def _bbox_dims_ft(solids):
        """Dimensions de la boite englobante, triees decroissant."""
        mn = [1e12, 1e12, 1e12]
        mx = [-1e12, -1e12, -1e12]
        found = False
        for s in solids:
            try:
                for edge in s.Edges:
                    for p in edge.Tessellate():
                        found = True
                        for i, v in enumerate((p.X, p.Y, p.Z)):
                            if v < mn[i]: mn[i] = v
                            if v > mx[i]: mx[i] = v
            except Exception:
                pass
        if not found:
            return None
        return sorted([mx[i] - mn[i] for i in range(3)], reverse=True)

    def measure_solids(solids):
        """
        Mesure une platine a partir de ses solides.
        1. face plane la plus grande -> encombrement A x B
        2. epaisseur = distance a la face plane opposee parallele du MEME solide
           (juste meme si la piece porte des raidisseurs ou des boulons)
        3. replis : volume / aire, puis boite englobante
        """
        if not solids:
            return None

        vol_ft3 = 0.0
        for s in solids:
            try:
                vol_ft3 += s.Volume
            except Exception:
                pass

        best_face  = None
        best_solid = None
        best_area  = 0.0
        for s in solids:
            try:
                for f in s.Faces:
                    if isinstance(f, PlanarFace):
                        a = f.Area
                        if a > best_area:
                            best_area, best_face, best_solid = a, f, s
            except Exception:
                pass

        dim_a = dim_b = ep = None
        methode = u""

        if best_face is not None and best_area > 1e-9:
            try:
                bb  = best_face.GetBoundingBox()
                p00 = best_face.Evaluate(UV(bb.Min.U, bb.Min.V))
                p10 = best_face.Evaluate(UV(bb.Max.U, bb.Min.V))
                p01 = best_face.Evaluate(UV(bb.Min.U, bb.Max.V))
                du  = p00.DistanceTo(p10)
                dv  = p00.DistanceTo(p01)
                if du > 1e-9 and dv > 1e-9:
                    dim_a = max(du, dv)
                    dim_b = min(du, dv)
            except Exception:
                pass

            if dim_a is not None:
                try:
                    n0 = best_face.FaceNormal
                    o0 = best_face.Origin
                    best_opp_area = 0.0
                    for f in best_solid.Faces:
                        if f is best_face or not isinstance(f, PlanarFace):
                            continue
                        if abs(n0.DotProduct(f.FaceNormal) + 1.0) > 1e-3:
                            continue
                        d = abs((f.Origin - o0).DotProduct(n0))
                        if d < 1e-9:
                            continue
                        if f.Area > best_opp_area:
                            best_opp_area = f.Area
                            ep = d
                    if ep is not None:
                        methode = u"Faces paralleles"
                except Exception:
                    ep = None

            if dim_a is not None and ep is None:
                try:
                    v_best = best_solid.Volume
                except Exception:
                    v_best = vol_ft3
                if v_best > 0:
                    ep = v_best / best_area
                    methode = u"Volume / aire"

        if dim_a is None or ep is None or ep <= 0 or ep > dim_b:
            dims = _bbox_dims_ft(solids)
            if dims is None:
                return None
            dim_a, dim_b, ep = dims[0], dims[1], dims[2]
            methode = u"Boite englobante"

        return {
            "dim_a_mm":  dim_a * FT_TO_MM,
            "dim_b_mm":  dim_b * FT_TO_MM,
            "ep_mm":     ep * FT_TO_MM,
            "volume_m3": to_m3(vol_ft3),
            "methode":   methode,
        }

    def _solid_dims_fast(s):
        """Dimensions via la boite du solide — beaucoup plus rapide que la tessellation."""
        try:
            bb = s.GetBoundingBox()
            if bb is None:
                return None
            d = [bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z]
            if min(d) <= 1e-9:
                return None
            return sorted(d, reverse=True)
        except Exception:
            return None

    def solid_too_small(solid):
        """Rejet rapide : un solide dont la boite entiere est plus petite qu'une
        platine ne peut pas en etre une. Seul rejet fiable sur la boite axiale —
        une platine inclinee a une boite bien plus epaisse que son epaisseur reelle."""
        dims = _solid_dims_fast(solid)
        if dims is None:
            return False
        return dims[0] * FT_TO_MM < DIM_MIN_MM

    def is_plate_measure(m):
        """Test de forme sur les dimensions MESUREES (independantes de l'orientation)."""
        if m is None:
            return False
        ep, b = m["ep_mm"], m["dim_b_mm"]
        if ep <= 0 or b <= 0:
            return False
        if ep > EP_MAX_MM or b < DIM_MIN_MM:
            return False
        return (ep / b) <= RATIO_MAX

    def solid_style_name(s, d):
        """Sous-categorie graphique du solide (plaque, boulon, soudure...)."""
        try:
            gid = s.GraphicsStyleId
            if gid is not None and gid != ElementId.InvalidElementId:
                gs = d.GetElement(gid)
                if gs is not None:
                    cat = getattr(gs, "GraphicsStyleCategory", None)
                    if cat is not None and cat.Name:
                        return cat.Name
                    return gs.Name or u""
        except Exception:
            pass
        return u""

    def solid_material_id(s):
        """Materiau porte par les faces du solide (les assemblages acier n'exposent
        pas leurs materiaux au niveau de l'element)."""
        try:
            for f in s.Faces:
                mid = f.MaterialElementId
                if mid is not None and mid != ElementId.InvalidElementId:
                    return mid
        except Exception:
            pass
        return None

    # ---------------------------------------------------------------- materiau
    def _param_masse_volumique(el, d):
        PARAM = u"#STR_Masse volumique"
        try:
            src_list = [d.GetElement(el.GetTypeId()), el]
        except Exception:
            src_list = [el]
        for src in src_list:
            if src is None:
                continue
            try:
                p = src.LookupParameter(PARAM)
                if p and p.HasValue and p.AsDouble() > 0:
                    return p.AsDouble() * DENSITY_FT3_TO_M3
            except Exception:
                pass
        return None

    def _material_by_id(mid, d):
        """(nom, densite, source) a partir d'un identifiant de materiau."""
        if mid is None or mid == ElementId.InvalidElementId:
            return (u"—", None, u"")
        try:
            mat = d.GetElement(mid)
        except Exception:
            mat = None
        if mat is None:
            return (u"—", None, u"")
        nom = mat.Name or u"—"
        try:
            aid = mat.StructuralAssetId
            if aid is not None and aid != ElementId.InvalidElementId:
                pse = d.GetElement(aid)
                if pse is not None:
                    asset = pse.GetStructuralAsset()
                    if asset is not None and asset.Density > 0:
                        return (nom, asset.Density * DENSITY_FT3_TO_M3, u"Materiau Revit")
        except Exception:
            pass
        if any(h in _norm(nom) for h in ACIER_HINTS):
            return (nom, ACIER_DEFAUT, u"Defaut acier 7850")
        return (nom, None, u"")

    def get_material_info(el, d):
        """(nom_materiau, densite_kg_m3, source_densite) — au niveau de l'element."""
        best_id  = None
        best_vol = -1.0
        try:
            for mid in el.GetMaterialIds(False):
                try:
                    v = el.GetMaterialVolume(mid)
                except Exception:
                    v = 0.0
                if v > best_vol:
                    best_vol, best_id = v, mid
        except Exception:
            pass

        nom, rho, src = _material_by_id(best_id, d)
        if rho:
            return (nom, rho, src)

        rho2 = _param_masse_volumique(el, d)
        if rho2:
            return (nom, rho2, u"#STR_Masse volumique")
        return (nom, rho, src)

    def get_material_info_solid(s, el, d):
        """Materiau d'un solide isole, avec repli sur l'element porteur."""
        nom, rho, src = _material_by_id(solid_material_id(s), d)
        if rho:
            return (nom, rho, src)
        nom2, rho2, src2 = get_material_info(el, d)
        if rho2:
            return (nom2, rho2, src2)
        return (nom if nom != u"—" else nom2, rho or rho2, src or src2)

    # =========================================================================
    # Collecte
    # =========================================================================
    class PlateData(object):
        def __init__(self):
            self.element_id  = 0
            self.sub_index   = 0
            self.is_link     = False
            self.source      = u""
            self.provenance  = u""
            self.famille     = u""
            self.type_name   = u""
            self.repere      = u""
            self.categorie   = u""
            self.niveau      = u""
            self.ep_mm       = 0.0
            self.dim_a_mm    = 0.0
            self.dim_b_mm    = 0.0
            self.volume_m3   = 0.0
            self.materiau    = u"—"
            self.densite     = None
            self.src_densite = u""
            self.masse_kg    = None
            self.methode     = u""

    def _bic(name):
        return getattr(BuiltInCategory, name, None)

    CAT_CONN = _bic("OST_StructConnections")

    # Toutes les sous-categories d'objets d'assemblage exposees par la version de
    # Revit installee (plaques, boulons, soudures, ancrages, autres...). Le nom exact
    # varie d'une version a l'autre : on les decouvre au lieu de les coder en dur.
    _EXCLUS = ("OST_StructConnections", "OST_StructConnectionSymbols",
               "OST_StructConnectionTags", "OST_StructConnectionHiddenLines")
    CONN_SUB_CATS = []
    try:
        for _n in dir(BuiltInCategory):
            if _n.startswith("OST_StructConnection") and _n not in _EXCLUS:
                _c = _bic(_n)
                if _c is not None:
                    CONN_SUB_CATS.append((_n, _c))
        CONN_SUB_CATS.sort()
    except Exception:
        pass
    # Categories dont le contenu est retenu sans test de forme
    CATS_PLAQUES_SURES = ("OST_StructConnectionPlates",)

    def _by_category(d, bic):
        if bic is None:
            return []
        try:
            return list(FilteredElementCollector(d).OfCategory(bic)
                        .WhereElementIsNotElementType().ToElements())
        except Exception:
            return []

    def _by_class(d, cls):
        try:
            return list(FilteredElementCollector(d).OfClass(cls)
                        .WhereElementIsNotElementType().ToElements())
        except Exception:
            return []

    def _fill_common(pd, el, d, source, is_link, provenance):
        pd.element_id = el.Id.IntegerValue
        pd.is_link    = is_link
        pd.source     = source
        pd.provenance = provenance
        pd.categorie  = get_category_name(el)
        pd.niveau     = get_level_name(el, d)
        nom, rho, src_rho = get_material_info(el, d)
        pd.materiau    = nom
        pd.densite     = rho
        pd.src_densite = src_rho

    def _set_mass(pd):
        if pd.densite and pd.volume_m3 > 0:
            pd.masse_kg = pd.volume_m3 * pd.densite

    def _scan_doc(d, source, is_link, keywords, use_conn, use_kw, progress, stats,
                  names_out=None):
        """Retourne la liste des PlateData du document d."""
        found = []

        # ---- A. Objets d'assemblage existant comme elements -----------------
        nb_plaques = 0
        if use_conn:
            for cat_name, bic in CONN_SUB_CATS:
                els = _by_category(d, bic)
                if not els:
                    continue
                stats.setdefault("cats", {})
                stats["cats"][cat_name] = stats["cats"].get(cat_name, 0) + len(els)
                nb_plaques += len(els)
                sure = cat_name in CATS_PLAQUES_SURES
                for i, el in enumerate(els):
                    progress(u"{} — {}".format(source, cat_name), i, len(els))
                    try:
                        solids, _strat = get_solids(el, allow_view=not is_link)
                        if not solids:
                            continue
                        m = measure_solids(solids)
                        if m is None:
                            continue
                        if not sure and not is_plate_measure(m):
                            continue
                        pd = PlateData()
                        _fill_common(pd, el, d, source, is_link, PROV_PLAQUE)
                        fam, typ = get_family_type_names(el, d)
                        pd.famille   = fam if fam != u"—" else pd.categorie
                        pd.type_name = typ
                        pd.ep_mm, pd.dim_a_mm = m["ep_mm"], m["dim_a_mm"]
                        pd.dim_b_mm = m["dim_b_mm"]
                        pd.volume_m3, pd.methode = m["volume_m3"], m["methode"]
                        _set_mass(pd)
                        found.append(pd)
                    except Exception:
                        pass
        stats["plaques"] = stats.get("plaques", 0) + nb_plaques

        # ---- B. Solides plats extraits des assemblages structurels ---------
        #     Uniquement si A n'a rien donne, sinon double comptage.
        if use_conn and not found:
            conns = _by_category(d, CAT_CONN)
            stats["assemblages"] = stats.get("assemblages", 0) + len(conns)
            for i, el in enumerate(conns):
                progress(u"{} — assemblages structurels".format(source), i, len(conns))
                try:
                    solids, strat = get_solids(el, use_instance=True,
                                               allow_view=not is_link)
                    if not solids:
                        continue
                    stats["strat"] = STRAT_LABELS.get(strat, u"?")
                    stats["solides"] = stats.get("solides", 0) + len(solids)
                    fam, typ = get_family_type_names(el, d)
                    idx = 0
                    for s in solids:
                        if solid_too_small(s):
                            continue
                        m = measure_solids([s])
                        if not is_plate_measure(m):
                            continue
                        idx += 1
                        pd = PlateData()
                        _fill_common(pd, el, d, source, is_link, PROV_ASSEMB)
                        pd.sub_index = idx
                        pd.famille   = fam
                        pd.type_name = typ
                        pd.repere    = solid_style_name(s, d)
                        pd.ep_mm, pd.dim_a_mm = m["ep_mm"], m["dim_a_mm"]
                        pd.dim_b_mm = m["dim_b_mm"]
                        pd.volume_m3, pd.methode = m["volume_m3"], m["methode"]
                        nom, rho, src_rho = get_material_info_solid(s, el, d)
                        pd.materiau, pd.densite, pd.src_densite = nom, rho, src_rho
                        _set_mass(pd)
                        found.append(pd)
                except Exception:
                    pass

        # ---- C. Familles / DirectShape reperees par mot-cle ----------------
        if use_kw and keywords:
            cands = _by_class(d, FamilyInstance) + _by_class(d, DirectShape)
            stats["familles"] = stats.get("familles", 0) + len(cands)
            deja = set(p.element_id for p in found)
            for i, el in enumerate(cands):
                if i % 100 == 0:
                    progress(u"{} — familles".format(source), i, len(cands))
                try:
                    fam, typ = get_family_type_names(el, d)
                    if names_out is not None:
                        names_out.add(u"{}   [{}]".format(fam, get_category_name(el)))
                    if not any(kw in (_norm(fam) + u" " + _norm(typ)) for kw in keywords):
                        continue
                    if el.Id.IntegerValue in deja:
                        continue
                    _sol, _st = get_solids(el, allow_view=not is_link)
                    m = measure_solids(_sol)
                    pd = PlateData()
                    _fill_common(pd, el, d, source, is_link, PROV_FAM)
                    pd.famille   = fam
                    pd.type_name = typ
                    if m is None:
                        pd.methode = u"Geometrie indisponible"
                    else:
                        pd.ep_mm, pd.dim_a_mm = m["ep_mm"], m["dim_a_mm"]
                        pd.dim_b_mm = m["dim_b_mm"]
                        pd.volume_m3, pd.methode = m["volume_m3"], m["methode"]
                    _set_mass(pd)
                    found.append(pd)
                except Exception:
                    pass

        return found

    def scan_model(keywords, include_links, use_conn, use_kw, progress, stats, names_out):
        results = _scan_doc(doc, u"Modele courant", False, keywords, use_conn, use_kw,
                            progress, stats, names_out)
        if include_links:
            seen_titles = set()
            for li in _by_class(doc, RevitLinkInstance):
                try:
                    ldoc = li.GetLinkDocument()
                    if ldoc is None or ldoc.Title in seen_titles:
                        continue
                    seen_titles.add(ldoc.Title)
                    results.extend(_scan_doc(ldoc, ldoc.Title, True, keywords,
                                             use_conn, use_kw, progress, stats))
                except Exception:
                    pass
        return results

    # ------------------------------------------------------------- regroupement
    class PlateGroup(object):
        def __init__(self, pd):
            self.source     = pd.source
            self.is_link    = pd.is_link
            self.provenance = pd.provenance
            self.famille    = pd.famille
            self.type_name  = pd.type_name
            self.repere     = pd.repere
            self.categorie  = pd.categorie
            self.ep_mm      = pd.ep_mm
            self.dim_a_mm   = pd.dim_a_mm
            self.dim_b_mm   = pd.dim_b_mm
            self.materiau   = pd.materiau
            self.densite    = pd.densite
            self.src_dens   = pd.src_densite
            self.methode    = pd.methode
            self.items      = []

        @property
        def nb(self):
            return len(self.items)

        @property
        def volume_total(self):
            return float(sum(p.volume_m3 for p in self.items))

        @property
        def masse_totale(self):
            vals = [p.masse_kg for p in self.items if p.masse_kg]
            return float(sum(vals)) if vals else None

        @property
        def masse_unitaire(self):
            mt = self.masse_totale
            return (mt / self.nb) if (mt and self.nb) else None

        @property
        def element_ids(self):
            ids = []
            for p in self.items:
                if p.element_id not in ids:
                    ids.append(p.element_id)
            return ids

        @property
        def niveaux(self):
            noms = []
            for p in self.items:
                if p.niveau and p.niveau not in noms:
                    noms.append(p.niveau)
            return u" / ".join(noms) if noms else u"—"

    def group_plates(plates):
        groups, order = {}, []
        for pd in plates:
            key = (pd.source, pd.provenance, pd.famille, pd.type_name, pd.repere,
                   round(pd.ep_mm, 0), round(pd.dim_a_mm, 0), round(pd.dim_b_mm, 0),
                   pd.materiau)
            g = groups.get(key)
            if g is None:
                g = PlateGroup(pd)
                groups[key] = g
                order.append(key)
            g.items.append(pd)
        res = [groups[k] for k in order]
        res.sort(key=lambda g: (g.source, _norm(g.famille), _norm(g.type_name),
                                -g.ep_mm, -g.dim_a_mm))
        return res

    # =========================================================================
    # Etat courant
    # =========================================================================
    _prefs = _load_prefs()
    STATE = {
        "keywords_txt": _prefs.get("keywords", DEFAULT_KEYWORDS),
        "links":        bool(_prefs.get("include_links", False)),
        "use_conn":     bool(_prefs.get("use_conn", True)),
        "use_kw":       bool(_prefs.get("use_kw", True)),
        "plates":       [],
        "groups":       [],
        "noms_vus":     set(),
        "stats":        {},
        "duree":        0.0,
    }

    def _msg_aucun_resultat():
        st = STATE["stats"]
        lignes = [u"Elements parcourus :",
                  u"  {} objet(s) d'assemblage (plaques, boulons...)".format(st.get("plaques", 0)),
                  u"  {} assemblage(s) structurel(s)".format(st.get("assemblages", 0)),
                  u"  {} famille(s)/DirectShape".format(st.get("familles", 0))]
        cats = st.get("cats", {})
        if cats:
            lignes.append(u"")
            lignes.append(u"Sous-categories d'assemblage trouvees :")
            for k in sorted(cats.keys()):
                lignes.append(u"  {} : {}".format(k, cats[k]))
        if st.get("solides"):
            lignes.append(u"")
            lignes.append(u"{} solide(s) lus dans les assemblages ({}) — "
                          u"aucun ne passe le test de forme "
                          u"(ep. <= {:.0f} mm, cote >= {:.0f} mm).".format(
                              st.get("solides", 0), st.get("strat", u"?"),
                              EP_MAX_MM, DIM_MIN_MM))
        elif st.get("assemblages"):
            lignes.append(u"")
            lignes.append(u"Aucun solide lisible dans la geometrie des assemblages.")
        lignes.append(u"")
        lignes.append(u"Cliquez sur « Diagnostic » pour le detail element par element.")
        return u"Aucune platine trouvee.\n\n" + u"\n".join(lignes)

    def run_scan(keywords_txt, include_links, use_conn, use_kw, owner=None):
        if not use_conn and not parse_keywords(keywords_txt):
            MessageBox.Show(u"Activez les assemblages structurels ou indiquez un mot-cle.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return False

        pw, lbl, pb = make_progress_window(TOOL_NAME)
        if owner is not None:
            try:
                pw.Owner = owner
            except Exception:
                pass
        lbl.Text = u"Analyse du modele en cours..."
        pw.Show()
        do_events(pw.Dispatcher)

        etat = {"last": -1}
        def progress(etape, i, total):
            if total <= 0:
                return
            pct = int(100.0 * i / total)
            if pct == etat["last"]:
                return
            etat["last"] = pct
            lbl.Text = u"{} : {} / {}".format(etape, i, total)
            pb.IsIndeterminate = False
            pb.Value = pct
            do_events(pw.Dispatcher)

        stats, noms = {}, set()
        t0 = time.time()
        try:
            plates = scan_model(parse_keywords(keywords_txt), include_links,
                                use_conn, use_kw, progress, stats, noms)
        finally:
            pw.Close()

        STATE["duree"]        = time.time() - t0
        STATE["stats"]        = stats
        STATE["noms_vus"]     = noms
        STATE["plates"]       = plates
        STATE["groups"]       = group_plates(plates)
        STATE["keywords_txt"] = keywords_txt
        STATE["links"]        = include_links
        STATE["use_conn"]     = use_conn
        STATE["use_kw"]       = use_kw

        p = _load_prefs()
        p["keywords"]      = keywords_txt
        p["include_links"] = bool(include_links)
        p["use_conn"]      = bool(use_conn)
        p["use_kw"]        = bool(use_kw)
        _save_prefs(p)
        return True

    def totals():
        # float() obligatoire : sum([]) renvoie l'entier 0 et IronPython refuse
        # une precision sur un format entier.
        nb    = len(STATE["plates"])
        vol   = float(sum(p.volume_m3 for p in STATE["plates"]))
        masse = float(sum(p.masse_kg for p in STATE["plates"] if p.masse_kg))
        return nb, vol, masse

    # =========================================================================
    # Lignes DataGrid
    # =========================================================================
    BG_WHITE = rgb(255, 255, 255)
    BG_ALT   = rgb(232, 240, 250)
    BG_WARN  = rgb(255, 235, 200)
    FG_DARK  = rgb(30, 30, 30)
    W_NORMAL = FontWeights.Normal
    W_BOLD   = FontWeights.Bold

    class PlateRow(object):
        def __init__(self, g, idx):
            self._g        = g
            self.Num       = u"{}".format(idx)
            self.Prov      = g.provenance if not g.is_link else u"{} [{}]".format(
                                 g.provenance, g.source)
            self.Famille   = g.famille
            self.Type      = g.type_name
            self.Repere    = g.repere or u"—"
            self.Ep        = fmt_mm(g.ep_mm)    if g.ep_mm    > 0 else u"—"
            self.DimA      = fmt_mm(g.dim_a_mm) if g.dim_a_mm > 0 else u"—"
            self.DimB      = fmt_mm(g.dim_b_mm) if g.dim_b_mm > 0 else u"—"
            self.Materiau  = g.materiau
            self.Nb        = u"{}".format(g.nb)
            self.MasseU    = fmt_kg(g.masse_unitaire)
            self.MasseT    = fmt_kg(g.masse_totale)
            suspect        = (g.ep_mm <= 0)
            self.RowBg     = BG_WARN if suspect else (BG_WHITE if idx % 2 == 1 else BG_ALT)
            self.RowFg     = FG_DARK
            self.RowWeight = W_BOLD if suspect else W_NORMAL

    def build_rows():
        col = ObservableCollection[object]()
        for idx, g in enumerate(STATE["groups"], start=1):
            col.Add(PlateRow(g, idx))
        return col

    # =========================================================================
    # Diagnostic geometrie
    # =========================================================================
    def _inventaire_geo(el, use_instance):
        """Detail de ce que renvoie chaque strategie de lecture pour un element."""
        out = []
        for strat in (0, 1, 2):
            o = _geo_options(strat, VIEW3D)
            if o is None:
                out.append(u"    [{}] indisponible (pas de vue 3D)".format(STRAT_LABELS[strat]))
                continue
            try:
                geo = el.get_Geometry(o)
            except Exception as ex:
                out.append(u"    [{}] erreur : {}".format(STRAT_LABELS[strat], ex))
                continue
            if geo is None:
                out.append(u"    [{}] aucune geometrie".format(STRAT_LABELS[strat]))
                continue
            types, nb = {}, 0
            try:
                for g in geo:
                    nb += 1
                    n = type(g).__name__
                    types[n] = types.get(n, 0) + 1
            except Exception:
                pass
            solids = []
            _collect_solids(geo, True, use_instance, 0, solids)
            out.append(u"    [{}] {} objet(s) {} -> {} solide(s)".format(
                STRAT_LABELS[strat], nb,
                u"/".join(u"{}x{}".format(v, k) for k, v in sorted(types.items())) or u"-",
                len(solids)))
            for j, s in enumerate(solids[:12], start=1):
                m = measure_solids([s])
                dims = _solid_dims_fast(s) or _bbox_dims_ft([s])
                boite = u"?"
                if dims is not None:
                    boite = u"{:.0f}x{:.0f}x{:.0f}".format(*[x * FT_TO_MM for x in dims])
                if m is None:
                    out.append(u"        solide {} : mesure impossible | boite {}".format(
                        j, boite))
                    continue
                try:
                    vol = to_m3(s.Volume) * 1e9      # mm3
                except Exception:
                    vol = 0.0
                nom_mat = get_material_info_solid(s, el, doc)[0]
                out.append(u"        solide {} : mesure {:.0f} x {:.0f} x {:.0f} mm | "
                           u"boite {} | vol {:.0f} mm3 | style={} | mat={} | platine={}".format(
                               j, m["dim_a_mm"], m["dim_b_mm"], m["ep_mm"], boite, vol,
                               solid_style_name(s, doc) or u"-", nom_mat,
                               u"OUI" if is_plate_measure(m) else u"non"))
            if len(solids) > 12:
                out.append(u"        ... {} autre(s) solide(s)".format(len(solids) - 12))
        return out

    def run_diagnostic():
        L = []
        L.append(u"Projet : {}".format(doc.Title))
        L.append(u"Revit {} — vue 3D utilisee : {}".format(
            app.VersionNumber, VIEW3D.Name if VIEW3D is not None else u"aucune"))
        L.append(u"")
        L.append(u"=== Sous-categories d'assemblage presentes ===")
        vide = True
        for cat_name, bic in CONN_SUB_CATS:
            n = len(_by_category(doc, bic))
            if n:
                vide = False
                L.append(u"  {} : {} element(s)".format(cat_name, n))
        if vide:
            L.append(u"  (aucune — les objets d'assemblage ne sont pas des elements "
                     u"independants dans cette maquette)")
        L.append(u"")

        conns = _by_category(doc, CAT_CONN)
        L.append(u"=== Assemblages structurels : {} ===".format(len(conns)))
        for i, el in enumerate(conns[:5], start=1):
            fam, typ = get_family_type_names(el, doc)
            L.append(u"")
            L.append(u"  [{}] Id {} — {} / {}".format(i, el.Id.IntegerValue, fam, typ))
            L.append(u"  Classe .NET : {}".format(type(el).__name__))
            try:
                bb = el.get_BoundingBox(None)
                if bb is not None:
                    L.append(u"  Boite : {:.0f} x {:.0f} x {:.0f} mm".format(
                        (bb.Max.X - bb.Min.X) * FT_TO_MM,
                        (bb.Max.Y - bb.Min.Y) * FT_TO_MM,
                        (bb.Max.Z - bb.Min.Z) * FT_TO_MM))
                else:
                    L.append(u"  Boite : aucune")
            except Exception:
                L.append(u"  Boite : erreur de lecture")
            L.extend(_inventaire_geo(el, True))
        if len(conns) > 5:
            L.append(u"")
            L.append(u"... {} autre(s) assemblage(s) non detailles.".format(len(conns) - 5))
        return u"\n".join(L)

    def show_diagnostic():
        try:
            txt = run_diagnostic()
        except Exception:
            txt = u"Diagnostic en echec :\n\n" + traceback.format_exc()

        d = Window()
        d.Title = TOOL_NAME
        d.Width = 820; d.Height = 620
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        hdr = Border(); hdr.Background = hex_brush("#2F6496")
        hdr.Padding = Thickness(14, 8, 14, 8)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        htb = TextBlock()
        htb.Text = u"Diagnostic geometrie des assemblages structurels"
        htb.FontSize = 12; htb.FontWeight = FontWeights.SemiBold
        htb.Foreground = hex_brush("#FFFFFF"); hdr.Child = htb

        box = TextBox()
        box.Text = txt
        box.IsReadOnly = True
        box.FontFamily = FontFamily("Consolas")
        box.FontSize = 11
        box.Margin = Thickness(10, 8, 10, 6)
        box.TextWrapping = TextWrapping.NoWrap
        box.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
        box.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        box.BorderBrush = hex_brush("#C0D0E0")
        Grid.SetRow(box, 1); droot.Children.Add(box)

        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)

        def _copier(s, e):
            try:
                Clipboard.SetText(txt)
            except Exception:
                pass
        btn_cp = _footer_btn(u"Copier", "#E67E22", 100, _copier)
        btn_cp.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_cp)
        dsp.Children.Add(_footer_btn(u"Fermer", "#3498DB", 90, lambda s, e: d.Close()))
        dgf.Children.Add(dsp)
        d.ShowDialog()

    # =========================================================================
    # Export helpers
    # =========================================================================
    def _ask_filename(folder, default_name):
        result = {"path": None}
        d = Window()
        d.Title = TOOL_NAME
        d.Width = 460; d.Height = 200
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        hdr = Border(); hdr.Background = hex_brush("#2F6496")
        hdr.Padding = Thickness(14, 7, 14, 7)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        hdr_tb = TextBlock()
        hdr_tb.Text = u"Fichier existant — choisir un nom"
        hdr_tb.FontSize = 12; hdr_tb.FontWeight = FontWeights.SemiBold
        hdr_tb.Foreground = hex_brush("#FFFFFF"); hdr.Child = hdr_tb

        body = StackPanel(); body.Margin = Thickness(16, 12, 16, 8)
        Grid.SetRow(body, 1); droot.Children.Add(body)

        lbl_warn = TextBlock()
        lbl_warn.Text = u"Le fichier \"{}\" existe deja dans ce dossier.".format(default_name)
        lbl_warn.FontSize = 11; lbl_warn.Foreground = hex_brush("#E74C3C")
        lbl_warn.TextWrapping = TextWrapping.Wrap; lbl_warn.Margin = Thickness(0, 0, 0, 8)
        body.Children.Add(lbl_warn)

        lbl_hint = TextBlock()
        lbl_hint.Text = u"Nouveau nom de fichier (sans extension) :"
        lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#555555")
        lbl_hint.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(lbl_hint)

        txt = TextBox(); txt.FontSize = 11; txt.Height = 26
        txt.Padding = Thickness(4, 2, 4, 2)
        txt.BorderBrush = hex_brush("#C0D0E0"); txt.BorderThickness = Thickness(1)
        txt.Text = os.path.splitext(default_name)[0] + u"_1"; txt.SelectAll()
        body.Children.Add(txt)

        lbl_err = TextBlock(); lbl_err.FontSize = 10
        lbl_err.Foreground = hex_brush("#E74C3C"); lbl_err.Margin = Thickness(0, 3, 0, 0)
        body.Children.Add(lbl_err)

        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)

        def _on_ok(s, e):
            name = txt.Text.strip()
            if not name:
                lbl_err.Text = u"Le nom ne peut pas etre vide."; return
            final = name if name.lower().endswith(".xlsx") else name + ".xlsx"
            fp = os.path.join(folder, final)
            if os.path.exists(fp):
                lbl_err.Text = u"Ce fichier existe aussi. Choisissez un autre nom."; return
            result["path"] = fp
            d.Close()

        btn_cancel = _footer_btn(u"Annuler",  "#E74C3C", 90, lambda s, e: d.Close())
        btn_ok2    = _footer_btn(u"Exporter", "#E67E22", 90, _on_ok)
        btn_cancel.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_cancel); dsp.Children.Add(btn_ok2)
        dgf.Children.Add(dsp)

        def on_key(s, e):
            if e.Key == System.Windows.Input.Key.Return:
                _on_ok(s, e)
        txt.KeyDown += on_key
        d.ShowDialog()
        return result["path"]

    def _show_export_success(path):
        d = Window()
        d.Title = TOOL_NAME
        d.Width = 420; d.Height = 155
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        body = StackPanel(); body.Margin = Thickness(16, 14, 16, 8)
        Grid.SetRow(body, 0); droot.Children.Add(body)
        tb1 = TextBlock(); tb1.Text = u"Export reussi :"
        tb1.FontSize = 11; tb1.FontWeight = FontWeights.SemiBold
        tb1.Foreground = hex_brush("#2F6496"); tb1.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(tb1)
        tb2 = TextBlock(); tb2.Text = path; tb2.FontSize = 10
        tb2.Foreground = hex_brush("#444444"); tb2.TextWrapping = TextWrapping.Wrap
        body.Children.Add(tb2)

        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 1); droot.Children.Add(dfooter)

        def _open_folder(s, e):
            try:
                psi = System.Diagnostics.ProcessStartInfo()
                psi.FileName  = "explorer.exe"
                psi.Arguments = u'"{}"'.format(os.path.dirname(path))
                System.Diagnostics.Process.Start(psi)
            except Exception:
                pass
            d.Close()

        btn_open = _footer_btn(u"Ouvrir le dossier", "#E67E22", 130, _open_folder)
        btn_ok3  = _footer_btn(u"OK",                "#3498DB",  60, lambda s, e: d.Close())
        btn_open.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_open); dsp.Children.Add(btn_ok3)
        dgf.Children.Add(dsp)
        d.ShowDialog()

    # =========================================================================
    # Export XLSX
    # =========================================================================
    def export_xlsx():
        if not STATE["groups"]:
            MessageBox.Show(u"Rien a exporter.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return None
        folder = pick_folder()
        if not folder:
            return None
        try:
            import xlsxwriter
        except Exception:
            MessageBox.Show(u"Le module xlsxwriter n'est pas disponible.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None
        try:
            default_name = u"quantification_platines.xlsx"
            fpath = os.path.join(folder, default_name)
            if os.path.exists(fpath):
                fpath = _ask_filename(folder, default_name)
                if not fpath:
                    return None

            groups, plates = STATE["groups"], STATE["plates"]
            nb_tot, vol_tot, masse_tot = totals()

            wb  = xlsxwriter.Workbook(fpath)
            ws  = wb.add_worksheet(u"Platines")
            wsd = wb.add_worksheet(u"Detail")
            ws2 = wb.add_worksheet(u"Synthese")

            fmt_title = wb.add_format({"bold": True, "font_size": 14, "font_name": "Calibri"})
            fmt_hdr   = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                       "font_color": "#FFFFFF", "border": 1,
                                       "font_name": "Calibri", "align": "center",
                                       "valign": "vcenter", "text_wrap": True})
            fmt_txt   = wb.add_format({"font_name": "Calibri"})
            fmt_mm1   = wb.add_format({"num_format": "#,##0.0", "font_name": "Calibri"})
            fmt_num3  = wb.add_format({"num_format": "#,##0.000", "font_name": "Calibri"})
            fmt_kg1   = wb.add_format({"num_format": "#,##0.0", "font_name": "Calibri"})
            fmt_int_c = wb.add_format({"font_name": "Calibri", "align": "center"})
            fmt_tot   = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                       "font_color": "#FFFFFF", "font_name": "Calibri"})
            fmt_tot_n = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                       "font_color": "#FFFFFF", "font_name": "Calibri",
                                       "num_format": "#,##0.0"})
            fmt_tot_3 = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                       "font_color": "#FFFFFF", "font_name": "Calibri",
                                       "num_format": "#,##0.000"})
            fmt_tot_i = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                       "font_color": "#FFFFFF", "font_name": "Calibri",
                                       "align": "center"})
            fmt_sub   = wb.add_format({"bold": True, "bg_color": "#D0E4F7",
                                       "font_name": "Calibri"})
            fmt_sub_i = wb.add_format({"bold": True, "bg_color": "#D0E4F7",
                                       "font_name": "Calibri", "align": "center"})
            DASH = u"—"

            def wnum(sheet, r, c, val, fmt):
                if val is None or val <= 0:
                    sheet.write(r, c, DASH, fmt_txt)
                else:
                    sheet.write_number(r, c, float(val), fmt)

            # Ecriture par liste (valeur, type) : ajouter une colonne ne decale
            # plus aucun indice.
            KFMT = {"mm": fmt_mm1, "n3": fmt_num3, "kg": fmt_kg1}

            def write_line(sheet, r, cells):
                for c, pair in enumerate(cells):
                    val, kind = pair
                    if kind == "txt":
                        sheet.write(r, c, val if val else DASH, fmt_txt)
                    elif kind == "int":
                        sheet.write_number(r, c, val, fmt_int_c)
                    else:
                        wnum(sheet, r, c, val, KFMT[kind])

            # ---------------- Feuille 1 : regroupement -------------------------
            headers = [u"N", u"Source", u"Provenance", u"Famille / Assemblage", u"Type",
                       u"Repere", u"Categorie", u"Epaisseur (mm)", u"Dimension A (mm)",
                       u"Dimension B (mm)", u"Materiau", u"Masse vol. (kg/m3)",
                       u"Source densite", u"Nb", u"Volume unit. (m3)",
                       u"Volume total (m3)", u"Masse unit. (kg)", u"Masse totale (kg)",
                       u"Niveau(x)", u"Methode de mesure"]
            ws.set_row(0, 32)
            ws.write_row(0, 0, headers, fmt_hdr)
            ws.freeze_panes(1, 0)
            ws.set_column(0, 0, 5); ws.set_column(1, 1, 18); ws.set_column(2, 2, 22)
            ws.set_column(3, 4, 34); ws.set_column(5, 6, 22); ws.set_column(7, 9, 15)
            ws.set_column(10, 10, 22); ws.set_column(11, 12, 16); ws.set_column(13, 13, 7)
            ws.set_column(14, 17, 15); ws.set_column(18, 18, 20); ws.set_column(19, 19, 20)

            for i, g in enumerate(groups, start=1):
                write_line(ws, i, [
                    (i, "int"), (g.source, "txt"), (g.provenance, "txt"),
                    (g.famille, "txt"), (g.type_name, "txt"), (g.repere, "txt"),
                    (g.categorie, "txt"),
                    (g.ep_mm, "mm"), (g.dim_a_mm, "mm"), (g.dim_b_mm, "mm"),
                    (g.materiau, "txt"), (g.densite, "mm"), (g.src_dens, "txt"),
                    (g.nb, "int"),
                    ((g.volume_total / g.nb) if g.nb else None, "n3"),
                    (g.volume_total, "n3"),
                    (g.masse_unitaire, "kg"), (g.masse_totale, "kg"),
                    (g.niveaux, "txt"), (g.methode, "txt"),
                ])

            i_nb  = headers.index(u"Nb")
            i_vol = headers.index(u"Volume total (m3)")
            i_mas = headers.index(u"Masse totale (kg)")
            tr = len(groups) + 2
            for c in range(0, len(headers)):
                ws.write(tr, c, u"", fmt_tot)
            ws.write(tr, 1, u"TOTAL", fmt_tot)
            ws.write(tr, 6, u"{} groupe(s)".format(len(groups)), fmt_tot)
            ws.write_number(tr, i_nb,  nb_tot,  fmt_tot_i)
            ws.write_number(tr, i_vol, vol_tot, fmt_tot_3)
            if masse_tot > 0:
                ws.write_number(tr, i_mas, masse_tot, fmt_tot_n)

            # ---------------- Feuille 2 : detail -------------------------------
            headers_d = [u"ElementId", u"Indice", u"Source", u"Provenance",
                         u"Famille / Assemblage", u"Type", u"Repere", u"Categorie",
                         u"Niveau", u"Epaisseur (mm)", u"Dimension A (mm)",
                         u"Dimension B (mm)", u"Volume (m3)", u"Materiau",
                         u"Masse (kg)", u"Methode de mesure"]
            wsd.set_row(0, 32)
            wsd.write_row(0, 0, headers_d, fmt_hdr)
            wsd.freeze_panes(1, 0)
            wsd.set_column(0, 0, 12); wsd.set_column(1, 1, 8); wsd.set_column(2, 2, 18)
            wsd.set_column(3, 3, 22); wsd.set_column(4, 5, 34); wsd.set_column(6, 8, 20)
            wsd.set_column(9, 12, 15); wsd.set_column(13, 13, 22); wsd.set_column(14, 14, 13)
            wsd.set_column(15, 15, 20)

            for i, p in enumerate(plates, start=1):
                write_line(wsd, i, [
                    (p.element_id, "int"),
                    (p.sub_index, "int") if p.sub_index else (u"", "txt"),
                    (p.source, "txt"), (p.provenance, "txt"),
                    (p.famille, "txt"), (p.type_name, "txt"), (p.repere, "txt"),
                    (p.categorie, "txt"), (p.niveau, "txt"),
                    (p.ep_mm, "mm"), (p.dim_a_mm, "mm"), (p.dim_b_mm, "mm"),
                    (p.volume_m3, "n3"), (p.materiau, "txt"),
                    (p.masse_kg, "kg"), (p.methode, "txt"),
                ])

            # ---------------- Feuille 3 : synthese -----------------------------
            try:
                proj_name = doc.Title or DASH
            except Exception:
                proj_name = DASH

            r2 = 0
            ws2.write(r2, 1, u"Quantification Platines — Synthese", fmt_title); r2 += 2
            for lib, val in [
                (u"Projet", proj_name),
                (u"Date", datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
                (u"Assemblages structurels", u"Inclus" if STATE["use_conn"] else u"Exclus"),
                (u"Recherche par mots-cles",
                 STATE["keywords_txt"] if STATE["use_kw"] else u"Desactivee"),
                (u"Modeles lies", u"Inclus" if STATE["links"] else u"Exclus"),
            ]:
                ws2.write(r2, 1, lib, fmt_hdr); ws2.write(r2, 2, val, fmt_txt); r2 += 1
            ws2.write(r2, 1, u"Nb platines", fmt_hdr)
            ws2.write_number(r2, 2, nb_tot, fmt_int_c); r2 += 1
            ws2.write(r2, 1, u"Nb types distincts", fmt_hdr)
            ws2.write_number(r2, 2, len(groups), fmt_int_c); r2 += 1
            ws2.write(r2, 1, u"Volume total (m3)", fmt_hdr)
            wnum(ws2, r2, 2, vol_tot, fmt_num3); r2 += 1
            ws2.write(r2, 1, u"Masse totale (kg)", fmt_hdr)
            wnum(ws2, r2, 2, masse_tot, fmt_kg1); r2 += 2

            def bloc(titre, dico):
                loc = r2
                ws2.write(loc, 1, titre, fmt_sub)
                ws2.write(loc, 2, u"Nb", fmt_sub_i)
                ws2.write(loc, 3, u"Masse (kg)", fmt_sub_i)
                loc += 1
                for k in sorted(dico.keys()):
                    ws2.write(loc, 1, k, fmt_txt)
                    ws2.write_number(loc, 2, dico[k]["nb"], fmt_int_c)
                    wnum(ws2, loc, 3, dico[k]["masse"], fmt_kg1)
                    loc += 1
                return loc + 1

            by_ep, by_mat, by_fam = {}, {}, {}
            for p in plates:
                k_ep = u"{:.0f} mm".format(float(p.ep_mm)) if p.ep_mm > 0 else DASH
                for dico, k in ((by_ep, k_ep), (by_mat, p.materiau or DASH),
                                (by_fam, p.famille or DASH)):
                    if k not in dico:
                        dico[k] = {"nb": 0, "masse": 0.0}
                    dico[k]["nb"] += 1
                    if p.masse_kg:
                        dico[k]["masse"] += p.masse_kg

            r2 = bloc(u"Par epaisseur", by_ep)
            r2 = bloc(u"Par materiau",  by_mat)
            r2 = bloc(u"Par famille / assemblage", by_fam)

            ws2.set_column("A:A", 3); ws2.set_column("B:B", 40); ws2.set_column("C:D", 16)

            wb.close()
            return fpath

        except Exception:
            MessageBox.Show(u"Export XLSX echoue :\n\n{}".format(traceback.format_exc()),
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return None

    # =========================================================================
    # Fenetre principale
    # =========================================================================
    win = Window()
    win.Title = TOOL_NAME
    win.Width = 1260; win.Height = 700
    win.MinWidth = 950; win.MinHeight = 460
    win.ResizeMode = ResizeMode.CanResize
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    for h in ["Auto", "Auto", "*", "Auto"]:
        root.RowDefinitions.Add(_rd(h))
    win.Content = root

    hdr_brd = Border()
    hdr_brd.Background = hex_brush("#2F6496")
    hdr_brd.Padding = Thickness(14, 9, 14, 9)
    Grid.SetRow(hdr_brd, 0); root.Children.Add(hdr_brd)
    hdr_tb = TextBlock()
    hdr_tb.Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
    hdr_tb.FontSize = 13; hdr_tb.FontWeight = FontWeights.SemiBold
    hdr_tb.Foreground = hex_brush("#FFFFFF")
    hdr_brd.Child = hdr_tb

    flt_brd = Border()
    flt_brd.Background = hex_brush("#F0F6FF")
    flt_brd.BorderBrush = hex_brush("#C0D0E0")
    flt_brd.BorderThickness = Thickness(0, 0, 0, 1)
    flt_brd.Padding = Thickness(14, 8, 14, 8)
    Grid.SetRow(flt_brd, 1); root.Children.Add(flt_brd)
    flt_sp = StackPanel(); flt_brd.Child = flt_sp

    line1 = StackPanel(); line1.Orientation = Orientation.Horizontal
    flt_sp.Children.Add(line1)

    chk_conn = CheckBox()
    chk_conn.Content = u"Assemblages structurels (platines acier)"
    chk_conn.IsChecked = STATE["use_conn"]
    chk_conn.FontSize = 11
    chk_conn.VerticalAlignment = VerticalAlignment.Center
    chk_conn.Margin = Thickness(0, 0, 16, 0)
    line1.Children.Add(chk_conn)

    chk_kw = CheckBox()
    chk_kw.Content = u"Familles contenant :"
    chk_kw.IsChecked = STATE["use_kw"]
    chk_kw.FontSize = 11
    chk_kw.VerticalAlignment = VerticalAlignment.Center
    chk_kw.Margin = Thickness(0, 0, 6, 0)
    line1.Children.Add(chk_kw)

    txt_kw = TextBox()
    txt_kw.Text = STATE["keywords_txt"]
    txt_kw.Width = 190; txt_kw.Height = 24; txt_kw.FontSize = 11
    txt_kw.Padding = Thickness(4, 2, 4, 2)
    txt_kw.BorderBrush = hex_brush("#C0D0E0"); txt_kw.BorderThickness = Thickness(1)
    txt_kw.VerticalContentAlignment = VerticalAlignment.Center
    line1.Children.Add(txt_kw)

    chk_links = CheckBox()
    chk_links.Content = u"Modeles lies"
    chk_links.IsChecked = STATE["links"]
    chk_links.FontSize = 11
    chk_links.VerticalAlignment = VerticalAlignment.Center
    chk_links.Margin = Thickness(16, 0, 12, 0)
    line1.Children.Add(chk_links)

    btn_search = Button()
    btn_search.Content = u"Rechercher"
    btn_search.Width = 110; btn_search.Height = 24
    btn_search.Background = hex_brush("#2ECC71"); btn_search.Foreground = hex_brush("#FFFFFF")
    btn_search.FontWeight = FontWeights.SemiBold; btn_search.BorderThickness = Thickness(0)
    line1.Children.Add(btn_search)

    lbl_info = TextBlock()
    lbl_info.FontSize = 11; lbl_info.FontWeight = FontWeights.SemiBold
    lbl_info.Foreground = hex_brush("#2F6496"); lbl_info.Margin = Thickness(0, 6, 0, 0)
    flt_sp.Children.Add(lbl_info)

    lbl_hint = TextBlock()
    lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#666666")
    lbl_hint.TextWrapping = TextWrapping.Wrap
    lbl_hint.Margin = Thickness(0, 3, 0, 0)
    flt_sp.Children.Add(lbl_hint)

    scroll = ScrollViewer()
    scroll.Margin = Thickness(8, 6, 8, 4)
    scroll.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
    scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
    Grid.SetRow(scroll, 2); root.Children.Add(scroll)

    dg = DataGrid()
    dg.AutoGenerateColumns = False
    dg.IsReadOnly          = True
    dg.CanUserSortColumns  = True
    dg.HeadersVisibility   = DataGridHeadersVisibility.Column
    dg.RowBackground       = BG_WHITE
    dg.AlternatingRowBackground = BG_ALT
    dg.BorderBrush         = rgb(200, 210, 220)
    dg.BorderThickness     = Thickness(1)
    dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
    dg.FrozenColumnCount   = 1
    dg.SelectionMode       = DataGridSelectionMode.Single

    row_style = SW.Style(DataGridRow)
    row_style.Setters.Add(SW.Setter(DataGridRow.BackgroundProperty, Binding("RowBg")))
    dg.RowStyle = row_style

    hdr_style = SW.Style(DataGridColumnHeader)
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.BackgroundProperty, hex_brush("#D0E4F7")))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.PaddingProperty,    Thickness(6, 3, 6, 3)))
    dg.ColumnHeaderStyle = hdr_style

    def cell_style(align=SW.TextAlignment.Left):
        s = SW.Style(TextBlock)
        s.Setters.Add(SW.Setter(TextBlock.TextAlignmentProperty, align))
        s.Setters.Add(SW.Setter(TextBlock.ForegroundProperty,    Binding("RowFg")))
        s.Setters.Add(SW.Setter(TextBlock.FontWeightProperty,    Binding("RowWeight")))
        return s

    def _hdr_style(align):
        s = SW.Style(DataGridColumnHeader)
        s.Setters.Add(SW.Setter(DataGridColumnHeader.BackgroundProperty, hex_brush("#D0E4F7")))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.PaddingProperty,    Thickness(6, 3, 6, 3)))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.HorizontalContentAlignmentProperty, align))
        return s

    hdr_center = _hdr_style(HorizontalAlignment.Center)
    hdr_right  = _hdr_style(HorizontalAlignment.Right)

    def make_col(header, binding, width_val, align=SW.TextAlignment.Left, hdr_sty=None):
        c = DataGridTextColumn()
        c.Header  = header
        c.Binding = Binding(binding)
        c.Width   = DataGridLength(width_val)
        c.ElementStyle = cell_style(align)
        if hdr_sty:
            c.HeaderStyle = hdr_sty
        return c

    C = SW.TextAlignment.Center
    R = SW.TextAlignment.Right
    dg.Columns.Add(make_col(u"N",                    "Num",      42,  C, hdr_center))
    dg.Columns.Add(make_col(u"Provenance",           "Prov",    130))
    dg.Columns.Add(make_col(u"Famille / Assemblage", "Famille", 200))
    dg.Columns.Add(make_col(u"Type",                 "Type",    150))
    dg.Columns.Add(make_col(u"Repère",          "Repere",  105))
    dg.Columns.Add(make_col(u"Ép. (mm)",        "Ep",       78,  R, hdr_right))
    dg.Columns.Add(make_col(u"Dim. A (mm)",          "DimA",     88,  R, hdr_right))
    dg.Columns.Add(make_col(u"Dim. B (mm)",          "DimB",     88,  R, hdr_right))
    dg.Columns.Add(make_col(u"Matériau",        "Materiau", 130))
    dg.Columns.Add(make_col(u"Nb",                   "Nb",       52,  C, hdr_center))
    dg.Columns.Add(make_col(u"Masse u. (kg)",        "MasseU",   92,  R, hdr_right))
    dg.Columns.Add(make_col(u"Masse tot. (kg)",      "MasseT",  100,  R, hdr_right))

    def on_dg_wheel(sender, e):
        scroll.ScrollToVerticalOffset(scroll.VerticalOffset - e.Delta / 3.0)
        e.Handled = True
    dg.PreviewMouseWheel += on_dg_wheel
    scroll.Content = dg

    footer, sp_btns, grid_f = _make_footer(SCRIPT_VERSION)
    Grid.SetRow(footer, 3); root.Children.Add(footer)

    lbl_total_f = TextBlock()
    lbl_total_f.FontSize = 11; lbl_total_f.FontWeight = FontWeights.SemiBold
    lbl_total_f.Foreground = hex_brush("#1F497D")
    lbl_total_f.VerticalAlignment   = VerticalAlignment.Center
    lbl_total_f.HorizontalAlignment = HorizontalAlignment.Center
    grid_f.Children.Add(lbl_total_f)

    def refresh_ui():
        dg.ItemsSource = None
        dg.ItemsSource = build_rows()
        nb, vol, masse = totals()
        resume = u"{} platine(s)   |   {} type(s) distinct(s)   |   {} m³   |   {} kg".format(
            nb, len(STATE["groups"]), u"{:.3f}".format(float(vol)), fmt_kg(masse))
        lbl_info.Text    = resume
        lbl_total_f.Text = resume
        st = STATE["stats"]
        prov = u""
        if any(p.provenance == PROV_ASSEMB for p in STATE["plates"]):
            prov = (u"  Platines extraites de la geometrie des assemblages "
                    u"(ep. <= {:.0f} mm, cote >= {:.0f} mm) : boulons et soudures ecartes.".format(
                        EP_MAX_MM, DIM_MIN_MM))
        lbl_hint.Text = (
            u"Analyse en {:.1f} s — {} plaque(s) d'assemblage, {} assemblage(s), "
            u"{} famille(s) parcourues.{}\n"
            u"Lignes identiques regroupees (assemblage, type, epaisseur, dimensions, "
            u"materiau). Selectionnez une ligne puis « Selectionner » pour les isoler dans Revit."
        ).format(STATE["duree"], st.get("plaques", 0), st.get("assemblages", 0),
                 st.get("familles", 0), prov)

    def on_search(s, e):
        if run_scan(txt_kw.Text, bool(chk_links.IsChecked),
                    bool(chk_conn.IsChecked), bool(chk_kw.IsChecked), win):
            refresh_ui()
            if not STATE["plates"]:
                MessageBox.Show(_msg_aucun_resultat(), TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Information)
    btn_search.Click += on_search

    def on_kw_key(s, e):
        if e.Key == System.Windows.Input.Key.Return:
            on_search(s, e)
    txt_kw.KeyDown += on_kw_key

    def on_select(s, e):
        sel = dg.SelectedItem
        if sel is None:
            MessageBox.Show(u"Selectionnez d'abord une ligne dans la liste.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        g = sel._g
        if g.is_link:
            MessageBox.Show(
                u"Ces platines appartiennent au modele lie \"{}\".\n"
                u"La selection n'est possible que dans le modele courant.".format(g.source),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)
            return
        try:
            ids = NetList[ElementId]()
            for eid in g.element_ids:
                ids.Add(ElementId(eid))
            uidoc.Selection.SetElementIds(ids)
            uidoc.ShowElements(ids)
        except Exception:
            MessageBox.Show(u"Selection impossible :\n\n{}".format(traceback.format_exc()),
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)

    def on_xlsx(s, e):
        path = export_xlsx()
        if path:
            _show_export_success(path)

    btn_diag  = _footer_btn(u"Diagnostic",        "#607D8B", 100,
                            lambda s, e: show_diagnostic())
    btn_sel   = _footer_btn(u"Sélectionner", "#8E44AD", 110, on_select)
    btn_diag.Margin = Thickness(0, 0, 6, 0)
    sp_btns.Children.Add(btn_diag)
    btn_xlsx  = _footer_btn(u"Exporter XLSX",     "#2ECC71", 120, on_xlsx)
    btn_close = _footer_btn(u"Fermer",            "#3498DB",  90, lambda s, e: win.Close())
    btn_sel.Margin  = Thickness(0, 0, 6, 0)
    btn_xlsx.Margin = Thickness(0, 0, 6, 0)
    sp_btns.Children.Add(btn_sel)
    sp_btns.Children.Add(btn_xlsx)
    sp_btns.Children.Add(btn_close)
    grid_f.Children.Add(sp_btns)

    run_scan(STATE["keywords_txt"], STATE["links"], STATE["use_conn"], STATE["use_kw"])
    refresh_ui()

    if not STATE["plates"]:
        MessageBox.Show(_msg_aucun_resultat(), TOOL_NAME,
                        MessageBoxButton.OK, MessageBoxImage.Information)

    win.ShowDialog()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
