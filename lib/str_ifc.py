# -*- coding: utf-8 -*-
# =============================================================================
# str_ifc.py - Couche export IFC pour STR Bim Tools.
#
# POURQUOI CE MODULE
# ------------------
# Un IFCExportOptions nu n'equivaut PAS a un export lance depuis le menu
# "Exporter > IFC" de Revit. Le panneau de Revit transmet a l'exporteur une
# quarantaine d'options NOMMEES (via IFCExportOptions.AddOption). Si le script
# ne les transmet pas, l'exporteur applique ses propres valeurs de repli :
# elements acier absents, geometrie triangulee grossierement, jeux de
# proprietes manquants, Parts ignorees, placement du site non georeference.
# C'est la cause des "oublis" et de la perte de precision constatee avec les
# versions <= 2.4.1 de l'outil, qui ne transmettait que 4 options.
#
# Ce module transmet TOUTES les options explicitement, et sait en plus
# reprendre un setup IFC enregistre dans le modele (identique au menu Revit)
# quand l'assembly de l'exporteur (Autodesk.IFC.Export.UI.dll) est chargeable.
#
# VERIFICATION DES CLEFS
# ----------------------
# Les clefs ci-dessous ont ete verifiees dans les litteraux UTF-16 de
# Revit.IFC.Export.dll (Revit 2025) : ce sont bien celles que l'exporteur lit.
# Trois options du panneau ne sont PAS des options nommees mais des proprietes
# typees de IFCExportOptions : ExportBaseQuantities, WallAndColumnSplitting et
# SpaceBoundaryLevel. FilterViewId est egalement une propriete typee : c'est
# elle, et non une option nommee, qui restreint l'export au contenu d'une vue.
#
# Compatible Revit 2024 / 2025 / 2026, IronPython 2.7 et 3.4.
# =============================================================================

import json
import os

import clr

clr.AddReference("RevitAPI")

import System
from System.Reflection import BindingFlags
from Autodesk.Revit.DB import (
    ElementId, IFCExportOptions, IFCVersion, Phase,
    FilteredElementCollector,
)

# Stockage extensible : uniquement pour l'inventaire de diagnostic. DataStorage
# vit dans ExtensibleStorage et non dans Autodesk.Revit.DB - et surtout, un
# import de diagnostic ne doit JAMAIS pouvoir empecher l'outil de demarrer.
try:
    from Autodesk.Revit.DB.ExtensibleStorage import DataStorage, Schema
    STOCKAGE_LISIBLE = True
except ImportError:
    DataStorage = None
    Schema = None
    STOCKAGE_LISIBLE = False


# =============================================================================
# Compatibilite ElementId (Int64 depuis Revit 2024)
# =============================================================================
def id_value(element_id):
    """Valeur entiere d'un ElementId, sans dependre de IntegerValue (obsolete)."""
    if element_id is None:
        return -1
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def element_id(valeur):
    """int -> ElementId (ElementId.InvalidElementId si valeur invalide)."""
    try:
        v = int(valeur)
    except (TypeError, ValueError):
        return ElementId.InvalidElementId
    if v <= 0:
        return ElementId.InvalidElementId
    return ElementId(v)


# =============================================================================
# Versions IFC disponibles (introspection : la liste varie selon la version)
# =============================================================================
_VERSIONS_CATALOGUE = [
    ("IFC2x3CV2", u"IFC 2x3 Coordination View 2.0"),
    ("IFC2x3",    u"IFC 2x3"),
    ("IFC2x3FM",  u"IFC 2x3 Basic FM Handover View"),
    ("IFC4",      u"IFC 4 (usage general)"),
    ("IFC4RV",    u"IFC 4 Reference View"),
    ("IFC4DTV",   u"IFC 4 Design Transfer View"),
    ("IFC4x3",    u"IFC 4x3"),
    ("IFC2x2",    u"IFC 2x2"),
]


def versions_disponibles():
    """[(nom_membre, libelle)] des IFCVersion reellement presents dans l'API."""
    return [(nom, lib) for nom, lib in _VERSIONS_CATALOGUE
            if hasattr(IFCVersion, nom)]


def version_ifc(nom_membre, defaut="IFC4"):
    """Nom de membre -> valeur IFCVersion, avec repli."""
    for candidat in (nom_membre, defaut, "IFC2x3CV2", "IFC4"):
        if candidat and hasattr(IFCVersion, candidat):
            return getattr(IFCVersion, candidat)
    # Dernier recours : le premier membre de l'enumeration
    return list(System.Enum.GetValues(clr.GetClrType(IFCVersion)))[0]


# =============================================================================
# Type de fichier
# =============================================================================
# Valeurs lues par l'exporteur sous la clef "IFCFileType" (enum IFCFileFormat).
TYPES_FICHIER = [
    ("Ifc",       u".ifc  (texte, standard)",     ".ifc"),
    ("IfcZIP",    u".ifcZIP  (compresse)",        ".ifcZIP"),
    ("IfcXML",    u".ifcXML  (XML)",              ".ifcXML"),
    ("IfcXMLZIP", u".ifcXMLZIP  (XML compresse)", ".ifcXMLZIP"),
]


def extension_fichier(nom_type):
    for nom, _libelle, ext in TYPES_FICHIER:
        if nom == nom_type:
            return ext
    return ".ifc"


