# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "3.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Reservations RES vs STR"
# =============================================================================
__title__ = "Sync\nReservations"
__doc__   = "Analyse et synchronise les reservations FGH_RES* depuis la maquette SPV liee."

# =============================================================================
# IMPORTS — tous en tete, obligatoire IronPython
# =============================================================================
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
import System.IO
import System.Text
import System.Windows.Markup
import System.Windows.Media
import io
import os
import traceback

from System.Collections.ObjectModel import ObservableCollection

from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FilteredWorksetCollector,
    WorksetKind,
    RevitLinkInstance,
    FamilyInstance,
    StorageType,
    ElementId,
    ElementTransformUtils,
    CopyPasteOptions,
    BuiltInParameter,
    View3D,
    ViewFamilyType,
    ViewFamily,
    BoundingBoxXYZ,
    XYZ,
)
from System.Collections.Generic import List as ClrList

doc   = revit.doc
uidoc = revit.uidoc

# =============================================================================
# CONSTANTES METIER
# =============================================================================
LINK_MODEL_PREFIX  = "FGH_RES_SPV"
FAMILY_PREFIX      = "FGH_RES"

ADN_PARAM          = "CONTROL_NE_PAS_TOUCHER"
ADN_FILTER_VAL     = "_STATUT"
MUTUALISE_PARAM    = "FGH_MUTUALISE"

# Parametres demande (lus des deux cotes)
PARAM_NUM          = "PVA_RES_DEM_NumReservation"
PARAM_DEMANDEUR    = "PVA_RES_DEM_Demandeur"
PARAM_DATE         = "PVA_RES_DEM_Date"
PARAM_COMMENTAIRE  = "PVA_RES_DEM_Commentaire"
PARAM_NIVEAU       = "WSP_NiveauAssocie"
PARAM_X            = "WSP_PositionX_NM95"
PARAM_Y            = "WSP_PositionY_NM95"
PARAM_Z            = "WSP_PositionZ_NM95"
PARAM_CONTROL      = "CONTROL_NE_PAS_TOUCHER"

# Parametres validation (lus uniquement depuis le lien RES)
PARAM_VAL_STATUT   = "PVA_RES_VAL_Statut"
PARAM_VAL_DATE     = "PVA_RES_VAL_Date"
PARAM_VAL_COMMENT  = "PVA_RES_VAL_Commentaire"
PARAM_RES_DEM      = "RES_Demandeur"
PARAM_RES_RESP     = "RES_Responsable"

# Valeurs de statut validation
VAL_VALIDE         = "VALIDE"
VAL_REFUSE         = "REFUSE"

# Parametres sync
STATUT_VALIDE_VALUE = "VALID"
STATUT_SUPPRIMEE    = "SUPPRIMEE"   # valeur ecrite dans PVA_RES_VAL_Statut pour marquer Supprime STR
TARGET_WORKSET_NAME = "03_STR_RESERVATIONS"   # sous-projet cible pour les elements copies
VIEW_3D_NAME        = "STR_Reservations"       # nom de la vue 3D
VIEW_3D_TEMPLATE    = "3D_STR+RES"            # gabarit de vue a appliquer
VIEW_3D_MARGIN_M    = 0.5                       # marge autour du bounding box (metres)
PARAM_MODIFIE       = "PVA_RES_DEM_Modifie"
PARAM_SUPPRIME      = "PVA_RES_DEM_Supprime"
PARAM_NOUVEAU       = "PVA_RES_DEM_Nouveau"

# Statuts de comparaison
STATUT_ABSENT   = "ABSENT"
STATUT_DIFF     = "DIFFERENT"
STATUT_STR_SEUL = "STR_SEUL"
STATUT_OK       = "OK"
STATUT_INVALID  = "INVALIDE"   # Cas D : valide au 1er round, refuse/vide au 2eme

# =============================================================================
# LABELS LOCALISES — accents ecrits directement en UTF-8 (encoding declare ligne 1)
# =============================================================================
LBL_WINDOW      = u"{}  [v{}]"
LBL_FOOTER      = u"v{} | STR BIM Tools by Tony Varin"
LBL_TITRE       = u"Comparaison Réservations — STR ({} él.) vs SPV/{} ({} él.)"
LBL_ABSENT_STAT = u"✖ Absentes : {}"
LBL_DIFF_STAT   = u"⚠ Différentes : {}"
LBL_INVALID_STAT = u"⛔ Invalidées : {}"
LBL_OK_STAT     = u"✔ OK : {}"
LBL_STR_STAT    = u"STR seul : {}"
LBL_TOTAL_STAT  = u"Total lien : {}  |  Total hôte : {}"

LBL_ABSENT_DET  = u"Non présente dans la maquette STR"
LBL_STR_DET     = u"Présente dans STR mais absente du lien SPV"
LBL_INVALID_DET = u"Validation retirée ou refusée — à supprimer de la STR"

# En-tetes colonnes DataGrid
HDR_VAL_STATUT  = u"Statut VAL"
HDR_STATUT      = u"Statut Synchro"
HDR_NUM         = u"N° Réservation"
HDR_FAMILLE     = u"Famille"
HDR_NIVEAU      = u"Niveau"
HDR_DEMANDEUR   = u"Demandeur"
HDR_DATE_DEM    = u"Date dem."
HDR_RES_DEM     = u"RES Dem."
HDR_RES_RESP    = u"Responsable"
HDR_VAL_DATE    = u"Date VAL"
HDR_VAL_COMMENT = u"Commentaire VAL"
HDR_DETAIL      = u"Détail / Différences"

LBL_BTN_SYNC      = u"Synchroniser"
LBL_BTN_CSV       = u"Exporter CSV"
LBL_BTN_CLOSE     = u"Fermer"
LBL_BTN_CHECK_ALL = u"Tout cocher"
LBL_BTN_UNCHECK   = u"Tout décocher"
LBL_BTN_VIEW3D    = u"Vue 3D"
LBL_SEL_COUNT     = u"{} sélectionnée(s)"
HDR_SEL           = u""

MSG_VIEW3D_NONE   = u"Aucune réservation sélectionnée avec un élément local à visualiser."
MSG_VIEW3D_ERR    = u"Erreur lors de la création de la vue 3D :\n\n{}"
MSG_VIEW3D_OK     = u"Vue 3D '{}' ouverte avec une zone de coupe autour de {} élément(s)."
MSG_VIEW3D_NOTPL  = u"Gabarit de vue '{}' introuvable.\nLa vue est créée sans gabarit."

LBL_NO_LINK     = u"Aucune maquette liée dont le nom contient '{}' n'a été trouvée.\n\nVérifie que la maquette est chargée."
LBL_NO_RES      = u"Aucune réservation (famille '{}') trouvée dans le lien."

