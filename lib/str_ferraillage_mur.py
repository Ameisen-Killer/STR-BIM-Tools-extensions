# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_mur.py - Calcul du ferraillage courant d'un mur droit.
#
# Logique pure, SANS API Revit : le script lit le mur (axe, epaisseur, cotes
# basse et haute, mur au-dessus), ce module calcule les jeux de barres :
#   - verticales et horizontales, face exterieure et face interieure ;
#   - enrobage, ordre des lits (horizontales ou verticales a l'exterieur) ;
#   - attentes en tete (mur du dessus) et en pied.
# Chaque jeu = une barre droite + une direction et une longueur de
# repartition, cree ensuite en un Rebar a espacement maximal.
#
# Unites : cm. Repere : u = sens du mur (axe de debut a fin), n = normale
# exterieure (Wall.Orientation), z vertical.
# Compatible IronPython 2.7 / 3.4 et CPython (tests hors Revit).
# =============================================================================

import math

FACES = (("ext", u"Extérieure"), ("int", u"Intérieure"))
DIRECTIONS = (("V", u"Verticales"), ("H", u"Horizontales"))

ATTENTE_AUTO = "auto"           # attente haute seulement si mur au-dessus
ATTENTE_TOUJOURS = "toujours"
ATTENTE_JAMAIS = "jamais"


def longueur_recouvrement(d_mm, multiple=50, pas_cm=5):
    """Recouvrement par defaut : multiple x d, arrondi au pas superieur (cm)."""
    l = multiple * float(d_mm) / 10.0
    return int(math.ceil(l / pas_cm) * pas_cm)


def rangs_defaut(d_mm=12, e_cm=15):
    """Les 4 rangs du tableau : (face, direction)."""
    rangs = []
    for face, _ in FACES:
        for direction, _ in DIRECTIONS:
            vert = direction == "V"
            rangs.append({
                "face": face, "dir": direction, "actif": True,
                "d": d_mm, "e": e_cm,
                "att_haut": longueur_recouvrement(d_mm) if vert else 0,
                "att_bas": 0,
                "commentaire": u"Vert. int+ext" if vert else u"Hori. int+ext",
            })
    return rangs


def _add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k)


def attente_haute_active(mode, mur_dessus):
    if mode == ATTENTE_TOUJOURS:
        return True
    if mode == ATTENTE_JAMAIS:
        return False
    return bool(mur_dessus)


def calculer_jeux(mur, config):
    """
    mur : dict
        o        : (x, y) debut de l'axe CENTRAL du mur (cm)
        u        : (ux, uy) direction unitaire du mur
        n        : (nx, ny) normale exterieure unitaire
        longueur : cm
        ep       : epaisseur (cm)
        z_bas, z_haut : cm
        mur_dessus : bool
        z_dessus   : pied du mur du dessus (cm, facultatif) : l'attente
                     traverse la dalle et se mesure depuis ce niveau
    config : dict
        enrobage   : cm (faces et extremites)
        h_ext      : True = horizontales au lit exterieur (contre le coffrage)
        attente    : ATTENTE_AUTO / ATTENTE_TOUJOURS / ATTENTE_JAMAIS
        rangs      : liste de dict (voir rangs_defaut)

    Retourne (jeux, erreurs). Un jeu :
        face, dir, d, e, commentaire,
        p0, p1     : extremites de la 1re barre (x, y, z en cm)
        norm       : direction de repartition (unitaire, 3D)
        repartition: longueur de repartition (cm)
    """
    c = float(config.get("enrobage", 3.0))
    h_ext = config.get("h_ext", True)
    mode = config.get("attente", ATTENTE_AUTO)
    L = float(mur["longueur"])
    ep = float(mur["ep"])
    zb, zh = float(mur["z_bas"]), float(mur["z_haut"])
    u = (mur["u"][0], mur["u"][1], 0.0)
    n = (mur["n"][0], mur["n"][1], 0.0)
    o = (mur["o"][0], mur["o"][1], 0.0)
    haut_actif = attente_haute_active(mode, mur.get("mur_dessus"))
    z_attente = zh
    if mur.get("mur_dessus") and mur.get("z_dessus") is not None:
        z_attente = max(zh, float(mur["z_dessus"]))

    jeux, erreurs = [], []
    rangs = [r for r in config.get("rangs", []) if r.get("actif")]
    for face, _ in FACES:
        rv = [r for r in rangs if r["face"] == face and r["dir"] == "V"]
        rh = [r for r in rangs if r["face"] == face and r["dir"] == "H"]
        dv = float(rv[0]["d"]) / 10.0 if rv else 0.0
        dh = float(rh[0]["d"]) / 10.0 if rh else 0.0
        # Distance face -> axe de chaque lit.
        if h_ext:
            off_h = c + dh / 2.0
            off_v = c + dh + dv / 2.0
        else:
            off_v = c + dv / 2.0
            off_h = c + dv + dh / 2.0
        signe = 1.0 if face == "ext" else -1.0

        for r in rv:
            d = dv
            decal = signe * (ep / 2.0 - off_v)
            if decal * signe < d / 2.0:
                erreurs.append(u"Face {0} : mur trop mince pour les deux lits"
                               .format(face))
                continue
            att_bas = float(r.get("att_bas") or 0)
            att_haut = float(r.get("att_haut") or 0)
            z0 = zb - att_bas if att_bas > 0 else zb + c
            z1 = z_attente + att_haut if haut_actif and att_haut > 0 else zh - c
            depart = c + d / 2.0
            base = _add(_add(o, u, depart), n, decal)
            jeux.append({
                "face": face, "dir": "V", "d": r["d"], "e": float(r["e"]),
                "commentaire": r.get("commentaire", u""),
                "p0": (base[0], base[1], z0), "p1": (base[0], base[1], z1),
                "norm": u, "repartition": L - 2.0 * depart,
                "attente_haute": z1 > zh,
            })
        for r in rh:
            d = dh
            decal = signe * (ep / 2.0 - off_h)
            if decal * signe < d / 2.0:
                erreurs.append(u"Face {0} : mur trop mince pour les deux lits"
                               .format(face))
                continue
            z = zb + c + d / 2.0
            a = _add(_add(o, u, c), n, decal)
            b = _add(_add(o, u, L - c), n, decal)
            jeux.append({
                "face": face, "dir": "H", "d": r["d"], "e": float(r["e"]),
                "commentaire": r.get("commentaire", u""),
                "p0": (a[0], a[1], z), "p1": (b[0], b[1], z),
                "norm": (0.0, 0.0, 1.0),
                "repartition": (zh - zb) - 2.0 * c - d,
                "attente_haute": False,
            })
    for j in jeux:
        if j["repartition"] <= 0 or j["e"] <= 0:
            erreurs.append(u"Jeu {0}/{1} : longueur de répartition nulle"
                           .format(j["face"], j["dir"]))
    jeux = [j for j in jeux if j["repartition"] > 0 and j["e"] > 0]
    return jeux, erreurs


def nombre_barres(repartition, e):
    """Nombre de barres d'un jeu a espacement maximal e (barres d'extremite
    comprises), comme SetLayoutAsMaximumSpacing."""
    if repartition <= 0:
        return 1
    return int(math.ceil(repartition / float(e) - 1e-6)) + 1