# =============================================================================
# Placement du site (georeferencement)
# =============================================================================
# Noms de l'enumeration SiteTransformBasis, transmis en chaine sous la clef
# "SitePlacement". Valides a l'execution contre l'enumeration si elle est
# accessible, sinon utilises tels quels (l'exporteur les parse par nom).
_PLACEMENTS_CATALOGUE = [
    ("Shared",     u"Coordonnees partagees (recommande LV95)"),
    ("Site",       u"Point topographique du site"),
    ("Project",    u"Point de base du projet"),
    ("Internal",   u"Origine interne Revit"),
    ("ProjectInTN", u"Point de base, nord geographique"),
    ("InternalInTN", u"Origine interne, nord geographique"),
]


def _noms_enum_placement():
    """Noms reels de SiteTransformBasis, ou None si l'enumeration est absente."""
    for chemin in ("Autodesk.Revit.DB.IFC", "Revit.IFC.Common.Enums"):
        try:
            module = __import__(chemin, globals(), locals(), ["SiteTransformBasis"])
            enum_type = getattr(module, "SiteTransformBasis")
            return [str(n) for n in
                    System.Enum.GetNames(clr.GetClrType(enum_type))]
        except Exception:
            continue
    return None


def placements_disponibles():
    """[(nom, libelle)] des placements de site proposables."""
    reels = None
    try:
        reels = _noms_enum_placement()
    except Exception:
        reels = None
    if not reels:
        return list(_PLACEMENTS_CATALOGUE)
    return [(nom, lib) for nom, lib in _PLACEMENTS_CATALOGUE if nom in reels]


# =============================================================================
# Phases du modele
# =============================================================================
def phases_disponibles(doc):
    """[(id_int, nom)] des phases du document, dans l'ordre du projet."""
    resultat = []
    try:
        for ph in FilteredElementCollector(doc).OfClass(Phase).ToElements():
            resultat.append((id_value(ph.Id), ph.Name))
    except Exception:
        return []
    return resultat


# =============================================================================
# Reglages par defaut = configuration en session verifiee (IFC 2x3 CV 2.0)
# =============================================================================
# PROVENANCE : ces valeurs sont le releve, propriete par propriete et par
# reflexion .NET, de la "Configuration en cours de session" du modele Fairmont
# Grand Hotel le 30.07.2026. C'est la SEULE configuration avec laquelle un
# export a effectivement abouti sur ce modele : 5.1 Mo en 29 s, doc.Export a
# renvoye True. Toutes les autres tentatives ont echoue sans produire de
# fichier.
#
# En pratique, c'est le setup predefini "IFC 2x3 Coordination View 2.0" avec
# IncludeSteelElements active.
#
# NE PAS remonter ces valeurs "pour ameliorer la qualite" sans un export de
# controle : c'est exactement ce qui a fait echouer les versions 3.0.0 a 3.1.2.
# L'ecart entre cette configuration et celle qui echouait porte surtout sur la
# version IFC (IFC4 Reference View au lieu de IFC 2x3 CV 2.0), le niveau de
# detail, les nomenclatures en jeux de proprietes et l'elevation du site.
#
# Pour memoire, le setup SPVA_Export_IFC4 du bureau (releve dans "IFC4
# SPVA.docx") differe de celui-ci par : version IFC4RV, lod 1.0,
# geometrie_vue True, altitude_site True, psets_nomenc + nomenc_specifiques
# True. Il reste atteignable a la main via les options de la fenetre.
DEFAUTS = {
    # Onglet General
    "version":            "IFC2x3CV2",   # IFC 2x3 Coordination View 2.0
    "type_fichier":       "Ifc",         # IFCFileType
    "prefixe":            u"",
    "espaces":            0,       # SpaceBoundaries
    "split_murs":         False,   # SplitWallsAndColumns
    "phase_id":           -1,      # ActivePhaseId

    # Onglet Contenu additionnel
    "vue_seule":          True,    # -> FilterViewId (filtre applique par l'outil)
    "pieces_vue":         False,   # ExportRoomsInView
    "acier":              True,    # IncludeSteelElements
    "elements_2d":        False,   # Export2DElements

    # Onglet Export jeux de proprietes
    "psets_revit":        False,   # ExportInternalRevitPropertySets
    "psets_ifc":          True,    # ExportIFCCommonPropertySets
    "quantites":          False,   # ExportBaseQuantities
    "psets_materiaux":    False,   # ExportMaterialPsets
    "psets_nomenc":       False,   # ExportSchedulesAsPsets
    "nomenc_specifiques": False,   # ExportSpecificSchedules
    "psets_user":         False,   # ExportUserDefinedPsets
    "psets_user_fichier": u"",     # ExportUserDefinedPsetsFileName

    # Onglet Niveau de detail
    "lod":                0.5,     # TessellationLevelOfDetail

    # Onglet Avance
    "parts":              False,   # ExportPartsAsBuildingElements
    "solides":            False,   # ExportSolidModelRep
    "geometrie_vue":      False,   # UseActiveViewGeometry
    "guid_ifc":           False,   # StoreIFCGUID
    "bbox":               False,   # ExportBoundingBox
    "triangulation":      False,   # UseOnlyTriangulation
    "nom_type_seul":      False,   # UseTypeNameOnlyForIfcType
    "nom_visible":        False,   # UseVisibleRevitNameAsEntityName
    "nom_famille_type":   False,   # UseFamilyAndTypeNameForReference

    # Onglet Reference geographique
    "placement":          "Shared",  # SitePlacement
    "altitude_site":      False,     # IncludeSiteElevation

    # Non exposes par le panneau, laisses a False comme dans la configuration
    "swept_avances":      False,   # ExportAdvancedSweptSolids
    "armatures_barres":   False,   # ExportBarsInUniformSetsAsSeparateIFCEntities
    "hote_entite_unique": False,   # ExportHostAsSingleEntity

    # Outil (non transmis a l'exporteur)
    "setup_modele":       u"",     # nom du setup IFC du modele, vide = manuel
    "journal":            True,
}


