# -*- coding: utf-8 -*-
# =============================================================================
# fgh_res.py - Validation des reservations FGH par un ingenieur, hors Revit.
#
# Circuit :
#   1. « Export IFC RES » : IFC light de la structure + IFC des reservations
#      FGH_RES, ce dernier enrichi d'un jeu de proprietes STR_FGH_RES (cle,
#      numero, demande, valeurs PVA_RES_VAL_* actuelles).
#   2. str-bim-tools.com/fgh/ : l'ingenieur ouvre les deux IFC, change le
#      statut, la date et le commentaire de validation ; la page ecrit un
#      fichier JSON (format STR_FGH_RES_VALIDATION).
#   3. « Import Validation RES » : le modeleur applique ce JSON dans la
#      maquette RES, puis « Sync Reservations » reporte dans la STR.
#
# CLE D'ECHANGE
# -------------
# La cle est l'ADN (CONTROL_NE_PAS_TOUCHER), comme dans « Sync Reservations »
# (audit du 13.08.2026 : 2 ADN en doublon sur 5014, contre 169 N° en
# doublon). Le UniqueId Revit voyage avec : il departage un ADN en doublon et
# revele une reservation resoumise (meme element, ADN refige) ou un ADN
# raccourci par « Nettoyer Control ». L'ElementId n'est qu'indicatif.
#
# Compatible IronPython 2.7 (Revit 2024) et 3.4 (Revit 2025+).
# =============================================================================

import io
import random
import re

from Autodesk.Revit.DB import (FamilyInstance, FilteredElementCollector,
                               StorageType, Element)

FORMAT = u"STR_FGH_RES_VALIDATION"
FORMAT_VERSION = 1
PSET_NOM = u"STR_FGH_RES"
PAGE_WEB = u"https://str-bim-tools.com/fgh/"

FAMILY_PREFIX = u"FGH_RES"
ADN_PARAM = u"CONTROL_NE_PAS_TOUCHER"
SUPPRIME_PARAM = u"PVA_RES_DEM_Supprime"
PARAM_NUM = u"PVA_RES_DEM_NumReservation"

# Parametres que la page web a le droit de changer (nom -> libelle)
P_STATUT = u"PVA_RES_VAL_Statut"
P_DATE = u"PVA_RES_VAL_Date"
P_COMMENT = u"PVA_RES_VAL_Commentaire"
PARAMS_VAL = [P_STATUT, P_DATE, P_COMMENT]
LIBELLES_VAL = {P_STATUT: u"Statut", P_DATE: u"Date", P_COMMENT: u"Commentaire"}

# Lus pour la fiche de la page (nom du parametre -> nom dans le jeu IFC)
PARAMS_FICHE = [
    (PARAM_NUM, u"Numero"),
    (u"PVA_RES_DEM_Demandeur", u"Demandeur"),
    (u"PVA_RES_DEM_Date", u"Date demande"),
    (u"PVA_RES_DEM_Commentaire", u"Commentaire demande"),
    (u"PVA_RES_DEM_Hauteur", u"Hauteur"),
    (u"PVA_RES_DEM_Longueur", u"Longueur"),
    (u"PVA_RES_DEM_Profondeur", u"Profondeur"),
    (u"PVA_RES_DEM_Diametre", u"Diametre"),
    (u"PVA_RES_DEM_Carottage", u"Carottage"),
    (u"PVA_RES_DEM_Calfeutrement", u"Calfeutrement"),
    (u"WSP_NiveauAssocie", u"Niveau associe"),
    (u"WSP_NatureParoi", u"Nature paroi"),
    (u"RES_Demandeur", u"RES Demandeur"),
    (u"RES_Responsable", u"RES Responsable"),
    (u"COM_Phasage", u"Phasage"),
]


# =============================================================================
# Lecture Revit
# =============================================================================
def id_int(eid):
    try:
        return int(eid.Value)          # Revit 2024+ : Int64
    except AttributeError:
        return int(eid.IntegerValue)


