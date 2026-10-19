# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_regles.py - Moteur de controle de conformite au BEP FGH.
#
# Chaque exigence du BEP devient une REGLE : un identifiant (celui du
# referentiel doc/FGH_BEP_Regles_STR.md), une categorie d'affichage, une
# severite, l'article du BEP, et une fonction qui retourne la liste des
# CONSTATS (les objets de la maquette qui ne respectent pas la regle).
#
# Une regle sans constat est conforme. Une regle qui ne peut pas s'appliquer
# (maquette non collaborative, referentiel incomplet, aucun element de la
# portee) est declaree NON APPLICABLE : elle ne compte ni en conforme ni en
# non conforme, ce qui evite de gonfler artificiellement le taux.
#
# Aucune regle ne leve : toute lecture de l'API Revit est protegee. Une regle
# qui echoue est rapportee comme telle plutot que de faire tomber l'analyse
# complete (une seule lecture non protegee avait deja fait echouer 26 956
# elements en silence sur un outil precedent).
#
# Ce module DEPEND de l'API Revit, PAS de WPF. IronPython 2.7 compatible.
# =============================================================================

import os
import re
import math

import clr
import System

from Autodesk.Revit.DB import (
    FilteredElementCollector, FilteredWorksetCollector, WorksetKind,
    BuiltInCategory, BuiltInParameter, Element, ElementId,
    Level, Family, Material, BasePoint, DirectShape, FamilyInstance,
    TextNote, Viewport,
    View, ViewSchedule, ViewSheet,
)

try:
    from Autodesk.Revit.DB import UnitTypeId, SpecTypeId
    UNITES_FORGE = True
except ImportError:                                  # Revit < 2021
    UNITES_FORGE = False

import fgh_bep_config
import fgh_bep_prefs

FT_M = 0.3048

# Severites, de la plus grave a la plus legere. L'ordre sert au tri et au
# code couleur du dashboard.
SEVERITES = [u"bloquant", u"majeur", u"mineur"]

STATUT_CONFORME     = u"conforme"
STATUT_NON_CONFORME = u"non conforme"
STATUT_NA           = u"non applicable"


# =============================================================================
# Structures
# =============================================================================
class Constat(object):
    """Un objet de la maquette qui ne respecte pas une regle.

    `correction` porte le nom conforme propose par la regle, ou None quand
    rien ne peut etre repare automatiquement. La fenetre de resultats ne
    montre sa colonne « Correction proposee » que pour les regles qui en
    produisent : c'est la regle qui sait reparer, pas l'interface.
    """

    __slots__ = ("objet", "type_objet", "detail", "attendu", "eid",
                 "correction")

    def __init__(self, objet, type_objet=u"", detail=u"", attendu=u"",
                 eid=None, correction=None):
        self.objet = objet or u"(sans nom)"
        self.type_objet = type_objet or u""
        self.detail = detail or u""
        self.attendu = attendu or u""
        self.eid = eid                                # ElementId ou None
        self.correction = correction                  # nom propose, ou None


# Garde-fou memoire, et rien d'autre. Il ne doit jamais etre atteint : une
# regle qui depasserait ce nombre est presumee en boucle ou en erreur. A ne
# pas confondre avec la limite d'AFFICHAGE de la fenetre, qui n'ampute
# jamais les donnees.
PLAFOND_MEMOIRE = 200000


class Resultat(object):
    """Resultat d'une regle : TOUS ses constats.

    Ils etaient autrefois coupes a la limite d'affichage, ce qui amputait
    aussi l'export : un ecart au-dela du 2000e n'existait plus nulle part,
    et le classeur remis en revue etait donc incomplet sans le dire. La
    fenetre coupe desormais a l'affichage seulement.
    """

    def __init__(self, limite_affichage):
        self.constats = []
        self.total = 0                                # nombre reel, non borne
        self.limite_affichage = limite_affichage
        self.non_applicable = False
        self.motif_na = u""
        self.erreur = None

    def ajouter(self, constat):
        self.total += 1
        if len(self.constats) < PLAFOND_MEMOIRE:
            self.constats.append(constat)

    def na(self, motif):
        self.non_applicable = True
        self.motif_na = motif

    @property
    def tronque(self):
        """Vrai si des constats ont ete REELLEMENT perdus, c'est-a-dire si le
        garde-fou memoire a joue. Ce n'est pas la limite d'affichage."""
        return self.total > len(self.constats)


class Regle(object):
    def __init__(self, rid, categorie, libelle, severite, reference, fonction):
        self.id = rid
        self.categorie = categorie
        self.libelle = libelle
        self.severite = severite
        self.reference = reference
        self.fonction = fonction


class Contexte(object):
    """
    Donnees partagees par les regles : le document, le referentiel, et les
    collectes lourdes faites UNE fois (elements de modele, niveaux, worksets).
    """

    def __init__(self, doc, app, ref):
        self.doc = doc
        self.app = app
        self.ref = ref
        self._elements = None
        self._niveaux = None
        self._worksets = None
        self._noms_params_projet = None
        self._offset_niveaux = None
        self._reservations = None
        self._feuilles = None

    # -- collectes ------------------------------------------------------------
    @property
    def elements(self):
        """Elements de modele des categories du referentiel, dedoublonnes."""
        if self._elements is None:
            vus = {}
            for nom_cat in self.ref.categories_modele:
                bic = _bic(nom_cat)
                if bic is None:
                    continue
                try:
                    col = (FilteredElementCollector(self.doc)
                           .OfCategory(bic).WhereElementIsNotElementType())
                    for el in col:
                        try:
                            vus[_eid_int(el.Id)] = el
                        except Exception:
                            pass
                except Exception:
                    pass
            self._elements = list(vus.values())
        return self._elements

    @property
    def niveaux(self):
        if self._niveaux is None:
            try:
                self._niveaux = list(FilteredElementCollector(self.doc)
                                     .OfClass(Level).ToElements())
            except Exception:
                self._niveaux = []
        return self._niveaux

    @property
    def worksets(self):
        if self._worksets is None:
            try:
                if self.doc.IsWorkshared:
                    self._worksets = list(FilteredWorksetCollector(self.doc)
                                          .OfKind(WorksetKind.UserWorkset))
                else:
                    self._worksets = []
            except Exception:
                self._worksets = []
        return self._worksets

    @property
    def noms_params_projet(self):
        """Noms de tous les parametres de projet lies a des categories."""
        if self._noms_params_projet is None:
            noms = set()
            try:
                it = self.doc.ParameterBindings.ForwardIterator()
                it.Reset()
                while it.MoveNext():
                    try:
                        noms.add(it.Key.Name)
                    except Exception:
                        pass
            except Exception:
                pass
            self._noms_params_projet = noms
        return self._noms_params_projet


# =============================================================================
# Helpers
# =============================================================================
def _bic(nom):
    try:
        return getattr(BuiltInCategory, nom)
    except AttributeError:
        return None


def _eid_int(eid):
    """Valeur entiere d'un ElementId. IntegerValue jusqu'a Revit 2024, Value
    ensuite : les deux sont tentes pour que le module survive a la migration."""
    if eid is None:
        return None
    for attr in ("IntegerValue", "Value"):
        try:
            return int(getattr(eid, attr))
        except Exception:
            pass
    return None


def _nom(el):
    """Nom d'un element. Element.Name leve sur certains types : jamais nu."""
    try:
        return el.Name
    except Exception:
        pass
    try:
        return Element.Name.__get__(el)
    except Exception:
        return u"(sans nom)"


def _nom_categorie(el):
    try:
        c = el.Category
        return c.Name if c is not None else u""
    except Exception:
        return u""


def _nom_type(doc, el):
    """Nom du type d'une instance, ou chaine vide."""
    try:
        tid = el.GetTypeId()
        if tid is None or tid == ElementId.InvalidElementId:
            return u""
        return _nom(doc.GetElement(tid))
    except Exception:
        return u""


def _param(doc, el, noms):
    """
    Parametre de l'instance puis du type, cherche sur une liste de noms
    (le nom du BEP suivi de ses alias). None si introuvable partout.
    """
    for source in (el, _type_de(doc, el)):
        if source is None:
            continue
        for n in noms:
            try:
                p = source.LookupParameter(n)
            except Exception:
                p = None
            if p is not None:
                return p
    return None


def _type_de(doc, el):
    try:
        tid = el.GetTypeId()
        if tid is None or tid == ElementId.InvalidElementId:
            return None
        return doc.GetElement(tid)
    except Exception:
        return None


def _valeur_texte(p):
    """Valeur lisible d'un parametre, ou chaine vide."""
    if p is None:
        return u""
    try:
        if not p.HasValue:
            return u""
    except Exception:
        pass
    for lecteur in ("AsString", "AsValueString"):
        try:
            v = getattr(p, lecteur)()
            if v:
                return v.strip()
        except Exception:
            pass
    return u""


def _bip(el, nom_bip):
    """Parametre built-in par nom, None si le nom n'existe pas dans cette version."""
    try:
        bip = getattr(BuiltInParameter, nom_bip)
    except AttributeError:
        return None
    try:
        return el.get_Parameter(bip)
    except Exception:
        return None


