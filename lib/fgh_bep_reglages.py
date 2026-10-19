# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_reglages.py - Fenetre « Configuration » du controle de conformite BEP.
#
# Ouverte depuis le footer de la fenetre de resultats. Elle sert a regler ce
# qui releve du projet et non du BEP, ou ce qui est encore en negociation
# avec la cellule BIM :
#   - les prefixes de familles tolerees dans les categories interdites (F06a) ;
#   - le jeu de caracteres admis, PAR NATURE D'OBJET (D03) : le BEP 2.10
#     n'admet que le blanc souligne, mais un nom de type a souvent besoin du
#     point la ou une famille n'en a pas besoin.
# La fenetre est concue pour s'etoffer : chaque bloc est une section
# independante empilee dans le meme panneau defilant.
#
# Ce qu'elle affiche est exactement ce qui sera applique : la saisie remplace
# la valeur du referentiel, elle ne s'y ajoute pas en silence. Le bouton
# « Valeurs du referentiel » remet les valeurs du BEP dans tous les champs.
#
# Ne pas confondre les deux voisins :
#   fgh_bep_config.py = lecture du referentiel BEP (fgh_bep_config.json) ;
#   fgh_bep_prefs.py  = lecture/ecriture des reglages (fgh_bep_prefs.json).
#
# Ce module DEPEND de WPF, pas de l'API Revit. IronPython 2.7 compatible.
# =============================================================================

import re

import System
from System.Windows import (Window, Thickness, WindowStartupLocation,
                            ResizeMode, TextWrapping,
                            HorizontalAlignment, VerticalAlignment,
                            MessageBox, MessageBoxButton, MessageBoxImage,
                            MessageBoxResult)
from System.Windows.Controls import (Grid, ScrollViewer, ScrollBarVisibility,
                                     StackPanel)

import str_ui as UI
import fgh_bep_config
import fgh_bep_prefs

LARGEUR = 780
HAUTEUR = 640


