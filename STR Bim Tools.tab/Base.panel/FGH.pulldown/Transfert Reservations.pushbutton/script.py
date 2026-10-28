# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "3.4.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Reservations RES vs STR"
# =============================================================================
# Titre du bouton, tooltip et version : voir bundle.yaml (pas de __title__ ici)

# =============================================================================
# FILET DE SECURITE — hors filet, le strict minimum pour afficher une erreur
# fatale. Sans lui, un import qui echoue ou une maquette non ouverte laisse
# l'outil muet : TaskDialog est natif Revit et fonctionne meme si WPF n'a pas
# charge.
# =============================================================================
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


# =============================================================================
# IMPORTS — tous en tete, obligatoire IronPython
# =============================================================================
_INIT_OK = False
try:
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
    import re

    from System.Collections.ObjectModel import ObservableCollection
    from System.Windows.Controls import ComboBoxItem

    from pyrevit import revit, forms
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        FilteredWorksetCollector,
        WorksetKind,
        RevitLinkInstance,
        FamilyInstance,
        Family,
        FamilySymbol,
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

    _INIT_OK = True
except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)

# Le reste du module ne contient que des litteraux et des definitions de
# fonctions : rien qui s'execute avant l'appel a run() en fin de fichier.

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
LBL_BTN_CHECK_ALL = u"Cocher affichés"
LBL_BTN_UNCHECK   = u"Décocher affichés"
LBL_BTN_VIEW3D    = u"Vue 3D"
LBL_SEL_COUNT     = u"{} sélectionnée(s)"
LBL_SEL_HIDDEN    = u"{} sélectionnée(s) — dont {} hors filtre"
HDR_SEL           = u""

# --- Barre de filtres ---
LBL_F_TITLE       = u"Filtres :"
LBL_F_VAL         = u"Statut VAL :"
LBL_F_DATE        = u"Date VAL :"
LBL_F_STAT        = u"Statut synchro :"
LBL_F_TXT         = u"Recherche :"
LBL_F_ACT         = u"Actionnables seulement"
LBL_F_ALL         = u"(Tous — {})"
LBL_F_ALL_DATES   = u"(Toutes — {})"
LBL_F_EMPTY       = u"(vide)"
LBL_F_ENTRY       = u"{} ({})"
LBL_BTN_RESET     = u"Réinitialiser"
LBL_FILTER_COUNT  = u"Affichées : {} / {}"
TIP_SEARCH        = u"Recherche libre : n° de réservation, famille, niveau, demandeur, responsable, commentaire VAL"
TIP_CHECK_ALL     = u"Coche uniquement les lignes actionnables actuellement affichées (filtre appliqué)"
TIP_UNCHECK       = u"Décoche uniquement les lignes actuellement affichées"
TIP_DATE          = u"Dates de validation présentes dans le lien SPV, de la plus récente à la plus ancienne"

MSG_DOUBLONS = (
    u"⚠ Contrôle des identifiants de réservation\n\n"
    u"{}\n"
    u"L'appariement se fait sur l'ADN ({}), pas sur le N° : les N° en doublon ne "
    u"sont donc plus perdus. En revanche, un ADN en doublon ou absent fait bien "
    u"disparaître une réservation de la comparaison.\n\n"
    u"Premiers identifiants concernés :\n{}"
)

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


def _is_valid_text(raw):
    """
    Teste si un texte de statut signifie reellement 'valide'.
    Attention : un simple 'VALID' in texte est piegeux — 'INVALIDE' et
    'NON VALIDE' contiennent tous les deux la sous-chaine 'VALID'.
    """
    if not raw:
        return False
    upper = raw.strip().upper()
    if "INVALID" in upper or "NON VALID" in upper or "PAS VALID" in upper:
        return False
    return "VALID" in upper


def _normalize_val_statut(raw):
    """
    Normalise la valeur de PVA_RES_VAL_Statut pour l'affichage et le tri.
    Retourne 'VALIDE', 'REFUSE', ou '' (vide).
    """
    if not raw:
        return ""
    upper = raw.strip().upper()
    if _is_valid_text(upper):
        return VAL_VALIDE
    if "REFUS" in upper:
        return VAL_REFUSE
    return raw.strip()


def _retire_validation(val_statut):
    """
    Statut VAL (normalise) qui retire une reservation deja copiee dans la STR (Cas D) :
    REFUSE, vide, ou negation explicite (INVALIDE, NON VALIDE). « A REVOIR » et tout
    autre statut en suspens laissent la reservation en place (decision Tony 28.10.2026).
    """
    if not val_statut or val_statut == VAL_REFUSE:
        return True
    upper = val_statut.strip().upper()
    return "INVALID" in upper or "NON VALID" in upper or "PAS VALID" in upper


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
            self.IsSelected = _is_valid_text(val_statut)
        else:
            self.IsSelected = False

        # Texte concatene en minuscules — support de la recherche libre de la barre de filtres
        self.SearchBlob = u" ".join([
            num or u"", famille or u"", niveau or u"",
            demandeur or u"", res_dem or u"", res_resp or u"",
            val_comment or u"", date_dem or u"", val_date or u"",
        ]).lower()

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