LBL_CSV_HEADER  = u"StatutVAL;StatutSTR;Numero;Famille;Niveau;Demandeur;DateDem;RESDem;Responsable;DateVal;CommentaireVAL;Detail"
LBL_CSV_OK      = u"Export CSV réussi :\n{}"
LBL_CSV_ERR     = u"Erreur export CSV :\n{}"

MSG_CONFIRM_SYNC = (
    u"Synchronisation : {} élément(s) à traiter\n\n"
    u"  • Cas A - Nouveaux à copier            : {}\n"
    u"  • Cas B - Modifiés à mettre à jour      : {}\n"
    u"  • Cas C - à marquer supprimés          : {}\n"
    u"  • Cas D - Validation retirée/refusée  : {}\n\n"
    u"Seules les réservations VALID sont copiées.\n"
    u"Les Cas D seront marqués Supprimé dans la STR.\n"
    u"Confirmer ?"
)
MSG_SYNC_RESULT = (
    u"Synchronisation terminée :\n\n"
    u"  Cas A - Nouveaux copiés              : {}\n"
    u"  Cas B - Modifiés copiés              : {}\n"
    u"  Cas B - Anciennes supprimées         : {}\n"
    u"  Cas C - Marqués supprimés            : {}\n"
    u"  Cas D - Invalides marqués supprimés  : {}\n\n"
    u"Total copiés : {}  |  Total marqués : {}"
)
MSG_SYNC_ERR    = u"Erreur lors de la synchronisation :\n\n{}"
MSG_NOTHING     = u"Aucun élément à synchroniser dans la sélection (ABSENT, DIFFERENT ou INVALIDE attendus)."
MSG_WORKSET_NOT_FOUND = (
    u"⚠ AVERTISSEMENT : le sous-projet '{}' est introuvable dans la maquette.\n"
    u"Les éléments copiés sont restés dans le sous-projet actif.\n"
    u"Pense à les déplacer manuellement ou à créer le sous-projet avant la prochaine synchro."
)

# =============================================================================
# SECTION : LECTURE PARAMETRES REVIT
# =============================================================================

def _get_param_str(element, param_name):
    """Lit un parametre texte, retourne string ou None."""
    try:
        p = element.LookupParameter(param_name)
        if p and p.HasValue:
            if p.StorageType == StorageType.String:
                v = p.AsString()
                return v if v and v.strip() else None
            vs = p.AsValueString()
            return vs if vs and vs.strip() else None
    except Exception:
        pass
    return None


def _get_param_int(element, param_name):
    """Lit un parametre Integer, retourne int ou None."""
    try:
        p = element.LookupParameter(param_name)
        if p and p.HasValue and p.StorageType == StorageType.Integer:
            return p.AsInteger()
    except Exception:
        pass
    return None


def _get_param_value_str(element, param_name):
    """Lit un parametre et retourne sa valeur sous forme de string pour comparaison."""
    try:
        p = element.LookupParameter(param_name)
        if p is None:
            return ""
        st = p.StorageType
        if st == StorageType.String:
            return p.AsString() or ""
        elif st == StorageType.Double:
            return str(round(p.AsDouble(), 6))
        elif st == StorageType.Integer:
            return str(p.AsInteger())
        elif st == StorageType.ElementId:
            eid = p.AsElementId()
            return str(eid.IntegerValue) if eid else ""
    except Exception:
        pass
    return ""


def _set_param_value(element, param_name, value):
    """Ecrit une valeur dans un parametre Revit. Retourne True si OK."""
    try:
        p = element.LookupParameter(param_name)
        if not p or p.IsReadOnly:
            return False
        if p.StorageType == StorageType.Integer:
            p.Set(int(value))
            return True
        if p.StorageType == StorageType.String:
            p.Set("" if value is None else str(value))
            return True
        if p.StorageType == StorageType.Double:
            p.Set(float(value))
            return True
    except Exception:
        pass
    return False


# =============================================================================
# SECTION : COLLECTE DES ELEMENTS
# =============================================================================

def collect_host_reservations():
    """
    Collecte les FamilyInstance FGH_RES* de la maquette hote.
    Exclusion : elements dont PVA_RES_VAL_Statut == 'SUPPRIMEE'
    (marques par l'outil Sync en Cas B/C/D).
    """
    result = []
    for e in FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements():
        try:
            if e.Symbol.Family.Name.startswith(FAMILY_PREFIX):
                if _get_param_str(e, PARAM_VAL_STATUT) != STATUT_SUPPRIMEE:
                    result.append(e)
        except Exception:
            pass
    return result


def find_link_instance():
    """Trouve la premiere RevitLinkInstance dont le nom contient LINK_MODEL_PREFIX."""
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        try:
            if LINK_MODEL_PREFIX in lnk.Name:
                return lnk
        except Exception:
            pass
    return None


def collect_link_reservations(link_instance):
    """
    Collecte les reservations du lien avec filtres inclusion/exclusion.
    Inclusion AND : famille FGH_RES* + ADN contient _STATUT
    Exclusion    : FGH_MUTUALISE = 1
    Note : PVA_RES_DEM_Supprime=1 (cote SPV) reste inclus — necessaire pour Cas C.
           C'est un parametre lu depuis le lien, pas ecrit par la STR.
    """
    linked_doc = link_instance.GetLinkDocument()
    if not linked_doc:
        return []
    result = []
    for e in FilteredElementCollector(linked_doc).OfClass(FamilyInstance).ToElements():
        try:
            if not e.Symbol.Family.Name.startswith(FAMILY_PREFIX):
                continue
            adn = _get_param_str(e, ADN_PARAM) or ""
            if ADN_FILTER_VAL not in adn:
                continue
            if _get_param_int(e, MUTUALISE_PARAM) == 1:
                continue
            result.append(e)
        except Exception:
            pass
    return result


# =============================================================================
# SECTION : COMPARAISON
# =============================================================================

def _build_snapshot(element):
    """Construit un dict des valeurs de parametres comparables."""
    return {
        "demandeur":   _get_param_value_str(element, PARAM_DEMANDEUR),
        "date":        _get_param_value_str(element, PARAM_DATE),
        "commentaire": _get_param_value_str(element, PARAM_COMMENTAIRE),
        "niveau":      _get_param_value_str(element, PARAM_NIVEAU),
        "x":           _get_param_value_str(element, PARAM_X),
        "y":           _get_param_value_str(element, PARAM_Y),
        "z":           _get_param_value_str(element, PARAM_Z),
        "control":     _get_param_value_str(element, PARAM_CONTROL),
    }