class Reglages(Window):
    """Retourne True (DialogResult) si les reglages ont ete enregistres."""

    def __init__(self, ref, tool_name, version):
        self.ref = ref
        self.tool_name = tool_name
        self.version = version
        # [(nom_categorie_OST, TextBox, [prefixes du referentiel])]
        self._champs_exclusions = []
        # [(cle_portee, TextBox, [caracteres du referentiel])]
        self._champs_caracteres = []

        self.Title = u"{0} - Configuration".format(tool_name)
        self.Width = LARGEUR
        self.Height = HAUTEUR
        self.MinWidth = 620
        self.MinHeight = 400
        self.WindowStartupLocation = WindowStartupLocation.CenterOwner
        self.ResizeMode = ResizeMode.CanResize
        self.Background = UI.couleur("fond")
        self._construire()

    # -- construction ---------------------------------------------------------
    def _construire(self):
        root = Grid()
        for h in ["Auto", "*", "Auto"]:
            root.RowDefinitions.Add(UI.rd(h))
        self.Content = root

        titre = UI.barre_titre(u"Configuration du contrôle BEP")
        Grid.SetRow(titre, 0)
        root.Children.Add(titre)

        corps = StackPanel()
        corps.Margin = Thickness(14, 4, 14, 10)
        corps.Children.Add(self._bloc_caracteres())
        corps.Children.Add(self._bloc_exclusions())

        defil = ScrollViewer()
        defil.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        defil.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        defil.Content = corps
        Grid.SetRow(defil, 1)
        root.Children.Add(defil)

        footer, sp_btns, grid_f = UI.make_footer(self.version)
        Grid.SetRow(footer, 2)
        root.Children.Add(footer)
        b_def = UI.footer_btn(u"Valeurs du référentiel", "secondaire", 160,
                              self._on_defaut)
        # Seul bouton clair de la bande : le texte blanc du gabarit y serait
        # illisible.
        b_def.Foreground = UI.couleur("texte")
        b_def.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(b_def)
        b_ok = UI.footer_btn(u"Enregistrer", "appliquer", 120,
                             self._on_enregistrer)
        b_ok.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(b_ok)
        sp_btns.Children.Add(UI.footer_btn(u"Annuler", "annuler", 90,
                                           lambda s, e: self.Close()))
        grid_f.Children.Add(sp_btns)

    # -- section : jeu de caracteres ------------------------------------------
    def _bloc_caracteres(self):
        """Un champ par nature d'objet effectivement controlee. La boucle suit
        `nommage.portees` du referentiel : activer une portee suffit a faire
        apparaitre son champ, sans toucher a cette fenetre."""
        sp = StackPanel()
        sp.Children.Add(UI.section_hdr(
            u"Caractères autorisés dans les noms, par nature d'objet"))
        sp.Children.Add(self._aide(
            u"Les lettres non accentuées (A-Z, a-z) et les chiffres (0-9) sont "
            u"toujours admis. Saisissez ici les caractères admis EN PLUS, par "
            u"exemple :  _ . -  (les espaces de saisie sont ignorés). "
            u"Un champ vide n'autorise que les lettres et les chiffres. "
            u"L'espace et le point-virgule ne peuvent pas être autorisés : "
            u"Revit ou le BEP les refusent de toute façon."))
        sp.Children.Add(self._aide(
            u"Rappel : le BEP 2.10 n'admet que le blanc souligné « _ ». Tout "
            u"ajout ici est un écart au BEP, à faire valider par la cellule "
            u"BIM. Le contrôle D03 et les corrections proposées suivent ce "
            u"que vous réglez ici."))

        portees = self.ref.nommage.get("portees") or {}
        actives = [(cle, lib) for cle, lib in fgh_bep_config.PORTEES
                   if portees.get(cle)]
        if not actives:
            sp.Children.Add(self._aide(
                u"Aucune portee de nommage n'est activée au référentiel : "
                u"rien à régler ici."))
            return sp

        gb = UI.group_box()
        interne = StackPanel()
        for cle, libelle in actives:
            brut = self.ref.caracteres_extra_referentiel(cle)
            tb = UI.zone_texte(150)
            tb.Text = fgh_bep_prefs.vers_texte_caracteres(
                self.ref.caracteres_extra(cle))
            tb.ToolTip = u"Référentiel BEP pour « {0} » : {1}".format(
                libelle,
                fgh_bep_prefs.vers_texte_caracteres(brut) or u"(rien)")
            interne.Children.Add(UI.ligne_champ(
                u"{0} :".format(libelle), tb, 170))
            self._champs_caracteres.append((cle, tb, list(brut)))
        gb.Child = interne
        sp.Children.Add(gb)
        return sp

    # -- section : familles tolerees ------------------------------------------
    def _bloc_exclusions(self):
        """Un champ par categorie interdite du referentiel. La boucle evite
        d'avoir a toucher cette fenetre le jour ou le BEP en interdit une
        seconde."""
        sp = StackPanel()
        sp.Children.Add(UI.section_hdr(
            u"Familles tolérées dans les catégories interdites"))
        sp.Children.Add(self._aide(
            u"Une occurrence est acceptée si le nom de sa FAMILLE commence par "
            u"l'une des valeurs ci-dessous. Séparez les valeurs par un "
            u"point-virgule, par exemple :  FGH_RES ; PVA_RES ; SPV_ . "
            u"La casse n'a pas d'importance. Un champ vide signifie : aucune "
            u"tolérance, toute occurrence de la catégorie est un écart."))

        effectives = self.ref.categories_interdites
        if not effectives:
            sp.Children.Add(self._aide(
                u"Aucune catégorie interdite n'est déclarée au référentiel : "
                u"rien à régler ici."))
            return sp

        for nom_cat in sorted(effectives.keys()):
            spec = effectives[nom_cat]
            brut = self.ref.categorie_interdite_referentiel(nom_cat)
            gb = UI.group_box()
            interne = StackPanel()

            libelle = spec.get("libelle") or nom_cat
            entete = UI.texte(u"{0}   ({1})".format(libelle, nom_cat), 11,
                              gras=True, marge=Thickness(0, 0, 0, 2))
            interne.Children.Add(entete)
            if spec.get("message"):
                interne.Children.Add(self._aide(spec.get("message")))

            tb = UI.zone_texte()
            # NaN = « largeur automatique » en WPF : le champ suit alors la
            # largeur de la fenetre au lieu des 210 px du gabarit.
            tb.Width = System.Double.NaN
            tb.HorizontalAlignment = HorizontalAlignment.Stretch
            tb.Margin = Thickness(0, 4, 0, 0)
            tb.Text = fgh_bep_prefs.vers_texte(spec.get("exclusions_famille"))
            tb.ToolTip = u"Valeurs du référentiel BEP : {0}".format(
                fgh_bep_prefs.vers_texte(brut.get("exclusions_famille"))
                or u"(aucune)")
            interne.Children.Add(tb)

            gb.Child = interne
            sp.Children.Add(gb)
            self._champs_exclusions.append(
                (nom_cat, tb, list(brut.get("exclusions_famille") or [])))
        return sp

    def _aide(self, contenu):
        tb = UI.texte(contenu, 10, brush=UI.couleur("texte_gris"),
                      marge=Thickness(0, 0, 0, 4))
        tb.TextWrapping = TextWrapping.Wrap
        tb.VerticalAlignment = VerticalAlignment.Top
        return tb

    # -- actions --------------------------------------------------------------
    def _on_defaut(self, sender, e):
        for _cle, tb, brut in self._champs_caracteres:
            tb.Text = fgh_bep_prefs.vers_texte_caracteres(brut)
        for _nom, tb, brut in self._champs_exclusions:
            tb.Text = fgh_bep_prefs.vers_texte(brut)

    def _natures_sans_prefixe_possible(self, caracteres):
        """Natures d'objet dont le jeu saisi ne permet meme pas d'ecrire le
        prefixe de specialite.

        Le cas typique est le champ vide, ou tout champ sans « _ » : le
        prefixe « STR_ » devient alors impossible a former, presque tous les
        noms passent en ecart, et plus aucune correction ne peut etre
        proposee. C'est un reglage licite mais qui ne s'improvise pas - il
        doit etre confirme, pas subi.
        """
        prefixe = self.ref.nommage.get("prefixe_specialite") or u""
        if not prefixe:
            return []
        out = []
        for cle, libelle in fgh_bep_config.PORTEES:
            if cle not in caracteres:
                continue
            motif = fgh_bep_config.motif_depuis_extra(caracteres[cle])
            try:
                if not re.match(motif, prefixe + u"X"):
                    out.append(libelle)
            except Exception:
                pass
        return out

    def _on_enregistrer(self, sender, e):
        caracteres = {}
        for cle, tb, _brut in self._champs_caracteres:
            caracteres[cle] = fgh_bep_prefs.depuis_texte_caracteres(tb.Text)

        bancales = self._natures_sans_prefixe_possible(caracteres)
        if bancales:
            prefixe = self.ref.nommage.get("prefixe_specialite") or u""
            reponse = MessageBox.Show(
                u"Le jeu de caractères saisi pour :\n\n    {0}\n\n"
                u"ne permet pas d'écrire le préfixe « {1} ». Presque tous les "
                u"noms passeront en écart et AUCUNE correction ne pourra être "
                u"proposée.\n\nC'est généralement un champ vide, ou un champ "
                u"dont le « _ » a été effacé.\n\nEnregistrer quand même ?"
                .format(u"\n    ".join(bancales), prefixe),
                self.tool_name, MessageBoxButton.YesNo,
                MessageBoxImage.Warning)
            if reponse != MessageBoxResult.Yes:
                return

        exclusions = {}
        for nom_cat, tb, _brut in self._champs_exclusions:
            exclusions[nom_cat] = fgh_bep_prefs.depuis_texte(tb.Text)

        # Une seule ecriture du fichier pour les deux sections : deux appels
        # laisseraient un fichier a moitie a jour si le second echouait.
        reglages = fgh_bep_prefs.charger()
        reglages["caracteres_extra"] = caracteres
        reglages["exclusions_famille"] = exclusions
        ok, msg = fgh_bep_prefs.enregistrer(reglages)
        if not ok:
            MessageBox.Show(
                u"Enregistrement impossible : {0}\n\n{1}".format(
                    msg, fgh_bep_prefs.FICHIER),
                self.tool_name, MessageBoxButton.OK, MessageBoxImage.Error)
            return
        self.DialogResult = True
        self.Close()


def afficher(proprietaire, tool_name, version):
    """Ouvre la fenetre et retourne True si les reglages ont ete enregistres.
    Le referentiel est relu ici : la fenetre montre toujours l'etat des
    fichiers, pas celui du lancement de l'analyse."""
    w = Reglages(fgh_bep_config.charger(), tool_name, version)
    try:
        w.Owner = proprietaire
    except Exception:
        pass
    return w.ShowDialog() == True
