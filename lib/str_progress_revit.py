# -*- coding: utf-8 -*-
# =============================================================================
# str_progress_revit.py - Progression reelle des exports Revit.
#
# Les API d'export de Revit (doc.Export en IFC, PDF, DWG...) sont des appels
# BLOQUANTS : ils ne rendent la main qu'a la fin et ne renvoient aucun
# avancement. Mais l'exporteur publie sa progression sur l'evenement
# Application.ProgressChanged - le flux qui alimente la barre d'etat de Revit.
#
# Ce module fait le pont entre cet evenement et une fenetre de progression
# (typiquement str_progress_sta.ProgressionSTA, qui vit sur son propre thread
# STA et reste donc peinte pendant que Revit travaille).
#
#     prog  = str_progress_sta.ProgressionSTA(total, TOOL_NAME, SCRIPT_VERSION)
#     suivi = str_progress_revit.SuiviProgressionRevit(prog, app)
#     suivi.brancher()
#     try:
#         ...  # boucle d'export
#     finally:
#         suivi.debrancher()
#         prog.fermer()
#
# La cible doit exposer une methode avancement(fraction, phase=None).
# Compatible Revit 2024+, IronPython 2.7 et 3.4.
# =============================================================================

import clr

clr.AddReference("RevitAPI")

import System

# Import defensif : un mecanisme d'affichage ne doit jamais pouvoir empecher
# l'outil qui l'utilise de demarrer.
try:
    from Autodesk.Revit.DB.Events import ProgressChangedEventArgs
    EVENEMENT_DISPONIBLE = True
except ImportError:
    ProgressChangedEventArgs = None
    EVENEMENT_DISPONIBLE = False


# Intervalle minimal entre deux traitements de l'evenement, en millisecondes.
#
# CRITIQUE POUR LA PERFORMANCE : ProgressChanged se declenche a chaque element
# traite, soit des centaines de milliers de fois sur un gros export. Le handler
# s'execute sur le thread de Revit, SYNCHRONIQUEMENT : l'exporteur attend qu'il
# rende la main a chaque tic. Sans ce garde-fou, la traversee .NET -> IronPython
# repetee ralentit l'export de facon tres sensible. Amortir le seul repeint de
# la fenetre ne suffit pas : c'est l'appel lui-meme qu'il faut ecarter, le plus
# tot et le plus platement possible.
INTERVALLE_MS = 150


class SuiviProgressionRevit(object):
    """
    Relaie la progression publiee par Revit vers une fenetre de progression.

    ATTENTION : un export enchaine PLUSIEURS plages de progression, une par
    phase de travail. Le pourcentage repart donc de zero a chaque phase,
    exactement comme dans la barre d'etat de Revit. La phase en cours est
    transmise avec la fraction pour que ce comportement reste lisible.
    """

    def __init__(self, cible, application, intervalle_ms=INTERVALLE_MS):
        self._cible = cible
        self._app = application
        self._delegue = None
        self._intervalle = int(intervalle_ms)
        self._dernier_tic = 0
        self.messages = []

    @property
    def branche(self):
        return self._delegue is not None

    def brancher(self):
        """Abonne au flux de progression. Sans effet si l'API est absente."""
        if not EVENEMENT_DISPONIBLE:
            self.messages.append(u"Progression detaillee indisponible : "
                                 u"ProgressChangedEventArgs absent.")
            return
        try:
            self._delegue = System.EventHandler[ProgressChangedEventArgs](
                self._sur_progression)
            self._app.ProgressChanged += self._delegue
        except Exception as ex:
            self._delegue = None
            self.messages.append(
                u"Progression detaillee indisponible : {0}".format(ex))

    def debrancher(self):
        """Se desabonne. Idempotent, ne leve jamais."""
        if self._delegue is None:
            return
        try:
            self._app.ProgressChanged -= self._delegue
        except Exception:
            pass
        self._delegue = None

    def _sur_progression(self, sender, args):
        # Premiere instruction : sortir sans rien lire dans le cas courant.
        # TickCount est une simple lecture d'entier, bien moins couteuse que la
        # lecture des proprietes de l'evenement et que l'appel a la cible.
        tic = System.Environment.TickCount
        if tic - self._dernier_tic < self._intervalle:
            return
        self._dernier_tic = tic
        try:
            bas = args.LowerRange
            haut = args.UpperRange
            if haut <= bas:
                return
            fraction = float(args.Position - bas) / float(haut - bas)
            try:
                phase = args.Caption or None
            except Exception:
                phase = None
            self._cible.avancement(fraction, phase)
        except Exception:
            # Une exception qui remonte depuis un handler d'evenement pendant un
            # export bloquant ferait echouer l'export : ne jamais la laisser
            # sortir d'ici.
            pass
