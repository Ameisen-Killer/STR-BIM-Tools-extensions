# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_elements.py - Ferraillage des poutres, poteaux et semelles.
#
# Logique pure, SANS API Revit (meme principe que str_ferraillage_mur) : le
# script lit l'element (repere, dimensions, enrobages, appuis ou elements
# voisins), ce module calcule les jeux de barres a creer.
#
# Inspire de RFT-Tools d'Essam Kader (licence MIT,
# github.com/EssamKader/SimpleBeam-RFT-Tool) : decoupage poutre / poteau /
# semelle isolee, ancrage en equerre dans l'appui, etriers en 3 zones,
# barres de peau, cadres interieurs, nappes en U, attentes de poteau.
# Les regles de dimensionnement egyptiennes (ECP 203) ne sont PAS reprises :
# toutes les valeurs sont des saisies avec des valeurs par defaut usuelles
# (SIA 262 : ancrage et recouvrement exprimes en diametres).
#
# Unites : cm. Un repere = {"o", "ex", "ey", "ez"} (tuples 3D, monde) ; les
# calculs se font dans le repere local puis sont convertis en coordonnees
# monde. Un jeu :
#   cle, libelle, d (mm), style ("std" ou "etrier"), pts (polyligne monde),
#   norm (normale au plan de la barre = sens de repartition), layout
#   ({"type": "simple"} | {"type": "nombre", "n", "longueur"} |
#    {"type": "max", "e", "longueur", "premier", "dernier"}),
#   commentaire.
# Compatible IronPython 2.7 / 3.4 et CPython (tests hors Revit).
# =============================================================================

import math

ATTENTE_AUTO = "auto"
ATTENTE_TOUJOURS = "toujours"
ATTENTE_JAMAIS = "jamais"

MANDRIN_ETRIER = 4.0        # diametre de mandrin des etriers, en Ø


# -----------------------------------------------------------------------------
# Outils
# -----------------------------------------------------------------------------
def _add(a, b, k=1.0):
    return tuple(a[i] + b[i] * k for i in range(3))


def monde(rep, p):
    """Point local (x, y, z) -> monde."""
    q = rep["o"]
    for k, axe in zip(p, (rep["ex"], rep["ey"], rep["ez"])):
        q = _add(q, axe, k)
    return q


def direction(rep, v):
    """Vecteur local -> monde."""
    q = (0.0, 0.0, 0.0)
    for k, axe in zip(v, (rep["ex"], rep["ey"], rep["ez"])):
        q = _add(q, axe, k)
    return q


def longueur_polyligne(pts):
    return sum(math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))
               for a, b in zip(pts[:-1], pts[1:]))


def nombre_barres_max(longueur, e, premier=True, dernier=True):
    """Nombre de barres d'un jeu a espacement maximal (comme
    SetLayoutAsMaximumSpacing), extremites exclues au besoin."""
    if longueur <= 0:
        n = 1
    else:
        n = int(math.ceil(longueur / float(e) - 1e-6)) + 1
    if not premier:
        n -= 1
    if not dernier:
        n -= 1
    return max(n, 0)


def nombre_barres(jeu):
    lay = jeu["layout"]
    if lay["type"] == "nombre":
        return int(lay["n"])
    if lay["type"] == "max":
        return nombre_barres_max(lay["longueur"], lay["e"],
                                 lay.get("premier", True), lay.get("dernier", True))
    return 1


def longueur_recouvrement(d_mm, multiple=50, pas_cm=5):
    """Recouvrement / ancrage : multiple x Ø, arrondi au pas superieur (cm)."""
    l = multiple * float(d_mm) / 10.0
    return int(math.ceil(l / pas_cm) * pas_cm)


def _enrobages(config, defaut=3.0):
    """{"haut", "bas", "autre"} en cm depuis config["enrobage"] (nombre ou
    dict, voir str_ferraillage_revit.config_effective)."""
    enr = config.get("enrobage", defaut)
    if isinstance(enr, dict):
        return dict((k, float(enr.get(k) if enr.get(k) is not None else defaut))
                    for k in ("haut", "bas", "autre"))
    return {"haut": float(enr), "bas": float(enr), "autre": float(enr)}


