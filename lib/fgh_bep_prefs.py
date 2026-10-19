# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_prefs.py - Reglages utilisateur du controle de conformite BEP.
#
# Deux fichiers, deux roles, volontairement separes :
#   - fgh_bep_config.json  = le REFERENTIEL, ce que le BEP SPVA impose. Il est
#     livre avec l'extension et ecrase a chaque mise a jour de celle-ci ;
#   - fgh_bep_prefs.json   = les REGLAGES de l'utilisateur, saisis depuis le
#     bouton « Configuration » de la fenetre de resultats. Jamais livre,
#     jamais ecrase, il survit aux mises a jour.
#
# Un reglage present ici REMPLACE la valeur du referentiel (il ne s'y ajoute
# pas) : ce que la fenetre affiche est exactement ce qui sera applique, sans
# fusion invisible derriere le dos de celui qui saisit.
#
# Ce module NE DEPEND PAS de l'API Revit ni de WPF. IronPython 2.7 compatible.
# =============================================================================

import os
import io
import json

FICHIER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fgh_bep_prefs.json")

# Separateur de saisie impose a l'utilisateur, et utilise pour re-afficher
# une liste. La lecture est plus permissive (voir depuis_texte).
SEPARATEUR = u" ; "


def charger():
    """Reglages utilisateur. Ne leve jamais : pas de fichier = pas de reglage,
    et le controle tourne alors sur le seul referentiel."""
    try:
        with io.open(FICHIER, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def enregistrer(d):
    """Ecrit le dictionnaire complet des reglages.
    Retourne (True, u"") ou (False, message) : l'echec doit se dire a l'ecran,
    pas disparaitre dans un except muet."""
    try:
        txt = json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True)
        # IronPython 2.7 : json.dumps rend un str (octets) des que la donnee
        # est purement ASCII ; io.open en mode texte n'accepte que de l'unicode.
        if isinstance(txt, bytes):
            txt = txt.decode("utf-8")
        with io.open(FICHIER, "w", encoding="utf-8") as f:
            f.write(txt)
        return True, u""
    except Exception as ex:
        return False, u"{0} : {1}".format(type(ex).__name__, ex)


# --- Conversions liste <-> texte saisi ----------------------------------------
def depuis_texte(txt):
    """« A ; B;C  » -> [u"A", u"B", u"C"]. Le point-virgule seul suffit :
    exiger les espaces autour ferait perdre une saisie correcte sur un detail
    de frappe. Les entrees vides et les doublons sont ecartes."""
    out = []
    for morceau in (txt or u"").replace(u"\r", u"\n").replace(u"\n", u";").split(u";"):
        v = morceau.strip()
        if v and v not in out:
            out.append(v)
    return out


def vers_texte(valeurs):
    """[u"A", u"B"] -> u"A ; B"."""
    return SEPARATEUR.join([v for v in (valeurs or []) if v])


# --- Exclusions de familles par categorie interdite ---------------------------
def exclusions_famille():
    """{nom_categorie_OST: [prefixe, ...]} tel que regle par l'utilisateur.
    Une categorie absente du dictionnaire garde la valeur du referentiel."""
    d = charger().get("exclusions_famille")
    if not isinstance(d, dict):
        return {}
    out = {}
    for cle, valeurs in d.items():
        if isinstance(valeurs, list):
            out[cle] = [v for v in valeurs if v]
        elif valeurs is None:
            out[cle] = []
    return out


def ecrire_exclusions_famille(par_categorie):
    """Remplace le bloc des exclusions et reecrit le fichier. Les autres
    reglages presents sont preserves : cette fenetre s'etoffera."""
    d = charger()
    d["exclusions_famille"] = dict(par_categorie or {})
    return enregistrer(d)


# --- Jeu de caracteres par nature d'objet -------------------------------------
def caracteres_extra():
    """{cle_portee: [caractere, ...]} regle par l'utilisateur.

    Une nature d'objet absente du dictionnaire garde le jeu du referentiel.
    Une liste VIDE est un reglage a part entiere - « lettres et chiffres,
    rien d'autre » - et ne doit donc pas etre confondue avec l'absence.
    """
    d = charger().get("caracteres_extra")
    if not isinstance(d, dict):
        return {}
    out = {}
    for cle, valeurs in d.items():
        if isinstance(valeurs, list):
            out[cle] = [v for v in valeurs if v]
        elif valeurs is None:
            out[cle] = []
    return out


def ecrire_caracteres_extra(par_portee):
    """Remplace le bloc des jeux de caracteres. Les autres reglages presents
    sont preserves."""
    d = charger()
    d["caracteres_extra"] = dict(par_portee or {})
    return enregistrer(d)


def depuis_texte_caracteres(txt):
    """Saisie libre -> liste de caracteres uniques.

    Plus permissif que depuis_texte() : on accepte aussi bien « _ . - » que
    « _;.;- » ou « _.- ». Chaque caractere non blanc compte pour lui-meme,
    parce qu'ici une « valeur » est un seul signe et que la ponctuation de
    separation est justement ce que l'on cherche a autoriser.
    """
    out = []
    for c in (txt or u""):
        if c.isspace() or c == u";":
            continue
        if c not in out:
            out.append(c)
    return out


def vers_texte_caracteres(valeurs):
    """[u'_', u'.'] -> u'_ . ' lisible, un caractere par groupe."""
    return u" ".join([v for v in (valeurs or []) if v])


def empreinte():
    """Empreinte du fichier de reglages, ou None s'il n'y en a pas.

    Un rapport doit pouvoir dire si des reglages locaux etaient actifs, et
    lesquels : deux controles du meme jour sur la meme maquette peuvent
    diverger pour cette seule raison."""
    if not os.path.isfile(FICHIER):
        return None
    import fgh_bep_config
    return fgh_bep_config.empreinte(FICHIER)