def _diff_detail(snap_host, snap_link):
    """Retourne une string decrivant les differences entre deux snapshots."""
    labels = [
        ("demandeur",   "Demandeur"),
        ("date",        "Date"),
        ("commentaire", "Commentaire"),
        ("niveau",      "Niveau"),
        ("x",           "X NM95"),
        ("y",           "Y NM95"),
        ("z",           "Z NM95"),
        ("control",     "Control"),
    ]
    parts = []
    for key, label in labels:
        v_h = snap_host.get(key, "") or ""
        v_l = snap_link.get(key, "") or ""
        if v_h != v_l:
            parts.append(u"{}: STR=[{}] / SPV=[{}]".format(label, v_h, v_l))
    return u" | ".join(parts)


def _get_family_name(element):
    try:
        return element.Symbol.Family.Name
    except Exception:
        return ""


def _normalize_val_statut(raw):
    """
    Normalise la valeur de PVA_RES_VAL_Statut pour l'affichage et le tri.
    Retourne 'VALIDE', 'REFUSE', ou '' (vide).
    """
    if not raw:
        return ""
    upper = raw.strip().upper()
    if "VALID" in upper:
        return VAL_VALIDE
    if "REFUS" in upper:
        return VAL_REFUSE
    return raw.strip()


def _val_statut_sort_key(val_statut):
    """
    Cle de tri pour PVA_RES_VAL_Statut :
    0 = VALIDE, 1 = REFUSE, 2 = autre/vide
    """
    if val_statut == VAL_VALIDE:
        return 0
    if val_statut == VAL_REFUSE:
        return 1
    return 2


def _date_to_sort_key(date_str):
    """
    Convertit une date DD/MM/YYYY en YYYYMMDD pour un tri chronologique correct.
    Retourne '00000000' si la date est vide ou non parseable (dates vides en dernier).
    """
    if not date_str:
        return "00000000"
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return "{}{}{}".format(parts[2], parts[1].zfill(2), parts[0].zfill(2))
    except Exception:
        pass
    return "00000000"


class ReservationRow(object):
    """Objet de donnee pour une ligne du DataGrid."""
    def __init__(self, num, famille, niveau, statut, detail,
                 demandeur, date_dem,
                 val_statut, val_date, val_comment,
                 res_dem, res_resp,
                 link_element=None, host_element=None):
        self.Num          = num
        self.Famille      = famille
        self.Niveau       = niveau
        self.Statut       = statut
        self.Detail       = detail
        self.Demandeur    = demandeur
        self.DateDem      = date_dem
        self.ValStatut    = val_statut
        self.ValDate      = val_date
        self.ValComment   = val_comment
        self.ResDem       = res_dem
        self.ResResp      = res_resp
        self._link_elem   = link_element
        self._host_elem   = host_element

        # Cles de tri chronologique pour les colonnes dates (YYYYMMDD)
        self.DateDemSort  = _date_to_sort_key(date_dem)
        self.ValDateSort  = _date_to_sort_key(val_date)

        # Ligne actionnable = peut etre synchronisee
        self.IsSelectable = statut in (STATUT_ABSENT, STATUT_DIFF, STATUT_INVALID)

        # Cochee par defaut uniquement si elle sera reellement synchronisee :
        # - Cas D (INVALIDE) : toujours coche, independant du statut VAL
        # - Cas A/B/C (ABSENT ou DIFFERENT) : seulement si VAL contient VALID
        if statut == STATUT_INVALID:
            self.IsSelected = True
        elif statut in (STATUT_ABSENT, STATUT_DIFF):
            self.IsSelected = STATUT_VALIDE_VALUE.lower() in (val_statut or "").lower()
        else:
            self.IsSelected = False

        # Couleur de ligne
        if statut == STATUT_INVALID:
            self.RowBg = "#FFD9A0"
        elif val_statut == VAL_VALIDE:
            self.RowBg = "#DFF0D8"
        elif val_statut == VAL_REFUSE:
            self.RowBg = "#FDDEDE"
        elif statut == STATUT_DIFF:
            self.RowBg = "#FFF3CD"
        elif statut == STATUT_STR_SEUL:
            self.RowBg = "#ECECEC"
        else:
            self.RowBg = "#FFFFFF"


