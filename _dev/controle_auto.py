# -*- coding: utf-8 -*-
"""
Controle automatique d'un depot STR BIM Tools, HORS Revit. Lance par GitHub
Actions a chaque envoi (.github/workflows/controle.yml), utilisable en local :

    python _dev/controle_auto.py                     depot courant
    python _dev/controle_auto.py --racine <dossier>  autre depot (CAN 241)
    python _dev/controle_auto.py --depot-public      + garde-fou CAN 241

Python 3.8+. PyYAML est necessaire pour lire les bundle.yaml (controle ignore
s'il manque). La syntaxe IronPython 2.7 elle-meme est verifiee a part par
syntaxe_py27.py, lance avec un vrai Python 2.7.

ERREURS (le controle echoue) : ce qui casse le chargement de pyRevit ou fait
planter un outil.
  - fichier illisible en UTF-8, marqueurs de conflit git (<<<<<<<) ;
  - bundle.yaml ou .json invalide, cle en double, layout mal forme ;
  - syntaxe ou appel Python 3 seulement (f-string, nonlocal, super() sans
    argument, print(..., end=) sans import __future__...) ;
  - nom importe de l'API Revit absent de Revit 2024 (hors bloc try) ;
  - XAML mal forme ;
  - appel vers un module de lib/ qui n'expose pas le nom appele ;
  - avec --depot-public : fichier ou import CAN 241.

AVERTISSEMENTS : layout qui cite un element absent ou oublie un bouton (il
n'apparait alors pas dans le ruban), fenetre sans version, "STR BIM Tools" ou
"Tony VARIN", XAML non ASCII, nom Revit invalide dans un bloc try,
self.attribut lu mais jamais assigne.
"""

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

try:
    import yaml
except ImportError:
    yaml = None

DOSSIER_DEV = os.path.dirname(os.path.abspath(__file__))
FICHIER_API = os.path.join(DOSSIER_DEV, "api_types_revit2024.txt")

ERREUR = "erreur"
AVERT = "avertissement"

# Lus par pyRevit ou IronPython : doivent etre en UTF-8.
EXT_UTF8 = (".py", ".yaml", ".yml", ".json", ".xaml")
# Seulement verifies pour les marqueurs de conflit.
EXT_TEXTE = EXT_UTF8 + (".md", ".txt", ".ini", ".csv")

# libgit2 (Update pyRevit) et git ecrivent toujours un libelle apres le
# marqueur, ce qui evite de confondre avec un trait "=======" de Markdown.
CONFLIT = re.compile(r"^(<{7}|>{7})( |$)", re.M)

# Copies de sauvegarde gardees a cote des script.py : pyRevit ne les execute
# pas, inutile d'y signaler des problemes.
SAUVEGARDE = re.compile(r"(?i)backup|ancien|_old\b")

CONTENEURS = (".tab", ".panel", ".pulldown", ".stack", ".splitbutton",
              ".splitpushbutton")
COMPOSANTS = CONTENEURS + (
    ".pushbutton", ".smartbutton", ".linkbutton", ".invokebutton",
    ".urlbutton", ".panelbutton", ".nobutton", ".content", ".combobox")
SEPARATEUR, SLIDEOUT = "---", ">>>"

CAN241_CHEMIN = re.compile(r"(?i)can[\s_-]*241|can\s+etayage")
CAN241_MODULE = re.compile(r"(?i)^can[\s_-]*241")

# Membres herites des fenetres WPF / WinForms et des classes .NET de base :
# lus sans etre assignes dans la classe Python, ce qui est normal.
HERITES = set("""
Close Show ShowDialog Hide Activate Dispatcher Title Width Height MinWidth
MinHeight MaxWidth MaxHeight Content Background ResizeMode Topmost
WindowStartupLocation Closing Closed Loaded IsEnabled Visibility DialogResult
Owner Resources FindName Controls Text Size ClientSize StartPosition
FormBorderStyle MaximizeBox MinimizeBox Font BackColor ForeColor AcceptButton
CancelButton Icon Refresh SuspendLayout ResumeLayout Invoke Left Top
""".split())

