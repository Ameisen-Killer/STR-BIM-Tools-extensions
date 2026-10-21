# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.2"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Liste de fer"
# =============================================================================
#  v1.0.0 - Liste de fer (SIA 262) depuis les armatures Revit : positions par
#           partition + numero d'armature, cotes exterieures, figures de
#           faconnage, recapitulation par diametre, export Excel (A4) et PDF
#           facultatif via Excel.
#  v1.0.1 - Les armatures illisibles restent signalees meme si aucune
#           position n'a pu etre lue.
#  v1.0.2 - Preferences enregistrees meme avec des accents (JSON ASCII).
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
    import os, io, json, datetime, shutil

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")

    import System
    import System.Windows.Forms as WinForms
    from System.IO import Path as NetPath
    from System.Diagnostics import Process, ProcessStartInfo
    from System.Collections.Generic import List as NetList
    from System.Runtime.InteropServices import Marshal
    from System.Windows import (Window, Thickness, WindowStartupLocation,
                                ResizeMode, MessageBox, MessageBoxButton,
                                MessageBoxImage, HorizontalAlignment,
                                VerticalAlignment, TextWrapping)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, Border,
                                         DataGridTextColumn, DataGridLength,
                                         DataGridLengthUnitType, ScrollViewer,
                                         ScrollBarVisibility, Orientation,
                                         ListBox, DataGridSelectionMode,
                                         DataGridGridLinesVisibility,
                                         DataGridHeadersVisibility)
    from System.Windows.Data import Binding

    from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                                   BuiltInParameter, ElementId)
    from Autodesk.Revit.DB.Structure import (Rebar, RebarInSystem,
                                             MultiplanarOption,
                                             DistributionType)

    import str_ui as UI
    import str_ferraillage as FER
    import str_ferraillage_excel as FXL
    import str_ferraillage_figure as FIG

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{0} | STR BIM Tools by Tony VARIN".format(SCRIPT_VERSION)
    PIED_PAGE = u"{0} v{1} | STR BIM Tools by Tony VARIN".format(
        TOOL_NAME, SCRIPT_VERSION)

    FT_CM = 30.48
    FT_MM = 304.8

    PERIMETRES = [(u"Tout le projet", "projet"),
                  (u"Vue active", "vue"),
                  (u"Sélection courante (armatures ou hôtes)", "selection")]
    MODES = [(u"Somme des cotes extérieures (SIA)", FER.MODE_COTES),
             (u"Longueur de barre Revit", FER.MODE_REVIT)]

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
            with io.open(_PREFS, "w", encoding="utf-8") as f:
                f.write(FER.vers_json(prefs))
        except Exception:
            pass

    def cle_projet():
        try:
            return doc.PathName or doc.Title
        except Exception:
            return doc.Title

    def cartouche_defaut():
        c = dict((k, v) for k, _, v in FXL.CHAMPS_CARTOUCHE)
        c["date"] = datetime.date.today().strftime("%d.%m.%Y")
        try:
            pi = doc.ProjectInformation
            c["objet1"] = pi.Name or u""
            lignes = [l.strip() for l in (pi.Address or u"").splitlines()
                      if l.strip()]
            if lignes:
                c["adresse1"] = lignes[0]
                c["adresse2"] = u", ".join(lignes[1:])
        except Exception:
            pass
        return c

    # =========================================================================
    # Lecture des armatures Revit
    # =========================================================================
    def _txt_param(el, bip):
        try:
            p = el.get_Parameter(bip)
            if p is not None and p.HasValue:
                return p.AsString() or p.AsValueString() or u""
        except Exception:
            pass
        return u""

    def _pt(p):
        return (p.X * FT_CM, p.Y * FT_CM, p.Z * FT_CM)

    def _segments(courbes):
        segs = []
        for c in courbes:
            try:
                nom = c.GetType().Name
                if nom == "Line":
                    segs.append({"type": "L",
                                 "pts": [_pt(c.GetEndPoint(0)),
                                         _pt(c.GetEndPoint(1))],
                                 "l": c.Length * FT_CM})
                else:
                    r = None
                    try:
                        r = c.Radius * FT_CM
                    except Exception:
                        pass
                    segs.append({"type": "A",
                                 "pts": [_pt(p) for p in c.Tessellate()],
                                 "l": c.Length * FT_CM, "r": r})
            except Exception:
                pass
        return segs

    def _courbes(barre, index, sans_cintrage=True):
        """Axe de la barre n° index (rayons supprimes : sommets nets)."""
        try:
            return barre.GetCenterlineCurves(
                False, False, sans_cintrage,
                MultiplanarOption.IncludeOnlyPlanarCurves, index)
        except Exception:
            return barre.GetCenterlineCurves(False, False, sans_cintrage)

    def _diametre_mm(barre):
        bt = doc.GetElement(barre.GetTypeId())
        for attr in ("BarNominalDiameter", "BarDiameter", "BarModelDiameter"):
            try:
                v = getattr(bt, attr)
                if v:
                    return round(v * FT_MM, 1)
            except Exception:
                pass
        try:
            p = barre.get_Parameter(BuiltInParameter.REBAR_BAR_DIAMETER)
            return round(p.AsDouble() * FT_MM, 1)
        except Exception:
            return 0.0

    def _mandrin_mm(barre):
        try:
            v = barre.GetBendData().BendDiameter
            if v:
                return v * FT_MM
        except Exception:
            pass
        try:
            return doc.GetElement(barre.GetTypeId()).StandardBendDiameter * FT_MM
        except Exception:
            return None

    def _indices_existants(barre):
        try:
            n = barre.NumberOfBarPositions
            idx = [i for i in range(n) if barre.DoesBarExistAtPosition(i)]
            if idx:
                return idx
        except Exception:
            pass
        try:
            return list(range(max(1, int(barre.Quantity))))
        except Exception:
            return [0]

    def _longueur_revit_cm(barre, courbes_avec_cintrage=None):
        if courbes_avec_cintrage is not None:
            return sum(c.Length for c in courbes_avec_cintrage) * FT_CM
        try:
            p = barre.get_Parameter(BuiltInParameter.REBAR_ELEM_LENGTH)
            if p is not None and p.HasValue:
                return p.AsDouble() * FT_CM
        except Exception:
            pass
        return None

    def _variable(barre):
        try:
            return barre.DistributionType == DistributionType.VaryingLength
        except Exception:
            return False

    def _idval(eid):
        """Entier d'un ElementId (IntegerValue retire apres Revit 2025)."""
        try:
            return eid.Value
        except Exception:
            return eid.IntegerValue

    def lire_barres(elements):
        """Elements Revit -> (liste de FER.Barre, liste d'erreurs)."""
        barres, erreurs = [], []
        for el in elements:
            eid = _idval(el.Id)
            try:
                partition = _txt_param(el, BuiltInParameter.NUMBER_PARTITION_PARAM)
                numero = _txt_param(el, BuiltInParameter.REBAR_NUMBER)
                remarque = _txt_param(el, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                d_mm = _diametre_mm(el)
                mandrin = _mandrin_mm(el)
                indices = _indices_existants(el)
                if _variable(el):
                    for i in indices:
                        forme = FER.analyser_forme(_segments(_courbes(el, i)), d_mm)
                        lg = _longueur_revit_cm(el, _courbes(el, i, False))
                        barres.append(FER.Barre(eid, partition, numero, 1, d_mm,
                                                forme, lg, mandrin, remarque,
                                                variable=True))
                else:
                    forme = FER.analyser_forme(
                        _segments(_courbes(el, indices[0])), d_mm)
                    barres.append(FER.Barre(eid, partition, numero, len(indices),
                                            d_mm, forme, _longueur_revit_cm(el),
                                            mandrin, remarque))
            except Exception as ex:
                erreurs.append(u"{0} : {1}".format(eid, ex))
        return barres, erreurs

    def collecter(perimetre):
        """Armatures (Rebar / RebarInSystem) du perimetre choisi."""
        if perimetre == "vue":
            col = FilteredElementCollector(doc, doc.ActiveView.Id)
        else:
            col = FilteredElementCollector(doc)
        elements = [e for e in col.OfCategory(BuiltInCategory.OST_Rebar)
                    .WhereElementIsNotElementType().ToElements()
                    if isinstance(e, (Rebar, RebarInSystem))]
        if perimetre == "selection":
            sel = set(_idval(i) for i in uidoc.Selection.GetElementIds())
            garde = []
            for e in elements:
                if _idval(e.Id) in sel:
                    garde.append(e)
                    continue
                try:
                    if _idval(e.GetHostId()) in sel:
                        garde.append(e)
                except Exception:
                    pass
            elements = garde
        return elements

    # =========================================================================
    # Export
    # =========================================================================
    def nom_fichier(cart):
        base = cart.get("no_liste") or u"Liste de fer"
        for ch in u'<>:"/\\|?*':
            base = base.replace(ch, u"_")
        return base.strip() or u"Liste de fer"

    def exporter_pdf(xlsx, pdf):
        """PDF de la 1re feuille via Excel (si installe). True si cree."""
        t = System.Type.GetTypeFromProgID("Excel.Application")
        if t is None:
            return False
        xl = System.Activator.CreateInstance(t)
        wb = None
        try:
            xl.Visible = False
            xl.DisplayAlerts = False
            wb = xl.Workbooks.Open(xlsx)
            try:
                ws = wb.Worksheets[1]
            except Exception:
                ws = wb.Worksheets.Item(1)
            ws.ExportAsFixedFormat(0, pdf)
            return os.path.isfile(pdf)
        finally:
            try:
                if wb is not None:
                    wb.Close(False)
            except Exception:
                pass
            try:
                xl.Quit()
                Marshal.ReleaseComObject(xl)
            except Exception:
                pass

    def ecrire_export(chemin, positions, cart, pdf):
        dossier_img = os.path.join(NetPath.GetTempPath(), u"STR_ListeFer")
        if os.path.isdir(dossier_img):
            shutil.rmtree(dossier_img, True)
        os.makedirs(dossier_img)
        images = {}
        for i, p in enumerate(positions):
            try:
                images[id(p)] = FIG.dessiner_png(
                    os.path.join(dossier_img, u"pos_{0}.png".format(i)),
                    p.forme, p.mandrin_mm,
                    FXL.FIGURE_LARGEUR_PX, FXL.FIGURE_HAUTEUR_PX)
            except Exception:
                pass                    # la cellule affichera les cotes
        try:
            FXL.ecrire_liste(chemin, positions, FER.recapituler(positions),
                             cart, images, PIED_PAGE)
        finally:
            shutil.rmtree(dossier_img, True)
        chemin_pdf = None
        if pdf:
            chemin_pdf = os.path.splitext(chemin)[0] + u".pdf"
            try:
                if not exporter_pdf(chemin, chemin_pdf):
                    chemin_pdf = u""
            except Exception:
                chemin_pdf = u""
        return chemin_pdf

    # =========================================================================
    # Lignes du DataGrid
    # =========================================================================
    class LignePosition(object):
        def __init__(self, p):
            self.pos = p
            self.Partition = p.partition
            self.Pos = p.repere
            self.PosTri = u"{0:08d}".format(_num(p.numero)) + p.repere
            self.Nombre = p.nb
            self.Diametre = p.d_int
            self.Longueur = FER.fmt_nombre(p.longueur_m)
            self.LongueurTri = p.longueur_m
            self.LongueurTot = FER.fmt_nombre(p.longueur_tot_m)
            self.LongueurTotTri = p.longueur_tot_m
            self.Poids = FER.fmt_nombre(p.poids_kg)
            self.PoidsTri = p.poids_kg
            self.Forme = u"Façonnée" if p.faconnee else u"Droite"
            self.Cotes = p.cotes
            self.Remarque = p.remarque
            self.Alertes = u" ; ".join(p.alertes)

    def _num(txt):
        chiffres = u"".join(ch for ch in (txt or u"") if ch.isdigit())
        try:
            return int(chiffres[:8])
        except ValueError:
            return 0

    # =========================================================================
    # Fenetre
    # =========================================================================
    class FenetreListeFer(Window):

        def __init__(self):
            self.Title = TOOL_NAME
            self.Width = 1260
            self.Height = 800
            self.MinWidth = 980
            self.MinHeight = 560
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.ResizeMode = ResizeMode.CanResize
            self.Background = UI.couleur("fond")
            self.prefs = charger_prefs()
            projet = self.prefs.get("projets", {}).get(cle_projet(), {})
            self.cart = cartouche_defaut()
            self.cart.update(projet.get("cartouche", {}))
            self.partitions_exclues = set(projet.get("partitions_exclues", []))
            self.barres = []
            self.erreurs = []
            self.positions = []
            self.cases_partition = {}
            self.champs = {}
            self._construire()
            self.actualiser()

        # --- Construction -----------------------------------------------------
        def _construire(self):
            root = Grid()
            for h in ["Auto", "Auto", "*", "Auto"]:
                root.RowDefinitions.Add(UI.rd(h))
            self.Content = root

            titre = UI.barre_titre(u"{0}  |  Revit {1}".format(
                TOOL_NAME, app.VersionNumber))
            Grid.SetRow(titre, 0)
            root.Children.Add(titre)

            # Barre de filtres
            barre = Border()
            barre.Background = UI.couleur("fond_filtre")
            barre.BorderBrush = UI.couleur("bordure")
            barre.BorderThickness = Thickness(0, 0, 0, 1)
            barre.Padding = Thickness(10, 7, 10, 7)
            sp = StackPanel()
            sp.Orientation = Orientation.Horizontal
            barre.Child = sp
            sp.Children.Add(UI.texte(u"Armatures :", marge=Thickness(0, 0, 6, 0)))
            self.cb_perimetre = UI.combo(PERIMETRES, 0, 250)
            UI.selectionner_valeur(self.cb_perimetre,
                                   self.prefs.get("perimetre", "projet"))
            sp.Children.Add(self.cb_perimetre)
            sp.Children.Add(UI.texte(u"Longueur :", marge=Thickness(16, 0, 6, 0)))
            self.cb_mode = UI.combo(MODES, 0, 230, infobulle=(
                u"Somme des cotes extérieures : convention des listes de fer "
                u"(ex. 60 + 21 + 465 = 5,46 m).\nLongueur de barre Revit : "
                u"paramètre Revit (axe, avec rayons de cintrage)."))
            UI.selectionner_valeur(self.cb_mode,
                                   self.prefs.get("mode", FER.MODE_COTES))
            sp.Children.Add(self.cb_mode)
            btn = UI.footer_btn(u"Actualiser", "appliquer", 100,
                                lambda s, e: self.actualiser())
            btn.Height = 24
            btn.Margin = Thickness(16, 0, 0, 0)
            sp.Children.Add(btn)
            self.cb_mode.SelectionChanged += lambda s, e: self.regrouper()
            Grid.SetRow(barre, 1)
            root.Children.Add(barre)

            # Corps : panneau gauche (partitions + cartouche) / liste
            corps = Grid()
            corps.Margin = Thickness(8)
            corps.ColumnDefinitions.Add(UI.cd(330))
            corps.ColumnDefinitions.Add(UI.cd("*"))
            Grid.SetRow(corps, 2)
            root.Children.Add(corps)

            sv = ScrollViewer()
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            sv.Margin = Thickness(0, 0, 8, 0)
            gauche = StackPanel()
            sv.Content = gauche
            Grid.SetColumn(sv, 0)
            corps.Children.Add(sv)

            gauche.Children.Add(UI.section_hdr(u"Partitions"))
            gb = UI.group_box()
            sp_p = StackPanel()
            gb.Child = sp_p
            boutons = StackPanel()
            boutons.Orientation = Orientation.Horizontal
            boutons.Margin = Thickness(0, 0, 0, 4)
            boutons.Children.Add(UI.small_btn(u"Toutes",
                                              lambda s, e: self._cocher(True)))
            boutons.Children.Add(UI.small_btn(u"Aucune",
                                              lambda s, e: self._cocher(False)))
            sp_p.Children.Add(boutons)
            self.lst_partitions = ListBox()
            self.lst_partitions.MaxHeight = 170
            self.lst_partitions.BorderBrush = UI.couleur("bordure")
            sp_p.Children.Add(self.lst_partitions)
            gauche.Children.Add(gb)

            gauche.Children.Add(UI.section_hdr(u"Cartouche de la liste"))
            gb2 = UI.group_box()
            sp_c = StackPanel()
            gb2.Child = sp_c
            for cle, libelle, _ in FXL.CHAMPS_CARTOUCHE:
                tb = UI.zone_texte(190, self.cart.get(cle, u""))
                self.champs[cle] = tb
                sp_c.Children.Add(UI.ligne_champ(libelle, tb, 110))
            gauche.Children.Add(gb2)

            gauche.Children.Add(UI.section_hdr(u"Export"))
            gb3 = UI.group_box()
            sp_e = StackPanel()
            gb3.Child = sp_e
            self.chk_pdf = UI.checkbox(
                u"Créer aussi le PDF (Excel requis)",
                self.prefs.get("pdf", True),
                u"Le PDF de la 1re feuille est produit par Excel installé "
                u"sur le poste.")
            self.chk_ouvrir = UI.checkbox(u"Ouvrir le fichier après l'export",
                                          self.prefs.get("ouvrir", True))
            sp_e.Children.Add(self.chk_pdf)
            sp_e.Children.Add(self.chk_ouvrir)
            gauche.Children.Add(gb3)

            # Liste des positions
            droite = Grid()
            droite.RowDefinitions.Add(UI.rd("*"))
            droite.RowDefinitions.Add(UI.rd("Auto"))
            Grid.SetColumn(droite, 1)
            corps.Children.Add(droite)
            self.dg = self._datagrid()
            Grid.SetRow(self.dg, 0)
            droite.Children.Add(self.dg)
            self.lbl_recap = UI.texte(u"", 11, marge=Thickness(2, 6, 2, 0))
            self.lbl_recap.TextWrapping = TextWrapping.Wrap
            Grid.SetRow(self.lbl_recap, 1)
            droite.Children.Add(self.lbl_recap)

            # Footer
            footer, sp_btns, grid_f = UI.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 3)
            root.Children.Add(footer)
            for libelle, cle, larg, handler in (
                    (u"Sélectionner", "fermer", 110, self._on_selectionner),
                    (u"Exporter Excel", "exporter", 130, self._on_exporter),
                    (u"Fermer", "annuler", 90, lambda s, e: self.Close())):
                b = UI.footer_btn(libelle, cle, larg, handler)
                b.Margin = Thickness(6, 0, 0, 0)
                sp_btns.Children.Add(b)
            grid_f.Children.Add(sp_btns)
            self.Closing += self._on_fermeture

        def _datagrid(self):
            dg = DataGrid()
            dg.AutoGenerateColumns = False
            dg.IsReadOnly = True
            dg.CanUserSortColumns = True
            dg.CanUserResizeColumns = True
            dg.SelectionMode = DataGridSelectionMode.Extended
            dg.AlternatingRowBackground = UI.couleur("ligne_alternee")
            dg.RowBackground = UI.couleur("fond")
            dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
            dg.HeadersVisibility = DataGridHeadersVisibility.Column
            dg.BorderBrush = UI.couleur("bordure")
            dg.FontSize = 12
            colonnes = [
                (u"Partition", "Partition", None, 130),
                (u"Pos.", "Pos", "PosTri", 55),
                (u"Nombre", "Nombre", None, 65),
                (u"ø", "Diametre", None, 45),
                (u"Long. m", "Longueur", "LongueurTri", 70),
                (u"Long. tot. m", "LongueurTot", "LongueurTotTri", 85),
                (u"Poids kg", "Poids", "PoidsTri", 80),
                (u"Forme", "Forme", None, 75),
                (u"Cotes ext. cm", "Cotes", None, 150),
                (u"Remarque", "Remarque", None, 150),
                (u"Alertes", "Alertes", None, 0),
            ]
            for entete, prop, tri, larg in colonnes:
                col = DataGridTextColumn()
                col.Header = entete
                col.Binding = Binding(prop)
                if tri:
                    col.SortMemberPath = tri
                if larg:
                    col.Width = DataGridLength(larg)
                else:
                    col.Width = DataGridLength(1, DataGridLengthUnitType.Star)
                dg.Columns.Add(col)
            return dg

        # --- Donnees ----------------------------------------------------------
        def actualiser(self):
            perimetre = UI.valeur_combo(self.cb_perimetre, "projet")
            try:
                elements = collecter(perimetre)
            except Exception as ex:
                elements = []
                MessageBox.Show(u"Lecture des armatures impossible :\n{0}".format(ex),
                                TOOL_NAME, MessageBoxButton.OK,
                                MessageBoxImage.Error)
            self.barres, self.erreurs = lire_barres(elements)
            self._remplir_partitions()
            self.regrouper()

        def _remplir_partitions(self):
            self.lst_partitions.Items.Clear()
            self.cases_partition = {}
            noms = sorted(set(b.partition for b in self.barres),
                          key=FER.cle_naturelle)
            for nom in noms:
                cb = UI.checkbox(nom or u"(sans partition)",
                                 nom not in self.partitions_exclues)
                cb.Checked += lambda s, e: self._maj_partitions()
                cb.Unchecked += lambda s, e: self._maj_partitions()
                self.cases_partition[nom] = cb
                self.lst_partitions.Items.Add(cb)

        def _cocher(self, etat):
            for cb in self.cases_partition.values():
                cb.IsChecked = etat
            self._maj_partitions()

        def _maj_partitions(self):
            for nom, cb in self.cases_partition.items():
                if cb.IsChecked:
                    self.partitions_exclues.discard(nom)
                else:
                    self.partitions_exclues.add(nom)
            self.regrouper()

        def regrouper(self):
            mode = UI.valeur_combo(self.cb_mode, FER.MODE_COTES)
            barres = [b for b in self.barres
                      if b.partition not in self.partitions_exclues]
            self.positions = FER.regrouper(barres, mode)
            self.dg.ItemsSource = None
            self.dg.ItemsSource = [LignePosition(p) for p in self.positions]
            rec = FER.recapituler(self.positions)
            parts = [u"{0} positions".format(rec["nb_positions"]),
                     u"{0} m".format(FER.fmt_nombre(rec["total"][0])),
                     u"{0} kg".format(FER.fmt_nombre(rec["total"][1])),
                     u"ø moyen {0}".format(FER.fmt_nombre(rec["d_moyen"]))]
            par_d = {}
            for d, _, lg, pds in rec["droites"] + rec["faconnees"]:
                par_d[d] = par_d.get(d, 0.0) + pds
            detail = u"   ".join(u"ø{0} : {1} kg".format(d, FER.fmt_nombre(par_d[d]))
                                 for d in sorted(par_d))
            txt = u"  |  ".join(parts)
            if detail:
                txt += u"\n" + detail
            nb_alertes = sum(1 for p in self.positions if p.alertes)
            if nb_alertes:
                txt += u"\n{0} position(s) avec alerte (colonne Alertes).".format(
                    nb_alertes)
            if self.erreurs:
                txt += u"\n{0} armature(s) illisible(s) ignorée(s) : {1}".format(
                    len(self.erreurs), u" ; ".join(self.erreurs[:3]))
            if not self.barres:
                txt = (u"Aucune armature Revit (catégorie Armature structurelle) "
                       u"trouvée dans ce périmètre.")
                if self.erreurs:
                    txt += u"\n{0} armature(s) illisible(s) : {1}".format(
                        len(self.erreurs), u" ; ".join(self.erreurs[:3]))
            self.lbl_recap.Text = txt

        # --- Actions ----------------------------------------------------------
        def _lire_cartouche(self):
            for cle, tb in self.champs.items():
                self.cart[cle] = tb.Text or u""
            return dict(self.cart)

        def _enregistrer(self):
            self._lire_cartouche()
            projets = self.prefs.setdefault("projets", {})
            projets[cle_projet()] = {
                "cartouche": self.cart,
                "partitions_exclues": sorted(self.partitions_exclues)}
            self.prefs["perimetre"] = UI.valeur_combo(self.cb_perimetre, "projet")
            self.prefs["mode"] = UI.valeur_combo(self.cb_mode, FER.MODE_COTES)
            self.prefs["pdf"] = bool(self.chk_pdf.IsChecked)
            self.prefs["ouvrir"] = bool(self.chk_ouvrir.IsChecked)
            sauver_prefs(self.prefs)

        def _on_fermeture(self, sender, e):
            self._enregistrer()

        def _on_selectionner(self, sender, e):
            lignes = list(self.dg.SelectedItems)
            if not lignes:
                MessageBox.Show(u"Sélectionne d'abord une ou plusieurs positions.",
                                TOOL_NAME, MessageBoxButton.OK,
                                MessageBoxImage.Information)
                return
            ids = NetList[ElementId]()
            vus = set()
            for l in lignes:
                for i in l.pos.ids:
                    if i not in vus:
                        vus.add(i)
                        ids.Add(ElementId(i))
            try:
                uidoc.Selection.SetElementIds(ids)
                uidoc.ShowElements(ids)
            except Exception as ex:
                MessageBox.Show(u"Sélection impossible : {0}".format(ex),
                                TOOL_NAME, MessageBoxButton.OK,
                                MessageBoxImage.Warning)

        def _on_exporter(self, sender, e):
            if not self.positions:
                MessageBox.Show(u"Aucune position à exporter.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            self._enregistrer()
            cart = self._lire_cartouche()
            dlg = WinForms.SaveFileDialog()
            dlg.Title = TOOL_NAME
            dlg.Filter = u"Classeur Excel (*.xlsx)|*.xlsx"
            dlg.FileName = nom_fichier(cart) + u".xlsx"
            dossier = self.prefs.get("dossier", u"")
            if dossier and os.path.isdir(dossier):
                dlg.InitialDirectory = dossier
            if dlg.ShowDialog() != WinForms.DialogResult.OK:
                return
            chemin = dlg.FileName
            self.prefs["dossier"] = os.path.dirname(chemin)
            sauver_prefs(self.prefs)
            try:
                pdf = ecrire_export(chemin, self.positions, cart,
                                    bool(self.chk_pdf.IsChecked))
            except Exception as ex:
                MessageBox.Show(u"Export impossible :\n{0}\n\n{1}".format(
                    ex, traceback.format_exc()), TOOL_NAME,
                    MessageBoxButton.OK, MessageBoxImage.Error)
                return
            msg = u"Liste de fer exportée :\n{0}".format(chemin)
            if pdf:
                msg += u"\n\nPDF :\n{0}".format(pdf)
            elif pdf == u"":
                msg += (u"\n\nPDF non créé (Excel absent ou refus). "
                        u"Imprime la 1re feuille en PDF depuis Excel.")
            MessageBox.Show(msg, TOOL_NAME, MessageBoxButton.OK,
                            MessageBoxImage.Information)
            if self.chk_ouvrir.IsChecked:
                try:
                    psi = ProcessStartInfo(pdf or chemin)
                    psi.UseShellExecute = True
                    Process.Start(psi)
                except Exception:
                    pass

    FenetreListeFer().ShowDialog()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION),
                _ex)