# =============================================================================
# CLE D'IDENTITE DES RESERVATIONS
# =============================================================================
# Mesure sur la maquette (audit du 13.08.2026, 5014 reservations SPV) :
#   N° de reservation .......... 169 valeurs en doublon (371 objets) — 95,97 %
#   ADN brut ..................    2 valeurs en doublon   (4 objets) — 99,96 %
#   N° + maquette d'origine ...  155 valeurs en doublon (333 objets) — 96,45 %
# Le N° ne suffit pas : les mandataires copient-collent leurs reservations sans
# renumeroter (on trouve le meme N° sur FGH_RES_V_RECT1 et FGH_RES_V_RECT4 dans
# une meme maquette). L'ADN est donc la cle primaire — c'est aussi celle du
# script ABI officiel.
#
# Reserve assumee : l'unicite de l'ADN vient de son horodatage de soumission,
# donc une resoumission produit un ADN different pour le meme percement. Le repli
# ci-dessous rattrape ce cas via la partie stable de l'ADN (N° + maquette,
# revision retiree), et uniquement quand la correspondance est certaine des deux
# cotes — sinon la ligne est signalee, jamais devinee.
#
# Structure : <N°>_<jj/mm/aaaa>_<hh/mm/ss>_STATUT_<n>_<maquette>_R<rev>
# ex. 04-0252_19/03/2026_14/06/13_STATUT_1_FGH_ELE_MAB_51_MOD_TTD_TTZ_R24

ADN_SEG_STATUT = u"STATUT"
ADN_RE_REVISION = r"_R\d+$"

_MATCH_REPORT = {"resoumissions": 0, "ambigus": [], "sans_adn_str": 0}


def _reset_match_report():
    _MATCH_REPORT["resoumissions"] = 0
    _MATCH_REPORT["ambigus"]       = []
    _MATCH_REPORT["sans_adn_str"]  = 0


def _re_adn_revision():
    if "adn_rev" not in _LAZY:
        _LAZY["adn_rev"] = re.compile(ADN_RE_REVISION)
    return _LAZY["adn_rev"]


def _adn_key(element):
    """Cle primaire : l'ADN complet. Chaine vide si absent."""
    return (_get_param_str(element, ADN_PARAM) or u"").strip()


def _fallback_key(element):
    """
    Partie stable de l'ADN : N° + maquette d'origine sans le suffixe de revision.
    Sert uniquement a reconnaitre un percement resoumis, jamais a apparier seule
    (155 collisions mesurees).
    Retourne None si l'ADN ne suit pas la structure attendue.
    """
    adn = _adn_key(element)
    if not adn:
        return None
    parts = adn.split(u"_")
    try:
        i = parts.index(ADN_SEG_STATUT)
    except ValueError:
        return None
    if i < 2 or len(parts) < i + 3:
        return None
    maquette = _re_adn_revision().sub(u"", u"_".join(parts[i + 2:]))
    return u"{}|{}".format(parts[0], maquette)


def audit_cles(elements):
    """ADN en doublon et elements sans ADN. Retourne (liste_doublons, nb_sans)."""
    counts, sans = {}, 0
    for e in elements:
        k = _adn_key(e)
        if not k:
            sans += 1
            continue
        counts[k] = counts.get(k, 0) + 1
    return sorted([k for k in counts if counts[k] > 1]), sans


def apparier(host_elems, link_elems):
    """
    Apparie les reservations du lien et de la STR.
    1. ADN identique — cas normal.
    2. Repli : meme partie stable (N° + maquette) avec un ADN different, et une
       seule candidate de chaque cote -> percement resoumis, a traiter en Cas B.
    Retourne (link_by_adn, paires {adn: e_host}, hotes_non_apparies).
    """
    _reset_match_report()

    link_by_adn = {}
    for e in link_elems:
        k = _adn_key(e)
        if k:
            link_by_adn[k] = e

    host_by_adn  = {}
    hosts_restants = []
    for e in host_elems:
        k = _adn_key(e)
        if k:
            host_by_adn[k] = e
        else:
            hosts_restants.append(e)
            _MATCH_REPORT["sans_adn_str"] += 1

    paires   = {}
    utilises = set()
    for adn, e_link in link_by_adn.items():
        h = host_by_adn.get(adn)
        if h is not None:
            paires[adn] = h
            utilises.add(_eid_int(h.Id))

    # Repli resoumission, sur les seuls elements non apparies
    fb_link = {}
    for adn, e_link in link_by_adn.items():
        if adn in paires:
            continue
        k = _fallback_key(e_link)
        if k:
            fb_link.setdefault(k, []).append((adn, e_link))

    fb_host = {}
    for adn, h in host_by_adn.items():
        if _eid_int(h.Id) in utilises:
            continue
        k = _fallback_key(h)
        if k:
            fb_host.setdefault(k, []).append(h)

    for k in sorted(fb_link.keys()):
        candidats_h = fb_host.get(k)
        if not candidats_h:
            continue
        candidats_l = fb_link[k]
        if len(candidats_l) == 1 and len(candidats_h) == 1:
            adn = candidats_l[0][0]
            paires[adn] = candidats_h[0]
            utilises.add(_eid_int(candidats_h[0].Id))
            _MATCH_REPORT["resoumissions"] += 1
        else:
            _MATCH_REPORT["ambigus"].append(
                u"{} : {} côté SPV / {} côté STR".format(
                    k, len(candidats_l), len(candidats_h)))

    for adn, h in host_by_adn.items():
        if _eid_int(h.Id) not in utilises:
            hosts_restants.append(h)

    return link_by_adn, paires, hosts_restants


def _match_report_text():
    """Bloc ajoute au message de fin de synchronisation."""
    lignes = []
    r = _MATCH_REPORT
    if r["resoumissions"]:
        lignes.append(u"Resoumissions détectées (ADN refigé, même N° et même "
                      u"maquette) : {}".format(r["resoumissions"]))
    if r["sans_adn_str"]:
        lignes.append(u"Réservations STR sans ADN : {} — jamais appariées, "
                      u"listées en STR seul".format(r["sans_adn_str"]))
    if r["ambigus"]:
        lignes.append(u"")
        lignes.append(u"⚠ Resoumissions ambiguës, non appariées :")
        for a in r["ambigus"][:15]:
            lignes.append(u"   • {}".format(a))
        if len(r["ambigus"]) > 15:
            lignes.append(u"   • ... et {} autre(s)".format(len(r["ambigus"]) - 15))
    return u"\n".join(lignes)


