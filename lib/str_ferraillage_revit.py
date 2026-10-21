# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_revit.py - Ferraillage des murs : partie API Revit.
#
# Partage par "Ferraillage mur" et "Mettre a jour murs" :
#   - lecture de la geometrie des murs et detection du mur du dessus ;
#   - creation des jeux de barres (Rebar a espacement maximal) ;
#   - LIEN MUR <-> ARMATURES :
#       * chaque poignee de barre est contrainte a la face du mur (ou a son
#         enrobage) la plus proche : Revit fait suivre les barres quand le
#         mur change de longueur, de hauteur ou d'epaisseur ;
#       * la configuration (tableau des barres) est enregistree dans le mur
#         (Extensible Storage) et chaque barre porte la marque du mur : la
#         mise a jour recalcule et remplace le ferraillage STR du mur.
#
# Les calculs (positions des barres) sont dans str_ferraillage_mur (pur).
# Compatible IronPython 2.7 (Revit 2024) et IronPython 3.4 (Revit 2025+).
# =============================================================================

import json

import clr
clr.AddReference("RevitAPI")

import System
from System import Guid
from System.Collections.Generic import List as NetList
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInParameter,
                               ElementId, Wall, Line, XYZ, Curve)
from Autodesk.Revit.DB.ExtensibleStorage import (AccessLevel, Entity, Schema,
                                                 SchemaBuilder)
from Autodesk.Revit.DB.Structure import (Rebar, RebarBarType, RebarStyle,
                                         RebarHookOrientation)

import str_ferraillage_mur as MUR

FT_CM = 30.48
FT_MM = 304.8

# Schema de stockage : NE JAMAIS CHANGER le GUID (donnees deja ecrites).
_GUID = Guid("6f0b3c1e-58a4-4c7d-9a2e-3d7b21f4e8a1")
_CHAMP = "Donnees"
_NOM_SCHEMA = "STR_BIM_Tools_FerraillageMur"


# -----------------------------------------------------------------------------
# Outils
# -----------------------------------------------------------------------------
def idval(eid):
    """Entier d'un ElementId (IntegerValue retire apres Revit 2025)."""
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _xy(p):
    return (p.X * FT_CM, p.Y * FT_CM)


def _xyz(p):
    return XYZ(p[0] / FT_CM, p[1] / FT_CM, p[2] / FT_CM)


# -----------------------------------------------------------------------------
# Extensible Storage
# -----------------------------------------------------------------------------
def _schema():
    sch = Schema.Lookup(_GUID)
    if sch is not None:
        return sch
    sb = SchemaBuilder(_GUID)
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)
    sb.SetSchemaName(_NOM_SCHEMA)
    sb.SetDocumentation(u"STR BIM Tools - ferraillage des murs")
    sb.AddSimpleField(_CHAMP, clr.GetClrType(System.String))
    return sb.Finish()


def lire_donnees(el):
    """dict stocke sur l'element, ou None."""
    sch = Schema.Lookup(_GUID)
    if sch is None:
        return None
    try:
        ent = el.GetEntity(sch)
        if ent is None or not ent.IsValid():
            return None
        txt = ent.Get[System.String](_CHAMP)
        return json.loads(txt) if txt else None
    except Exception:
        return None


def ecrire_donnees(el, donnees):
    """A appeler dans une transaction."""
    sch = _schema()
    ent = Entity(sch)
    ent.Set[System.String](_CHAMP, json.dumps(donnees))
    el.SetEntity(ent)


def barres_str_du_mur(doc, mur_id):
    """Armatures creees par l'outil pour ce mur (marque dans la barre)."""
    res = []
    if Schema.Lookup(_GUID) is None:
        return res
    for rb in FilteredElementCollector(doc).OfClass(Rebar):
        try:
            if idval(rb.GetHostId()) != mur_id:
                continue
            d = lire_donnees(rb)
            if d and d.get("mur") == mur_id:
                res.append(rb)
        except Exception:
            pass
    return res


def armatures_par_mur(doc):
    """{id mur: (nb armatures STR, nb autres armatures)}."""
    res = {}
    stock = Schema.Lookup(_GUID) is not None
    for rb in FilteredElementCollector(doc).OfClass(Rebar):
        try:
            h = idval(rb.GetHostId())
            d = lire_donnees(rb) if stock else None
            str_, autres = res.get(h, (0, 0))
            if d and d.get("mur") == h:
                str_ += 1
            else:
                autres += 1
            res[h] = (str_, autres)
        except Exception:
            pass
    return res