def _jeu(rep, cle, libelle, d, pts_locaux, norm_local, layout, commentaire,
         style="std"):
    return {"cle": cle, "libelle": libelle, "d": int(d), "style": style,
            "pts": [monde(rep, p) for p in pts_locaux],
            "norm": direction(rep, norm_local), "layout": layout,
            "commentaire": commentaire,
            "longueur_barre": longueur_polyligne(pts_locaux)}


def _layout_nombre(n, longueur):
    if n <= 1:
        return {"type": "simple"}
    return {"type": "nombre", "n": int(n), "longueur": float(longueur)}


def _rectangle_ccw(cu, cv, larg, haut):
    """Cadre ferme (u, v), sens trigonometrique, depart au coin haut-gauche,
    point de depart repete a la fin. Avec la normale u x v et des crochets
    Left/Left, les crochets se retournent vers l'interieur (constat RFT-Tools
    R21, verifie dans Revit 2024)."""
    hu, hv = larg / 2.0, haut / 2.0
    pts = [(cu - hu, cv + hv), (cu - hu, cv - hv), (cu + hu, cv - hv),
           (cu + hu, cv + hv)]
    return pts + [pts[0]]


def _zones(debut, fin, zone, e_ext, e_cour):
    """Repartition en 3 zones (extremites serrees, courant) entre debut et
    fin : [(z0, longueur, e, premier, dernier)]. zone <= 0 : une seule zone."""
    long_tot = fin - debut
    if long_tot <= 0:
        return []
    if zone <= 0 or 2.0 * zone >= long_tot - 1e-6:
        return [(debut, long_tot, e_ext if zone > 0 else e_cour, True, True)]
    res = [(debut, zone, e_ext, True, True)]
    milieu = long_tot - 2.0 * zone
    if milieu > e_cour / 2.0:
        res.append((debut + zone, milieu, e_cour, False, False))
    res.append((fin - zone, zone, e_ext, True, True))
    return res


# =============================================================================
# POUTRE
# =============================================================================
def poutre_defaut():
    return {"n_inf": 3, "d_inf": 16, "n_inf2": 0, "n_sup": 2, "d_sup": 12,
            "ancrage": "equerre", "lb": 40, "d_etr": 8, "e_appui": 15,
            "e_travee": 25, "zone_appui": 0, "peau": "auto", "d_peau": 10,
            "e_peau": 20, "enrobage": 3, "enrobage_revit": True}


