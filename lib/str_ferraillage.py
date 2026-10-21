# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage.py - Calculs de la liste de fer (STR BIM Tools).
#
# Logique pure, SANS API Revit ni WPF : le script de l'outil lit les barres
# Revit, les traduit en enregistrements simples (dict / tuples en cm) et ce
# module fait le reste :
#   - analyse geometrique d'une barre (cotes exterieures, figure 2D) ;
#   - regroupement par position (partition + numero d'armature) ;
#   - recapitulation par diametre (barres droites / faconnees), au format des
#     listes de fer SIA 262 du bureau.
#
# Conventions (identiques aux listes BaCAD du bureau) :
#   - cotes de faconnage = dimensions EXTERIEURES en cm, arrondies au cm ;
#   - longueur d'une barre = somme des cotes exterieures ;
#   - poids lineique = 7850 kg/m3 x pi x d^2 / 4 ;
#   - diametre moyen = diametre equivalent (poids total / longueur totale).
#
# Compatible IronPython 2.7 (Revit 2024), IronPython 3.4 (Revit 2025+) et
# CPython (tests hors Revit).
# =============================================================================

import math
import re

MASSE_VOLUMIQUE_ACIER = 7850.0      # kg/m3
TOLERANCE_CM = 0.5                  # extremites considerees jointes

MODE_COTES = "cotes"                # longueur = somme des cotes exterieures
MODE_REVIT = "revit"                # longueur = parametre "Longueur de barre"


# -----------------------------------------------------------------------------
# Acier
# -----------------------------------------------------------------------------
def kg_par_m(d_mm):
    """Poids lineique (kg/m) d'une barre de diametre nominal d_mm."""
    d = float(d_mm) / 1000.0
    return MASSE_VOLUMIQUE_ACIER * math.pi * d * d / 4.0


def diametre_equivalent(poids_kg, longueur_m):
    """Diametre (mm) d'une barre unique de meme poids lineique moyen."""
    if not longueur_m or poids_kg <= 0:
        return 0.0
    return math.sqrt((poids_kg / longueur_m) / kg_par_m(1.0))


# -----------------------------------------------------------------------------
# Vecteurs (tuples)
# -----------------------------------------------------------------------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norme(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norme(a)
    if n < 1e-12:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def _dist(a, b):
    return _norme(_sub(a, b))


def _perpendiculaire(u):
    """Un vecteur unitaire quelconque perpendiculaire a u."""
    ref = (0.0, 0.0, 1.0) if abs(u[2]) < 0.9 else (1.0, 0.0, 0.0)
    return _unit(_cross(u, ref))