FENETRE = re.compile(r"XamlReader|WPFWindow|ShowDialog\s*\(|Windows\.Window\b"
                     r"|WinForms\.Form\b|\bForm\s*\)|make_footer\s*\(")
VERSION = re.compile(r"SCRIPT_VERSION|__version__|make_footer\s*\(")
MARQUE = re.compile(r"(?i)STR\s*BIM\s*Tools|make_footer\s*\(")
AUTEUR = re.compile(r"(?i)Tony\s+VARIN|make_footer\s*\(")


class Rapport(object):

    def __init__(self):
        self.lignes = []

    def ajouter(self, niveau, chemin, ligne, message):
        self.lignes.append((niveau, chemin, ligne or 0, message))

    def erreur(self, chemin, ligne, message):
        self.ajouter(ERREUR, chemin, ligne, message)

    def avert(self, chemin, ligne, message):
        self.ajouter(AVERT, chemin, ligne, message)

    def nombre(self, niveau):
        return sum(1 for l in self.lignes if l[0] == niveau)


# -----------------------------------------------------------------------------
# Fichiers
# -----------------------------------------------------------------------------

def lister_fichiers(racine):
    """Fichiers suivis par git, sinon tout le dossier hors dossiers caches."""
    try:
        sortie = subprocess.check_output(
            ["git", "-C", racine, "ls-files", "-z"],
            stderr=subprocess.DEVNULL)
        chemins = [c for c in sortie.decode("utf-8").split("\0") if c]
        if chemins:
            return sorted(c for c in chemins
                          if os.path.isfile(os.path.join(racine, c)))
    except (OSError, subprocess.CalledProcessError):
        pass
    chemins = []
    for dossier, sous, noms in os.walk(racine):
        sous[:] = [s for s in sous
                   if not s.startswith(".") and s != "__pycache__"]
        for nom in noms:
            chemin = os.path.relpath(os.path.join(dossier, nom), racine)
            chemins.append(chemin.replace(os.sep, "/"))
    return sorted(chemins)


def lire_textes(racine, chemins, rapport):
    textes = {}
    for chemin in chemins:
        ext = os.path.splitext(chemin)[1].lower()
        if ext not in EXT_TEXTE:
            continue
        with open(os.path.join(racine, chemin), "rb") as f:
            brut = f.read()
        try:
            texte = brut.decode("utf-8-sig")
        except UnicodeDecodeError as ex:
            if ext in EXT_UTF8:
                rapport.erreur(chemin, brut[:ex.start].count(b"\n") + 1,
                               "fichier non UTF-8 (enregistre en ANSI ?) : "
                               "pyRevit lira mal les accents")
            texte = brut.decode("latin-1")
        for m in CONFLIT.finditer(texte):
            rapport.erreur(chemin, texte[:m.start()].count("\n") + 1,
                           "marqueur de conflit git '{0}' : fusion ratee, "
                           "le fichier est casse".format(m.group(1)))
        textes[chemin] = texte
    return textes


# -----------------------------------------------------------------------------
# bundle.yaml, layouts et JSON
# -----------------------------------------------------------------------------

if yaml:
    class _ChargeurStrict(yaml.SafeLoader):
        pass

    def _mapping_sans_doublon(chargeur, noeud, deep=False):
        vues = set()
        for noeud_cle, _valeur in noeud.value:
            cle = chargeur.construct_object(noeud_cle, deep=deep)
            try:
                doublon = cle in vues
            except TypeError:
                continue
            if doublon:
                raise yaml.constructor.ConstructorError(
                    None, None, "cle en double : {0!r}".format(cle),
                    noeud_cle.start_mark)
            vues.add(cle)
        return chargeur.construct_mapping(noeud, deep)

    _ChargeurStrict.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_sans_doublon)


def nom_layout(element):
    """'Bouton[title:Autre titre]' -> 'Bouton', comme pyRevit."""
    m = re.match(r"(.+)\[(.+):(.*)\]", element)
    return m.group(1) if m else element


