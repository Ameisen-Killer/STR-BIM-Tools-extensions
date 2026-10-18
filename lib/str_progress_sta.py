# -*- coding: utf-8 -*-
# =============================================================================
# str_progress_sta.py - Fenetre de progression sur thread STA dedie.
#
# A utiliser quand l'operation BLOQUE le thread principal de Revit (doc.Export,
# doc.Print...) : la fenetre vit sur son propre thread STA avec sa propre boucle
# de messages, elle reste donc peinte et reactive pendant que Revit travaille.
# Pour les boucles Python ordinaires, preferer can241_progress (plus simple).
#
# Corrige trois defauts de l'implementation locale precedente :
#   - un SEUL thread de chronometre, arme par un evenement interruptible
#     (l'ancien code creait un thread par element et les fuyait) ;
#   - attente de demarrage bornee (l'ancien Wait() sans delai figeait Revit
#     definitivement si la construction de la fenetre levait une exception) ;
#   - bouton Annuler : l'appelant interroge .annulation_demandee entre deux
#     elements et s'arrete proprement.
#
# Ce module DEPEND de WPF (pas de l'API Revit). IronPython 2.7 compatible.
# =============================================================================

import time

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
import System.Windows as SW
from System.Threading import ApartmentState, ManualResetEventSlim, Thread, ThreadStart
from System.Windows import Thickness, Window
from System.Windows.Controls import Grid, ProgressBar, StackPanel
from System.Windows.Threading import Dispatcher, DispatcherPriority

import str_ui


DELAI_DEMARRAGE_MS = 10000   # au-dela, on renonce a la fenetre plutot que figer
DELAI_FERMETURE_MS = 3000

# Une operation bloquante (doc.Export, doc.Print) n'est pas interruptible :
# l'annulation ne peut etre prise en compte qu'entre deux elements.
MSG_ANNULATION = (u"Annulation demandee : le fichier en cours se termine "
                  u"normalement (cela peut prendre plusieurs minutes), "
                  u"puis l'export s'arrete.")