def calculer_poutre(p, config):
    """
    p : dict
        repere  : o sur l'axe de la poutre au centre de la section, a
                  l'origine de la ligne de reference ; ex = axe, ey = ez x ex
                  (largeur), ez vertical
        L       : longueur de la ligne de reference (cm)
        b, h    : section (cm)
        appuis  : [debut, fin], None ou {"x_face": abscisse de la face cote
                  travee, "largeur": cm, "enrobage": cm ou None}
    Retourne (jeux, erreurs, infos).
    """
    rep = p["repere"]
    c = _enrobages(config)
    ch, cb, cc = c["haut"], c["bas"], c["autre"]
    b, h, L = float(p["b"]), float(p["h"]), float(p["L"])
    de = float(config.get("d_etr", 8)) / 10.0
    di = float(config.get("d_inf", 16)) / 10.0
    ds = float(config.get("d_sup", 12)) / 10.0
    lb = float(config.get("lb", 40))
    equerre = config.get("ancrage", "equerre") == "equerre"
    jeux, erreurs, infos = [], [], []
    appuis = list(p.get("appuis") or [None, None])

    # Extremites : face d'appui (ou bout de poutre) et longueur d'ancrage
    # droite dans l'appui (a = largeur - enrobage, comme RFT-Tools).
    bouts = []
    for k, ap in enumerate(appuis):
        s = -1.0 if k == 0 else 1.0
        if ap:
            c_ap = ap.get("enrobage")
            a = float(ap["largeur"]) - (float(c_ap) if c_ap is not None else cc)
            bouts.append({"face": float(ap["x_face"]), "a": max(a, 0.0), "s": s,
                          "appui": True})
        else:
            x_bout = 0.0 if k == 0 else L
            bouts.append({"face": x_bout - s * cc, "a": 0.0, "s": s,
                          "appui": False})
            erreurs.append(u"Pas d'appui détecté au {0} : barres droites "
                           u"arrêtées à l'enrobage".format(
                               u"début" if k == 0 else u"fin"))
    portee = bouts[1]["face"] - bouts[0]["face"]
    if portee <= 0:
        return [], [u"Portée nulle entre les appuis"], infos
    infos.append(u"Portée libre {0:.0f} cm".format(portee))

    h_int = h - ch - cb - 2.0 * de          # hauteur dispo pour les retours

    def barre_principale(d, z, dessus, retrait=0.0):
        """Polyligne locale d'une barre longitudinale a y = 0."""
        dcm = d
        pts = []
        sens = -1.0 if dessus else 1.0      # retour vers le bas / le haut
        coins = []
        retours = []
        for bt in bouts:
            a = max(bt["a"] - retrait, 0.0)
            x = bt["face"] + bt["s"] * a
            coins.append(x)
            if bt["appui"] and equerre:
                besoin = lb * dcm
                leg = max(besoin - a, 10.0 * dcm)
                leg = min(leg, h_int - dcm)
                retours.append(leg if leg > dcm else 0.0)
                if a + leg < besoin - 0.5:
                    erreurs.append(u"Ancrage {0} : {1:.0f} cm disponibles "
                                   u"pour {2:.0f} cm requis".format(
                                       u"sup." if dessus else u"inf.",
                                       a + leg, besoin))
            else:
                retours.append(0.0)
                if bt["appui"] and a < lb * dcm - 0.5:
                    erreurs.append(u"Ancrage droit {0} : {1:.0f} cm pour "
                                   u"{2:.0f} cm requis".format(
                                       u"sup." if dessus else u"inf.", a, lb * dcm))
        if retours[0]:
            pts.append((coins[0], 0.0, z + sens * retours[0]))
        pts.append((coins[0], 0.0, z))
        pts.append((coins[1], 0.0, z))
        if retours[1]:
            pts.append((coins[1], 0.0, z + sens * retours[1]))
        return pts

    def lit(cle, libelle, n, d_mm, dcm, z, dessus, retrait, commentaire):
        if n <= 0:
            return
        Y = b / 2.0 - cc - de - dcm / 2.0
        if Y <= 0:
            erreurs.append(u"{0} : poutre trop étroite".format(libelle))
            return
        pts = barre_principale(dcm, z, dessus, retrait)
        y0 = -Y if n > 1 else 0.0
        pts = [(x, y0, zz) for x, _, zz in pts]
        jeux.append(_jeu(rep, cle, libelle, d_mm, pts, (0.0, 1.0, 0.0),
                         _layout_nombre(n, 2.0 * Y), commentaire))
        if n > 1:
            jeu_esp = (2.0 * Y - n * dcm) / (n - 1)
            if jeu_esp < max(2.0, dcm):
                erreurs.append(u"{0} : espacement libre {1:.1f} cm trop "
                               u"faible".format(libelle, jeu_esp))

    n_inf = int(config.get("n_inf", 0))
    z_inf = -h / 2.0 + cb + de + di / 2.0
    lit("inf1", u"Inférieures", n_inf, config.get("d_inf", 16), di, z_inf,
        False, 0.0, u"Inf.")
    n_inf2 = int(config.get("n_inf2", 0))
    if n_inf2:
        z2 = z_inf + di + max(2.0, di)
        lit("inf2", u"Inférieures 2e lit", n_inf2, config.get("d_inf", 16), di,
            z2, False, di + 1.0, u"Inf. 2e lit")
    z_sup = h / 2.0 - ch - de - ds / 2.0
    lit("sup", u"Supérieures", int(config.get("n_sup", 0)),
        config.get("d_sup", 12), ds, z_sup, True, di, u"Sup.")

    # Etriers : cadre ferme, 3 zones (premier a 5 cm des faces d'appui).
    larg = b - 2.0 * cc - de
    haut = h - ch - cb - de
    if larg <= MANDRIN_ETRIER * de or haut <= MANDRIN_ETRIER * de:
        erreurs.append(u"Etriers : section trop petite")
    elif config.get("e_appui", 0) > 0 and config.get("e_travee", 0) > 0:
        zc = (cb - ch) / 2.0
        cadre = [(0.0, u, v) for u, v in _rectangle_ccw(0.0, zc, larg, haut)]
        x0 = bouts[0]["face"] + (5.0 if bouts[0]["appui"] else de / 2.0)
        x1 = bouts[1]["face"] - (5.0 if bouts[1]["appui"] else de / 2.0)
        zone = float(config.get("zone_appui", 0) or 0)
        if zone <= 0:
            zone = round((x1 - x0) / 4.0)
        for i, (xd, lg, e, prem, dern) in enumerate(_zones(
                x0, x1, zone, float(config["e_appui"]),
                float(config["e_travee"]))):
            pts = [(xd, y, z) for _, y, z in cadre]
            jeux.append(_jeu(rep, "etr{0}".format(i), u"Etriers zone {0}".format(i + 1),
                             config.get("d_etr", 8), pts, (1.0, 0.0, 0.0),
                             {"type": "max", "e": e, "longueur": lg,
                              "premier": prem, "dernier": dern},
                             u"Etriers", style="etrier"))

    # Barres de peau : faces laterales, droites, ancrees comme les barres
    # inferieures sans retour.
    peau = config.get("peau", "auto")
    if peau == "oui" or (peau == "auto" and h > 70.0):
        dp = float(config.get("d_peau", 10)) / 10.0
        H = (z_sup - ds / 2.0) - (z_inf + di / 2.0)
        n_int = int(math.ceil(H / float(config.get("e_peau", 20)) - 1e-6))
        n_lits = n_int - 1
        if n_lits >= 1:
            pas = H / n_int
            Yp = b / 2.0 - cc - de - dp / 2.0
            xa = bouts[0]["face"] + bouts[0]["s"] * bouts[0]["a"]
            xb = bouts[1]["face"] + bouts[1]["s"] * bouts[1]["a"]
            z0 = z_inf + di / 2.0 + pas
            for cote, y in (("g", -Yp), ("d", Yp)):
                jeux.append(_jeu(rep, "peau_" + cote, u"Peau", config.get("d_peau", 10),
                                 [(xa, y, z0), (xb, y, z0)], (0.0, 0.0, 1.0),
                                 _layout_nombre(n_lits, pas * (n_lits - 1)),
                                 u"Peau"))
            infos.append(u"Peau : {0} lit(s) par face, pas {1:.1f} cm".format(
                n_lits, pas))
    return jeux, erreurs, infos


