# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Nettoyer reperes"
# =============================================================================
# Ne laisse visibles, dans les vues posees sur une feuille, que les reperes de
# coupe, d'elevation et de detail dont la vue cible est sur la MEME feuille.
#
# Revit n'a pas de reglage "afficher seulement les coupes de cette feuille" :
# l'outil le fait element par element, avec "Masquer dans la vue" (pas de
# filtre de vue). Il se relance quand des vues ont change de feuille : les
# reperes redevenus utiles sont reaffiches, les autres masques.
#
# Workflow :
#   1. Choix des feuilles (la feuille active, ou celle de la vue active, est
#      precochee).
#   2. Pour chaque vue posee sur ces feuilles (plans, coupes, elevations,
#      details), l'outil passe en revue les reperes :
#        - repere de coupe / detail / callout (categorie Vues, OST_Viewers)
#        - repere d'elevation (ElevationMarker) : garde si une au moins de ses
#          fleches pointe vers une vue de la feuille
#   3. Regle pour un repere qui cible la vue S, dans une vue de la feuille F :
#        - S (ou une de ses vues dependantes) est sur F    -> affiche
#        - S n'est sur aucune feuille                       -> option
#        - S est sur une autre feuille                      -> masque
#   4. Mode "Reafficher" : reaffiche tous les reperes masques dans les vues
#      des feuilles choisies (retour arriere complet).
#
# Retrouver la vue cible d'un repere : le repere porte le nom de sa vue
# (parametre VIEW_NAME). Si plusieurs vues portent ce nom, on ecarte la vue
# proprietaire du repere (callout) puis on tranche par GetDependentElements.
# En dernier recours, on lit le numero de feuille affiche dans la tete du
# repere (VIEWER_SHEET_NUMBER).
# =============================================================================