# -----------------------------------------------------------------------------
# Analyse d'une barre
# -----------------------------------------------------------------------------
def analyser_forme(segments, d_mm):
    """
    segments : liste ordonnee de dict decrivant l'axe de la barre, rayons de
    cintrage supprimes (GetCenterlineCurves(..., suppressBendRadius=True)) :
        {"type": "L", "pts": [p0, p1], "l": longueur_cm}
        {"type": "A", "pts": [p0, ..., pn], "l": longueur_cm, "r": rayon_cm}
    points en cm (x, y, z). d_mm : diametre nominal.

    Retourne un dict :
        dims     : cotes exterieures (int, cm), une par segment
        longueur : somme des cotes (cm)
        droite   : True pour une barre droite sans crochet
        plane    : False si la barre n'est pas dans un plan
        segs2d   : [{"pts": [(x, y), ...], "txt": u"465"}] figure 2D (cm)
        signature: tuple pour comparer deux formes
    """
    segs = [s for s in segments if s.get("pts") and len(s["pts"]) >= 2]
    if not segs:
        return {"dims": [], "longueur": 0, "droite": True, "plane": True,
                "segs2d": [], "signature": ()}

    d_cm = float(d_mm) / 10.0
    n = len(segs)

    # --- Cotes exterieures --------------------------------------------------
    dirs_debut, dirs_fin = [], []
    for s in segs:
        p = s["pts"]
        dirs_debut.append(_unit(_sub(p[1], p[0])))
        dirs_fin.append(_unit(_sub(p[-1], p[-2])))

    def _allonge(i, j):
        """Allongement (cm) d'une cote au coude entre le segment i et j=i+1."""
        if _dist(segs[i]["pts"][-1], segs[j]["pts"][0]) > TOLERANCE_CM:
            return 0.0
        a, b = dirs_fin[i], dirs_debut[j]
        if a is None or b is None:
            return 0.0
        c = max(-1.0, min(1.0, _dot(a, b)))
        deviation = math.acos(c)              # 0 = alignes, pi = epingle
        if deviation < math.radians(2.0):
            return 0.0
        # Point exterieur : d/2 * tan(deviation/2), plafonne a d/2 (90 deg et
        # plus : la cote est prise a la face exterieure du segment voisin).
        return 0.5 * d_cm * min(math.tan(deviation / 2.0), 1.0)

    dims = []
    for i, s in enumerate(segs):
        l = float(s.get("l") or 0.0)
        if s["type"] == "L":
            if i > 0:
                l += _allonge(i - 1, i)
            if i < n - 1:
                l += _allonge(i, i + 1)
        dims.append(int(round(l)))

    droite = (n == 1 and segs[0]["type"] == "L")

    # --- Plan de la barre ----------------------------------------------------
    pts = []
    for s in segs:
        for p in s["pts"]:
            if not pts or _dist(pts[-1], p) > 1e-6:
                pts.append(p)
    normale = None
    plane = True
    for i in range(len(pts) - 2):
        a = _unit(_sub(pts[i + 1], pts[i]))
        b = _unit(_sub(pts[i + 2], pts[i + 1]))
        if a is None or b is None:
            continue
        c = _cross(a, b)
        if _norme(c) > 1e-3:
            c = _unit(c)
            if normale is None:
                normale = c
            elif abs(_dot(normale, c)) < 0.999:
                plane = False
    # Axe principal : le plus long segment droit (horizontal sur la figure).
    lignes = [(s.get("l") or 0.0, s) for s in segs if s["type"] == "L"]
    if lignes:
        ref = max(lignes, key=lambda t: t[0])[1]
        u = _unit(_sub(ref["pts"][-1], ref["pts"][0]))
    else:
        u = _unit(_sub(segs[0]["pts"][-1], segs[0]["pts"][0]))
        if u is None and len(segs[0]["pts"]) > 2:
            u = _unit(_sub(segs[0]["pts"][1], segs[0]["pts"][0]))
    if u is None:
        u = (1.0, 0.0, 0.0)
    if normale is None or abs(_dot(normale, u)) > 0.999:
        normale = _perpendiculaire(u)
    v = _unit(_cross(normale, u)) or _perpendiculaire(u)

    o = segs[0]["pts"][0]

    def _proj(p):
        q = _sub(p, o)
        return (_dot(q, u), _dot(q, v))

    segs2d = []
    for s, dim in zip(segs, dims):
        segs2d.append({"pts": [_proj(p) for p in s["pts"]],
                       "txt": u"{0}".format(dim),
                       "arc": s["type"] != "L",
                       "r": s.get("r")})

    # Retournement : la forme se developpe au-dessus du segment principal.
    if lignes:
        y_ref = _proj(ref["pts"][0])[1]
        ys = [p[1] for sg in segs2d for p in sg["pts"]]
        if ys and (sum(ys) / len(ys)) < y_ref - 1e-6:
            for sg in segs2d:
                sg["pts"] = [(x, -y) for (x, y) in sg["pts"]]

    signature = tuple(dims) + (n,)
    return {"dims": dims, "longueur": sum(dims), "droite": droite,
            "plane": plane, "segs2d": segs2d, "signature": signature}


# -----------------------------------------------------------------------------
# Regroupement en positions
# -----------------------------------------------------------------------------
def cle_naturelle(texte):
    """Tri naturel : '2' < '10', 'A2' < 'A10'."""
    morceaux = re.split(r"(\d+)", texte or u"")
    return [(0, int(m), u"") if m.isdigit() else (1, 0, m.lower())
            for m in morceaux if m != u""]


class Barre(object):
    """Enregistrement brut : n barres identiques d'un element Revit."""

    def __init__(self, elem_id, partition, numero, nb, d_mm, forme,
                 longueur_revit_cm=None, mandrin_mm=None, remarque=u"",
                 variable=False):
        self.elem_id = elem_id
        self.partition = partition or u""
        self.numero = numero or u""
        self.nb = int(nb)
        self.d_mm = float(d_mm)
        self.forme = forme
        self.longueur_revit_cm = longueur_revit_cm
        self.mandrin_mm = mandrin_mm
        self.remarque = (remarque or u"").strip()
        self.variable = variable

    def longueur_cm(self, mode):
        if mode == MODE_REVIT and self.longueur_revit_cm:
            return int(round(self.longueur_revit_cm))
        return int(self.forme["longueur"])