def nom(el):
    if el is None:
        return u""
    try:
        return Element.Name.GetValue(el) or u""
    except Exception:
        try:
            return el.Name or u""
        except Exception:
            return u""


def famille(el):
    try:
        return nom(el.Symbol.Family)
    except Exception:
        return u""


def est_reservation(el):
    return isinstance(el, FamilyInstance) and famille(el).startswith(FAMILY_PREFIX)


def supprimee(el):
    """Reservation marquee supprimee (PVA_RES_DEM_Supprime coche)."""
    try:
        p = el.LookupParameter(SUPPRIME_PARAM)
        return p is not None and p.HasValue and p.StorageType == StorageType.Integer and p.AsInteger() == 1
    except Exception:
        return False


def reservations(doc, avec_supprimees=False):
    """Instances FGH_RES* du document, sans celles marquees supprimees (sauf demande)."""
    return [e for e in FilteredElementCollector(doc).OfClass(FamilyInstance)
            .WhereElementIsNotElementType().ToElements()
            if est_reservation(e) and (avec_supprimees or not supprimee(e))]


def texte_param(el, nom_param):
    """Valeur affichee d'un parametre, u'' si absent ou vide."""
    try:
        p = el.LookupParameter(nom_param)
        if p is None or not p.HasValue:
            return u""
        if p.StorageType == StorageType.String:
            return p.AsString() or u""
        if p.StorageType == StorageType.Integer and \
                u"bool" in u"{}".format(p.Definition.GetDataType().TypeId):
            return u"Oui" if p.AsInteger() else u"Non"
        return p.AsValueString() or u""
    except Exception:
        try:
            return el.LookupParameter(nom_param).AsValueString() or u""
        except Exception:
            return u""


def adn(el):
    return (texte_param(el, ADN_PARAM) or u"").strip()


def niveau(doc, el):
    try:
        lv = doc.GetElement(el.LevelId)
        if lv is not None:
            return nom(lv)
    except Exception:
        pass
    return texte_param(el, u"WSP_NiveauAssocie")


def donnees(doc, el, export_du):
    """[(nom, valeur texte)] du jeu STR_FGH_RES d'une reservation."""
    p = [(u"Cle ADN", adn(el)),
         (u"Revit UniqueId", el.UniqueId),
         (u"Revit ElementId", u"{}".format(id_int(el.Id))),
         (u"Famille", famille(el)),
         (u"Type", nom(doc.GetElement(el.GetTypeId()))),
         (u"Niveau", niveau(doc, el))]
    for nom_param, lib in PARAMS_FICHE:
        p.append((lib, texte_param(el, nom_param)))
    for nom_param in PARAMS_VAL:
        p.append((nom_param, texte_param(el, nom_param)))
    p.append((u"Maquette", doc.Title))
    p.append((u"Export du", export_du))
    return p


# =============================================================================
# Ecriture STEP
# =============================================================================
_ALPHABET = u"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def guid_ifc():
    """GlobalId IFC (22 caracteres en base 64 IFC) tire au hasard."""
    n = random.getrandbits(128)
    car = []
    for _ in range(22):
        car.append(_ALPHABET[n & 63])
        n >>= 6
    car.reverse()          # le premier caractere ne porte que 2 bits (0 a 3)
    return u"".join(car)


def chaine_step(s):
    """Texte -> chaine STEP : apostrophes doublees, accents en \\X2\\...\\X0\\."""
    if s is None:
        s = u""
    elif not isinstance(s, type(u"")):
        try:
            s = s.decode("utf-8")
        except Exception:
            s = u"{}".format(s)
    out = []
    bloc = []
    def vider():
        if bloc:
            out.append(u"\\X2\\" + u"".join(u"{:04X}".format(ord(c)) for c in bloc) + u"\\X0\\")
            del bloc[:]
    for c in s:
        o = ord(c)
        if 32 <= o < 127:
            vider()
            if c == u"'":
                out.append(u"''")
            elif c == u"\\":
                out.append(u"\\\\")
            else:
                out.append(c)
        elif o >= 127 and o < 0x10000:
            bloc.append(c)
        else:
            vider()
            out.append(u" ")
    vider()
    return u"'" + u"".join(out) + u"'"