# Hors filet : strict minimum pour pouvoir afficher une erreur fatale.
import clr
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(titre, ex):
    td = TaskDialog(titre)
    td.MainContent = u"Erreur : " + u"{0}".format(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.Show()


try:
    import io
    import json
    import os

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")

    import System
    import System.Windows as SW
    from System.Collections.Generic import List
    from System.Windows import Thickness, Window
    from System.Windows.Controls import (Grid, ListBox, ListBoxItem,
                                         Orientation, RadioButton,
                                         SelectionMode, StackPanel)

    from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter,
                                   ElementCategoryFilter, ElementId,
                                   ElevationMarker, FilteredElementCollector,
                                   Transaction, TransactionStatus, View,
                                   ViewSheet, ViewType)

    import str_ui

    uidoc = __revit__.ActiveUIDocument
    doc = uidoc.Document
    app = __revit__.Application

    _FOOTER = u"v{0} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "prefs.json")

    # Vues posees sur une feuille dans lesquelles on nettoie les reperes.
    TYPES_VUES_TRAITEES = (
        ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan,
        ViewType.AreaPlan, ViewType.Section, ViewType.Elevation,
        ViewType.Detail,
    )

    # ======================================================================
    # Helpers
    # ======================================================================
    def id_value(element_id):
        """Valeur entiere d'un ElementId, sans dependre de IntegerValue."""
        if element_id is None:
            return -1
        try:
            return int(element_id.Value)
        except AttributeError:
            return int(element_id.IntegerValue)

    def charger_prefs():
        try:
            if os.path.isfile(_PREFS_FILE):
                with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def sauver_prefs(prefs):
        try:
            texte = json.dumps(prefs, ensure_ascii=True)
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                f.write(u"{0}".format(texte))
        except Exception:
            pass

    def libelle_feuille(f):
        return u"{0} - {1}".format(f.SheetNumber, f.Name)

    # ======================================================================
    # Analyse du modele : feuilles, vues, reperes
    # ======================================================================
    class Modele(object):
        """Tout ce qui est lu une fois avant la transaction."""

        def __init__(self):
            self.feuilles = sorted(
                [f for f in FilteredElementCollector(doc).OfClass(ViewSheet)
                 if not f.IsTemplate and not f.IsPlaceholder],
                key=lambda f: f.SheetNumber)

            # id vue -> set(id feuille)
            self.feuilles_de_vue = {}
            for f in self.feuilles:
                for vid in f.GetAllPlacedViews():
                    self.feuilles_de_vue.setdefault(
                        id_value(vid), set()).add(id_value(f.Id))
            self.numero_feuille = dict(
                (id_value(f.Id), f.SheetNumber) for f in self.feuilles)

            # Vues par nom, pour retrouver la cible d'un repere.
            self.vues_par_nom = {}
            self.vues = {}
            for v in FilteredElementCollector(doc).OfClass(View):
                if v.IsTemplate or isinstance(v, ViewSheet):
                    continue
                self.vues[id_value(v.Id)] = v
                self.vues_par_nom.setdefault(v.Name, []).append(v)

            self._cible_cache = {}
            self._feuilles_cible_cache = {}

            # Tous les reperes du modele (pour retrouver ceux deja masques).
            self.viewers = list(
                FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Viewers)
                .WhereElementIsNotElementType())
            self.marqueurs = list(
                FilteredElementCollector(doc).OfClass(ElevationMarker))

        # ------------------------------------------------------------------
        def feuilles_cible(self, vue):
            """Feuilles ou la vue apparait, elle ou une de ses dependantes."""
            cle = id_value(vue.Id)
            if cle in self._feuilles_cible_cache:
                return self._feuilles_cible_cache[cle]
            res = set(self.feuilles_de_vue.get(cle, set()))
            try:
                for dep in vue.GetDependentViewIds():
                    res |= self.feuilles_de_vue.get(id_value(dep), set())
            except Exception:
                pass
            self._feuilles_cible_cache[cle] = res
            return res

        def vue_cible(self, viewer):
            """Vue referencee par un repere (OST_Viewers), ou None."""
            cle = id_value(viewer.Id)
            if cle in self._cible_cache:
                return self._cible_cache[cle]
            nom = None
            p = viewer.get_Parameter(BuiltInParameter.VIEW_NAME)
            if p is not None and p.HasValue:
                nom = p.AsString()
            if not nom:
                try:
                    nom = viewer.Name
                except Exception:
                    nom = None
            candidats = list(self.vues_par_nom.get(nom, [])) if nom else []
            # Un callout appartient a sa vue parente : ce n'est pas sa cible.
            proprio = id_value(viewer.OwnerViewId)
            candidats = [v for v in candidats if id_value(v.Id) != proprio]
            cible = None
            if len(candidats) == 1:
                cible = candidats[0]
            elif len(candidats) > 1:
                filtre = ElementCategoryFilter(BuiltInCategory.OST_Viewers)
                for v in candidats:
                    try:
                        deps = v.GetDependentElements(filtre)
                    except Exception:
                        continue
                    if any(id_value(d) == cle for d in deps):
                        cible = v
                        break
            self._cible_cache[cle] = cible
            return cible

        # ------------------------------------------------------------------
        def decision_viewer(self, viewer, vue, id_feuille, masquer_non_places):
            """True = afficher, False = masquer, None = ne pas toucher."""
            cible = self.vue_cible(viewer)
            if cible is not None:
                if id_value(cible.Id) == id_value(vue.Id):
                    return None
                return self._regle(self.feuilles_cible(cible), id_feuille,
                                   masquer_non_places)
            # Repere sans vue retrouvee : numero de feuille de la tete.
            p = viewer.get_Parameter(BuiltInParameter.VIEWER_SHEET_NUMBER)
            if p is None:
                return None
            num = (p.AsString() or u"").strip()
            if not num or num.strip(u"-") == u"":
                return False if masquer_non_places else True
            return num == self.numero_feuille.get(id_feuille)

        def decision_marqueur(self, marqueur, id_feuille, masquer_non_places):
            """Repere d'elevation : garde si une de ses vues est utile."""
            decisions = []
            try:
                n = marqueur.MaximumViewCount
            except Exception:
                n = 4
            for i in range(n):
                try:
                    if not marqueur.HasViewAssociated(i):
                        continue
                    v = self.vues.get(id_value(marqueur.GetViewId(i)))
                except Exception:
                    v = None
                if v is None:
                    continue
                decisions.append(self._regle(self.feuilles_cible(v),
                                             id_feuille, masquer_non_places))
            if not decisions:
                return None
            return any(decisions)

        @staticmethod
        def _regle(feuilles, id_feuille, masquer_non_places):
            if id_feuille in feuilles:
                return True
            if not feuilles:
                return not masquer_non_places
            return False

        # ------------------------------------------------------------------
        def vues_de_feuille(self, feuille):
            res = []
            for vid in feuille.GetAllPlacedViews():
                v = self.vues.get(id_value(vid))
                if v is not None and v.ViewType in TYPES_VUES_TRAITEES:
                    res.append(v)
            return sorted(res, key=lambda v: v.Name)

    # ======================================================================
    # Calcul des actions (lecture seule, avant la transaction)
    # ======================================================================
    def peut_masquer(el, vue):
        try:
            return el.CanBeHidden(vue)
        except Exception:
            return False

    def est_masque(el, vue):
        try:
            return el.IsHidden(vue)
        except Exception:
            return False

    def actions_vue(modele, vue, id_feuille, mode, masquer_non_places):
        """(ids a masquer, ids a reafficher) pour une vue."""
        a_masquer, a_afficher = [], []
        tous = modele.viewers + modele.marqueurs

        if mode == "reafficher":
            for el in tous:
                if est_masque(el, vue):
                    a_afficher.append(el.Id)
            return a_masquer, a_afficher

        def decision(el):
            if isinstance(el, ElevationMarker):
                return modele.decision_marqueur(el, id_feuille,
                                                masquer_non_places)
            return modele.decision_viewer(el, vue, id_feuille,
                                          masquer_non_places)

        # Reperes masques qui redeviennent utiles.
        for el in tous:
            if est_masque(el, vue) and decision(el) is True:
                a_afficher.append(el.Id)

        # Reperes visibles dans la vue qui ne servent pas sur cette feuille.
        visibles = list(FilteredElementCollector(doc, vue.Id)
                        .OfCategory(BuiltInCategory.OST_Viewers)
                        .WhereElementIsNotElementType())
        visibles += list(FilteredElementCollector(doc, vue.Id)
                         .OfClass(ElevationMarker))
        for el in visibles:
            if decision(el) is False and peut_masquer(el, vue):
                a_masquer.append(el.Id)
        return a_masquer, a_afficher

    # ======================================================================
    # Fenetre
    # ======================================================================
    class DialogueNettoyer(Window):

        def __init__(self, modele, preselection, prefs):
            self._modele = modele
            self.resultat = None
            self.Title = TOOL_NAME
            self.Width = 620
            self.Height = 640
            self.MinWidth = 520
            self.MinHeight = 480
            self.ResizeMode = SW.ResizeMode.CanResizeWithGrip
            self.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
            self.Background = str_ui.couleur("fond")
            self._construire(preselection, prefs)
            self._maj_compteur()

        def _construire(self, preselection, prefs):
            racine = Grid()
            for h in ["Auto", "*", "Auto", "Auto"]:
                racine.RowDefinitions.Add(str_ui.rd(h))
            self.Content = racine

            titre = str_ui.barre_titre(
                u"Nettoyer repères  |  Revit {0}".format(app.VersionNumber))
            Grid.SetRow(titre, 0)
            racine.Children.Add(titre)

            # --- Feuilles ---------------------------------------------------
            corps = Grid()
            corps.Margin = Thickness(14, 6, 14, 0)
            for h in ["Auto", "*"]:
                corps.RowDefinitions.Add(str_ui.rd(h))
            Grid.SetRow(corps, 1)
            racine.Children.Add(corps)

            entete = str_ui.section_hdr(u"Feuilles à traiter  ({0})".format(
                len(self._modele.feuilles)))
            Grid.SetRow(entete, 0)
            corps.Children.Add(entete)

            boite = str_ui.group_box(stretch=True)
            Grid.SetRow(boite, 1)
            corps.Children.Add(boite)
            interne = Grid()
            for h in ["Auto", "*"]:
                interne.RowDefinitions.Add(str_ui.rd(h))
            boite.Child = interne

            barre = StackPanel()
            barre.Orientation = Orientation.Horizontal
            barre.Margin = Thickness(0, 0, 0, 6)
            barre.Children.Add(str_ui.texte(u"Filtrer :",
                                            marge=Thickness(0, 0, 6, 0)))
            self.txt_filtre = str_ui.zone_texte(largeur=160)
            self.txt_filtre.TextChanged += self._on_filtre
            barre.Children.Add(self.txt_filtre)
            barre.Children.Add(str_ui.small_btn(u"Tout cocher", self._on_tout))
            barre.Children.Add(str_ui.small_btn(u"Tout décocher",
                                                self._on_rien))
            self.lbl_compte = str_ui.texte(
                u"", gras=True, brush=str_ui.couleur("titre"),
                marge=Thickness(4, 0, 0, 0))
            barre.Children.Add(self.lbl_compte)
            Grid.SetRow(barre, 0)
            interne.Children.Add(barre)

            self.lst = ListBox()
            self.lst.SelectionMode = SelectionMode.Multiple
            self.lst.Background = str_ui.couleur("fond")
            self.lst.BorderBrush = str_ui.couleur("bordure")
            self.lst.FontSize = 11
            for f in self._modele.feuilles:
                item = ListBoxItem()
                n = len(self._modele.vues_de_feuille(f))
                item.Content = u"{0}   ({1} vue{2})".format(
                    libelle_feuille(f), n, u"s" if n > 1 else u"")
                item.Tag = f
                item.Selected += self._on_selection
                item.Unselected += self._on_selection
                self.lst.Items.Add(item)
                if id_value(f.Id) in preselection:
                    item.IsSelected = True
            Grid.SetRow(self.lst, 1)
            interne.Children.Add(self.lst)

            # --- Action et option ---------------------------------------------
            bas = StackPanel()
            bas.Margin = Thickness(14, 0, 14, 6)
            Grid.SetRow(bas, 2)
            racine.Children.Add(bas)
            bas.Children.Add(str_ui.section_hdr(u"Action"))
            gb = str_ui.group_box()
            sp = StackPanel()
            gb.Child = sp
            bas.Children.Add(gb)

            self.rb_nettoyer = RadioButton()
            self.rb_nettoyer.Content = (
                u"Nettoyer : ne garder que les repères des vues posées sur "
                u"la même feuille")
            self.rb_nettoyer.GroupName = "mode"
            self.rb_nettoyer.FontSize = 11
            self.rb_nettoyer.Margin = Thickness(0, 2, 0, 2)
            self.rb_nettoyer.IsChecked = True
            sp.Children.Add(self.rb_nettoyer)

            self.cb_non_places = str_ui.checkbox(
                u"Masquer aussi les repères des vues posées sur aucune feuille",
                coche=bool(prefs.get("masquer_non_places", True)),
                infobulle=(u"Décoché : les coupes et détails pas encore mis "
                           u"en page restent visibles partout."))
            self.cb_non_places.Margin = Thickness(20, 2, 0, 6)
            sp.Children.Add(self.cb_non_places)

            self.rb_reafficher = RadioButton()
            self.rb_reafficher.Content = (
                u"Réafficher tous les repères masqués dans les vues de ces "
                u"feuilles")
            self.rb_reafficher.GroupName = "mode"
            self.rb_reafficher.FontSize = 11
            self.rb_reafficher.Margin = Thickness(0, 2, 0, 2)
            sp.Children.Add(self.rb_reafficher)

            self.rb_nettoyer.Checked += self._on_mode
            self.rb_reafficher.Checked += self._on_mode

            # --- Footer --------------------------------------------------------
            footer, sp_btns, grid_f = str_ui.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 3)
            racine.Children.Add(footer)
            b_annuler = str_ui.footer_btn(u"Annuler", "annuler", 90,
                                          lambda s, e: self.Close())
            b_annuler.Margin = Thickness(0, 0, 6, 0)
            sp_btns.Children.Add(b_annuler)
            sp_btns.Children.Add(str_ui.footer_btn(u"Appliquer", "appliquer",
                                                   110, self._on_ok))
            grid_f.Children.Add(sp_btns)

        # ------------------------------------------------------------------
        def _selection(self):
            return [it.Tag for it in self.lst.Items if it.IsSelected]

        def _maj_compteur(self):
            self.lbl_compte.Text = u"{0} cochée(s)".format(
                len(self._selection()))

        def _on_selection(self, sender, e):
            self._maj_compteur()

        def _on_mode(self, sender, e):
            self.cb_non_places.IsEnabled = bool(self.rb_nettoyer.IsChecked)

        def _on_filtre(self, sender, e):
            req = self.txt_filtre.Text.strip().lower()
            for it in self.lst.Items:
                vis = (not req) or (req in libelle_feuille(it.Tag).lower())
                it.Visibility = (SW.Visibility.Visible if vis
                                 else SW.Visibility.Collapsed)

        def _cocher(self, valeur):
            for it in self.lst.Items:
                if it.Visibility == SW.Visibility.Visible:
                    it.IsSelected = valeur
            self._maj_compteur()

        def _on_tout(self, sender, e):
            self._cocher(True)

        def _on_rien(self, sender, e):
            self._cocher(False)

        def _on_ok(self, sender, e):
            feuilles = self._selection()
            if not feuilles:
                self.lbl_compte.Text = u"Coche au moins une feuille"
                self.lbl_compte.Foreground = str_ui.couleur("erreur")
                return
            self.resultat = {
                "feuilles": feuilles,
                "mode": ("reafficher" if self.rb_reafficher.IsChecked
                         else "nettoyer"),
                "masquer_non_places": bool(self.cb_non_places.IsChecked),
            }
            self.Close()

    # ======================================================================
    # Execution
    # ======================================================================
    def preselection_active(modele):
        vue = doc.ActiveView
        if isinstance(vue, ViewSheet):
            return set([id_value(vue.Id)])
        return set(modele.feuilles_de_vue.get(id_value(vue.Id), set()))

    def appliquer(modele, choix):
        mode = choix["mode"]
        plan = []   # (feuille, vue, a_masquer, a_afficher)
        for f in choix["feuilles"]:
            for v in modele.vues_de_feuille(f):
                a_m, a_a = actions_vue(modele, v, id_value(f.Id), mode,
                                       choix["masquer_non_places"])
                plan.append((f, v, a_m, a_a))

        erreurs = []
        t = Transaction(doc, u"STR - Nettoyer repères" if mode == "nettoyer"
                        else u"STR - Réafficher repères")
        t.Start()
        try:
            for f, v, a_m, a_a in plan:
                try:
                    if a_a:
                        v.UnhideElements(List[ElementId](a_a))
                    if a_m:
                        v.HideElements(List[ElementId](a_m))
                except Exception as ex:
                    erreurs.append(u"{0} : {1}".format(v.Name, ex))
            t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise
        return plan, erreurs

    def afficher_bilan(plan, erreurs):
        n_m = sum(len(p[2]) for p in plan)
        n_a = sum(len(p[3]) for p in plan)
        lignes = []
        feuille_courante = None
        for f, v, a_m, a_a in plan:
            if f is not feuille_courante:
                lignes.append(libelle_feuille(f))
                feuille_courante = f
            lignes.append(u"    {0} : {1} masqué(s), {2} réaffiché(s)".format(
                v.Name, len(a_m), len(a_a)))
        if not plan:
            lignes.append(u"Aucun plan, coupe, élévation ou détail posé sur "
                          u"les feuilles choisies.")

        td = TaskDialog(TOOL_NAME)
        td.MainInstruction = u"{0} repère(s) masqué(s), {1} réaffiché(s)".format(
            n_m, n_a)
        contenu = u"{0} vue(s) traitée(s) sur {1} feuille(s).".format(
            len(plan), len(set(id_value(p[0].Id) for p in plan)))
        if erreurs:
            contenu += u"\n\n{0} vue(s) en erreur :\n".format(len(erreurs))
            contenu += u"\n".join(erreurs)
        td.MainContent = contenu
        td.ExpandedContent = u"\n".join(lignes)
        td.FooterText = u"{0}  -  {1}".format(_FOOTER, SCRIPT_AUTHOR)
        td.CommonButtons = TaskDialogCommonButtons.Close
        td.Show()

    def main():
        modele = Modele()
        if not modele.feuilles:
            td = TaskDialog(TOOL_NAME)
            td.MainContent = u"Le projet ne contient aucune feuille."
            td.FooterText = _FOOTER
            td.Show()
            return
        prefs = charger_prefs()
        dlg = DialogueNettoyer(modele, preselection_active(modele), prefs)
        dlg.ShowDialog()
        choix = dlg.resultat
        if choix is None:
            return
        prefs["masquer_non_places"] = choix["masquer_non_places"]
        sauver_prefs(prefs)
        plan, erreurs = appliquer(modele, choix)
        afficher_bilan(plan, erreurs)

    main()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