def compare_reservations(host_elems, link_elems):
    """
    Compare les deux ensembles.
    Tri : d'abord par statut VAL (VALIDE > REFUSE > vide),
          puis par statut STR (INVALIDE > ABSENT > DIFFERENT > STR_SEUL > OK).
    Retourne (rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid).
    """
    host_by_num = {}
    for e in host_elems:
        num = _get_param_str(e, PARAM_NUM) or ""
        if num:
            host_by_num[num] = e

    link_by_num = {}
    for e in link_elems:
        num = _get_param_str(e, PARAM_NUM) or ""
        if num:
            link_by_num[num] = e

    rows        = []
    nb_absent   = 0
    nb_diff     = 0
    nb_ok       = 0
    nb_str_seul = 0
    nb_invalid  = 0

    # Elements du lien
    for num, e_link in link_by_num.items():
        val_statut  = _normalize_val_statut(_get_param_str(e_link, PARAM_VAL_STATUT))
        val_date    = _get_param_str(e_link, PARAM_VAL_DATE)    or ""
        val_comment = _get_param_str(e_link, PARAM_VAL_COMMENT) or ""
        res_dem     = _get_param_str(e_link, PARAM_RES_DEM)     or ""
        res_resp    = _get_param_str(e_link, PARAM_RES_RESP)    or ""

        e_host = host_by_num.get(num)

        if e_host is None:
            # Element absent en local
            nb_absent += 1
            rows.append(ReservationRow(
                num=num,
                famille=_get_family_name(e_link),
                niveau=_get_param_value_str(e_link, PARAM_NIVEAU),
                statut=STATUT_ABSENT,
                detail=LBL_ABSENT_DET,
                demandeur=_get_param_str(e_link, PARAM_DEMANDEUR) or "",
                date_dem=_get_param_str(e_link, PARAM_DATE) or "",
                val_statut=val_statut, val_date=val_date,
                val_comment=val_comment, res_dem=res_dem, res_resp=res_resp,
                link_element=e_link, host_element=None,
            ))
        else:
            # Element present en local — verifier le Cas D en priorite
            # Cas D : deja copie en local + validation retiree ou refusee
            # Condition : val_statut != VALIDE ET element present en local
            # (couvre REFUSE, vide, et tout autre statut non-VALID)
            if val_statut != VAL_VALIDE:
                nb_invalid += 1
                detail_d = LBL_INVALID_DET
                if val_statut == VAL_REFUSE:
                    detail_d = u"Réservation refusée — à supprimer de la STR"
                elif not val_statut:
                    detail_d = u"Validation retirée (statut vide) — à supprimer de la STR"
                rows.append(ReservationRow(
                    num=num,
                    famille=_get_family_name(e_link),
                    niveau=_get_param_value_str(e_link, PARAM_NIVEAU),
                    statut=STATUT_INVALID,
                    detail=detail_d,
                    demandeur=_get_param_str(e_link, PARAM_DEMANDEUR) or "",
                    date_dem=_get_param_str(e_link, PARAM_DATE) or "",
                    val_statut=val_statut, val_date=val_date,
                    val_comment=val_comment, res_dem=res_dem, res_resp=res_resp,
                    link_element=e_link, host_element=e_host,
                ))
            else:
                # Cas normal : comparer les parametres
                snap_link = _build_snapshot(e_link)
                snap_host = _build_snapshot(e_host)
                detail    = _diff_detail(snap_host, snap_link)
                if detail:
                    nb_diff += 1
                    rows.append(ReservationRow(
                        num=num,
                        famille=_get_family_name(e_link),
                        niveau=_get_param_value_str(e_link, PARAM_NIVEAU),
                        statut=STATUT_DIFF,
                        detail=detail,
                        demandeur=_get_param_str(e_link, PARAM_DEMANDEUR) or "",
                        date_dem=_get_param_str(e_link, PARAM_DATE) or "",
                        val_statut=val_statut, val_date=val_date,
                        val_comment=val_comment, res_dem=res_dem, res_resp=res_resp,
                        link_element=e_link, host_element=e_host,
                    ))
                else:
                    nb_ok += 1
                    rows.append(ReservationRow(
                        num=num,
                        famille=_get_family_name(e_link),
                        niveau=_get_param_value_str(e_link, PARAM_NIVEAU),
                        statut=STATUT_OK,
                        detail="",
                        demandeur=_get_param_str(e_link, PARAM_DEMANDEUR) or "",
                        date_dem=_get_param_str(e_link, PARAM_DATE) or "",
                        val_statut=val_statut, val_date=val_date,
                        val_comment=val_comment, res_dem=res_dem, res_resp=res_resp,
                        link_element=e_link, host_element=e_host,
                    ))

    # Elements STR absents du lien
    for num, e_host in host_by_num.items():
        if num not in link_by_num:
            nb_str_seul += 1
            rows.append(ReservationRow(
                num=num,
                famille=_get_family_name(e_host),
                niveau=_get_param_value_str(e_host, PARAM_NIVEAU),
                statut=STATUT_STR_SEUL,
                detail=LBL_STR_DET,
                demandeur=_get_param_str(e_host, PARAM_DEMANDEUR) or "",
                date_dem=_get_param_str(e_host, PARAM_DATE) or "",
                val_statut="", val_date="", val_comment="",
                res_dem="", res_resp="",
                link_element=None, host_element=e_host,
            ))

    # Double tri : 1) INVALIDE en premier, puis statut VAL, puis statut STR
    cmp_order = {
        STATUT_INVALID:  0,
        STATUT_ABSENT:   1,
        STATUT_DIFF:     2,
        STATUT_STR_SEUL: 3,
        STATUT_OK:       4,
    }
    rows.sort(key=lambda r: (
        0 if r.Statut == STATUT_INVALID else 1,   # INVALIDE toujours en premier
        _val_statut_sort_key(r.ValStatut),
        cmp_order.get(r.Statut, 9)
    ))

    return rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid


# =============================================================================
# SECTION : SYNCHRONISATION
# =============================================================================

def _is_statut_valide(link_element):
    """Verifie que PVA_RES_VAL_Statut contient 'VALID' (insensible casse)."""
    statut = _get_param_str(link_element, PARAM_VAL_STATUT) or ""
    return STATUT_VALIDE_VALUE.lower() in statut.lower()


# Constantes de classification des cas
CAS_A = "A"   # nouveau a copier
CAS_B = "B"   # modifie a mettre a jour (copie + ancien marque supprime)
CAS_C = "C"   # marquer local supprime (annulation demandeur)
CAS_D = "D"   # validation retiree/refusee apres integration
CAS_NONE = None   # ligne non actionnable


def _classify_row(row):
    """
    Determine dans quel cas A/B/C/D tombe une ligne de reservation.
    Source unique de verite pour la logique de synchronisation.
    Retourne CAS_A, CAS_B, CAS_C, CAS_D ou CAS_NONE.
    """
    e_link = row._link_elem
    e_host = row._host_elem

    # Cas D : INVALIDE avec element local (traite en priorite)
    if row.Statut == STATUT_INVALID and e_host is not None:
        return CAS_D

    # Cas A/B/C necessitent ABSENT ou DIFFERENT + lien valide
    if row.Statut not in (STATUT_ABSENT, STATUT_DIFF):
        return CAS_NONE
    if e_link is None:
        return CAS_NONE
    if not _is_statut_valide(e_link):
        return CAS_NONE

    supprime_lien = _get_param_int(e_link, PARAM_SUPPRIME)
    modifie_lien  = _get_param_int(e_link, PARAM_MODIFIE)

    if row.Statut == STATUT_ABSENT:
        if supprime_lien != 1:
            return CAS_A
        return CAS_NONE

    # row.Statut == STATUT_DIFF
    if supprime_lien == 1 and e_host is not None:
        return CAS_C
    if modifie_lien == 1 and e_host is not None:
        return CAS_B
    return CAS_A


def _find_workset_id(workset_name):
    """
    Recherche le sous-projet par son nom via FilteredWorksetCollector.
    C'est la methode standard en Revit 2024 pour iterer les worksets.
    Retourne un WorksetId ou None si non trouve / projet non collaboratif.
    """
    try:
        if not doc.IsWorkshared:
            return None
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            if ws.Name == workset_name:
                return ws.Id
    except Exception:
        pass
    return None


def _assign_to_workset(elements, workset_id):
    """
    Assigne une liste d'elements au sous-projet identifie par workset_id (WorksetId).
    ELEM_PARTITION_PARAM attend un Integer : p.Set(workset_id.IntegerValue).
    Retourne le nombre d'elements assignes avec succes.
    """
    if not elements or workset_id is None:
        return 0
    count = 0
    for e in elements:
        try:
            p = e.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
            if p and not p.IsReadOnly:
                p.Set(workset_id.IntegerValue)
                count += 1
        except Exception:
            pass
    return count


_PARAMS_COPY = [
    PARAM_NUM, PARAM_DEMANDEUR, PARAM_DATE, PARAM_COMMENTAIRE,
    PARAM_NIVEAU, PARAM_X, PARAM_Y, PARAM_Z, PARAM_CONTROL,
    PARAM_VAL_STATUT, PARAM_VAL_DATE, PARAM_VAL_COMMENT,
    PARAM_RES_DEM, PARAM_RES_RESP,
]


