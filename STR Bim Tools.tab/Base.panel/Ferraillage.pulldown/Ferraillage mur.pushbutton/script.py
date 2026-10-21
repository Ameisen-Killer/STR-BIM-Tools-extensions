# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Ferraillage mur"
# =============================================================================
#  v1.0.0 - Ferraillage courant des murs droits : barres verticales et
#           horizontales par face, enrobage, ordre des lits, attentes en tete
#           (mur du dessus detecte) et en pied. Jeux Revit a espacement
#           maximal, partition et commentaire renseignes pour la liste de fer.
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

    from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                                   BuiltInParameter, ElementId, Wall, Line,
                                   XYZ, Curve, View3D, Transaction,
                                   TransactionStatus)
    from Autodesk.Revit.DB.Structure import (Rebar, RebarBarType, RebarStyle,
                                             RebarHookOrientation)
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
    from Autodesk.Revit.Exceptions import OperationCanceledException

    import str_ui as UI
    import str_ferraillage as FER
    import str_ferraillage_mur as MUR

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{0} | STR BIM Tools by Tony VARIN".format(SCRIPT_VERSION)
    FT_CM = 30.48
    FT_MM = 304.8

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
    # Types de barres
    # =========================================================================
    def diametre_type_mm(bt):
        for attr in ("BarNominalDiameter", "BarDiameter", "BarModelDiameter"):
            try:
                v = getattr(bt, attr)
                if v:
                    return round(v * FT_MM, 1)
            except Exception:
                pass
        return 0.0

    def types_barres():
        """{diametre mm (int): RebarBarType}, un type par diametre."""
        res = {}
        for bt in FilteredElementCollector(doc).OfClass(RebarBarType):
            d = int(round(diametre_type_mm(bt)))
            if d > 0 and d not in res:
                res[d] = bt
        return res

    # =========================================================================
    # Lecture des murs
    # =========================================================================
    def _idval(eid):
        try:
            return eid.Value
        except Exception:
            return eid.IntegerValue

    def _xy(p):
        return (p.X * FT_CM, p.Y * FT_CM)

    def lire_mur(w):
        """Mur Revit -> dict geometrique (cm) pour str_ferraillage_mur."""
        info = {"id": _idval(w.Id), "elem": w, "erreur": u""}
        try:
            info["type"] = w.WallType.Name
        except Exception:
            info["type"] = u"?"
        courbe = w.Location.Curve if hasattr(w.Location, "Curve") else None
        if courbe is None or not isinstance(courbe, Line):
            info["erreur"] = u"Mur courbe ou sans axe : non géré"
            return info
        p0, p1 = courbe.GetEndPoint(0), courbe.GetEndPoint(1)
        d = (p1 - p0).Normalize()
        n = w.Orientation
        ep = w.Width * FT_CM
        # Ligne de justification -> axe central.
        decal = 0.0
        try:
            cle = w.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
            if cle in (2, 4):
                decal = -ep / 2.0
            elif cle in (3, 5):
                decal = ep / 2.0
        except Exception:
            pass
        o = _xy(p0)
        bb = w.get_BoundingBox(None)
        if bb is None:
            info["erreur"] = u"Géométrie introuvable"
            return info
        info.update({
            "o": (o[0] + n.X * decal, o[1] + n.Y * decal),
            "u": (d.X, d.Y), "n": (n.X, n.Y),
            "longueur": courbe.Length * FT_CM, "ep": ep,
            "z_bas": bb.Min.Z * FT_CM, "z_haut": bb.Max.Z * FT_CM,
        })
        return info

    def detecter_mur_dessus(info, tous):
        """Un mur dont le pied est a la tete de celui-ci et qui le recouvre."""
        if info.get("erreur"):
            return None
        ux, uy = info["u"]
        nx, ny = info["n"]
        ox, oy = info["o"]
        for autre in tous:
            if autre["id"] == info["id"] or autre.get("erreur"):
                continue
            # Pied du mur du dessus : a la tete de celui-ci, ou au-dessus
            # d'une dalle intermediaire (jusqu'a 60 cm).
            ecart = autre["z_bas"] - info["z_haut"]
            if ecart < -5.0 or ecart > 60.0:
                continue
            ax, ay = autre["o"]
            bx = ax + autre["u"][0] * autre["longueur"]
            by = ay + autre["u"][1] * autre["longueur"]
            # Recouvrement le long de l'axe et ecart transversal.
            s0 = (ax - ox) * ux + (ay - oy) * uy
            s1 = (bx - ox) * ux + (by - oy) * uy
            t0 = (ax - ox) * nx + (ay - oy) * ny
            t1 = (bx - ox) * nx + (by - oy) * ny
            recouvre = min(max(s0, s1), info["longueur"]) - max(min(s0, s1), 0.0)
            if recouvre > 10.0 and max(abs(t0), abs(t1)) < \
                    (info["ep"] + autre["ep"]) / 2.0:
                return autre
        return None

    def armatures_existantes():
        """{id mur: nombre d'armatures hebergees}."""
        res = {}
        for rb in FilteredElementCollector(doc).OfClass(Rebar):
            try:
                h = _idval(rb.GetHostId())
                res[h] = res.get(h, 0) + 1
            except Exception:
                pass
        return res

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
    # Creation des armatures
    # =========================================================================
    def _xyz(p):
        return XYZ(p[0] / FT_CM, p[1] / FT_CM, p[2] / FT_CM)

    def creer_jeu(mur, jeu, bt, partition, vue3d):
        ligne = Line.CreateBound(_xyz(jeu["p0"]), _xyz(jeu["p1"]))
        courbes = NetList[Curve]()
        courbes.Add(ligne)
        norm = XYZ(jeu["norm"][0], jeu["norm"][1], jeu["norm"][2])
        rb = Rebar.CreateFromCurves(doc, RebarStyle.Standard, bt, None, None,
                                    mur, norm, courbes,
                                    RebarHookOrientation.Left,
                                    RebarHookOrientation.Left, True, True)
        rb.GetShapeDrivenAccessor().SetLayoutAsMaximumSpacing(
            jeu["e"] / FT_CM, jeu["repartition"] / FT_CM, True, True, True)
        for bip, val in ((BuiltInParameter.NUMBER_PARTITION_PARAM, partition),
                         (BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                          jeu["commentaire"])):
            try:
                p = rb.get_Parameter(bip)
                if p is not None and not p.IsReadOnly and val:
                    p.Set(val)
            except Exception:
                pass
        if vue3d is not None:
            try:
                rb.SetUnobscuredInView(vue3d, True)
            except Exception:
                pass
        return rb

    # =========================================================================
    # Lignes du tableau des murs
    # =========================================================================
    class LigneMur(object):
        def __init__(self, info, nb_existants):
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
            self.Existants = nb_existants or u""
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
            self.rangs = self.prefs.get("rangs") or MUR.rangs_defaut(
                12 if 12 in barres else (sorted(barres)[0] if barres else 12))
            self.controles = []
            self.cree = 0
            self._construire()
            self._apercu()

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
                self.prefs.get("enrobage", 3)))
            sp.Children.Add(UI.ligne_champ(u"Enrobage (cm)", self.tb_enrobage, 170))
            self.cb_lit = UI.combo(LITS, 0, 260)
            UI.selectionner_valeur(self.cb_lit, self.prefs.get("h_ext", True))
            sp.Children.Add(UI.ligne_champ(u"Lit extérieur", self.cb_lit, 170))
            self.cb_attente = UI.combo(ATTENTES, 0, 260)
            UI.selectionner_valeur(self.cb_attente,
                                   self.prefs.get("attente", MUR.ATTENTE_AUTO))
            sp.Children.Add(UI.ligne_champ(u"Attentes en tête", self.cb_attente, 170))
            self.tb_partition = UI.zone_texte(260, self.prefs.get(
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
                info["mur_dessus"] = info.get("dessus") is not None
                if info["mur_dessus"]:
                    info["z_dessus"] = info["dessus"]["z_bas"]
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
            deja = [i for i, _ in res if self.existants.get(i["id"])]
            if deja:
                r = MessageBox.Show(
                    u"{0} mur(s) ont déjà des armatures. Ajouter quand même ?"
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
            partition = self.tb_partition.Text or u""
            t = Transaction(doc, u"STR - Ferraillage mur")
            echecs = []
            crees = []
            try:
                t.Start()
                for info, jeux in res:
                    for j in jeux:
                        try:
                            rb = creer_jeu(info["elem"], j, self.barres[j["d"]],
                                           partition, vue3d)
                            crees.append(rb.Id)
                        except Exception as ex:
                            echecs.append(u"Mur {0} {1}/{2} : {3}".format(
                                info["id"], j["face"], j["dir"], ex))
                if t.GetStatus() == TransactionStatus.Started:
                    t.Commit()
            except Exception:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                raise
            self.cree = len(crees)
            msg = u"{0} jeux de barres créés ({1} barres).".format(len(crees), nb)
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
        barres = types_barres()
        if not barres:
            MessageBox.Show(u"Aucun type de barre d'armature dans le projet.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
        else:
            infos = []
            for m in murs:
                try:
                    infos.append(lire_mur(m))
                except Exception as ex:
                    infos.append({"id": _idval(m.Id), "elem": m, "type": u"?",
                                  "erreur": u"Lecture impossible : {0}".format(ex)})
            # Murs candidats au-dessus : tous les murs du projet.
            tous = []
            for w in FilteredElementCollector(doc).OfClass(Wall).ToElements():
                try:
                    tous.append(lire_mur(w))
                except Exception:
                    pass                # mur-rideau, empile... : ignore
            for info in infos:
                info["dessus"] = detecter_mur_dessus(info, tous)
            FenetreMur(infos, armatures_existantes(), barres).ShowDialog()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION),
                _ex)
