# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.6.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Bissectrice"
# =============================================================================
#  v1.6.0 - Selection elargie : lignes simples, ossatures, poteaux, murs,
#           ou tout element avec une LocationCurve lineaire.
#           Extraction de la direction via GeometryCurve ou LocationCurve.
# =============================================================================

import clr, math, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Line, XYZ, LocationCurve,
    Transaction, TransactionStatus,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit

doc   = revit.doc
uidoc = revit.uidoc


# =============================================================================
# Extraction de la ligne depuis n'importe quel element compatible
# =============================================================================
def get_line(elem):
    """
    Retourne la courbe Line de l'element, quelle que soit sa nature :
      - Ligne simple / ligne de modele (GeometryCurve)
      - Ossature, poteau, mur, poutre... (LocationCurve)
    Retourne None si aucune geometrie lineaire droite n'est trouvable.
    """
    # 1. CurveElement (lignes simples, lignes de modele)
    try:
        c = elem.GeometryCurve
        if isinstance(c, Line):
            return c
    except Exception:
        pass
    # 2. Element avec LocationCurve (ossatures, poteaux, murs...)
    try:
        loc = elem.Location
        if isinstance(loc, LocationCurve):
            c = loc.Curve
            if isinstance(c, Line):
                return c
    except Exception:
        pass
    return None


# =============================================================================
# Filtre — tout element ayant une geometrie lineaire droite
# =============================================================================
class LinearElementFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return get_line(elem) is not None
    def AllowReference(self, ref, point):
        return True


# =============================================================================
# Geometrie — projection dans le repere de la vue
# =============================================================================
def dot3(ax, ay, az, bx, by, bz):
    return ax*bx + ay*by + az*bz


def normalize_2d(du, dv):
    n = math.sqrt(du*du + dv*dv)
    if n < 1e-9:
        return None
    return du/n, dv/n