# =============================================================================
# POTEAU
# =============================================================================
def poteau_defaut():
    return {"n_x": 3, "n_y": 3, "d_long": 16, "d_etr": 8, "e_zone": 10,
            "e_courant": 20, "zone": 0, "attente": ATTENTE_AUTO, "l_att": 0,
            "att_pied": 0, "cadre_int": True, "enrobage": 3,
            "enrobage_revit": True}


def _positions(n, demi):
    if n <= 1:
        return [0.0]
    pas = 2.0 * demi / (n - 1)
    return [-demi + i * pas for i in range(n)]


def calculer_poteau(p, config):
    """
    p : dict
        repere : o = centre de la section a z = 0 (monde) ; ex = sens de b
                 (HandOrientation), ey = sens de h, ez vertical
        b, h   : section (cm) ; z_bas, z_haut : cotes (cm)
        dessus : True si un poteau ou un mur est detecte au-dessus
        z_dessus : pied de l'element du dessus (cm)
    """
    rep = p["repere"]
    c = _enrobages(config)
    cc = c["autre"]
    b, h = float(p["b"]), float(p["h"])
    zb, zh = float(p["z_bas"]), float(p["z_haut"])
    dl = float(config.get("d_long", 16)) / 10.0
    de = float(config.get("d_etr", 8)) / 10.0
    nx, ny = int(config.get("n_x", 2)), int(config.get("n_y", 2))
    jeux, erreurs, infos = [], [], []
    if nx < 2 or ny < 2:
        return [], [u"Au moins 2 barres par face"], infos
    X = b / 2.0 - cc - de - dl / 2.0
    Y = h / 2.0 - cc - de - dl / 2.0
    if X <= 0 or Y <= 0:
        return [], [u"Section trop petite"], infos

    mode = config.get("attente", ATTENTE_AUTO)
    haut_actif = mode == ATTENTE_TOUJOURS or (mode == ATTENTE_AUTO and
                                              p.get("dessus"))
    l_att = float(config.get("l_att", 0) or 0) or \
        longueur_recouvrement(config.get("d_long", 16))
    z_att = max(zh, float(p.get("z_dessus") or zh)) if p.get("dessus") else zh
    z1 = z_att + l_att if haut_actif else zh - c["haut"]
    att_pied = float(config.get("att_pied", 0) or 0)
    z0 = zb - att_pied if att_pied > 0 else zb + c["bas"]
    if haut_actif:
        infos.append(u"Attentes en tête : {0:.0f} cm".format(l_att))

    dmm = config.get("d_long", 16)
    for cle, y in (("face_y-", -Y), ("face_y+", Y)):
        jeux.append(_jeu(rep, cle, u"Longitudinales", dmm,
                         [(-X, y, z0), (-X, y, z1)], (1.0, 0.0, 0.0),
                         _layout_nombre(nx, 2.0 * X), u"Long."))
    if ny > 2:
        pas = 2.0 * Y / (ny - 1)
        for cle, x in (("face_x-", -X), ("face_x+", X)):
            jeux.append(_jeu(rep, cle, u"Longitudinales", dmm,
                             [(x, -Y + pas, z0), (x, -Y + pas, z1)],
                             (0.0, 1.0, 0.0),
                             _layout_nombre(ny - 2, pas * (ny - 3)), u"Long."))

    # Cadres : exterieur + interieurs (boucles fermees autour des barres
    # intermediaires, principe RFT-Tools), 3 zones verticales.
    larg = b - 2.0 * cc - de
    prof = h - 2.0 * cc - de
    cadres = [("ext", 0.0, 0.0, larg, prof)]
    if config.get("cadre_int", True):
        for sens, n, demi, autre in (("x", nx, X, prof), ("y", ny, Y, larg)):
            if n < 4:
                if n == 3:
                    infos.append(u"Barre milieu des faces {0} non tenue par un "
                                 u"cadre : épingle à ajouter".format(
                                     u"b" if sens == "x" else u"h"))
                continue
            pos = _positions(n, demi)
            w = pos[n - 2] - pos[1] + dl + de
            if w < (MANDRIN_ETRIER + 1.0) * de:
                infos.append(u"Cadre intérieur {0} trop étroit pour être "
                             u"plié".format(sens))
                continue
            if sens == "x":
                cadres.append(("int_x", 0.0, 0.0, w, autre))
            else:
                cadres.append(("int_y", 0.0, 0.0, autre, w))
    t0, t1 = zb + 5.0, zh - 5.0
    zone = float(config.get("zone", 0) or 0)
    if zone <= 0:
        zone = max((zh - zb) / 6.0, max(b, h), 50.0)
    zones = _zones(t0, t1, zone, float(config.get("e_zone", 10)),
                   float(config.get("e_courant", 20)))
    for nom, cu, cv, w, hh in cadres:
        poly = _rectangle_ccw(cu, cv, w, hh)
        for i, (zd, lg, e, prem, dern) in enumerate(zones):
            jeux.append(_jeu(rep, "cadre_{0}_{1}".format(nom, i),
                             u"Cadres", config.get("d_etr", 8),
                             [(u, v, zd) for u, v in poly], (0.0, 0.0, 1.0),
                             {"type": "max", "e": e, "longueur": lg,
                              "premier": prem, "dernier": dern},
                             u"Cadres", style="etrier"))
    return jeux, erreurs, infos


