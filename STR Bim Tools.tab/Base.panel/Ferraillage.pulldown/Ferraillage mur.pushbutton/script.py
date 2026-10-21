# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Ferraillage mur"
# =============================================================================
#  v1.0.0 - Ferraillage courant des murs droits : barres verticales et
#           horizontales par face, enrobage, ordre des lits, attentes en tete
#           (mur du dessus detecte) et en pied. Jeux Revit a espacement
#           maximal, partition et commentaire renseignes pour la liste de fer.
#  v1.1.0 - Armatures liees au mur : poignees contraintes aux faces du mur,
#           configuration enregistree dans le mur, relancer l'outil remplace
#           le ferraillage STR (bouton "Mettre a jour murs" pour plusieurs).
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
    import os, io, json, math

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")

    from System.Collections.Generic import List as NetList
    from System.Windows import (Window, Thickness, WindowStartupLocation,
                                ResizeMode, MessageBox, MessageBoxButton,
                                MessageBoxImage, MessageBoxResult,
                                TextWrapping)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, Border,
                                         DataGridTextColumn, DataGridLength,
                                         DataGridLengthUnitType, ScrollViewer,
                                         ScrollBarVisibility, Orientation,
                                         DataGridGridLinesVisibility,
                                         DataGridHeadersVisibility, CheckBox)
    from System.Windows.Data import Binding

    from Autodesk.Revit.DB import (ElementId, Wall, View3D, Transaction,
                                   TransactionStatus)
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
    from Autodesk.Revit.Exceptions import OperationCanceledException

    import str_ui as UI
    import str_ferraillage as FER
    import str_ferraillage_mur as MUR
    import str_ferraillage_revit as FR

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{0} | STR BIM Tools by Tony VARIN".format(SCRIPT_VERSION)

    LITS = [(u"Horizontales contre le coffrage", True),
            (u"Verticales contre le coffrage", False)]
    ATTENTES = [(u"Auto : si un mur est détecté au-dessus", MUR.ATTENTE_AUTO),
                (u"Toujours", MUR.ATTENTE_TOUJOURS),
                (u"Jamais", MUR.ATTENTE_JAMAIS)]

    # =========================================================================
    # Preferences (par poste, fichier ignore par git)
    # =========================================================================
    _PREFS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "prefs.json")

    def charger_prefs():
        try:
            with io.open(_PREFS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def sauver_prefs(prefs):
        try:
            txt = json.dumps(prefs, ensure_ascii=False, indent=1)
            with io.open(_PREFS, "w", encoding="utf-8") as f:
                f.write(txt if isinstance(txt, type(u"")) else txt.decode("utf-8"))
        except Exception:
            pass

    # =========================================================================
    # Selection
    # =========================================================================
    class FiltreMurs(ISelectionFilter):
        def AllowElement(self, el):
            return isinstance(el, Wall)

        def AllowReference(self, ref, pt):
            return False

    def murs_selectionnes():
        murs = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
        murs = [m for m in murs if isinstance(m, Wall)]
        if murs:
            return murs
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element, FiltreMurs(),
                u"Sélectionne le ou les murs à ferrailler, puis Terminer")
        except OperationCanceledException:
            return []
        return [doc.GetElement(r.ElementId) for r in refs]

    # =========================================================================
    # Lignes du tableau des murs
    # =========================================================================
    class LigneMur(object):
        def __init__(self, info, existants):
            self.info = info
            self.Mur = info.get("type", u"")
            self.Id = info["id"]
            if info.get("erreur"):
                self.Longueur = self.Epaisseur = self.Hauteur = u""
                self.ZBas = self.ZHaut = self.Dessus = u""
            else:
                self.Longueur = FER.fmt_nombre(info["longueur"] / 100.0)
                self.Epaisseur = FER.fmt_nombre(info["ep"], 1)
                self.Hauteur = FER.fmt_nombre(
                    (info["z_haut"] - info["z_bas"]) / 100.0)
                self.ZBas = FER.fmt_nombre(info["z_bas"] / 100.0, 3)
                self.ZHaut = FER.fmt_nombre(info["z_haut"] / 100.0, 3)
                dessus = info.get("dessus")
                self.Dessus = u"Oui ({0})".format(dessus["id"]) if dessus else u"Non"
            nb_str, nb_autres = existants or (0, 0)
            self.Existants = u"{0} STR".format(nb_str) if nb_str else u""
            if nb_autres:
                self.Existants += (u" + " if nb_str else u"") + \
                    u"{0} autre(s)".format(nb_autres)
            self.Remarque = info.get("erreur", u"")

    # =========================================================================
    # Fenetre
    # =========================================================================
    class FenetreMur(Window):

        def __init__(self, infos, existants, barres):
            self.Title = TOOL_NAME
            self.Width = 1080
            self.Height = 760
            self.MinWidth = 900
            self.MinHeight = 600
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.ResizeMode = ResizeMode.CanResize
            self.Background = UI.couleur("fond")
            self.infos = infos
            self.existants = existants
            self.barres = barres            # {d mm: RebarBarType}
            self.prefs = charger_prefs()
            # Configuration deja enregistree dans un des murs : elle prime.
            self.config_mur = None
            for info in infos:
                cfg = FR.config_du_mur(info["elem"])
                if cfg:
                    self.config_mur = cfg
                    break
            source = self.config_mur or self.prefs
            self.rangs = source.get("rangs") or MUR.rangs_defaut(
                12 if 12 in barres else (sorted(barres)[0] if barres else 12))
            self.controles = []
            self.cree = 0
            self._construire()
            self._apercu()

        def _src(self, cle, defaut):
            if self.config_mur and cle in self.config_mur:
                return self.config_mur[cle]
            return self.prefs.get(cle, defaut)

        # --- Construction -----------------------------------------------------
        def _construire(self):
            root = Grid()
            for h in ["Auto", "*", "Auto"]:
                root.RowDefinitions.Add(UI.rd(h))
            self.Content = root
            titre = UI.barre_titre(u"{0}  |  Revit {1}".format(
                TOOL_NAME, app.VersionNumber))
            Grid.SetRow(titre, 0)
            root.Children.Add(titre)

            sv = ScrollViewer()
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            corps = StackPanel()
            corps.Margin = Thickness(12, 4, 12, 8)
            sv.Content = corps
            Grid.SetRow(sv, 1)
            root.Children.Add(sv)

            corps.Children.Add(UI.section_hdr(u"Murs sélectionnés"))
            corps.Children.Add(self._grille_murs())

            corps.Children.Add(UI.section_hdr(u"Barres par face"))
            gb = UI.group_box()
            gb.Child = self._tableau_rangs()
            corps.Children.Add(gb)

            corps.Children.Add(UI.section_hdr(u"Options"))
            gb2 = UI.group_box()
            sp = StackPanel()
            gb2.Child = sp
            self.tb_enrobage = UI.zone_texte(80, u"{0}".format(
                self._src("enrobage", 3)))
            sp.Children.Add(UI.ligne_champ(u"Enrobage (cm)", self.tb_enrobage, 170))
            self.cb_lit = UI.combo(LITS, 0, 260)
            UI.selectionner_valeur(self.cb_lit, self._src("h_ext", True))
            sp.Children.Add(UI.ligne_champ(u"Lit extérieur", self.cb_lit, 170))
            self.cb_attente = UI.combo(ATTENTES, 0, 260)
            UI.selectionner_valeur(self.cb_attente,
                                   self._src("attente", MUR.ATTENTE_AUTO))
            sp.Children.Add(UI.ligne_champ(u"Attentes en tête", self.cb_attente, 170))
            self.tb_partition = UI.zone_texte(260, self._src(
                "partition", u"Elévations"))
            sp.Children.Add(UI.ligne_champ(u"Partition (liste de fer)",
                                           self.tb_partition, 170))
            self.chk_3d = UI.checkbox(
                u"Barres visibles en entier dans la vue 3D active",
                self.prefs.get("vue3d", True))
            sp.Children.Add(self.chk_3d)
            corps.Children.Add(gb2)

            self.lbl_apercu = UI.texte(u"", 11, marge=Thickness(2, 4, 2, 0))
            self.lbl_apercu.TextWrapping = TextWrapping.Wrap
            corps.Children.Add(self.lbl_apercu)

            footer, sp_btns, grid_f = UI.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 2)
            root.Children.Add(footer)
            for libelle, cle, larg, handler in (
                    (u"Aperçu", "fermer", 90, lambda s, e: self._apercu()),
                    (u"Créer le ferraillage", "appliquer", 160, self._on_creer),
                    (u"Fermer", "annuler", 90, lambda s, e: self.Close())):
                b = UI.footer_btn(libelle, cle, larg, handler)
                b.Margin = Thickness(6, 0, 0, 0)
                sp_btns.Children.Add(b)
            grid_f.Children.Add(sp_btns)

        def _grille_murs(self):
            dg = DataGrid()
            dg.AutoGenerateColumns = False
            dg.IsReadOnly = True
            dg.MaxHeight = 170
            dg.AlternatingRowBackground = UI.couleur("ligne_alternee")
            dg.RowBackground = UI.couleur("fond")
            dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
            dg.HeadersVisibility = DataGridHeadersVisibility.Column
            dg.BorderBrush = UI.couleur("bordure")
            dg.FontSize = 12
            for entete, prop, larg in (
                    (u"Type de mur", "Mur", 200), (u"ID", "Id", 80),
                    (u"Long. m", "Longueur", 70), (u"Ép. cm", "Epaisseur", 60),
                    (u"Haut. m", "Hauteur", 70), (u"Z bas m", "ZBas", 80),
                    (u"Z haut m", "ZHaut", 80),
                    (u"Mur au-dessus", "Dessus", 110),
                    (u"Armatures existantes", "Existants", 120),
                    (u"Remarque", "Remarque", 0)):
                col = DataGridTextColumn()
                col.Header = entete
                col.Binding = Binding(prop)
                col.Width = DataGridLength(larg) if larg else \
                    DataGridLength(1, DataGridLengthUnitType.Star)
                dg.Columns.Add(col)
            dg.ItemsSource = [LigneMur(i, self.existants.get(i["id"]))
                              for i in self.infos]
            return dg

        def _tableau_rangs(self):
            g = Grid()
            largeurs = [50, 90, 100, 90, 70, 110, 110, "*"]
            for w in largeurs:
                g.ColumnDefinitions.Add(UI.cd(w))
            entetes = [u"Actif", u"Face", u"Barres", u"Ø (mm)", u"e (cm)",
                       u"Attente tête (cm)", u"Attente pied (cm)",
                       u"Commentaire (liste de fer)"]
            g.RowDefinitions.Add(UI.rd("Auto"))
            for c, t in enumerate(entetes):
                tb = UI.texte(t, 11, gras=True, marge=Thickness(0, 0, 6, 4))
                Grid.SetColumn(tb, c)
                Grid.SetRow(tb, 0)
                g.Children.Add(tb)
            diam = sorted(self.barres) or [12]
            faces = dict(MUR.FACES)
            dirs = dict(MUR.DIRECTIONS)
            for i, r in enumerate(self.rangs):
                g.RowDefinitions.Add(UI.rd("Auto"))
                ligne = i + 1
                chk = CheckBox()
                chk.IsChecked = bool(r.get("actif", True))
                chk.Margin = Thickness(8, 4, 0, 4)
                cb_d = UI.combo([(u"Ø{0}".format(d), d) for d in diam], 0, 80)
                UI.selectionner_valeur(cb_d, int(r.get("d", 12)))
                tb_e = UI.zone_texte(55, u"{0}".format(r.get("e", 15)))
                vert = r["dir"] == "V"
                tb_h = UI.zone_texte(80, u"{0}".format(r.get("att_haut", 0)))
                tb_b = UI.zone_texte(80, u"{0}".format(r.get("att_bas", 0)))
                tb_h.IsEnabled = tb_b.IsEnabled = vert
                tb_c = UI.zone_texte(220, r.get("commentaire", u""))
                cellules = [chk, UI.texte(faces.get(r["face"], r["face"])),
                            UI.texte(dirs.get(r["dir"], r["dir"])),
                            cb_d, tb_e, tb_h, tb_b, tb_c]
                for c, ctl in enumerate(cellules):
                    if c > 0:
                        ctl.Margin = Thickness(0, 3, 6, 3)
                    Grid.SetColumn(ctl, c)
                    Grid.SetRow(ctl, ligne)
                    g.Children.Add(ctl)
                self.controles.append((r, chk, cb_d, tb_e, tb_h, tb_b, tb_c))
            return g

        # --- Lecture du formulaire -------------------------------------------
        def _nombre(self, tb, defaut, nom):
            txt = (tb.Text or u"").strip().replace(u",", u".")
            if not txt:
                return defaut
            try:
                return float(txt)
            except ValueError:
                raise ValueError(u"Valeur invalide pour {0} : {1}".format(nom, txt))

        def _config(self):
            rangs = []
            for r, chk, cb_d, tb_e, tb_h, tb_b, tb_c in self.controles:
                nom = u"{0} {1}".format(r["face"], r["dir"])
                e = self._nombre(tb_e, 15, u"e " + nom)
                if bool(chk.IsChecked) and e <= 0:
                    raise ValueError(u"Espacement nul : " + nom)
                rangs.append({
                    "face": r["face"], "dir": r["dir"],
                    "actif": bool(chk.IsChecked),
                    "d": UI.valeur_combo(cb_d, 12), "e": e,
                    "att_haut": self._nombre(tb_h, 0, u"attente tête " + nom),
                    "att_bas": self._nombre(tb_b, 0, u"attente pied " + nom),
                    "commentaire": tb_c.Text or u""})
            return {"enrobage": self._nombre(self.tb_enrobage, 3, u"enrobage"),
                    "h_ext": UI.valeur_combo(self.cb_lit, True),
                    "attente": UI.valeur_combo(self.cb_attente, MUR.ATTENTE_AUTO),
                    "partition": self.tb_partition.Text or u"",
                    "rangs": rangs}

        def _enregistrer(self, config):
            self.prefs.update({
                "rangs": config["rangs"], "enrobage": config["enrobage"],
                "h_ext": config["h_ext"], "attente": config["attente"],
                "partition": self.tb_partition.Text or u"",
                "vue3d": bool(self.chk_3d.IsChecked)})
            sauver_prefs(self.prefs)

        def _calculer(self, config):
            """[(info, jeux)], erreurs, nb barres, poids kg."""
            res, erreurs, nb, kg = [], [], 0, 0.0
            for info in self.infos:
                if info.get("erreur"):
                    continue
                jeux, err = MUR.calculer_jeux(info, config)
                erreurs.extend(u"Mur {0} : {1}".format(info["id"], m) for m in err)
                for j in jeux:
                    n = MUR.nombre_barres(j["repartition"], j["e"])
                    lg = math.sqrt(sum((a - b) ** 2 for a, b in
                                       zip(j["p0"], j["p1"]))) / 100.0
                    nb += n
                    kg += n * lg * FER.kg_par_m(j["d"])
                res.append((info, jeux))
            return res, erreurs, nb, kg

        def _apercu(self):
            try:
                config = self._config()
            except ValueError as ex:
                self.lbl_apercu.Text = u"{0}".format(ex)
                return
            res, erreurs, nb, kg = self._calculer(config)
            nb_jeux = sum(len(j) for _, j in res)
            txt = u"Aperçu : {0} mur(s), {1} jeux de barres, {2} barres, " \
                  u"environ {3} kg.".format(len(res), nb_jeux, nb,
                                            FER.fmt_nombre(kg, 0))
            avec = sum(1 for i, _ in res if i.get("dessus"))
            if config["attente"] == MUR.ATTENTE_AUTO:
                txt += u"\nAttentes en tête sur {0} mur(s) avec un mur au-dessus.".format(avec)
            if erreurs:
                txt += u"\n" + u"\n".join(erreurs[:5])
            ignores = [i for i in self.infos if i.get("erreur")]
            if ignores:
                txt += u"\n{0} mur(s) ignoré(s) (voir Remarque).".format(len(ignores))
            self.lbl_apercu.Text = txt

        # --- Creation ---------------------------------------------------------
        def _on_creer(self, sender, e):
            try:
                config = self._config()
            except ValueError as ex:
                MessageBox.Show(u"{0}".format(ex), TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            self._enregistrer(config)
            res, erreurs, nb, kg = self._calculer(config)
            if not any(j for _, j in res):
                MessageBox.Show(u"Aucune barre à créer.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            deja = [i for i, _ in res
                    if (self.existants.get(i["id"]) or (0, 0))[1]]
            if deja:
                r = MessageBox.Show(
                    u"{0} mur(s) ont déjà des armatures non créées par cet "
                    u"outil (elles sont conservées). Continuer ?"
                    .format(len(deja)), TOOL_NAME, MessageBoxButton.YesNo,
                    MessageBoxImage.Question)
                if r != MessageBoxResult.Yes:
                    return
            manquants = sorted(set(j["d"] for _, js in res for j in js
                                   if j["d"] not in self.barres))
            if manquants:
                MessageBox.Show(u"Aucun type de barre Revit pour Ø {0}.".format(
                    u", ".join(u"{0}".format(d) for d in manquants)), TOOL_NAME,
                    MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            vue3d = doc.ActiveView if (self.chk_3d.IsChecked and
                                       isinstance(doc.ActiveView, View3D)) else None
            t = Transaction(doc, u"STR - Ferraillage mur")
            echecs, crees, remplacees, liees = [], [], 0, 0
            try:
                t.Start()
                for info, _ in res:
                    ids, nb_supp, err, nb_c = FR.ferrailler_mur(
                        doc, info, config, self.barres, vue3d)
                    crees.extend(ids)
                    remplacees += nb_supp
                    liees += nb_c
                    echecs.extend(u"Mur {0} : {1}".format(info["id"], m)
                                  for m in err)
                if t.GetStatus() == TransactionStatus.Started:
                    t.Commit()
            except Exception:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                raise
            self.cree = len(crees)
            msg = u"{0} jeux de barres créés ({1} barres), liés au mur " \
                  u"({2} poignées contraintes).".format(len(crees), nb, liees)
            if remplacees:
                msg += u"\n{0} jeu(x) STR précédent(s) remplacé(s).".format(remplacees)
            if echecs:
                msg += u"\n\n{0} échec(s) :\n{1}".format(
                    len(echecs), u"\n".join(echecs[:8]))
            MessageBox.Show(msg, TOOL_NAME, MessageBoxButton.OK,
                            MessageBoxImage.Information if not echecs
                            else MessageBoxImage.Warning)
            if crees:
                ids = NetList[ElementId]()
                for i in crees:
                    ids.Add(i)
                try:
                    uidoc.Selection.SetElementIds(ids)
                except Exception:
                    pass
                self.Close()

    # =========================================================================
    # Main
    # =========================================================================
    murs = murs_selectionnes()
    if murs:
        barres = FR.types_barres(doc)
        if not barres:
            MessageBox.Show(u"Aucun type de barre d'armature dans le projet.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
        else:
            tous = FR.lire_tous_murs(doc)
            infos = []
            for m in murs:
                try:
                    infos.append(FR.preparer_mur(FR.lire_mur(m), tous))
                except Exception as ex:
                    infos.append({"id": FR.idval(m.Id), "elem": m, "type": u"?",
                                  "erreur": u"Lecture impossible : {0}".format(ex)})
            FenetreMur(infos, FR.armatures_par_mur(doc), barres).ShowDialog()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION),
                _ex)