def reglages_par_defaut():
    """Copie modifiable des reglages par defaut."""
    return dict(DEFAUTS)


# =============================================================================
# Construction des options d'export
# =============================================================================
def _b(valeur):
    """Booleen -> chaine attendue par l'exporteur."""
    return "true" if valeur else "false"


def _options_nommees(reglages, view_id_int):
    """
    Table complete des options nommees a transmettre.
    Retourne [(clef, valeur_chaine)].
    """
    r = reglages
    paires = [
        # Perimetre
        ("ActiveViewId",                    str(view_id_int if view_id_int > 0 else -1)),
        ("UseActiveViewGeometry",           _b(r["geometrie_vue"])),

        # Contenu
        ("ExportRoomsInView",               _b(r["pieces_vue"])),
        ("IncludeSteelElements",            _b(r["acier"])),
        ("ExportPartsAsBuildingElements",   _b(r["parts"])),
        ("Export2DElements",                _b(r["elements_2d"])),
        ("ExportHostAsSingleEntity",        _b(r["hote_entite_unique"])),
        ("ExportBarsInUniformSetsAsSeparateIFCEntities",
                                            _b(r["armatures_barres"])),

        # Jeux de proprietes
        ("ExportIFCCommonPropertySets",     _b(r["psets_ifc"])),
        ("ExportInternalRevitPropertySets", _b(r["psets_revit"])),
        ("ExportMaterialPsets",             _b(r["psets_materiaux"])),
        ("ExportSchedulesAsPsets",          _b(r["psets_nomenc"])),
        ("ExportSpecificSchedules",         _b(r["nomenc_specifiques"])),
        ("ExportUserDefinedPsets",          _b(r["psets_user"])),

        # Geometrie
        ("ExportSolidModelRep",             _b(r["solides"])),
        ("ExportAdvancedSweptSolids",       _b(r["swept_avances"])),
        ("TessellationLevelOfDetail",       "{0:.2f}".format(float(r["lod"]))),
        ("UseOnlyTriangulation",            _b(r["triangulation"])),
        ("ExportBoundingBox",               _b(r["bbox"])),

        # Georeferencement
        ("SitePlacement",                   str(r["placement"])),
        ("IncludeSiteElevation",            _b(r["altitude_site"])),

        # Divers
        ("StoreIFCGUID",                    _b(r["guid_ifc"])),
        ("UseTypeNameOnlyForIfcType",       _b(r["nom_type_seul"])),
        ("UseVisibleRevitNameAsEntityName", _b(r["nom_visible"])),
        ("UseFamilyAndTypeNameForReference", _b(r["nom_famille_type"])),
        ("IFCFileType",                     str(r["type_fichier"])),
    ]

    if r["psets_user"] and r["psets_user_fichier"]:
        paires.append(("ExportUserDefinedPsetsFileName",
                       r["psets_user_fichier"]))

    phase = int(r.get("phase_id", -1) or -1)
    if phase > 0:
        paires.append(("ActivePhaseId", str(phase)))

    return paires


def options_transmises(reglages, view_id_int):
    """
    Table des options nommees telles qu'elles seront transmises, pour trace
    dans un journal. Sert au diagnostic : si un element manque dans l'IFC, la
    reponse est presque toujours dans cette liste.
    """
    return _options_nommees(reglages, view_id_int)


# Correspondance reglage de l'outil -> propriete de IFCExportConfiguration.
# Les noms de proprietes proviennent du releve par reflexion d'une configuration
# reelle (Revit 2024). Une propriete absente de la version installee est
# simplement ignoree, avec une trace dans le journal.
CORRESPONDANCE_PROPRIETES = [
    ("version",            "IFCVersion"),
    ("type_fichier",       "IFCFileType"),
    ("espaces",            "SpaceBoundaries"),
    ("split_murs",         "SplitWallsAndColumns"),
    ("phase_id",           "ActivePhaseId"),
    ("vue_seule",          "VisibleElementsOfCurrentView"),
    ("pieces_vue",         "ExportRoomsInView"),
    ("acier",              "IncludeSteelElements"),
    ("elements_2d",        "Export2DElements"),
    ("psets_revit",        "ExportInternalRevitPropertySets"),
    ("psets_ifc",          "ExportIFCCommonPropertySets"),
    ("quantites",          "ExportBaseQuantities"),
    ("psets_materiaux",    "ExportMaterialPsets"),
    ("psets_nomenc",       "ExportSchedulesAsPsets"),
    ("nomenc_specifiques", "ExportSpecificSchedules"),
    ("psets_user",         "ExportUserDefinedPsets"),
    ("psets_user_fichier", "ExportUserDefinedPsetsFileName"),
    ("lod",                "TessellationLevelOfDetail"),
    ("parts",              "ExportPartsAsBuildingElements"),
    ("solides",            "ExportSolidModelRep"),
    ("geometrie_vue",      "UseActiveViewGeometry"),
    ("guid_ifc",           "StoreIFCGUID"),
    ("bbox",               "ExportBoundingBox"),
    ("triangulation",      "UseOnlyTriangulation"),
    ("nom_type_seul",      "UseTypeNameOnlyForIfcType"),
    ("nom_visible",        "UseVisibleRevitNameAsEntityName"),
    ("nom_famille_type",   "UseFamilyAndTypeNameForReference"),
    ("placement",          "SitePlacement"),
    ("altitude_site",      "IncludeSiteElevation"),
    ("hote_entite_unique", "ExportHostAsSingleEntity"),
    ("armatures_barres",   "ExportBarsInUniformSetsAsSeparateIFCEntities"),
    ("swept_avances",      "ExportAdvancedSweptSolids"),
]


