# -*- coding: utf-8 -*-
"""
element_constraint_editor_multi.py
Script pyRevit - Revit 2024

Selection multiple : murs, sols, poteaux, ossatures.
Calcul automatique du niveau le plus proche en Z (filtre par emprise XY).
Pour la contrainte haute : si aucun niveau valide XY n'est au-dessus du Z haut,
fallback sur tous les niveaux (sans filtre XY).
"""
__doc__ = "Cale les contraintes de plusieurs éléments sur les niveaux les plus proches."
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Editeur de contraintes multiples"
# =============================================================================

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInParameter,
    BuiltInCategory,
    Level,
    Wall,
    Floor,
    FamilyInstance,
    Transaction,
    ElementId,
    DatumExtentType,
    ViewPlan,
)
from Autodesk.Revit.UI import TaskDialog

import System.Windows.Forms as WinForms
import System.Drawing as Drawing

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
_FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)


# --- Helpers ------------------------------------------------------------------
def ft_to_cm(ft): return ft * 30.48
def cm_to_ft(cm): return cm / 30.48

def detect_type(elem):
    if isinstance(elem, Wall):  return "wall"
    if isinstance(elem, Floor): return "floor"
    if isinstance(elem, FamilyInstance):
        cat = elem.Category
        if cat is None: return None
        cid = cat.Id.IntegerValue
        if cid == int(BuiltInCategory.OST_StructuralColumns): return "column"
        if cid == int(BuiltInCategory.OST_StructuralFraming): return "framing"
    return None

TYPE_LABELS = {"wall": u"Mur", "floor": u"Sol",
               "column": u"Poteau", "framing": u"Ossature"}

def get_bounds(elem):
    bb = elem.get_BoundingBox(None)
    if bb is None:
        raise Exception("Bounding box introuvable ID={}.".format(elem.Id.IntegerValue))
    cx = (bb.Min.X + bb.Max.X) / 2.0
    cy = (bb.Min.Y + bb.Max.Y) / 2.0
    return bb.Min.Z, bb.Max.Z, cx, cy


# --- Emprise XY des niveaux ---------------------------------------------------
def get_level_xy_extent(level):
    plan_views = FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
    assoc = None
    for v in plan_views:
        if not v.IsTemplate and v.GenLevel and v.GenLevel.Id == level.Id:
            assoc = v; break
    if assoc is None: return None
    curves = []
    for et in [DatumExtentType.ViewSpecific, DatumExtentType.Model]:
        try:
            raw = level.GetCurvesInView(et, assoc)
            if raw: curves = list(raw)
            if curves: break
        except Exception: pass
    if curves:
        xs, ys = [], []
        for c in curves:
            for pt in [c.GetEndPoint(0), c.GetEndPoint(1)]:
                xs.append(pt.X); ys.append(pt.Y)
        if xs: return (min(xs), min(ys), max(xs), max(ys))
    try:
        if assoc.CropBoxActive:
            cb = assoc.CropBox
            return (cb.Min.X, cb.Min.Y, cb.Max.X, cb.Max.Y)
    except Exception: pass
    return None

def point_in_extent(cx, cy, extent, tol=1.0):
    if extent is None: return True
    return (extent[0]-tol <= cx <= extent[2]+tol and
            extent[1]-tol <= cy <= extent[3]+tol)

def get_levels_with_extents():
    raw = FilteredElementCollector(doc).OfClass(Level).ToElements()
    data = [{"level": l, "elevation_ft": l.Elevation,
             "extent": get_level_xy_extent(l)} for l in raw]
    data.sort(key=lambda d: d["elevation_ft"])
    return data

def filter_levels(levels_data, cx, cy):
    """Filtre les niveaux par emprise XY. Fallback sur tous si aucun valide."""
    valid = [d for d in levels_data if point_in_extent(cx, cy, d["extent"])]
    return valid if valid else levels_data