def verifier_yaml(chemins, textes, rapport):
    if yaml is None:
        print("NB : PyYAML absent, bundle.yaml non verifies "
              "(pip install pyyaml).")
        return
    for chemin, texte in sorted(textes.items()):
        if not chemin.lower().endswith((".yaml", ".yml")):
            continue
        try:
            donnees = yaml.load(texte, Loader=_ChargeurStrict)
        except yaml.YAMLError as ex:
            marque = getattr(ex, "problem_mark", None)
            ligne = marque.line + 1 if marque else 0
            detail = getattr(ex, "problem", None) or str(ex)
            rapport.erreur(chemin, ligne, "YAML invalide : {0} (pyRevit "
                           "plante au chargement)".format(detail))
            continue
        if os.path.basename(chemin) != "bundle.yaml":
            continue
        if not isinstance(donnees, dict):
            rapport.erreur(chemin, 1, "bundle.yaml doit contenir des "
                           "cles 'nom: valeur'")
            continue
        if "layout" in donnees:
            verifier_layout(chemins, chemin, donnees["layout"], texte,
                            rapport)


def verifier_layout(chemins, chemin, layout, texte, rapport):
    if not isinstance(layout, list) or not all(
            isinstance(e, str) for e in layout):
        rapport.erreur(chemin, ligne_de(texte, "layout"), "layout doit etre "
                       "une liste de noms ('- Nom du bouton')")
        return
    dossier = os.path.dirname(chemin)
    if not dossier.lower().endswith(CONTENEURS):
        return
    # Sous-dossiers d'apres les fichiers du depot, pas le disque : un dossier
    # local non suivi ne doit pas compter.
    enfants = []
    for autre in chemins:
        if not autre.startswith(dossier + "/"):
            continue
        nom = autre[len(dossier) + 1:].split("/")[0]
        base, ext = os.path.splitext(nom)
        if "/" in autre[len(dossier) + 1:] and ext.lower() in COMPOSANTS \
                and base not in enfants:
            enfants.append(base)
    noms = [nom_layout(e) for e in layout
            if SEPARATEUR not in e and SLIDEOUT not in e]
    for nom in noms:
        if nom not in enfants:
            rapport.avert(chemin, ligne_de(texte, nom),
                          "le layout cite '{0}' mais aucun dossier ne porte "
                          "ce nom".format(nom))
    for enfant in enfants:
        if enfant not in noms:
            rapport.avert(chemin, ligne_de(texte, "layout"),
                          "'{0}' absent du layout : il n'apparaitra pas dans "
                          "le ruban".format(enfant))


def verifier_json(textes, rapport):
    for chemin, texte in sorted(textes.items()):
        if not chemin.lower().endswith(".json"):
            continue
        try:
            json.loads(texte)
        except ValueError as ex:
            rapport.erreur(chemin, getattr(ex, "lineno", 0),
                           "JSON invalide : {0}".format(ex))


def ligne_de(texte, motif):
    i = texte.find(motif)
    return texte[:i].count("\n") + 1 if i >= 0 else 1


# -----------------------------------------------------------------------------
# Python
# -----------------------------------------------------------------------------

def analyser_python(textes, rapport):
    arbres = {}
    for chemin, texte in sorted(textes.items()):
        if not chemin.endswith(".py"):
            continue
        if SAUVEGARDE.search(os.path.basename(chemin)):
            continue
        if texte.startswith("#!") and "python3" in texte.split("\n", 1)[0]:
            continue  # moteur CPython : les regles IronPython ne s'appliquent pas
        # IronPython accepte DB.StorageType.None, Python 3 non : on renomme
        # l'attribut (meme longueur) pour pouvoir analyser le reste.
        source = re.sub(r"\.None\b", ".NONE", texte)
        try:
            arbres[chemin] = ast.parse(source)
        except SyntaxError as ex:
            rapport.avert(chemin, ex.lineno, "analyse detaillee impossible "
                          "({0}) ; la syntaxe est verifiee par l'etape "
                          "Python 2.7".format(ex.msg))
    return arbres