def _niveau_de(doc, el):
    """Niveau porteur d'un element, teste dans l'ordre des cas Revit courants."""
    for nom_bip in ("LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
                    "WALL_BASE_CONSTRAINT", "FAMILY_BASE_LEVEL_PARAM",
                    "STAIRS_BASE_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM"):
        p = _bip(el, nom_bip)
        if p is None:
            continue
        try:
            eid = p.AsElementId()
            if eid is not None and eid != ElementId.InvalidElementId:
                lvl = doc.GetElement(eid)
                if isinstance(lvl, Level):
                    return lvl
        except Exception:
            pass
    try:
        eid = el.LevelId
        if eid is not None and eid != ElementId.InvalidElementId:
            lvl = doc.GetElement(eid)
            if isinstance(lvl, Level):
                return lvl
    except Exception:
        pass
    return None


def _nom_workset(doc, el):
    try:
        p = el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if p is not None:
            v = p.AsValueString()
            if v:
                return v
    except Exception:
        pass
    return u""


def _mediane(valeurs):
    v = sorted(valeurs)
    n = len(v)
    if not n:
        return 0.0
    if n % 2:
        return float(v[n // 2])
    return float(v[n // 2 - 1] + v[n // 2]) / 2.0


def _unite_attendue(nom):
    """UnitTypeId nomme dans le referentiel, ou None si inconnu de l'API."""
    if not UNITES_FORGE or not nom:
        return None
    try:
        return getattr(UnitTypeId, nom)
    except AttributeError:
        return None


# =============================================================================
# REGLES - Projet et fichier
# =============================================================================
def _r_version_revit(ctx, res):
    attendu = ctx.ref.projet.get("version_revit") or u""
    if not attendu:
        return res.na(u"version Revit non définie au référentiel")
    try:
        actuelle = ctx.app.VersionNumber
    except Exception:
        return res.na(u"version Revit illisible")
    if actuelle != attendu:
        res.ajouter(Constat(
            objet=u"Version Revit",
            type_objet=u"Projet",
            detail=u"maquette ouverte dans Revit {0}".format(actuelle),
            attendu=u"Revit {0} (R24)".format(attendu)))


def _r_taille_fichier(ctx, res):
    limite = ctx.ref.projet.get("taille_max_mo") or 0
    if not limite:
        return res.na(u"taille maximale non définie au référentiel")
    chemin = u""
    try:
        chemin = ctx.doc.PathName or u""
    except Exception:
        pass
    if not chemin or not os.path.isfile(chemin):
        return res.na(u"maquette non enregistrée localement (taille non mesurable)")
    try:
        mo = os.path.getsize(chemin) / (1024.0 * 1024.0)
    except Exception:
        return res.na(u"taille du fichier illisible")
    if mo > float(limite):
        res.ajouter(Constat(
            objet=os.path.basename(chemin),
            type_objet=u"Fichier",
            detail=u"{0:.0f} Mo".format(mo),
            attendu=u"{0} Mo maximum".format(limite)))


def _r_unites(ctx, res):
    if not UNITES_FORGE:
        return res.na(u"API des unités indisponible dans cette version de Revit")
    specs = [("longueur", "Length"), ("surface", "Area"),
             ("volume", "Volume"), ("angle", "Angle")]
    try:
        unites = ctx.doc.GetUnits()
    except Exception:
        return res.na(u"unités du document illisibles")
    for cle, nom_spec in specs:
        attendu_nom = ctx.ref.unites.get(cle)
        attendu = _unite_attendue(attendu_nom)
        if attendu is None:
            continue
        try:
            spec = getattr(SpecTypeId, nom_spec)
            actuel = unites.GetFormatOptions(spec).GetUnitTypeId()
        except Exception:
            continue
        try:
            conforme = (actuel.TypeId == attendu.TypeId)
        except Exception:
            conforme = True                            # ne pas inventer un ecart
        if not conforme:
            res.ajouter(Constat(
                objet=cle.capitalize(),
                type_objet=u"Unité du projet",
                detail=_lisible_unite(actuel),
                attendu=attendu_nom))


def _lisible_unite(forge_id):
    try:
        brut = forge_id.TypeId or u""
    except Exception:
        return u"(inconnue)"
    # "autodesk.unit.unit:millimeters-1.0.1" -> "millimeters"
    corps = brut.split(":")[-1]
    return corps.split("-")[0] or brut


# =============================================================================
# REGLES - Georeferencement
# =============================================================================
def _points_base(ctx):
    """(point_topo, point_base_projet) - None si absent."""
    topo, base = None, None
    try:
        for bp in FilteredElementCollector(ctx.doc).OfClass(BasePoint).ToElements():
            try:
                if bp.IsShared:
                    topo = bp
                else:
                    base = bp
            except Exception:
                pass
    except Exception:
        pass
    return topo, base


def _coord_point(bp):
    """(E, N, Z) en metres, ou None."""
    if bp is None:
        return None
    out = []
    for nom_bip in ("BASEPOINT_EASTWEST_PARAM", "BASEPOINT_NORTHSOUTH_PARAM",
                    "BASEPOINT_ELEVATION_PARAM"):
        p = _bip(bp, nom_bip)
        if p is None:
            return None
        try:
            out.append(p.AsDouble() * FT_M)
        except Exception:
            return None
    return tuple(out)


def _controle_point(res, libelle, mesure, attendu, tol):
    if mesure is None:
        res.ajouter(Constat(objet=libelle, type_objet=u"Géoréférencement",
                            detail=u"point introuvable dans la maquette",
                            attendu=u"point présent et calé"))
        return
    axes = [("E/O", 0, "e"), ("N/S", 1, "n"), ("Z", 2, "z")]
    for nom_axe, i, cle in axes:
        cible = attendu.get(cle)
        if cible is None:
            continue
        ecart = mesure[i] - float(cible)
        if abs(ecart) > tol:
            res.ajouter(Constat(
                objet=u"{0} - {1}".format(libelle, nom_axe),
                type_objet=u"Géoréférencement",
                detail=u"{0:.4f} m (écart {1:+.4f} m)".format(mesure[i], ecart),
                attendu=u"{0:.4f} m".format(float(cible))))


def _r_point_topo(ctx, res):
    attendu = ctx.ref.geo.get("point_topo")
    if not attendu:
        return res.na(u"point topographique non défini au référentiel")
    tol = float(ctx.ref.geo.get("tolerance_m") or 0.001)
    topo, _ = _points_base(ctx)
    _controle_point(res, u"Point topographique", _coord_point(topo), attendu, tol)


def _r_point_base(ctx, res):
    attendu = ctx.ref.geo.get("point_base")
    if not attendu:
        return res.na(u"point de base projet non défini au référentiel")
    tol = float(ctx.ref.geo.get("tolerance_m") or 0.001)
    _, base = _points_base(ctx)
    _controle_point(res, u"Point de base projet", _coord_point(base), attendu, tol)

    cible = attendu.get("angle_nord_deg")
    if cible is None or base is None:
        return
    p = _bip(base, "BASEPOINT_ANGLETON_PARAM")
    if p is None:
        return
    try:
        angle = math.degrees(p.AsDouble()) % 360.0
    except Exception:
        return
    tol_a = float(ctx.ref.geo.get("tolerance_angle_deg") or 0.0001)
    cible = float(cible) % 360.0
    # Revit et le BEP peuvent compter l'angle dans des sens opposes : les deux
    # lectures sont acceptees, l'ecart affiche est le plus petit des deux.
    ecarts = [abs(angle - cible), abs((360.0 - angle) % 360.0 - cible)]
    if min(ecarts) > tol_a:
        res.ajouter(Constat(
            objet=u"Angle au Nord géographique",
            type_objet=u"Géoréférencement",
            detail=u"{0:.7f} deg".format(angle),
            attendu=u"{0:.7f} deg".format(cible)))


def _r_cube_reperage(ctx, res):
    attendu = (ctx.ref.geo.get("famille_cube") or u"").strip()
    if not attendu:
        return res.na(u"famille de repérage non définie au référentiel")
    cible = attendu.lower().replace(u".rfa", u"")
    try:
        familles = FilteredElementCollector(ctx.doc).OfClass(Family).ToElements()
    except Exception:
        familles = []
    present = False
    for f in familles:
        if cible in _nom(f).lower():
            present = True
            break
    if not present:
        res.ajouter(Constat(
            objet=attendu,
            type_objet=u"Famille",
            detail=u"famille de repérage absente de la maquette",
            attendu=u"cube d'implantation charge et posé"))
        return
    # Chargee mais jamais posee : le controle de georeferencement de la cellule
    # BIM s'appuie sur l'occurrence, pas sur la famille.
    posee = False
    try:
        for fi in (FilteredElementCollector(ctx.doc).OfClass(FamilyInstance)
                   .WhereElementIsNotElementType()):
            try:
                if cible in fi.Symbol.Family.Name.lower():
                    posee = True
                    break
            except Exception:
                pass
    except Exception:
        posee = True                                   # ne pas accuser a tort
    if not posee:
        res.ajouter(Constat(
            objet=attendu,
            type_objet=u"Famille",
            detail=u"famille chargée mais aucune occurrence posée",
            attendu=u"une occurrence implantée dans la maquette"))


# =============================================================================
# REGLES - Niveaux
# =============================================================================
def _appariement_niveaux(ctx):
    """
    Apparie les niveaux de la maquette avec ceux du BEP et calcule l'ecart
    altimetrique global (mediane des ecarts). Les altitudes du BEP sont en
    MN95 ; celles de Revit dependent de la base d'elevation du projet. Un
    decalage CONSTANT est donc un probleme de calage, pas 26 niveaux faux :
    il est rapporte une seule fois.
    """
    if ctx._offset_niveaux is not None:
        return ctx._offset_niveaux
    paires = []                                        # (niveau_revit, def_bep)
    hors_liste = []
    for lvl in ctx.niveaux:
        d = ctx.ref.niveau_par_nom(_nom(lvl))
        if d is None:
            hors_liste.append(lvl)
        else:
            paires.append((lvl, d))
    ecarts = []
    for lvl, d in paires:
        try:
            ecarts.append(float(d.get("alt")) - lvl.Elevation * FT_M)
        except Exception:
            pass
    offset = _mediane(ecarts) if ecarts else 0.0
    ctx._offset_niveaux = (paires, hors_liste, offset)
    return ctx._offset_niveaux


def _r_niveaux_manquants(ctx, res):
    if not ctx.ref.niveaux:
        return res.na(u"aucun niveau au référentiel")
    presents = set()
    for lvl in ctx.niveaux:
        d = ctx.ref.niveau_par_nom(_nom(lvl))
        if d:
            presents.add(d.get("code"))
    for d in ctx.ref.niveaux:
        # Les niveaux « toleres » (0.00, TOITURE) sont dans la maquette de
        # reference mais absents du tableau du BEP : leur altitude est
        # controlee s'ils existent, leur absence n'est pas reprochee.
        if d.get("tolere"):
            continue
        if d.get("code") not in presents:
            res.ajouter(Constat(
                objet=d.get("code"),
                type_objet=u"Niveau",
                detail=u"niveau du BEP absent de la maquette",
                attendu=u"{0} à {1:.3f} m".format(d.get("code"),
                                                  float(d.get("alt") or 0.0))))


def _r_niveaux_hors_liste(ctx, res):
    if not ctx.ref.niveaux:
        return res.na(u"aucun niveau au référentiel")
    _, hors_liste, _ = _appariement_niveaux(ctx)
    for lvl in hors_liste:
        try:
            alt = lvl.Elevation * FT_M
        except Exception:
            alt = 0.0
        res.ajouter(Constat(
            objet=_nom(lvl),
            type_objet=u"Niveau",
            detail=u"niveau hors liste BEP (elevation {0:.3f} m)".format(alt),
            attendu=u"niveau de la maquette IMP, ou validation ecrite de la cellule BIM",
            eid=lvl.Id))


def _r_niveaux_altitudes(ctx, res):
    if not ctx.ref.niveaux:
        return res.na(u"aucun niveau au référentiel")
    paires, _, offset = _appariement_niveaux(ctx)
    if not paires:
        return res.na(u"aucun niveau du BEP retrouve dans la maquette")
    tol = float(ctx.ref.get("tolerance_niveau_m", 0.005))
    for lvl, d in paires:
        try:
            alt_revit = lvl.Elevation * FT_M + offset
        except Exception:
            continue
        cible = float(d.get("alt") or 0.0)
        ecart = alt_revit - cible
        if abs(ecart) > tol:
            res.ajouter(Constat(
                objet=_nom(lvl),
                type_objet=u"Niveau",
                detail=u"{0:.3f} m (écart {1:+.3f} m)".format(alt_revit, ecart),
                attendu=u"{0:.3f} m".format(cible),
                eid=lvl.Id))


def _r_calage_altimetrique(ctx, res):
    if not ctx.ref.niveaux:
        return res.na(u"aucun niveau au référentiel")
    paires, _, offset = _appariement_niveaux(ctx)
    if not paires:
        return res.na(u"aucun niveau du BEP retrouve dans la maquette")
    tol = float(ctx.ref.get("tolerance_niveau_m", 0.005))
    if abs(offset) > tol:
        res.ajouter(Constat(
            objet=u"Base d'elevation du projet",
            type_objet=u"Géoréférencement",
            detail=u"tous les niveaux sont décalés de {0:+.3f} m".format(-offset),
            attendu=u"altitudes MN95 du BEP (niveau {0} à {1:.3f} m)".format(
                ctx.ref.get("niveau_reference"),
                float((ctx.ref.niveau_par_nom(ctx.ref.get("niveau_reference")) or
                       {}).get("alt") or 0.0))))


def _r_elements_niveau_hors_liste(ctx, res):
    if not ctx.ref.niveaux:
        return res.na(u"aucun niveau au référentiel")
    codes = set()
    for d in ctx.ref.niveaux:
        codes.add(d.get("code"))
        codes.add(d.get("nom"))
    for el in ctx.elements:
        lvl = _niveau_de(ctx.doc, el)
        if lvl is None:
            continue
        nom_lvl = _nom(lvl)
        if nom_lvl not in codes:
            res.ajouter(Constat(
                objet=u"{0} - {1}".format(_nom_categorie(el), _nom_type(ctx.doc, el)),
                type_objet=_nom_categorie(el),
                detail=u"rattaché au niveau « {0} »".format(nom_lvl),
                attendu=u"niveau fini de la liste BEP",
                eid=el.Id))


# =============================================================================
# REGLES - Sous-projets
# =============================================================================
def _r_sous_projets_nommage(ctx, res):
    if not ctx.doc.IsWorkshared:
        return res.na(u"maquette non collaborative (aucun sous-projet)")
    prefixes = ctx.ref.sous_projets.get("prefixes_autorises") or []
    if not prefixes:
        return res.na(u"préfixes de sous-projets non définis au référentiel")
    for ws in ctx.worksets:
        try:
            nom = ws.Name
        except Exception:
            continue
        if not any(nom.startswith(p) for p in prefixes):
            res.ajouter(Constat(
                objet=nom,
                type_objet=u"Sous-projet",
                detail=u"préfixe non conforme",
                attendu=u" | ".join(prefixes)))


def _r_sous_projets_attendus(ctx, res):
    if not ctx.doc.IsWorkshared:
        return res.na(u"maquette non collaborative (aucun sous-projet)")
    if not ctx.ref.sous_projets.get("controler_attendus"):
        return res.na(u"contrôle désactivé au référentiel")
    attendus = ctx.ref.sous_projets.get("attendus") or []
    presents = set()
    for ws in ctx.worksets:
        try:
            presents.add(ws.Name)
        except Exception:
            pass
    for a in attendus:
        if a not in presents:
            res.ajouter(Constat(objet=a, type_objet=u"Sous-projet",
                                detail=u"sous-projet obligatoire absent",
                                attendu=u"sous-projet créé"))


def _r_elements_sous_projet(ctx, res):
    if not ctx.doc.IsWorkshared:
        return res.na(u"maquette non collaborative (aucun sous-projet)")
    prefixes = ctx.ref.sous_projets.get("prefixes_autorises") or []
    if not prefixes:
        return res.na(u"préfixes de sous-projets non définis au référentiel")
    for el in ctx.elements:
        nom_ws = _nom_workset(ctx.doc, el)
        if not nom_ws:
            continue
        if not any(nom_ws.startswith(p) for p in prefixes):
            res.ajouter(Constat(
                objet=u"{0} - {1}".format(_nom_categorie(el), _nom_type(ctx.doc, el)),
                type_objet=_nom_categorie(el),
                detail=u"sous-projet « {0} »".format(nom_ws),
                attendu=u"sous-projet 03_STR_...",
                eid=el.Id))


# =============================================================================
# REGLES - Nommage
# =============================================================================
def _portee_active(ctx, cle):
    return bool((ctx.ref.nommage.get("portees") or {}).get(cle))


def _types_modele(ctx):
    """Types (FamilySymbol et types systeme) des categories de modele du
    referentiel.

    Volontairement borne a `categories_modele` plutot qu'a tous les
    ElementType du document : sans ce filtre, le controle de nommage
    remonterait aussi les styles de texte, de cotation, les cartouches et les
    types de vue, que l'article 3.1.1 ne vise pas. Ajouter une categorie au
    referentiel suffit a elargir la portee.
    """
    out = []
    vus = set()
    for nom_cat in ctx.ref.categories_modele:
        bic = _bic(nom_cat)
        if bic is None:
            continue
        try:
            col = (FilteredElementCollector(ctx.doc).OfCategory(bic)
                   .WhereElementIsElementType())
        except Exception:
            continue
        for t in col:
            try:
                cle = t.Id.IntegerValue
            except Exception:
                try:
                    cle = t.Id.Value
                except Exception:
                    continue
            if cle in vus:
                continue
            vus.add(cle)
            out.append(t)
    return out


def _vues_projet(ctx):
    """Vues du projet, hors gabarits, feuilles et nomenclatures : ces deux
    dernieres ont leur propre portee et seraient comptees deux fois."""
    out = []
    try:
        col = FilteredElementCollector(ctx.doc).OfClass(View)
    except Exception:
        return out
    for v in col:
        try:
            if v.IsTemplate:
                continue
        except Exception:
            continue
        if isinstance(v, (ViewSheet, ViewSchedule)):
            continue
        nom = _nom(v)
        if not nom or nom.startswith(u"<"):            # vues systeme
            continue
        out.append((nom, u"Vue", v.Id, "vues"))
    return out


def _objets_nommage(ctx):
    """[(nom, type_objet, eid, cle_portee)] des objets soumis au controle.

    La cle de portee accompagne chaque objet jusqu'au constat : c'est elle
    qui designe le jeu de caracteres a lui appliquer, reglable par nature
    d'objet dans la fenetre Configuration."""
    out = []
    if _portee_active(ctx, "familles"):
        try:
            for f in FilteredElementCollector(ctx.doc).OfClass(Family).ToElements():
                out.append((_nom(f), u"Famille", f.Id, "familles"))
        except Exception:
            pass
    if _portee_active(ctx, "types"):
        # _nom() enveloppe deja la lecture : ElementType.Name leve une
        # AttributeError sur certains types, et un seul appel nu suffirait a
        # priver toute la portee de son controle.
        for t in _types_modele(ctx):
            out.append((_nom(t), u"Type", t.Id, "types"))
    if _portee_active(ctx, "materiaux"):
        try:
            for m in FilteredElementCollector(ctx.doc).OfClass(Material).ToElements():
                out.append((_nom(m), u"Matériau", m.Id, "materiaux"))
        except Exception:
            pass
    if _portee_active(ctx, "sous_projets"):
        for ws in ctx.worksets:
            try:
                out.append((ws.Name, u"Sous-projet", None, "sous_projets"))
            except Exception:
                pass
    if _portee_active(ctx, "parametres"):
        for n in sorted(ctx.noms_params_projet):
            out.append((n, u"Paramètre de projet", None, "parametres"))
    if _portee_active(ctx, "feuilles"):
        try:
            for v in FilteredElementCollector(ctx.doc).OfClass(ViewSheet).ToElements():
                out.append((_nom(v), u"Feuille", v.Id, "feuilles"))
        except Exception:
            pass
    if _portee_active(ctx, "vues"):
        out.extend(_vues_projet(ctx))
    if _portee_active(ctx, "nomenclatures"):
        try:
            for s in FilteredElementCollector(ctx.doc).OfClass(ViewSchedule).ToElements():
                nom = _nom(s)
                if nom.startswith(u"<"):               # nomenclatures systeme
                    continue
                out.append((nom, u"Nomenclature", s.Id, "nomenclatures"))
        except Exception:
            pass
    return out


# --- Proposition de nom conforme ---------------------------------------------
# Types d'objets de nommage dont le nom peut reellement etre reecrit par
# l'outil. Volontairement restrictif :
#   - « Parametre de projet » en est absent : le nom d'un parametre partage
#     vient du fichier de parametres partages, pas de la maquette, et le BEP
#     tolere pour eux le prefixe « #STR_ » que le jeu de caracteres refuse -
#     proposer une correction reviendrait a casser le parametre ;
#   - les autres passent par Element.Name, ou par WorksetTable pour les
#     sous-projets (voir fgh_bep_correction.py).
TYPES_RENOMMABLES = (u"Famille", u"Type", u"Matériau", u"Sous-projet",
                     u"Feuille", u"Vue", u"Nomenclature")

# Depliage des lettres accentuees. Table explicite plutot que unicodedata :
# la presence du module n'est pas garantie sur le moteur IronPython embarque,
# et un import qui echoue priverait toutes les lignes de leur suggestion.
_ACCENTS = {
    u"à": u"a", u"á": u"a", u"â": u"a", u"ã": u"a", u"ä": u"a", u"å": u"a",
    u"ç": u"c",
    u"è": u"e", u"é": u"e", u"ê": u"e", u"ë": u"e",
    u"ì": u"i", u"í": u"i", u"î": u"i", u"ï": u"i",
    u"ñ": u"n",
    u"ò": u"o", u"ó": u"o", u"ô": u"o", u"õ": u"o", u"ö": u"o", u"ø": u"o",
    u"ù": u"u", u"ú": u"u", u"û": u"u", u"ü": u"u",
    u"ý": u"y", u"ÿ": u"y",
    u"æ": u"ae", u"œ": u"oe", u"ß": u"ss",
    u"À": u"A", u"Á": u"A", u"Â": u"A", u"Ã": u"A", u"Ä": u"A", u"Å": u"A",
    u"Ç": u"C",
    u"È": u"E", u"É": u"E", u"Ê": u"E", u"Ë": u"E",
    u"Ì": u"I", u"Í": u"I", u"Î": u"I", u"Ï": u"I",
    u"Ñ": u"N",
    u"Ò": u"O", u"Ó": u"O", u"Ô": u"O", u"Õ": u"O", u"Ö": u"O", u"Ø": u"O",
    u"Ù": u"U", u"Ú": u"U", u"Û": u"U", u"Ü": u"U",
    u"Ý": u"Y",
    u"°": u"deg", u"²": u"2", u"³": u"3", u"µ": u"u", u"'": u"_", u"’": u"_",
}


def _sans_accents(txt):
    return u"".join([_ACCENTS.get(c, c) for c in (txt or u"")])


def _nom_conforme(ref, nom, motif):
    """
    Nom conforme propose pour `nom`, ou None si rien de sur ne peut l'etre.

    La proposition corrige les DEUX regles de nommage a la fois (jeu de
    caracteres ET prefixe de specialite) : corriger l'une pour voir l'autre
    echouer au controle suivant ferait faire deux passes pour rien.

    Elle n'est rendue que si elle satisfait elle-meme le referentiel : mieux
    vaut pas de suggestion qu'une suggestion a corriger a la main.
    """
    if not motif or not nom:
        return None
    try:
        rex = re.compile(motif)
    except Exception:
        return None

    # Caractere de remplacement : le blanc souligne s'il est admis, sinon
    # rien du tout (jeu de caracteres exotique : on se contente de retirer).
    remplacement = u"_" if rex.match(u"_") else u""

    out = []
    for c in _sans_accents(nom):
        out.append(c if rex.match(c) else remplacement)
    propose = u"".join(out)

    if remplacement:
        # « Mur beton - 30 cm » donnerait « Mur_beton___30_cm » : les series
        # de separateurs nees d'un meme blanc typographique sont ramenees a un.
        while remplacement * 2 in propose:
            propose = propose.replace(remplacement * 2, remplacement)
        propose = propose.strip(remplacement)
    if not propose:
        return None

    prefixe = ref.nommage.get("prefixe_specialite")
    if prefixe:
        toleres = ref.nommage.get("prefixes_toleres") or [prefixe]
        # Le prefixe doit lui-meme passer le jeu de caracteres. « STR_ »
        # contient un blanc souligne : si le jeu de la nature d'objet ne
        # l'admet pas, prefixer rendrait la suggestion invalide et la ferait
        # rejeter en bloc plus bas. On rend alors le nom seulement nettoye :
        # D03 reste corrigeable, D01 restera non conforme, ce qui est la
        # verite plutot qu'une absence de suggestion inexplicable.
        if not any(propose.startswith(p) for p in toleres) and                 rex.match(u"{0}{1}".format(prefixe, propose)):
            propose = u"{0}{1}".format(prefixe, propose)

    if not rex.match(propose) or propose == nom:
        return None
    return propose


def _correction_nommage(ctx, nom, type_objet, cle_portee):
    """Suggestion pour une ligne de nommage, None si l'objet n'est pas
    renommable par l'outil."""
    if type_objet not in TYPES_RENOMMABLES:
        return None
    return _nom_conforme(ctx.ref, nom, ctx.ref.motif_nommage(cle_portee))


def _r_caracteres_interdits(ctx, res):
    objets = _objets_nommage(ctx)
    if not objets:
        return res.na(u"aucune portee de nommage activée au référentiel")
    # Le jeu de caracteres se regle PAR NATURE D'OBJET (fenetre Configuration) :
    # un nom de type peut admettre le point sans que les familles le fassent.
    # Les motifs sont compiles une fois, pas une fois par objet.
    rex_par_portee = {}
    for _nom_obj, _type_objet, _eid, cle_portee in objets:
        if cle_portee in rex_par_portee:
            continue
        motif = ctx.ref.motif_nommage(cle_portee)
        try:
            rex_par_portee[cle_portee] = (re.compile(motif), motif)
        except Exception:
            rex_par_portee[cle_portee] = (None, motif)
    if all(r is None for r, _m in rex_par_portee.values()):
        return res.na(u"jeu de caractères invalide ou absent au référentiel")

    for nom, type_objet, eid, cle_portee in objets:
        if not nom:
            continue
        rex, motif = rex_par_portee.get(cle_portee, (None, None))
        if rex is None or rex.match(nom):
            continue
        fautifs = sorted(set(c for c in nom if not re.match(motif, c)))
        res.ajouter(Constat(
            objet=nom, type_objet=type_objet,
            detail=u"caractères interdits : {0}".format(
                u" ".join(fautifs) if fautifs else u"(espace)"),
            attendu=u"lettres, chiffres et {0}".format(
                u" ".join(ctx.ref.caracteres_extra(cle_portee)) or u"rien d'autre"),
            eid=eid,
            correction=_correction_nommage(ctx, nom, type_objet, cle_portee)))


def _r_prefixe_specialite(ctx, res):
    prefixe = ctx.ref.nommage.get("prefixe_specialite")
    if not prefixe:
        return res.na(u"préfixe de spécialité non défini au référentiel")
    toleres = ctx.ref.nommage.get("prefixes_toleres") or [prefixe]
    objets = _objets_nommage(ctx)
    if not objets:
        return res.na(u"aucune portee de nommage activée au référentiel")
    for nom, type_objet, eid, cle_portee in objets:
        if not nom:
            continue
        if any(nom.startswith(p) for p in toleres):
            continue
        res.ajouter(Constat(
            objet=nom, type_objet=type_objet,
            detail=u"ne commence pas par le trigramme de spécialité",
            attendu=u"{0}...".format(prefixe),
            eid=eid,
            correction=_correction_nommage(ctx, nom, type_objet, cle_portee)))


# =============================================================================
# REGLES - Attributs PVA
# =============================================================================
def _noms_attribut(a):
    return [a.get("nom")] + list(a.get("alias") or [])


def _elements_portee(ctx, portee):
    if portee == u"porteurs":
        bics = set()
        for nom_cat in ctx.ref.categories_porteuses:
            bic = _bic(nom_cat)
            if bic is not None:
                bics.add(bic)
        out = []
        for el in ctx.elements:
            try:
                if el.Category is not None and \
                        _bic_de_categorie(el.Category) in bics:
                    out.append(el)
            except Exception:
                pass
        return out
    return ctx.elements


def _bic_de_categorie(cat):
    """BuiltInCategory d'une Category. Revit 2023+ l'expose directement ;
    avant, il faut convertir l'entier de l'ElementId en valeur d'enum (la
    construction directe BuiltInCategory(int) n'existe pas sous IronPython)."""
    if cat is None:
        return None
    try:
        return cat.BuiltInCategory
    except Exception:
        pass
    try:
        return System.Enum.ToObject(clr.GetClrType(BuiltInCategory),
                                    _eid_int(cat.Id))
    except Exception:
        return None


def _fabrique_regle_attribut(a):
    """Construit la fonction de controle d'UN attribut du referentiel."""
    noms = _noms_attribut(a)
    valeurs = a.get("valeurs")
    portee = a.get("portee") or u"modele"

    def _controle(ctx, res):
        # 1. L'attribut existe-t-il seulement dans le projet ? Si non, un seul
        #    constat vaut mieux que 26 000 lignes disant la meme chose.
        if not any(n in ctx.noms_params_projet for n in noms):
            res.ajouter(Constat(
                objet=noms[0], type_objet=u"Paramètre de projet",
                detail=u"paramètre absent du projet (aucun élément ne le porte)",
                attendu=u"paramètre partage SPVA charge et lié aux catégories"))
            return
        elements = _elements_portee(ctx, portee)
        if not elements:
            return res.na(u"aucun élément dans la portee « {0} »".format(portee))
        autorisees = None
        if valeurs:
            autorisees = set(v.strip().lower() for v in valeurs)
        for el in elements:
            p = _param(ctx.doc, el, noms)
            libelle = u"{0} - {1}".format(_nom_categorie(el), _nom_type(ctx.doc, el))
            if p is None:
                res.ajouter(Constat(objet=libelle, type_objet=_nom_categorie(el),
                                    detail=u"paramètre absent sur l'élément",
                                    attendu=noms[0], eid=el.Id))
                continue
            v = _valeur_texte(p)
            if not v:
                res.ajouter(Constat(objet=libelle, type_objet=_nom_categorie(el),
                                    detail=u"valeur vide",
                                    attendu=_attendu_valeurs(valeurs, noms[0]),
                                    eid=el.Id))
                continue
            if autorisees is not None and v.lower() not in autorisees:
                res.ajouter(Constat(objet=libelle, type_objet=_nom_categorie(el),
                                    detail=u"valeur « {0} »".format(v),
                                    attendu=_attendu_valeurs(valeurs, noms[0]),
                                    eid=el.Id))
    return _controle


def _attendu_valeurs(valeurs, nom):
    if not valeurs:
        return u"{0} renseigné".format(nom)
    if len(valeurs) > 6:
        return u"{0} ... ({1} valeurs admises)".format(
            u", ".join(valeurs[:6]), len(valeurs))
    return u", ".join(valeurs)


# =============================================================================
# REGLES - Modelisation STR
# =============================================================================
def _r_loadbearing(ctx, res):
    nom_param = ctx.ref.param_loadbearing
    elements = _elements_portee(ctx, u"porteurs")
    if not elements:
        return res.na(u"aucun élément porteur dans la maquette")
    for el in elements:
        etat = _capacite_structurelle(ctx, el, nom_param)
        if etat is True:
            continue
        libelle = u"{0} - {1}".format(_nom_categorie(el), _nom_type(ctx.doc, el))
        if etat is False:
            detail = u"déclaré non porteur"
        else:
            detail = u"capacité structurelle non renseignée"
        res.ajouter(Constat(objet=libelle, type_objet=_nom_categorie(el),
                            detail=detail,
                            attendu=u"{0} = vrai".format(nom_param),
                            eid=el.Id))


def _capacite_structurelle(ctx, el, nom_param):
    """True porteur / False declare non porteur / None non renseigne."""
    p = _param(ctx.doc, el, [nom_param])
    if p is not None:
        try:
            if p.HasValue:
                return bool(p.AsInteger())
        except Exception:
            pass
    for nom_bip in ("WALL_STRUCTURAL_SIGNIFICANT", "FLOOR_PARAM_IS_STRUCTURAL",
                    "INSTANCE_STRUCT_USAGE_PARAM"):
        pb = _bip(el, nom_bip)
        if pb is None:
            continue
        try:
            if pb.HasValue:
                if nom_bip == "INSTANCE_STRUCT_USAGE_PARAM":
                    return True                        # usage structurel defini
                return bool(pb.AsInteger())
        except Exception:
            pass
    # Poteaux, ossatures et fondations structurels sont porteurs par categorie.
    try:
        bic = _bic_de_categorie(el.Category)
        if bic in (BuiltInCategory.OST_StructuralColumns,
                   BuiltInCategory.OST_StructuralFraming,
                   BuiltInCategory.OST_StructuralFoundation):
            return True
    except Exception:
        pass
    return None


def _r_categories_interdites(ctx, res):
    regles = ctx.ref.categories_interdites
    if not regles:
        return res.na(u"aucune catégorie interdite au référentiel")
    for nom_cat, spec in regles.items():
        bic = _bic(nom_cat)
        if bic is None:
            continue
        message = spec.get("message") or u"catégorie interdite"
        # Prefixes de familles admis : referentiel BEP, ou saisie de l'onglet
        # Configuration. Comparaison en minuscules : une exception tapee a la
        # main ne doit pas rester sans effet pour une histoire de casse.
        exclusions = [x.strip().lower()
                      for x in (spec.get("exclusions_famille") or []) if x]
        try:
            col = (FilteredElementCollector(ctx.doc).OfCategory(bic)
                   .WhereElementIsNotElementType())
        except Exception:
            continue
        for el in col:
            nom_fam = _nom_famille(el)
            cible = (nom_fam or u"").lower()
            if any(cible.startswith(x) for x in exclusions):
                continue
            res.ajouter(Constat(
                objet=u"{0} - {1}".format(nom_fam or _nom_categorie(el),
                                          _nom_type(ctx.doc, el)),
                type_objet=_nom_categorie(el),
                detail=message,
                attendu=u"élément classé dans une catégorie IFC",
                eid=el.Id))


def _nom_famille(el):
    try:
        return el.Symbol.Family.Name
    except Exception:
        pass
    p = _bip(el, "ALL_MODEL_FAMILY_NAME")
    if p is not None:
        v = _valeur_texte(p)
        if v:
            return v
    return u""


def _r_directshape(ctx, res):
    try:
        formes = list(FilteredElementCollector(ctx.doc).OfClass(DirectShape)
                      .WhereElementIsNotElementType())
    except Exception:
        return res.na(u"DirectShape indisponible dans cette version de Revit")
    if not formes:
        return
    for ds in formes:
        res.ajouter(Constat(
            objet=_nom(ds), type_objet=u"DirectShape",
            detail=u"géométrie importée non classée (exportée en IfcBuildingElementProxy)",
            attendu=u"famille Revit classée, ou accord ecrit de la cellule BIM",
            eid=ds.Id))


def _r_elements_sans_niveau(ctx, res):
    if not ctx.elements:
        return res.na(u"aucun élément de modèle dans la maquette")
    for el in ctx.elements:
        if _niveau_de(ctx.doc, el) is None:
            res.ajouter(Constat(
                objet=u"{0} - {1}".format(_nom_categorie(el), _nom_type(ctx.doc, el)),
                type_objet=_nom_categorie(el),
                detail=u"aucun niveau de rattachement",
                attendu=u"élément attaché à un étage fini",
                eid=el.Id))


# =============================================================================
# REGLES - Reservations et percements
# =============================================================================
def _reservations(ctx):
    """
    Population identique a celle des outils Sync / Doublons Reservations :
    occurrences dont la famille commence par le prefixe du referentiel, hors
    elements marques supprimes. Auditer une autre population ferait diverger
    les compteurs des deux outils sans explication visible.
    """
    if ctx._reservations is not None:
        return ctx._reservations
    conf = ctx.ref.reservations
    prefixe = conf.get("prefixe_famille") or u""
    supprime = (conf.get("statut_supprime") or u"").strip().lower()
    param_statut = conf.get("param_statut_validation") or u""
    out = []
    if prefixe:
        try:
            for el in (FilteredElementCollector(ctx.doc).OfClass(FamilyInstance)
                       .WhereElementIsNotElementType()):
                try:
                    if not _nom_famille(el).startswith(prefixe):
                        continue
                    if supprime and param_statut:
                        v = _valeur_texte(_param(ctx.doc, el, [param_statut]))
                        if v.strip().lower() == supprime:
                            continue
                    out.append(el)
                except Exception:
                    pass
        except Exception:
            pass
    ctx._reservations = out
    return out


def _libelle_reservation(ctx, el, numero=None):
    if numero is None:
        conf = ctx.ref.reservations
        noms = [conf.get("param_numero")] + list(conf.get("alias_numero") or [])
        numero = _valeur_texte(_param(ctx.doc, el, [n for n in noms if n]))
    return u"{0} - {1}".format(numero or u"(sans numéro)", _nom_famille(el))


def _fabrique_regle_params_reservation(cle_liste, libelle_bloc):
    """Controle de presence des parametres d'un bloc du processus percements."""

    def _controle(ctx, res):
        conf = ctx.ref.reservations
        noms = conf.get(cle_liste) or []
        if not noms:
            return res.na(u"paramètres non définis au référentiel")
        if not _reservations(ctx):
            return res.na(u"aucune réservation dans la maquette")
        for n in noms:
            if n not in ctx.noms_params_projet:
                res.ajouter(Constat(
                    objet=n, type_objet=u"Paramètre de projet",
                    detail=u"paramètre {0} absent du projet".format(libelle_bloc),
                    attendu=u"paramètre partage SPVA charge et lié aux réservations"))
    return _controle


def _r_res_numerotation(ctx, res):
    conf = ctx.ref.reservations
    reservations = _reservations(ctx)
    if not reservations:
        return res.na(u"aucune réservation dans la maquette")
    noms = [conf.get("param_numero")] + list(conf.get("alias_numero") or [])
    noms = [n for n in noms if n]
    motif = conf.get("format_numero")
    try:
        rex = re.compile(motif) if motif else None
    except Exception:
        rex = None
    for el in reservations:
        numero = _valeur_texte(_param(ctx.doc, el, noms))
        if not numero:
            res.ajouter(Constat(
                objet=_libelle_reservation(ctx, el, u""),
                type_objet=u"Reservation",
                detail=u"numéro de percement vide",
                attendu=u"numéro unique au format NN-NNN",
                eid=el.Id))
            continue
        if rex is not None and not rex.match(numero):
            res.ajouter(Constat(
                objet=_libelle_reservation(ctx, el, numero),
                type_objet=u"Reservation",
                detail=u"numéro « {0} » hors format".format(numero),
                attendu=u"numéro du mandataire suivi d'un compteur (ex. 02-001)",
                eid=el.Id))


def _r_res_doublons(ctx, res):
    """
    Doublons de numero DANS la maquette STR. L'outil « Doublons Reservations »
    va plus loin (il compare a la maquette SPV liee et juge les positions) :
    cette regle sert de voyant dans le tableau de bord, pas de remplacant.
    """
    conf = ctx.ref.reservations
    reservations = _reservations(ctx)
    if not reservations:
        return res.na(u"aucune réservation dans la maquette")
    noms = [conf.get("param_numero")] + list(conf.get("alias_numero") or [])
    noms = [n for n in noms if n]
    par_numero = {}
    for el in reservations:
        numero = _valeur_texte(_param(ctx.doc, el, noms))
        if not numero:
            continue                                   # traite par la regle G01
        par_numero.setdefault(numero, []).append(el)
    for numero in sorted(par_numero.keys()):
        lot = par_numero[numero]
        if len(lot) < 2:
            continue
        for el in lot:
            res.ajouter(Constat(
                objet=_libelle_reservation(ctx, el, numero),
                type_objet=u"Reservation",
                detail=u"numéro porte par {0} réservations".format(len(lot)),
                attendu=u"un numéro unique par percement",
                eid=el.Id))


def _concerne_str(ctx, el):
    """La reservation attend-elle une validation de l'ingenieur civil ?"""
    nom = ctx.ref.reservations.get("param_perc_str")
    if not nom:
        return True
    p = _param(ctx.doc, el, [nom])
    if p is None:
        return True                                    # parametre absent : on
    try:                                               # ne presume pas du non
        if p.StorageType.ToString() == "Integer":
            return bool(p.AsInteger())
    except Exception:
        pass
    v = _valeur_texte(p).strip().lower()
    if not v:
        return True
    return v in (u"oui", u"yes", u"1", u"vrai", u"true", u"o")


def _r_res_attente_validation(ctx, res):
    conf = ctx.ref.reservations
    reservations = _reservations(ctx)
    if not reservations:
        return res.na(u"aucune réservation dans la maquette")
    param_statut = conf.get("param_statut_validation")
    if not param_statut:
        return res.na(u"paramètre de validation non défini au référentiel")
    traites = set((v or u"").strip().lower()
                  for v in (conf.get("statuts_traites") or []))
    if not traites:
        return res.na(u"statuts de validation non définis au référentiel")
    for el in reservations:
        if not _concerne_str(ctx, el):
            continue
        v = _valeur_texte(_param(ctx.doc, el, [param_statut]))
        if v.strip().lower() in traites:
            continue
        res.ajouter(Constat(
            objet=_libelle_reservation(ctx, el),
            type_objet=u"Reservation",
            detail=(u"statut « {0} »".format(v) if v
                    else u"aucun statut de validation"),
            attendu=u"{0} renseigné (validation de l'ingenieur civil)".format(
                param_statut),
            eid=el.Id))


def _r_res_statut_hors_liste(ctx, res):
    conf = ctx.ref.reservations
    reservations = _reservations(ctx)
    if not reservations:
        return res.na(u"aucune réservation dans la maquette")
    param_statut = conf.get("param_statut_validation")
    admis = conf.get("statuts_admis") or []
    if not param_statut or not admis:
        return res.na(u"statuts admis non définis au référentiel")
    autorises = set(v.strip().lower() for v in admis)
    for el in reservations:
        v = _valeur_texte(_param(ctx.doc, el, [param_statut]))
        if not v:
            continue                                   # traite par la regle G04
        if v.strip().lower() in autorises:
            continue
        res.ajouter(Constat(
            objet=_libelle_reservation(ctx, el),
            type_objet=u"Reservation",
            detail=u"statut « {0} » hors liste".format(v),
            attendu=u", ".join(admis),
            eid=el.Id))


# =============================================================================
# REGLES - Feuilles et livrables
# =============================================================================
def _feuilles(ctx):
    """Feuilles reelles du projet (les emplacements reserves sont exclus)."""
    if ctx._feuilles is not None:
        return ctx._feuilles
    out = []
    try:
        for sh in FilteredElementCollector(ctx.doc).OfClass(ViewSheet):
            try:
                if sh.IsPlaceholder:
                    continue
            except Exception:
                pass
            out.append(sh)
    except Exception:
        pass
    ctx._feuilles = out
    return out


def _numero_feuille(sh):
    p = _bip(sh, "SHEET_NUMBER")
    v = _valeur_texte(p)
    return v or _nom(sh)


def _r_feuilles_codification(ctx, res):
    conf = ctx.ref.livrables
    if not conf.get("controler_feuilles"):
        return res.na(u"contrôle des feuilles désactivé au référentiel")
    champs = conf.get("champs") or []
    if not champs:
        return res.na(u"champs de codification non définis au référentiel")
    feuilles = _feuilles(ctx)
    if not feuilles:
        return res.na(u"aucune feuille dans la maquette")
    for sh in feuilles:
        libelle = u"{0} - {1}".format(_numero_feuille(sh), _nom(sh))
        for champ in champs:
            nom_param = champ.get("param")
            if not nom_param:
                continue
            p = _param(ctx.doc, sh, [nom_param])
            if p is None:
                res.ajouter(Constat(
                    objet=libelle, type_objet=u"Feuille",
                    detail=u"paramètre {0} absent du cartouche".format(nom_param),
                    attendu=champ.get("libelle") or nom_param,
                    eid=sh.Id))
                continue
            v = _valeur_texte(p)
            if not v:
                res.ajouter(Constat(
                    objet=libelle, type_objet=u"Feuille",
                    detail=u"{0} : valeur vide".format(champ.get("libelle")),
                    attendu=_attendu_champ(ctx, champ),
                    eid=sh.Id))
                continue
            if not _champ_valide(ctx, champ, v):
                res.ajouter(Constat(
                    objet=libelle, type_objet=u"Feuille",
                    detail=u"{0} : « {1} »".format(champ.get("libelle"), v),
                    attendu=_attendu_champ(ctx, champ),
                    eid=sh.Id))


def _champ_valide(ctx, champ, valeur):
    valeurs = ctx.ref.resoudre_valeurs(champ.get("valeurs"))
    if valeurs:
        return valeur.strip() in valeurs
    motif = champ.get("format")
    if motif:
        try:
            return bool(re.match(motif, valeur.strip()))
        except Exception:
            return True
    return True


def _attendu_champ(ctx, champ):
    valeurs = ctx.ref.resoudre_valeurs(champ.get("valeurs"))
    if valeurs:
        return _attendu_valeurs(valeurs, champ.get("libelle") or u"")
    motif = champ.get("format")
    if motif == u"^[0-9]{4}$":
        return u"4 chiffres"
    if motif:
        return u"format {0}".format(motif)
    return champ.get("libelle") or u"valeur renseignée"


def _r_feuilles_revision(ctx, res):
    conf = ctx.ref.livrables
    if not conf.get("controler_feuilles"):
        return res.na(u"contrôle des feuilles désactivé au référentiel")
    motif = conf.get("format_revision")
    if not motif:
        return res.na(u"format de révision non défini au référentiel")
    feuilles = _feuilles(ctx)
    if not feuilles:
        return res.na(u"aucune feuille dans la maquette")
    try:
        rex = re.compile(motif)
    except Exception:
        return res.na(u"format de révision invalide au référentiel")
    for sh in feuilles:
        v = _valeur_texte(_bip(sh, "SHEET_CURRENT_REVISION"))
        libelle = u"{0} - {1}".format(_numero_feuille(sh), _nom(sh))
        if not v:
            res.ajouter(Constat(
                objet=libelle, type_objet=u"Feuille",
                detail=u"aucune révision courante",
                attendu=u"indice sur 2 chiffres (00 = 1re publication)",
                eid=sh.Id))
        elif not rex.match(v.strip()):
            res.ajouter(Constat(
                objet=libelle, type_objet=u"Feuille",
                detail=u"révision « {0} »".format(v),
                attendu=u"indice sur 2 chiffres (00 = 1re publication)",
                eid=sh.Id))


def _r_nomenclatures_livrables(ctx, res):
    """
    La liste des livrables doit exister DANS la maquette, sous forme de
    nomenclatures de vues et de feuilles (art. 2.11.4).
    """
    attendues = [(u"OST_Sheets", u"nomenclature de feuilles"),
                 (u"OST_Views", u"nomenclature de vues")]
    try:
        schedules = list(FilteredElementCollector(ctx.doc).OfClass(ViewSchedule))
    except Exception:
        return res.na(u"nomenclatures illisibles")
    presentes = set()
    for vs in schedules:
        try:
            if vs.IsTemplate or vs.Name.startswith(u"<"):
                continue
            cid = vs.Definition.CategoryId
            if cid is None or cid == ElementId.InvalidElementId:
                continue
            presentes.add(_eid_int(cid))
        except Exception:
            pass
    for nom_cat, libelle in attendues:
        bic = _bic(nom_cat)
        if bic is None:
            continue
        try:
            attendu_id = _eid_int(ElementId(bic))
        except Exception:
            continue
        if attendu_id not in presentes:
            res.ajouter(Constat(
                objet=libelle, type_objet=u"Nomenclature",
                detail=u"{0} absente de la maquette".format(libelle),
                attendu=u"liste des livrables tenue dans la MN (art. 2.11.4)"))


def _r_textes_manuels(ctx, res):
    """
    Toute information saisie a la main est interdite sur les plans extraits :
    les annotations doivent lire un attribut (art. 3.4.8.1). Seules les notes
    des vues REELLEMENT placees sur une feuille sont relevees : un texte dans
    une vue de travail ne part pas au client.
    """
    if not ctx.ref.livrables.get("controler_textes_manuels"):
        return res.na(u"contrôle des textes manuels désactivé au référentiel")
    try:
        notes = list(FilteredElementCollector(ctx.doc).OfClass(TextNote)
                     .WhereElementIsNotElementType())
    except Exception:
        return res.na(u"notes de texte illisibles")
    if not notes:
        return
    vues_publiees = {}
    try:
        for vp in FilteredElementCollector(ctx.doc).OfClass(Viewport):
            try:
                sh = ctx.doc.GetElement(vp.SheetId)
                vues_publiees[_eid_int(vp.ViewId)] = (
                    _numero_feuille(sh) if sh is not None else u"?")
            except Exception:
                pass
    except Exception:
        return res.na(u"cartouches illisibles")
    for sh in _feuilles(ctx):
        try:
            vues_publiees[_eid_int(sh.Id)] = _numero_feuille(sh)
        except Exception:
            pass
    if not vues_publiees:
        return res.na(u"aucune vue placée sur une feuille")

    for tn in notes:
        try:
            proprio = _eid_int(tn.OwnerViewId)
        except Exception:
            continue
        if proprio not in vues_publiees:
            continue
        try:
            texte = (tn.Text or u"").strip().replace(u"\r", u" ").replace(u"\n", u" ")
        except Exception:
            texte = u""
        if len(texte) > 60:
            texte = texte[:60] + u"..."
        res.ajouter(Constat(
            objet=u"Feuille {0}".format(vues_publiees[proprio]),
            type_objet=u"Note de texte",
            detail=u"texte saisi à la main : « {0} »".format(texte),
            attendu=u"étiquette lisant un attribut de l'élément",
            eid=tn.Id))


# =============================================================================
# REGISTRE
# =============================================================================
CAT_PROJET   = u"Projet et fichier"
CAT_GEO      = u"Géoréférencement"
CAT_NIVEAUX  = u"Niveaux"
CAT_WORKSETS = u"Sous-projets"
CAT_NOMMAGE  = u"Nommage"
CAT_ATTRIBUTS = u"Attributs PVA"
CAT_MODELISATION = u"Modélisation STR"
CAT_RESERVATIONS = u"Réservations"
CAT_LIVRABLES = u"Feuilles et livrables"


def registre(ref):
    """Liste des regles, referentiel compris (les attributs en produisent une chacun)."""
    regles = [
        Regle(u"A05", CAT_PROJET, u"Version Revit imposée",
              u"majeur", u"4.1.2", _r_version_revit),
        Regle(u"A06", CAT_PROJET, u"Taille de la maquette",
              u"majeur", u"4.2", _r_taille_fichier),
        Regle(u"F10", CAT_PROJET, u"Unités du modèle",
              u"majeur", u"3.4.7", _r_unites),

        Regle(u"B02", CAT_GEO, u"Point topographique",
              u"bloquant", u"3.3.1", _r_point_topo),
        Regle(u"B03", CAT_GEO, u"Point de base projet et angle au Nord",
              u"bloquant", u"3.3.1", _r_point_base),
        Regle(u"B04", CAT_GEO, u"Cube de repérage d'implantation",
              u"majeur", u"3.3.2", _r_cube_reperage),

        Regle(u"B05a", CAT_NIVEAUX, u"Niveaux du BEP présents",
              u"bloquant", u"3.3.3", _r_niveaux_manquants),
        Regle(u"B05b", CAT_NIVEAUX, u"Altitudes des niveaux",
              u"bloquant", u"3.3.3", _r_niveaux_altitudes),
        Regle(u"B05c", CAT_NIVEAUX, u"Calage altimétrique global",
              u"bloquant", u"3.3.3", _r_calage_altimetrique),
        Regle(u"B06", CAT_NIVEAUX, u"Niveaux hors liste BEP",
              u"majeur", u"3.3.3", _r_niveaux_hors_liste),
        Regle(u"B07", CAT_NIVEAUX, u"Éléments rattachés à un niveau hors liste",
              u"majeur", u"3.4.1", _r_elements_niveau_hors_liste),

        Regle(u"C04", CAT_WORKSETS, u"Nommage des sous-projets",
              u"majeur", u"3.1.2", _r_sous_projets_nommage),
        Regle(u"C03", CAT_WORKSETS, u"Sous-projets obligatoires",
              u"mineur", u"3.1.2.3", _r_sous_projets_attendus),
        Regle(u"C05", CAT_WORKSETS, u"Éléments hors sous-projet déclaré",
              u"majeur", u"3.4.2", _r_elements_sous_projet),

        Regle(u"D03", CAT_NOMMAGE, u"Caractères interdits dans les noms",
              u"bloquant", u"2.10", _r_caracteres_interdits),
        Regle(u"D01", CAT_NOMMAGE, u"Préfixe de spécialité",
              u"majeur", u"3.1.1", _r_prefixe_specialite),

        Regle(u"F01", CAT_MODELISATION, u"Capacité structurelle des porteurs",
              u"bloquant", u"3.4.8.3", _r_loadbearing),
        Regle(u"F06a", CAT_MODELISATION, u"Modèles génériques interdits",
              u"majeur", u"3.4.8.1", _r_categories_interdites),
        Regle(u"F06b", CAT_MODELISATION, u"Géométries DirectShape non classées",
              u"majeur", u"3.4.8.1", _r_directshape),
        Regle(u"F08", CAT_MODELISATION, u"Éléments sans niveau de rattachement",
              u"majeur", u"3.4.1", _r_elements_sans_niveau),

        Regle(u"G02", CAT_RESERVATIONS, u"Paramètres de demande de percement",
              u"majeur", u"3.06.1",
              _fabrique_regle_params_reservation("parametres_demande",
                                                 u"de demande")),
        Regle(u"G03", CAT_RESERVATIONS, u"Paramètres de validation des percements",
              u"majeur", u"3.06.03",
              _fabrique_regle_params_reservation("parametres_validation",
                                                 u"de validation")),
        Regle(u"G01a", CAT_RESERVATIONS, u"Format du numéro de percement",
              u"majeur", u"3.06.2", _r_res_numerotation),
        Regle(u"G01b", CAT_RESERVATIONS, u"Unicité du numéro de percement",
              u"bloquant", u"3.06.2", _r_res_doublons),
        Regle(u"G04", CAT_RESERVATIONS, u"Percements en attente de validation STR",
              u"bloquant", u"3.06.03", _r_res_attente_validation),
        Regle(u"G05", CAT_RESERVATIONS, u"Statut de validation hors liste",
              u"mineur", u"3.06.03", _r_res_statut_hors_liste),

        Regle(u"H02", CAT_LIVRABLES, u"Codification des feuilles",
              u"majeur", u"2.11.4", _r_feuilles_codification),
        Regle(u"H06", CAT_LIVRABLES, u"Indice de révision des feuilles",
              u"majeur", u"2.11.4", _r_feuilles_revision),
        Regle(u"H07", CAT_LIVRABLES, u"Liste des livrables dans la maquette",
              u"majeur", u"2.11.4", _r_nomenclatures_livrables),
        Regle(u"H08", CAT_LIVRABLES, u"Annotations saisies à la main",
              u"mineur", u"3.4.8.1", _r_textes_manuels),
    ]

    # Une regle par attribut PVA du referentiel : ajouter un attribut au JSON
    # suffit a creer son controle.
    for i, a in enumerate(ref.attributs, 1):
        regles.append(Regle(
            u"E{0:02d}".format(i), CAT_ATTRIBUTS,
            u"{0} ({1})".format(a.get("libelle") or a.get("nom"), a.get("nom")),
            a.get("severite") or u"majeur",
            a.get("reference") or u"3.2.2",
            _fabrique_regle_attribut(a)))
    return regles


# =============================================================================
# Analyse
# =============================================================================
def analyser(doc, app, progress=None):
    """
    Execute toutes les regles et retourne un dict exploitable par le
    dashboard et par l'export XLSX.
    """
    ref = fgh_bep_config.charger()
    ctx = Contexte(doc, app, ref)
    regles = registre(ref)

    lignes = []
    if ref.erreur:
        lignes.append({
            "id": u"CFG", "categorie": CAT_PROJET,
            "libelle": u"Référentiel BEP", "severite": u"bloquant",
            "reference": u"-", "statut": STATUT_NON_CONFORME, "motif_na": u"",
            "nb": 1, "tronque": False,
            "constats": [Constat(objet=os.path.basename(fgh_bep_config.FICHIER),
                                 type_objet=u"Configuration",
                                 detail=ref.erreur,
                                 attendu=u"fgh_bep_config.json lisible")],
        })

    total = len(regles)
    for i, regle in enumerate(regles, 1):
        if progress:
            try:
                progress(i, total, regle.libelle)
            except Exception:
                pass
        res = Resultat(ref.max_constats)
        try:
            regle.fonction(ctx, res)
        except Exception as ex:
            res.erreur = u"{0} : {1}".format(type(ex).__name__, ex)
            res.constats = [Constat(objet=regle.libelle, type_objet=u"Controle",
                                    detail=u"contrôle interrompu : {0}".format(ex),
                                    attendu=u"contrôle exécuté")]
            res.total = 1

        if res.non_applicable:
            statut = STATUT_NA
        elif res.total:
            statut = STATUT_NON_CONFORME
        else:
            statut = STATUT_CONFORME

        lignes.append({
            "id": regle.id, "categorie": regle.categorie,
            "libelle": regle.libelle, "severite": regle.severite,
            "reference": regle.reference, "statut": statut,
            "motif_na": res.motif_na, "nb": res.total,
            "tronque": res.tronque, "constats": res.constats,
            "erreur": res.erreur,
        })

    code, phrase, couleur = _statut_depot(lignes, ref)
    return {
        "regles": lignes,
        "kpi": _kpi(lignes, ctx),
        "categories": _synthese_categories(lignes),
        "contexte": _contexte(doc, app, ref, ctx),
        "depot": {"code": code, "phrase": phrase, "couleur": couleur},
    }


# Statuts de depot. Le taux de conformite pondere toutes les regles a
# egalite : il ne dit donc pas si la maquette est deposable. Ce statut-la le
# dit, et c'est lui qui doit etre lu en premier.
DEPOT_REFUS      = u"REFUS"
DEPOT_A_CORRIGER = u"À CORRIGER"
DEPOT_RESERVE    = u"SOUS RÉSERVE"
DEPOT_CONFORME   = u"CONFORME"
DEPOT_INCOMPLET  = u"INCOMPLET"


def _statut_depot(lignes, ref):
    """
    (code, phrase, cle de couleur) resumant l'aptitude au depot.

    L'incompletude prime sur tout le reste : un referentiel illisible ou une
    regle interrompue laissent un angle mort, et aucun verdict ne peut etre
    prononce sur ce qui n'a pas ete controle. Vient ensuite la severite la
    plus haute rencontree, du bloquant au mineur.
    """
    interrompues = [l for l in lignes if l.get("erreur")]
    if (ref is not None and ref.erreur) or interrompues:
        motif = (u"le référentiel BEP est illisible" if (ref is not None and ref.erreur)
                 else u"{0} règle(s) interrompue(s)".format(len(interrompues)))
        return (DEPOT_INCOMPLET,
                u"Verdict indisponible : {0}. Le taux ci-contre ne porte "
                u"que sur les règles effectivement exécutées.".format(motif),
                "texte_gris")

    ko = [l for l in lignes if l["statut"] == STATUT_NON_CONFORME]
    par_severite = {}
    for l in ko:
        par_severite[l["severite"]] = par_severite.get(l["severite"], 0) + l["nb"]

    if par_severite.get(u"bloquant"):
        return (DEPOT_REFUS,
                u"{0} écart(s) bloquant(s) : la maquette ne peut pas être "
                u"déposée en l'état.".format(par_severite[u"bloquant"]),
                "erreur")
    if par_severite.get(u"majeur"):
        return (DEPOT_A_CORRIGER,
                u"{0} écart(s) majeur(s) : à corriger avant la prochaine "
                u"échéance.".format(par_severite[u"majeur"]),
                "avertissement")
    if par_severite.get(u"mineur"):
        return (DEPOT_RESERVE,
                u"{0} écart(s) mineur(s) seulement : dépôt possible, "
                u"corrections à planifier.".format(par_severite[u"mineur"]),
                "exporter")
    return (DEPOT_CONFORME,
            u"Aucun écart sur les règles applicables.", "ok")


def _kpi(lignes, ctx):
    applicables = [l for l in lignes if l["statut"] != STATUT_NA]
    conformes = [l for l in applicables if l["statut"] == STATUT_CONFORME]
    non_conformes = [l for l in applicables if l["statut"] == STATUT_NON_CONFORME]
    constats = sum([l["nb"] for l in non_conformes]) if non_conformes else 0
    def _somme(severite):
        return sum([l["nb"] for l in non_conformes
                    if l["severite"] == severite]) if non_conformes else 0

    bloquants = _somme(u"bloquant")
    taux = (100.0 * len(conformes) / len(applicables)) if applicables else 100.0
    try:
        nb_elements = len(ctx.elements)
    except Exception:
        nb_elements = 0
    return {
        "elements": nb_elements,
        "regles": len(lignes),
        "applicables": len(applicables),
        "conformes": len(conformes),
        "non_conformes": len(non_conformes),
        "non_applicables": len(lignes) - len(applicables),
        "constats": constats,
        "bloquants": bloquants,
        "majeurs": _somme(u"majeur"),
        "mineurs": _somme(u"mineur"),
        "interrompues": len([l for l in lignes if l.get("erreur")]),
        "taux": taux,
    }


def _synthese_categories(lignes):
    ordre = []
    par_cat = {}
    for l in lignes:
        c = l["categorie"]
        if c not in par_cat:
            par_cat[c] = {"nom": c, "regles": 0, "conformes": 0,
                          "non_conformes": 0, "na": 0, "constats": 0}
            ordre.append(c)
        d = par_cat[c]
        d["regles"] += 1
        if l["statut"] == STATUT_CONFORME:
            d["conformes"] += 1
        elif l["statut"] == STATUT_NON_CONFORME:
            d["non_conformes"] += 1
            d["constats"] += l["nb"]
        else:
            d["na"] += 1
    out = []
    for c in ordre:
        d = par_cat[c]
        applicables = d["regles"] - d["na"]
        d["taux"] = (100.0 * d["conformes"] / applicables) if applicables else 100.0
        out.append(d)
    return out


def _horodatage():
    """Date et heure du controle, au format lisible par un humain."""
    try:
        import datetime
        return datetime.datetime.now().strftime(u"%d.%m.%Y %H:%M")
    except Exception:
        return u"(inconnu)"


def _utilisateur(app):
    """Qui a lance le controle : compte Revit, et compte Windows s'il differe.

    Les deux valent d'etre notes : le premier identifie la licence, le second
    le poste. L'un sans l'autre laisse une ambiguite dans une equipe."""
    revit = u""
    try:
        revit = app.Username or u""
    except Exception:
        pass
    poste = u""
    try:
        poste = os.environ.get("USERNAME") or os.environ.get("USER") or u""
    except Exception:
        pass
    if revit and poste and revit.lower() != poste.lower():
        return u"{0} (session {1})".format(revit, poste)
    return revit or poste or u"(inconnu)"


def _contexte(doc, app, ref, ctx):
    try:
        chemin = doc.PathName or u""
    except Exception:
        chemin = u""
    taille = u"-"
    if chemin and os.path.isfile(chemin):
        try:
            taille = u"{0:.0f} Mo".format(os.path.getsize(chemin) / 1048576.0)
        except Exception:
            pass
    try:
        version = app.VersionNumber
    except Exception:
        version = u"?"
    return {
        "titre": _titre_doc(doc),
        "chemin": chemin,
        "taille": taille,
        "version_revit": version,
        "collaboratif": bool(getattr(doc, "IsWorkshared", False)),
        "referentiel": os.path.basename(fgh_bep_config.FICHIER),
        "erreur_referentiel": ref.erreur or u"",
        # --- Tracabilite : de quoi rejouer et comparer deux rapports --------
        "horodatage": _horodatage(),
        "utilisateur": _utilisateur(app),
        "bep_revision": ref.bep.get("revision") or u"(non declaree)",
        "bep_date": ref.bep.get("date") or u"",
        "bep_emetteur": ref.bep.get("emetteur") or u"",
        "bep_fichier": ref.bep.get("fichier") or u"",
        "empreinte_referentiel": ref.empreinte,
        "empreinte_reglages": fgh_bep_prefs.empreinte(),
        "derogations": ref.derogations(),
        # Relus par la fenetre de resultats pour valider un nom saisi a la
        # main avant de l'ecrire dans la maquette. Un motif par nature
        # d'objet : le jeu de caracteres se regle separement pour chacune.
        "caracteres_autorises": ref.nommage.get("caracteres_autorises") or u"",
        "motifs_nommage": ref.motifs_par_libelle(),
        # Nombre d'ecarts affiches par regle dans la fenetre. L'export, lui,
        # ecrit la totalite : ce plafond ne doit jamais amputer une donnee.
        "limite_affichage": ref.max_constats,
    }


def _titre_doc(doc):
    try:
        return doc.Title
    except Exception:
        return u"(sans titre)"