def config_depuis_reglages(reglages, journal=None):
    """
    Fabrique un IFCExportConfiguration portant les reglages de l'outil.

    C'est la voie fiable : les deux seuls exports ayant abouti sur le modele
    Fairmont sont passes par un objet de configuration, jamais par la table
    d'options AddOption ecrite a la main. UpdateOptions transmet ensuite tout ce
    que le panneau Revit transmet, y compris les options qu'on ne connait pas -
    et notamment il derive lui-meme FilterViewId de
    VisibleElementsOfCurrentView, au lieu qu'on impose un ActiveViewId que le
    panneau, lui, laisse a -1.

    Retourne None si l'assembly de l'exporteur n'est pas chargeable.
    """
    disponible, _msg = charger_assembly_exporteur()
    if not disponible:
        return None
    type_config = (_etat_assembly["types"] or {}).get("config")
    if type_config is None:
        return None
    try:
        cfg = type_config.CreateDefaultConfiguration()
        type_net = cfg.GetType()
    except Exception as ex:
        if journal is not None:
            journal.append(u"CreateDefaultConfiguration : {0}".format(ex))
        return None

    ignores = []
    for clef, nom_prop in CORRESPONDANCE_PROPRIETES:
        if clef not in reglages:
            continue
        valeur = reglages[clef]
        # Phase : -1 signifie "ne pas imposer", on garde la valeur par defaut
        # de la configuration (le panneau y met 0, pas -1).
        if clef == "phase_id":
            try:
                if int(valeur) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        try:
            prop = type_net.GetProperty(nom_prop)
        except Exception:
            prop = None
        if prop is None or not prop.CanWrite:
            ignores.append(nom_prop)
            continue
        try:
            prop.SetValue(cfg, _convertir(prop.PropertyType, valeur), None)
        except Exception as ex:
            ignores.append(u"{0} ({1})".format(nom_prop, ex))

    if ignores and journal is not None:
        journal.append(u"Proprietes non appliquees a la configuration : "
                       + u", ".join(ignores))
    try:
        cfg.Name = u"STR BIM Tools - options manuelles"
    except Exception:
        pass
    return cfg


def construire_options(reglages, view_id_int, journal=None):
    """
    Options d'export pour la vue donnee. Retourne (IFCExportOptions, config).

    Voie principale : un IFCExportConfiguration reel passe a UpdateOptions.
    Repli, si l'assembly de l'exporteur est introuvable : la table d'options
    nommees ecrite a la main (_options_brutes), moins fidele.
    """
    cfg = config_depuis_reglages(reglages, journal)
    if cfg is not None:
        opts = options_depuis_setup(cfg, view_id_int, reglages["vue_seule"],
                                   journal)
        if opts is not None:
            return opts, cfg
        if journal is not None:
            journal.append(u"UpdateOptions indisponible, repli sur la table "
                           u"d'options nommees.")
    return _options_brutes(reglages, view_id_int, journal), None


def _options_brutes(reglages, view_id_int, journal=None):
    """
    Repli : IFCExportOptions rempli a la main.

    N'a jamais suffi a produire un IFC sur un gros modele - conserve uniquement
    pour le cas ou l'assembly de l'exporteur serait introuvable.
    """
    opts = IFCExportOptions()
    opts.FileVersion = version_ifc(reglages["version"])
    opts.ExportBaseQuantities = bool(reglages["quantites"])
    opts.WallAndColumnSplitting = bool(reglages["split_murs"])
    opts.SpaceBoundaryLevel = int(reglages["espaces"])

    if reglages["vue_seule"]:
        opts.FilterViewId = element_id(view_id_int)
    else:
        opts.FilterViewId = ElementId.InvalidElementId

    for clef, valeur in _options_nommees(reglages, view_id_int):
        try:
            opts.AddOption(clef, valeur)
        except Exception as ex:
            if journal is not None:
                journal.append(u"Option refusee par l'API : {0} = {1} ({2})"
                               .format(clef, valeur, ex))
    return opts


# =============================================================================
# Setups IFC enregistres dans le modele (assembly de l'exporteur)
# =============================================================================
_etat_assembly = {"charge": False, "tente": False, "message": u"", "types": None}


def _chemins_assembly_candidats():
    """Chemins possibles de l'assembly du panneau d'export IFC."""
    chemins = []
    try:
        racine = os.path.dirname(
            clr.GetClrType(IFCExportOptions).Assembly.Location)
    except Exception:
        racine = None
    if racine:
        chemins.append(os.path.join(racine, "AddIns", "IFCExporterUI",
                                    "Autodesk.IFC.Export.UI.dll"))
        chemins.append(os.path.join(racine, "AddIns", "IFCExporterUI",
                                    "IFCExporterUIOverride.dll"))
        # Surcharge open source installee en bundle (ProgramData)
        version = os.path.basename(racine).split()[-1]
        prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
        chemins.append(os.path.join(
            prog_data, "Autodesk", "ApplicationPlugins",
            "IFC {0}.bundle".format(version), "Contents", version,
            "IFCExporterUIOverride.dll"))
    return [c for c in chemins if os.path.isfile(c)]