def filter_levels_top(levels_data, cx, cy, z_top_ft):
    """
    Pour la contrainte haute :
    Filtre XY normal, mais si aucun niveau valide n'est >= z_top_ft,
    on elargit a tous les niveaux (sans filtre XY) pour trouver le
    niveau le plus proche au-dessus.
    """
    valid_xy = [d for d in levels_data if point_in_extent(cx, cy, d["extent"])]
    if not valid_xy:
        valid_xy = levels_data
    # Y a-t-il un niveau >= z_top_ft dans les valides XY ?
    above = [d for d in valid_xy if d["elevation_ft"] >= z_top_ft]
    if above:
        return valid_xy  # filtre XY suffit, il y a un niveau au-dessus
    # Fallback : on cherche dans TOUS les niveaux
    return levels_data

def find_closest(z_ft, levels_data):
    best = best_off = None
    for d in levels_data:
        off = z_ft - d["elevation_ft"]
        if best is None or abs(off) < abs(best_off):
            best, best_off = d, off
    return best, best_off


# --- Ref Z sol ----------------------------------------------------------------
def get_floor_z_ref(floor):
    p_lvl = floor.get_Parameter(BuiltInParameter.LEVEL_PARAM)
    p_off = floor.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    if p_lvl and p_lvl.AsElementId().IntegerValue != -1 and p_off:
        lvl = doc.GetElement(p_lvl.AsElementId())
        if lvl: return lvl.Elevation + p_off.AsDouble()
    bb = floor.get_BoundingBox(None)
    if bb: return bb.Max.Z
    raise Exception("Z reference sol introuvable.")


# --- Calcul auto par type -----------------------------------------------------
def compute_wall(elem, levels_data):
    z_bot, z_top, cx, cy = get_bounds(elem)
    valid_bot = filter_levels(levels_data, cx, cy)
    valid_top = filter_levels_top(levels_data, cx, cy, z_top)
    base_d, base_off = find_closest(z_bot, valid_bot)
    top_d,  top_off  = find_closest(z_top, valid_top)
    return {"elem": elem, "type": "wall",
            "z_bot_cm": ft_to_cm(z_bot), "z_top_cm": ft_to_cm(z_top),
            "valid_count": len(valid_bot),
            "base_lvl": base_d["level"], "base_off_ft": base_off, "base_off_cm": ft_to_cm(base_off),
            "top_lvl":  top_d["level"],  "top_off_ft":  top_off,  "top_off_cm":  ft_to_cm(top_off),
            "error": None}

def compute_floor(elem, levels_data):
    z_bot, z_top, cx, cy = get_bounds(elem)
    z_ref = get_floor_z_ref(elem)
    valid = filter_levels(levels_data, cx, cy)
    lvl_d, off = find_closest(z_ref, valid)
    return {"elem": elem, "type": "floor",
            "z_bot_cm": ft_to_cm(z_bot), "z_top_cm": ft_to_cm(z_top),
            "valid_count": len(valid),
            "base_lvl": lvl_d["level"], "base_off_ft": off, "base_off_cm": ft_to_cm(off),
            "top_lvl": None, "top_off_ft": None, "top_off_cm": None,
            "error": None}

def compute_column(elem, levels_data):
    z_bot, z_top, cx, cy = get_bounds(elem)
    valid_bot = filter_levels(levels_data, cx, cy)
    valid_top = filter_levels_top(levels_data, cx, cy, z_top)
    base_d, base_off = find_closest(z_bot, valid_bot)
    top_d,  top_off  = find_closest(z_top, valid_top)
    return {"elem": elem, "type": "column",
            "z_bot_cm": ft_to_cm(z_bot), "z_top_cm": ft_to_cm(z_top),
            "valid_count": len(valid_bot),
            "base_lvl": base_d["level"], "base_off_ft": base_off, "base_off_cm": ft_to_cm(base_off),
            "top_lvl":  top_d["level"],  "top_off_ft":  top_off,  "top_off_cm":  ft_to_cm(top_off),
            "error": None}

