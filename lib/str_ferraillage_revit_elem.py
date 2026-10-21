# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_revit_elem.py - Ferraillage des poutres, poteaux et
# semelles isolees : partie API Revit.
#
# Lecture des elements (repere, section, enrobages, appuis et voisins) et
# creation des jeux calcules par str_ferraillage_elements (pur).
#
# Constats repris de RFT-Tools d'Essam Kader (licence MIT, verifies sur
# Revit 2024, github.com/EssamKader/SimpleBeam-RFT-Tool) :
#   - get_BoundingBox(None) est aligne sur les axes du projet : pour un
#     element tourne, b et h se lisent sur la geometrie du SYMBOLE
#     (GeometryInstance.GetSymbolGeometry().GetBoundingBox()) projetee par
#     GeometryInstance.Transform ;
#   - la ligne de reference d'une poutre n'est pas le centre de la section
#     (justification haut par defaut) : decalage lu sur cette meme boite ;
#   - Location.Point.Z d'un poteau vaut 0 quel que soit l'etage : hauteurs
#     lues sur la boite englobante ;
#   - b d'un poteau suit HandOrientation ;
#   - cadres fermes : contour trigonometrique (normale u x v) et crochets
#     Left/Left => crochets retournes vers l'interieur du beton ;
#   - Revit rabat les cadres sur l'enrobage de l'hote : les enrobages se
#     lisent sur l'element (parametres Enrobage haut / bas / autres faces).
#
# Le lien element <-> armatures reprend celui des murs : configuration
# enregistree dans l'element, marque dans chaque barre (meme schema
# Extensible Storage que str_ferraillage_revit), "Mettre a jour" recalcule.
# Compatible IronPython 2.7 (Revit 2024) et IronPython 3.4 (Revit 2025+).
# =============================================================================

import clr
clr.AddReference("RevitAPI")

from System.Collections.Generic import List as NetList
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInParameter,
                               BuiltInCategory, ElementId, FamilyInstance,
                               GeometryInstance, Options, Wall, Line, XYZ,
                               Curve, Element)
from Autodesk.Revit.DB.Structure import (Rebar, RebarHookType, RebarStyle,
                                         RebarHookOrientation)

import str_ferraillage_elements as ELEM
import str_ferraillage_revit as FR

FT_CM = FR.FT_CM

OUTIL_POUTRE = "poutre"
OUTIL_POTEAU = "poteau"
OUTIL_SEMELLE = "semelle"

CATEGORIES = {
    OUTIL_POUTRE: BuiltInCategory.OST_StructuralFraming,
    OUTIL_POTEAU: BuiltInCategory.OST_StructuralColumns,
    OUTIL_SEMELLE: BuiltInCategory.OST_StructuralFoundation,
}


# -----------------------------------------------------------------------------
# Outils
# -----------------------------------------------------------------------------
def _cm(p):
    return (p.X * FT_CM, p.Y * FT_CM, p.Z * FT_CM)


def _vec(v):
    return (v.X, v.Y, v.Z)


def _horizontal(v):
    w = XYZ(v.X, v.Y, 0.0)
    return w.Normalize() if w.GetLength() > 1e-9 else None


def nom_element(el):
    """Nom d'un type (RebarHookType...) lisible en IronPython."""
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = el.get_Parameter(bip)
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    try:
        return Element.Name.GetValue(el)
    except Exception:
        return u"?"


def categorie_est(el, bic):
    try:
        return el.Category is not None and \
            FR.idval(el.Category.Id) == int(bic)
    except Exception:
        return False


def _boite_locale(el):
    """(boite du symbole, Transform) ou (None, None). Voir en-tete."""
    try:
        for g in el.get_Geometry(Options()):
            if isinstance(g, GeometryInstance):
                sg = g.GetSymbolGeometry()
                if sg is None:
                    continue
                bb = sg.GetBoundingBox()
                if bb is not None:
                    return bb, g.Transform
    except Exception:
        pass
    return None, None


