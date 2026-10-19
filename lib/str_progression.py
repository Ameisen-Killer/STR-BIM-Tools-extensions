# -*- coding: utf-8 -*-
# =============================================================================
# str_progression.py - Fenetre de progression commune aux outils STR BIM Tools.
# (Copie publique de can241_progress, qui reste dans le depot prive CAN 241 :
#  meme classe Progression, meme usage.)
#
# Remplace les barres "IsIndeterminate" (qui defilaient sans rien dire) par une
# VRAIE progression de 0 a 100 % : l'appelant annonce un total, puis appelle
# avancer() a chaque iteration.
#
# Le rafraichissement est amorti par la classe elle-meme : avancer() peut etre
# appele a chaque element sans cout notable, l'affichage n'est repeint qu'un
# nombre borne de fois (PAS_MAX). L'appelant n'a plus a ecrire de « if n % 25 ».
#
# Ce module DEPEND de WPF (pas de l'API Revit). IronPython 2.7 compatible.
# =============================================================================

PAS_MAX = 150          # nombre maximal de repeints sur toute la progression
LARGEUR = 420
HAUTEUR = 150

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
import System.Windows as SW
from System.Windows import (Window, Thickness, WindowStartupLocation, ResizeMode)
from System.Windows.Controls import StackPanel, TextBlock, ProgressBar
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Threading import DispatcherPriority


def _brush(h):
    h = h.lstrip("#")
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16),
                                         int(h[4:6], 16)))


class Progression(object):
    """Fenetre de progression a barre determinee.

        p = Progression(u"Lecture de la maquette...", _FOOTER)
        p.demarrer(total)                 # total connu -> barre 0-100 %
        for i, el in enumerate(elements, 1):
            ...
            p.avancer(i, u"{} éléments lus...".format(n_retenus))
        p.fin()

    Un total nul ou inconnu retombe sur une barre indeterminee : mieux vaut
    une barre qui defile qu'un pourcentage invente.
    """

    def __init__(self, titre, footer=u"", total=0):
        self.total = 0
        self._valeur = 0
        self._dernier = -1
        self._pas = 1
        self._ouverte = False

        win = Window()
        win.Title = titre
        win.Width = LARGEUR
        win.Height = HAUTEUR
        win.ResizeMode = ResizeMode.NoResize
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen
        win.Background = _brush("#FFFFFF")

        sp = StackPanel()
        sp.Margin = Thickness(16, 14, 16, 10)
        win.Content = sp

        lbl = TextBlock()
        lbl.Margin = Thickness(0, 0, 0, 8)
        sp.Children.Add(lbl)

        pb = ProgressBar()
        pb.Height = 18
        pb.Minimum = 0
        pb.Maximum = 100
        pb.Value = 0
        pb.IsIndeterminate = True      # jusqu'au demarrer(total)
        sp.Children.Add(pb)

        pct = TextBlock()
        pct.FontSize = 10
        pct.Margin = Thickness(0, 4, 0, 0)
        pct.HorizontalAlignment = SW.HorizontalAlignment.Right
        pct.Foreground = _brush("#2F6496")
        sp.Children.Add(pct)

        ftr = TextBlock()
        ftr.Text = footer or u""
        ftr.FontSize = 9
        ftr.Foreground = _brush("#888888")
        ftr.Margin = Thickness(0, 6, 0, 0)
        ftr.HorizontalAlignment = SW.HorizontalAlignment.Right
        sp.Children.Add(ftr)

        self.win = win
        self.lbl = lbl
        self.bar = pb
        self.pct = pct
        if total:
            self._fixer_total(total)

    # --- cycle de vie ---------------------------------------------------------
    def _fixer_total(self, total):
        try:
            total = int(total or 0)
        except Exception:
            total = 0
        self.total = max(total, 0)
        if self.total > 0:
            self.bar.IsIndeterminate = False
            self.bar.Maximum = self.total
            self.bar.Value = 0
            self._pas = max(1, self.total // PAS_MAX)
        else:
            self.bar.IsIndeterminate = True
            self._pas = 1

    def demarrer(self, total=None, texte=None):
        """Affiche la fenetre. `total` fixe (ou re-fixe) l'echelle de la barre."""
        if total is not None:
            self._fixer_total(total)
        if texte:
            self.lbl.Text = texte
        if not self._ouverte:
            self.win.Show()
            self._ouverte = True
        self._repeindre(force=True)
        return self

    def fin(self):
        try:
            self.win.Close()
        except Exception:
            pass
        self._ouverte = False

    # compatibilite « with » : le bloc protege la fermeture
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.fin()
        return False

    # --- progression ----------------------------------------------------------
    def avancer(self, valeur=None, texte=None):
        """Porte la progression a `valeur` (ou +1 si None) et rafraichit si
        le pas d'amortissement est atteint. `texte` remplace le libelle."""
        if valeur is None:
            self._valeur += 1
        else:
            try:
                self._valeur = int(valeur)
            except Exception:
                self._valeur += 1
        if texte is not None:
            self._texte = texte
        else:
            self._texte = getattr(self, "_texte", None)
        fini = self.total > 0 and self._valeur >= self.total
        recul = self._valeur < self._dernier      # jamais en usage normal,
        # mais un compteur qui redescend doit se voir tout de suite plutot
        # que de laisser la barre figee sur l'ancienne valeur
        if fini or recul or self._valeur - self._dernier >= self._pas:
            self._repeindre()

    def etape(self, texte, valeur=None):
        """Change le libelle (et eventuellement la valeur) et repeint tout de
        suite : pour les traitements en quelques grandes etapes."""
        self._texte = texte
        if valeur is not None:
            try:
                self._valeur = int(valeur)
            except Exception:
                pass
        self._repeindre(force=True)

    def sous_total(self, total):
        """Repart de zero sur une nouvelle echelle (2e passe d'un traitement)."""
        self._valeur = 0
        self._dernier = -1
        self._fixer_total(total)
        self._repeindre(force=True)

    # --- affichage ------------------------------------------------------------
    def _repeindre(self, force=False):
        self._dernier = self._valeur
        txt = getattr(self, "_texte", None)
        if txt:
            self.lbl.Text = txt
        if self.total > 0:
            v = min(max(self._valeur, 0), self.total)
            self.bar.Value = v
            self.pct.Text = u"{:.0f} %   ({} / {})".format(
                100.0 * v / self.total, v, self.total)
        else:
            self.pct.Text = u""
        self._do_events()

    def _do_events(self):
        try:
            self.win.Dispatcher.Invoke(System.Action(lambda: None),
                                       DispatcherPriority.Background)
        except Exception:
            pass