# -----------------------------------------------------------------------------
# Types de barres
# -----------------------------------------------------------------------------
def diametre_type_mm(bt):
    for attr in ("BarNominalDiameter", "BarDiameter", "BarModelDiameter"):
        try:
            v = getattr(bt, attr)
            if v:
                return round(v * FT_MM, 1)
        except Exception:
            pass
    return 0.0


def types_barres(doc):
    """{diametre mm (int): RebarBarType}, un type par diametre."""
    res = {}
    for bt in FilteredElementCollector(doc).OfClass(RebarBarType):
        d = int(round(diametre_type_mm(bt)))
        if d > 0 and d not in res:
            res[d] = bt
    return res


# -----------------------------------------------------------------------------
# Lecture des murs
# -----------------------------------------------------------------------------
def lire_mur(w):
    """Mur Revit -> dict geometrique (cm) pour str_ferraillage_mur."""
    info = {"id": idval(w.Id), "elem": w, "erreur": u""}
    try:
        info["type"] = w.WallType.Name
    except Exception:
        info["type"] = u"?"
    courbe = w.Location.Curve if hasattr(w.Location, "Curve") else None
    if courbe is None or not isinstance(courbe, Line):
        info["erreur"] = u"Mur courbe ou sans axe : non géré"
        return info
    p0, p1 = courbe.GetEndPoint(0), courbe.GetEndPoint(1)
    d = (p1 - p0).Normalize()
    n = w.Orientation
    ep = w.Width * FT_CM
    # Ligne de justification -> axe central.
    decal = 0.0
    try:
        cle = w.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
        if cle in (2, 4):
            decal = -ep / 2.0
        elif cle in (3, 5):
            decal = ep / 2.0
    except Exception:
        pass
    o = _xy(p0)
    bb = w.get_BoundingBox(None)
    if bb is None:
        info["erreur"] = u"Géométrie introuvable"
        return info
    info.update({
        "o": (o[0] + n.X * decal, o[1] + n.Y * decal),
        "u": (d.X, d.Y), "n": (n.X, n.Y),
        "longueur": courbe.Length * FT_CM, "ep": ep,
        "z_bas": bb.Min.Z * FT_CM, "z_haut": bb.Max.Z * FT_CM,
    })
    return info


def lire_tous_murs(doc):
    tous = []
    for w in FilteredElementCollector(doc).OfClass(Wall).ToElements():
        try:
            tous.append(lire_mur(w))
        except Exception:
            pass                # mur-rideau, empile... : ignore
    return tous


def detecter_mur_dessus(info, tous):
    """Mur dont le pied est a la tete de celui-ci (ou au-dessus d'une dalle
    intermediaire, jusqu'a 60 cm) et qui le recouvre en plan."""
    if info.get("erreur"):
        return None
    ux, uy = info["u"]
    nx, ny = info["n"]
    ox, oy = info["o"]
    for autre in tous:
        if autre["id"] == info["id"] or autre.get("erreur"):
            continue
        ecart = autre["z_bas"] - info["z_haut"]
        if ecart < -5.0 or ecart > 60.0:
            continue
        ax, ay = autre["o"]
        bx = ax + autre["u"][0] * autre["longueur"]
        by = ay + autre["u"][1] * autre["longueur"]
        s0 = (ax - ox) * ux + (ay - oy) * uy
        s1 = (bx - ox) * ux + (by - oy) * uy
        t0 = (ax - ox) * nx + (ay - oy) * ny
        t1 = (bx - ox) * nx + (by - oy) * ny
        recouvre = min(max(s0, s1), info["longueur"]) - max(min(s0, s1), 0.0)
        if recouvre > 10.0 and max(abs(t0), abs(t1)) < \
                (info["ep"] + autre["ep"]) / 2.0:
            return autre
    return None


def preparer_mur(info, tous):
    """Complete info (mur du dessus) avant str_ferraillage_mur.calculer_jeux."""
    dessus = detecter_mur_dessus(info, tous)
    info["dessus"] = dessus
    info["mur_dessus"] = dessus is not None
    if dessus is not None:
        info["z_dessus"] = dessus["z_bas"]
    return info