class Position(object):
    """Une ligne de la liste de fer."""

    def __init__(self, partition, numero, d_mm, longueur_cm, forme):
        self.partition = partition
        self.numero = numero
        self.repere = numero            # numero affiche (suffixe si doublon)
        self.d_mm = d_mm
        self.longueur_cm = longueur_cm
        self.forme = forme
        self.nb = 0
        self.ids = []
        self.remarques = []
        self.mandrin_mm = None
        self.alertes = []
        self.variable = False           # jeu de barres a longueur variable

    # Valeurs derivees ---------------------------------------------------------
    @property
    def d_int(self):
        return int(round(self.d_mm))

    @property
    def longueur_m(self):
        return self.longueur_cm / 100.0

    @property
    def longueur_tot_m(self):
        return self.nb * self.longueur_cm / 100.0

    @property
    def kg_m(self):
        return kg_par_m(self.d_mm)

    @property
    def poids_kg(self):
        return self.longueur_tot_m * self.kg_m

    @property
    def faconnee(self):
        return not self.forme["droite"]

    @property
    def remarque(self):
        return u" / ".join(self.remarques)

    @property
    def cotes(self):
        return u" / ".join(u"{0}".format(c) for c in self.forme["dims"])


def regrouper(barres, mode=MODE_COTES):
    """
    Barres -> positions triees (partition, numero). Les barres d'un meme
    numero mais de geometrie differente donnent des lignes separees (12a,
    12b...) avec une alerte, sauf pour les jeux a longueur variable.
    """
    groupes = {}
    ordre = []
    for b in barres:
        cle = (b.partition, b.numero, int(round(b.d_mm)),
               b.longueur_cm(mode), b.forme["signature"])
        pos = groupes.get(cle)
        if pos is None:
            pos = Position(b.partition, b.numero, b.d_mm,
                           b.longueur_cm(mode), b.forme)
            pos.variable = b.variable
            groupes[cle] = pos
            ordre.append(cle)
        pos.nb += b.nb
        if b.elem_id not in pos.ids:
            pos.ids.append(b.elem_id)
        if b.remarque and b.remarque not in pos.remarques:
            pos.remarques.append(b.remarque)
        if pos.mandrin_mm is None and b.mandrin_mm:
            pos.mandrin_mm = b.mandrin_mm
        if not b.forme.get("plane", True) and \
                u"Barre 3D (figure projetee)" not in pos.alertes:
            pos.alertes.append(u"Barre 3D (figure projetee)")
        if not b.numero and u"Sans numero" not in pos.alertes:
            pos.alertes.append(u"Sans numero")

    positions = [groupes[c] for c in ordre]
    positions.sort(key=lambda p: (cle_naturelle(p.partition),
                                  cle_naturelle(p.numero),
                                  -p.longueur_cm))

    # Numeros partages par plusieurs geometries.
    par_numero = {}
    for p in positions:
        par_numero.setdefault((p.partition, p.numero), []).append(p)
    for lst in par_numero.values():
        if len(lst) < 2:
            continue
        for i, p in enumerate(lst):
            p.repere = u"{0}{1}".format(p.numero, _lettre(i))
            if not p.variable:
                p.alertes.append(u"Numero partage par {0} formes differentes"
                                 .format(len(lst)))
    return positions


