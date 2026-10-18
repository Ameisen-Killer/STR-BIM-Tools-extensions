# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Quantification Escaliers"
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
    import sys, os, io, json

    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase");           clr.AddReference("System.Windows.Forms")
    import System, System.IO, System.Diagnostics
    import System.Windows.Forms as WinForms
    import System.Windows as SW
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode,
                                FontWeights, TextWrapping)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, RowDefinition,
                                         ColumnDefinition, ScrollViewer, ScrollBarVisibility,
                                         DataGridLength, DataGridLengthUnitType, DataGridRow,
                                         Orientation, DataGridHeadersVisibility,
                                         DataGridGridLinesVisibility, DataGridSelectionMode,
                                         TextBox)
    from System.Windows.Controls.Primitives import DataGridColumnHeader
    from System.Windows.Threading import DispatcherPriority
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Data import Binding
    from System.Collections.ObjectModel import ObservableCollection

    from Autodesk.Revit.DB import (
        FilteredElementCollector, BuiltInCategory, BuiltInParameter,
        UnitUtils, UnitTypeId, ElementId, Transaction,
        View3D, ViewFamilyType, ViewFamily, BoundingBoxXYZ, XYZ,
    )

    try:
        from Autodesk.Revit.DB.Architecture import Stairs, StairsRun, StairsLanding
        HAS_STAIRS_API = True
    except ImportError:
        HAS_STAIRS_API = False

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app   = __revit__.Application

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    # =========================================================================
    # Helpers UI
    # =========================================================================
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    def _rd(h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto)
        return rd

    def _footer_btn(text, color, width, handler):
        b = Button()
        b.Content = text; b.Width = width; b.Height = 28
        b.Background = hex_brush(color); b.Foreground = hex_brush("#FFFFFF")
        b.FontWeight = FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler
        return b

    def _make_footer(version):
        brd = Border()
        brd.BorderThickness = Thickness(0, 1, 0, 0)
        brd.BorderBrush = hex_brush("#C0D0E0")
        brd.Background  = hex_brush("#F5F5F5")
        brd.Padding = Thickness(0, 6, 0, 6)
        g = Grid()
        lbl = TextBlock()
        lbl.Text = u"v{} | STR BIM Tools by Tony Varin".format(version)
        lbl.FontSize = 10; lbl.Foreground = hex_brush("#888888")
        lbl.VerticalAlignment = VerticalAlignment.Center
        lbl.Margin = Thickness(10, 0, 0, 0)
        g.Children.Add(lbl)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Right
        sp.Margin = Thickness(0, 0, 10, 0)
        brd.Child = g
        return brd, sp, g

    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(data):
        try:
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def pick_folder():
        try:
            prefs = _load_prefs()
            dlg = WinForms.FolderBrowserDialog()
            dlg.Description = u"Choisir le dossier d'export"
            last = prefs.get("last_export_folder", u"")
            if last and os.path.isdir(last):
                dlg.SelectedPath = last
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                folder = dlg.SelectedPath
                prefs["last_export_folder"] = folder
                _save_prefs(prefs)
                return folder
        except Exception:
            pass
        return None

    # =========================================================================
    # Helpers metier
    # =========================================================================
    def to_m3(val):
        try:
            return float(UnitUtils.ConvertFromInternalUnits(val, UnitTypeId.CubicMeters))
        except Exception:
            return float(val) * 0.0283168466

    def to_m(val):
        try:
            return float(UnitUtils.ConvertFromInternalUnits(val, UnitTypeId.Meters))
        except Exception:
            return float(val) * 0.3048

    def fmt_m3(v):
        try:
            return u"{:.3f}".format(float(v))
        except Exception:
            return u"—"

    def get_level_name(el):
        for bip in [BuiltInParameter.STAIRS_BASE_LEVEL_PARAM,
                    BuiltInParameter.FAMILY_LEVEL_PARAM,
                    BuiltInParameter.LEVEL_PARAM,
                    BuiltInParameter.SCHEDULE_LEVEL_PARAM]:
            try:
                p = el.get_Parameter(bip)
                if p and p.AsElementId() != ElementId.InvalidElementId:
                    lvl = doc.GetElement(p.AsElementId())
                    if lvl:
                        return lvl.Name
            except Exception:
                pass
        return u"—"

    def get_element_volume_by_materials(el):
        """Somme des volumes materiaux de l'element."""
        try:
            total = 0.0
            for mid in el.GetMaterialIds(False):
                try:
                    total += el.GetMaterialVolume(mid)
                except Exception:
                    pass
            return to_m3(total) if total > 0 else 0.0
        except Exception:
            return 0.0

    def get_stair_volume(el):
        """
        Volume d'un escalier Revit.
        Pour les escaliers natifs : somme des volumes de toutes les volees + paliers.
        Fallback : somme des materiaux de l'element parent.
        """
        vol = 0.0
        if HAS_STAIRS_API and isinstance(el, Stairs):
            # Somme volees
            try:
                for run_id in el.GetStairsRuns():
                    run = doc.GetElement(run_id)
                    if run:
                        vol += get_element_volume_by_materials(run)
            except Exception:
                pass
            # Somme paliers
            try:
                for land_id in el.GetStairsLandings():
                    land = doc.GetElement(land_id)
                    if land:
                        vol += get_element_volume_by_materials(land)
            except Exception:
                pass
            if vol > 0:
                return vol
        # Fallback : HOST_VOLUME_COMPUTED ou materiaux directs
        for bip in [BuiltInParameter.HOST_VOLUME_COMPUTED]:
            try:
                p = el.get_Parameter(bip)
                if p and p.HasValue and p.AsDouble() > 0:
                    return to_m3(p.AsDouble())
            except Exception:
                pass
        return get_element_volume_by_materials(el)

    def get_family_type_names(el):
        try:
            fam = el.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
            typ = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            f = fam.AsString() if fam else u""
            t = typ.AsString() if typ else u""
            if f or t:
                return f or u"—", t or u"—"
        except Exception:
            pass
        try:
            et = doc.GetElement(el.GetTypeId())
            if et:
                return (getattr(et, "FamilyName", None) or u"—",
                        getattr(et, "Name", None) or u"—")
        except Exception:
            pass
        return u"—", u"—"

    # =========================================================================
    # Collecte des escaliers
    # =========================================================================
    class StairData(object):
        def __init__(self):
            self.element_id  = 0
            self.element     = None
            self.source      = u""
            self.famille     = u""
            self.type_name   = u""
            self.niveau      = u""
            self.volume_m3   = 0.0
            self.nb_marches  = 0
            self.nb_volees   = 0
            self.nb_paliers  = 0
            self.largeurs    = u""
            self.double_flag = False
            self.note        = u""

    def _get_run_data(run):
        """Retourne (nb_risers, width_m) pour une StairsRun."""
        nb = 0
        w  = 0.0
        # Nombre de contremarches
        for attr in ["ActualRiserCount", "NumberOfRisers"]:
            try:
                v = getattr(run, attr, None)
                if v is not None and int(v) > 0:
                    nb = int(v)
                    break
            except Exception:
                pass
        if nb == 0:
            for bip_name in ["STAIRS_ATTR_NUM_RISERS", "STAIRS_ACTUAL_NUM_RISERS"]:
                bip = getattr(BuiltInParameter, bip_name, None)
                if bip is None:
                    continue
                try:
                    p = run.get_Parameter(bip)
                    if p and p.HasValue and p.AsInteger() > 0:
                        nb = p.AsInteger()
                        break
                except Exception:
                    pass
        # Largeur
        for attr in ["ActualRunWidth", "Width"]:
            try:
                v = getattr(run, attr, None)
                if v is not None and float(v) > 0:
                    w = to_m(float(v))
                    break
            except Exception:
                pass
        if w == 0.0:
            for bip_name in ["STAIRS_ATTR_MIN_WIDTH", "STAIRS_MINIMUM_WIDTH"]:
                bip = getattr(BuiltInParameter, bip_name, None)
                if bip is None:
                    continue
                try:
                    p = run.get_Parameter(bip)
                    if p and p.HasValue and p.AsDouble() > 0:
                        w = to_m(p.AsDouble())
                        break
                except Exception:
                    pass
        return nb, w

    def _get_parent_riser_count(el):
        """Nb total de contremarches depuis le parametre de l'element parent."""
        for bip_name in ["STAIRS_ACTUAL_NUM_RISERS", "STAIRS_ATTR_NUM_RISERS"]:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            try:
                p = el.get_Parameter(bip)
                if p and p.HasValue and p.AsInteger() > 0:
                    return p.AsInteger()
            except Exception:
                pass
        return 0

    def _get_parent_width(el):
        """Largeur minimale depuis le parametre de l'element parent."""
        for bip_name in ["STAIRS_ATTR_MIN_WIDTH", "STAIRS_MINIMUM_WIDTH"]:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            try:
                p = el.get_Parameter(bip)
                if p and p.HasValue and p.AsDouble() > 0:
                    return to_m(p.AsDouble())
            except Exception:
                pass
        return 0.0

    def collect_stairs():
        results  = []
        seen_ids = set()

        # ------------------------------------------------------------------
        # 1. Escaliers Revit natifs (OST_Stairs)
        # ------------------------------------------------------------------
        try:
            stairs_els = (FilteredElementCollector(doc)
                          .OfCategory(BuiltInCategory.OST_Stairs)
                          .WhereElementIsNotElementType()
                          .ToElements())
        except Exception:
            stairs_els = []

        # Constituer l'ensemble des IDs de sous-elements (volees/paliers)
        child_ids = set()
        if HAS_STAIRS_API:
            for el in stairs_els:
                if isinstance(el, Stairs):
                    try:
                        for rid in el.GetStairsRuns():
                            child_ids.add(rid.IntegerValue)
                    except Exception:
                        pass
                    try:
                        for lid in el.GetStairsLandings():
                            child_ids.add(lid.IntegerValue)
                    except Exception:
                        pass

        for el in stairs_els:
            if el.Id.IntegerValue in seen_ids:
                continue
            # Ignorer les sous-elements si on les detecte dans OST_Stairs
            if el.Id.IntegerValue in child_ids:
                continue
            seen_ids.add(el.Id.IntegerValue)

            sd = StairData()
            sd.element_id = el.Id.IntegerValue
            sd.element    = el
            sd.source     = u"Escalier Revit"
            sd.niveau     = get_level_name(el)
            sd.famille, sd.type_name = get_family_type_names(el)
            if sd.famille in (u"—", u"") or u"Stair" in sd.famille or u"Escalier" in sd.famille:
                sd.famille = u"Escalier"
            sd.volume_m3 = get_stair_volume(el)

            # Donnees des volees
            run_widths    = []
            total_risers  = 0
            nb_runs       = 0
            nb_landings   = 0

            if HAS_STAIRS_API and isinstance(el, Stairs):
                try:
                    run_ids = el.GetStairsRuns()
                    nb_runs = run_ids.Count
                    for run_id in run_ids:
                        run = doc.GetElement(run_id)
                        if run and isinstance(run, StairsRun):
                            nb, w = _get_run_data(run)
                            total_risers += nb
                            if w > 0:
                                run_widths.append(u"{:.2f}".format(w))
                except Exception:
                    pass
                try:
                    landing_ids = el.GetStairsLandings()
                    nb_landings = landing_ids.Count
                except Exception:
                    pass
                # Si les volees n'ont pas donne de marches, essayer le parent
                if total_risers == 0:
                    total_risers = _get_parent_riser_count(el)
            else:
                # Pas d'API Architecture : parametres directs
                total_risers = _get_parent_riser_count(el)
                w = _get_parent_width(el)
                if w > 0:
                    run_widths.append(u"{:.2f}".format(w))

            sd.nb_volees  = nb_runs
            sd.nb_paliers = nb_landings
            sd.largeurs   = u" / ".join(run_widths) if run_widths else u"—"

            # Fallback geometrique si aucune marche trouvee par l'API
            RISER_H_M = 0.17
            estim_note = u""
            if total_risers == 0:
                try:
                    bb = el.get_BoundingBox(None)
                    if bb:
                        h_m = to_m(bb.Max.Z - bb.Min.Z)
                        if h_m > 0.10:
                            total_risers = max(1, int(round(h_m / RISER_H_M)))
                            estim_note = u" | ~{:.2f}m/{}cm = {} marches".format(
                                h_m, int(RISER_H_M * 100), total_risers)
                except Exception:
                    pass

            sd.nb_marches = total_risers

            # Controle volume + info estimation
            vol_note = u"Vol. OK" if sd.volume_m3 > 0 else u"Vol. non calcule"
            sd.note  = vol_note + estim_note

            results.append(sd)

        # ------------------------------------------------------------------
        # 2. Familles "escalier" (Generic Models / SpecialityEquipment)
        #    Detectees par le nom de famille ou de type
        # ------------------------------------------------------------------
        IN_SITU_CATS = []
        for bic_name in ["OST_GenericModel", "OST_SpecialityEquipment", "OST_StairsRailing"]:
            bic = getattr(BuiltInCategory, bic_name, None)
            if bic is not None:
                IN_SITU_CATS.append(bic)

        KEYWORDS = [u"escal", u"stair", u"stairc"]

        for cat in IN_SITU_CATS:
            try:
                els = (FilteredElementCollector(doc)
                       .OfCategory(cat)
                       .WhereElementIsNotElementType()
                       .ToElements())
            except Exception:
                continue
            for el in els:
                if el.Id.IntegerValue in seen_ids:
                    continue
                fam, typ = get_family_type_names(el)
                combined = (fam + u" " + typ).lower()
                if not any(kw in combined for kw in KEYWORDS):
                    continue
                seen_ids.add(el.Id.IntegerValue)

                sd = StairData()
                sd.element_id = el.Id.IntegerValue
                sd.element    = el
                sd.source     = u"Famille / In-situ"
                sd.famille    = fam
                sd.type_name  = typ
                sd.niveau     = get_level_name(el)
                sd.volume_m3  = get_element_volume_by_materials(el)

                # --- Marches : estimation geometrique h / 17 cm ---
                RISER_H_M = 0.17  # contremarche standard CH/FR : 17 cm
                nb_marches_insitu = 0
                h_m_insitu = 0.0
                try:
                    bb = el.get_BoundingBox(None)
                    if bb:
                        h_m_insitu = to_m(bb.Max.Z - bb.Min.Z)
                        if h_m_insitu > 0.10:
                            nb_marches_insitu = max(1,
                                int(round(h_m_insitu / RISER_H_M)))
                except Exception:
                    pass

                sd.nb_marches = nb_marches_insitu

                # --- Largeur ---
                for pname in [u"Largeur", u"Largeur volee", u"Largeur min.",
                              u"Width", u"Stair Width", u"LargeurVolee"]:
                    try:
                        p = el.LookupParameter(pname)
                        if p and p.HasValue and p.AsDouble() > 0:
                            sd.largeurs = u"{:.2f}".format(to_m(p.AsDouble()))
                            break
                    except Exception:
                        pass

                # --- Note ---
                if nb_marches_insitu > 0 and h_m_insitu > 0:
                    sd.note = u"In-situ | ~{:.2f}m / {}cm = {} marches".format(
                        h_m_insitu, int(RISER_H_M * 100), nb_marches_insitu)
                else:
                    sd.note = u"In-situ | hauteur non disponible"

                results.append(sd)

        # ------------------------------------------------------------------
        # 3. Controle double comptage global
        #    Detecter des StairsRun/StairsLanding orphelins (pas rattaches a un Stairs)
        # ------------------------------------------------------------------
        orphan_count = 0
        for bic_name in ["OST_StairsRuns", "OST_StairsLandings"]:
            bic = getattr(BuiltInCategory, bic_name, None)
            if bic is None:
                continue
            try:
                sub_els = (FilteredElementCollector(doc)
                           .OfCategory(bic)
                           .WhereElementIsNotElementType()
                           .ToElements())
                for sub in sub_els:
                    if sub.Id.IntegerValue not in child_ids:
                        orphan_count += 1
            except Exception:
                pass

        return results, orphan_count

    # =========================================================================
    # Lancer la collecte
    # =========================================================================
    stair_list, orphan_count = collect_stairs()

    if not stair_list:
        MessageBox.Show(
            u"Aucun escalier trouve dans le projet.\n\n"
            u"Verifiez que des elements de categorie « Escaliers » sont presents,\n"
            u"ou que des familles contenant « escal » dans leur nom existent.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        sys.exit()

    total_volume  = sum(sd.volume_m3 for sd in stair_list)
    total_marches = sum(sd.nb_marches for sd in stair_list)

    double_count_msg = u""
    if orphan_count > 0:
        double_count_msg = (
            u"  ATTENTION : {} volee(s)/palier(s) non rattache(s) a un escalier parent "
            u"detecte(s) — risque de double comptage !"
        ).format(orphan_count)

    # =========================================================================
    # Lignes DataGrid
    # =========================================================================
    def rgb(r, g, b):
        return SolidColorBrush(Color.FromRgb(r, g, b))

    BG_WHITE = rgb(255, 255, 255)
    BG_ALT   = rgb(232, 240, 250)
    BG_WARN  = rgb(255, 235, 200)
    FG_DARK  = rgb(30,  30,  30)
    FG_BLUE  = rgb(31,  73, 125)
    W_NORMAL = FontWeights.Normal
    W_BOLD   = FontWeights.Bold

    class StairRow(object):
        def __init__(self, sd, idx):
            self._sd       = sd
            self.Num       = u"{}".format(idx)
            self.Source    = sd.source
            self.Famille   = sd.famille
            self.Type      = sd.type_name
            self.Niveau    = sd.niveau
            self.Volume    = fmt_m3(sd.volume_m3) if sd.volume_m3 > 0 else u"—"
            self.Marches   = u"{}".format(sd.nb_marches) if sd.nb_marches > 0 else u"—"
            self.Volees    = u"{}".format(sd.nb_volees)  if sd.nb_volees  > 0 else u"—"
            self.Paliers   = u"{}".format(sd.nb_paliers) if sd.nb_paliers > 0 else u"—"
            self.Largeurs  = sd.largeurs
            self.Note      = sd.note
            self.RowBg     = BG_WARN if sd.double_flag else (BG_WHITE if idx % 2 == 1 else BG_ALT)
            self.RowFg     = FG_DARK
            self.RowWeight = W_BOLD if sd.double_flag else W_NORMAL
            self.element_id = sd.element_id

    rows = ObservableCollection[object]()
    for idx, sd in enumerate(stair_list, start=1):
        rows.Add(StairRow(sd, idx))

    # =========================================================================
    # Vue 3D
    # =========================================================================
    def show_in_3d(element_id_int):
        try:
            el_id   = ElementId(element_id_int)
            element = doc.GetElement(el_id)
            if element is None:
                MessageBox.Show(u"Element introuvable.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return

            # Selectionner dans Revit
            id_col = System.Collections.Generic.List[ElementId]()
            id_col.Add(el_id)
            uidoc.Selection.SetElementIds(id_col)

            # Chercher vue 3D STR existante ou en creer une
            VIEW_NAME    = u"STR_Escaliers_3D"
            target_view  = None
            for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
                try:
                    if not v.IsTemplate and v.Name == VIEW_NAME:
                        target_view = v
                        break
                except Exception:
                    pass

            if target_view is None:
                vft = None
                for v in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
                    try:
                        if v.ViewFamily == ViewFamily.ThreeDimensional:
                            vft = v
                            break
                    except Exception:
                        pass
                if vft:
                    t = Transaction(doc, u"STR - Creer vue 3D escaliers")
                    t.Start()
                    try:
                        target_view = View3D.CreateIsometric(doc, vft.Id)
                        target_view.Name = VIEW_NAME
                        t.Commit()
                    except Exception:
                        t.RollBack()
                        target_view = None

            if target_view is None:
                MessageBox.Show(
                    u"Impossible de creer ou de trouver une vue 3D.\n"
                    u"L'element est selectionne dans Revit.",
                    TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)
                return

            # SectionBox autour de l'element (+30 cm de marge)
            bb = element.get_BoundingBox(None)
            if bb:
                margin = 1.0  # ~30 cm en pieds
                t = Transaction(doc, u"STR - SectionBox escalier")
                t.Start()
                try:
                    nb = BoundingBoxXYZ()
                    nb.Min = XYZ(bb.Min.X - margin, bb.Min.Y - margin, bb.Min.Z - margin)
                    nb.Max = XYZ(bb.Max.X + margin, bb.Max.Y + margin, bb.Max.Z + margin)
                    target_view.IsSectionBoxActive = True
                    target_view.SetSectionBox(nb)
                    t.Commit()
                except Exception:
                    t.RollBack()

            uidoc.ActiveView = target_view

        except Exception:
            MessageBox.Show(
                u"Erreur Vue 3D :\n\n{}".format(traceback.format_exc()),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)

    # =========================================================================
    # Export helpers
    # =========================================================================
    def _ask_filename(folder, default_name):
        result = {"path": None}
        d = Window()
        d.Title = TOOL_NAME
        d.Width = 460; d.Height = 200
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        hdr = Border(); hdr.Background = hex_brush("#2F6496")
        hdr.Padding = Thickness(14, 7, 14, 7)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        hdr_tb = TextBlock()
        hdr_tb.Text = u"Fichier existant — choisir un nom"
        hdr_tb.FontSize = 12; hdr_tb.FontWeight = FontWeights.SemiBold
        hdr_tb.Foreground = hex_brush("#FFFFFF"); hdr.Child = hdr_tb

        body = StackPanel(); body.Margin = Thickness(16, 12, 16, 8)
        Grid.SetRow(body, 1); droot.Children.Add(body)

        lbl_warn = TextBlock()
        lbl_warn.Text = u"Le fichier \"{}\" existe deja dans ce dossier.".format(default_name)
        lbl_warn.FontSize = 11; lbl_warn.Foreground = hex_brush("#E74C3C")
        lbl_warn.TextWrapping = TextWrapping.Wrap; lbl_warn.Margin = Thickness(0, 0, 0, 8)
        body.Children.Add(lbl_warn)

        lbl_hint = TextBlock()
        lbl_hint.Text = u"Nouveau nom de fichier (sans extension) :"
        lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#555555")
        lbl_hint.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(lbl_hint)

        txt = TextBox(); txt.FontSize = 11; txt.Height = 26
        txt.Padding = Thickness(4, 2, 4, 2)
        txt.BorderBrush = hex_brush("#C0D0E0"); txt.BorderThickness = Thickness(1)
        base_name = os.path.splitext(default_name)[0]
        txt.Text = base_name + u"_1"; txt.SelectAll()
        body.Children.Add(txt)

        lbl_err = TextBlock(); lbl_err.FontSize = 10
        lbl_err.Foreground = hex_brush("#E74C3C"); lbl_err.Margin = Thickness(0, 3, 0, 0)
        body.Children.Add(lbl_err)

        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)

        def _on_ok(s, e):
            name = txt.Text.strip()
            if not name:
                lbl_err.Text = u"Le nom ne peut pas etre vide."; return
            final = name if name.lower().endswith(".xlsx") else name + ".xlsx"
            fp = os.path.join(folder, final)
            if os.path.exists(fp):
                lbl_err.Text = u"Ce fichier existe aussi. Choisissez un autre nom."; return
            result["path"] = fp
            d.Close()

        btn_cancel = _footer_btn(u"Annuler",  "#E74C3C", 90, lambda s, e: d.Close())
        btn_ok2    = _footer_btn(u"Exporter", "#E67E22", 90, _on_ok)
        btn_cancel.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_cancel); dsp.Children.Add(btn_ok2)
        dgf.Children.Add(dsp)

        def on_key(s, e):
            if e.Key == System.Windows.Input.Key.Return:
                _on_ok(s, e)
        txt.KeyDown += on_key
        d.ShowDialog()
        return result["path"]

    def _show_export_success(path):
        d = Window()
        d.Title = TOOL_NAME
        d.Width = 420; d.Height = 155
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        body = StackPanel(); body.Margin = Thickness(16, 14, 16, 8)
        Grid.SetRow(body, 0); droot.Children.Add(body)
        tb1 = TextBlock(); tb1.Text = u"Export reussi :"
        tb1.FontSize = 11; tb1.FontWeight = FontWeights.SemiBold
        tb1.Foreground = hex_brush("#2F6496"); tb1.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(tb1)
        tb2 = TextBlock(); tb2.Text = path; tb2.FontSize = 10
        tb2.Foreground = hex_brush("#444444"); tb2.TextWrapping = TextWrapping.Wrap
        body.Children.Add(tb2)

        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 1); droot.Children.Add(dfooter)

        def _open_folder(s, e):
            try:
                psi = System.Diagnostics.ProcessStartInfo()
                psi.FileName  = "explorer.exe"
                psi.Arguments = u'"{}"'.format(os.path.dirname(path))
                System.Diagnostics.Process.Start(psi)
            except Exception:
                pass
            d.Close()

        btn_open = _footer_btn(u"Ouvrir le dossier", "#E67E22", 130, _open_folder)
        btn_ok3  = _footer_btn(u"OK",                "#3498DB",  60, lambda s, e: d.Close())
        btn_open.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_open); dsp.Children.Add(btn_ok3)
        dgf.Children.Add(dsp)
        d.ShowDialog()

    # =========================================================================
    # Export XLSX
    # =========================================================================
    def export_xlsx():
        folder = pick_folder()
        if not folder:
            return None
        try:
            import xlsxwriter
        except Exception:
            MessageBox.Show(u"Le module xlsxwriter n'est pas disponible.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None
        try:
            default_name = u"quantification_escaliers.xlsx"
            fpath = os.path.join(folder, default_name)
            if os.path.exists(fpath):
                fpath = _ask_filename(folder, default_name)
                if not fpath:
                    return None

            wb  = xlsxwriter.Workbook(fpath)
            ws  = wb.add_worksheet(u"Escaliers")
            ws2 = wb.add_worksheet(u"Synthese")

            fmt_title  = wb.add_format({"bold": True, "font_size": 14, "font_name": "Calibri"})
            fmt_hdr    = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                         "font_color": "#FFFFFF", "border": 1,
                                         "font_name": "Calibri", "align": "center",
                                         "valign": "vcenter", "text_wrap": True})
            fmt_num    = wb.add_format({"num_format": "#,##0.000", "font_name": "Calibri"})
            fmt_int_c  = wb.add_format({"font_name": "Calibri", "align": "center"})
            fmt_txt    = wb.add_format({"font_name": "Calibri"})
            fmt_warn   = wb.add_format({"font_name": "Calibri", "bg_color": "#FFEBC8"})
            fmt_wnum   = wb.add_format({"font_name": "Calibri", "bg_color": "#FFEBC8",
                                         "num_format": "#,##0.000"})
            fmt_wint   = wb.add_format({"font_name": "Calibri", "bg_color": "#FFEBC8",
                                         "align": "center"})
            fmt_tot    = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                         "font_color": "#FFFFFF", "font_name": "Calibri",
                                         "num_format": "#,##0.000"})
            fmt_tot_int = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                          "font_color": "#FFFFFF", "font_name": "Calibri",
                                          "align": "center"})
            fmt_sub    = wb.add_format({"bold": True, "bg_color": "#D0E4F7",
                                         "font_name": "Calibri"})
            fmt_sub_n  = wb.add_format({"bold": True, "bg_color": "#D0E4F7",
                                         "font_name": "Calibri", "num_format": "#,##0.000"})
            fmt_sub_i  = wb.add_format({"bold": True, "bg_color": "#D0E4F7",
                                         "font_name": "Calibri", "align": "center"})

            # En-tetes feuille 1
            headers = [
                u"N", u"Source", u"Famille", u"Type", u"Niveau",
                u"Volume (m3)", u"Nb marches", u"Nb volees",
                u"Nb paliers", u"Largeur(s) (m)", u"Note / Controle"
            ]
            ws.set_row(0, 30)
            ws.write_row(0, 0, headers, fmt_hdr)
            ws.freeze_panes(1, 0)
            ws.set_column(0, 0, 4)   # N
            ws.set_column(1, 1, 16)  # Source
            ws.set_column(2, 2, 26)  # Famille
            ws.set_column(3, 3, 26)  # Type
            ws.set_column(4, 4, 18)  # Niveau
            ws.set_column(5, 5, 13)  # Volume
            ws.set_column(6, 8, 11)  # Marches/Volees/Paliers
            ws.set_column(9, 9, 16)  # Largeurs
            ws.set_column(10, 10, 32) # Note

            for i, sd in enumerate(stair_list, start=1):
                r = i
                fw  = fmt_warn if sd.double_flag else fmt_txt
                fn  = fmt_wnum if sd.double_flag else fmt_num
                fi  = fmt_wint if sd.double_flag else fmt_int_c

                ws.write_number(r, 0, i, fi)
                ws.write(r, 1, sd.source,     fw)
                ws.write(r, 2, sd.famille,    fw)
                ws.write(r, 3, sd.type_name,  fw)
                ws.write(r, 4, sd.niveau,     fw)
                if sd.volume_m3 > 0:
                    ws.write_number(r, 5, sd.volume_m3, fn)
                else:
                    ws.write(r, 5, u"—", fw)
                for col, val in [(6, sd.nb_marches), (7, sd.nb_volees), (8, sd.nb_paliers)]:
                    if val > 0:
                        ws.write_number(r, col, val, fi)
                    else:
                        ws.write(r, col, u"—", fw)
                ws.write(r, 9,  sd.largeurs, fw)
                ws.write(r, 10, sd.note,     fw)

            # Ligne totaux
            tot_row = len(stair_list) + 2
            ws.write(tot_row, 0, u"", fmt_tot)
            ws.write(tot_row, 1, u"TOTAL", fmt_tot)
            ws.write(tot_row, 2, u"", fmt_tot)
            ws.write(tot_row, 3, u"", fmt_tot)
            ws.write(tot_row, 4,
                     u"{} escalier(s)".format(len(stair_list)), fmt_tot)
            if total_volume > 0:
                ws.write_number(tot_row, 5, total_volume, fmt_tot)
            else:
                ws.write(tot_row, 5, u"—", fmt_tot)
            if total_marches > 0:
                ws.write_number(tot_row, 6, total_marches, fmt_tot_int)
            else:
                ws.write(tot_row, 6, u"—", fmt_tot_int)
            for c in range(7, 11):
                ws.write(tot_row, c, u"", fmt_tot)

            # Synthese par niveau
            by_level = {}
            for sd in stair_list:
                lvl = sd.niveau or u"—"
                if lvl not in by_level:
                    by_level[lvl] = {"count": 0, "volume": 0.0, "marches": 0}
                by_level[lvl]["count"]   += 1
                by_level[lvl]["volume"]  += sd.volume_m3
                by_level[lvl]["marches"] += sd.nb_marches

            # Synthese par source
            by_source = {}
            for sd in stair_list:
                src = sd.source or u"—"
                if src not in by_source:
                    by_source[src] = {"count": 0, "volume": 0.0}
                by_source[src]["count"]  += 1
                by_source[src]["volume"] += sd.volume_m3

            # Feuille 2
            proj_name = u"—"
            try:
                proj_name = doc.Title or u"—"
            except Exception:
                pass

            r2 = 0
            ws2.write(r2, 1, u"Quantification Escaliers — Synthese", fmt_title)
            r2 += 2
            ws2.write(r2, 1, u"Projet",              fmt_hdr); ws2.write(r2, 2, proj_name,              fmt_txt); r2 += 1
            ws2.write(r2, 1, u"Nb escaliers total",  fmt_hdr); ws2.write_number(r2, 2, len(stair_list), fmt_int_c); r2 += 1
            ws2.write(r2, 1, u"Volume total (m3)",   fmt_hdr)
            if total_volume > 0:
                ws2.write_number(r2, 2, total_volume, fmt_num)
            else:
                ws2.write(r2, 2, u"—", fmt_txt)
            r2 += 1
            ws2.write(r2, 1, u"Nb marches total",    fmt_hdr)
            if total_marches > 0:
                ws2.write_number(r2, 2, total_marches, fmt_int_c)
            else:
                ws2.write(r2, 2, u"—", fmt_txt)
            r2 += 2

            # Par niveau
            ws2.write(r2, 1, u"Par niveau", fmt_sub)
            ws2.write(r2, 2, u"Nb escaliers", fmt_sub_i)
            ws2.write(r2, 3, u"Volume (m3)", fmt_sub_n)
            ws2.write(r2, 4, u"Nb marches", fmt_sub_i)
            r2 += 1
            for lvl in sorted(by_level.keys()):
                d2 = by_level[lvl]
                ws2.write(r2, 1, lvl, fmt_txt)
                ws2.write_number(r2, 2, d2["count"],   fmt_int_c)
                if d2["volume"] > 0:
                    ws2.write_number(r2, 3, d2["volume"], fmt_num)
                else:
                    ws2.write(r2, 3, u"—", fmt_txt)
                if d2["marches"] > 0:
                    ws2.write_number(r2, 4, d2["marches"], fmt_int_c)
                else:
                    ws2.write(r2, 4, u"—", fmt_txt)
                r2 += 1
            r2 += 1

            # Par source
            ws2.write(r2, 1, u"Par source", fmt_sub)
            ws2.write(r2, 2, u"Nb escaliers", fmt_sub_i)
            ws2.write(r2, 3, u"Volume (m3)", fmt_sub_n)
            r2 += 1
            for src in sorted(by_source.keys()):
                d2 = by_source[src]
                ws2.write(r2, 1, src, fmt_txt)
                ws2.write_number(r2, 2, d2["count"],  fmt_int_c)
                if d2["volume"] > 0:
                    ws2.write_number(r2, 3, d2["volume"], fmt_num)
                else:
                    ws2.write(r2, 3, u"—", fmt_txt)
                r2 += 1

            # Avertissement double comptage
            if double_count_msg:
                r2 += 1
                fmt_dc = wb.add_format({"bold": True, "font_color": "#C0392B",
                                         "font_name": "Calibri"})
                ws2.write(r2, 1, double_count_msg, fmt_dc)

            ws2.set_column("A:A", 3)
            ws2.set_column("B:B", 28)
            ws2.set_column("C:E", 16)

            wb.close()
            return fpath

        except Exception:
            MessageBox.Show(
                u"Export XLSX echoue :\n\n{}".format(traceback.format_exc()),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)
            return None

    # =========================================================================
    # Fenetre principale
    # =========================================================================
    win = Window()
    win.Title = TOOL_NAME
    win.Width = 1200; win.Height = 680
    win.MinWidth = 900; win.MinHeight = 450
    win.ResizeMode = ResizeMode.CanResize
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    for h in ["Auto", "Auto", "*", "Auto"]:
        root.RowDefinitions.Add(_rd(h))
    win.Content = root

    # Header bleu
    hdr_brd = Border()
    hdr_brd.Background = hex_brush("#2F6496")
    hdr_brd.Padding = Thickness(14, 9, 14, 9)
    Grid.SetRow(hdr_brd, 0); root.Children.Add(hdr_brd)
    hdr_sp = StackPanel()
    hdr_sp.Orientation = Orientation.Horizontal
    hdr_brd.Child = hdr_sp
    hdr_tb = TextBlock()
    hdr_tb.Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
    hdr_tb.FontSize = 13; hdr_tb.FontWeight = FontWeights.SemiBold
    hdr_tb.Foreground = hex_brush("#FFFFFF")
    hdr_tb.VerticalAlignment = VerticalAlignment.Center
    hdr_sp.Children.Add(hdr_tb)

    # Bande info
    info_brd = Border()
    info_brd.Background = hex_brush("#F0F6FF")
    info_brd.BorderBrush = hex_brush("#C0D0E0")
    info_brd.BorderThickness = Thickness(0, 0, 0, 1)
    info_brd.Padding = Thickness(14, 8, 14, 8)
    Grid.SetRow(info_brd, 1); root.Children.Add(info_brd)
    info_sp = StackPanel(); info_brd.Child = info_sp

    lbl_info = TextBlock()
    lbl_info.Text = (
        u"{}  escalier(s)  trouve(s)   |   "
        u"Volume total : {} m³   |   "
        u"Marches total : {}"
    ).format(len(stair_list), fmt_m3(total_volume), total_marches)
    lbl_info.FontSize = 11; lbl_info.FontWeight = FontWeights.SemiBold
    lbl_info.Foreground = hex_brush("#2F6496")
    info_sp.Children.Add(lbl_info)

    if double_count_msg:
        lbl_dc = TextBlock()
        lbl_dc.Text = double_count_msg
        lbl_dc.FontSize = 10; lbl_dc.Foreground = hex_brush("#C0392B")
        lbl_dc.Margin = Thickness(0, 4, 0, 0)
        info_sp.Children.Add(lbl_dc)

    lbl_hint = TextBlock()
    lbl_hint.Text = u"Selectionnez un escalier dans la liste puis cliquez sur « Vue 3D » pour l'isoler."
    lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#666666")
    lbl_hint.Margin = Thickness(0, 4, 0, 0)
    info_sp.Children.Add(lbl_hint)

    # DataGrid
    scroll = ScrollViewer()
    scroll.Margin = Thickness(8, 6, 8, 4)
    scroll.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
    scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
    Grid.SetRow(scroll, 2); root.Children.Add(scroll)

    dg = DataGrid()
    dg.AutoGenerateColumns  = False
    dg.IsReadOnly           = True
    dg.CanUserSortColumns   = True
    dg.HeadersVisibility    = DataGridHeadersVisibility.Column
    dg.RowBackground        = BG_WHITE
    dg.AlternatingRowBackground = BG_ALT
    dg.BorderBrush          = rgb(200, 210, 220)
    dg.BorderThickness      = Thickness(1)
    dg.GridLinesVisibility  = DataGridGridLinesVisibility.Horizontal
    dg.FrozenColumnCount    = 1
    dg.ItemsSource          = rows
    dg.SelectionMode        = DataGridSelectionMode.Single

    row_style = SW.Style(DataGridRow)
    row_style.Setters.Add(SW.Setter(DataGridRow.BackgroundProperty, Binding("RowBg")))
    dg.RowStyle = row_style

    hdr_style = SW.Style(DataGridColumnHeader)
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.BackgroundProperty, hex_brush("#D0E4F7")))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.PaddingProperty,    Thickness(6, 3, 6, 3)))
    dg.ColumnHeaderStyle = hdr_style

    def cell_style(align=SW.TextAlignment.Left):
        s = SW.Style(TextBlock)
        s.Setters.Add(SW.Setter(TextBlock.TextAlignmentProperty, align))
        s.Setters.Add(SW.Setter(TextBlock.ForegroundProperty,    Binding("RowFg")))
        s.Setters.Add(SW.Setter(TextBlock.FontWeightProperty,    Binding("RowWeight")))
        return s

    hdr_center = SW.Style(DataGridColumnHeader)
    hdr_center.Setters.Add(SW.Setter(
        DataGridColumnHeader.HorizontalContentAlignmentProperty, HorizontalAlignment.Center))
    hdr_right = SW.Style(DataGridColumnHeader)
    hdr_right.Setters.Add(SW.Setter(
        DataGridColumnHeader.HorizontalContentAlignmentProperty, HorizontalAlignment.Right))

    def make_col(header, binding, width_val, is_star=False,
                 align=SW.TextAlignment.Left, hdr_sty=None):
        c = DataGridTextColumn()
        c.Header  = header
        c.Binding = Binding(binding)
        c.Width   = (DataGridLength(width_val, DataGridLengthUnitType.Star)
                     if is_star else DataGridLength(width_val))
        c.ElementStyle = cell_style(align)
        if hdr_sty:
            c.HeaderStyle = hdr_sty
        return c

    dg.Columns.Add(make_col(u"N",            "Num",      42,  align=SW.TextAlignment.Center, hdr_sty=hdr_center))
    dg.Columns.Add(make_col(u"Source",      "Source",  112))
    dg.Columns.Add(make_col(u"Famille",     "Famille", 165))
    dg.Columns.Add(make_col(u"Type",        "Type",    155))
    dg.Columns.Add(make_col(u"Niveau",      "Niveau",  112))
    dg.Columns.Add(make_col(u"Vol. (m³)", "Volume", 90, align=SW.TextAlignment.Right, hdr_sty=hdr_right))
    dg.Columns.Add(make_col(u"Marches",     "Marches",  72, align=SW.TextAlignment.Center, hdr_sty=hdr_center))
    dg.Columns.Add(make_col(u"Volées", "Volees",   64, align=SW.TextAlignment.Center, hdr_sty=hdr_center))
    dg.Columns.Add(make_col(u"Paliers",     "Paliers",  64, align=SW.TextAlignment.Center, hdr_sty=hdr_center))
    dg.Columns.Add(make_col(u"Largeur(s) m", "Largeurs", 112, align=SW.TextAlignment.Right, hdr_sty=hdr_right))
    dg.Columns.Add(make_col(u"Contrôle", "Note",    260))

    def on_dg_wheel(sender, e):
        scroll.ScrollToVerticalOffset(scroll.VerticalOffset - e.Delta / 3.0)
        e.Handled = True
    dg.PreviewMouseWheel += on_dg_wheel

    scroll.Content = dg

    # Footer
    footer, sp_btns, grid_f = _make_footer(SCRIPT_VERSION)
    Grid.SetRow(footer, 3); root.Children.Add(footer)

    lbl_total_f = TextBlock()
    lbl_total_f.Text = u"{}  escalier(s)   |   {} m³   |   {} marche(s)".format(
        len(stair_list), fmt_m3(total_volume), total_marches)
    lbl_total_f.FontSize = 11; lbl_total_f.FontWeight = FontWeights.SemiBold
    lbl_total_f.Foreground = hex_brush("#1F497D")
    lbl_total_f.VerticalAlignment   = VerticalAlignment.Center
    lbl_total_f.HorizontalAlignment = HorizontalAlignment.Center
    grid_f.Children.Add(lbl_total_f)

    def on_vue3d(s, e):
        sel = dg.SelectedItem
        if sel is None:
            MessageBox.Show(
                u"Selectionnez un escalier dans la liste d'abord.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        show_in_3d(sel.element_id)

    def on_xlsx(s, e):
        path = export_xlsx()
        if path:
            _show_export_success(path)

    btn_vue3d  = _footer_btn(u"Vue 3D",         "#8E44AD",  90, on_vue3d)
    btn_xlsx   = _footer_btn(u"Exporter XLSX",  "#2ECC71", 120, on_xlsx)
    btn_close  = _footer_btn(u"Fermer",         "#3498DB",  90, lambda s, e: win.Close())
    btn_vue3d.Margin = Thickness(0, 0, 6, 0)
    btn_xlsx.Margin  = Thickness(0, 0, 6, 0)
    sp_btns.Children.Add(btn_vue3d)
    sp_btns.Children.Add(btn_xlsx)
    sp_btns.Children.Add(btn_close)
    grid_f.Children.Add(sp_btns)

    win.ShowDialog()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