def _copy_elements_from_link(link_instance, elements):
    """
    Copie une liste d'elements depuis le lien vers la maquette hote.
    CopyElements entre documents ne preserve pas les parametres shared —
    copie explicite apres la geometrie.
    """
    if not elements:
        return []
    linked_doc = link_instance.GetLinkDocument()
    transform  = link_instance.GetTotalTransform()
    opts       = CopyPasteOptions()
    ids        = ClrList[ElementId]()
    for e in elements:
        ids.Add(e.Id)
    new_ids = ElementTransformUtils.CopyElements(
        linked_doc, ids, doc, transform, opts
    )
    copied = []
    for nid in new_ids:
        e = doc.GetElement(nid)
        if e:
            copied.append(e)

    if len(copied) == len(elements):
        for src, dst in zip(elements, copied):
            for pname in _PARAMS_COPY:
                try:
                    p_src = src.LookupParameter(pname)
                    p_dst = dst.LookupParameter(pname)
                    if not p_src or not p_dst or p_dst.IsReadOnly:
                        continue
                    st = p_src.StorageType
                    if st == StorageType.String:
                        p_dst.Set(p_src.AsString() or "")
                    elif st == StorageType.Double:
                        p_dst.Set(p_src.AsDouble())
                    elif st == StorageType.Integer:
                        p_dst.Set(p_src.AsInteger())
                except Exception:
                    pass

    return copied


def _mark_as_new(elements):
    """Cas A : marque comme nouveaux (reset Modifie, pas de touche a VAL_Statut)."""
    for e in elements:
        _set_param_value(e, PARAM_NOUVEAU, 1)
        _set_param_value(e, PARAM_MODIFIE, 0)


def _mark_as_deleted(elements):
    """
    Cas B (ancien), Cas C, Cas D : marque l'element STR comme supprime.
    Ecrit 'SUPPRIMEE' dans PVA_RES_VAL_Statut — c'est ce statut que
    collect_host_reservations() utilise pour exclure ces elements a la prochaine synchro.
    Ecrit aussi la date dans PVA_RES_DEM_Commentaire pour la tracabilite.
    """
    comment = u"Supprimé le : {}".format(
        System.DateTime.Now.ToString("dd/MM/yyyy")
    )
    count = 0
    for e in elements:
        _set_param_value(e, PARAM_VAL_STATUT,  STATUT_SUPPRIMEE)
        _set_param_value(e, PARAM_MODIFIE,     0)
        _set_param_value(e, PARAM_NOUVEAU,     0)
        _set_param_value(e, PARAM_COMMENTAIRE, comment)
        count += 1
    return count


def _pin_elements(elements):
    """Epingle les elements pour empecher un deplacement accidentel."""
    for e in elements:
        try:
            e.Pinned = True
        except Exception:
            pass


def synchronize_reservations(rows, link_instance):
    """
    Execute la synchronisation Cas A / B / C / D.
    Cas D : element present en local + validation retiree/refusee dans le lien
            → marquer local Supprime=1 + vider PVA_RES_VAL_Statut
    Retourne (nb_cas_a, nb_cas_b_copies, nb_cas_b_marks, nb_cas_c, nb_cas_d,
              workset_not_found, erreur_str)
    """
    cas_a_sources    = []
    cas_b_sources    = []
    cas_b_old_locals = []
    cas_c_locals     = []
    cas_d_locals     = []

    for row in rows:
        cas = _classify_row(row)
        if cas == CAS_A:
            cas_a_sources.append(row._link_elem)
        elif cas == CAS_B:
            cas_b_sources.append(row._link_elem)
            cas_b_old_locals.append(row._host_elem)
        elif cas == CAS_C:
            cas_c_locals.append(row._host_elem)
        elif cas == CAS_D:
            cas_d_locals.append(row._host_elem)

    nb_cas_a        = 0
    nb_cas_b_copies = 0
    nb_cas_b_marks  = 0
    nb_cas_c        = 0
    nb_cas_d        = 0

    workset_id         = _find_workset_id(TARGET_WORKSET_NAME)
    workset_not_found  = (workset_id is None) and (len(cas_a_sources) + len(cas_b_sources) > 0)

    try:
        if cas_a_sources:
            with revit.Transaction(u"STR - Sync Reservations Cas A"):
                copied_a = _copy_elements_from_link(link_instance, cas_a_sources)
                _mark_as_new(copied_a)
                _pin_elements(copied_a)
                if workset_id is not None:
                    _assign_to_workset(copied_a, workset_id)
                nb_cas_a = len(copied_a)

        if cas_b_sources:
            with revit.Transaction(u"STR - Sync Reservations Cas B"):
                copied_b = _copy_elements_from_link(link_instance, cas_b_sources)
                _pin_elements(copied_b)
                if workset_id is not None:
                    _assign_to_workset(copied_b, workset_id)
                nb_cas_b_copies = len(copied_b)
                nb_cas_b_marks  = _mark_as_deleted(cas_b_old_locals)

        if cas_c_locals:
            with revit.Transaction(u"STR - Sync Reservations Cas C"):
                nb_cas_c = _mark_as_deleted(cas_c_locals)

        if cas_d_locals:
            with revit.Transaction(u"STR - Sync Reservations Cas D"):
                nb_cas_d = _mark_as_deleted(cas_d_locals)

    except Exception:
        return (nb_cas_a, nb_cas_b_copies, nb_cas_b_marks, nb_cas_c, nb_cas_d,
                workset_not_found, traceback.format_exc())

    return (nb_cas_a, nb_cas_b_copies, nb_cas_b_marks, nb_cas_c, nb_cas_d,
            workset_not_found, None)


# =============================================================================
# SECTION : VUE 3D
# =============================================================================

def _get_or_create_3d_view(view_name):
    """
    Retourne la vue 3D nommee view_name si elle existe,
    sinon la cree a partir du premier ViewFamilyType 3D isometrique.
    Retourne (view, created_flag) ou (None, False) en cas d'erreur.
    """
    existing = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v in existing:
        if not v.IsTemplate and v.Name == view_name:
            return v, False

    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if t.ViewFamily == ViewFamily.ThreeDimensional:
            vft = t
            break

    if vft is None:
        return None, False

    with revit.Transaction(u"STR - Creer vue 3D reservations"):
        view = View3D.CreateIsometric(doc, vft.Id)
        view.Name = view_name

    return view, True


def _find_view_template(template_name):
    """
    Recherche un gabarit de vue 3D par son nom exact.
    Retourne l'ElementId du gabarit ou ElementId.InvalidElementId si non trouve.
    """
    views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v in views:
        if v.IsTemplate and v.Name == template_name:
            return v.Id
    return ElementId.InvalidElementId