def compute_framing(elem, levels_data):
    z_bot, z_top, cx, cy = get_bounds(elem)
    z_mid = (z_bot + z_top) / 2.0
    valid = filter_levels(levels_data, cx, cy)
    lvl_d, off = find_closest(z_mid, valid)
    return {"elem": elem, "type": "framing",
            "z_bot_cm": ft_to_cm(z_bot), "z_top_cm": ft_to_cm(z_top),
            "valid_count": len(valid),
            "base_lvl": lvl_d["level"], "base_off_ft": off, "base_off_cm": ft_to_cm(off),
            "top_lvl": None, "top_off_ft": None, "top_off_cm": None,
            "error": None}


# --- Application Revit --------------------------------------------------------
def apply_result(data):
    elem = data["elem"]
    typ  = data["type"]
    if typ == "wall":
        elem.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).Set(data["base_lvl"].Id)
        elem.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).Set(data["base_off_ft"])
        elem.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(data["top_lvl"].Id)
        elem.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(data["top_off_ft"])
    elif typ == "floor":
        elem.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(data["base_off_ft"])
        elem.get_Parameter(BuiltInParameter.LEVEL_PARAM).Set(data["base_lvl"].Id)
    elif typ == "column":
        elem.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).Set(data["base_lvl"].Id)
        elem.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(data["base_off_ft"])
        elem.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM).Set(data["top_lvl"].Id)
        elem.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(data["top_off_ft"])
    elif typ == "framing":
        elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM).Set(data["base_lvl"].Id)
        elem.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM).Set(data["base_off_ft"])