def verifier_syntaxe_py3(chemin, arbre, rapport):
    futur_print = any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__"
        and any(a.name == "print_function" for a in n.names)
        for n in arbre.body)

    def signaler(noeud, quoi):
        rapport.erreur(chemin, getattr(noeud, "lineno", 0),
                       "{0} : refuse par IronPython 2.7".format(quoi))

    for n in ast.walk(arbre):
        if isinstance(n, ast.JoinedStr):
            signaler(n, "f-string")
        elif isinstance(n, ast.arguments):
            if n.kwonlyargs or getattr(n, "posonlyargs", None):
                signaler(n.kwonlyargs[0] if n.kwonlyargs else n.posonlyargs[0],
                         "argument keyword-only ou positional-only")
            for a in n.args + n.kwonlyargs + [n.vararg, n.kwarg]:
                if a is not None and a.annotation is not None:
                    signaler(a, "annotation de type")
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.returns is not None:
                signaler(n, "annotation de type")
            if isinstance(n, ast.AsyncFunctionDef):
                signaler(n, "async def")
        elif isinstance(n, ast.AnnAssign):
            signaler(n, "annotation de type")
        elif isinstance(n, ast.Nonlocal):
            signaler(n, "nonlocal")
        elif isinstance(n, (ast.YieldFrom, ast.Await, ast.AsyncFor,
                            ast.AsyncWith)):
            signaler(n, "yield from / await")
        elif isinstance(n, ast.NamedExpr):
            signaler(n, "operateur :=")
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.MatMult):
            signaler(n, "operateur @")
        elif isinstance(n, ast.Raise) and n.cause is not None:
            signaler(n, "raise ... from ...")
        elif isinstance(n, ast.Starred) and isinstance(n.ctx, ast.Store):
            signaler(n, "affectation etoilee (a, *b = ...)")
        elif isinstance(n, (ast.List, ast.Tuple, ast.Set)) and isinstance(
                n.ctx if hasattr(n, "ctx") else ast.Load(), ast.Load) and any(
                    isinstance(e, ast.Starred) for e in n.elts):
            signaler(n, "depliage *x dans une liste")
        elif isinstance(n, ast.Dict) and None in n.keys:
            signaler(n, "depliage **x dans un dictionnaire")
        elif isinstance(n, ast.Call):
            if sum(isinstance(a, ast.Starred) for a in n.args) > 1 or sum(
                    k.arg is None for k in n.keywords) > 1:
                signaler(n, "plusieurs *args ou **kwargs dans un appel")
            if isinstance(n.func, ast.Name):
                if n.func.id == "super" and not n.args:
                    signaler(n, "super() sans argument")
                if (n.func.id == "print" and n.keywords
                        and not futur_print):
                    signaler(n, "print(..., end=/sep=/file=) sans 'from "
                             "__future__ import print_function'")
        elif hasattr(ast, "Match") and isinstance(n, ast.Match):
            signaler(n, "match / case")


def contextes_try(arbre):
    """Noeud -> 'try' (dans un try), 'secours' (dans un except) ou absent."""
    contexte = {}

    def visiter(noeud, etat):
        if etat:
            contexte[noeud] = etat
        if isinstance(noeud, ast.Try) or type(noeud).__name__ == "TryStar":
            for enfant in noeud.body:
                visiter(enfant, etat or "try")
            for gestion in noeud.handlers:
                for enfant in gestion.body:
                    visiter(enfant, "secours")
            for enfant in noeud.orelse + noeud.finalbody:
                visiter(enfant, etat)
            return
        for enfant in ast.iter_child_nodes(noeud):
            visiter(enfant, etat)

    visiter(arbre, None)
    return contexte


def charger_api():
    api = {}
    if not os.path.isfile(FICHIER_API):
        return api
    for ligne in io.open(FICHIER_API, encoding="utf-8-sig"):
        ligne = ligne.strip()
        if "|" in ligne:
            ns, nom = ligne.split("|", 1)
            api.setdefault(ns, set()).add(nom)
    return api


