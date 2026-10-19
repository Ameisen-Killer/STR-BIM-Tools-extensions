# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_config.py - Referentiel BEP du projet Fairmont Grand Hotel (FGH).
#
# Charge « fgh_bep_config.json » (racine de l'extension) : toutes les valeurs
# imposees par le BEP SPVA y sont ecrites en donnees, jamais en dur dans le
# code. Ajouter une zone, corriger une altitude ou changer un nom d'attribut
# se fait donc sans toucher a une ligne de Python.
#
# Si le fichier est absent ou illisible, le module retombe sur un referentiel
# minimal integre : l'outil doit pouvoir dire « le referentiel est manquant »
# plutot que refuser de demarrer.
#
# Ce module NE DEPEND PAS de l'API Revit ni de WPF. IronPython 2.7 compatible.
# =============================================================================

import os
import io
import json
import re

import fgh_bep_prefs

FICHIER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fgh_bep_config.json")

# Referentiel de secours : le strict minimum pour que l'outil demarre et
# signale lui-meme l'absence du fichier de configuration.
_DEFAUT = {
    "projet": {"code": u"FGH", "discipline": u"STR", "emetteur": u"ABI",
               "version_revit": u"2024", "taille_max_mo": 350,
               "num_mandataire_percement": u"02"},
    "unites": {"longueur": u"Centimeters", "surface": u"SquareMeters",
               "volume": u"CubicMeters", "angle": u"Degrees"},
    "geo": {}, "niveaux": [], "niveau_reference": u"FGH_100",
    "tolerance_niveau_m": 0.005,
    "sous_projets": {"prefixes_autorises": [], "attendus": [],
                     "controler_attendus": False},
    "nommage": {"caracteres_autorises": u"^[A-Za-z0-9_]+$",
                "prefixe_specialite": u"STR_", "prefixes_toleres": [],
                "portees": {}},
    "zones": [], "attributs": [],
    "reservations": {}, "livrables": {},
    "categories_modele": [], "categories_porteuses": [],
    "categories_interdites": {},
    "param_loadbearing": u"LoadBearing",
    "limites": {"constats_par_regle": 2000},
}


# Natures d'objets soumises au controle de nommage : (cle du referentiel,
# libelle affiche). Table unique, partagee par le moteur de regles et par la
# fenetre de configuration - un libelle qui diverge entre les deux rendrait
# impossible de relier un reglage a la ligne d'ecart qu'il gouverne.
PORTEES = (
    ("familles",      u"Famille"),
    ("types",         u"Type"),
    ("materiaux",     u"Matériau"),
    ("sous_projets",  u"Sous-projet"),
    ("parametres",    u"Paramètre de projet"),
    ("feuilles",      u"Feuille"),
    ("vues",          u"Vue"),
    ("nomenclatures", u"Nomenclature"),
)

LIBELLE_PORTEE = dict(PORTEES)
PORTEE_PAR_LIBELLE = dict([(lib, cle) for cle, lib in PORTEES])

# Jeu de base impose par le BEP 2.10 : lettres non accentuees et chiffres.
# Tout le reste se regle caractere par caractere (voir caracteres_extra).
BASE_CARACTERES = u"A-Za-z0-9"


def motif_depuis_extra(extra):
    r"""['_', '.'] -> '^[A-Za-z0-9_\.]+$'. Les caracteres sont echappes un a
    un : la saisie vient d'un champ libre, elle ne doit jamais pouvoir se
    comporter comme un fragment d'expression reguliere."""
    dedans = u"".join([re.escape(c) for c in (extra or []) if c])
    return u"^[{0}{1}]+$".format(BASE_CARACTERES, dedans)


def empreinte(chemin):
    """Empreinte courte d'un fichier, ou une mention explicite.

    SHA-1 tronquee a 12 caracteres : de quoi comparer deux rapports d'un coup
    d'oeil, sans pretendre a un scellement cryptographique. Si hashlib manque
    sur le moteur, on retombe sur taille+date, qui distingue encore deux
    versions du meme fichier - et on le dit, plutot que de laisser croire a
    une empreinte."""
    try:
        with io.open(chemin, "rb") as f:
            octets = f.read()
    except Exception:
        return u"(fichier absent)"
    try:
        import hashlib
        return hashlib.sha1(octets).hexdigest()[:12]
    except Exception:
        pass
    try:
        return u"taille {0} o, modifie {1:.0f}".format(
            len(octets), os.path.getmtime(chemin))
    except Exception:
        return u"(empreinte indisponible)"