# --- Rapport WinForms ---------------------------------------------------------
class ReportForm(WinForms.Form):
    def __init__(self, results, errors):
        self.results = results
        self.errors  = errors
        self._build_ui()

    def _build_ui(self):
        self.Text            = u"Rapport \u2013 Recalibrage automatique des contraintes"
        self.Size            = Drawing.Size(980, 560)
        self.StartPosition   = WinForms.FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.Sizable

        lv = WinForms.ListView()
        lv.Dock = WinForms.DockStyle.Fill
        lv.View = WinForms.View.Details
        lv.FullRowSelect = True
        lv.GridLines = True
        lv.Font = Drawing.Font("Consolas", 8.5)

        for name, w in [
            (u"ID",            70),
            (u"Type",          75),
            (u"Z bas (cm)",    85),
            (u"Z haut (cm)",   85),
            (u"Niv. valides",  75),
            (u"Niv. bas/ref.", 150),
            (u"D\u00e9cal. (cm)",   85),
            (u"Niv. haut",    150),
            (u"D\u00e9cal. (cm)",   85),
            (u"Statut",        60),
        ]:
            col = WinForms.ColumnHeader()
            col.Text = name; col.Width = w
            lv.Columns.Add(col)

        for d in self.results:
            item = WinForms.ListViewItem(str(d["elem"].Id.IntegerValue))
            item.SubItems.Add(TYPE_LABELS.get(d["type"], d["type"]))
            item.SubItems.Add(u"{:.1f}".format(d["z_bot_cm"]))
            item.SubItems.Add(u"{:.1f}".format(d["z_top_cm"]))
            item.SubItems.Add(str(d.get("valid_count", u"?")))
            item.SubItems.Add(d["base_lvl"].Name if d["base_lvl"] else u"\u2014")
            item.SubItems.Add(u"{:+.1f}".format(d["base_off_cm"]) if d["base_off_cm"] is not None else u"\u2014")
            item.SubItems.Add(d["top_lvl"].Name  if d["top_lvl"]  else u"\u2014")
            item.SubItems.Add(u"{:+.1f}".format(d["top_off_cm"])  if d["top_off_cm"]  is not None else u"\u2014")
            if d["error"]:
                item.SubItems.Add(u"ERR")
                item.ForeColor = Drawing.Color.Red
            else:
                item.SubItems.Add(u"OK")
                item.ForeColor = Drawing.Color.DarkGreen
            lv.Items.Add(item)

        ok_count  = sum(1 for d in self.results if not d["error"])
        err_count = len(self.errors)
        panel_h   = (85 if self.errors else 48) + 18   # + ligne de footer

        panel = WinForms.Panel()
        panel.Dock      = WinForms.DockStyle.Bottom
        panel.Height    = panel_h
        panel.BackColor = Drawing.Color.WhiteSmoke

        counts_by_type = {}
        for d in self.results:
            if not d["error"]:
                counts_by_type[d["type"]] = counts_by_type.get(d["type"], 0) + 1
        parts = [u"{} {}(s)".format(v, TYPE_LABELS[k]) for k, v in counts_by_type.items()]
        summary = u"  |  ".join(parts) if parts else u"Aucun"

        lbl = WinForms.Label()
        lbl.Text = u"{} \u00e9l\u00e9ment(s) modifi\u00e9(s) : {}  |  {} erreur(s)".format(
            ok_count, summary, err_count)
        lbl.Location  = Drawing.Point(10, 14)
        lbl.Size      = Drawing.Size(820, 20)
        lbl.Font      = Drawing.Font("Segoe UI", 9, Drawing.FontStyle.Bold)
        panel.Controls.Add(lbl)

        if self.errors:
            lbl_err = WinForms.Label()
            lbl_err.Text      = u" | ".join(self.errors)
            lbl_err.Location  = Drawing.Point(10, 36)
            lbl_err.Size      = Drawing.Size(840, 36)
            lbl_err.ForeColor = Drawing.Color.Red
            panel.Controls.Add(lbl_err)

        lbl_ftr = WinForms.Label()
        lbl_ftr.Text      = _FOOTER
        lbl_ftr.Location  = Drawing.Point(10, panel_h - 20)
        lbl_ftr.Size      = Drawing.Size(400, 16)
        lbl_ftr.Font      = Drawing.Font("Segoe UI", 8)
        lbl_ftr.ForeColor = Drawing.Color.FromArgb(136, 136, 136)
        panel.Controls.Add(lbl_ftr)

        btn = WinForms.Button()
        btn.Text     = u"Fermer"
        btn.Size     = Drawing.Size(90, 28)
        btn.Location = Drawing.Point(870, (panel_h - 28) // 2)
        btn.Anchor   = (WinForms.AnchorStyles.Right | WinForms.AnchorStyles.Top)
        btn.Click   += lambda s, e: self.Close()
        panel.Controls.Add(btn)

        self.Controls.Add(lv)
        self.Controls.Add(panel)


# =============================================================================
# POINT D'ENTREE
# =============================================================================
selection = uidoc.Selection.GetElementIds()

elems_by_type = {"wall": [], "floor": [], "column": [], "framing": []}
for eid in selection:
    el = doc.GetElement(eid)
    t  = detect_type(el)
    if t: elems_by_type[t].append(el)

total = sum(len(v) for v in elems_by_type.values())
if total == 0:
    TaskDialog.Show(u"Erreur",
        u"Aucun element compatible selectionne.\n"
        u"Types supportes : mur, sol, poteau, ossature.")
    import sys; sys.exit()

levels_data = get_levels_with_extents()

results = []
errors  = []
compute_fn = {"wall": compute_wall, "floor": compute_floor,
              "column": compute_column, "framing": compute_framing}

for typ, elems in elems_by_type.items():
    for elem in elems:
        try:
            results.append(compute_fn[typ](elem, levels_data))
        except Exception as ex:
            msg = u"ID {} : {}".format(elem.Id.IntegerValue, str(ex))
            errors.append(msg)
            results.append({
                "elem": elem, "type": typ,
                "z_bot_cm": 0, "z_top_cm": 0, "valid_count": 0,
                "base_lvl": None, "base_off_ft": 0, "base_off_cm": None,
                "top_lvl":  None, "top_off_ft":  0, "top_off_cm":  None,
                "error": str(ex),
            })

with Transaction(doc, u"Recalibrage automatique contraintes") as t:
    t.Start()
    for data in results:
        if data["error"] or data["base_lvl"] is None:
            continue
        try:
            apply_result(data)
        except Exception as ex:
            data["error"] = str(ex)
            errors.append(u"ID {} : {}".format(data["elem"].Id.IntegerValue, str(ex)))
    t.Commit()

WinForms.Application.Run(ReportForm(results, errors))