# =============================================================================
# SEMELLE ISOLEE
# =============================================================================
def semelle_defaut():
    return {"d_x": 14, "e_x": 15, "d_y": 14, "e_y": 15, "forme": "U",
            "lit_bas": "auto", "sup": False, "d_sup": 12, "e_sup": 20,
            "attentes": True, "n_x": 3, "n_y": 3, "d_att": 16, "l_att": 0,
            "pied": 25, "c_pot": 3, "d_cadre": 8, "nb_cadres": 2,
            "ceinture": False, "d_ceint": 12, "enrobage": 5,
            "enrobage_revit": True}


def _nappe(rep, cle, libelle, dmm, dir_x, demi_ext, demi_rep, z, forme,
           z_retour, e, commentaire):
    """Jeux d'une direction de nappe. dir_x : barres le long de x (reparties
    en y), sinon le long de y (reparties en x)."""
    def pt(t, s, zz):
        return (t, s, zz) if dir_x else (s, t, zz)
    norm = (0.0, 1.0, 0.0) if dir_x else (1.0, 0.0, 0.0)
    n = nombre_barres_max(2.0 * demi_rep, e)
    pas = 2.0 * demi_rep / (n - 1) if n > 1 else 0.0
    gauche = [pt(-demi_ext, 0, z_retour), pt(-demi_ext, 0, z)]
    droite = [pt(demi_ext, 0, z), pt(demi_ext, 0, z_retour)]

    def place(pts, s0):
        """Polyligne placee a la 1re position de la repartition."""
        return [(q[0], s0, q[2]) if dir_x else (s0, q[1], q[2]) for q in pts]

    res = []
    if forme == "L" and n >= 2:
        na, nb_ = (n + 1) // 2, n // 2
        a = gauche + [pt(demi_ext, 0, z)]
        bb = [pt(-demi_ext, 0, z)] + droite
        res.append(_jeu(rep, cle + "_a", libelle, dmm, place(a, -demi_rep), norm,
                        _layout_nombre(na, 2.0 * pas * (na - 1)), commentaire))
        res.append(_jeu(rep, cle + "_b", libelle, dmm, place(bb, -demi_rep + pas),
                        norm, _layout_nombre(nb_, 2.0 * pas * (nb_ - 1)),
                        commentaire))
        return res
    if forme == "U":
        pts = gauche + droite
    else:
        pts = [pt(-demi_ext, 0, z), pt(demi_ext, 0, z)]
    res.append(_jeu(rep, cle, libelle, dmm, place(pts, -demi_rep), norm,
                    {"type": "max", "e": e, "longueur": 2.0 * demi_rep,
                     "premier": True, "dernier": True}, commentaire))
    return res