def charger_assembly_exporteur():
    """
    Charge l'assembly du panneau d'export IFC (pour lire les setups du modele).
    Retourne (disponible, message). Idempotent.

    IMPORTANT : IFCExportConfiguration vit dans BIM.IFC.Export.UI
    (Autodesk.IFC.Export.UI.dll), PAS dans Autodesk.Revit.DB.IFC. C'est
    l'erreur qui rendait le "moteur Open IFC" inoperant dans les versions
    precedentes de l'outil.
    """
    if _etat_assembly["tente"]:
        return _etat_assembly["charge"], _etat_assembly["message"]
    _etat_assembly["tente"] = True

    candidats = _chemins_assembly_candidats()
    if not candidats:
        _etat_assembly["message"] = u"Assembly du panneau IFC introuvable."
        return False, _etat_assembly["message"]

    for chemin in candidats:
        try:
            clr.AddReferenceToFileAndPath(chemin)
            module = __import__("BIM.IFC.Export.UI", globals(), locals(),
                                ["IFCExportConfiguration",
                                 "IFCExportConfigurationsMap"])
            _etat_assembly["types"] = {
                "config": getattr(module, "IFCExportConfiguration"),
                "map": getattr(module, "IFCExportConfigurationsMap", None),
            }
            _etat_assembly["charge"] = True
            _etat_assembly["message"] = os.path.basename(chemin)
            return True, _etat_assembly["message"]
        except Exception as ex:
            _etat_assembly["message"] = u"{0} : {1}".format(
                os.path.basename(chemin), ex)
    return False, _etat_assembly["message"]


def _essayer(appels, etiquette, diagnostic):
    """
    Tente plusieurs signatures d'un meme appel (l'API de l'exporteur change
    d'arite selon la version de Revit). Retourne (succes, valeur) et consigne
    l'echec : une source silencieusement absente donne une liste incomplete
    sans que personne ne s'en apercoive.
    """
    derniere = None
    for appel in appels:
        try:
            return True, appel()
        except Exception as ex:
            derniere = ex
    diagnostic.append(u"{0} : indisponible ({1})".format(etiquette, derniere))
    return False, None


def setups_du_modele(doc):
    """
    Setups d'export IFC lisibles, comme la liste "Configuration" du panneau
    Revit. Celle-ci se compose de TROIS sources, et il faut les trois :

      1. la configuration "en session" : les reglages du dernier export IFC
         manuel du modele. C'est celle qui reproduit un export du menu Revit ;
      2. les setups predefinis (IFC2x3 CV2, IFC4 RV, IFC4 DTV...) ;
      3. les setups nommes enregistres dans le modele.

    Retourne (liste_de_(nom, configuration), lignes_de_diagnostic). Liste vide
    si rien n'est lisible : les options manuelles restent utilisables.
    """
    disponible, message = charger_assembly_exporteur()
    if not disponible:
        return [], [u"Assembly de l'exporteur non chargee : {0}".format(message)]

    diagnostic = [u"Assembly : {0}".format(message)]
    type_config = _etat_assembly["types"].get("config")
    type_map = _etat_assembly["types"].get("map")

    resultat = []
    deja_vus = set()

    def ajouter(cfg, origine):
        if cfg is None:
            return 0
        nom = unicode_safe(getattr(cfg, "Name", None) or u"")
        if not nom:
            nom = origine
        if nom.lower() in deja_vus:
            return 0
        deja_vus.add(nom.lower())
        resultat.append((nom, cfg))
        return 1

    # --- 1. Configuration en session ---
    if type_config is not None:
        ok, cfg_session = _essayer(
            [lambda: type_config.GetInSession(),
             lambda: type_config.GetInSession(doc)],
            u"Configuration en session", diagnostic)
        if ok and ajouter(cfg_session, u"<En session>"):
            diagnostic.append(u"Configuration en session : 1")

    # --- 2 et 3. Predefinis + enregistres dans le modele ---
    if type_map is None:
        diagnostic.append(u"IFCExportConfigurationsMap absent de l'assembly.")
        return _trier(resultat), diagnostic

    ok, carte = _essayer([lambda: type_map(doc), lambda: type_map()],
                         u"IFCExportConfigurationsMap", diagnostic)
    if not ok or carte is None:
        return _trier(resultat), diagnostic

    def moissonner(etiquette):
        """Ajoute les configurations presentes dans la carte, et compte."""
        gagnes = 0
        derniere = None
        for source, libelle in ((getattr(carte, "Values", None), u"Values"),
                                (carte, u"enumeration directe")):
            if source is None:
                continue
            try:
                for cfg in source:
                    gagnes += ajouter(cfg, u"(sans nom)")
                derniere = None
                break
            except Exception as ex:
                derniere = u"{0} via {1}".format(ex, libelle)
        if derniere:
            diagnostic.append(u"{0} : lecture en echec ({1})".format(etiquette,
                                                                     derniere))
        else:
            diagnostic.append(u"{0} : {1}".format(etiquette, gagnes))
        return gagnes

    # --- 2. Setups predefinis ---
    methode = getattr(carte, "AddBuiltInConfigurations", None)
    if methode is None:
        diagnostic.append(u"AddBuiltInConfigurations : methode absente")
    else:
        _essayer([lambda: methode(doc), lambda: methode()],
                 u"AddBuiltInConfigurations", diagnostic)
    moissonner(u"Setups predefinis")

    # --- 3. Setups enregistres dans le modele ---
    _publier_document(doc, diagnostic)
    methode = getattr(carte, "AddSavedConfigurations", None)
    if methode is None:
        diagnostic.append(u"AddSavedConfigurations : methode absente")
    else:
        _essayer([lambda: methode(doc), lambda: methode()],
                 u"AddSavedConfigurations", diagnostic)
    if moissonner(u"Setups enregistres dans le modele") == 0:
        # Repli : lire les setups directement dans le stockage extensible.
        diagnostic.append(u"Aucun setup livre par l'assembly, lecture directe "
                          u"du stockage extensible :")
        lus = 0
        for nom, cfg in configs_depuis_stockage(doc, diagnostic):
            lus += ajouter(cfg, nom)
        diagnostic.append(u"Setups lus en direct : {0}".format(lus))
        if lus == 0:
            diagnostic.append(
                u"Aucun setup enregistre du modele lu. Contournement : ouvrez "
                u"une fois Fichier > Exporter > IFC dans Revit (il suffit "
                u"d'annuler), puis relancez l'outil.")

    if not resultat:
        diagnostic.append(u"Aucun setup lisible.")
    return _trier(resultat), diagnostic


