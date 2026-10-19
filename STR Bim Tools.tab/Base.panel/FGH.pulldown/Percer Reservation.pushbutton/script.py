# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Percer Reservation"
# =============================================================================

# Hors filet : strict minimum pour pouvoir afficher une erreur fatale
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


try:
    import os, io, json

    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import System, System.IO, System.Text, System.Windows.Markup
    import System.Windows as SW
    from System.Collections.Generic import List

    from Autodesk.Revit.DB import (
        FilteredElementCollector, Transaction, TransactionGroup, TransactionStatus,
        BuiltInCategory, BuiltInParameter, ElementId, Element,
        ElementMulticategoryFilter, ElementIntersectsSolidFilter,
        FamilyInstance, Family, FamilySymbol, Options, ViewDetailLevel, View3D,
        Solid, GeometryInstance, GeometryObject, XYZ, Transform, SolidUtils,
        CurveLoop, Line,
        GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationsType,
        InstanceVoidCutUtils, DirectShape, FreeFormElement, SaveAsOptions,
        ElementTransformUtils, IFailuresPreprocessor, FailureProcessingResult,
        FailureSeverity, WorksetKind, FilteredWorksetCollector
    )
    from Autodesk.Revit.DB.Structure import StructuralType
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

    try:
        from Autodesk.Revit.DB import UnitUtils, UnitTypeId
        USE_FORGE_UNITS = True
    except ImportError:
        USE_FORGE_UNITS = False

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # CONSTANTES METIER
    # =========================================================================
    FAMILY_PREFIX       = "FGH_RES"                 # familles de reservation attendues
    PARAM_NUM           = "PVA_RES_DEM_NumReservation"
    TARGET_WORKSET_NAME = "03_STR_RESERVATIONS"

    CUTTER_FAM_PREFIX   = "STR_PERCEMENT_"          # famille de coupe generee
    TAG_CUTTER          = "STR_PERCEMENT"           # tag Commentaires du cutter
    TAG_BOUCHON         = "STR_BOUCHON"             # tag ApplicationDataId du bouchon
    APP_ID              = "STR_BIM_TOOLS"

    # Volume minimal d'intersection retenu (m3) : sous ce seuil = simple contact
    VOL_MIN_M3          = 1.0e-6

    # Categories susceptibles d'etre traversees
    CATS_HOTES = [
        BuiltInCategory.OST_Walls,
        BuiltInCategory.OST_Floors,
        BuiltInCategory.OST_StructuralFoundation,
        BuiltInCategory.OST_StructuralFraming,
        BuiltInCategory.OST_StructuralColumns,
        BuiltInCategory.OST_Columns,
        BuiltInCategory.OST_Roofs,
        BuiltInCategory.OST_Ceilings,
    ]

    # Caracteres refuses par Revit dans un nom d'element
    _BAD_CHARS = u"\\:{}[]|;<>?`~"

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    FEET3_TO_M3 = 0.3048 ** 3

    # =========================================================================
    # HELPERS GENERIQUES
    # =========================================================================
    def _eid_int(eid):
        """ElementId -> int, compatible Revit 2024 (IntegerValue) et 2025+ (Value)."""
        if eid is None:
            return -1
        try:
            return eid.IntegerValue
        except Exception:
            pass
        try:
            return eid.Value
        except Exception:
            return -1

    def _sanitize(name):
        """Retire les caracteres refuses par Revit dans les noms d'elements."""
        out = []
        for ch in (name or u""):
            out.append(u"_" if ch in _BAD_CHARS or ch == u"/" else ch)
        return u"".join(out).strip() or u"SANS_NUM"

    def _p_str(el, pname):
        try:
            p = el.LookupParameter(pname)
            if p and p.HasValue:
                v = p.AsString()
                if v:
                    return v.strip()
                v = p.AsValueString()
                if v:
                    return v.strip()
        except Exception:
            pass
        return u""

    def _set_str(el, bip, value):
        try:
            p = el.get_Parameter(bip)
            if p is not None and not p.IsReadOnly:
                p.Set(value)
                return True
        except Exception:
            pass
        return False

    def _to_m3(vol_ft3):
        if USE_FORGE_UNITS:
            try:
                return float(UnitUtils.ConvertFromInternalUnits(vol_ft3, UnitTypeId.CubicMeters))
            except Exception:
                pass
        return float(vol_ft3) * FEET3_TO_M3

    def _cat_name(el):
        try:
            return el.Category.Name
        except Exception:
            return u"(sans categorie)"

    def _type_name(el):
        try:
            t = doc.GetElement(el.GetTypeId())
            if t is not None:
                try:
                    return t.Name
                except Exception:
                    pass
            p = el.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
            if p:
                return p.AsValueString() or u""
        except Exception:
            pass
        return u""

    def _level_name(el):
        for bip in (BuiltInParameter.LEVEL_PARAM,
                    BuiltInParameter.FAMILY_LEVEL_PARAM,
                    BuiltInParameter.WALL_BASE_CONSTRAINT,
                    BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                    BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM):
            try:
                p = el.get_Parameter(bip)
                if p is not None and p.HasValue:
                    lvl = doc.GetElement(p.AsElementId())
                    if lvl is not None:
                        return lvl.Name
            except Exception:
                pass
        return u""

    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(d):
        try:
            txt = json.dumps(d, ensure_ascii=False)
            try:
                txt = txt.decode("utf-8")          # IronPython 2.7 : str -> unicode
            except Exception:
                pass
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                f.write(txt)
        except Exception:
            pass

    # =========================================================================
    # PHASES
    # =========================================================================
    def _phase_order():
        """{id_phase: rang chronologique}. doc.Phases est deja dans l'ordre."""
        order = {}
        try:
            i = 0
            for ph in doc.Phases:
                order[_eid_int(ph.Id)] = i
                i += 1
        except Exception:
            pass
        return order

    def _phase_of(el, bip):
        try:
            p = el.get_Parameter(bip)
            if p is not None and p.HasValue:
                return p.AsElementId()
        except Exception:
            pass
        return ElementId.InvalidElementId

    def _phase_name(eid):
        try:
            ph = doc.GetElement(eid)
            if ph is not None:
                return ph.Name
        except Exception:
            pass
        return u"-"

    # =========================================================================
    # GEOMETRIE
    # =========================================================================
    def _any_3d_view():
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if not v.IsTemplate:
                    return v
            except Exception:
                pass
        return None

    def _collect_solids(gel, out):
        if gel is None:
            return
        for g in gel:
            try:
                if isinstance(g, Solid):
                    if g.Volume > 1.0e-9 and g.Faces.Size > 0:
                        out.append(g)
                elif isinstance(g, GeometryInstance):
                    _collect_solids(g.GetInstanceGeometry(), out)
            except Exception:
                pass

    def get_solids(el):
        """Solides de l'element en coordonnees projet.

        Repli sur une vue 3D si la lecture en detail fin ne rend rien : certains
        elements (assemblages, ossatures avec platines) n'exposent leur geometrie
        que via Options.View.
        """
        res = []
        try:
            opts = Options()
            opts.ComputeReferences       = False
            opts.IncludeNonVisibleObjects = False
            opts.DetailLevel             = ViewDetailLevel.Fine
            _collect_solids(el.get_Geometry(opts), res)
        except Exception:
            pass
        if res:
            return res
        try:
            v3d = _any_3d_view()
            if v3d is not None:
                opts = Options()
                opts.ComputeReferences       = False
                opts.IncludeNonVisibleObjects = False
                opts.View                    = v3d
                _collect_solids(el.get_Geometry(opts), res)
        except Exception:
            pass
        return res

    def bbox_solid(el):
        """Boite englobante de l'element convertie en solide (geometrie de secours)."""
        try:
            bb = el.get_BoundingBox(None)
            if bb is None:
                return None
            mn, mx = bb.Min, bb.Max
            if bb.Transform is not None and not bb.Transform.IsIdentity:
                mn = bb.Transform.OfPoint(bb.Min)
                mx = bb.Transform.OfPoint(bb.Max)
            x0, x1 = min(mn.X, mx.X), max(mn.X, mx.X)
            y0, y1 = min(mn.Y, mx.Y), max(mn.Y, mx.Y)
            z0, z1 = min(mn.Z, mx.Z), max(mn.Z, mx.Z)
            if (x1 - x0) < 1e-6 or (y1 - y0) < 1e-6 or (z1 - z0) < 1e-6:
                return None
            pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
            loop = CurveLoop()
            for i in range(4):
                loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
            loops = List[CurveLoop]()
            loops.Add(loop)
            return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)
        except Exception:
            return None

    def solids_center(solids):
        """Centre de la boite englobante de la liste de solides (coordonnees projet).

        La boite d'un solide est exprimee dans son repere propre : les 8 sommets
        sont transformes, pas seulement Min et Max.
        """
        mnx = mny = mnz = 1.0e12
        mxx = mxy = mxz = -1.0e12
        for s in solids:
            try:
                bb = s.GetBoundingBox()
                for ix in (bb.Min.X, bb.Max.X):
                    for iy in (bb.Min.Y, bb.Max.Y):
                        for iz in (bb.Min.Z, bb.Max.Z):
                            p = bb.Transform.OfPoint(XYZ(ix, iy, iz))
                            mnx, mny, mnz = min(mnx, p.X), min(mny, p.Y), min(mnz, p.Z)
                            mxx, mxy, mxz = max(mxx, p.X), max(mxy, p.Y), max(mxz, p.Z)
            except Exception:
                pass
        if mnx > 1.0e11:
            return XYZ(0, 0, 0)
        return XYZ((mnx + mxx) / 2.0, (mny + mxy) / 2.0, (mnz + mxz) / 2.0)

    def intersect_solids(host_solids, res_solids):
        """Solides d'intersection hote x reservation + volume total (ft3)."""
        out, vol = [], 0.0
        for hs in host_solids:
            for rs in res_solids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        hs, rs, BooleanOperationsType.Intersect)
                except Exception:
                    continue
                if inter is None:
                    continue
                try:
                    if inter.Volume > 1.0e-9:
                        out.append(inter)
                        vol += inter.Volume
                except Exception:
                    pass
        return out, vol

    # =========================================================================
    # GESTION DES ARTEFACTS CREES PAR L'OUTIL
    # =========================================================================
    def cutter_family_name(num):
        return CUTTER_FAM_PREFIX + _sanitize(num)

    def find_cutter_family(num):
        target = cutter_family_name(num)
        for f in FilteredElementCollector(doc).OfClass(Family):
            try:
                if f.Name == target:
                    return f
            except Exception:
                pass
        return None

    def find_cutter_instances(num):
        fam = find_cutter_family(num)
        if fam is None:
            return []
        wanted = set()
        try:
            for sid in fam.GetFamilySymbolIds():
                wanted.add(_eid_int(sid))
        except Exception:
            pass
        res = []
        for fi in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
            try:
                if _eid_int(fi.GetTypeId()) in wanted:
                    res.append(fi)
            except Exception:
                pass
        return res

    def find_bouchons(num):
        """DirectShape bouchons de la reservation : tag dans ApplicationDataId."""
        prefix = u"{}|{}|".format(TAG_BOUCHON, _sanitize(num))
        res = []
        for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
            try:
                if (ds.ApplicationDataId or u"").startswith(prefix):
                    res.append(ds)
            except Exception:
                pass
        return res

    def cleanup(num):
        """Retire coupes, cutters, bouchons et famille de coupe de la reservation.

        A appeler dans une transaction ouverte. Retourne (hotes_liberes, nb_bouchons).
        """
        hosts_freed = []
        for inst in find_cutter_instances(num):
            try:
                for hid in InstanceVoidCutUtils.GetElementsBeingCut(inst):
                    host = doc.GetElement(hid)
                    if host is None:
                        continue
                    try:
                        InstanceVoidCutUtils.RemoveInstanceVoidCut(doc, host, inst)
                        hosts_freed.append(host)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if inst.Pinned:
                    inst.Pinned = False
            except Exception:
                pass
            try:
                doc.Delete(inst.Id)
            except Exception:
                pass

        nb_b = 0
        for ds in find_bouchons(num):
            try:
                if ds.Pinned:
                    ds.Pinned = False
            except Exception:
                pass
            try:
                doc.Delete(ds.Id)
                nb_b += 1
            except Exception:
                pass

        fam = find_cutter_family(num)
        if fam is not None:
            try:
                doc.Delete(fam.Id)
            except Exception:
                pass

        return hosts_freed, nb_b

    # =========================================================================
    # FAMILLE DE COUPE GENEREE
    # =========================================================================
    _TPL_KEYS_GOOD = (u"generic model", u"modele generique", u"modele-generique")
    _TPL_KEYS_BAD  = (u"face", u"wall", u"mur", u"floor", u"sol", u"ceiling", u"plafond",
                      u"roof", u"toit", u"line", u"ligne", u"adaptive", u"adaptatif",
                      u"two level", u"deux niveaux", u"pattern", u"motif", u"curtain",
                      u"annotation", u"titleblock", u"cartouche")

    def _norm(s):
        s = (s or u"").lower()
        for a, b in ((u"\xe8", u"e"), (u"\xe9", u"e"), (u"\xea", u"e"),
                     (u"\xe0", u"a"), (u"\xe2", u"a"), (u"\xee", u"i"),
                     (u"\xf4", u"o"), (u"\xfb", u"u"), (u"\xe7", u"c")):
            s = s.replace(a, b)
        return s

    def find_generic_template():
        """Chemin du gabarit de famille 'Modele generique metrique' (.rft)."""
        prefs = _load_prefs()
        p = prefs.get("template_rft", u"")
        if p and os.path.isfile(p):
            return p

        roots = []
        try:
            if app.FamilyTemplatePath and os.path.isdir(app.FamilyTemplatePath):
                roots.append(app.FamilyTemplatePath)
        except Exception:
            pass
        for extra in (r"C:\ProgramData\Autodesk\RVT " + str(app.VersionNumber) + r"\Family Templates",):
            if os.path.isdir(extra):
                roots.append(extra)

        best = None
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                for fn in filenames:
                    if not fn.lower().endswith(".rft"):
                        continue
                    n = _norm(fn)
                    if not any(k in n for k in _TPL_KEYS_GOOD):
                        continue
                    if any(k in n for k in _TPL_KEYS_BAD):
                        continue
                    full = os.path.join(dirpath, fn)
                    score = 0
                    if u"metric" in n or u"metrique" in n or n.startswith(u"m_"):
                        score += 10
                    score -= len(fn)
                    if best is None or score > best[0]:
                        best = (score, full)
        return best[1] if best else None

    def ask_template_path():
        """Boite de dialogue pour designer le gabarit .rft manuellement."""
        try:
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import OpenFileDialog, DialogResult
            dlg = OpenFileDialog()
            dlg.Title  = "Selectionnez le gabarit de famille Modele generique metrique (.rft)"
            dlg.Filter = "Gabarit de famille (*.rft)|*.rft"
            try:
                if app.FamilyTemplatePath:
                    dlg.InitialDirectory = app.FamilyTemplatePath
            except Exception:
                pass
            if dlg.ShowDialog() == DialogResult.OK and dlg.FileName:
                prefs = _load_prefs()
                prefs["template_rft"] = dlg.FileName
                _save_prefs(prefs)
                return dlg.FileName
        except Exception:
            pass
        return None

    def build_cutter_family(num, solids, origin):
        """Cree et charge une famille de coupe (vides) et retourne son FamilySymbol.

        Les solides sont recentres sur origin : la famille contient la geometrie
        autour de son origine, l'occurrence est ensuite placee sur origin.
        A appeler HORS transaction (LoadFamily ouvre la sienne).
        """
        tpl = find_generic_template()
        if not tpl:
            tpl = ask_template_path()
        if not tpl:
            raise Exception(u"Gabarit de famille 'Modele generique metrique' introuvable. "
                            u"Relancez l'outil et designez le fichier .rft.")

        famdoc = app.NewFamilyDocument(tpl)
        if famdoc is None:
            raise Exception(u"Impossible de creer le document de famille depuis :\n" + tpl)

        fam_name = cutter_family_name(num)
        tmp_dir  = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "STR_BimTools")
        try:
            if not os.path.isdir(tmp_dir):
                os.makedirs(tmp_dir)
        except Exception:
            tmp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
        tmp_path = os.path.join(tmp_dir, fam_name + ".rfa")

        tr = Transform.CreateTranslation(XYZ(-origin.X, -origin.Y, -origin.Z))

        tf = Transaction(famdoc, "STR - Geometrie de coupe")
        tf.Start()
        try:
            nb = 0
            for s in solids:
                try:
                    local = SolidUtils.CreateTransformed(s, tr)
                    ff = FreeFormElement.Create(famdoc, local)
                    ok = False
                    try:
                        p = ff.get_Parameter(BuiltInParameter.ELEMENT_IS_CUTTING)
                        if p is not None and not p.IsReadOnly:
                            p.Set(1)
                            ok = True
                    except Exception:
                        pass
                    if not ok:
                        for pname in (u"Solid/Void", u"Plein/Vide", u"Massif/Vide"):
                            try:
                                p = ff.LookupParameter(pname)
                                if p is not None and not p.IsReadOnly:
                                    p.Set(1)
                                    ok = True
                                    break
                            except Exception:
                                pass
                    if not ok:
                        raise Exception(u"impossible de basculer la forme en vide "
                                        u"(parametre Plein/Vide inaccessible)")
                    nb += 1
                except Exception as ex_s:
                    raise Exception(u"Creation de la geometrie de coupe : {}".format(ex_s))
            if nb == 0:
                raise Exception(u"Aucune geometrie de coupe creee.")

            try:
                pcut = famdoc.OwnerFamily.get_Parameter(
                    BuiltInParameter.FAMILY_ALLOW_CUT_WITH_VOIDS)
                if pcut is not None and not pcut.IsReadOnly:
                    pcut.Set(1)
            except Exception:
                pass
            tf.Commit()
        except Exception:
            if tf.GetStatus() == TransactionStatus.Started:
                tf.RollBack()
            try:
                famdoc.Close(False)
            except Exception:
                pass
            raise

        try:
            sao = SaveAsOptions()
            sao.OverwriteExistingFile = True
            famdoc.SaveAs(tmp_path, sao)
        except Exception as ex_sv:
            try:
                famdoc.Close(False)
            except Exception:
                pass
            raise Exception(u"Enregistrement de la famille de coupe : {}".format(ex_sv))

        fam = None
        try:
            fam = famdoc.LoadFamily(doc)
        except Exception:
            fam = None
        try:
            famdoc.Close(False)
        except Exception:
            pass
        if fam is None:
            try:
                doc.LoadFamily(tmp_path)
            except Exception:
                pass
            fam = find_cutter_family(num)
        if fam is None:
            raise Exception(u"Chargement de la famille de coupe impossible.")

        sym = None
        try:
            for sid in fam.GetFamilySymbolIds():
                sym = doc.GetElement(sid)
                break
        except Exception:
            pass
        if sym is None:
            raise Exception(u"Type de famille de coupe introuvable.")
        return sym

    # =========================================================================
    # GESTION DES AVERTISSEMENTS
    # =========================================================================
    class WarnSwallower(IFailuresPreprocessor):
        def PreprocessFailures(self, fa):
            try:
                for f in fa.GetFailureMessages():
                    if f.GetSeverity() == FailureSeverity.Warning:
                        fa.DeleteWarning(f)
            except Exception:
                pass
            return FailureProcessingResult.Continue

    def _quiet(t):
        try:
            o = t.GetFailureHandlingOptions()
            o.SetFailuresPreprocessor(WarnSwallower())
            o.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(o)
        except Exception:
            pass

    # =========================================================================
    # WORKSET
    # =========================================================================
    def target_workset_id():
        try:
            if not doc.IsWorkshared:
                return None
            for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
                if ws.Name == TARGET_WORKSET_NAME:
                    return ws.Id
        except Exception:
            pass
        return None

    def set_workset(el, wsid):
        if wsid is None:
            return
        try:
            p = el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
            if p is not None and not p.IsReadOnly:
                p.Set(_eid_int(wsid))
        except Exception:
            pass

    # =========================================================================
    # SELECTION DE LA RESERVATION
    # =========================================================================
    class ResFilter(ISelectionFilter):
        def AllowElement(self, e):
            try:
                return isinstance(e, FamilyInstance)
            except Exception:
                return False

        def AllowReference(self, r, p):
            return False

    def pick_reservation():
        """Element selectionne, sinon selection interactive. Retourne None si annule."""
        try:
            ids = list(uidoc.Selection.GetElementIds())
        except Exception:
            ids = []
        cands = []
        for i in ids:
            e = doc.GetElement(i)
            if isinstance(e, FamilyInstance):
                cands.append(e)
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            TaskDialog.Show(TOOL_NAME,
                            u"Cet outil traite une seule reservation a la fois.\n\n"
                            u"{} elements sont selectionnes.".format(len(cands)))
            return None
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element, ResFilter(),
                "Selectionnez la reservation a percer")
            return doc.GetElement(ref.ElementId)
        except Exception:
            return None

    # =========================================================================
    # ANALYSE
    # =========================================================================
    class HostRow(object):
        """Ligne du tableau : un element traverse."""
        def __init__(self, host, inter_solids, vol_m3, eligible, motif,
                     deja_perce, besoin_bouchon, ph_host, ph_dem):
            # L'analyse se deroule dans une transaction annulee : on memorise
            # l'identifiant, pas l'objet Element, qui serait relu apres coup.
            self.HostEid    = host.Id
            self.HostInt    = _eid_int(host.Id)
            self.Solids     = inter_solids
            self.PhHost     = ph_host
            self.PhDem      = ph_dem
            self.Eligible   = eligible
            self.Bouchon    = besoin_bouchon
            self.DejaPerce  = deja_perce
            self.IsSelected = bool(eligible)

            self.Cat   = _cat_name(host)
            self.Typ   = _type_name(host)
            self.Niv   = _level_name(host)
            self.Phase = _phase_name(ph_host)
            self.Vol   = u"{:.4f}".format(vol_m3) if vol_m3 > 0 else u"-"
            self.Bch   = u"oui" if besoin_bouchon else u"non"
            if not eligible:
                self.Etat = motif
            elif deja_perce:
                self.Etat = u"deja perce (sera refait)"
            else:
                self.Etat = u"a percer"

        def toggle(self):
            if self.Eligible:
                self.IsSelected = not self.IsSelected

    def analyse(res, res_solids):
        """Analyse dans une transaction annulee : les percements existants sont
        retires le temps de mesurer la geometrie reelle des hotes, puis restaures.
        Retourne (rows, deja_perce_global)."""
        num       = _p_str(res, PARAM_NUM) or u"{}".format(_eid_int(res.Id))
        order     = _phase_order()
        ph_res    = _phase_of(res, BuiltInParameter.PHASE_CREATED)
        rang_res  = order.get(_eid_int(ph_res), 10 ** 6)

        rows = []
        deja = False

        t = Transaction(doc, "STR - Analyse percement")
        _quiet(t)
        t.Start()
        try:
            hosts_freed, _ = cleanup(num)
            deja = len(hosts_freed) > 0
            doc.Regenerate()

            # candidats : intersection geometrique + hotes precedemment perces
            cats = List[BuiltInCategory]()
            for c in CATS_HOTES:
                cats.Add(c)
            cand = {}
            for s in res_solids:
                try:
                    col = (FilteredElementCollector(doc)
                           .WherePasses(ElementMulticategoryFilter(cats))
                           .WhereElementIsNotElementType()
                           .WherePasses(ElementIntersectsSolidFilter(s)))
                    for e in col:
                        cand[_eid_int(e.Id)] = e
                except Exception:
                    pass
            for h in hosts_freed:
                cand[_eid_int(h.Id)] = h
            cand.pop(_eid_int(res.Id), None)
            freed_ids = set([_eid_int(x.Id) for x in hosts_freed])

            for key in sorted(cand.keys()):
                host = cand[key]
                try:
                    hs = get_solids(host)
                    inter, vol_ft3 = intersect_solids(hs, res_solids)
                    vol_m3 = _to_m3(vol_ft3)
                    if vol_m3 < VOL_MIN_M3 and _eid_int(host.Id) not in freed_ids:
                        continue

                    eligible, motif = True, u""
                    try:
                        if not InstanceVoidCutUtils.CanBeCutWithVoid(host):
                            eligible = False
                            motif = u"non decoupable par vide"
                    except Exception:
                        eligible = False
                        motif = u"eligibilite indeterminee"
                    if eligible and not inter:
                        eligible = False
                        motif = u"intersection non calculable"

                    ph_h  = _phase_of(host, BuiltInParameter.PHASE_CREATED)
                    ph_d  = _phase_of(host, BuiltInParameter.PHASE_DEMOLISHED)
                    r_h   = order.get(_eid_int(ph_h), 10 ** 6)
                    r_d   = order.get(_eid_int(ph_d), None)
                    besoin = (r_h < rang_res) and (r_d is None or r_d > rang_res)

                    rows.append(HostRow(host, inter, vol_m3, eligible, motif,
                                        _eid_int(host.Id) in freed_ids,
                                        besoin, ph_h, ph_d))
                except Exception:
                    pass
        finally:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()

        return rows, deja, num, ph_res

    # =========================================================================
    # APPLICATION
    # =========================================================================
    def appliquer(res, num, res_solids, rows, faire_bouchons, ph_res):
        """Reconstruit integralement le percement de la reservation."""
        origin = solids_center(res_solids)
        wsid   = target_workset_id()
        cibles = [r for r in rows if r.IsSelected and r.Eligible]

        stats = {"coupes": 0, "bouchons": 0, "echecs": []}

        tg = TransactionGroup(doc, u"STR - Percement reservation {}".format(num))
        tg.Start()
        try:
            # 1 - nettoyage de l'etat anterieur
            t1 = Transaction(doc, u"STR - Nettoyage percement")
            _quiet(t1)
            t1.Start()
            cleanup(num)
            t1.Commit()

            # 2 - famille de coupe (hors transaction : LoadFamily ouvre la sienne)
            sym = build_cutter_family(num, res_solids, origin)

            # 3 - placement, coupes et bouchons
            t2 = Transaction(doc, u"STR - Percement reservation")
            _quiet(t2)
            t2.Start()
            try:
                if not sym.IsActive:
                    sym.Activate()
                    doc.Regenerate()

                inst = doc.Create.NewFamilyInstance(origin, sym, StructuralType.NonStructural)
                doc.Regenerate()

                # garantie de position : certains gabarits recalent l'occurrence
                try:
                    loc = inst.Location.Point
                    d = XYZ(origin.X - loc.X, origin.Y - loc.Y, origin.Z - loc.Z)
                    if d.GetLength() > 1.0e-9:
                        ElementTransformUtils.MoveElement(doc, inst.Id, d)
                        doc.Regenerate()
                except Exception:
                    pass

                _set_str(inst, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                         u"{}|{}".format(TAG_CUTTER, num))
                _set_str(inst, BuiltInParameter.ALL_MODEL_MARK,
                         u"{}|{}".format(TAG_CUTTER, num))
                set_workset(inst, wsid)

                for r in cibles:
                    host = doc.GetElement(r.HostEid)
                    if host is None:
                        stats["echecs"].append(u"{} {} : element introuvable".format(
                            r.Cat, r.HostInt))
                        continue
                    try:
                        InstanceVoidCutUtils.AddInstanceVoidCut(doc, host, inst)
                        stats["coupes"] += 1
                    except Exception as ex_c:
                        stats["echecs"].append(u"{} {} : {}".format(
                            r.Cat, r.HostInt, ex_c))
                        continue

                    if faire_bouchons and r.Bouchon and r.Solids:
                        try:
                            shp = List[GeometryObject]()
                            for s in r.Solids:
                                shp.Add(s)
                            ds = DirectShape.CreateElement(
                                doc, ElementId(BuiltInCategory.OST_GenericModel))
                            ds.ApplicationId     = APP_ID
                            ds.ApplicationDataId = u"{}|{}|{}".format(
                                TAG_BOUCHON, _sanitize(num), r.HostInt)
                            ds.SetShape(shp)
                            try:
                                ds.Name = _sanitize(u"STR_BOUCHON_{}".format(num))
                            except Exception:
                                pass
                            _set_str(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                                     u"{}|{}|{}".format(TAG_BOUCHON, num, r.HostInt))

                            okp = True
                            try:
                                p = ds.get_Parameter(BuiltInParameter.PHASE_CREATED)
                                if p is not None and not p.IsReadOnly:
                                    p.Set(r.PhHost)
                                else:
                                    okp = False
                            except Exception:
                                okp = False
                            try:
                                p = ds.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED)
                                if p is not None and not p.IsReadOnly:
                                    p.Set(ph_res)
                                else:
                                    okp = False
                            except Exception:
                                okp = False

                            set_workset(ds, wsid)
                            if not okp:
                                stats["echecs"].append(
                                    u"Bouchon {} {} : phases non modifiables".format(
                                        r.Cat, r.HostInt))
                            else:
                                stats["bouchons"] += 1
                        except Exception as ex_b:
                            stats["echecs"].append(u"Bouchon {} {} : {}".format(
                                r.Cat, r.HostInt, ex_b))

                try:
                    inst.Pinned = True
                except Exception:
                    pass
                t2.Commit()
            except Exception:
                if t2.GetStatus() == TransactionStatus.Started:
                    t2.RollBack()
                raise

            tg.Assimilate()
        except Exception:
            try:
                if tg.GetStatus() == TransactionStatus.Started:
                    tg.RollBack()
            except Exception:
                pass
            raise

        return stats

    def retirer(num):
        stats = {"hotes": 0, "bouchons": 0}
        t = Transaction(doc, u"STR - Retrait percement {}".format(num))
        _quiet(t)
        t.Start()
        try:
            hosts, nb_b = cleanup(num)
            stats["hotes"]    = len(hosts)
            stats["bouchons"] = nb_b
            t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise
        return stats

    # =========================================================================
    # UI
    # =========================================================================
    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1020" Height="600" MinWidth="820" MinHeight="460"
    WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
      <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
    </Border>

    <Border Grid.Row="1" Background="#FAFCFF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="12,8">
      <StackPanel>
        <TextBlock x:Name="lbl_res"  FontSize="12" FontWeight="SemiBold" Foreground="#2F6496"/>
        <TextBlock x:Name="lbl_res2" FontSize="11" Foreground="#444444" Margin="0,3,0,0"/>
        <TextBlock x:Name="lbl_warn" FontSize="11" Foreground="#C0392B" Margin="0,3,0,0"
                   TextWrapping="Wrap" Visibility="Collapsed"/>
      </StackPanel>
    </Border>

    <Border Grid.Row="2" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="8,7">
      <StackPanel Orientation="Horizontal">
        <Button x:Name="btn_all"  Width="110" Height="26" Margin="0,0,6,0"
                Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        <Button x:Name="btn_none" Width="110" Height="26" Margin="0,0,12,0"
                Background="#E74C3C" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        <TextBlock x:Name="lbl_count" FontSize="11" Foreground="#2F6496"
                   VerticalAlignment="Center" FontWeight="SemiBold"/>
      </StackPanel>
    </Border>

    <DataGrid x:Name="dg_main" Grid.Row="3" Margin="8,8,8,4"
              AutoGenerateColumns="False" IsReadOnly="True"
              AlternatingRowBackground="#E8F0FA" RowBackground="White"
              GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
              HeadersVisibility="Column" CanUserResizeColumns="True" CanUserSortColumns="True"
              FontSize="12">
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,3"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <DataGridCheckBoxColumn x:Name="col_sel" Binding="{Binding IsSelected}"
                                Width="40" SortMemberPath="IsSelected"/>
        <DataGridTextColumn x:Name="col_cat"  Binding="{Binding Cat}"   Width="120"/>
        <DataGridTextColumn x:Name="col_typ"  Binding="{Binding Typ}"   Width="*" MinWidth="200"/>
        <DataGridTextColumn x:Name="col_niv"  Binding="{Binding Niv}"   Width="95"/>
        <DataGridTextColumn x:Name="col_pha"  Binding="{Binding Phase}" Width="135"/>
        <DataGridTextColumn x:Name="col_vol"  Binding="{Binding Vol}"   Width="85"/>
        <DataGridTextColumn x:Name="col_bch"  Binding="{Binding Bch}"   Width="65"/>
        <DataGridTextColumn x:Name="col_eta"  Binding="{Binding Etat}"  Width="*" MinWidth="170"/>
      </DataGrid.Columns>
    </DataGrid>

    <Border Grid.Row="4" Background="#FAFCFF" BorderBrush="#C0D0E0"
            BorderThickness="0,1,0,0" Padding="12,7">
      <StackPanel>
        <CheckBox x:Name="chk_bouchon" FontSize="11" IsChecked="True"/>
        <TextBlock x:Name="lbl_bouchon" FontSize="10" Foreground="#888888"
                   Margin="20,2,0,0" TextWrapping="Wrap"/>
      </StackPanel>
    </Border>

    <Border Grid.Row="5" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_remove" Width="150" Height="28" Margin="4,0,0,0"
                  Background="#E74C3C" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_apply"  Width="130" Height="28" Margin="6,0,0,0"
                  Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close"  Width="90"  Height="28" Margin="6,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

    def run_window(res, num, rows, deja, res_solids, ph_res, secours):
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        win = System.Windows.Markup.XamlReader.Load(stream)

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        win.FindName("lbl_footer").Text = _FOOTER

        try:
            fam_res = res.Symbol.Family.Name
        except Exception:
            fam_res = u"?"
        win.FindName("lbl_res").Text = u"Réservation n° {}   —   {} / {}".format(
            num, fam_res, _type_name(res))
        win.FindName("lbl_res2").Text = u"Phase : {}   |   Id : {}   |   {} élément(s) traversé(s)".format(
            _phase_name(ph_res), _eid_int(res.Id), len(rows))

        warns = []
        if secours:
            warns.append(u"Géométrie du vide absente de la famille : la boîte englobante "
                         u"de la réservation a été utilisée. Vérifiez le résultat.")
        if deja:
            warns.append(u"Cette réservation est déjà percée. « Appliquer » retire tout "
                         u"puis reconstruit avec la géométrie actuelle.")
        if warns:
            w = win.FindName("lbl_warn")
            w.Text = u"\n".join(warns)
            w.Visibility = SW.Visibility.Visible

        for nm, txt in ((u"col_sel", u""), (u"col_cat", u"Catégorie"), (u"col_typ", u"Type"),
                        (u"col_niv", u"Niveau"), (u"col_pha", u"Phase de l'hôte"),
                        (u"col_vol", u"Volume m³"), (u"col_bch", u"Bouchon"),
                        (u"col_eta", u"État")):
            c = win.FindName(nm)
            if c is not None:
                c.Header = txt

        win.FindName("btn_all").Content    = u"Tout cocher"
        win.FindName("btn_none").Content   = u"Tout décocher"
        win.FindName("btn_remove").Content = u"Retirer le percement"
        win.FindName("btn_apply").Content  = u"Appliquer"
        win.FindName("btn_close").Content  = u"Fermer"
        win.FindName("chk_bouchon").Content = \
            u"Créer les bouchons de phase dans les éléments existants"
        win.FindName("lbl_bouchon").Text = (
            u"Le volume percé dans un élément existant est reconstruit à l'identique, "
            u"créé dans la phase de l'hôte et démoli dans la phase de la réservation : "
            u"le trou n'apparaît qu'à partir de la nouvelle construction.")

        dg = win.FindName("dg_main")
        dg.ItemsSource = rows

        lbl_count = win.FindName("lbl_count")

        def refresh_count():
            n = len([r for r in rows if r.IsSelected and r.Eligible])
            ne = len([r for r in rows if not r.Eligible])
            txt = u"{} élément(s) sélectionné(s) sur {}".format(n, len(rows))
            if ne:
                txt += u"   —   {} non éligible(s)".format(ne)
            lbl_count.Text = txt

        def redraw():
            src = dg.ItemsSource
            dg.ItemsSource = None
            dg.ItemsSource = src
            refresh_count()

        def on_cell(sender, e):
            try:
                if dg.CurrentColumn is not None and dg.CurrentColumn.DisplayIndex == 0:
                    if dg.CurrentItem is not None:
                        dg.CurrentItem.toggle()
                        redraw()
            except Exception:
                pass

        dg.CurrentCellChanged += on_cell

        def on_all(s, e):
            for r in rows:
                if r.Eligible:
                    r.IsSelected = True
            redraw()

        def on_none(s, e):
            for r in rows:
                r.IsSelected = False
            redraw()

        state = {"action": None}

        def on_apply(s, e):
            if not [r for r in rows if r.IsSelected and r.Eligible]:
                SW.MessageBox.Show(u"Aucun élément sélectionné.", TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
                return
            state["action"] = "apply"
            state["bouchon"] = bool(win.FindName("chk_bouchon").IsChecked)
            win.Close()

        def on_remove(s, e):
            state["action"] = "remove"
            win.Close()

        win.FindName("btn_all").Click    += on_all
        win.FindName("btn_none").Click   += on_none
        win.FindName("btn_apply").Click  += on_apply
        win.FindName("btn_remove").Click += on_remove
        win.FindName("btn_close").Click  += lambda s, e: win.Close()

        win.FindName("btn_remove").IsEnabled = bool(deja)

        refresh_count()
        win.ShowDialog()
        return state

    # =========================================================================
    # MAIN
    # =========================================================================
    def main():
        res = pick_reservation()
        if res is None:
            return

        try:
            fam_name = res.Symbol.Family.Name
        except Exception:
            fam_name = u""
        if fam_name and not fam_name.startswith(FAMILY_PREFIX):
            td = TaskDialog(TOOL_NAME)
            td.MainInstruction = u"Famille inattendue"
            td.MainContent = (u"L'element selectionne appartient a la famille « {} », "
                              u"qui ne commence pas par « {} ».\n\n"
                              u"Continuer quand meme ?".format(fam_name, FAMILY_PREFIX))
            td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            if td.Show() != TaskDialogResult.Yes:
                return

        res_solids = get_solids(res)
        secours = False
        if not res_solids:
            td = TaskDialog(TOOL_NAME)
            td.MainInstruction = u"Geometrie du vide introuvable"
            td.MainContent = (
                u"La famille de reservation n'expose aucun volume exploitable : le vide "
                u"y est probablement modelise sans l'option de coupe, il est donc "
                u"invisible pour l'API.\n\n"
                u"Utiliser la boite englobante de la reservation comme volume de "
                u"percement ?\n\n"
                u"Attention : pour une reservation cylindrique ou oblique, la boite "
                u"englobante donne un percement plus large que la reservation reelle.")
            td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            if td.Show() != TaskDialogResult.Yes:
                return
            bs = bbox_solid(res)
            if bs is None:
                TaskDialog.Show(TOOL_NAME, u"Boite englobante inexploitable. Abandon.")
                return
            res_solids = [bs]
            secours = True

        rows, deja, num, ph_res = analyse(res, res_solids)

        if not rows and not deja:
            TaskDialog.Show(TOOL_NAME,
                            u"Cette reservation ne traverse aucun element des categories "
                            u"analysees (murs, sols, fondations, ossatures, poteaux, "
                            u"toitures, plafonds).")
            return

        state = run_window(res, num, rows, deja, res_solids, ph_res, secours)
        act = state.get("action")

        if act == "apply":
            stats = appliquer(res, num, res_solids, rows,
                              state.get("bouchon", True), ph_res)
            msg = (u"Reservation n° {}\n\n"
                   u"{} element(s) perce(s)\n"
                   u"{} bouchon(s) de phase cree(s)").format(
                num, stats["coupes"], stats["bouchons"])
            td = TaskDialog(TOOL_NAME)
            td.MainInstruction = u"Percement applique"
            td.MainContent = msg
            if stats["echecs"]:
                td.ExpandedContent = u"\n".join(stats["echecs"][:30])
            td.Show()

        elif act == "remove":
            stats = retirer(num)
            TaskDialog.Show(TOOL_NAME,
                            u"Reservation n° {}\n\n"
                            u"{} element(s) libere(s)\n"
                            u"{} bouchon(s) supprime(s)".format(
                                num, stats["hotes"], stats["bouchons"]))

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
