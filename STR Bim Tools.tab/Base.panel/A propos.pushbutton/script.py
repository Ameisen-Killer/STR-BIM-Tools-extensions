# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"À propos"
SITE           = u"www.str-bim-tools.com"
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


try:
    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import os

    from System import Uri
    from System.Diagnostics import Process
    from System.Windows import (Window, Thickness, WindowStartupLocation,
                                ResizeMode, TextWrapping, VerticalAlignment)
    from System.Windows.Controls import Grid, StackPanel
    from System.Windows.Documents import Hyperlink, Run

    import str_ui as UI

    LARGEUR = 520
    HAUTEUR = 430

    # Quatre principes de conception, volontairement generaux : cette
    # fenetre reste neutre et ne cite aucun contexte professionnel.
    PRINCIPES = [
        (u"La règle métier est une donnée, pas du code",
         u"Normes, catalogues et listes de valeurs vivent dans des fichiers "
         u"de référence. Une valeur qui change ne demande aucune reprise de "
         u"programme."),
        (u"Rien n'est écrit sans un geste explicite",
         u"Les outils lisent et rapportent. Ce qu'ils écrivent, vous l'avez "
         u"demandé ligne par ligne, et cela s'annule d'un Ctrl+Z."),
        (u"Ce qui échoue se dit",
         u"Un refus, une valeur illisible, un contrôle interrompu sont "
         u"rapportés nommément. Aucun échec n'est avalé en silence."),
        (u"Chaque outil sait dire ce qu'il ne fait pas",
         u"Les limites connues sont écrites dans les notices, au même titre "
         u"que les fonctions."),
    ]

    def _nb_outils():
        """Compte les boutons du ruban. Purement informatif : en cas de doute
        on n'affiche rien plutôt qu'un chiffre faux."""
        try:
            racine = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))
            n = 0
            for dossier, sous, _fichiers in os.walk(racine):
                n += len([d for d in sous if d.endswith(".pushbutton")])
            return n
        except Exception:
            return 0

    class APropos(Window):

        def __init__(self):
            self.Title = u"STR BIM Tools - {0}".format(TOOL_NAME)
            self.Width = LARGEUR
            self.Height = HAUTEUR
            self.MinWidth = 440
            self.MinHeight = 380
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.ResizeMode = ResizeMode.CanResize
            self.Background = UI.couleur("fond")
            self._construire()

        def _construire(self):
            root = Grid()
            for h in ["Auto", "*", "Auto"]:
                root.RowDefinitions.Add(UI.rd(h))
            self.Content = root

            titre = UI.barre_titre(u"STR BIM Tools")
            Grid.SetRow(titre, 0)
            root.Children.Add(titre)

            corps = StackPanel()
            corps.Margin = Thickness(16, 10, 16, 10)

            intro = UI.texte(
                u"Une boîte à outils Revit pour l'ingénierie structure, "
                u"bâtie sur quatre principes.", 11)
            intro.TextWrapping = TextWrapping.Wrap
            intro.Margin = Thickness(0, 0, 0, 8)
            corps.Children.Add(intro)

            gb = UI.group_box()
            interne = StackPanel()
            for i, (titre_p, detail) in enumerate(PRINCIPES):
                t = UI.texte(u"{0}. {1}".format(i + 1, titre_p), 11, gras=True,
                             brush=UI.couleur("titre"),
                             marge=Thickness(0, 6 if i else 0, 0, 1))
                t.TextWrapping = TextWrapping.Wrap
                interne.Children.Add(t)
                d = UI.texte(detail, 10, brush=UI.couleur("texte_gris"))
                d.TextWrapping = TextWrapping.Wrap
                d.VerticalAlignment = VerticalAlignment.Top
                interne.Children.Add(d)
            gb.Child = interne
            corps.Children.Add(gb)

            n = _nb_outils()
            ligne = u"{0}  |  Revit 2024 et suivants".format(
                u"{0} outils".format(n) if n else u"pyRevit")
            corps.Children.Add(UI.texte(ligne, 10,
                                        brush=UI.couleur("texte_gris"),
                                        marge=Thickness(0, 8, 0, 0)))

            # Lien cliquable : un TextBlock ne suffit pas, il faut un
            # Hyperlink et l'ouverture par le navigateur du poste.
            lien_tb = UI.texte(u"", 12, marge=Thickness(0, 6, 0, 0))
            lien = Hyperlink(Run(SITE))
            try:
                lien.NavigateUri = Uri(u"https://" + SITE)
            except Exception:
                pass
            lien.RequestNavigate += self._on_lien
            lien_tb.Inlines.Add(lien)
            corps.Children.Add(lien_tb)

            Grid.SetRow(corps, 1)
            root.Children.Add(corps)

            footer, sp_btns, grid_f = UI.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 2)
            root.Children.Add(footer)
            sp_btns.Children.Add(UI.footer_btn(u"Fermer", "fermer", 90,
                                               lambda s, e: self.Close()))
            grid_f.Children.Add(sp_btns)

        def _on_lien(self, sender, e):
            """Ouvre le site dans le navigateur par défaut. Un lien mort ne
            doit pas faire tomber la fenêtre."""
            try:
                Process.Start(e.Uri.AbsoluteUri)
            except Exception:
                pass
            e.Handled = True

    APropos().ShowDialog()

except Exception as _ex:
    _show_fatal(u"STR BIM Tools - {0} - Erreur de chargement".format(TOOL_NAME),
                _ex)