NOM_SCHEMA_SETUPS = u"IFCExportConfigurationMap"


def _valeur_champ(entite, champ):
    """Valeur d'un champ de stockage extensible, quelle que soit sa signature."""
    type_valeur = champ.ValueType
    for lecture in (lambda: entite.Get[type_valeur](champ),
                    lambda: entite.Get[type_valeur](champ.FieldName)):
        try:
            return True, lecture()
        except Exception as ex:
            derniere = ex
    return False, derniere


def _convertir(cible, valeur):
    """Adapte une valeur JSON au type .NET attendu par une propriete."""
    nom_type = cible.Name
    if cible.IsEnum:
        try:
            return System.Enum.ToObject(cible, int(valeur))
        except Exception:
            return System.Enum.Parse(cible, u"{0}".format(valeur))
    if nom_type == "Boolean":
        return bool(valeur)
    if nom_type in ("Double", "Single"):
        return float(valeur)
    if nom_type in ("Int32", "Int64", "Int16"):
        return int(valeur)
    if nom_type == "String":
        return u"{0}".format(valeur)
    return valeur


def _configs_depuis_json(type_config, texte, diagnostic):
    """
    Decode le champ MapField : les setups enregistres y sont serialises en JSON
    par l'assembly de l'exporteur (via son IFCExportConfigurationConverter).

    Retourne [(nom, configuration)].
    """
    try:
        donnees = json.loads(texte)
    except Exception as ex:
        diagnostic.append(u"MapField illisible (JSON) : {0}".format(ex))
        return []

    # La structure varie selon la version : dictionnaire nom -> configuration,
    # liste de configurations, ou configuration unique.
    candidats = []
    if isinstance(donnees, dict):
        sous = [v for v in donnees.values() if isinstance(v, dict)]
        candidats = sous if sous else [donnees]
    elif isinstance(donnees, list):
        candidats = [v for v in donnees if isinstance(v, dict)]
    if not candidats:
        diagnostic.append(u"MapField : aucune configuration reconnue "
                          u"(type {0})".format(type(donnees).__name__))
        return []

    diagnostic.append(u"MapField : {0} configuration(s), clefs de la premiere : "
                      u"{1}".format(len(candidats),
                                    u", ".join(sorted(candidats[0].keys()))[:400]))

    resultat = []
    for brut in candidats:
        valeurs = {}
        for clef, valeur in brut.items():
            if clef.startswith(u"$") or isinstance(valeur, (dict, list)):
                continue
            valeurs[clef] = valeur
        if not valeurs:
            continue
        cfg, applique, ignores = _config_depuis_valeurs(type_config, valeurs)
        if cfg is None:
            continue
        nom = unicode_safe(getattr(cfg, "Name", u"") or u"")
        if not nom:
            nom = unicode_safe(brut.get(u"Name") or u"(sans nom)")
        resultat.append((nom, cfg))
        diagnostic.append(u"    {0} : {1} champs appliques{2}".format(
            nom, applique,
            u", ignores : " + u", ".join(sorted(ignores)) if ignores else u""))
    return resultat


def _config_depuis_valeurs(type_config, valeurs):
    """
    Reconstruit un IFCExportConfiguration a partir des champs stockes.

    On part de la configuration par defaut puis on ecrit chaque champ sur la
    propriete de meme nom, par reflexion : l'objet obtenu est un vrai
    IFCExportConfiguration, donc UpdateOptions transmettra ensuite TOUTES les
    options que le panneau Revit transmet, y compris celles que l'outil
    n'expose pas.
    """
    try:
        cfg = type_config.CreateDefaultConfiguration()
    except Exception as ex:
        return None, 0, [u"CreateDefaultConfiguration : {0}".format(ex)]

    type_net = cfg.GetType()
    applique = 0
    ignores = []
    for nom, valeur in valeurs.items():
        prop = None
        # Les noms de champs ne collent pas toujours aux noms de proprietes :
        # essayer le nom brut, puis sans prefixe technique.
        for candidat in (nom, nom.replace(u"Setup", u"", 1),
                         nom.replace(u"IFC", u"", 1)):
            try:
                prop = type_net.GetProperty(candidat)
            except Exception:
                prop = None
            if prop is not None:
                break
        if prop is None or not prop.CanWrite:
            ignores.append(nom)
            continue
        try:
            prop.SetValue(cfg, _convertir(prop.PropertyType, valeur), None)
            applique += 1
        except Exception:
            ignores.append(nom)
    return cfg, applique, ignores