def _etendue(bb, tr, direction):
    """Etendue (pieds) de la boite locale selon une direction monde."""
    lx = direction.DotProduct(tr.BasisX)
    ly = direction.DotProduct(tr.BasisY)
    lz = direction.DotProduct(tr.BasisZ)
    proj = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                proj.append(lx * x + ly * y + lz * z)
    return max(proj) - min(proj)


def _centre(el):
    """Centre de l'element (XYZ, pieds) : boite locale si possible."""
    bb, tr = _boite_locale(el)
    if bb is not None:
        return tr.OfPoint((bb.Min + bb.Max) * 0.5)
    b = el.get_BoundingBox(None)
    return (b.Min + b.Max) * 0.5 if b is not None else None


def lire_enrobages(el):
    """Enrobages Revit (cm) : {"haut", "bas", "autre"}, None si absent."""
    doc = el.Document
    res = {}
    for cle, bip in (("haut", BuiltInParameter.CLEAR_COVER_TOP),
                     ("bas", BuiltInParameter.CLEAR_COVER_BOTTOM),
                     ("autre", BuiltInParameter.CLEAR_COVER_OTHER)):
        try:
            t = doc.GetElement(el.get_Parameter(bip).AsElementId())
            res[cle] = round(t.CoverDistance * FT_CM, 2) if t is not None else None
        except Exception:
            res[cle] = None
    return res


def config_effective(info, config):
    """Avec config["enrobage_revit"] : enrobages lus sur l'element (les
    valeurs manquantes reprennent config["enrobage"])."""
    if not config.get("enrobage_revit"):
        return config
    enr = config.get("enrobage", 3.0)
    defaut = float(enr) if not isinstance(enr, dict) else 3.0
    lu = info.get("enrobages") or {}
    cfg = dict(config)
    cfg["enrobage"] = dict((k, lu.get(k) if lu.get(k) is not None else defaut)
                           for k in ("haut", "bas", "autre"))
    return cfg


def types_crochets(doc):
    """[(libelle, RebarHookType, angle en degres)] tries par angle."""
    res = []
    for ht in FilteredElementCollector(doc).OfClass(RebarHookType):
        try:
            ang = int(round(ht.HookAngle * 180.0 / 3.141592653589793))
        except Exception:
            ang = 0
        res.append((u"{0} ({1}°)".format(nom_element(ht), ang), ht, ang))
    res.sort(key=lambda t: (abs(t[2] - 135), t[0]))
    return res


def crochet_par_nom(doc, nom):
    crochets = types_crochets(doc)
    for lib, ht, _ in crochets:
        if lib == nom:
            return ht
    return crochets[0][1] if crochets else None


def _elements(doc, bic):
    return list(FilteredElementCollector(doc).OfCategory(bic)
                .WhereElementIsNotElementType().ToElements())


# -----------------------------------------------------------------------------
# Poutres
# -----------------------------------------------------------------------------
def _appui(doc, poutre, P, ex, z_min, z_max, debut, candidats):
    """Appui (poteau, mur, poutre porteuse) autour de l'extremite P."""
    rayon = 30.0 / FT_CM
    meilleur, dist_min = None, None
    for el in candidats:
        if el.Id == poutre.Id:
            continue
        bb = el.get_BoundingBox(None)
        if bb is None:
            continue
        if not (bb.Min.X - rayon <= P.X <= bb.Max.X + rayon and
                bb.Min.Y - rayon <= P.Y <= bb.Max.Y + rayon):
            continue
        if bb.Max.Z < z_min - 5.0 / FT_CM or bb.Min.Z > z_max:
            continue
        c = (bb.Min + bb.Max) * 0.5
        d = ((c.X - P.X) ** 2 + (c.Y - P.Y) ** 2) ** 0.5
        if dist_min is None or d < dist_min:
            meilleur, dist_min = el, d
    if meilleur is None:
        return None
    if isinstance(meilleur, Wall):
        largeur = meilleur.Width
        try:
            centre = meilleur.Location.Curve.Project(P).XYZPoint
        except Exception:
            centre = _centre(meilleur)
    else:
        bb, tr = _boite_locale(meilleur)
        if bb is not None:
            largeur = _etendue(bb, tr, ex)
        else:
            b = meilleur.get_BoundingBox(None)
            largeur = abs(ex.X) * (b.Max.X - b.Min.X) + \
                abs(ex.Y) * (b.Max.Y - b.Min.Y)
        centre = _centre(meilleur)
    if centre is None:
        return None
    enr = lire_enrobages(meilleur) if not isinstance(meilleur, Wall) else {}
    return {"id": FR.idval(meilleur.Id), "centre": centre,
            "largeur": largeur * FT_CM, "enrobage": enr.get("autre"),
            "nom": FR.nom_type(meilleur)}