def verifier_api_revit(chemin, arbre, api, rapport):
    if not api:
        return
    contexte = contextes_try(arbre)

    def signaler(noeud, message):
        etat = contexte.get(noeud)
        if etat == "secours":
            return  # repli volontaire pour une autre version de Revit
        if etat == "try":
            rapport.avert(chemin, noeud.lineno, message + " (dans un try : "
                          "cette branche echouera toujours)")
        else:
            rapport.erreur(chemin, noeud.lineno, message)

    def ailleurs(nom):
        ns = sorted(n for n, noms in api.items() if nom in noms)
        return " (present dans " + ", ".join(ns) + ")" if ns else \
            " (introuvable dans l'API Revit 2024)"

    # alias local -> namespace Revit (from Autodesk.Revit import DB, ...)
    alias = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module and \
                n.module.startswith("Autodesk.Revit"):
            for a in n.names:
                if a.name == "*":
                    continue
                complet = n.module + "." + a.name
                if complet in api:
                    alias[a.asname or a.name] = complet
                    continue
                if n.module not in api:
                    signaler(n, "namespace Revit inconnu : " + n.module)
                elif a.name not in api[n.module]:
                    signaler(n, "{0} absent de {1}{2}".format(
                        a.name, n.module, ailleurs(a.name)))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in api and a.asname:
                    alias[a.asname] = a.name

    def namespace_de(noeud):
        if isinstance(noeud, ast.Name):
            return alias.get(noeud.id)
        if isinstance(noeud, ast.Attribute):
            parent = namespace_de(noeud.value)
            if parent and parent + "." + noeud.attr in api:
                return parent + "." + noeud.attr
        return None

    for n in ast.walk(arbre):
        if not isinstance(n, ast.Attribute):
            continue
        ns = namespace_de(n.value)
        if not ns or n.attr in api[ns] or ns + "." + n.attr in api:
            continue
        signaler(n, "{0}.{1} n'existe pas{2}".format(
            ns.rsplit(".", 1)[-1], n.attr, ailleurs(n.attr)))


def noms_publics(arbre):
    """Noms visibles d'un module, None si impossible a savoir (import *)."""
    trouves = set()

    def parcourir(corps):
        for noeud in corps:
            if isinstance(noeud, (ast.FunctionDef, ast.ClassDef)):
                trouves.add(noeud.name)
            elif isinstance(noeud, (ast.Assign, ast.AugAssign, ast.AnnAssign,
                                    ast.For, ast.With)):
                for cible in ast.walk(noeud):
                    if isinstance(cible, ast.Name) and isinstance(
                            cible.ctx, ast.Store):
                        trouves.add(cible.id)
            elif isinstance(noeud, (ast.Import, ast.ImportFrom)):
                for a in noeud.names:
                    if a.name == "*":
                        raise ValueError
                    trouves.add(a.asname or a.name.split(".")[0])
            for champ in ("body", "orelse", "finalbody"):
                if not isinstance(noeud, (ast.FunctionDef, ast.ClassDef)):
                    parcourir(getattr(noeud, champ, []) or [])
            for gestion in getattr(noeud, "handlers", []) or []:
                parcourir(gestion.body)

    try:
        parcourir(arbre.body)
    except ValueError:
        return None
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Global):
            trouves.update(noeud.names)
        elif isinstance(noeud, ast.FunctionDef) and noeud.name == \
                "__getattr__" and noeud in arbre.body:
            return None
    return trouves


def verifier_modules_lib(arbres, modules, rapport):
    for chemin, arbre in sorted(arbres.items()):
        courant = os.path.splitext(os.path.basename(chemin))[0]
        locaux = {}
        for n in ast.walk(arbre):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name in modules and a.name != courant:
                        locaux[a.asname or a.name] = a.name
        for n in ast.walk(arbre):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id in locaux):
                module = locaux[n.value.id]
                if modules[module] is not None and \
                        n.attr not in modules[module] and \
                        not n.attr.startswith("__"):
                    rapport.erreur(chemin, n.lineno, "{0}.{1} n'existe pas "
                                   "dans lib/{0}.py".format(module, n.attr))