def calculer_semelle(s, config):
    """
    s : dict
        repere : o = centre de la face inferieure ; ex, ey = axes locaux de la
                 semelle (a selon ex, b selon ey), ez vertical
        a, b, ep : dimensions (cm)
        poteau : None ou {"c": (x, y) centre local, "u": (ux, uy) sens de b du
                 poteau (local), "b", "h" (cm), "config": config poteau ou None}
    """
    rep = s["repere"]
    c = _enrobages(config, 5.0)
    ch, cb, cc = c["haut"], c["bas"], c["autre"]
    A, B, ep = float(s["a"]), float(s["b"]), float(s["ep"])
    jeux, erreurs, infos = [], [], []
    pot = s.get("poteau")

    # Direction du lit inferieur : le plus grand debord (RFT-Tools §3), sinon
    # la plus grande dimension.
    lit = config.get("lit_bas", "auto")
    if lit not in ("X", "Y"):
        if pot:
            ux, uy = pot["u"]
            ext_x = abs(ux) * pot["b"] + abs(uy) * pot["h"]
            ext_y = abs(uy) * pot["b"] + abs(ux) * pot["h"]
            lit = "X" if (A - ext_x) >= (B - ext_y) else "Y"
        else:
            lit = "X" if A >= B else "Y"
    infos.append(u"Lit inférieur : barres selon {0}".format(
        u"a (X)" if lit == "X" else u"b (Y)"))
    dx = float(config.get("d_x", 14)) / 10.0
    dy = float(config.get("d_y", 14)) / 10.0
    d_bas, d_haut = (dx, dy) if lit == "X" else (dy, dx)
    sup = bool(config.get("sup"))
    dsup = float(config.get("d_sup", 12)) / 10.0
    forme = config.get("forme", "U")
    for dir_x in (True, False):
        bas = (lit == "X") == dir_x
        dd = dx if dir_x else dy
        long_dir, larg_dir = (A, B) if dir_x else (B, A)
        if bas:
            z = cb + dd / 2.0
            demi_ext = long_dir / 2.0 - cc - dd / 2.0
            demi_rep = larg_dir / 2.0 - cc - d_haut - dd / 2.0
        else:
            z = cb + d_bas + dd / 2.0
            demi_ext = long_dir / 2.0 - cc - d_bas - dd / 2.0
            demi_rep = larg_dir / 2.0 - cc - dd / 2.0
        z_ret = ep - ch - dd / 2.0 - (2.0 * dsup if sup else 0.0)
        if z_ret - z < 2.0 * dd:
            erreurs.append(u"Semelle trop mince pour les retours")
        cle = "inf_x" if dir_x else "inf_y"
        e = float(config.get("e_x" if dir_x else "e_y", 15))
        jeux.extend(_nappe(rep, cle, u"Nappe inférieure",
                           config.get("d_x" if dir_x else "d_y", 14), dir_x,
                           demi_ext, demi_rep, z, forme, z_ret, e,
                           u"Nappe inf. {0}".format(u"X" if dir_x else u"Y")))
    if sup:
        es = float(config.get("e_sup", 20))
        for dir_x in (True, False):
            dessus = (lit == "X") == dir_x       # meme ordre que la nappe inf.
            z = ep - ch - dsup / 2.0 - (0.0 if dessus else dsup)
            long_dir, larg_dir = (A, B) if dir_x else (B, A)
            jeux.extend(_nappe(rep, "sup_x" if dir_x else "sup_y",
                               u"Nappe supérieure", config.get("d_sup", 12),
                               dir_x, long_dir / 2.0 - cc - dsup / 2.0,
                               larg_dir / 2.0 - cc - dsup / 2.0, z, "droite",
                               z, es, u"Nappe sup. {0}".format(
                                   u"X" if dir_x else u"Y")))

    # Ceinture : cadre ferme sur le pourtour, a mi-hauteur.
    if config.get("ceinture"):
        dce = float(config.get("d_ceint", 12)) / 10.0
        poly = _rectangle_ccw(0.0, 0.0, A - 2.0 * cc - dce, B - 2.0 * cc - dce)
        jeux.append(_jeu(rep, "ceinture", u"Ceinture", config.get("d_ceint", 12),
                         [(u, v, ep / 2.0) for u, v in poly], (0.0, 0.0, 1.0),
                         {"type": "simple"}, u"Ceinture", style="etrier"))

    # Attentes du poteau : barres en L posees sur la nappe inferieure, pied
    # tourne vers l'exterieur, cadres de maintien dans la semelle.
    if config.get("attentes") and pot:
        cfg_p = pot.get("config") or {}
        nx = int(cfg_p.get("n_x", config.get("n_x", 3)))
        ny = int(cfg_p.get("n_y", config.get("n_y", 3)))
        d_att_mm = cfg_p.get("d_long", config.get("d_att", 16))
        da = float(d_att_mm) / 10.0
        dca = float(cfg_p.get("d_etr", config.get("d_cadre", 8))) / 10.0
        cp = float(config.get("c_pot", 3))
        X = pot["b"] / 2.0 - cp - dca - da / 2.0
        Y = pot["h"] / 2.0 - cp - dca - da / 2.0
        if nx < 2 or ny < 2 or X <= 0 or Y <= 0:
            erreurs.append(u"Attentes : section du poteau trop petite")
        else:
            cx, cy = pot["c"]
            ux, uy = pot["u"]
            vx, vy = -uy, ux

            def loc(x, y, z):
                return (cx + x * ux + y * vx, cy + x * uy + y * vy, z)
            l_att = float(config.get("l_att", 0) or 0) or \
                longueur_recouvrement(d_att_mm)
            z_p = cb + dx + dy + da / 2.0
            z_t = ep + l_att
            pied = float(config.get("pied", 25))
            rangs = [("y-", (0.0, -1.0), -Y, nx, X, (1.0, 0.0)),
                     ("y+", (0.0, 1.0), Y, nx, X, (1.0, 0.0))]
            if ny > 2:
                pas = 2.0 * Y / (ny - 1)
                rangs += [("x-", (-1.0, 0.0), -X, ny - 2, Y - pas, (0.0, 1.0)),
                          ("x+", (1.0, 0.0), X, ny - 2, Y - pas, (0.0, 1.0))]
            for nom, (px, py), fixe, n, demi, (rx, ry) in rangs:
                # Premier point de la rangee (cote negatif de la repartition).
                if rx:
                    x0, y0 = -demi, fixe
                else:
                    x0, y0 = fixe, -demi
                pts = [loc(x0 + px * pied, y0 + py * pied, z_p),
                       loc(x0, y0, z_p), loc(x0, y0, z_t)]
                norm = (rx * ux + ry * vx, rx * uy + ry * vy, 0.0)
                jeux.append(_jeu(rep, "att_" + nom, u"Attentes poteau", d_att_mm,
                                 pts, norm, _layout_nombre(n, 2.0 * demi),
                                 u"Attentes poteau"))
            infos.append(u"Attentes : {0} barres Ø{1}, {2:.0f} cm au-dessus "
                         u"de la semelle".format(2 * nx + 2 * max(ny - 2, 0),
                                                 d_att_mm, l_att))
            nbc = int(config.get("nb_cadres", 2))
            if nbc > 0:
                w = pot["b"] - 2.0 * cp - dca
                hh = pot["h"] - 2.0 * cp - dca
                z_haut_c = ep - ch - (2.0 * dsup if sup else 0.0) - dca
                pas_c = 15.0
                z0c = max(z_haut_c - pas_c * (nbc - 1), z_p + da)
                poly = [loc(u, v, z0c) for u, v in _rectangle_ccw(0.0, 0.0, w, hh)]
                jeu = {"cle": "cadres_att", "libelle": u"Cadres attentes",
                       "d": int(cfg_p.get("d_etr", config.get("d_cadre", 8))),
                       "style": "etrier", "pts": [monde(rep, q) for q in poly],
                       "norm": direction(rep, (0.0, 0.0, 1.0)),
                       "layout": _layout_nombre(nbc, z_haut_c - z0c),
                       "commentaire": u"Cadres attentes",
                       "longueur_barre": longueur_polyligne(poly)}
                jeux.append(jeu)
    elif config.get("attentes"):
        infos.append(u"Aucun poteau détecté sur la semelle : pas d'attentes")
    return jeux, erreurs, infos


# -----------------------------------------------------------------------------
# Recapitulatif
# -----------------------------------------------------------------------------
def poids_jeux(jeux, kg_par_m):
    """(nombre de barres, kg)."""
    nb, kg = 0, 0.0
    for j in jeux:
        n = nombre_barres(j)
        nb += n
        kg += n * j["longueur_barre"] / 100.0 * kg_par_m(j["d"])
    return nb, kg