def lire_poutre(el, candidats=None):
    doc = el.Document
    info = {"id": FR.idval(el.Id), "elem": el, "erreur": u"",
            "type": FR.nom_type(el), "outil": OUTIL_POUTRE}
    courbe = getattr(el.Location, "Curve", None)
    if courbe is None or not isinstance(courbe, Line):
        info["erreur"] = u"Poutre courbe ou sans axe : non gérée"
        return info
    p0, p1 = courbe.GetEndPoint(0), courbe.GetEndPoint(1)
    if abs(p1.Z - p0.Z) > 0.01 * courbe.Length:
        info["erreur"] = u"Poutre inclinée : non gérée"
        return info
    ex = _horizontal(p1 - p0)
    ez = XYZ.BasisZ
    ey = ez.CrossProduct(ex)
    bb, tr = _boite_locale(el)
    if bb is not None:
        b = _etendue(bb, tr, ey)
        h = bb.Max.Z - bb.Min.Z
        centre = tr.OfPoint((bb.Min + bb.Max) * 0.5)
    else:
        wb = el.get_BoundingBox(None)
        if wb is None:
            info["erreur"] = u"Géométrie introuvable"
            return info
        b = abs(ey.X) * (wb.Max.X - wb.Min.X) + abs(ey.Y) * (wb.Max.Y - wb.Min.Y)
        h = wb.Max.Z - wb.Min.Z
        centre = (wb.Min + wb.Max) * 0.5
    du = ey.DotProduct(centre - p0)
    dv = centre.Z - p0.Z
    o = p0 + ey * du + ez * dv
    L = courbe.Length
    if candidats is None:
        candidats = []
        for bic in (BuiltInCategory.OST_StructuralColumns,
                    BuiltInCategory.OST_Walls,
                    BuiltInCategory.OST_StructuralFraming):
            candidats.extend(_elements(doc, bic))
    z_min, z_max = o.Z - h / 2.0, o.Z + h / 2.0
    appuis, noms = [], []
    for k, P in enumerate((p0, p1)):
        ap = _appui(doc, el, P, ex, z_min, z_max, k == 0, candidats)
        if ap is not None:
            xc = ex.DotProduct(ap["centre"] - p0) * FT_CM
            x_face = xc + ap["largeur"] / 2.0 if k == 0 else xc - ap["largeur"] / 2.0
            ap["x_face"] = x_face
            noms.append(u"{0} ({1})".format(ap["nom"], ap["id"]))
        else:
            noms.append(u"aucun")
        appuis.append(ap)
    if appuis[0] and appuis[1] and appuis[0]["id"] == appuis[1]["id"]:
        appuis[1] = None
        noms[1] = u"aucun"
    info.update({
        "repere": {"o": _cm(o), "ex": _vec(ex), "ey": _vec(ey), "ez": _vec(ez)},
        "L": L * FT_CM, "b": b * FT_CM, "h": h * FT_CM,
        "appuis": [None if a is None else
                   {"x_face": a["x_face"], "largeur": a["largeur"],
                    "enrobage": a["enrobage"]} for a in appuis],
        "appuis_txt": u" / ".join(noms),
        "enrobages": lire_enrobages(el),
    })
    return info