def verifier_attributs(chemin, arbre, rapport):
    for classe in [n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)]:
        assignes, methodes, lus = set(), set(), {}
        for noeud in classe.body:
            if isinstance(noeud, ast.Assign):
                for cible in noeud.targets:
                    if isinstance(cible, ast.Name):
                        assignes.add(cible.id)
        for noeud in ast.walk(classe):
            if isinstance(noeud, ast.FunctionDef):
                methodes.add(noeud.name)
            if (isinstance(noeud, ast.Attribute)
                    and isinstance(noeud.value, ast.Name)
                    and noeud.value.id == "self"):
                if isinstance(noeud.ctx, (ast.Store, ast.Del)):
                    assignes.add(noeud.attr)
                else:
                    lus.setdefault(noeud.attr, noeud.lineno)
            # setattr(self, "nom", ...)
            if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
                    and noeud.func.id == "setattr" and len(noeud.args) > 1
                    and isinstance(noeud.args[1], ast.Constant)):
                assignes.add(noeud.args[1].value)
        for attr, ligne in sorted(lus.items(), key=lambda kv: kv[1]):
            if attr not in assignes and attr not in methodes and \
                    attr not in HERITES:
                rapport.avert(chemin, ligne, "self.{0} lu mais jamais assigne "
                              "dans {1}".format(attr, classe.name))


def verifier_xaml(chemin, texte, debut, rapport):
    """debut : numero de la ligne ou commence le texte XAML."""
    for i, car in enumerate(texte):
        if ord(car) > 127:
            rapport.avert(chemin, debut + texte[:i].count("\n"),
                          "caractere non ASCII '{0}' dans le XAML (convention "
                          "STR BIM Tools : texte accentue mis apres le "
                          "chargement)".format(car))
            break
    propre = texte.strip()
    if propre.startswith("<") and propre.endswith(">"):
        try:
            ET.fromstring(propre)
        except ET.ParseError as ex:
            ligne, _col = ex.position
            decalage = len(texte) - len(texte.lstrip())
            rapport.erreur(chemin, debut + texte[:decalage].count("\n")
                           + ligne - 1, "XAML mal forme : {0}".format(ex))


def verifier_xaml_python(chemin, arbre, rapport):
    for n in ast.walk(arbre):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                "xmlns" in n.value and "<" in n.value:
            verifier_xaml(chemin, n.value, n.lineno, rapport)


def verifier_conventions(chemin, texte, rapport):
    if os.path.basename(chemin) != "script.py" or not FENETRE.search(texte):
        return
    manque = [libelle for libelle, motif in (
        ("la version (SCRIPT_VERSION)", VERSION),
        ("'STR BIM Tools'", MARQUE),
        ("'Tony VARIN'", AUTEUR)) if not motif.search(texte)]
    if manque:
        rapport.avert(chemin, 1, "la fenetre doit afficher " +
                      ", ".join(manque))


def verifier_can241(chemins, arbres, rapport):
    for chemin in chemins:
        if CAN241_CHEMIN.search(chemin):
            rapport.erreur(chemin, 0, "fichier CAN 241 dans le depot public : "
                           "il doit aller dans STR-BIM-Tools-CAN241")
    for chemin, arbre in sorted(arbres.items()):
        for n in ast.walk(arbre):
            modules = []
            if isinstance(n, ast.Import):
                modules = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                modules = [n.module]
            for module in modules:
                if CAN241_MODULE.search(module):
                    rapport.erreur(chemin, n.lineno, "import de {0} dans le "
                                   "depot public".format(module))


# -----------------------------------------------------------------------------
# Sortie
# -----------------------------------------------------------------------------