class Referentiel(object):
    """Acces confortable au referentiel BEP charge depuis le JSON."""

    def __init__(self, data, source=None, erreur=None):
        self._d = data
        self.source = source
        self.erreur = erreur

    # -- acces generique ------------------------------------------------------
    def get(self, cle, defaut=None):
        return self._d.get(cle, defaut)

    def bloc(self, cle):
        """Sous-dictionnaire, toujours un dict meme si la cle manque."""
        v = self._d.get(cle)
        return v if isinstance(v, dict) else {}

    # -- raccourcis metier ----------------------------------------------------
    @property
    def bep(self):
        """Reference contractuelle controlee : revision, date, emetteur."""
        return self.bloc("bep")

    @property
    def empreinte(self):
        """Empreinte du fichier de referentiel effectivement charge."""
        return empreinte(self.source or FICHIER)

    def derogations(self):
        """
        [(sujet, valeur du BEP, valeur appliquee)] pour chaque reglage qui
        s'ecarte du referentiel.

        C'est la piece qui manque a un rapport pour etre probant : deux
        controles du meme jour, sur la meme maquette, peuvent diverger par ce
        seul jeu de reglages. Liste vide = le referentiel a ete applique tel
        quel.
        """
        out = []
        for cle, libelle in PORTEES:
            surcharges = fgh_bep_prefs.caracteres_extra()
            if cle not in surcharges:
                continue
            brut = self.caracteres_extra_referentiel(cle)
            applique = list(surcharges[cle])
            if applique == list(brut):
                continue
            out.append((
                u"Caractères admis — {0}".format(libelle),
                u" ".join(brut) or u"(lettres et chiffres seuls)",
                u" ".join(applique) or u"(lettres et chiffres seuls)"))

        surcharges = fgh_bep_prefs.exclusions_famille()
        brut_cats = self.bloc("categories_interdites")
        for nom_cat in sorted(surcharges.keys()):
            if nom_cat not in brut_cats:
                continue
            brut = self.categorie_interdite_referentiel(nom_cat)
            avant = list(brut.get("exclusions_famille") or [])
            apres = list(surcharges[nom_cat])
            if avant == apres:
                continue
            libelle = (brut.get("libelle") if isinstance(brut, dict) else None)                 or nom_cat
            out.append((
                u"Familles tolérées — {0}".format(libelle),
                u" ; ".join(avant) or u"(aucune)",
                u" ; ".join(apres) or u"(aucune)"))
        return out

    @property
    def projet(self):
        return self.bloc("projet")

    @property
    def geo(self):
        return self.bloc("geo")

    @property
    def unites(self):
        return self.bloc("unites")

    @property
    def nommage(self):
        return self.bloc("nommage")

    # -- jeu de caracteres par nature d'objet ---------------------------------
    def caracteres_extra_referentiel(self, cle_portee=None):
        """Caracteres admis en plus des lettres et chiffres, tels que le BEP
        les impose. Sans cle, la valeur par defaut."""
        bloc = self.nommage.get("caracteres_extra")
        if not isinstance(bloc, dict):
            # Referentiel ancien, sans le bloc : on retrouve les caracteres
            # supplementaires en retirant la base du motif global.
            return [u"_"]
        if cle_portee and cle_portee in bloc:
            return list(bloc.get(cle_portee) or [])
        return list(bloc.get("_defaut") or [])

    def caracteres_extra(self, cle_portee):
        """Jeu effectif pour une nature d'objet : le reglage utilisateur s'il
        existe pour elle, sinon la valeur du referentiel."""
        surcharges = fgh_bep_prefs.caracteres_extra()
        if cle_portee in surcharges:
            return list(surcharges[cle_portee])
        return self.caracteres_extra_referentiel(cle_portee)

    def motif_nommage(self, cle_portee=None):
        """Expression reguliere du jeu de caracteres pour une nature d'objet.

        Sans reglage ni bloc `caracteres_extra`, on rend le motif global du
        referentiel tel quel : une maquette dont personne n'a touche la
        configuration se controle exactement comme avant.
        """
        if cle_portee is None:
            return self.nommage.get("caracteres_autorises")
        if not isinstance(self.nommage.get("caracteres_extra"), dict) and \
                cle_portee not in fgh_bep_prefs.caracteres_extra():
            return self.nommage.get("caracteres_autorises")
        return motif_depuis_extra(self.caracteres_extra(cle_portee))

    def motifs_par_libelle(self):
        """{libelle affiche: motif} - forme attendue par la fenetre de
        resultats, qui ne connait des objets que leur libelle."""
        return dict([(lib, self.motif_nommage(cle)) for cle, lib in PORTEES])

    @property
    def sous_projets(self):
        return self.bloc("sous_projets")

    @property
    def zones(self):
        return list(self._d.get("zones") or [])

    @property
    def niveaux(self):
        """Liste de dicts {code, nom, alt} dans l'ordre du BEP."""
        return list(self._d.get("niveaux") or [])

    @property
    def codes_niveaux(self):
        return [n.get("code") for n in self.niveaux if n.get("code")]

    def niveau_par_nom(self, nom):
        """Retrouve un niveau du referentiel par son code, son nom long ou
        l'un de ses alias (variantes d'ecriture tolerees)."""
        if not nom:
            return None
        cible = nom.strip()
        for n in self.niveaux:
            if cible == (n.get("code") or u"") or cible == (n.get("nom") or u""):
                return n
            for a in (n.get("alias") or []):
                if cible == a:
                    return n
        return None

    @property
    def reservations(self):
        return self.bloc("reservations")

    @property
    def livrables(self):
        return self.bloc("livrables")

    def resoudre_valeurs(self, valeurs):
        """
        Developpe le jeton "@zones" d'une liste de valeurs admises : les zones
        de coordination ne sont ecrites qu'une fois dans le referentiel.
        """
        if not valeurs:
            return valeurs
        if valeurs == "@zones":
            return self.zones
        out = []
        for v in valeurs:
            if v == "@zones":
                out.extend(self.zones)
            else:
                out.append(v)
        return out

    @property
    def attributs(self):
        """
        Liste des attributs PVA a controler. La valeur speciale "@zones" du
        champ `valeurs` est resolue ici : le JSON n'a pas a recopier la liste
        des zones deux fois.
        """
        out = []
        for a in (self._d.get("attributs") or []):
            a = dict(a)
            a["valeurs"] = self.resoudre_valeurs(a.get("valeurs"))
            out.append(a)
        return out

    @property
    def categories_modele(self):
        return list(self._d.get("categories_modele") or [])

    @property
    def categories_porteuses(self):
        return list(self._d.get("categories_porteuses") or [])

    @property
    def categories_interdites(self):
        """
        {nom_categorie_OST: {libelle, message, exclusions_famille}}.

        Les exclusions reglees par l'utilisateur (bouton « Configuration » de
        la fenetre de resultats) REMPLACENT celles du referentiel pour la
        categorie concernee. Une categorie absente des reglages garde sa
        valeur BEP ; une categorie reglee mais inconnue du referentiel est
        ignoree, elle ne cree pas de controle fantome.
        """
        surcharges = fgh_bep_prefs.exclusions_famille()
        out = {}
        for nom, spec in self.bloc("categories_interdites").items():
            # Le referentiel autorise la forme courte « categorie: message ».
            spec = dict(spec) if isinstance(spec, dict) else {"message": spec}
            if nom in surcharges:
                spec["exclusions_famille"] = list(surcharges[nom])
            out[nom] = spec
        return out

    def categorie_interdite_referentiel(self, nom_categorie):
        """Specification BEP d'une categorie interdite, hors reglages
        utilisateur : c'est elle que restaure « Valeurs du referentiel »."""
        spec = self.bloc("categories_interdites").get(nom_categorie)
        return dict(spec) if isinstance(spec, dict) else {"message": spec or u""}

    @property
    def param_loadbearing(self):
        return self._d.get("param_loadbearing") or u"LoadBearing"

    @property
    def max_constats(self):
        try:
            return int(self.bloc("limites").get("constats_par_regle", 2000))
        except (TypeError, ValueError):
            return 2000


def charger():
    """
    Retourne un Referentiel. Ne leve jamais : une configuration illisible
    donne un referentiel de secours porteur du message d'erreur, que le
    dashboard affiche comme une non-conformite a part entiere.
    """
    try:
        with io.open(FICHIER, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as ex:
        return Referentiel(dict(_DEFAUT), source=FICHIER,
                           erreur=u"Référentiel BEP illisible : {0}".format(ex))

    # Les cles absentes du fichier prennent la valeur de secours plutot que
    # de faire planter une regle a l'execution.
    fusion = dict(_DEFAUT)
    fusion.update(data)
    return Referentiel(fusion, source=FICHIER)