def audit_numeros(elements):
    """
    Controle de coherence des N° de reservation sur un jeu d'elements.
    La comparaison indexe les elements par N° : un doublon ecrase l'entree
    precedente et un element sans N° est purement ignore. Cette fonction
    permet de le signaler a l'utilisateur au lieu de le subir en silence.
    Retourne (liste_des_num_en_doublon, nb_sans_numero).
    """
    counts     = {}
    nb_sans_id = 0
    for e in elements:
        num = _get_param_str(e, PARAM_NUM) or ""
        if not num:
            nb_sans_id += 1
            continue
        counts[num] = counts.get(num, 0) + 1
    return sorted([n for n, c in counts.items() if c > 1]), nb_sans_id


def compare_reservations(host_elems, link_elems):
    """
    Compare les deux ensembles.
    Tri : d'abord par statut VAL (VALIDE > REFUSE > vide),
          puis par statut STR (INVALIDE > ABSENT > DIFFERENT > STR_SEUL > OK).
    Retourne (rows, nb_absent, nb_diff, nb_ok, nb_str_seul, nb_invalid).
    """
    # Appariement sur l'ADN, avec repli resoumission. Le N° reste la reference
    # metier affichee, il ne sert plus d'identifiant.
    link_by_adn, paires, hosts_non_apparies = apparier(host_elems, link_elems)

    rows        = []
    nb_absent   = 0
    nb_diff     = 0
    nb_ok       = 0
    nb_str_seul = 0
    nb_invalid  = 0

    # Elements du lien
    for adn, e_link in link_by_adn.items():
        num         = _get_param_str(e_link, PARAM_NUM) or ""
        val_statut  = _normalize_val_statut(_get_param_str(e_link, PARAM_VAL_STATUT))
        val_date    = _get_param_str(e_link, PARAM_VAL_DATE)    or ""
        val_comment = _get_param_str(e_link, PARAM_VAL_COMMENT) or ""
        res_dem     = _get_param_str(e_link, PARAM_RES_DEM)     or ""
        res_resp    = _get_param_str(e_link, PARAM_RES_RESP)    or ""

        e_host = paires.get(adn)

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
            # Condition : statut REFUSE, vide ou nie (INVALIDE...) ET element present
            # en local ; « A REVOIR » reste en place, compare comme les autres
            if _retire_validation(val_statut):
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

    # Elements STR sans correspondance dans le lien (ADN absent du lien, ou
    # reservation STR depourvue d'ADN : creation manuelle, percement mutualise...)
    for e_host in hosts_non_apparies:
        nb_str_seul += 1
        rows.append(ReservationRow(
                num=_get_param_str(e_host, PARAM_NUM) or "",
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
    """Verifie que PVA_RES_VAL_Statut vaut bien 'valide' (insensible casse,
    negations 'INVALIDE' / 'NON VALIDE' exclues)."""
    return _is_valid_text(_get_param_str(link_element, PARAM_VAL_STATUT) or "")


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


# =============================================================================
# REMAPPAGE DES FAMILLES DUPLIQUEES PAR LES MANDATAIRES
# =============================================================================
# Les mandataires ont duplique les familles de reservation dans leur maquette
# (FGH_RES_H_RECT devenu FGH_RES_H_RECT2, ...). Sans traitement, CopyElements
# ramene le doublon dans la STR. On copie donc normalement, puis on rebascule
# l'occurrence sur la famille de reference locale avant de reecrire les
# parametres : la copie a deja pose la position, la rotation et l'orientation,
# le changement de type n'y touche pas.
FAMILLES_CANONIQUES = [
    "FGH_RES_H_CIRC",
    "FGH_RES_H_RECT",
    "FGH_RES_V_CIRC",
    "FGH_RES_V_RECT",
]

# Suffixe tolere apres le nom canonique pour reconnaitre un doublon.
# Couvre RECT2, RECT_2, RECT 2, RECT-2, RECTv2, RECT_copie1, RECT copy 3.
_PATTERN_SUFFIXE_DOUBLON = r"^[\s_\-]*(?:v|ver|version|copie|copy|dup|dupl)?[\s_\-]*\d+$"

# Parametres built-in transferables : tous les autres built-in sont soit geres
# par Revit (identite, sous-projet, phase), soit porteurs du placement — les
# recopier depuis le lien deplacerait la reservation, le lien ayant sa propre
# transformation. Les dimensions des familles de reservation ne sont PAS des
# built-in : elles passent par la branche parametres de famille / partages.
_NOMS_BIP_TRANSFERABLES = ("ALL_MODEL_INSTANCE_COMMENTS", "ALL_MODEL_MARK")

# Construits a la premiere utilisation : le module ne doit rien executer au
# chargement, sinon un import rate plante hors du filet try/except global.
_LAZY = {}


def _re_suffixe_doublon():
    if "re_suffixe" not in _LAZY:
        _LAZY["re_suffixe"] = re.compile(_PATTERN_SUFFIXE_DOUBLON, re.IGNORECASE)
    return _LAZY["re_suffixe"]


def _bip_transferables():
    if "bip_ok" not in _LAZY:
        vals = set()
        for nom in _NOMS_BIP_TRANSFERABLES:
            try:
                vals.add(int(getattr(BuiltInParameter, nom)))
            except Exception:
                pass
        _LAZY["bip_ok"] = vals
    return _LAZY["bip_ok"]

_REMAP_REPORT = {
    "remappes":         {},   # {nom famille du lien: nb d'occurrences}
    "non_reconnues":    {},   # {nom famille du lien: nb} — regle a elargir
    "echecs":           [],   # descriptions lisibles
    "params_perdus":    {},   # {nom parametre: nb} — absent de la famille cible
    "familles_purgees": [],
}


def _reset_remap_report():
    _REMAP_REPORT["remappes"]         = {}
    _REMAP_REPORT["non_reconnues"]    = {}
    _REMAP_REPORT["echecs"]           = []
    _REMAP_REPORT["params_perdus"]    = {}
    _REMAP_REPORT["familles_purgees"] = []


def _bump(dico, cle):
    dico[cle] = dico.get(cle, 0) + 1


def _eid_int(eid):
    """ElementId -> int, compatible Revit 2024 (IntegerValue) et 2025+ (Value)."""
    if eid is None:
        return -1
    try:
        return eid.IntegerValue
    except Exception:
        pass
    try:
        return eid.Value
    except Exception:
        return -1


def _safe_name(element):
    """Element.Name peut lever sur certains types — jamais de lecture API nue."""
    try:
        return element.Name
    except Exception:
        return ""


def _canonical_for(fam_name):
    """
    Nom de la famille de reference correspondant a fam_name, ou None.
    None signifie soit 'deja la bonne famille', soit 'nom non reconnu' :
    les deux cas sont distingues par l'appelant via _is_canonique().
    """
    if not fam_name:
        return None
    for canon in FAMILLES_CANONIQUES:
        if fam_name == canon:
            return None
        if fam_name.startswith(canon):
            if _re_suffixe_doublon().match(fam_name[len(canon):]):
                return canon
    return None


def _is_canonique(fam_name):
    return fam_name in FAMILLES_CANONIQUES


def _find_family(nom):
    for f in FilteredElementCollector(doc).OfClass(Family):
        if _safe_name(f) == nom:
            return f
    return None


def _find_canonical_symbol(canon_name, type_name):
    """
    Type de la famille de reference locale a appliquer.
    Retourne (symbole, avertissement). Le type de meme nom est prefere ;
    a defaut le premier type par ordre alphabetique, ce qui est sans
    consequence sur la geometrie puisque les dimensions sont portees par
    l'occurrence.
    """
    fam = _find_family(canon_name)
    if fam is None:
        return None, u"famille de référence « {} » absente de la maquette".format(canon_name)
    symbols = []
    try:
        for sid in fam.GetFamilySymbolIds():
            s = doc.GetElement(sid)
            if s is not None:
                symbols.append(s)
    except Exception:
        pass
    if not symbols:
        return None, u"famille de référence « {} » sans type".format(canon_name)
    for s in symbols:
        if _safe_name(s) == type_name:
            return s, u""
    symbols.sort(key=_safe_name)
    return symbols[0], u"type « {} » absent de « {} », type « {} » appliqué".format(
        type_name, canon_name, _safe_name(symbols[0]))


def _transfer_all_instance_params(src, dst):
    """
    Transfere TOUS les parametres d'occurrence exploitables, dimensions
    comprises : parametres de famille, partages et de projet, plus les rares
    built-in inoffensifs. Volontairement ecarte :
      - les parametres en lecture seule ;
      - les parametres de type ElementId (niveau, phase, hote, option de
        conception) : les identifiants du lien n'ont aucun sens dans la STR, et
        la copie a deja pose les bonnes references ;
      - les autres built-in, qui portent le placement (elevation, decalage) et
        deplaceraient la reservation, le lien ayant sa propre transformation.
    """
    for p_src in src.Parameters:
        try:
            if p_src.StorageType == StorageType.ElementId:
                continue
            try:
                bip = p_src.Definition.BuiltInParameter
                if bip is not None and int(bip) != int(BuiltInParameter.INVALID):
                    if int(bip) not in _bip_transferables():
                        continue
            except Exception:
                pass

            nom = p_src.Definition.Name
            if not nom:
                continue
            p_dst = dst.LookupParameter(nom)
            if p_dst is None:
                if p_src.HasValue:
                    _bump(_REMAP_REPORT["params_perdus"], nom)
                continue
            if p_dst.IsReadOnly or p_dst.StorageType != p_src.StorageType:
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


def _remap_to_canonical(pairs):
    """
    Rebascule sur la famille de reference locale les copies issues d'une famille
    dupliquee. Retourne (set des occurrences remappees, noms des familles
    dupliquees rencontrees).
    """
    remappes  = set()
    doublons  = set()
    symbol_cache = {}

    for src, dst in pairs:
        fam_name = _get_family_name(dst)
        if _is_canonique(fam_name):
            continue

        canon = _canonical_for(fam_name)
        if canon is None:
            if fam_name:
                _bump(_REMAP_REPORT["non_reconnues"], fam_name)
            continue

        num = _get_param_str(src, PARAM_NUM) or u"(sans n°)"
        try:
            type_name = _safe_name(dst.Symbol)
        except Exception:
            type_name = ""

        cle = (canon, type_name)
        if cle not in symbol_cache:
            symbol_cache[cle] = _find_canonical_symbol(canon, type_name)
        sym, avert = symbol_cache[cle]

        if sym is None:
            _REMAP_REPORT["echecs"].append(
                u"N° {} ({}) : {}".format(num, fam_name, avert))
            continue
        if avert:
            _REMAP_REPORT["echecs"].append(u"N° {} : {}".format(num, avert))

        try:
            if not sym.IsActive:
                sym.Activate()
                doc.Regenerate()
            dst.Symbol = sym
            remappes.add(_eid_int(dst.Id))
            doublons.add(fam_name)
            _bump(_REMAP_REPORT["remappes"], fam_name)
        except Exception as ex:
            _REMAP_REPORT["echecs"].append(
                u"N° {} : bascule sur « {} » impossible ({})".format(num, canon, ex))

    if remappes:
        doc.Regenerate()
    return remappes, doublons


def _purge_familles_doublons(noms):
    """Supprime une famille dupliquee devenue orpheline. Jamais en force."""
    for nom in sorted(noms):
        try:
            fam = _find_family(nom)
            if fam is None:
                continue
            sym_ids = set()
            for sid in fam.GetFamilySymbolIds():
                sym_ids.add(_eid_int(sid))
            utilisee = False
            for fi in (FilteredElementCollector(doc)
                       .OfClass(FamilyInstance)
                       .WhereElementIsNotElementType()):
                if _eid_int(fi.GetTypeId()) in sym_ids:
                    utilisee = True
                    break
            if utilisee:
                continue
            doc.Delete(fam.Id)
            _REMAP_REPORT["familles_purgees"].append(nom)
        except Exception:
            pass


def _remap_report_text():
    """Bloc de compte rendu ajoute au message de fin de synchronisation."""
    lignes = []
    r = _REMAP_REPORT

    if r["remappes"]:
        total = sum(r["remappes"].values())
        lignes.append(u"Familles dupliquées remappées : {} réservation(s)".format(total))
        for nom in sorted(r["remappes"].keys()):
            lignes.append(u"   • {} → {}  ({})".format(
                nom, _canonical_for(nom), r["remappes"][nom]))
    if r["familles_purgees"]:
        lignes.append(u"Familles dupliquées purgées : {}".format(
            u", ".join(sorted(r["familles_purgees"]))))
    if r["non_reconnues"]:
        lignes.append(u"")
        lignes.append(u"⚠ Familles non reconnues, copiées telles quelles :")
        for nom in sorted(r["non_reconnues"].keys()):
            lignes.append(u"   • {}  ({})".format(nom, r["non_reconnues"][nom]))
    if r["params_perdus"]:
        lignes.append(u"")
        lignes.append(u"⚠ Paramètres du lien absents de la famille de référence :")
        for nom in sorted(r["params_perdus"].keys()):
            lignes.append(u"   • {}  ({})".format(nom, r["params_perdus"][nom]))
    if r["echecs"]:
        lignes.append(u"")
        lignes.append(u"⚠ Anomalies de remappage :")
        for e in r["echecs"][:15]:
            lignes.append(u"   • {}".format(e))
        if len(r["echecs"]) > 15:
            lignes.append(u"   • ... et {} autre(s)".format(len(r["echecs"]) - 15))

    return u"\n".join(lignes)


def _pair_sources_and_copies(sources, copied):
    """
    Apparie chaque element source a sa copie.
    ElementTransformUtils.CopyElements ne garantit PAS que l'ordre des ids
    retournes suit l'ordre des ids fournis : un appariement positionnel peut
    donc ecrire les parametres d'une reservation sur une autre.
    Strategie en trois temps : appariement par ADN s'il a survecu a la copie,
    sinon par N° de reservation, sinon repli positionnel (cas ou aucun parametre
    n'est preserve).
    """
    if len(sources) != len(copied):
        return []

    def _essai(keyfunc):
        src_by_key = {}
        for s in sources:
            k = keyfunc(s)
            if k:
                src_by_key[k] = s
        if len(src_by_key) != len(sources):
            return None
        pairs, matched = [], set()
        for dst in copied:
            k = keyfunc(dst)
            src = src_by_key.get(k)
            if src is None or k in matched:
                return None
            matched.add(k)
            pairs.append((src, dst))
        return pairs if len(pairs) == len(sources) else None

    for keyfunc in (_adn_key, lambda e: _get_param_str(e, PARAM_NUM) or ""):
        pairs = _essai(keyfunc)
        if pairs:
            return pairs

    # Repli : ordre de retour suppose identique a l'ordre d'envoi
    return list(zip(sources, copied))


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

    pairs = _pair_sources_and_copies(elements, copied)

    # Bascule sur les familles de reference AVANT la reecriture des parametres :
    # un changement de type remet les parametres d'occurrence aux valeurs par
    # defaut de la nouvelle famille, il faut donc ecrire apres.
    remappes, doublons = _remap_to_canonical(pairs)

    for src, dst in pairs:
        if _eid_int(dst.Id) in remappes:
            # Occurrence remappee : transfert integral, dimensions comprises.
            _transfer_all_instance_params(src, dst)
            continue
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

    # La famille dupliquee n'a plus d'occurrence des lors que toutes ses copies
    # ont bascule : on la retire de la maquette.
    if doublons:
        _purge_familles_doublons(doublons)

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

    _reset_remap_report()

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
    Title="" Width="1500" Height="700"
    MinWidth="1100" MinHeight="480"
    ResizeMode="CanResize" Background="White"
    WindowStartupLocation="CenterScreen">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
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
            Padding="10,5" Margin="0,0,0,4">
      <WrapPanel Orientation="Horizontal">
        <Border Background="#DFF0D8" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_valide" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FDDEDE" CornerRadius="4" Padding="8,3" Margin="0,3,16,3">
          <TextBlock x:Name="lbl_refuse" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FDDEDE" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_absent" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FFF3CD" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_diff" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#FFD9A0" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_invalid" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#DFF0D8" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_ok" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <Border Background="#E8E8E8" CornerRadius="4" Padding="8,3" Margin="0,3,16,3">
          <TextBlock x:Name="lbl_str_seul" FontSize="12" FontWeight="SemiBold"/>
        </Border>
        <TextBlock x:Name="lbl_total" FontSize="12" Margin="0,3,12,3"
                   VerticalAlignment="Center" Foreground="#444444"/>
        <!-- Separateur (Height explicite : un WrapPanel n'etire pas ses enfants) -->
        <Separator Width="1" Height="18" Background="#C0D0E0" Margin="0,3,12,3"/>
        <!-- Compteur lignes affichees -->
        <Border Background="#E8F0FA" CornerRadius="4" Padding="8,3" Margin="0,3,8,3">
          <TextBlock x:Name="lbl_filter_count" FontSize="12" FontWeight="SemiBold"
                     Foreground="#2F6496"/>
        </Border>
        <!-- Compteur selection -->
        <Border Background="#E8F0FA" CornerRadius="4" Padding="8,3" Margin="0,3,0,3">
          <TextBlock x:Name="lbl_sel_count" FontSize="12" FontWeight="SemiBold"
                     Foreground="#2980B9"/>
        </Border>
      </WrapPanel>
    </Border>

    <!-- Barre de filtres — WrapPanel : passe sur deux lignes si la fenetre est retrecie -->
    <Border Grid.Row="2" Background="#F0F6FF"
            BorderBrush="#C0D0E0" BorderThickness="0,0,0,1"
            Padding="10,5" Margin="0,0,0,4">
      <WrapPanel Orientation="Horizontal">
        <TextBlock x:Name="lbl_f_title" FontSize="11" FontWeight="SemiBold"
                   Foreground="#2F6496" VerticalAlignment="Center" Margin="0,3,10,3"/>
        <TextBlock x:Name="lbl_f_val" FontSize="11"
                   VerticalAlignment="Center" Margin="0,3,4,3"/>
        <ComboBox x:Name="cb_val_statut" Width="130" Height="24" FontSize="11"
                  VerticalContentAlignment="Center" Margin="0,3,12,3"/>
        <TextBlock x:Name="lbl_f_date" FontSize="11"
                   VerticalAlignment="Center" Margin="0,3,4,3"/>
        <ComboBox x:Name="cb_val_date" Width="150" Height="24" FontSize="11"
                  VerticalContentAlignment="Center" Margin="0,3,12,3"/>
        <TextBlock x:Name="lbl_f_stat" FontSize="11"
                   VerticalAlignment="Center" Margin="0,3,4,3"/>
        <ComboBox x:Name="cb_statut" Width="135" Height="24" FontSize="11"
                  VerticalContentAlignment="Center" Margin="0,3,12,3"/>
        <TextBlock x:Name="lbl_f_txt" FontSize="11"
                   VerticalAlignment="Center" Margin="0,3,4,3"/>
        <TextBox x:Name="tb_search" Width="140" Height="24" FontSize="11"
                 VerticalContentAlignment="Center" Margin="0,3,12,3"/>
        <CheckBox x:Name="chk_actionnable" FontSize="11"
                  VerticalAlignment="Center" Margin="0,3,10,3"/>
        <Button x:Name="btn_reset" Width="95" Height="24" Margin="0,3,12,3"
                Background="#BDC3C7" Foreground="#333333"
                BorderThickness="0" FontSize="11"/>
        <Button x:Name="btn_check_all" Width="120" Height="24" Margin="0,3,4,3"
                Background="#2ECC71" Foreground="White"
                BorderThickness="0" FontSize="11" FontWeight="SemiBold"/>
        <Button x:Name="btn_uncheck_all" Width="130" Height="24" Margin="0,3,0,3"
                Background="#E74C3C" Foreground="White"
                BorderThickness="0" FontSize="11" FontWeight="SemiBold"/>
      </WrapPanel>
    </Border>

    <!-- DataGrid -->
    <DataGrid x:Name="dg_main" Grid.Row="3"
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
    <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
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


def _update_sel_count(window, state):
    """
    Met a jour le compteur de lignes cochees dans la barre de stats.
    Le comptage porte sur TOUTES les lignes, pas seulement celles affichees :
    une ligne cochee puis masquee par un filtre reste synchronisee, il faut
    donc le signaler explicitement.
    """
    rows    = state["rows"]
    view    = state.get("view")
    if view is None:
        view = rows
    nb_sel      = sum(1 for r in rows if r.IsSelected)
    nb_sel_view = sum(1 for r in view if r.IsSelected)
    nb_hidden   = nb_sel - nb_sel_view

    if nb_hidden > 0:
        window.FindName("lbl_sel_count").Text = LBL_SEL_HIDDEN.format(nb_sel, nb_hidden)
    else:
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


# =============================================================================
# SECTION : BARRE DE FILTRES
# Tag de ComboBoxItem = valeur filtree ; Tag None = pas de filtre.
# state["busy"] evite que le repeuplement des combos declenche un filtrage.
# =============================================================================

def _combo_tag(combo):
    """Valeur filtree portee par l'element selectionne, ou None si '(Tous)'."""
    try:
        item = combo.SelectedItem
        return None if item is None else item.Tag
    except Exception:
        return None


def _fill_combo(combo, entries, keep_tag):
    """
    Remplit un ComboBox a partir de [(tag, libelle), ...].
    Restaure la selection portant keep_tag si elle existe encore, sinon index 0.
    """
    combo.Items.Clear()
    idx = 0
    for i, pair in enumerate(entries):
        tag, label = pair
        item          = ComboBoxItem()
        item.Content  = label
        item.Tag      = tag
        item.FontSize = 11
        combo.Items.Add(item)
        if keep_tag is not None and tag is not None and tag == keep_tag:
            idx = i
    combo.SelectedIndex = idx


def _counts_by(rows, getter):
    """Effectifs par valeur (chaine normalisee, '' pour vide)."""
    counts = {}
    for r in rows:
        key = (getter(r) or u"").strip()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _label_for(value, nb):
    return LBL_F_ENTRY.format(value if value else LBL_F_EMPTY, nb)


def _populate_statut_combos(window, state):
    """Remplit les combos Statut VAL et Statut synchro a partir du jeu complet."""
    rows = state["rows"]

    cb_val = window.FindName("cb_val_statut")
    counts = _counts_by(rows, lambda r: r.ValStatut)
    keys   = sorted(counts.keys(),
                    key=lambda k: (_val_statut_sort_key(k), k == u"", k))
    entries = [(None, LBL_F_ALL.format(len(rows)))]
    for k in keys:
        entries.append((k, _label_for(k, counts[k])))
    _fill_combo(cb_val, entries, _combo_tag(cb_val))

    cb_stat = window.FindName("cb_statut")
    counts  = _counts_by(rows, lambda r: r.Statut)
    order   = {STATUT_INVALID: 0, STATUT_ABSENT: 1, STATUT_DIFF: 2,
               STATUT_STR_SEUL: 3, STATUT_OK: 4}
    keys    = sorted(counts.keys(), key=lambda k: (order.get(k, 9), k))
    entries = [(None, LBL_F_ALL.format(len(rows)))]
    for k in keys:
        entries.append((k, _label_for(k, counts[k])))
    _fill_combo(cb_stat, entries, _combo_tag(cb_stat))


def _populate_date_combo(window, state):
    """
    Remplit la combo Date VAL, de la date la plus recente a la plus ancienne.
    Les effectifs tiennent compte du filtre Statut VAL courant : en choisissant
    VALIDE puis une date, on voit directement combien de reservations validees
    ce jour-la sont concernees.
    """
    cb_val  = window.FindName("cb_val_statut")
    f_val   = _combo_tag(cb_val)
    scope   = [r for r in state["rows"]
               if f_val is None or (r.ValStatut or u"") == f_val]

    counts  = _counts_by(scope, lambda r: r.ValDate)
    dates   = sorted([k for k in counts.keys() if k],
                     key=_date_to_sort_key, reverse=True)

    entries = [(None, LBL_F_ALL_DATES.format(len(scope)))]
    for d in dates:
        entries.append((d, _label_for(d, counts[d])))
    if counts.get(u"", 0) > 0:
        entries.append((u"", _label_for(u"", counts[u""])))

    cb_date = window.FindName("cb_val_date")
    _fill_combo(cb_date, entries, _combo_tag(cb_date))


def _apply_filter(window, state):
    """Recalcule la vue filtree et la pousse dans le DataGrid."""
    if state.get("busy"):
        return

    rows     = state["rows"]
    f_val    = _combo_tag(window.FindName("cb_val_statut"))
    f_date   = _combo_tag(window.FindName("cb_val_date"))
    f_stat   = _combo_tag(window.FindName("cb_statut"))
    txt      = (window.FindName("tb_search").Text or u"").strip().lower()
    only_act = (window.FindName("chk_actionnable").IsChecked == True)

    view = []
    for r in rows:
        if f_val is not None and (r.ValStatut or u"") != f_val:
            continue
        if f_date is not None and (r.ValDate or u"").strip() != f_date:
            continue
        if f_stat is not None and r.Statut != f_stat:
            continue
        if only_act and not r.IsSelectable:
            continue
        if txt and txt not in r.SearchBlob:
            continue
        view.append(r)

    state["view"] = view

    dg   = window.FindName("dg_main")
    coll = ObservableCollection[object]()
    for r in view:
        coll.Add(r)
    dg.ItemsSource = None
    dg.ItemsSource = coll

    window.FindName("lbl_filter_count").Text = LBL_FILTER_COUNT.format(len(view), len(rows))
    _update_sel_count(window, state)


def _reload_grid(window, state, link_name):
    """Recharge les compteurs, les filtres et le DataGrid depuis state['rows']."""
    rows = state["rows"]

    state["busy"] = True
    try:
        _populate_statut_combos(window, state)
        _populate_date_combo(window, state)
    finally:
        state["busy"] = False

    nb_valide, nb_refuse, _ = _count_val_statuts(rows)

    window.FindName("lbl_titre").Text    = LBL_TITRE.format(
        state["nb_host_total"], link_name, state["nb_link_total"])
    window.FindName("lbl_valide").Text   = u"✔ VALIDE : {}".format(nb_valide)
    window.FindName("lbl_refuse").Text   = u"✖ REFUSE : {}".format(nb_refuse)
    window.FindName("lbl_absent").Text   = LBL_ABSENT_STAT.format(state["nb_absent"])
    window.FindName("lbl_diff").Text     = LBL_DIFF_STAT.format(state["nb_diff"])
    window.FindName("lbl_invalid").Text  = LBL_INVALID_STAT.format(state["nb_invalid"])
    window.FindName("lbl_ok").Text       = LBL_OK_STAT.format(state["nb_ok"])
    window.FindName("lbl_str_seul").Text = LBL_STR_STAT.format(state["nb_str_seul"])
    window.FindName("lbl_total").Text    = LBL_TOTAL_STAT.format(
        state["nb_link_total"], state["nb_host_total"])

    _apply_filter(window, state)


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

    # Libelles de la barre de filtres (accents via Python)
    window.FindName("lbl_f_title").Text        = LBL_F_TITLE
    window.FindName("lbl_f_val").Text          = LBL_F_VAL
    window.FindName("lbl_f_date").Text         = LBL_F_DATE
    window.FindName("lbl_f_stat").Text         = LBL_F_STAT
    window.FindName("lbl_f_txt").Text          = LBL_F_TXT
    window.FindName("chk_actionnable").Content = LBL_F_ACT
    window.FindName("btn_reset").Content       = LBL_BTN_RESET
    window.FindName("cb_val_date").ToolTip     = TIP_DATE
    window.FindName("tb_search").ToolTip       = TIP_SEARCH
    window.FindName("btn_check_all").ToolTip   = TIP_CHECK_ALL
    window.FindName("btn_uncheck_all").ToolTip = TIP_UNCHECK

    # Footer
    window.FindName("footer_label").Text = LBL_FOOTER.format(SCRIPT_VERSION)

    # Etat mutable partage entre callbacks
    # "rows" = jeu complet, "view" = sous-ensemble affiche apres filtrage
    state = {
        "rows":          rows,
        "view":          None,
        "busy":          False,
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
        _update_sel_count(window, state)

    dg.CurrentCellChanged += on_cell_changed

    # -------------------------------------------------------------------------
    # FILTRES : Statut VAL / Date VAL / Statut synchro / recherche libre
    # -------------------------------------------------------------------------
    def _refresh_view():
        cur_src = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = cur_src
        _update_sel_count(window, state)

    def on_val_statut_changed(s, e):
        # Les dates proposees suivent le statut choisi (effectifs recalcules)
        if state.get("busy"):
            return
        state["busy"] = True
        try:
            _populate_date_combo(window, state)
        finally:
            state["busy"] = False
        _apply_filter(window, state)

    def on_filter_changed(s, e):
        _apply_filter(window, state)

    def on_reset(s, e):
        state["busy"] = True
        try:
            window.FindName("tb_search").Text              = u""
            window.FindName("chk_actionnable").IsChecked   = False
            window.FindName("cb_val_statut").SelectedIndex = 0
            window.FindName("cb_statut").SelectedIndex     = 0
            # Repeupler AVANT de remettre l'index a 0 : _populate_date_combo
            # restaure la date courante si elle existe encore
            _populate_date_combo(window, state)
            window.FindName("cb_val_date").SelectedIndex   = 0
        finally:
            state["busy"] = False
        _apply_filter(window, state)

    window.FindName("cb_val_statut").SelectionChanged += on_val_statut_changed
    window.FindName("cb_val_date").SelectionChanged   += on_filter_changed
    window.FindName("cb_statut").SelectionChanged     += on_filter_changed
    window.FindName("tb_search").TextChanged          += on_filter_changed
    window.FindName("chk_actionnable").Checked        += on_filter_changed
    window.FindName("chk_actionnable").Unchecked      += on_filter_changed
    window.FindName("btn_reset").Click                += on_reset

    # -------------------------------------------------------------------------
    # COCHER / DECOCHER — portent sur les lignes AFFICHEES (filtre applique)
    # -------------------------------------------------------------------------
    def _current_view():
        # Attention : une vue filtree VIDE est une vue valide — pas de "or rows",
        # sinon un filtre sans resultat cocherait tout le jeu de donnees
        view = state.get("view")
        return state["rows"] if view is None else view

    def on_check_all(s, e):
        for r in _current_view():
            if r.IsSelectable:
                r.IsSelected = True
        _refresh_view()

    def on_uncheck_all(s, e):
        for r in _current_view():
            r.IsSelected = False
        _refresh_view()

    window.FindName("btn_check_all").Click   += on_check_all
    window.FindName("btn_uncheck_all").Click += on_uncheck_all

    # Chargement initial (apres cablage des evenements)
    _reload_grid(window, state, link_name)

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

        match_txt = _match_report_text()
        if match_txt:
            result_msg += u"\n\n" + match_txt

        remap_txt = _remap_report_text()
        if remap_txt:
            result_msg += u"\n\n" + remap_txt

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
        state["nb_link_total"] = len(new_link)
        state["view"]          = None

        _reload_grid(window, state, link_name)

    # -------------------------------------------------------------------------
    # BOUTON EXPORTER CSV
    # -------------------------------------------------------------------------
    def on_export(s, e):
        # Exporte ce qui est affiche (filtre applique), pas le jeu complet
        _v          = state.get("view")
        export_rows = state["rows"] if _v is None else _v
        desktop     = os.path.join(os.path.expanduser("~"), "Desktop")
        stamp       = System.DateTime.Now.ToString("yyyyMMdd_HHmm")
        csv_path    = os.path.join(
            desktop, "STR_Reservations_Analyse_{}.csv".format(stamp))
        try:
            lines = [LBL_CSV_HEADER]
            for r in export_rows:
                lines.append(u"{};{};{};{};{};{};{};{};{};{};{};{}".format(
                    r.ValStatut, r.Statut, r.Num, r.Famille, r.Niveau,
                    r.Demandeur, r.DateDem,
                    r.ResDem, r.ResResp,
                    r.ValDate, r.ValComment,
                    r.Detail.replace(";", " /")
                ))
            with io.open(csv_path, 'w', encoding='utf-8-sig') as f:
                f.write(u"\n".join(lines))
            forms.alert(
                LBL_CSV_OK.format(csv_path) +
                u"\n\n{} ligne(s) exportée(s) sur {}.".format(
                    len(export_rows), len(state["rows"])),
                title="Export CSV")
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

    # Controle de coherence des identifiants. Depuis la v3.3.0 l'appariement se
    # fait sur l'ADN : ce sont les ADN en doublon ou absents qui font disparaitre
    # une reservation, les N° en doublon ne sont plus qu'informatifs.
    dup_link, no_adn_link = audit_cles(link_elems)
    dup_host, no_adn_host = audit_cles(host_elems)
    dup_num_link, _       = audit_numeros(link_elems)
    dup_num_host, _       = audit_numeros(host_elems)
    if dup_link or dup_host or no_adn_link or no_adn_host:
        lignes = []
        if dup_link:
            lignes.append(u"  • Lien SPV : {} ADN en doublon".format(len(dup_link)))
        if no_adn_link:
            lignes.append(u"  • Lien SPV : {} élément(s) sans ADN".format(no_adn_link))
        if dup_host:
            lignes.append(u"  • Maquette STR : {} ADN en doublon".format(len(dup_host)))
        if no_adn_host:
            lignes.append(u"  • Maquette STR : {} élément(s) sans ADN".format(no_adn_host))
        if dup_num_link or dup_num_host:
            lignes.append(u"  • Pour information, N° en doublon — SPV : {} / STR : {} "
                          u"(sans conséquence sur l'appariement)".format(
                              len(dup_num_link), len(dup_num_host)))
        apercu = u"\n".join(sorted(set(dup_link + dup_host))[:8]) or u"  (aucun)"
        forms.alert(MSG_DOUBLONS.format(u"\n".join(lignes), ADN_PARAM, apercu),
                    title=u"Contrôle des identifiants de réservation")

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


if _INIT_OK:
    try:
        run()
    except Exception as _ex:
        _show_fatal(u"{} v{} — Erreur d'execution".format(TOOL_NAME, SCRIPT_VERSION), _ex)