def _echapper(valeur, propriete=False):
    valeur = str(valeur).replace("%", "%25").replace("\r", "%0D") \
        .replace("\n", "%0A")
    if propriete:
        valeur = valeur.replace(":", "%3A").replace(",", "%2C")
    return valeur


def publier(rapport, nb_fichiers):
    lignes = sorted(rapport.lignes, key=lambda l: (l[0] != ERREUR, l[1], l[2]))
    nb_err, nb_av = rapport.nombre(ERREUR), rapport.nombre(AVERT)
    for niveau, chemin, ligne, message in lignes:
        print("  {0:<13} {1}{2} -> {3}".format(
            niveau.upper(), chemin, ":" + str(ligne) if ligne else "",
            message))
    print("")
    print("{0} fichiers controles : {1} erreur(s), {2} avertissement(s)."
          .format(nb_fichiers, nb_err, nb_av))

    if os.environ.get("GITHUB_ACTIONS"):
        for niveau, chemin, ligne, message in lignes:
            print("::{0} file={1},line={2},title={3}::{4}".format(
                "error" if niveau == ERREUR else "warning",
                _echapper(chemin, True), max(ligne, 1),
                _echapper("STR BIM Tools", True), _echapper(message)))
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with io.open(resume, "a", encoding="utf-8") as f:
            f.write(u"## Controle STR BIM Tools : {0} erreur(s), {1} "
                    u"avertissement(s)\n\n".format(nb_err, nb_av))
            if not lignes:
                f.write(u"Tout est en ordre ({0} fichiers).\n".format(
                    nb_fichiers))
                return
            f.write(u"| | Fichier | Ligne | Probleme |\n|---|---|---|---|\n")
            for niveau, chemin, ligne, message in lignes[:300]:
                f.write(u"| {0} | `{1}` | {2} | {3} |\n".format(
                    u"❌" if niveau == ERREUR else u"⚠️",
                    chemin, ligne or u"", message.replace(u"|", u"\\|")))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--racine", default=os.path.dirname(DOSSIER_DEV),
                        help="dossier du depot a controler")
    parser.add_argument("--lib", action="append", default=[],
                        help="dossier lib/ supplementaire (modules partages)")
    parser.add_argument("--depot-public", action="store_true",
                        help="interdit tout fichier ou import CAN 241")
    args = parser.parse_args()
    racine = os.path.abspath(args.racine)

    rapport = Rapport()
    chemins = lister_fichiers(racine)
    textes = lire_textes(racine, chemins, rapport)
    verifier_yaml(chemins, textes, rapport)
    verifier_json(textes, rapport)

    arbres = analyser_python(textes, rapport)
    modules = {}
    for dossier in [os.path.join(racine, "lib")] + args.lib:
        if not os.path.isdir(dossier):
            continue
        for nom in os.listdir(dossier):
            if nom.endswith(".py"):
                with io.open(os.path.join(dossier, nom),
                             encoding="utf-8-sig") as f:
                    try:
                        arbre = ast.parse(re.sub(r"\.None\b", ".NONE",
                                                 f.read()))
                    except SyntaxError:
                        continue
                modules.setdefault(nom[:-3], noms_publics(arbre))
    api = charger_api()
    if not api:
        print("NB : api_types_revit2024.txt absent, imports Revit non "
              "verifies.")
    for chemin, arbre in sorted(arbres.items()):
        verifier_syntaxe_py3(chemin, arbre, rapport)
        verifier_api_revit(chemin, arbre, api, rapport)
        verifier_attributs(chemin, arbre, rapport)
        verifier_xaml_python(chemin, arbre, rapport)
        verifier_conventions(chemin, textes[chemin], rapport)
    verifier_modules_lib(arbres, modules, rapport)
    for chemin, texte in sorted(textes.items()):
        if chemin.lower().endswith(".xaml"):
            verifier_xaml(chemin, texte, 1, rapport)
    if args.depot_public:
        verifier_can241(chemins, arbres, rapport)

    publier(rapport, len(chemins))
    return 1 if rapport.nombre(ERREUR) else 0


if __name__ == "__main__":
    sys.exit(main())