# -----------------------------------------------------------------------------
# Poteaux
# -----------------------------------------------------------------------------
def _repere_poteau(el):
    """(centre XYZ, ex, ey, b pieds, h pieds) ; ey = Z x ex pour garder un
    repere direct (cadres trigonometriques) meme si le poteau est en miroir."""
    ex = _horizontal(el.HandOrientation) if hasattr(el, "HandOrientation") \
        else None
    bb, tr = _boite_locale(el)
    if ex is None and tr is not None:
        ex = _horizontal(tr.BasisX)
    if ex is None:
        ex = XYZ.BasisX
    ey = XYZ.BasisZ.CrossProduct(ex)
    if bb is not None:
        return (tr.OfPoint((bb.Min + bb.Max) * 0.5), ex, ey,
                _etendue(bb, tr, ex), _etendue(bb, tr, ey))
    wb = el.get_BoundingBox(None)
    return ((wb.Min + wb.Max) * 0.5, ex, ey,
            abs(ex.X) * (wb.Max.X - wb.Min.X) + abs(ex.Y) * (wb.Max.Y - wb.Min.Y),
            abs(ey.X) * (wb.Max.X - wb.Min.X) + abs(ey.Y) * (wb.Max.Y - wb.Min.Y))


def _au_dessus(doc, el, centre, z_haut, categories):
    """Element (poteau, mur) dont le pied est a la tete de el (jusqu'a 60 cm
    plus haut) et qui recouvre le centre en plan."""
    for bic in categories:
        for autre in _elements(doc, bic):
            if autre.Id == el.Id:
                continue
            bb = autre.get_BoundingBox(None)
            if bb is None:
                continue
            ecart = (bb.Min.Z - z_haut) * FT_CM
            if ecart < -5.0 or ecart > 60.0:
                continue
            if bb.Min.X <= centre.X <= bb.Max.X and \
                    bb.Min.Y <= centre.Y <= bb.Max.Y:
                return autre, bb.Min.Z
    return None, None


def lire_poteau(el):
    doc = el.Document
    info = {"id": FR.idval(el.Id), "elem": el, "erreur": u"",
            "type": FR.nom_type(el), "outil": OUTIL_POTEAU}
    if getattr(el.Location, "Point", None) is None:
        info["erreur"] = u"Poteau incliné : non géré"
        return info
    wb = el.get_BoundingBox(None)
    if wb is None:
        info["erreur"] = u"Géométrie introuvable"
        return info
    centre, ex, ey, b, h = _repere_poteau(el)
    dessus, z_dessus = _au_dessus(
        doc, el, centre, wb.Max.Z,
        (BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Walls))
    info.update({
        "repere": {"o": (centre.X * FT_CM, centre.Y * FT_CM, 0.0),
                   "ex": _vec(ex), "ey": _vec(ey), "ez": (0.0, 0.0, 1.0)},
        "b": b * FT_CM, "h": h * FT_CM,
        "z_bas": wb.Min.Z * FT_CM, "z_haut": wb.Max.Z * FT_CM,
        "dessus": dessus is not None,
        "dessus_id": FR.idval(dessus.Id) if dessus is not None else None,
        "z_dessus": z_dessus * FT_CM if z_dessus is not None else None,
        "enrobages": lire_enrobages(el),
    })
    return info