_RX_ENTITE = re.compile(r"^#(\d+)\s*=\s*(IFC[A-Z0-9_]+)\s*\((.*)\)\s*;\s*$")
_RX_ID = re.compile(r"^#(\d+)\s*=")
_EXCLUS = ("IFCREL", "IFCPROPERTY", "IFCQUANTITY")


def _arguments(s):
    """Arguments de premier niveau d'une entite STEP."""
    args, prof, chaine, deb, i, n = [], 0, False, 0, 0, len(s)
    while i < n:
        c = s[i]
        if chaine:
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                chaine = False
        elif c == "'":
            chaine = True
        elif c == "(":
            prof += 1
        elif c == ")":
            prof -= 1
        elif c == "," and prof == 0:
            args.append(s[deb:i].strip())
            deb = i + 1
        i += 1
    args.append(s[deb:].strip())
    return args


def injecter(chemin_ifc, par_eid):
    """Ajoute le jeu STR_FGH_RES aux elements de l'IFC dont le Tag (ElementId
    ecrit par l'exporteur Revit) figure dans par_eid {u"123": [(nom, v)]}.
    Reecrit le fichier. Retourne (nb elements IFC lies, [ElementId absents])."""
    with io.open(chemin_ifc, "r", encoding="latin-1", newline="") as f:
        texte = f.read()
    lignes = texte.splitlines(True)
    max_id, fin_data, cibles = 0, None, []
    for k, ligne in enumerate(lignes):
        if ligne.startswith(u"#"):
            m_id = _RX_ID.match(ligne)
            if m_id:
                max_id = max(max_id, int(m_id.group(1)))
            if u"'" not in ligne:
                continue
            m = _RX_ENTITE.match(ligne.strip())
            if not m or m.group(2).startswith(_EXCLUS):
                continue
            a = _arguments(m.group(3))
            if len(a) < 8 or len(a[0]) != 24:
                continue
            tag = a[7]
            if len(tag) > 2 and tag[0] == u"'" and tag[-1] == u"'" and tag[1:-1] in par_eid:
                cibles.append((int(m.group(1)), a[1] or u"$", tag[1:-1]))
        elif ligne.strip() == u"ENDSEC;":
            fin_data = k
    if fin_data is None:
        raise ValueError(u"IFC illisible : section DATA introuvable.")
    eol = u"\r\n" if u"\r\n" in texte else u"\n"
    nouvelles, suivant = [], [max_id]

    def ent(t):
        suivant[0] += 1
        nouvelles.append(u"#{}={};{}".format(suivant[0], t, eol))
        return suivant[0]

    groupes = {}
    for eid_ifc, owner, tag in cibles:
        groupes.setdefault(tag, []).append((eid_ifc, owner))
    for tag in sorted(groupes):
        elems = groupes[tag]
        props = [ent(u"IFCPROPERTYSINGLEVALUE({},$,IFCTEXT({}),$)".format(
            chaine_step(n), chaine_step(v))) for n, v in par_eid[tag]]
        pset = ent(u"IFCPROPERTYSET({},{},{},$,({}))".format(
            chaine_step(guid_ifc()), elems[0][1], chaine_step(PSET_NOM),
            u",".join(u"#{}".format(i) for i in props)))
        ent(u"IFCRELDEFINESBYPROPERTIES({},{},$,$,({}),#{})".format(
            chaine_step(guid_ifc()), elems[0][1],
            u",".join(u"#{}".format(e) for e, _o in elems), pset))
    lignes[fin_data:fin_data] = nouvelles
    with io.open(chemin_ifc, "w", encoding="latin-1", newline="") as f:
        f.write(u"".join(lignes))
    absents = sorted((t for t in par_eid if t not in groupes), key=lambda t: (len(t), t))
    return len(cibles), absents
