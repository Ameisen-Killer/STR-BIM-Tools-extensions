# -*- coding: utf-8 -*-
# =============================================================================
# fgh_res_geom.py - Mesure geometrique des reservations FGH, STR contre RES.
#
# Les outils de synchronisation comparent des parametres texte, dont les
# coordonnees WSP_Position*_NM95 ecrites par le script des mandataires : une
# reservation deplacee ou redimensionnee a la main dans la maquette RES garde
# ses anciens parametres. Ici on mesure la geometrie reelle des deux cotes,
# dans le repere de la maquette STR (transformation du lien appliquee) :
#   - position   : distance entre les centres de gravite des solides ;
#   - volumetrie : encombrement X/Y/Z et volume des solides.
#
# Utilise par « Sync Reservations » (voyant de geometrie). « Controle Position »
# applique la meme methode avec ses propres tolerances reglables.
#
# Compatible IronPython 2.7 (Revit 2024) et 3.4 (Revit 2025+).
# =============================================================================

import math

from Autodesk.Revit.DB import (Options, ViewDetailLevel, Solid,
                               GeometryInstance, XYZ)

TOL_POSITION_CM = 1.0     # ecart entre centres de gravite
TOL_DIMENSION_CM = 1.0    # ecart d'encombrement sur un axe
TOL_VOLUME_PCT = 2.0      # ecart de volume

PIED_CM = 30.48
PIED3_L = 28.316846592


def _collecter_solides(gel, out):
    if gel is None:
        return
    for g in gel:
        try:
            if isinstance(g, Solid):
                if g.Volume > 1.0e-9 and g.Faces.Size > 0:
                    out.append(g)
            elif isinstance(g, GeometryInstance):
                _collecter_solides(g.GetInstanceGeometry(), out)
        except Exception:
            pass


def _solides(el):
    res = []
    try:
        opts = Options()
        opts.ComputeReferences = False
        opts.IncludeNonVisibleObjects = False
        opts.DetailLevel = ViewDetailLevel.Fine
        _collecter_solides(el.get_Geometry(opts), res)
    except Exception:
        pass
    return res


def mesurer(el, transform=None):
    """
    Mesure un element dans le repere de la maquette STR.
    transform : transformation du lien, None pour un element local.
    Retourne None si rien n'est mesurable, sinon un dict en unites internes
    (pieds) : c = centre de gravite, mn / mx = encombrement, vol = volume,
    approx = True quand la mesure vient de la boite englobante faute de solide.

    L'encombrement vient des sommets des solides, transformes un a un : la
    boite englobante d'un element de lien tourne serait fausse.
    """
    pts, vol, sx, sy, sz, approx = [], 0.0, 0.0, 0.0, 0.0, False
    for s in _solides(el):
        try:
            v = s.Volume
            g = s.ComputeCentroid()
            loc = []
            for edge in s.Edges:
                for p in edge.Tessellate():
                    loc.append(p)
            if not loc:
                continue
            pts.extend(loc)
            vol += v
            sx += g.X * v
            sy += g.Y * v
            sz += g.Z * v
        except Exception:
            pass

    if vol > 1.0e-9 and pts:
        centre = XYZ(sx / vol, sy / vol, sz / vol)
    else:
        # Famille sans solide lisible (vide seul, geometrie masquee...)
        approx = True
        try:
            bb = el.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            return None
        a, b = bb.Min, bb.Max
        pts = [XYZ(x, y, z) for x in (a.X, b.X) for y in (a.Y, b.Y) for z in (a.Z, b.Z)]
        centre = XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, (a.Z + b.Z) / 2.0)
        vol = abs((b.X - a.X) * (b.Y - a.Y) * (b.Z - a.Z))

    if transform is not None:
        centre = transform.OfPoint(centre)
        pts = [transform.OfPoint(p) for p in pts]

    xs = [p.X for p in pts]
    ys = [p.Y for p in pts]
    zs = [p.Z for p in pts]
    return {"c": (centre.X, centre.Y, centre.Z),
            "mn": (min(xs), min(ys), min(zs)),
            "mx": (max(xs), max(ys), max(zs)),
            "vol": vol, "approx": approx}


def dims_cm(m):
    """Encombrement X, Y, Z d'une mesure, en cm."""
    return [(m["mx"][i] - m["mn"][i]) * PIED_CM for i in range(3)]


def recouvrement(a, b):
    """Part commune des deux encombrements (intersection / union), en %."""
    inter, va, vb = 1.0, 1.0, 1.0
    for i in range(3):
        inter *= max(0.0, min(a["mx"][i], b["mx"][i]) - max(a["mn"][i], b["mn"][i]))
        va *= (a["mx"][i] - a["mn"][i])
        vb *= (b["mx"][i] - b["mn"][i])
    union = va + vb - inter
    return 100.0 * inter / union if union > 1.0e-12 else 0.0


def comparer(m_str, m_res, tol_pos=TOL_POSITION_CM, tol_dim=TOL_DIMENSION_CM,
             tol_vol=TOL_VOLUME_PCT):
    """
    Compare la mesure STR et la mesure RES d'une meme reservation.
    Retourne None si l'une des deux manque, sinon un dict :
      ecart (cm), d = [dX, dY, dZ] (cm, RES - STR), dims_str / dims_res (cm),
      ddim (cm, plus grand ecart d'encombrement), vol_str / vol_res (litres),
      dvol (%), recouvrement (%), approx, deplacee, volumetrie (booleens).
    """
    if m_str is None or m_res is None:
        return None
    d = [(m_res["c"][i] - m_str["c"][i]) * PIED_CM for i in range(3)]
    ecart = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    da, db = dims_cm(m_str), dims_cm(m_res)
    ddim = max(abs(db[i] - da[i]) for i in range(3))
    vol_str = m_str["vol"] * PIED3_L
    vol_res = m_res["vol"] * PIED3_L
    dvol = 100.0 * (vol_res - vol_str) / max(vol_str, 1.0e-9)
    return {"ecart": ecart, "d": d, "dims_str": da, "dims_res": db,
            "ddim": ddim, "vol_str": vol_str, "vol_res": vol_res, "dvol": dvol,
            "recouvrement": recouvrement(m_str, m_res),
            "approx": bool(m_str["approx"] or m_res["approx"]),
            "deplacee": ecart > tol_pos,
            "volumetrie": ddim > tol_dim or abs(dvol) > tol_vol}