def _compute_bounding_box(elem_transform_pairs, margin_ft):
    """
    Calcule le bounding box englobant une liste de (element, transform_or_None).
    Si transform est fourni, les coins du BB sont transformes dans le repere hote.
    Ajoute une marge margin_ft (en pieds) sur chaque face.
    Retourne un BoundingBoxXYZ ou None si aucun element n'a de geometrie.
    """
    min_x = min_y = min_z =  1e18
    max_x = max_y = max_z = -1e18
    found = False

    for e, transform in elem_transform_pairs:
        try:
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue

            # Construire les 8 coins du bounding box
            corners = [
                XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z),
                XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
                XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z),
                XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
                XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z),
                XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
                XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z),
                XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
            ]

            # Appliquer la transformation si presente (element de lien)
            if transform is not None:
                corners = [transform.OfPoint(c) for c in corners]

            for c in corners:
                found = True
                if c.X < min_x: min_x = c.X
                if c.Y < min_y: min_y = c.Y
                if c.Z < min_z: min_z = c.Z
                if c.X > max_x: max_x = c.X
                if c.Y > max_y: max_y = c.Y
                if c.Z > max_z: max_z = c.Z
        except Exception:
            pass

    if not found:
        return None

    crop_box = BoundingBoxXYZ()
    crop_box.Min = XYZ(min_x - margin_ft, min_y - margin_ft, min_z - margin_ft)
    crop_box.Max = XYZ(max_x + margin_ft, max_y + margin_ft, max_z + margin_ft)
    return crop_box


def open_3d_cropbox(rows, link_instance):
    """
    Ouvre la vue 3D STR_Reservations avec une zone de coupe calculee
    autour des elements coches.
    - Si _host_elem existe  : utilise l'element local (STR)
    - Si _host_elem est None : utilise _link_elem transforme (RES lie)
    Applique le gabarit de vue VIEW_3D_TEMPLATE (3D_STR+RES).
    Retourne (view_or_None, message_str).
    """
    # Recuperer la transformation du lien une seule fois
    try:
        link_transform = link_instance.GetTotalTransform()
    except Exception:
        link_transform = None

    # Construire la liste (element, transform_or_None) pour les lignes cochees
    elem_pairs = []
    for row in rows:
        if not row.IsSelected:
            continue
        if row._host_elem is not None:
            # Element local — pas de transformation necessaire
            elem_pairs.append((row._host_elem, None))
        elif row._link_elem is not None:
            # Element absent de STR — utiliser le lien avec sa transformation
            elem_pairs.append((row._link_elem, link_transform))

    if not elem_pairs:
        return None, MSG_VIEW3D_NONE

    try:
        margin_ft = VIEW_3D_MARGIN_M * 3.28084

        crop_box = _compute_bounding_box(elem_pairs, margin_ft)
        if crop_box is None:
            return None, u"Impossible de calculer le bounding box des éléments sélectionnés."

        view, _created = _get_or_create_3d_view(VIEW_3D_NAME)
        if view is None:
            return None, u"Impossible de trouver ou créer un type de vue 3D isometrique."

        template_id  = _find_view_template(VIEW_3D_TEMPLATE)
        has_template = (template_id != ElementId.InvalidElementId)

        warn_no_tpl = ""
        if not has_template:
            warn_no_tpl = u"\n\n" + MSG_VIEW3D_NOTPL.format(VIEW_3D_TEMPLATE)

        with revit.Transaction(u"STR - Vue 3D zone de coupe reservations"):
            if has_template:
                view.ViewTemplateId = template_id
            # Zone de coupe (SectionBox) uniquement — pas de cadrage
            view.IsSectionBoxActive = True
            view.SetSectionBox(crop_box)

        uidoc.ActiveView = view
        uidoc.RequestViewChange(view)

        msg = MSG_VIEW3D_OK.format(VIEW_3D_NAME, len(elem_pairs)) + warn_no_tpl
        return view, msg

    except Exception:
        return None, MSG_VIEW3D_ERR.format(traceback.format_exc())


# =============================================================================
# SECTION : INTERFACE WPF
# REGLE : XAML en ASCII strict — accents assignes via .Text / .Header en Python
# =============================================================================

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="" Width="1380" Height="680"
    ResizeMode="CanResize" Background="White"
    WindowStartupLocation="CenterScreen">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Titre -->
    <TextBlock x:Name="lbl_titre" Grid.Row="0"
               FontSize="13" FontWeight="SemiBold"
               Margin="10,10,10,4"/>

    <!-- Barre de statistiques -->
    <Border Grid.Row="1" Background="#F0F4FA"
            BorderBrush="#C0D0E0" BorderThickness="0,0,0,1"
            Padding="10,6" Margin="0,0,0,4">
      <StackPanel Orientation="Horizontal">
        <Border Background="#DFF0D8" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_valide" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FDDEDE" CornerRadius="4" Padding="8,3" Margin="0,0,16,0">
          <TextBlock x:Name="lbl_refuse" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FDDEDE" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_absent" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FFF3CD" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_diff" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FFD9A0" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_invalid" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#DFF0D8" CornerRadius="4" Padding="8,3" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_ok" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#E8E8E8" CornerRadius="4" Padding="8,3" Margin="0,0,16,0">
          <TextBlock x:Name="lbl_str_seul" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <TextBlock x:Name="lbl_total" FontSize="12"
                   VerticalAlignment="Center" Foreground="#444444"/>
        <!-- Separateur -->
        <Separator Width="1" Background="#C0D0E0" Margin="12,2,12,2"/>
        <!-- Compteur selection -->
        <Border Background="#E8F0FA" CornerRadius="4" Padding="8,3">
          <TextBlock x:Name="lbl_sel_count" FontSize="12" FontWeight="SemiBold"
                     Foreground="#2980B9"/>
        </Border>
        <!-- Boutons tout cocher / decocher -->
        <Button x:Name="btn_check_all" Content="Tout cocher"
                Width="95" Height="24" Margin="8,0,4,0"
                Background="#BDC3C7" Foreground="#333333"
                BorderThickness="0" FontSize="11"/>
        <Button x:Name="btn_uncheck_all" Content="Tout decocher"
                Width="105" Height="24"
                Background="#BDC3C7" Foreground="#333333"
                BorderThickness="0" FontSize="11"/>
      </StackPanel>
    </Border>

    <!-- DataGrid -->
    <DataGrid x:Name="dg_main" Grid.Row="2"
              Margin="8,0,8,4"
              AutoGenerateColumns="False"
              IsReadOnly="False"
              GridLinesVisibility="Horizontal"
              BorderBrush="#C0D0E0" BorderThickness="1"
              HeadersVisibility="Column"
              SelectionMode="Single"
              CanUserResizeColumns="True"
              CanUserSortColumns="True"
              FontSize="12"
              RowBackground="White"
              AlternatingRowBackground="#E8F0FA">
      <DataGrid.RowStyle>
        <Style TargetType="DataGridRow">
          <Setter Property="Background" Value="{Binding RowBg}"/>
        </Style>
      </DataGrid.RowStyle>
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,4"/>
          <Setter Property="BorderBrush" Value="#C0D0E0"/>
          <Setter Property="BorderThickness" Value="0,0,1,1"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <!-- Colonne checkbox : DataGridCheckBoxColumn avec SortMemberPath pour le tri -->
        <DataGridCheckBoxColumn Header="" Binding="{Binding IsSelected, Mode=TwoWay}"
                                Width="34" IsReadOnly="False" SortMemberPath="IsSelected"/>
        <!-- Groupe validation (VAL) -->
        <DataGridTextColumn Header="StatutVAL"   Binding="{Binding ValStatut}"  Width="80"  IsReadOnly="True"/>
        <DataGridTextColumn Header="DateVal"      Binding="{Binding ValDate}"    Width="80"  IsReadOnly="True" SortMemberPath="ValDateSort"/>
        <DataGridTextColumn Header="CommentVAL"   Binding="{Binding ValComment}" Width="160" IsReadOnly="True"/>
        <!-- Groupe comparaison (STR) -->
        <DataGridTextColumn Header="StatutSTR"   Binding="{Binding Statut}"     Width="100"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Numero"      Binding="{Binding Num}"        Width="100" IsReadOnly="True"/>
        <DataGridTextColumn Header="Famille"     Binding="{Binding Famille}"    Width="155" IsReadOnly="True"/>
        <DataGridTextColumn Header="Niveau"      Binding="{Binding Niveau}"     Width="85"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Demandeur"   Binding="{Binding Demandeur}"  Width="85"  IsReadOnly="True"/>
        <DataGridTextColumn Header="DateDem"     Binding="{Binding DateDem}"    Width="80"  IsReadOnly="True" SortMemberPath="DateDemSort"/>
        <DataGridTextColumn Header="RESDem"      Binding="{Binding ResDem}"     Width="80"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Responsable" Binding="{Binding ResResp}"    Width="90"  IsReadOnly="True"/>
        <DataGridTextColumn Header="Detail"      Binding="{Binding Detail}"     Width="*"   IsReadOnly="True"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Footer -->
    <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,5">
      <Grid Margin="8,0">
        <TextBlock x:Name="footer_label"
                   FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal">
          <Button x:Name="btn_view3d"  Content="Vue 3D"
                  Width="80"  Height="28" Margin="0,0,6,0"
                  Background="#8E44AD" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_sync"   Content="Synchroniser"
                  Width="120" Height="28" Margin="0,0,6,0"
                  Background="#2ECC71" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_export" Content="Exporter CSV"
                  Width="110" Height="28" Margin="0,0,6,0"
                  Background="#E67E22" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_close"  Content="Fermer"
                  Width="80" Height="28"
                  Background="#3498DB" Foreground="White"
                  BorderThickness="0" FontSize="12"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>