def configs_depuis_stockage(doc, diagnostic):
    """
    Lit les setups enregistres directement dans le stockage extensible du
    modele, sans passer par AddSavedConfigurations.

    Necessaire parce que l'assembly refuse de les livrer : elle exige que
    IFCCommandOverrideApplication.TheDocument soit renseigne, propriete qui
    n'est ni accessible en ecriture ni exposee en set_TheDocument. Les setups
    sont pourtant bien la, portes par des DataStorage au schema
    IFCExportConfigurationMap.
    """
    resultat = []
    if not STOCKAGE_LISIBLE:
        diagnostic.append(u"Lecture directe impossible : stockage extensible "
                          u"illisible.")
        return resultat
    type_config = (_etat_assembly["types"] or {}).get("config")
    if type_config is None:
        diagnostic.append(u"Lecture directe impossible : IFCExportConfiguration "
                          u"indisponible.")
        return resultat

    try:
        stockages = list(FilteredElementCollector(doc)
                         .OfClass(DataStorage).ToElements())
    except Exception as ex:
        diagnostic.append(u"Lecture directe : collecte impossible ({0})".format(ex))
        return resultat

    champs_tracees = False
    for st in stockages:
        try:
            guids = list(st.GetEntitySchemaGuids())
        except Exception:
            continue
        for guid in guids:
            try:
                schema = Schema.Lookup(guid)
            except Exception:
                schema = None
            if schema is None:
                continue
            try:
                if unicode_safe(schema.SchemaName) != NOM_SCHEMA_SETUPS:
                    continue
                entite = st.GetEntity(schema)
                if not entite.IsValid():
                    continue
                champs = list(schema.ListFields())
            except Exception as ex:
                diagnostic.append(u"Lecture directe [{0}] : {1}".format(
                    id_value(st.Id), ex))
                continue

            valeurs = {}
            for champ in champs:
                ok, valeur = _valeur_champ(entite, champ)
                if ok:
                    valeurs[unicode_safe(champ.FieldName)] = valeur
            if not champs_tracees:
                diagnostic.append(u"Champs du schema : {0}".format(
                    u", ".join(sorted([unicode_safe(c.FieldName)
                                       for c in champs]))))
                champs_tracees = True
            if not valeurs:
                continue

            # Cas reel sur Revit 2024 : le schema n'a qu'un champ, MapField, qui
            # contient toutes les configurations serialisees en JSON. Il ne
            # correspond a aucune propriete de IFCExportConfiguration : il faut
            # le decoder, pas l'affecter.
            texte_carte = None
            for clef in (u"MapField", u"Map", u"Configurations"):
                if clef in valeurs and isinstance(valeurs[clef],
                                                  (str, type(u""))):
                    texte_carte = valeurs[clef]
                    break

            if texte_carte:
                diagnostic.append(u"MapField [{0}] : {1} caracteres".format(
                    id_value(st.Id), len(texte_carte)))
                for nom, cfg in _configs_depuis_json(type_config, texte_carte,
                                                     diagnostic):
                    resultat.append((nom, cfg))
                continue

            cfg, applique, ignores = _config_depuis_valeurs(type_config, valeurs)
            if cfg is None:
                diagnostic.append(u"Lecture directe [{0}] : {1}".format(
                    id_value(st.Id), u" / ".join(ignores)))
                continue
            nom = unicode_safe(getattr(cfg, "Name", u"") or u"")
            if not nom:
                nom = u"Setup du modele [{0}]".format(id_value(st.Id))
            resultat.append((nom, cfg))
            diagnostic.append(
                u"Lu dans le modele : {0} ({1} champs appliques{2})".format(
                    nom, applique,
                    u", ignores : " + u", ".join(sorted(ignores))
                    if ignores else u""))
    return resultat


def _publier_document(doc, diagnostic):
    """
    Renseigne le document courant dans le statique de l'assembly de l'exporteur.

    L'assembly garde le document actif dans IFCCommandOverrideApplication.
    TheDocument, qui n'est rempli que lorsque l'utilisateur ouvre le panneau
    "Exporter > IFC" de Revit. Tant qu'il est vide, AddSavedConfigurations()
    ne trouve aucun document a interroger : elle repond sans erreur et sans
    rien ajouter. La liste est alors amputee de tous les setups du bureau
    (SPVA_Export_IFC4...) sans le moindre message d'avertissement.
    """
    try:
        module = __import__("BIM.IFC.Export.UI", globals(), locals(),
                            ["IFCCommandOverrideApplication"])
        type_app = getattr(module, "IFCCommandOverrideApplication")
    except Exception as ex:
        diagnostic.append(
            u"IFCCommandOverrideApplication introuvable : {0}".format(ex))
        return False

    # TheDocument est un membre STATIQUE PROTEGE : IronPython refuse d'y toucher
    # ("cannot access protected member without a python subclass"), mais la
    # reflexion .NET peut l'ecrire. C'est la voie qui debloque
    # AddSavedConfigurations, donc les setups enregistres du modele.
    drapeaux = (BindingFlags.Static | BindingFlags.NonPublic
                | BindingFlags.Public | BindingFlags.FlattenHierarchy)

    def _par_reflexion():
        type_net = clr.GetClrType(type_app)
        prop = type_net.GetProperty("TheDocument", drapeaux)
        if prop is not None and prop.CanWrite:
            prop.SetValue(None, doc, None)
            return
        for nom_champ in ("TheDocument", "theDocument", "m_theDocument",
                          "<TheDocument>k__BackingField"):
            champ = type_net.GetField(nom_champ, drapeaux)
            if champ is not None:
                champ.SetValue(None, doc)
                return
        raise Exception(u"ni propriete ni champ TheDocument accessible")

    echecs = []
    for etiquette, poser in (
            (u"reflexion", _par_reflexion),
            (u"TheDocument", lambda: setattr(type_app, "TheDocument", doc)),
            (u"set_TheDocument", lambda: type_app.set_TheDocument(doc))):
        try:
            poser()
            diagnostic.append(u"Document publie a l'assembly ({0}).".format(
                etiquette))
            return True
        except Exception as ex:
            # Consigner CHAQUE tentative : ne rapporter que la derniere masque
            # la vraie raison du refus (propriete en lecture seule, absente...).
            echecs.append(u"{0} -> {1}".format(etiquette, ex))
    diagnostic.append(u"Document non publiable a l'assembly : {0}".format(
        u" | ".join(echecs)))
    return False


