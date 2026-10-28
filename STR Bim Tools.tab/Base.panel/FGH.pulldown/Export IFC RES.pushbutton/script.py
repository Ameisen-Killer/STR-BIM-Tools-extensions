# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "FGH - Export IFC RES"
# =============================================================================
# Prepare les fichiers que l'ingenieur ouvre sur str-bim-tools.com/fgh/ pour
# valider les reservations sans Revit :
#   - <maquette>_RES.ifc       : reservations FGH_RES* de la maquette active,
#                                avec le jeu de proprietes STR_FGH_RES (cle
#                                ADN, UniqueId, demande, PVA_RES_VAL_*) ;
#   - <maquette>_STR_light.ifc : elements porteurs de la maquette active
#                                (murs, dalles, poteaux, poutres, fondations,
#                                escaliers), sans jeux de proprietes.
# Lancer dans la maquette RES pour le premier, dans la maquette STR pour le
# second. Une vue 3D temporaire filtre ce qui part : tout est annule apres
# l'export, la maquette n'est pas modifiee. Voir lib/fgh_res.py.
# =============================================================================

import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + u"{}".format(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


try:
    import io, os, json, datetime
    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase"); clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")
    import System
    import System.Windows as SW
    from System.Windows import (Window, Thickness, MessageBox, MessageBoxButton,
                                MessageBoxImage, MessageBoxResult, WindowStartupLocation)
    from System.Windows.Controls import Grid, StackPanel, Orientation, TextBlock
    from System.Windows.Forms import FolderBrowserDialog, DialogResult
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, ElementId,
                                   Transaction, TransactionGroup, TransactionStatus,
                                   View3D, ViewFamilyType, ViewFamily, CategoryType,
                                   IFailuresPreprocessor, FailureProcessingResult,
                                   FailureSeverity)
    import str_ifc
    import str_ui
    import str_progression
    import fgh_res

    doc = __revit__.ActiveUIDocument.Document
    app = __revit__.Application

    _PREFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fgh_res_prefs.json")

    # Elements porteurs gardes dans l'IFC light de la structure
    CATS_STRUCTURE = [BuiltInCategory.OST_Walls, BuiltInCategory.OST_Floors,
                      BuiltInCategory.OST_StructuralColumns,
                      BuiltInCategory.OST_StructuralFraming,
                      BuiltInCategory.OST_StructuralFoundation,
                      BuiltInCategory.OST_Roofs, BuiltInCategory.OST_Stairs,
                      BuiltInCategory.OST_Ramps]

    # Configuration verifiee de lib/str_ifc.py (IFC 2x3 CV 2.0), allegee :
    # aucun jeu de proprietes (celui des reservations est ajoute apres coup).
    def reglages_export():
        r = str_ifc.reglages_par_defaut()
        r.update({"vue_seule": True, "psets_ifc": False, "psets_revit": False,
                  "quantites": False, "psets_materiaux": False, "guid_ifc": False,
                  "elements_2d": False, "pieces_vue": False})
        return r

    # --- Preferences -----------------------------------------------------------
    def lire_prefs():
        try:
            with io.open(_PREFS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def ecrire_prefs(p):
        try:
            with io.open(_PREFS, "w", encoding="utf-8") as f:
                f.write(u"{}".format(json.dumps(p, ensure_ascii=False, indent=2)))
        except Exception:
            pass

    def radical(suffixe):
        base = u"".join(c if (c.isalnum() or c in u"-_.") else u"_" for c in (doc.Title or u"maquette"))
        return u"{}_{}".format(base, suffixe)

    # --- Inventaire ---------------------------------------------------------------
    def ids_categories(cats):
        out = set()
        for c in cats:
            try:
                out.add(fgh_res.id_int(ElementId(c)))
            except Exception:
                pass
        return out

    def elements_structure():
        out = []
        for c in CATS_STRUCTURE:
            try:
                out.extend(FilteredElementCollector(doc).OfCategory(c)
                           .WhereElementIsNotElementType().ToElementIds())
            except Exception:
                pass
        return out

    # --- Export -------------------------------------------------------------------
    class Echecs(IFailuresPreprocessor):
        """Avertissements effaces, erreur = annulation, sans boite modale."""
        def __init__(self):
            self.messages = []

        def PreprocessFailures(self, acc):
            erreur = False
            for msg in list(acc.GetFailureMessages()):
                try:
                    self.messages.append(msg.GetDescriptionText())
                except Exception:
                    pass
                if msg.GetSeverity() == FailureSeverity.Warning:
                    try:
                        acc.DeleteWarning(msg)
                    except Exception:
                        pass
                else:
                    erreur = True
            return (FailureProcessingResult.ProceedWithRollBack if erreur
                    else FailureProcessingResult.Continue)

    # Barre de progression par etapes : l'export IFC de Revit est un seul appel
    # bloquant, sans avancement interne, donc on annonce chaque etape avant de la lancer.
    _prog = {"p": None, "n": 0, "t0": None}

    def etape(texte):
        p = _prog["p"]
        if p is None:
            return
        _prog["n"] += 1
        p.etape(u"{}\nDémarré à {}".format(texte, datetime.datetime.now().strftime("%H:%M:%S")), _prog["n"] - 1)

    def exporter(dossier, nom, cats_gardees, garder, quoi=u""):
        """Vue 3D temporaire qui ne montre que ce qu'il faut, export IFC filtre
        sur elle, puis tout est annule. Retourne (chemin ou None, messages)."""
        etape(u"{} : préparation de la vue 3D temporaire…".format(quoi))
        chemin = os.path.join(dossier, nom + u".ifc")
        if os.path.isfile(chemin):
            os.remove(chemin)
        tg = TransactionGroup(doc, u"STR - FGH : export IFC")
        tg.Start()
        messages = []
        try:
            t = Transaction(doc, u"STR - FGH : vue temporaire")
            t.Start()
            vft = [v for v in FilteredElementCollector(doc).OfClass(ViewFamilyType)
                   if v.ViewFamily == ViewFamily.ThreeDimensional][0]
            vue = View3D.CreateIsometric(doc, vft.Id)
            try:
                vue.ViewTemplateId = ElementId.InvalidElementId
            except Exception:
                pass
            try:
                vue.IsSectionBoxActive = False
            except Exception:
                pass
            for cat in doc.Settings.Categories:
                try:
                    if fgh_res.id_int(cat.Id) in cats_gardees:
                        continue
                    if cat.CategoryType == CategoryType.Model and vue.CanCategoryBeHidden(cat.Id):
                        vue.SetCategoryHidden(cat.Id, True)
                except Exception:
                    pass
            t.Commit()

            etape(u"{} : filtrage des éléments de la vue…".format(quoi))
            t = Transaction(doc, u"STR - FGH : filtre de la vue")
            t.Start()
            cacher = [e.Id for e in FilteredElementCollector(doc, vue.Id)
                      .WhereElementIsNotElementType().ToElements()
                      if not garder(e) and e.CanBeHidden(vue)]
            if cacher:
                vue.HideElements(List[ElementId](cacher))
            t.Commit()

            etape(u"{} : export IFC par Revit (étape la plus longue, Revit ne répond plus pendant ce temps)…".format(quoi))
            t = Transaction(doc, u"STR - FGH : export IFC")
            t.Start()
            ech = Echecs()
            try:
                o = t.GetFailureHandlingOptions().SetFailuresPreprocessor(ech)
                t.SetFailureHandlingOptions(o)
            except Exception:
                pass
            try:
                opts, _cfg = str_ifc.construire_options(reglages_export(),
                                                        fgh_res.id_int(vue.Id), messages)
                doc.Export(dossier, nom, opts)
            finally:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                messages.extend(ech.messages)
        finally:
            tg.RollBack()
        return (chemin if os.path.isfile(chemin) else None), messages

    def exporter_reservations(dossier):
        res = fgh_res.reservations(doc)
        if not res:
            return u"Réservations : aucune famille FGH_RES* dans cette maquette."
        ids = set(fgh_res.id_int(e.Id) for e in res)
        cats = set(fgh_res.id_int(e.Category.Id) for e in res if e.Category is not None)
        def garder(e):
            return fgh_res.id_int(e.Id) in ids
        chemin, msgs = exporter(dossier, radical(u"RES"), cats, garder,
                                u"Réservations ({})".format(len(res)))
        if not chemin:
            return u"Réservations : l'export n'a produit aucun fichier.\n" + u"\n".join(msgs[:5])
        etape(u"Réservations : ajout des données de validation dans l'IFC…")
        quand = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        par_eid = dict((u"{}".format(fgh_res.id_int(e.Id)), fgh_res.donnees(doc, e, quand)) for e in res)
        n, absents = fgh_res.injecter(chemin, par_eid)
        sans_adn = sum(1 for e in res if not fgh_res.adn(e))
        txt = u"Réservations : {} exportée(s) → {}".format(len(par_eid) - len(absents), os.path.basename(chemin))
        n_sup = len(fgh_res.reservations(doc, avec_supprimees=True)) - len(res)
        if n_sup:
            txt += u"\n   {} supprimée(s) ({} coché) non exportée(s)".format(n_sup, fgh_res.SUPPRIME_PARAM)
        if absents:
            txt += u"\n   {} sans géométrie dans l'IFC (ElementId {}{})".format(
                len(absents), u", ".join(absents[:8]), u"…" if len(absents) > 8 else u"")
        if sans_adn:
            txt += u"\n   ⚠ {} sans {} : elles ne pourront pas être retrouvées par leur clé.".format(
                sans_adn, fgh_res.ADN_PARAM)
        return txt

    def exporter_structure(dossier):
        ids = set(fgh_res.id_int(i) for i in elements_structure())
        if not ids:
            return u"Structure : aucun élément porteur dans cette maquette."
        def garder(e):
            return fgh_res.id_int(e.Id) in ids and not fgh_res.est_reservation(e)
        chemin, msgs = exporter(dossier, radical(u"STR_light"), ids_categories(CATS_STRUCTURE), garder,
                                u"Structure light ({} éléments)".format(len(ids)))
        if not chemin:
            return u"Structure : l'export n'a produit aucun fichier.\n" + u"\n".join(msgs[:5])
        return u"Structure light : {} élément(s) → {} ({:.1f} Mo)".format(
            len(ids), os.path.basename(chemin), os.path.getsize(chemin)/1048576.0)

    # --- Fenetre ------------------------------------------------------------------
    def fenetre():
        prefs = lire_prefs()
        n_res = len(fgh_res.reservations(doc))
        n_sup = len(fgh_res.reservations(doc, avec_supprimees=True)) - n_res
        n_str = len(elements_structure())

        win = Window()
        win.Title = u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION)
        win.Width = 640; win.SizeToContent = SW.SizeToContent.Height
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen
        win.ResizeMode = SW.ResizeMode.NoResize
        win.Background = str_ui.couleur("fond")
        root = Grid()
        for h in ("Auto", "Auto", "Auto"):
            root.RowDefinitions.Add(str_ui.rd(h))
        win.Content = root

        titre = str_ui.barre_titre(u"{}  |  {}  |  Revit {}".format(TOOL_NAME, doc.Title, app.VersionNumber))
        Grid.SetRow(titre, 0); root.Children.Add(titre)

        corps = StackPanel(); corps.Margin = Thickness(14, 10, 14, 6)
        Grid.SetRow(corps, 1); root.Children.Add(corps)
        corps.Children.Add(str_ui.section_hdr(u"Fichiers à créer pour str-bim-tools.com/fgh/"))
        gb = str_ui.group_box(); sp = StackPanel(); gb.Child = sp; corps.Children.Add(gb)
        cb_res = str_ui.checkbox(u"Réservations FGH_RES de cette maquette ({}{})  →  {}.ifc".format(
            n_res, u", {} supprimée(s) écartée(s)".format(n_sup) if n_sup else u"", radical(u"RES")), n_res > 0,
            u"À lancer dans la maquette RES : c'est elle que l'ingénieur valide.")
        cb_res.IsEnabled = n_res > 0
        cb_str = str_ui.checkbox(u"Structure light de cette maquette ({} éléments porteurs)  →  {}.ifc".format(
            n_str, radical(u"STR_light")), n_str > 0 and n_res == 0,
            u"À lancer dans la maquette STR : murs, dalles, poteaux, poutres, fondations, escaliers.")
        cb_str.IsEnabled = n_str > 0
        sp.Children.Add(cb_res); sp.Children.Add(cb_str)

        corps.Children.Add(str_ui.section_hdr(u"Dossier"))
        ligne = StackPanel(); ligne.Orientation = Orientation.Horizontal
        tb_dos = str_ui.zone_texte(470, prefs.get(u"dossier") or os.path.join(
            os.environ.get("USERPROFILE", u""), u"Documents"))
        def parcourir(s, e):
            d = FolderBrowserDialog(); d.SelectedPath = tb_dos.Text
            if d.ShowDialog() == DialogResult.OK:
                tb_dos.Text = d.SelectedPath
        b = str_ui.small_btn(u"Parcourir…", parcourir); b.Margin = Thickness(6, 0, 0, 0)
        ligne.Children.Add(tb_dos); ligne.Children.Add(b); corps.Children.Add(ligne)

        note = TextBlock(); note.TextWrapping = SW.TextWrapping.Wrap; note.FontSize = 11
        note.Foreground = str_ui.couleur("texte_gris"); note.Margin = Thickness(0, 10, 0, 4)
        note.Text = (u"Ensuite : l'ingénieur ouvre {} et y glisse les deux IFC. Il valide ou refuse les "
                     u"réservations ; ses changements partent dans un fichier JSON que tu appliques "
                     u"avec « Import Validation RES » dans la maquette RES. La maquette n'est pas "
                     u"modifiée par cet export.").format(fgh_res.PAGE_WEB)
        corps.Children.Add(note)
        lbl_res = TextBlock(); lbl_res.TextWrapping = SW.TextWrapping.Wrap; lbl_res.FontSize = 11.5
        lbl_res.Margin = Thickness(0, 4, 0, 4); corps.Children.Add(lbl_res)

        footer, sp_btns, grid_f = str_ui.make_footer(SCRIPT_VERSION)
        Grid.SetRow(footer, 2); root.Children.Add(footer)

        def ouvrir_page(s, e):
            try:
                System.Diagnostics.Process.Start(fgh_res.PAGE_WEB)
            except Exception:
                pass

        def go(s, e):
            dossier = (tb_dos.Text or u"").strip()
            if not dossier or not os.path.isdir(dossier):
                MessageBox.Show(u"Choisis un dossier existant.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            if not (cb_res.IsChecked or cb_str.IsChecked):
                return
            prefs[u"dossier"] = dossier; ecrire_prefs(prefs)
            lignes = []
            win.Cursor = SW.Input.Cursors.Wait
            prog = str_progression.Progression(u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
                                               u"STR BIM Tools by Tony Varin")
            _prog["p"] = prog; _prog["n"] = 0
            prog.win.Height = 190; prog.win.Width = 520
            prog.lbl.TextWrapping = SW.TextWrapping.Wrap
            try:
                prog.demarrer((4 if cb_res.IsChecked else 0) + (3 if cb_str.IsChecked else 0),
                              u"Préparation…")
                if cb_res.IsChecked:
                    lignes.append(exporter_reservations(dossier))
                if cb_str.IsChecked:
                    lignes.append(exporter_structure(dossier))
            except Exception as ex:
                lignes.append(u"Erreur : {}".format(ex))
            finally:
                _prog["p"] = None
                prog.fin()
                win.Cursor = None
            lbl_res.Text = u"\n".join(lignes)
            lbl_res.Foreground = str_ui.couleur("ok")
            try:
                System.Diagnostics.Process.Start(dossier)
            except Exception:
                pass

        sp_btns.Children.Add(str_ui.footer_btn(u"Fermer", "fermer", 90, lambda s, e: win.Close()))
        bp = str_ui.footer_btn(u"Ouvrir la page web", "secondaire", 150, ouvrir_page)
        bp.Foreground = str_ui.couleur("texte"); bp.Margin = Thickness(6, 0, 0, 0)
        sp_btns.Children.Add(bp)
        bg = str_ui.footer_btn(u"Exporter", "appliquer", 110, go); bg.Margin = Thickness(6, 0, 0, 0)
        sp_btns.Children.Add(bg)
        grid_f.Children.Add(sp_btns)
        return win

    fenetre().ShowDialog()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