# =============================================================================
# MAIN
# =============================================================================
def main():
    flt         = LinearElementFilter()
    active_view = uidoc.ActiveView

    # Repere de la vue : u = droite, v = haut
    vr = active_view.RightDirection
    vu = active_view.UpDirection
    rx, ry, rz = float(vr.X), float(vr.Y), float(vr.Z)
    ux, uy, uz = float(vu.X), float(vu.Y), float(vu.Z)

    # ── Selection element 1 ────────────────────────────────────────────────
    try:
        ref1 = uidoc.Selection.PickObject(
            ObjectType.Element, flt,
            u"Selectionnez le 1er element lineaire  [Echap = annuler]"
        )
    except OperationCanceledException:
        return

    elem1 = doc.GetElement(ref1)
    g1    = get_line(elem1)
    if g1 is None:
        TaskDialog.Show(TOOL_NAME, u"Le 1er element n'a pas de geometrie lineaire droite.")
        return

    a1    = g1.GetEndPoint(0)
    b1    = g1.GetEndPoint(1)
    dir1  = g1.Direction
    a1x, a1y, a1z = float(a1.X), float(a1.Y), float(a1.Z)
    b1x, b1y, b1z = float(b1.X), float(b1.Y), float(b1.Z)
    d1x,  d1y,  d1z  = float(dir1.X), float(dir1.Y), float(dir1.Z)
    len1  = float(g1.Length)

    p1u  = dot3(a1x, a1y, a1z, rx, ry, rz)
    p1v  = dot3(a1x, a1y, a1z, ux, uy, uz)
    d1pu = dot3(d1x, d1y, d1z, rx, ry, rz)
    d1pv = dot3(d1x, d1y, d1z, ux, uy, uz)

    d1_norm = normalize_2d(d1pu, d1pv)
    if d1_norm is None:
        TaskDialog.Show(TOOL_NAME, u"Le 1er element est perpendiculaire au plan de la vue.")
        return

    # ── Selection element 2 ────────────────────────────────────────────────
    try:
        ref2 = uidoc.Selection.PickObject(
            ObjectType.Element, flt,
            u"Selectionnez le 2eme element lineaire  [Echap = annuler]"
        )
    except OperationCanceledException:
        return

    elem2 = doc.GetElement(ref2)
    g2    = get_line(elem2)
    if g2 is None:
        TaskDialog.Show(TOOL_NAME, u"Le 2eme element n'a pas de geometrie lineaire droite.")
        return

    a2    = g2.GetEndPoint(0)
    b2    = g2.GetEndPoint(1)
    dir2  = g2.Direction
    a2x, a2y, a2z = float(a2.X), float(a2.Y), float(a2.Z)
    b2x, b2y, b2z = float(b2.X), float(b2.Y), float(b2.Z)
    d2x,  d2y,  d2z  = float(dir2.X), float(dir2.Y), float(dir2.Z)
    len2  = float(g2.Length)

    p2u  = dot3(a2x, a2y, a2z, rx, ry, rz)
    p2v  = dot3(a2x, a2y, a2z, ux, uy, uz)
    d2pu = dot3(d2x, d2y, d2z, rx, ry, rz)
    d2pv = dot3(d2x, d2y, d2z, ux, uy, uz)

    d2_norm = normalize_2d(d2pu, d2pv)
    if d2_norm is None:
        TaskDialog.Show(TOOL_NAME, u"Le 2eme element est perpendiculaire au plan de la vue.")
        return

    # ── Verification non-parallelisme ──────────────────────────────────────
    denom = d1pu * d2pv - d1pv * d2pu
    if abs(denom) < 1e-9:
        TaskDialog.Show(
            TOOL_NAME,
            u"Les deux elements sont paralleles ou confondus dans le plan de la vue.\n\n"
            u"Info: d1_proj=({:.4f},{:.4f})  d2_proj=({:.4f},{:.4f})\n"
            u"      denom = {:.2e}".format(d1pu, d1pv, d2pu, d2pv, denom)
        )
        return

    # ── Ancre = milieu des milieux des deux elements ───────────────────────
    cx = ((a1x + b1x) / 2.0 + (a2x + b2x) / 2.0) / 2.0
    cy = ((a1y + b1y) / 2.0 + (a2y + b2y) / 2.0) / 2.0
    cz = ((a1z + b1z) / 2.0 + (a2z + b2z) / 2.0) / 2.0

    # ── Direction bissectrice dans le plan de la vue ───────────────────────
    bu = d1_norm[0] + d2_norm[0]
    bv = d1_norm[1] + d2_norm[1]
    bn = math.sqrt(bu*bu + bv*bv)
    if bn < 1e-9:
        # Antiparalleles : perpendiculaire dans le plan de vue
        bu = -d1_norm[1]
        bv =  d1_norm[0]
        bn = math.sqrt(bu*bu + bv*bv)
        if bn < 1e-9:
            TaskDialog.Show(TOOL_NAME, u"Impossible de calculer la bissectrice.")
            return
    bu /= bn
    bv /= bn

    # Retour en coordonnees monde (right et up sont orthonormaux → bd est unitaire)
    bd_x = bu * rx + bv * ux
    bd_y = bu * ry + bv * uy
    bd_z = bu * rz + bv * uz

    # ── Longueur = moyenne des deux elements source ────────────────────────
    half = (len1 + len2) / 4.0

    pt_start = XYZ(cx - bd_x * half, cy - bd_y * half, cz - bd_z * half)
    pt_end   = XYZ(cx + bd_x * half, cy + bd_y * half, cz + bd_z * half)

    try:
        bisect_line = Line.CreateBound(pt_start, pt_end)
    except Exception as ex:
        TaskDialog.Show(TOOL_NAME,
            u"Impossible de creer la ligne bissectrice :\n" + str(ex))
        return

    # ── Transaction ────────────────────────────────────────────────────────
    t_tr = Transaction(doc, u"STR - Bissectrice")
    try:
        t_tr.Start()
        doc.Create.NewDetailCurve(active_view, bisect_line)
        t_tr.Commit()
    except Exception as ex:
        try:
            if t_tr.GetStatus() == TransactionStatus.Started:
                t_tr.RollBack()
        except Exception:
            pass
        TaskDialog.Show(TOOL_NAME,
            u"Erreur lors de la creation de la bissectrice :\n" + str(ex))


main()