def _trier(paires):
    """Configuration en session en tete, le reste par ordre alphabetique."""
    session = [p for p in paires if p[0].lower().find(u"session") >= 0]
    autres = sorted([p for p in paires if p not in session],
                    key=lambda paire: paire[0].lower())
    return session + autres


def options_depuis_setup(config, view_id_int, vue_seule, journal=None):
    """
    Construit les options a partir d'un setup du modele (autoritaire).
    Retourne IFCExportOptions, ou None si l'API refuse.
    """
    opts = IFCExportOptions()
    filtre = element_id(view_id_int) if vue_seule else ElementId.InvalidElementId

    appels = (
        lambda: config.UpdateOptions(opts, filtre),
        lambda: config.UpdateOptions(opts, view_id_int),
        lambda: config.UpdateOptions(opts, filtre, None),
    )
    derniere = None
    for appel in appels:
        try:
            appel()
            opts.FilterViewId = filtre
            return opts
        except Exception as ex:
            derniere = ex
    if journal is not None:
        journal.append(u"UpdateOptions a echoue : {0}".format(derniere))
    return None


def decrire_configuration(cfg):
    """
    Toutes les proprietes publiques lisibles d'un IFCExportConfiguration, par
    reflexion .NET : [(nom, valeur)] trie par nom.

    Sert a comparer une configuration qui fonctionne (celle en session, ou un
    setup du modele) avec les options que l'outil transmet. C'est le seul moyen
    de reperer une option decisive que l'outil n'expose pas du tout - la liste
    des proprietes de l'exporteur est plus large que celle des options nommees.
    """
    lignes = []
    if cfg is None:
        return [(u"(aucune configuration)", u"")]
    try:
        type_net = cfg.GetType()
        proprietes = list(type_net.GetProperties())
    except Exception as ex:
        return [(u"(reflexion impossible)", unicode_safe(ex))]

    for prop in proprietes:
        try:
            nom = unicode_safe(prop.Name)
        except Exception:
            continue
        try:
            if not prop.CanRead or len(list(prop.GetIndexParameters())):
                continue
            valeur = unicode_safe(prop.GetValue(cfg, None))
        except Exception as ex:
            valeur = u"<illisible : {0}>".format(ex)
        lignes.append((nom, valeur))
    lignes.sort()
    return lignes or [(u"(aucune propriete lisible)", u"")]


def inventaire_schemas_ifc(doc):
    """
    Inventaire du stockage extensible lie a l'IFC : schemas enregistres dans la
    session et DataStorage presents dans le modele.

    Sert quand l'assembly de l'exporteur refuse de livrer les setups
    enregistres : cet inventaire dit s'ils sont bien dans le modele, et sous
    quel schema, ce qui ouvre la voie a une lecture directe.
    """
    if not STOCKAGE_LISIBLE:
        return [u"Stockage extensible illisible : DataStorage/Schema absents "
                u"de Autodesk.Revit.DB.ExtensibleStorage sur ce Revit."]

    lignes = []
    try:
        schemas = list(Schema.ListSchemas())
        lignes.append(u"Schemas enregistres dans la session : {0}".format(
            len(schemas)))
        for sch in schemas:
            try:
                nom = unicode_safe(sch.SchemaName)
            except Exception:
                nom = u"?"
            if nom.lower().find(u"ifc") >= 0:
                lignes.append(u"    schema IFC : {0}  ({1})".format(
                    nom, unicode_safe(sch.GUID)))
    except Exception as ex:
        lignes.append(u"ListSchemas : {0}".format(ex))

    try:
        stockages = list(FilteredElementCollector(doc)
                         .OfClass(DataStorage).ToElements())
        lignes.append(u"DataStorage dans le modele : {0}".format(
            len(stockages)))
        for st in stockages:
            try:
                guids = list(st.GetEntitySchemaGuids())
            except Exception:
                continue
            for guid in guids:
                sch = None
                try:
                    sch = Schema.Lookup(guid)
                except Exception:
                    sch = None
                nom = (unicode_safe(sch.SchemaName) if sch is not None
                       else u"(schema non enregistre)")
                if sch is None or nom.lower().find(u"ifc") >= 0:
                    lignes.append(u"    {0} [{1}] -> {2}  ({3})".format(
                        unicode_safe(st.Name) or u"(sans nom)",
                        id_value(st.Id), nom, unicode_safe(guid)))
    except Exception as ex:
        lignes.append(u"Inventaire DataStorage : {0}".format(ex))
    return lignes


def unicode_safe(valeur):
    """Chaine .NET -> texte, sans planter en IronPython 2.7."""
    try:
        return u"{0}".format(valeur)
    except Exception:
        return u"?"