"""

# Liste des en-tetes colonnes (ordre identique aux colonnes XAML)
# Index 0 = checkbox, puis : VAL group, puis STR group
COLUMN_HEADERS = [
    HDR_SEL,
    HDR_VAL_STATUT, HDR_VAL_DATE, HDR_VAL_COMMENT,
    HDR_STATUT, HDR_NUM, HDR_FAMILLE, HDR_NIVEAU,
    HDR_DEMANDEUR, HDR_DATE_DEM, HDR_RES_DEM, HDR_RES_RESP,
    HDR_DETAIL
]


def _count_val_statuts(rows):
    """Compte les VALIDE, REFUSE et INVALIDE parmi les rows."""
    nb_valide  = sum(1 for r in rows if r.ValStatut == VAL_VALIDE)
    nb_refuse  = sum(1 for r in rows if r.ValStatut == VAL_REFUSE)
    nb_invalid = sum(1 for r in rows if r.Statut == STATUT_INVALID)
    return nb_valide, nb_refuse, nb_invalid


def _update_sel_count(window, rows):
    """Met a jour le compteur de lignes cochees dans la barre de stats."""
    nb_sel = sum(1 for r in rows if r.IsSelected)
    window.FindName("lbl_sel_count").Text = LBL_SEL_COUNT.format(nb_sel)
    # Activer/desactiver Synchroniser selon la selection
    btn_sync = window.FindName("btn_sync")
    btn_sync.IsEnabled = nb_sel > 0
    if nb_sel > 0:
        btn_sync.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(46, 204, 113)
        )
    else:
        btn_sync.Background = System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(170, 170, 170)
        )


def _reload_grid(window, rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid,
                 nb_host_total, nb_link_total, link_name):
    """Recharge les donnees du DataGrid et met a jour les compteurs."""
    dg   = window.FindName("dg_main")
    coll = ObservableCollection[object]()
    for r in rows:
        coll.Add(r)
    dg.ItemsSource = coll

    nb_valide, nb_refuse, _ = _count_val_statuts(rows)

    window.FindName("lbl_titre").Text    = LBL_TITRE.format(nb_host_total, link_name, nb_link_total)
    window.FindName("lbl_valide").Text   = u"✔ VALIDE : {}".format(nb_valide)
    window.FindName("lbl_refuse").Text   = u"✖ REFUSE : {}".format(nb_refuse)
    window.FindName("lbl_absent").Text   = LBL_ABSENT_STAT.format(nb_absent)
    window.FindName("lbl_diff").Text     = LBL_DIFF_STAT.format(nb_diff)
    window.FindName("lbl_invalid").Text  = LBL_INVALID_STAT.format(nb_invalid)
    window.FindName("lbl_ok").Text       = LBL_OK_STAT.format(nb_ok)
    window.FindName("lbl_str_seul").Text = LBL_STR_STAT.format(nb_str_seul)
    window.FindName("lbl_total").Text    = LBL_TOTAL_STAT.format(nb_link_total, nb_host_total)

    _update_sel_count(window, rows)


def build_and_show(rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid,
                   nb_host_total, nb_link_total, link_name, link_instance):

    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
    window = System.Windows.Markup.XamlReader.Load(stream)

    window.Title = TOOL_NAME

    # En-tetes colonnes avec accents (assignes via code)
    dg = window.FindName("dg_main")
    for i, hdr in enumerate(COLUMN_HEADERS):
        if i < dg.Columns.Count:
            dg.Columns[i].Header = hdr

    # Libelles boutons (accents via Python)
    window.FindName("btn_sync").Content       = LBL_BTN_SYNC
    window.FindName("btn_export").Content     = LBL_BTN_CSV
    window.FindName("btn_close").Content      = LBL_BTN_CLOSE
    window.FindName("btn_check_all").Content  = LBL_BTN_CHECK_ALL
    window.FindName("btn_uncheck_all").Content = LBL_BTN_UNCHECK
    window.FindName("btn_view3d").Content     = LBL_BTN_VIEW3D

    # Footer
    window.FindName("footer_label").Text = LBL_FOOTER.format(SCRIPT_VERSION)

    # Chargement initial
    _reload_grid(window, rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid,
                 nb_host_total, nb_link_total, link_name)

    # Etat mutable partage entre callbacks
    state = {
        "rows":          rows,
        "nb_absent":     nb_absent,
        "nb_diff":       nb_diff,
        "nb_ok":         nb_ok,
        "nb_str_seul":   nb_str_seul,
        "nb_invalid":    nb_invalid,
        "nb_host_total": nb_host_total,
        "nb_link_total": nb_link_total,
    }

    # -------------------------------------------------------------------------
    # CHECKBOX : mise a jour du compteur apres chaque changement de cellule
    # Pattern IronPython : CurrentCellChanged est l'event le plus fiable
    # pour capturer les modifications de DataGridCheckBoxColumn
    # -------------------------------------------------------------------------
    def on_cell_changed(s, e):
        _update_sel_count(window, state["rows"])

    dg.CurrentCellChanged += on_cell_changed

    # -------------------------------------------------------------------------
    # BOUTONS TOUT COCHER / TOUT DECOCHER (lignes actionnables uniquement)
    # -------------------------------------------------------------------------
    def on_check_all(s, e):
        for r in state["rows"]:
            if r.IsSelectable:
                r.IsSelected = True
        # Forcer le rafraichissement du DataGrid
        cur_src = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = cur_src
        _update_sel_count(window, state["rows"])

    def on_uncheck_all(s, e):
        for r in state["rows"]:
            r.IsSelected = False
        cur_src = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = cur_src
        _update_sel_count(window, state["rows"])

    window.FindName("btn_check_all").Click   += on_check_all
    window.FindName("btn_uncheck_all").Click += on_uncheck_all

    # -------------------------------------------------------------------------
    # BOUTON SYNCHRONISER — traite uniquement les lignes cochees
    # -------------------------------------------------------------------------
    def on_sync(s, e):
        cur_rows  = state["rows"]
        selected  = [r for r in cur_rows if r.IsSelected and r.IsSelectable]

        if not selected:
            forms.alert(MSG_NOTHING, title="Synchronisation")
            return

        # Preview : utilise la meme fonction de classification que la synchro reelle
        nb_a = nb_b = nb_c = nb_d = 0
        for row in selected:
            cas = _classify_row(row)
            if cas == CAS_A:
                nb_a += 1
            elif cas == CAS_B:
                nb_b += 1
            elif cas == CAS_C:
                nb_c += 1
            elif cas == CAS_D:
                nb_d += 1

        total_preview = nb_a + nb_b + nb_c + nb_d
        if total_preview == 0:
            forms.alert(
                u"Aucun élément à traiter parmi la sélection.",
                title="Synchronisation"
            )
            return

        confirmed = forms.alert(
            MSG_CONFIRM_SYNC.format(total_preview, nb_a, nb_b, nb_c, nb_d),
            title="Confirmer la synchronisation",
            yes=True, no=True
        )
        if not confirmed:
            return

        r_a, r_b_cp, r_b_mk, r_c, r_d, ws_not_found, err = synchronize_reservations(
            selected, link_instance
        )

        if err:
            forms.alert(MSG_SYNC_ERR.format(err), title="Erreur synchronisation")
            return

        # Construire le message de resultat avec avertissement eventuel
        result_msg = MSG_SYNC_RESULT.format(
            r_a, r_b_cp, r_b_mk, r_c, r_d,
            r_a + r_b_cp, r_b_mk + r_c + r_d
        )
        if ws_not_found:
            result_msg += u"\n\n" + MSG_WORKSET_NOT_FOUND.format(TARGET_WORKSET_NAME)

        forms.alert(result_msg, title=u"Synchronisation terminée")

        # Rafraichissement apres synchro
        new_host  = collect_host_reservations()
        new_link  = collect_link_reservations(link_instance)
        new_rows, new_absent, new_diff, new_ok, new_str_seul, new_invalid = compare_reservations(
            new_host, new_link
        )
        state["rows"]          = new_rows
        state["nb_absent"]     = new_absent
        state["nb_diff"]       = new_diff
        state["nb_ok"]         = new_ok
        state["nb_str_seul"]   = new_str_seul
        state["nb_invalid"]    = new_invalid
        state["nb_host_total"] = len(new_host)

        _reload_grid(window, new_rows, new_absent, new_diff, new_ok, new_str_seul, new_invalid,
                     len(new_host), state["nb_link_total"], link_name)

    # -------------------------------------------------------------------------
    # BOUTON EXPORTER CSV
    # -------------------------------------------------------------------------
    def on_export(s, e):
        desktop  = os.path.join(os.path.expanduser("~"), "Desktop")
        csv_path = os.path.join(desktop, "STR_Reservations_Analyse.csv")
        try:
            lines = [LBL_CSV_HEADER]
            for r in state["rows"]:
                lines.append(u"{};{};{};{};{};{};{};{};{};{};{};{}".format(
                    r.ValStatut, r.Statut, r.Num, r.Famille, r.Niveau,
                    r.Demandeur, r.DateDem,
                    r.ResDem, r.ResResp,
                    r.ValDate, r.ValComment,
                    r.Detail.replace(";", " /")
                ))
            with io.open(csv_path, 'w', encoding='utf-8-sig') as f:
                f.write(u"\n".join(lines))
            forms.alert(LBL_CSV_OK.format(csv_path), title="Export CSV")
        except Exception as ex:
            forms.alert(LBL_CSV_ERR.format(str(ex)), title="Erreur")

    # -------------------------------------------------------------------------
    # BOUTON VUE 3D
    # -------------------------------------------------------------------------
    def on_view3d(s, e):
        _view, msg = open_3d_cropbox(state["rows"], link_instance)
        forms.alert(msg, title="Vue 3D")
        if _view is not None:
            window.Close()

    window.FindName("btn_sync").Click   += on_sync
    window.FindName("btn_export").Click += on_export
    window.FindName("btn_view3d").Click += on_view3d
    window.FindName("btn_close").Click  += lambda s, e: window.Close()

    window.ShowDialog()


# =============================================================================
# POINT D'ENTREE
# =============================================================================

def run():
    link_instance = find_link_instance()
    if not link_instance:
        forms.alert(LBL_NO_LINK.format(LINK_MODEL_PREFIX), title="Lien introuvable")
        return

    link_name  = link_instance.Name
    host_elems = collect_host_reservations()
    link_elems = collect_link_reservations(link_instance)

    if not link_elems:
        forms.alert(LBL_NO_RES.format(FAMILY_PREFIX), title="Aucune reservation")
        return

    rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid = compare_reservations(
        host_elems, link_elems
    )

    build_and_show(
        rows=rows,
        nb_absent=nb_absent, nb_diff=nb_diff,
        nb_ok=nb_ok, nb_str_seul=nb_str_seul, nb_invalid=nb_invalid,
        nb_host_total=len(host_elems),
        nb_link_total=len(link_elems),
        link_name=link_name,
        link_instance=link_instance,
    )


run()