class ProgressionSTA(object):
    """
    Fenetre de progression a deux niveaux (global + element courant).

        prog = ProgressionSTA(len(vues), u"Export IFC", SCRIPT_VERSION)
        try:
            for i, v in enumerate(vues, 1):
                if prog.annulation_demandee:
                    break
                prog.debut_element(v.Name, i - 1)
                ...            # operation bloquante
                prog.fin_element(i)
        finally:
            prog.fermer()

    Toutes les methodes publiques sont appelables depuis le thread Revit.
    """

    def __init__(self, total, titre, version, annulable=True, topmost=True):
        """
        topmost : garder la fenetre au premier plan. A mettre a False quand
        l'appelant ouvre des boites de dialogue PENDANT sa boucle (confirmation
        d'ecrasement...). Une fenetre topmost appartenant a un autre thread
        passe DEVANT une MessageBox modale : l'utilisateur ne voit pas la
        question, le traitement semble fige alors qu'il attend un clic.
        """
        self._total = max(1, int(total))
        self._titre = titre
        self._version = version
        self._annulable = annulable
        self._topmost = topmost
        self._faits = 0
        self._pct = None      # None = progression reelle pas encore recue

        self._fenetre = None
        self._dispatcher = None
        self._pret = ManualResetEventSlim(False)
        self._arret = ManualResetEventSlim(False)
        self._annule = False
        self._ferme = False
        self._erreur_demarrage = None

        self._debut_global = time.time()
        self._debut_element = None

        self._thread = Thread(ThreadStart(self._boucle_fenetre))
        self._thread.SetApartmentState(ApartmentState.STA)
        self._thread.IsBackground = True
        self._thread.Start()
        # Borne l'attente : une fenetre qui ne s'ouvre pas ne doit jamais
        # bloquer Revit. L'export continuera simplement sans progression.
        self._pret.Wait(DELAI_DEMARRAGE_MS)

        self._thread_chrono = Thread(ThreadStart(self._boucle_chrono))
        self._thread_chrono.IsBackground = True
        self._thread_chrono.Start()

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------
    @property
    def disponible(self):
        """False si la fenetre n'a pas pu s'ouvrir (l'appelant continue quand meme)."""
        return self._dispatcher is not None

    @property
    def annulation_demandee(self):
        return self._annule

    @property
    def erreur_demarrage(self):
        return self._erreur_demarrage

    # ------------------------------------------------------------------
    # Construction (thread STA dedie)
    # ------------------------------------------------------------------
    def _boucle_fenetre(self):
        try:
            self._construire()
            self._fenetre.Show()
        except Exception as ex:
            self._erreur_demarrage = u"{0}".format(ex)
            self._dispatcher = None
            self._pret.Set()
            return
        self._pret.Set()
        Dispatcher.Run()   # tourne jusqu'a InvokeShutdown()

    def _construire(self):
        win = Window()
        win.Title = self._titre
        win.Width = 540
        win.Height = 290 if self._annulable else 250
        win.ResizeMode = SW.ResizeMode.NoResize
        win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        win.Background = str_ui.couleur("fond")
        win.Topmost = self._topmost

        racine = Grid()
        for h in ["*", "Auto"]:
            racine.RowDefinitions.Add(str_ui.rd(h))
        win.Content = racine

        corps = StackPanel()
        corps.Margin = Thickness(20, 16, 20, 8)
        Grid.SetRow(corps, 0)
        racine.Children.Add(corps)

        # --- Progression globale ---
        corps.Children.Add(str_ui.texte(u"Progression globale", gras=True,
                                        brush=str_ui.couleur("titre"),
                                        marge=Thickness(0, 0, 0, 4)))

        self._barre_globale = ProgressBar()
        self._barre_globale.Minimum = 0
        self._barre_globale.Maximum = self._total
        self._barre_globale.Value = 0
        self._barre_globale.Height = 18
        self._barre_globale.Margin = Thickness(0, 0, 0, 3)
        corps.Children.Add(self._barre_globale)

        ligne_g = Grid()
        ligne_g.Margin = Thickness(0, 0, 0, 14)
        for w in ["*", "Auto"]:
            ligne_g.ColumnDefinitions.Add(str_ui.cd(w))
        self._lbl_compte = str_ui.texte(
            u"0 / {0}  (0%)".format(self._total),
            brush=str_ui.couleur("texte_gris"), marge=Thickness(0))
        Grid.SetColumn(self._lbl_compte, 0)
        ligne_g.Children.Add(self._lbl_compte)
        self._lbl_chrono_global = str_ui.texte(u"00:00", gras=True,
                                               brush=str_ui.couleur("titre"),
                                               marge=Thickness(0))
        self._lbl_chrono_global.HorizontalAlignment = SW.HorizontalAlignment.Right
        Grid.SetColumn(self._lbl_chrono_global, 1)
        ligne_g.Children.Add(self._lbl_chrono_global)
        corps.Children.Add(ligne_g)

        # --- Element courant ---
        corps.Children.Add(str_ui.texte(u"Element en cours", gras=True,
                                        brush=str_ui.couleur("titre"),
                                        marge=Thickness(0, 0, 0, 4)))

        ligne_e = Grid()
        ligne_e.Margin = Thickness(0, 0, 0, 4)
        for w in ["*", "Auto"]:
            ligne_e.ColumnDefinitions.Add(str_ui.cd(w))
        self._lbl_element = str_ui.texte(u"Preparation...", marge=Thickness(0))
        self._lbl_element.TextTrimming = SW.TextTrimming.CharacterEllipsis
        Grid.SetColumn(self._lbl_element, 0)
        ligne_e.Children.Add(self._lbl_element)
        self._lbl_chrono_element = str_ui.texte(u"", gras=True,
                                                brush=str_ui.couleur("ok"),
                                                marge=Thickness(0))
        self._lbl_chrono_element.HorizontalAlignment = SW.HorizontalAlignment.Right
        Grid.SetColumn(self._lbl_chrono_element, 1)
        ligne_e.Children.Add(self._lbl_chrono_element)
        corps.Children.Add(ligne_e)

        self._barre_element = ProgressBar()
        self._barre_element.Height = 14
        self._barre_element.Maximum = 1
        corps.Children.Add(self._barre_element)

        self._lbl_etat = str_ui.texte(u"", taille=10,
                                      brush=str_ui.couleur("avertissement"),
                                      marge=Thickness(0, 8, 0, 0))
        corps.Children.Add(self._lbl_etat)

        # --- Footer + Annuler ---
        footer, sp_btns, grid_f = str_ui.make_footer(self._version)
        Grid.SetRow(footer, 1)
        racine.Children.Add(footer)
        if self._annulable:
            self._btn_annuler = str_ui.footer_btn(u"Annuler", "annuler", 100,
                                                  self._on_annuler)
            sp_btns.Children.Add(self._btn_annuler)
            grid_f.Children.Add(sp_btns)

        # La croix de la fenetre vaut demande d'annulation, pas fermeture :
        # fermer pendant un doc.Export laisserait l'appelant sans retour.
        win.Closing += self._on_closing

        self._fenetre = win
        self._dispatcher = win.Dispatcher

    # ------------------------------------------------------------------
    # Handlers (thread STA)
    # ------------------------------------------------------------------
    def _on_annuler(self, sender, e):
        self._annule = True
        try:
            self._btn_annuler.IsEnabled = False
            self._btn_annuler.Content = u"Annulation..."
            self._lbl_etat.Text = MSG_ANNULATION
        except Exception:
            pass

    def _on_closing(self, sender, e):
        if not self._ferme:
            e.Cancel = True
            self._annule = True
            try:
                self._lbl_etat.Text = MSG_ANNULATION
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Chronometre : un seul thread, reveil interruptible
    # ------------------------------------------------------------------
    def _boucle_chrono(self):
        while not self._arret.IsSet:
            self._rafraichir_chronos()
            self._arret.Wait(1000)

    def _rafraichir_chronos(self):
        global_txt = str_ui.fmt_duree(time.time() - self._debut_global)
        debut = self._debut_element
        element_txt = (self._texte_element(time.time() - debut)
                       if debut is not None else None)

        def maj(g=global_txt, e=element_txt):
            self._lbl_chrono_global.Text = g
            if e is not None:
                self._lbl_chrono_element.Text = e
        self._invoquer(maj)

    def _texte_element(self, secondes):
        """'42 %   01:23' quand la progression reelle est connue, sinon l'heure."""
        temps = str_ui.fmt_duree(secondes)
        if self._pct is None:
            return temps
        return u"{0} %   {1}".format(self._pct, temps)

    def _invoquer(self, action):
        if self._dispatcher is None:
            return
        try:
            self._dispatcher.BeginInvoke(DispatcherPriority.Normal,
                                         System.Action(action))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API appelee depuis le thread Revit
    # ------------------------------------------------------------------
    def debut_element(self, libelle, deja_faits):
        """
        Demarre l'element.

        La barre est remise a zero en mode DETERMINE, jamais en indetermine :
        une ProgressBar indeterminee anime en boucle a ~60 images par seconde et
        fait tourner le thread STA en continu, ce qui prend du temps de calcul a
        l'operation en cours. Sur un export ou aucune progression reelle n'est
        publiee, l'animation tournerait du debut a la fin pour ne rien dire.
        La preuve que le traitement avance est donnee par le chronometre, qui
        defile a la seconde.
        """
        self._debut_element = time.time()
        self._faits = deja_faits
        self._pct = None
        total = self._total
        pct = int(round(deja_faits * 100.0 / total))

        def maj(n=libelle, faits=deja_faits, p=pct):
            self._lbl_element.Text = n
            self._lbl_chrono_element.Text = u"00:00"
            self._lbl_compte.Text = u"{0} / {1}  ({2}%)".format(faits, total, p)
            self._barre_element.IsIndeterminate = False
            self._barre_element.Maximum = 100
            self._barre_element.Value = 0
        self._invoquer(maj)

    def avancement(self, fraction, phase=None):
        """
        Progression reelle de l'element courant, fraction entre 0.0 et 1.0.

        Fait avancer la barre de l'element de 0 a 100 % ET la barre globale de
        facon continue (elements termines + fraction en cours). Amorti : on ne
        repeint qu'au changement de pourcentage entier, l'evenement source
        pouvant se declencher des milliers de fois par seconde.
        """
        try:
            valeur = float(fraction)
        except (TypeError, ValueError):
            return
        valeur = max(0.0, min(1.0, valeur))
        pct = int(round(valeur * 100.0))
        if pct == self._pct:
            return
        self._pct = pct

        total = self._total
        faits = self._faits
        debut = self._debut_element
        texte = self._texte_element(time.time() - debut if debut else 0.0)
        pct_global = int(round((faits + valeur) * 100.0 / total))

        def maj(p=pct, t=texte, f=faits, v=valeur, pg=pct_global, ph=phase):
            self._barre_element.IsIndeterminate = False
            self._barre_element.Maximum = 100
            self._barre_element.Value = p
            self._barre_globale.IsIndeterminate = False
            self._barre_globale.Maximum = total
            self._barre_globale.Value = f + v
            self._lbl_compte.Text = u"{0} / {1}  ({2}%)".format(f, total, pg)
            self._lbl_chrono_element.Text = t
            # Ne jamais ecraser le message d'annulation.
            if ph and not self._annule:
                self._lbl_etat.Text = ph
        self._invoquer(maj)

    def fin_element(self, faits, message=None):
        """Cloture l'element : barre globale avancee, chrono figee."""
        duree = (time.time() - self._debut_element
                 if self._debut_element is not None else 0.0)
        self._debut_element = None
        self._faits = faits
        self._pct = None
        total = self._total
        pct = int(round(faits * 100.0 / total))
        duree_txt = str_ui.fmt_duree(duree)

        def maj(faits=faits, p=pct, d=duree_txt, msg=message):
            self._barre_globale.IsIndeterminate = False
            self._barre_globale.Maximum = total
            self._barre_globale.Value = faits
            self._lbl_compte.Text = u"{0} / {1}  ({2}%)".format(faits, total, p)
            self._barre_element.IsIndeterminate = False
            # Remplir la barre en tenant compte du maximum courant : il vaut 100
            # des qu'une progression reelle est arrivee, et poser Value = 1
            # affichait alors 1 % en fin d'element au lieu de 100 %.
            self._barre_element.Value = self._barre_element.Maximum
            self._lbl_chrono_element.Text = d
            if msg:
                self._lbl_etat.Text = msg
        self._invoquer(maj)
        return duree

    def message(self, texte):
        def maj(t=texte):
            self._lbl_etat.Text = t
        self._invoquer(maj)

    @property
    def duree_totale(self):
        return time.time() - self._debut_global

    def fermer(self):
        """Arrete chrono et thread STA. Idempotent, sans exception."""
        if self._ferme:
            return
        self._ferme = True
        self._arret.Set()

        def fermeture():
            try:
                self._fenetre.Close()
            except Exception:
                pass
            try:
                Dispatcher.CurrentDispatcher.InvokeShutdown()
            except Exception:
                pass
        self._invoquer(fermeture)
        try:
            self._thread.Join(DELAI_FERMETURE_MS)
        except Exception:
            pass
