# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Rapport de Matériaux"
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
    import sys, os, io, csv, json
    from collections import OrderedDict

    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase"); clr.AddReference("System.Windows.Forms")
    import System, System.IO, System.Diagnostics
    import System.Windows.Forms as WinForms
    import System.Windows as SW
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode,
                                FontWeights, TextWrapping, CornerRadius)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, RowDefinition,
                                         ColumnDefinition, ScrollViewer, ScrollBarVisibility,
                                         ProgressBar, CheckBox, ComboBox, ComboBoxItem,
                                         DataGridLength, DataGridLengthUnitType, DataGridRow,
                                         Orientation, DataGridHeadersVisibility,
                                         DataGridGridLinesVisibility)
    from System.Windows.Controls.Primitives import DataGridColumnHeader
    from System.Windows.Threading import DispatcherPriority
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Data import Binding
    from System.Collections.ObjectModel import ObservableCollection
    from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                                   BuiltInParameter, UnitUtils, UnitTypeId, ElementId)

    doc = __revit__.ActiveUIDocument.Document
    app = __revit__.Application
    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # Helpers UI module-level
    # =========================================================================
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)))

    def _rd(h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto)
        return rd

    def _section_hdr(text):
        tb = TextBlock(); tb.Text = text; tb.FontSize = 11
        tb.FontWeight = FontWeights.SemiBold; tb.Foreground = hex_brush("#2F6496")
        tb.Margin = Thickness(0, 6, 0, 3); return tb

    def _group_box(stretch=False):
        gb = Border(); gb.BorderBrush = hex_brush("#C0D0E0"); gb.BorderThickness = Thickness(1)
        gb.Background = hex_brush("#FAFCFF"); gb.Padding = Thickness(10, 8, 10, 8)
        gb.Margin = Thickness(0, 0, 0, 0 if stretch else 8); return gb

    def _footer_btn(text, color, width, handler):
        b = Button(); b.Content = text; b.Width = width; b.Height = 28
        b.Background = hex_brush(color); b.Foreground = hex_brush("#FFFFFF")
        b.FontWeight = FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler; return b

    def _make_footer(version):
        brd = Border(); brd.BorderThickness = Thickness(0, 1, 0, 0)
        brd.BorderBrush = hex_brush("#C0D0E0"); brd.Background = hex_brush("#F5F5F5")
        brd.Padding = Thickness(0, 6, 0, 6)
        g = Grid()
        lbl = TextBlock()
        lbl.Text = u"v{} | STR BIM Tools by Tony Varin".format(version)
        lbl.FontSize = 10; lbl.Foreground = hex_brush("#888888")
        lbl.VerticalAlignment = VerticalAlignment.Center; lbl.Margin = Thickness(10, 0, 0, 0)
        g.Children.Add(lbl)
        sp = StackPanel(); sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Right; sp.Margin = Thickness(0, 0, 10, 0)
        brd.Child = g; return brd, sp, g

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

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

    def pick_folder(title=u"Choisir un dossier"):
        try:
            prefs = _load_prefs()
            dlg = WinForms.FolderBrowserDialog(); dlg.Description = title
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
    # Données / constantes métier
    # =========================================================================
    _RAW_CATEGORIES = [
        (u"Murs",                    "OST_Walls"),
        (u"Sols",                    "OST_Floors"),
        (u"Ossatures",               "OST_StructuralFraming"),
        (u"Poteaux",                 "OST_StructuralColumns"),
        (u"Toitures",                "OST_Roofs"),
        (u"Plafonds",                "OST_Ceilings"),
        (u"Escaliers",               "OST_Stairs"),
        (u"Assemblages structurels", "OST_StructuralConnectionHandler"),
        (u"Bords de dalle",          "OST_SlabEdges"),
    ]
    PHASE_BUCKETS = OrderedDict([
        ("EXISTANT_CONSERVE", u"Existant conservé"),
        ("EXISTANT_DEMOLI",   u"Existant démoli"),
        ("NOUVEAU",           u"Nouveau"),
    ])
    ALL_CATEGORIES = OrderedDict()
    for _label, _bic_name in _RAW_CATEGORIES:
        _bic = getattr(BuiltInCategory, _bic_name, None)
        if _bic is not None:
            ALL_CATEGORIES[_label] = _bic

    all_phases      = [doc.Phases.get_Item(i) for i in range(doc.Phases.Size)]
    phase_order_map = {ph.Id.IntegerValue: idx for idx, ph in enumerate(all_phases)}
    phase_name_map  = {ph.Name: ph.Id for ph in all_phases}
    phase_names     = [ph.Name for ph in all_phases]

    def _get_active_phase_name():
        try:
            av = doc.ActiveView
            ph_id = av.PhaseId if hasattr(av, 'PhaseId') else None
            if ph_id is None:
                p = av.get_Parameter(BuiltInParameter.VIEW_PHASE)
                if p: ph_id = p.AsElementId()
            if ph_id:
                ph = doc.GetElement(ph_id)
                if ph: return ph.Name
        except Exception:
            pass
        return phase_names[-1] if phase_names else None

    _default_phase = _get_active_phase_name()
    if _default_phase not in phase_names:
        _default_phase = phase_names[-1] if phase_names else None

    def fmt_vol(v):
        try: return u"{:,.1f}".format(float(v)).replace(",", u" ")
        except: return u"0.0"

    def fmt_pct(v):
        try: return u"{:.1f} %".format(float(v))
        except: return u"0.0 %"

    # =========================================================================
    # Fonctions d'analyse (logique métier)
    # =========================================================================
    def to_m3(internal_volume):
        try: return float(UnitUtils.ConvertFromInternalUnits(internal_volume, UnitTypeId.CubicMeters))
        except: return float(internal_volume) * 0.0283168466

    def safe_material_name(mat):
        if mat is None: return u"(matériau introuvable)"
        return mat.Name if getattr(mat, "Name", None) else u"(sans nom)"

    def get_material_ids(el):
        try: return list(el.GetMaterialIds(False))
        except: return []

    def get_phase_id(el, bip):
        try:
            p = el.get_Parameter(bip)
            if p: return p.AsElementId()
        except: pass
        return ElementId.InvalidElementId

    def classify_phase_status(el, sel_phase_order):
        created_id    = get_phase_id(el, BuiltInParameter.PHASE_CREATED)
        demolished_id = get_phase_id(el, BuiltInParameter.PHASE_DEMOLISHED)
        created_ord   = phase_order_map.get(created_id.IntegerValue,    None)
        demol_ord     = phase_order_map.get(demolished_id.IntegerValue, None)
        if created_ord is None: return None
        if created_ord < sel_phase_order:
            if demol_ord is not None and demol_ord <= sel_phase_order:
                return "EXISTANT_DEMOLI"
            return "EXISTANT_CONSERVE"
        if created_ord == sel_phase_order:
            return "NOUVEAU"
        return None

    def collect_mat_volumes_by_phase(bic, sel_phase_order, cancel_state):
        elements = (FilteredElementCollector(doc)
                    .OfCategory(bic).WhereElementIsNotElementType().ToElements())
        stats = {"nb_elements": len(elements), "nb_with_materials": 0,
                 "nb_without_materials": 0, "nb_out_of_phase_scope": 0,
                 "nb_volume_errors": 0, "nb_zero_volume": 0}
        buckets = {k: {} for k in PHASE_BUCKETS.keys()}
        for el in elements:
            if cancel_state['cancelled']: return None, None
            phase_status = classify_phase_status(el, sel_phase_order)
            if phase_status is None:
                stats["nb_out_of_phase_scope"] += 1; continue
            mat_ids = get_material_ids(el)
            if not mat_ids:
                stats["nb_without_materials"] += 1; continue
            stats["nb_with_materials"] += 1
            for mid in mat_ids:
                mat  = doc.GetElement(mid)
                name = safe_material_name(mat)
                key  = (mid.IntegerValue, name)
                try: vol = to_m3(el.GetMaterialVolume(mid))
                except: stats["nb_volume_errors"] += 1; continue
                if vol <= 0.0: stats["nb_zero_volume"] += 1; continue
                if key not in buckets[phase_status]:
                    buckets[phase_status][key] = {"name": name, "volume": 0.0,
                                                   "material_id": mid.IntegerValue}
                buckets[phase_status][key]["volume"] += vol
        sorted_buckets = OrderedDict()
        for phase_key, phase_label in PHASE_BUCKETS.items():
            items = sorted(buckets[phase_key].values(),
                           key=lambda x: (-x["volume"], x["name"].lower()))
            sorted_buckets[phase_key] = {"label": phase_label, "items": items,
                                          "total": sum(x["volume"] for x in items)}
        return stats, sorted_buckets

    # =========================================================================
    # 1. Dialogue sélection phase + catégories
    # =========================================================================
    class SelectionDialog(Window):
        def __init__(self):
            self.Title      = TOOL_NAME
            self.Width      = 520; self.Height = 570
            self.MinWidth   = 420; self.MinHeight = 420
            self.ResizeMode = ResizeMode.CanResize
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.Background = hex_brush("#FFFFFF")
            self.result_phase = None
            self.result_cats  = None
            self._build_ui()

        def _build_ui(self):
            root = Grid()
            for h in ["Auto", "*", "Auto"]:
                root.RowDefinitions.Add(_rd(h))
            self.Content = root

            # Barre titre bleue
            hdr = Border(); hdr.Background = hex_brush("#2F6496")
            hdr.Padding = Thickness(14, 9, 14, 9)
            Grid.SetRow(hdr, 0); root.Children.Add(hdr)
            tb_title = TextBlock()
            tb_title.Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
            tb_title.FontSize = 13; tb_title.FontWeight = FontWeights.SemiBold
            tb_title.Foreground = hex_brush("#FFFFFF"); hdr.Child = tb_title

            # Corps scrollable
            sv = ScrollViewer(); sv.Margin = Thickness(14, 6, 14, 4)
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            Grid.SetRow(sv, 1); root.Children.Add(sv)
            content = StackPanel(); sv.Content = content

            # Section : phase
            content.Children.Add(_section_hdr(u"Phase de référence"))
            grp_ph = _group_box(); inner_ph = StackPanel()
            hint = TextBlock()
            hint.Text = (u"Phase Revit utilisée pour classifier les éléments "
                         u"(existant conservé / existant démoli / nouveau).")
            hint.FontSize = 10; hint.Foreground = hex_brush("#666666")
            hint.TextWrapping = TextWrapping.Wrap; hint.Margin = Thickness(0, 0, 0, 8)
            inner_ph.Children.Add(hint)
            self._cb_phase = ComboBox(); self._cb_phase.Height = 28; self._cb_phase.FontSize = 11
            for pname in phase_names:
                item = ComboBoxItem(); item.Content = pname
                self._cb_phase.Items.Add(item)
                if pname == _default_phase:
                    self._cb_phase.SelectedItem = item
            if self._cb_phase.SelectedIndex < 0 and self._cb_phase.Items.Count > 0:
                self._cb_phase.SelectedIndex = self._cb_phase.Items.Count - 1
            inner_ph.Children.Add(self._cb_phase)
            grp_ph.Child = inner_ph; content.Children.Add(grp_ph)

            # Section : catégories
            content.Children.Add(_section_hdr(u"Catégories à analyser"))
            grp_cats = _group_box(stretch=True); inner_cats = StackPanel()
            sp_sel = StackPanel(); sp_sel.Orientation = Orientation.Horizontal
            sp_sel.Margin = Thickness(0, 0, 0, 8)
            def _on_all(s, e):
                for cb in self._cat_cbs: cb.IsChecked = True
            def _on_none(s, e):
                for cb in self._cat_cbs: cb.IsChecked = False
            b_all = Button(); b_all.Content = u"Tout sélectionner"; b_all.Height = 24
            b_all.FontSize = 10; b_all.Padding = Thickness(8,0,8,0); b_all.Margin = Thickness(0,0,6,0)
            b_all.Background = hex_brush("#2ECC71"); b_all.Foreground = hex_brush("#FFFFFF")
            b_all.BorderThickness = Thickness(0); b_all.Click += _on_all
            b_none = Button(); b_none.Content = u"Tout décocher"; b_none.Height = 24
            b_none.FontSize = 10; b_none.Padding = Thickness(8,0,8,0)
            b_none.Background = hex_brush("#E74C3C"); b_none.Foreground = hex_brush("#FFFFFF")
            b_none.BorderThickness = Thickness(0); b_none.Click += _on_none
            sp_sel.Children.Add(b_all); sp_sel.Children.Add(b_none)
            inner_cats.Children.Add(sp_sel)
            self._cat_cbs = []
            for label in ALL_CATEGORIES.keys():
                cb = CheckBox(); cb.Content = label; cb.IsChecked = True
                cb.FontSize = 11; cb.Margin = Thickness(0, 3, 0, 3)
                inner_cats.Children.Add(cb); self._cat_cbs.append(cb)
            grp_cats.Child = inner_cats; content.Children.Add(grp_cats)

            # Footer
            footer, sp_btns, grid_f = _make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 2); root.Children.Add(footer)
            btn_cancel = _footer_btn(u"Annuler",          "#E74C3C",  90, lambda s,e: self.Close())
            btn_ok     = _footer_btn(u"Lancer l'analyse", "#E67E22", 130, self._on_ok)
            btn_cancel.Margin = Thickness(0, 0, 6, 0)
            sp_btns.Children.Add(btn_cancel); sp_btns.Children.Add(btn_ok)
            grid_f.Children.Add(sp_btns)

        def _on_ok(self, s, e):
            sel = self._cb_phase.SelectedItem
            if sel is None:
                MessageBox.Show(u"Veuillez sélectionner une phase.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning); return
            cats = [cb.Content for cb in self._cat_cbs if cb.IsChecked == True]
            if not cats:
                MessageBox.Show(u"Veuillez sélectionner au moins une catégorie.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning); return
            self.result_phase = sel.Content
            self.result_cats  = cats
            self.Close()

    sel_dlg = SelectionDialog()
    sel_dlg.ShowDialog()
    if not sel_dlg.result_phase:
        sys.exit()

    selected_phase_name  = sel_dlg.result_phase
    selected_categories  = sel_dlg.result_cats
    selected_phase_id    = phase_name_map[selected_phase_name]
    selected_phase_order = phase_order_map.get(selected_phase_id.IntegerValue, 0)
    CATEGORIES           = OrderedDict((k, ALL_CATEGORIES[k]) for k in selected_categories)

    # =========================================================================
    # 2. Fenêtre de progression + boucle d'analyse
    # =========================================================================
    cancel_state = {'cancelled': False}

    prog_win = Window()
    prog_win.Title = TOOL_NAME
    prog_win.Width = 440; prog_win.Height = 175
    prog_win.ResizeMode = ResizeMode.NoResize
    prog_win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    prog_win.Background = hex_brush("#FFFFFF")

    _pw_root = Grid()
    for h in ["Auto", "*", "Auto"]:
        _pw_root.RowDefinitions.Add(_rd(h))
    prog_win.Content = _pw_root

    _pw_hdr = Border(); _pw_hdr.Background = hex_brush("#2F6496")
    _pw_hdr.Padding = Thickness(14, 7, 14, 7)
    Grid.SetRow(_pw_hdr, 0); _pw_root.Children.Add(_pw_hdr)
    _pw_hdr_tb = TextBlock(); _pw_hdr_tb.Text = u"Analyse en cours…"
    _pw_hdr_tb.FontSize = 12; _pw_hdr_tb.FontWeight = FontWeights.SemiBold
    _pw_hdr_tb.Foreground = hex_brush("#FFFFFF"); _pw_hdr.Child = _pw_hdr_tb

    _pw_body = StackPanel(); _pw_body.Margin = Thickness(14, 10, 14, 6)
    Grid.SetRow(_pw_body, 1); _pw_root.Children.Add(_pw_body)
    progress_label = TextBlock(); progress_label.Text = u"Initialisation…"
    progress_label.FontSize = 11; progress_label.Margin = Thickness(0, 0, 0, 8)
    _pw_body.Children.Add(progress_label)
    progress_bar = ProgressBar(); progress_bar.Minimum = 0
    progress_bar.Maximum = max(len(CATEGORIES), 1); progress_bar.Height = 16
    _pw_body.Children.Add(progress_bar)

    _pw_footer, _pw_sp, _pw_gf = _make_footer(SCRIPT_VERSION)
    Grid.SetRow(_pw_footer, 2); _pw_root.Children.Add(_pw_footer)
    _pw_sp.Children.Add(_footer_btn(u"Annuler", "#E74C3C", 90,
                                     lambda s,e: cancel_state.update({'cancelled': True})))
    _pw_gf.Children.Add(_pw_sp)

    prog_win.Show()

    def do_events():
        try: progress_bar.Dispatcher.Invoke(System.Action(lambda: None), DispatcherPriority.Background)
        except: pass

    cat_data           = OrderedDict()
    total_els          = 0
    skipped_categories = []

    for idx, (label, bic) in enumerate(CATEGORIES.items(), start=1):
        progress_label.Text = u"Analyse : {} ({}/{})".format(label, idx, len(CATEGORIES))
        progress_bar.Value  = idx
        do_events()
        if cancel_state['cancelled']:
            prog_win.Close()
            MessageBox.Show(u"Analyse annulée par l'utilisateur.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Information)
            sys.exit()
        stats, phase_data = collect_mat_volumes_by_phase(bic, selected_phase_order, cancel_state)
        if cancel_state['cancelled'] or stats is None:
            prog_win.Close()
            MessageBox.Show(u"Analyse annulée par l'utilisateur.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Information)
            sys.exit()
        total_els += stats["nb_elements"]
        if any(phase_data[k]["items"] for k in phase_data.keys()):
            cat_data[label] = {"stats": stats, "phases": phase_data}
        else:
            skipped_categories.append((label, stats))

    prog_win.Close()

    if not cat_data:
        MessageBox.Show(
            u"Aucun matériau quantifiable trouvé pour la phase et les catégories sélectionnées.",
            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
        sys.exit()

    # ---- Consolidation des totaux ----
    global_phase_totals = OrderedDict()
    for phase_key, phase_label in PHASE_BUCKETS.items():
        accum = {}
        for entry in cat_data.values():
            for item in entry["phases"][phase_key]["items"]:
                key = (item["material_id"], item["name"])
                if key not in accum:
                    accum[key] = {"name": item["name"], "volume": 0.0,
                                  "material_id": item["material_id"]}
                accum[key]["volume"] += item["volume"]
        items = sorted(accum.values(), key=lambda x: (-x["volume"], x["name"].lower()))
        global_phase_totals[phase_key] = {"label": phase_label, "items": items,
                                           "total": sum(x["volume"] for x in items)}

    grand_total = sum(global_phase_totals[k]["total"] for k in PHASE_BUCKETS.keys())
    all_total_by_mat = {}
    for phase_key in PHASE_BUCKETS.keys():
        for item in global_phase_totals[phase_key]["items"]:
            key = (item["material_id"], item["name"])
            if key not in all_total_by_mat:
                all_total_by_mat[key] = {"name": item["name"], "volume": 0.0,
                                          "material_id": item["material_id"]}
            all_total_by_mat[key]["volume"] += item["volume"]
    all_total_by_mat = OrderedDict(
        (k, v) for k, v in sorted(all_total_by_mat.items(),
                                   key=lambda kv: (-kv[1]["volume"], kv[1]["name"].lower())))

    # =========================================================================
    # Fonctions d'export
    # =========================================================================
    def export_csv():
        folder = pick_folder(u"Dossier pour l'export CSV")
        if not folder: return None
        try:
            path = System.IO.Path.Combine(folder, "rapport_materiaux_phases.csv")
            with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(["Section","Categorie","StatutPhase","Materiau",
                                  "Volume_m3","Pourcentage","PhaseReference"])
                for cat_label, entry in cat_data.items():
                    for phase_key, phase_info in entry["phases"].items():
                        phase_total = phase_info["total"]
                        for item in phase_info["items"]:
                            pct = (item["volume"] / phase_total * 100.0) if phase_total else 0.0
                            writer.writerow(["Categorie", cat_label, phase_info["label"],
                                             item["name"], round(item["volume"], 6),
                                             round(pct, 3), selected_phase_name])
            return path
        except Exception as ex:
            MessageBox.Show(u"Export CSV échoué :\n{}".format(ex), TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None

    def _ask_filename(folder, default_name):
        """Dialogue de saisie nom de fichier — affiché si le fichier existe déjà.
        Retourne le chemin complet validé, ou None si annulé."""
        result = {"path": None}
        d = Window(); d.Title = TOOL_NAME
        d.Width = 460; d.Height = 195
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]: droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        # Barre titre bleue
        hdr = Border(); hdr.Background = hex_brush("#2F6496"); hdr.Padding = Thickness(14, 7, 14, 7)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        hdr_tb = TextBlock(); hdr_tb.Text = u"Fichier existant — choisir un nom"
        hdr_tb.FontSize = 12; hdr_tb.FontWeight = FontWeights.SemiBold
        hdr_tb.Foreground = hex_brush("#FFFFFF"); hdr.Child = hdr_tb

        # Corps
        body = StackPanel(); body.Margin = Thickness(16, 12, 16, 8)
        Grid.SetRow(body, 1); droot.Children.Add(body)

        lbl_warn = TextBlock()
        lbl_warn.Text = u"Le fichier \"{}\" existe déjà dans ce dossier.".format(default_name)
        lbl_warn.FontSize = 11; lbl_warn.Foreground = hex_brush("#E74C3C")
        lbl_warn.TextWrapping = TextWrapping.Wrap; lbl_warn.Margin = Thickness(0, 0, 0, 8)
        body.Children.Add(lbl_warn)

        lbl_hint = TextBlock(); lbl_hint.Text = u"Nouveau nom de fichier (sans extension) :"
        lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#555555")
        lbl_hint.Margin = Thickness(0, 0, 0, 4)
        body.Children.Add(lbl_hint)

        from System.Windows.Controls import TextBox
        txt = TextBox(); txt.FontSize = 11; txt.Height = 26; txt.Padding = Thickness(4, 2, 4, 2)
        txt.BorderBrush = hex_brush("#C0D0E0"); txt.BorderThickness = Thickness(1)
        base_name = os.path.splitext(default_name)[0]
        txt.Text = base_name + u"_1"; txt.SelectAll()
        body.Children.Add(txt)

        lbl_err = TextBlock(); lbl_err.FontSize = 10; lbl_err.Foreground = hex_brush("#E74C3C")
        lbl_err.Margin = Thickness(0, 3, 0, 0)
        body.Children.Add(lbl_err)

        # Footer
        dfooter, dsp, dgf = _make_footer(SCRIPT_VERSION)
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)

        def _on_ok(s, e):
            name = txt.Text.strip()
            if not name:
                lbl_err.Text = u"Le nom ne peut pas être vide."; return
            final = name if name.lower().endswith(".xlsx") else name + ".xlsx"
            final_path = os.path.join(folder, final)
            if os.path.exists(final_path):
                lbl_err.Text = u"Ce fichier existe aussi. Choisissez un autre nom."; return
            result["path"] = final_path
            d.Close()

        btn_cancel = _footer_btn(u"Annuler",   "#E74C3C", 90, lambda s,e: d.Close())
        btn_ok     = _footer_btn(u"Exporter",  "#E67E22", 90, _on_ok)
        btn_cancel.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_cancel); dsp.Children.Add(btn_ok)
        dgf.Children.Add(dsp)

        txt.KeyDown += lambda s, e: (_on_ok(s, e) if e.Key == System.Windows.Input.Key.Return else None)
        d.ShowDialog()
        return result["path"]

    def export_xlsx():
        folder = pick_folder(u"Dossier pour l'export XLSX")
        if not folder: return None
        try:
            import xlsxwriter
        except Exception:
            MessageBox.Show(u"Le module xlsxwriter n'est pas disponible.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None
        try:
            default_name = "rapport_materiaux_phases.xlsx"
            if os.path.exists(os.path.join(folder, default_name)):
                path = _ask_filename(folder, default_name)
                if not path: return None
            else:
                path = os.path.join(folder, default_name)
            wb   = xlsxwriter.Workbook(path)
            ws1  = wb.add_worksheet(u"Synthese")
            ws2  = wb.add_worksheet(u"Detail")
            ws3  = wb.add_worksheet(u"Totaux phases")
            fmt_title = wb.add_format({"bold": True, "font_size": 14, "font_name": "Calibri"})
            fmt_hdr   = wb.add_format({"bold": True, "bg_color": "#2F6496", "font_color": "#FFFFFF",
                                        "border": 1, "font_name": "Calibri", "align": "center"})
            fmt_num   = wb.add_format({"num_format": "#,##0.0",  "font_name": "Calibri"})
            fmt_pct_x = wb.add_format({"num_format": "0.0%",    "font_name": "Calibri"})
            fmt_txt   = wb.add_format({"font_name": "Calibri"})

            ws1.write("B2", u"Rapport Matériaux par phases", fmt_title)
            ws1.write("B4", u"Phase de référence",        fmt_hdr); ws1.write("C4", selected_phase_name,   fmt_txt)
            ws1.write("B5", u"Catégories avec résultats", fmt_hdr); ws1.write("C5", len(cat_data),         fmt_num)
            ws1.write("B6", u"Éléments analysés",         fmt_hdr); ws1.write("C6", total_els,             fmt_num)
            ws1.write("B7", u"Matériaux distincts",       fmt_hdr); ws1.write("C7", len(all_total_by_mat), fmt_num)
            ws1.write("B8", u"Total général (m³)",        fmt_hdr); ws1.write("C8", grand_total,           fmt_num)
            row = 10
            ws1.write_row(row, 1, [u"Statut", u"Volume (m³)", u"% du total"], fmt_hdr); row += 1
            for phase_key, phase_info in global_phase_totals.items():
                ws1.write(row, 1, phase_info["label"], fmt_txt)
                ws1.write_number(row, 2, phase_info["total"], fmt_num)
                ws1.write_number(row, 3, (phase_info["total"]/grand_total) if grand_total else 0.0, fmt_pct_x)
                row += 1

            row = 1
            ws2.write_row(row, 1, [u"Catégorie", u"Statut", u"Matériau",
                                    u"Volume (m³)", u"% dans le statut", u"Phase de référence"], fmt_hdr)
            row += 1
            for cat_label, entry in cat_data.items():
                for phase_key, phase_info in entry["phases"].items():
                    phase_total = phase_info["total"]
                    for item in phase_info["items"]:
                        ws2.write(row, 1, cat_label, fmt_txt)
                        ws2.write(row, 2, phase_info["label"], fmt_txt)
                        ws2.write(row, 3, item["name"], fmt_txt)
                        ws2.write_number(row, 4, item["volume"], fmt_num)
                        ws2.write_number(row, 5, (item["volume"]/phase_total) if phase_total else 0.0, fmt_pct_x)
                        ws2.write(row, 6, selected_phase_name, fmt_txt)
                        row += 1

            row = 1
            ws3.write_row(row, 1, [u"Statut", u"Matériau", u"Volume (m³)",
                                    u"% dans le statut", u"Phase de référence"], fmt_hdr); row += 1
            for phase_key, phase_info in global_phase_totals.items():
                for item in phase_info["items"]:
                    ws3.write(row, 1, phase_info["label"], fmt_txt)
                    ws3.write(row, 2, item["name"], fmt_txt)
                    ws3.write_number(row, 3, item["volume"], fmt_num)
                    ws3.write_number(row, 4, (item["volume"]/phase_info["total"]) if phase_info["total"] else 0.0, fmt_pct_x)
                    ws3.write(row, 5, selected_phase_name, fmt_txt)
                    row += 1

            for ws in [ws1, ws2, ws3]:
                ws.set_column("A:A", 3);  ws.set_column("B:B", 24); ws.set_column("C:C", 24)
                ws.set_column("D:D", 34); ws.set_column("E:F", 18); ws.freeze_panes(2, 1)
            wb.close()
            return path
        except Exception as ex:
            MessageBox.Show(u"Export XLSX échoué :\n{}".format(ex), TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None

    # =========================================================================
    # Construction des lignes DataGrid
    # =========================================================================
    W_BOLD   = FontWeights.Bold
    W_NORMAL = FontWeights.Normal

    def rgb(r, g, b): return SolidColorBrush(Color.FromRgb(r, g, b))

    FG_WHITE      = rgb(255, 255, 255); FG_DARK      = rgb(30,  30,  30)
    FG_BLUE_NAVY  = rgb(31,  73,  125); FG_BLUE_TOTAL= rgb(18,  90,  160)
    FG_GRAY_MED   = rgb(80,  80,  80);  FG_PHASE     = rgb(70,  70,  70)

    BG_WHITE        = rgb(255,255,255); BG_ALT          = rgb(247,251,255)
    BG_SUBTOTAL     = rgb(210,225,242); BG_TOTAL_HEADER = rgb(45, 45, 45)
    BG_TOTAL_ROW    = rgb(235,245,255); BG_INFO         = rgb(242,247,250)
    BG_PHASE_KEEP   = rgb(226,239,218); BG_PHASE_DEMO   = rgb(248,222,222)
    BG_PHASE_NEW    = rgb(222,235,247)

    FS_NORMAL = 11.0; FS_HEADER = 11.5; FS_SMALL = 10.0

    class MatRow(object):
        def __init__(self, label, volume_str, pct_str, row_kind, fg, bg, weight, font_size=11.0):
            self.Label     = label;      self.Volume   = volume_str; self.Pct      = pct_str
            self.RowKind   = row_kind;   self.RowFg    = fg;         self.RowBg    = bg
            self.RowWeight = weight;     self.FontSize = font_size

    rows = ObservableCollection[object]()
    phase_bg_map = {"EXISTANT_CONSERVE": BG_PHASE_KEEP, "EXISTANT_DEMOLI": BG_PHASE_DEMO, "NOUVEAU": BG_PHASE_NEW}

    for cat_label, entry in cat_data.items():
        stats = entry["stats"]
        rows.Add(MatRow(u"CATÉGORIE : {}".format(cat_label.upper()), u"", u"",
                        "header", FG_DARK, BG_INFO, W_BOLD, FS_HEADER))
        rows.Add(MatRow(
            u"  {} éléments | {} avec matériaux | {} sans matériaux | {} hors scope phase".format(
                stats["nb_elements"], stats["nb_with_materials"],
                stats["nb_without_materials"], stats["nb_out_of_phase_scope"]),
            u"", u"", "info", FG_GRAY_MED, BG_INFO, W_NORMAL, FS_SMALL))
        for phase_key, phase_info in entry["phases"].items():
            if not phase_info["items"]: continue
            rows.Add(MatRow(u"  {}".format(phase_info["label"].upper()), u"", u"",
                            "phase", FG_PHASE, phase_bg_map[phase_key], W_BOLD, FS_SMALL))
            phase_total = phase_info["total"]
            for item in phase_info["items"]:
                pct = (item["volume"] / phase_total * 100.0) if phase_total else 0.0
                rows.Add(MatRow(u"    {}".format(item["name"]),
                                fmt_vol(item["volume"]), fmt_pct(pct),
                                "material", FG_DARK, BG_WHITE, W_NORMAL))
            cat_pct = (phase_total / grand_total * 100.0) if grand_total else 0.0
            rows.Add(MatRow(u"  Sous-total {}".format(phase_info["label"]),
                            fmt_vol(phase_total), fmt_pct(cat_pct),
                            "subtotal", FG_BLUE_NAVY, BG_SUBTOTAL, W_BOLD))
        rows.Add(MatRow(u"", u"", u"", "blank", FG_DARK, BG_WHITE, W_NORMAL))

    rows.Add(MatRow(u"TOTAUX PAR PHASE", u"Volume (m³)", u"%",
                    "header", FG_WHITE, BG_TOTAL_HEADER, W_BOLD, FS_HEADER))
    for phase_key, phase_info in global_phase_totals.items():
        pct = (phase_info["total"] / grand_total * 100.0) if grand_total else 0.0
        rows.Add(MatRow(phase_info["label"], fmt_vol(phase_info["total"]), fmt_pct(pct),
                        "subtotal", FG_BLUE_TOTAL, BG_TOTAL_ROW, W_BOLD))
    rows.Add(MatRow(u"", u"", u"", "blank", FG_DARK, BG_WHITE, W_NORMAL))
    rows.Add(MatRow(u"TOTAL GÉNÉRAL PAR MATÉRIAU", u"Volume (m³)", u"%",
                    "header", FG_WHITE, BG_TOTAL_HEADER, W_BOLD, FS_HEADER))
    for item in all_total_by_mat.values():
        pct = (item["volume"] / grand_total * 100.0) if grand_total else 0.0
        rows.Add(MatRow(u"    {}".format(item["name"]),
                        fmt_vol(item["volume"]), fmt_pct(pct),
                        "material", FG_BLUE_TOTAL, BG_TOTAL_ROW, W_NORMAL))

    # =========================================================================
    # 3. Fenêtre de résultats
    # =========================================================================
    win = Window()
    win.Title = TOOL_NAME
    win.Width = 960; win.Height = 860
    win.MinWidth = 680; win.MinHeight = 500
    win.ResizeMode = ResizeMode.CanResize
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = hex_brush("#FFFFFF")

    root = Grid()
    for h in ["Auto", "Auto", "*", "Auto"]:
        root.RowDefinitions.Add(_rd(h))
    win.Content = root

    # ---- Barre titre bleue ----
    hdr_brd = Border(); hdr_brd.Background = hex_brush("#2F6496")
    hdr_brd.Padding = Thickness(14, 9, 14, 9)
    Grid.SetRow(hdr_brd, 0); root.Children.Add(hdr_brd)
    hdr_tb = TextBlock()
    hdr_tb.Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
    hdr_tb.FontSize = 13; hdr_tb.FontWeight = FontWeights.SemiBold
    hdr_tb.Foreground = hex_brush("#FFFFFF"); hdr_brd.Child = hdr_tb

    # ---- Bande d'info + synthèse (fixe) ----
    info_brd = Border(); info_brd.Background = hex_brush("#F0F6FF")
    info_brd.BorderBrush = hex_brush("#C0D0E0"); info_brd.BorderThickness = Thickness(0, 0, 0, 1)
    info_brd.Padding = Thickness(14, 8, 14, 8)
    Grid.SetRow(info_brd, 1); root.Children.Add(info_brd)
    info_sp = StackPanel(); info_brd.Child = info_sp

    lbl_info = TextBlock()
    lbl_info.Text = (u"Phase : {}   •   {} catégorie(s)   •   "
                     u"{} élément(s)   •   {} matériau(x) distinct(s)").format(
        selected_phase_name, len(cat_data), total_els, len(all_total_by_mat))
    lbl_info.FontSize = 11; lbl_info.FontWeight = FontWeights.SemiBold
    lbl_info.Foreground = hex_brush("#2F6496"); lbl_info.Margin = Thickness(0, 0, 0, 6)
    info_sp.Children.Add(lbl_info)

    # Chips de synthèse par phase
    synth_sp = StackPanel(); synth_sp.Orientation = Orientation.Horizontal
    chip_colors = {"EXISTANT_CONSERVE": "#4CAF50", "EXISTANT_DEMOLI": "#E74C3C", "NOUVEAU": "#2196F3"}
    for phase_key, phase_info in global_phase_totals.items():
        if phase_info["total"] <= 0: continue
        pct_ph = (phase_info["total"] / grand_total * 100.0) if grand_total else 0.0
        chip = Border(); chip.Background = hex_brush(chip_colors.get(phase_key, "#888888"))
        chip.CornerRadius = CornerRadius(3)
        chip.Padding = Thickness(10, 4, 10, 4); chip.Margin = Thickness(0, 0, 8, 0)
        tb_chip = TextBlock()
        tb_chip.Text = u"{}    {} m³  ({:.0f} %)".format(
            phase_info["label"], fmt_vol(phase_info["total"]), pct_ph)
        tb_chip.FontSize = 10; tb_chip.FontWeight = FontWeights.SemiBold
        tb_chip.Foreground = hex_brush("#FFFFFF"); chip.Child = tb_chip
        synth_sp.Children.Add(chip)
    info_sp.Children.Add(synth_sp)

    if skipped_categories:
        lbl_skip = TextBlock()
        lbl_skip.Text = u"Sans volume exploitable : {}".format(
            u", ".join(x[0] for x in skipped_categories))
        lbl_skip.FontSize = 10; lbl_skip.Foreground = hex_brush("#888888")
        lbl_skip.Margin = Thickness(0, 5, 0, 0)
        info_sp.Children.Add(lbl_skip)

    # ---- DataGrid (scrollable) ----
    scroll = ScrollViewer(); scroll.Margin = Thickness(8, 6, 8, 4)
    scroll.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
    scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
    Grid.SetRow(scroll, 2); root.Children.Add(scroll)

    dg = DataGrid()
    dg.AutoGenerateColumns = False; dg.IsReadOnly = True; dg.CanUserSortColumns = False
    dg.HeadersVisibility        = DataGridHeadersVisibility.Column
    dg.RowBackground            = BG_WHITE; dg.AlternatingRowBackground = BG_ALT
    dg.BorderBrush              = rgb(200, 210, 220); dg.BorderThickness = Thickness(1)
    dg.GridLinesVisibility      = DataGridGridLinesVisibility.Horizontal
    dg.HorizontalGridLinesBrush = rgb(220, 228, 238)
    dg.FrozenColumnCount        = 1; dg.ItemsSource = rows

    row_style = SW.Style(DataGridRow)
    row_style.Setters.Add(SW.Setter(DataGridRow.BackgroundProperty, Binding("RowBg")))
    dg.RowStyle = row_style

    hdr_style = SW.Style(DataGridColumnHeader)
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.BackgroundProperty, hex_brush("#D0E4F7")))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold))
    hdr_style.Setters.Add(SW.Setter(DataGridColumnHeader.PaddingProperty, Thickness(6, 3, 6, 3)))
    dg.ColumnHeaderStyle = hdr_style

    def make_cell_style(align=SW.TextAlignment.Left):
        s = SW.Style(TextBlock)
        s.Setters.Add(SW.Setter(TextBlock.TextAlignmentProperty, align))
        s.Setters.Add(SW.Setter(TextBlock.ForegroundProperty,   Binding("RowFg")))
        s.Setters.Add(SW.Setter(TextBlock.FontWeightProperty,   Binding("RowWeight")))
        s.Setters.Add(SW.Setter(TextBlock.FontSizeProperty,     Binding("FontSize")))
        return s

    hdr_right = SW.Style(DataGridColumnHeader)
    hdr_right.Setters.Add(SW.Setter(DataGridColumnHeader.HorizontalContentAlignmentProperty, HorizontalAlignment.Right))

    col_label = DataGridTextColumn()
    col_label.Header       = u"Catégorie / Phase / Matériau"
    col_label.Binding      = Binding("Label")
    col_label.Width        = DataGridLength(1, DataGridLengthUnitType.Star)
    col_label.ElementStyle = make_cell_style(SW.TextAlignment.Left)
    col_label.CanUserSort  = False

    col_vol = DataGridTextColumn()
    col_vol.Header       = u"Volume (m³)"; col_vol.Binding = Binding("Volume")
    col_vol.Width        = DataGridLength(130)
    col_vol.ElementStyle = make_cell_style(SW.TextAlignment.Right)
    col_vol.HeaderStyle  = hdr_right; col_vol.CanUserSort = False

    col_pct = DataGridTextColumn()
    col_pct.Header       = u"%"; col_pct.Binding = Binding("Pct")
    col_pct.Width        = DataGridLength(80)
    col_pct.ElementStyle = make_cell_style(SW.TextAlignment.Right)
    col_pct.HeaderStyle  = hdr_right; col_pct.CanUserSort = False

    dg.Columns.Add(col_label); dg.Columns.Add(col_vol); dg.Columns.Add(col_pct)

    def on_dg_wheel(sender, e):
        scroll.ScrollToVerticalOffset(scroll.VerticalOffset - e.Delta / 3.0)
        e.Handled = True
    dg.PreviewMouseWheel += on_dg_wheel
    scroll.Content = dg

    # ---- Footer : version | total | CSV | XLSX | Fermer ----
    footer, sp_btns, grid_f = _make_footer(SCRIPT_VERSION)
    Grid.SetRow(footer, 3); root.Children.Add(footer)

    lbl_total = TextBlock()
    lbl_total.Text = u"TOTAL  •  {} m³".format(fmt_vol(grand_total))
    lbl_total.FontSize = 11; lbl_total.FontWeight = FontWeights.SemiBold
    lbl_total.Foreground = hex_brush("#1F497D")
    lbl_total.VerticalAlignment = VerticalAlignment.Center
    lbl_total.HorizontalAlignment = HorizontalAlignment.Center
    grid_f.Children.Add(lbl_total)

    def _show_export_success(path):
        """Dialogue de confirmation export avec bouton Ouvrir le dossier."""
        d = Window(); d.Title = TOOL_NAME
        d.Width = 400; d.Height = 155
        d.ResizeMode = ResizeMode.NoResize
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["*", "Auto"]: droot.RowDefinitions.Add(_rd(h))
        d.Content = droot
        body = StackPanel(); body.Margin = Thickness(16, 14, 16, 8)
        Grid.SetRow(body, 0); droot.Children.Add(body)
        tb1 = TextBlock(); tb1.Text = u"Export réussi :"
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
                folder_path = os.path.dirname(path)
                psi = System.Diagnostics.ProcessStartInfo()
                psi.FileName  = "explorer.exe"
                psi.Arguments = u'"{}"'.format(folder_path)
                System.Diagnostics.Process.Start(psi)
            except Exception:
                pass
            d.Close()
        btn_open = _footer_btn(u"Ouvrir le dossier", "#E67E22", 130, _open_folder)
        btn_ok   = _footer_btn(u"OK",                "#3498DB",  60, lambda s,e: d.Close())
        btn_open.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_open); dsp.Children.Add(btn_ok)
        dgf.Children.Add(dsp)
        d.ShowDialog()

    def _on_csv(s, e):
        path = export_csv()
        if path: _show_export_success(path)
    def _on_xlsx(s, e):
        path = export_xlsx()
        if path: _show_export_success(path)

    btn_csv   = _footer_btn(u"Exporter CSV",  "#27AE60", 105, _on_csv)
    btn_xlsx  = _footer_btn(u"Exporter XLSX", "#2ECC71", 110, _on_xlsx)
    btn_close = _footer_btn(u"Fermer",        "#3498DB",  90, lambda s,e: win.Close())
    btn_csv.Margin = Thickness(0, 0, 6, 0); btn_xlsx.Margin = Thickness(0, 0, 6, 0)
    sp_btns.Children.Add(btn_csv); sp_btns.Children.Add(btn_xlsx); sp_btns.Children.Add(btn_close)
    grid_f.Children.Add(sp_btns)

    win.ShowDialog()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