# -----------------------------------------------------------------------------
# Semelles isolees
# -----------------------------------------------------------------------------
def lire_semelle(el):
    doc = el.Document
    info = {"id": FR.idval(el.Id), "elem": el, "erreur": u"",
            "type": FR.nom_type(el), "outil": OUTIL_SEMELLE}
    if not isinstance(el, FamilyInstance):
        info["erreur"] = u"Semelle filante ou dalle : non gérée (semelles " \
                         u"isolées uniquement)"
        return info
    wb = el.get_BoundingBox(None)
    bb, tr = _boite_locale(el)
    if wb is None:
        info["erreur"] = u"Géométrie introuvable"
        return info
    if bb is not None:
        ex = _horizontal(tr.BasisX) or XYZ.BasisX
        ey = XYZ.BasisZ.CrossProduct(ex)
        a, b = _etendue(bb, tr, ex), _etendue(bb, tr, ey)
        c = tr.OfPoint((bb.Min + bb.Max) * 0.5)
    else:
        ex, ey = XYZ.BasisX, XYZ.BasisY
        a, b = wb.Max.X - wb.Min.X, wb.Max.Y - wb.Min.Y
        c = (wb.Min + wb.Max) * 0.5
    o = XYZ(c.X, c.Y, wb.Min.Z)
    # Poteau pose sur la semelle.
    poteau, pot_txt = None, u"aucun"
    for col in _elements(doc, BuiltInCategory.OST_StructuralColumns):
        cb = col.get_BoundingBox(None)
        if cb is None:
            continue
        if cb.Min.Z < wb.Min.Z - 0.01 or (cb.Min.Z - wb.Max.Z) * FT_CM > 60.0:
            continue
        pc = (cb.Min + cb.Max) * 0.5
        rel = pc - o
        if abs(rel.DotProduct(ex)) > a / 2.0 or abs(rel.DotProduct(ey)) > b / 2.0:
            continue
        cc, cex, _, cbw, chw = _repere_poteau(col)
        relc = cc - o
        d = FR.lire_donnees(col) or {}
        poteau = {"c": (relc.DotProduct(ex) * FT_CM, relc.DotProduct(ey) * FT_CM),
                  "u": (cex.DotProduct(ex), cex.DotProduct(ey)),
                  "b": cbw * FT_CM, "h": chw * FT_CM,
                  "config": d.get("config") if isinstance(d.get("config"), dict)
                  else None}
        pot_txt = u"{0} ({1}){2}".format(FR.nom_type(col), FR.idval(col.Id),
                                         u", ferraillé" if poteau["config"] else u"")
        break
    info.update({
        "repere": {"o": _cm(o), "ex": _vec(ex), "ey": _vec(ey),
                   "ez": (0.0, 0.0, 1.0)},
        "a": a * FT_CM, "b": b * FT_CM, "ep": (wb.Max.Z - wb.Min.Z) * FT_CM,
        "poteau": poteau, "poteau_txt": pot_txt,
        "enrobages": lire_enrobages(el),
    })
    return info


LECTEURS = {OUTIL_POUTRE: lire_poutre, OUTIL_POTEAU: lire_poteau,
            OUTIL_SEMELLE: lire_semelle}
CALCULS = {OUTIL_POUTRE: ELEM.calculer_poutre,
           OUTIL_POTEAU: ELEM.calculer_poteau,
           OUTIL_SEMELLE: ELEM.calculer_semelle}


def calculer(info, config):
    """(jeux, erreurs, infos) avec les enrobages effectifs."""
    return CALCULS[info["outil"]](info, config_effective(info, config))


# -----------------------------------------------------------------------------
# Creation / remplacement
# -----------------------------------------------------------------------------
def barres_str_de(doc, hote_id):
    """Armatures creees par les outils STR pour cet element."""
    res = []
    for rb in FilteredElementCollector(doc).OfClass(Rebar):
        try:
            if FR.idval(rb.GetHostId()) != hote_id:
                continue
            d = FR.lire_donnees(rb)
            if d and (d.get("hote") == hote_id or d.get("mur") == hote_id):
                res.append(rb)
        except Exception:
            pass
    return res


