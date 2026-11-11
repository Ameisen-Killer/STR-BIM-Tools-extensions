# -*- coding: utf-8 -*-
"""Chronometrage des outils STR BIM Tools (IronPython 2.7, Revit 2024+).

But : savoir OU part le temps d'un outil avant de l'optimiser. Chaque
lancement ajoute ses mesures a un fichier CSV unique par poste :

    %APPDATA%\\STR BIM Tools\\chronometrage.csv

Une ligne par mesure : date ; outil ; version ; maquette ; mesure ; type ;
duree_s ; appels. Le fichier s'ouvre dans Excel (separateur « ; »).

Deux sortes de mesures :
  - les ETAPES, sequentielles : etape("Calcul") ferme l'etape en cours et en
    ouvre une nouvelle ; fin() ferme la derniere et ecrit le fichier ;
  - les CUMULS, pour une fonction appelee des milliers de fois au milieu
    d'une boucle : f = chrono.mesurer("Géométrie", f) l'enveloppe et additionne
    son temps et son nombre d'appels. Temps INCLUSIF : une fonction mesuree
    qui en appelle une autre compte aussi le temps de celle-ci.

    ch = str_chrono.Chrono(TOOL_NAME, SCRIPT_VERSION, doc)
    get_area = ch.mesurer(u"Surface", get_area)
    ch.etape(u"Collecte")
    ...
    ch.etape(u"Calcul")
    ...
    ch.compter(u"Éléments analysés", n)
    ch.fin()

Rien ici ne doit jamais faire echouer l'outil mesure : toute erreur
(fichier ouvert dans Excel, dossier en lecture seule...) est avalee et fin()
retourne simplement None.
"""

import io
import os
import datetime

try:
    from System.Diagnostics import Stopwatch
    _FREQ = float(Stopwatch.Frequency)

    def _maintenant():
        # Horloge haute resolution : time.time() n'avance que par pas de
        # ~15 ms sous Windows, ce qui fausserait les cumuls de fonctions
        # appelees des milliers de fois.
        return Stopwatch.GetTimestamp() / _FREQ
except Exception:          # hors Revit (controle automatique, tests)
    import time

    def _maintenant():
        return time.time()


DOSSIER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                       u"STR BIM Tools")
FICHIER = os.path.join(DOSSIER, u"chronometrage.csv")
ENTETE = u"date;outil;version;maquette;mesure;type;duree_s;appels\n"


def _titre(doc):
    try:
        return doc.Title or u""
    except Exception:
        return u""


def _champ(txt):
    """Texte sur une seule cellule CSV : pas de « ; » ni de saut de ligne."""
    try:
        t = u"{}".format(txt)
    except Exception:
        t = u"?"
    return t.replace(u";", u",").replace(u"\r", u" ").replace(u"\n", u" ")


class Chrono(object):
    """Mesures d'un lancement d'outil, ecrites en fin de traitement."""

    def __init__(self, outil, version, doc=None):
        self.outil = outil
        self.version = version
        self.maquette = _titre(doc)
        self._lignes = []         # [mesure, type, duree_s, appels]
        self._cumuls = []         # [nom, [duree_s, appels]] dans l'ordre
        self._etape = None
        self._t0 = None
        self._debut = None

    # -- etapes ----------------------------------------------------------------
    def etape(self, nom):
        """Ferme l'etape en cours et demarre l'etape `nom`."""
        try:
            self._clore()
            self._etape = nom
            self._t0 = _maintenant()
            if self._debut is None:
                self._debut = self._t0
        except Exception:
            pass

    def _clore(self):
        if self._etape is not None:
            self._lignes.append([self._etape, u"étape",
                                 _maintenant() - self._t0, 1])
            self._etape = None

    # -- compteurs -------------------------------------------------------------
    def compter(self, nom, valeur):
        """Volume traite (nombre d'elements, de points...) : donne l'echelle
        sans laquelle une duree ne veut rien dire d'un modele a l'autre."""
        try:
            self._lignes.append([nom, u"compte", None, int(valeur)])
        except Exception:
            pass

    # -- cumuls ----------------------------------------------------------------
    def mesurer(self, nom, fn):
        """Enveloppe `fn` pour cumuler son temps et son nombre d'appels.
        Plusieurs fonctions peuvent partager le meme `nom`."""
        cumul = None
        for n, c in self._cumuls:
            if n == nom:
                cumul = c
                break
        if cumul is None:
            cumul = [0.0, 0]
            self._cumuls.append([nom, cumul])

        def enveloppe(*args, **kwargs):
            t = _maintenant()
            try:
                return fn(*args, **kwargs)
            finally:
                cumul[0] += _maintenant() - t
                cumul[1] += 1
        try:
            enveloppe.__name__ = fn.__name__
            enveloppe.__doc__ = fn.__doc__
        except Exception:
            pass
        return enveloppe

    # -- ecriture --------------------------------------------------------------
    def fin(self):
        """Ferme l'etape en cours et ajoute les mesures au fichier CSV, puis
        remet les compteurs a zero : un outil qui reste ouvert et relance son
        calcul (bouton « Exporter » clique deux fois) ecrit deux series
        distinctes avec le meme objet. Un appel sans nouvelle mesure n'ecrit
        rien. Retourne le chemin du fichier, ou None."""
        try:
            self._clore()
            lignes = list(self._lignes)
            for nom, cumul in self._cumuls:
                if cumul[1]:
                    lignes.append([nom, u"cumul", cumul[0], cumul[1]])
            if self._debut is not None:
                lignes.append([u"TOTAL", u"total",
                               _maintenant() - self._debut, 1])
            # remise a zero en place : les enveloppes de mesurer() gardent
            # une reference sur leur liste de cumul
            self._lignes = []
            self._debut = None
            for _nom, cumul in self._cumuls:
                cumul[0] = 0.0
                cumul[1] = 0
            if not lignes:
                return None
            date = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
            if not os.path.isdir(DOSSIER):
                os.makedirs(DOSSIER)
            nouveau = not os.path.isfile(FICHIER)
            with io.open(FICHIER, "a", encoding="utf-8") as f:
                if nouveau:
                    f.write(u"﻿" + ENTETE)   # BOM : accents lus par Excel
                for mesure, typ, duree, appels in lignes:
                    f.write(u";".join([
                        date, _champ(self.outil), _champ(self.version),
                        _champ(self.maquette), _champ(mesure), typ,
                        u"" if duree is None else u"{:.3f}".format(duree),
                        u"{}".format(appels)]) + u"\n")
            return FICHIER
        except Exception:
            return None