def _lettre(i):
    lettres = u"abcdefghijklmnopqrstuvwxyz"
    if i < len(lettres):
        return lettres[i]
    return lettres[i // len(lettres) - 1] + lettres[i % len(lettres)]


# -----------------------------------------------------------------------------
# Recapitulation par diametre
# -----------------------------------------------------------------------------
def recapituler(positions):
    """
    Retourne un dict :
        droites / faconnees : liste triee de (d, kg_m, longueur_m, poids_kg)
        tot_droites / tot_faconnees : (longueur_m, poids_kg)
        total : (longueur_m, poids_kg)
        nb_positions, d_moyen
    """
    cumul = {True: {}, False: {}}
    for p in positions:
        c = cumul[p.faconnee].setdefault(p.d_int, [0.0, 0.0])
        c[0] += p.longueur_tot_m
        c[1] += p.poids_kg

    def _table(dico):
        return [(d, kg_par_m(d), dico[d][0], dico[d][1]) for d in sorted(dico)]

    droites = _table(cumul[False])
    faconnees = _table(cumul[True])
    tot_d = (sum(r[2] for r in droites), sum(r[3] for r in droites))
    tot_f = (sum(r[2] for r in faconnees), sum(r[3] for r in faconnees))
    total = (tot_d[0] + tot_f[0], tot_d[1] + tot_f[1])
    return {"droites": droites, "faconnees": faconnees,
            "tot_droites": tot_d, "tot_faconnees": tot_f, "total": total,
            "nb_positions": len(positions),
            "d_moyen": diametre_equivalent(total[1], total[0])}


# -----------------------------------------------------------------------------
# Formatage (affichage fenetre)
# -----------------------------------------------------------------------------
def fmt_nombre(valeur, decimales=2):
    """1404.28 -> u'1 404,28' (convention des listes du bureau)."""
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return u""
    txt = (u"{0:,." + str(decimales) + u"f}").format(v)
    return txt.replace(u",", u" ").replace(u".", u",")


# -----------------------------------------------------------------------------
# Figure de faconnage : mise en page 2D (pixels), dessinee ensuite en WPF
# -----------------------------------------------------------------------------
def mise_en_page_figure(forme, largeur=340.0, hauteur=80.0):
    """
    Place la figure d'une barre dans un cadre largeur x hauteur (px).
    Les proportions sont volontairement comprimees (figure schematique, comme
    les listes du bureau) : une barre de 465 x 21 reste lisible, un etrier
    carre reste carre.

    Retourne {"traits": [[(x, y), ...], ...],
              "textes": [(x, y, texte, ancrage)]}   ancrage : 'c' centre,
              'g' texte a gauche du point, 'd' a droite, 'h' au-dessus,
              'b' en dessous.
    """
    segs = forme.get("segs2d") or []
    if not segs:
        return {"traits": [], "textes": []}
    mx, my = 30.0, 15.0
    wa, ha = largeur - 2 * mx, hauteur - 2 * my

    if forme.get("droite"):
        y = hauteur * 0.42
        x0, x1 = mx + wa * 0.15, mx + wa * 0.85
        return {"traits": [[(x0, y), (x1, y)]],
                "textes": [((x0 + x1) / 2.0, y + 3.0, segs[0]["txt"], "b")]}

    xs = [p[0] for s in segs for p in s["pts"]]
    ys = [p[1] for s in segs for p in s["pts"]]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    w, h = max(xmax - xmin, 1e-6), max(ymax - ymin, 1e-6)

    # Boite dessinee : toute la hauteur disponible, largeur comprimee
    # (racine du rapport largeur / hauteur), plafonnee a la largeur dispo.
    if h > 1e-3:
        bh = ha
        bw = min(wa, ha * math.sqrt(w / h))
        if w <= 1e-3:
            bw = 0.0
    else:
        bh, bw = 0.0, wa * 0.7
    sx = bw / w if w > 1e-3 else 0.0
    sy = bh / h if h > 1e-3 else 0.0
    ox = mx + (wa - bw) / 2.0
    oy = my + (ha - bh) / 2.0

    def _ecran(p):
        return (ox + (p[0] - xmin) * sx, oy + (ymax - p[1]) * sy)

    traits = [[_ecran(p) for p in s["pts"]] for s in segs]
    tous = [p for t in traits for p in t]
    cx = sum(p[0] for p in tous) / len(tous)
    cy = sum(p[1] for p in tous) / len(tous)

    textes = []
    for s, t in zip(segs, traits):
        if len(t) == 2:
            mxp, myp = (t[0][0] + t[1][0]) / 2.0, (t[0][1] + t[1][1]) / 2.0
        else:
            mxp, myp = t[len(t) // 2]
        dx, dy = t[-1][0] - t[0][0], t[-1][1] - t[0][1]
        lg = math.sqrt(dx * dx + dy * dy)
        if lg < 1e-6:
            nx, ny = 0.0, -1.0
        else:
            nx, ny = -dy / lg, dx / lg
        cote = (mxp - cx) * nx + (myp - cy) * ny
        if abs(cote) < 1e-6:
            # Segment passant par le centre : texte dessous / a gauche.
            cote = ny if abs(ny) > abs(nx) else -nx
        if cote < 0:
            nx, ny = -nx, -ny
        x, y = mxp + nx * 4.0, myp + ny * 4.0
        if abs(ny) >= abs(nx):
            ancrage = "b" if ny > 0 else "h"
        else:
            ancrage = "d" if nx > 0 else "g"
        textes.append((x, y, s["txt"], ancrage))
    return {"traits": traits, "textes": textes}