# -----------------------------------------------------------------------------
# Creation / remplacement
# -----------------------------------------------------------------------------
def contraindre_au_mur(rb):
    """
    Lie chaque poignee de la barre a la face du mur (ou a l'enrobage) la plus
    proche, en gardant la position actuelle : la barre suit le mur.
    Retourne le nombre de poignees contraintes.
    """
    nb = 0
    try:
        mgr = rb.GetRebarConstraintsManager()
        if not mgr.IsRebarConstrainedPlacementEnabled:
            mgr.IsRebarConstrainedPlacementEnabled = True
        for poignee in mgr.GetAllHandles():
            meilleur, dist = None, None
            for cand in mgr.GetConstraintCandidatesForHandle(poignee):
                try:
                    if not cand.IsToHostFaceOrCover():
                        continue
                    try:
                        dd = abs(cand.GetDistanceToTargetCover())
                    except Exception:
                        dd = abs(cand.GetDistanceToTargetHostFace())
                except Exception:
                    continue
                if dist is None or dd < dist:
                    meilleur, dist = cand, dd
            if meilleur is not None:
                try:
                    mgr.SetPreferredConstraintForHandle(poignee, meilleur)
                    nb += 1
                except Exception:
                    pass
    except Exception:
        pass
    return nb


def creer_jeu(doc, mur, jeu, bt, partition, vue3d=None):
    ligne = Line.CreateBound(_xyz(jeu["p0"]), _xyz(jeu["p1"]))
    courbes = NetList[Curve]()
    courbes.Add(ligne)
    norm = XYZ(jeu["norm"][0], jeu["norm"][1], jeu["norm"][2])
    rb = Rebar.CreateFromCurves(doc, RebarStyle.Standard, bt, None, None,
                                mur, norm, courbes,
                                RebarHookOrientation.Left,
                                RebarHookOrientation.Left, True, True)
    rb.GetShapeDrivenAccessor().SetLayoutAsMaximumSpacing(
        jeu["e"] / FT_CM, jeu["repartition"] / FT_CM, True, True, True)
    for bip, val in ((BuiltInParameter.NUMBER_PARTITION_PARAM, partition),
                     (BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                      jeu["commentaire"])):
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
    ecrire_donnees(rb, {"mur": idval(mur.Id), "face": jeu["face"],
                        "dir": jeu["dir"]})
    return rb


def ferrailler_mur(doc, info, config, barres, vue3d=None):
    """
    Remplace le ferraillage STR du mur (dans une transaction ouverte) :
    supprime les barres STR existantes, cree les nouveaux jeux, les lie au
    mur et enregistre la configuration dans le mur.
    config : celle de str_ferraillage_mur + "partition".
    Retourne (ids crees, nb supprimees, echecs, nb poignees contraintes).
    """
    mur = info["elem"]
    jeux, echecs = MUR.calculer_jeux(info, config)
    anciennes = barres_str_du_mur(doc, info["id"])
    if anciennes:
        ids = NetList[ElementId]()
        for rb in anciennes:
            ids.Add(rb.Id)
        doc.Delete(ids)
    crees = []
    for j in jeux:
        bt = barres.get(int(j["d"]))
        if bt is None:
            echecs.append(u"Pas de type de barre Revit Ø{0}".format(j["d"]))
            continue
        try:
            rb = creer_jeu(doc, mur, j, bt, config.get("partition", u""), vue3d)
            crees.append(rb)
        except Exception as ex:
            echecs.append(u"{0}/{1} : {2}".format(j["face"], j["dir"], ex))
    nb_contraintes = 0
    if crees:
        doc.Regenerate()
        for rb in crees:
            nb_contraintes += contraindre_au_mur(rb)
    sauve = dict((k, v) for k, v in config.items())
    ecrire_donnees(mur, {"config": sauve})
    return [rb.Id for rb in crees], len(anciennes), echecs, nb_contraintes


def config_du_mur(el):
    """Configuration enregistree dans le mur, ou None."""
    d = lire_donnees(el)
    if d and isinstance(d.get("config"), dict):
        return d["config"]
    return None