def creer_jeu(doc, hote, jeu, bt, crochet, partition, vue3d=None):
    courbes = NetList[Curve]()
    pts = [FR._xyz(p) for p in jeu["pts"]]
    for a, b in zip(pts[:-1], pts[1:]):
        courbes.Add(Line.CreateBound(a, b))
    norm = XYZ(jeu["norm"][0], jeu["norm"][1], jeu["norm"][2])
    etrier = jeu.get("style") == "etrier"
    rb = Rebar.CreateFromCurves(
        doc, RebarStyle.StirrupTie if etrier else RebarStyle.Standard, bt,
        crochet if etrier else None, crochet if etrier else None,
        hote, norm, courbes, RebarHookOrientation.Left,
        RebarHookOrientation.Left, True, True)
    lay = jeu["layout"]
    acc = rb.GetShapeDrivenAccessor()
    if lay["type"] == "nombre":
        acc.SetLayoutAsFixedNumber(int(lay["n"]), lay["longueur"] / FT_CM,
                                   True, True, True)
    elif lay["type"] == "max":
        acc.SetLayoutAsMaximumSpacing(lay["e"] / FT_CM, lay["longueur"] / FT_CM,
                                      True, bool(lay.get("premier", True)),
                                      bool(lay.get("dernier", True)))
    for bip, val in ((BuiltInParameter.NUMBER_PARTITION_PARAM, partition),
                     (BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                      jeu.get("commentaire"))):
        try:
            p = rb.get_Parameter(bip)
            if p is not None and not p.IsReadOnly and val:
                p.Set(val)
        except Exception:
            pass
    if vue3d is not None:
        try:
            rb.SetUnobscuredInView(vue3d, True)
        except Exception:
            pass
    try:
        FR.ecrire_donnees(rb, {"hote": FR.idval(hote.Id), "cle": jeu["cle"]})
    except Exception:
        pass
    return rb


def ferrailler(doc, info, config, barres, vue3d=None):
    """
    Remplace le ferraillage STR de l'element (transaction ouverte par
    l'appelant) et enregistre la configuration dans l'element.
    config : celle de str_ferraillage_elements + "partition" + "crochet"
    (libelle du type de crochet des etriers).
    Retourne (ids crees, nb supprimees, echecs).
    """
    hote = info["elem"]
    jeux, echecs, _ = calculer(info, config)
    anciennes = barres_str_de(doc, info["id"])
    if anciennes:
        ids = NetList[ElementId]()
        for rb in anciennes:
            ids.Add(rb.Id)
        doc.Delete(ids)
    crochet = crochet_par_nom(doc, config.get("crochet", u""))
    crees = []
    for j in jeux:
        bt = barres.get(int(j["d"]))
        if bt is None:
            echecs.append(u"Pas de type de barre Revit Ø{0}".format(j["d"]))
            continue
        if j.get("style") == "etrier" and crochet is None:
            echecs.append(u"{0} : aucun type de crochet dans le projet".format(
                j["libelle"]))
            continue
        try:
            crees.append(creer_jeu(doc, hote, j, bt, crochet,
                                   config.get("partition", u""), vue3d))
        except Exception as ex:
            echecs.append(u"{0} : {1}".format(j["libelle"], ex))
    try:
        FR.ecrire_donnees(hote, {"config": dict(config), "outil": info["outil"]})
    except Exception as ex:
        echecs.append(u"Configuration non enregistrée : {0}".format(ex))
    return [rb.Id for rb in crees], len(anciennes), echecs


def donnees_element(el):
    """(outil, config) enregistres dans l'element, ou (None, None)."""
    d = FR.lire_donnees(el)
    if d and d.get("outil") in LECTEURS and isinstance(d.get("config"), dict):
        return d["outil"], d["config"]
    return None, None


def elements_ferrailles(doc):
    """[(element, outil, config)] de tout le projet."""
    res = []
    for outil, bic in CATEGORIES.items():
        for el in _elements(doc, bic):
            o, cfg = donnees_element(el)
            if o == outil:
                res.append((el, o, cfg))
    return res


def armatures_par_hote(doc):
    """{id hote: (nb armatures STR, nb autres)}."""
    res = {}
    for rb in FilteredElementCollector(doc).OfClass(Rebar):
        try:
            h = FR.idval(rb.GetHostId())
            d = FR.lire_donnees(rb)
            n_str, autres = res.get(h, (0, 0))
            if d and (d.get("hote") == h or d.get("mur") == h):
                n_str += 1
            else:
                autres += 1
            res[h] = (n_str, autres)
        except Exception:
            pass
    return res
