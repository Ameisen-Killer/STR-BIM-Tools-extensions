# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "3.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Copie Elevations depuis Lien"
# =============================================================================
__doc__ = "Copie des élévations et des coupes depuis une maquette liée."

import sys, os, io, traceback, clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
import System.IO
import System.Text
import System.Windows.Markup

from System.Windows import (
    Window, GridLength, GridUnitType, Thickness,
    MessageBox, MessageBoxButton, MessageBoxImage,
    HorizontalAlignment, VerticalAlignment,
    WindowStartupLocation, ResizeMode, FontWeights, TextWrapping
)
from System.Windows.Controls import (
    Grid, StackPanel, DataGrid, TextBlock, Button, Label,
    Border, DataGridTextColumn, DataGridCheckBoxColumn,
    RowDefinition, ColumnDefinition, ProgressBar,
    ComboBox, ComboBoxItem, ScrollViewer, CheckBox,
    SelectionChangedEventArgs, ScrollBarVisibility
)
from System.Windows.Data    import Binding
from System.Windows.Media   import SolidColorBrush, Color
from System.Windows.Threading import DispatcherPriority
from System import Action
import System.Threading

import math
from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, TransactionStatus,
    BuiltInCategory, BuiltInParameter, ViewType,
    ElevationMarker, ViewFamilyType, ViewFamily,
    XYZ, BoundingBoxXYZ, ElementId, RevitLinkInstance,
    ViewSection, View, ViewPlan, Transform, UnitUtils, Level, Viewport,
    ElementTypeGroup
)

try:
    from Autodesk.Revit.DB import UnitTypeId
    USE_FORGE_UNITS = True
except ImportError:
    USE_FORGE_UNITS = False

from pyrevit import revit, script as pyscript

doc   = revit.doc
uidoc = revit.uidoc

# =============================================================================
# XAML
# =============================================================================
XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1000" Height="640"
    MinWidth="780" MinHeight="480"
    WindowStartupLocation="CenterScreen"
    Background="White" ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- BARRE OUTILS -->
    <Border Grid.Row="0" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="8,7">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>

        <TextBlock Grid.Column="0" x:Name="lbl_link_label"
                   VerticalAlignment="Center" Margin="0,0,6,0" FontWeight="SemiBold"/>
        <ComboBox Grid.Column="1" x:Name="cmb_links"
                  Width="280" Height="26" Margin="0,0,12,0" VerticalAlignment="Center"/>

        <TextBlock Grid.Column="2" x:Name="lbl_type_label"
                   VerticalAlignment="Center" Margin="0,0,6,0" FontWeight="SemiBold"/>
        <ComboBox Grid.Column="3" x:Name="cmb_type"
                  Width="180" Height="26" Margin="0,0,12,0" VerticalAlignment="Center"/>

        <CheckBox Grid.Column="5" x:Name="chk_all"
                  VerticalAlignment="Center" Margin="0,0,10,0"/>
        <Button Grid.Column="6" x:Name="btn_refresh"
                Width="110" Height="26"
                Background="#2ECC71" Foreground="White"
                FontWeight="SemiBold" BorderThickness="0"/>
      </Grid>
    </Border>

    <!-- BANDEAU INFO -->
    <Border Grid.Row="1" Background="#FFFBE6" BorderBrush="#FFE082"
            BorderThickness="0,0,0,1" Padding="8,5">
      <StackPanel Orientation="Vertical">
        <TextBlock x:Name="lbl_info" FontSize="11" Foreground="#795548"
                   Margin="0,0,0,4"/>
        <Grid x:Name="pnl_progress" Visibility="Collapsed">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <ProgressBar x:Name="pb_main" Grid.Column="0"
                       Height="14" Minimum="0" Maximum="100" Value="0"
                       Foreground="#2F6496" Background="#E0E8F0"
                       BorderThickness="0" Margin="0,0,8,0"/>
          <TextBlock x:Name="lbl_progress" Grid.Column="1"
                     FontSize="11" Foreground="#2F6496"
                     VerticalAlignment="Center" MinWidth="80"
                     FontWeight="SemiBold"/>
        </Grid>
      </StackPanel>
    </Border>

    <!-- DATAGRID -->
    <DataGrid x:Name="dg_main" Grid.Row="2" Margin="8,8,8,4"
              AutoGenerateColumns="False" IsReadOnly="False"
              AlternatingRowBackground="#E8F0FA" RowBackground="White"
              GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
              HeadersVisibility="Column"
              CanUserResizeColumns="True" CanUserSortColumns="True"
              CanUserAddRows="False" CanUserDeleteRows="False"
              SelectionMode="Single"
              FontSize="12">
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,3"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <DataGridCheckBoxColumn x:Name="col_sel"
                                Binding="{Binding IsSelected, Mode=TwoWay}"
                                Width="36" SortMemberPath="IsSelected"/>
        <DataGridTextColumn x:Name="col_nom"
                            Binding="{Binding Nom}" Width="*" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_type"
                            Binding="{Binding TypeVue}" Width="160" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_echelle"
                            Binding="{Binding Echelle}" Width="80" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_niveau"
                            Binding="{Binding Niveau}" Width="120" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_feuille"
                            Binding="{Binding Feuille}" Width="120" IsReadOnly="True"/>
        <DataGridTextColumn x:Name="col_statut"
                            Binding="{Binding Statut}" Width="120" IsReadOnly="True"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- FOOTER -->
    <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <TextBlock x:Name="lbl_count" FontSize="11" Foreground="#2F6496"
                     FontWeight="SemiBold" VerticalAlignment="Center" Margin="0,0,12,0"/>
          <Button x:Name="btn_copy" Width="130" Height="26" Margin="4,0,0,0"
                  Background="#2F6496" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close" Width="90" Height="26" Margin="4,0,0,0"
                  Background="#E74C3C" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

# =============================================================================
# HELPERS
# =============================================================================

def load_xaml(xaml_str):
    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(xaml_str))
    return System.Windows.Markup.XamlReader.Load(stream)


def do_events(dispatcher):
    """Pompe les evenements WPF pour rafraichir l'UI."""
    try:
        dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Background)
    except Exception:
        pass


def ft_to_m(ft):
    if USE_FORGE_UNITS:
        return float(UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Meters))
    return ft * 0.3048


def get_link_instances(document):
    """Retourne tous les RevitLinkInstance charges du document."""
    links = []
    collector = FilteredElementCollector(document).OfClass(RevitLinkInstance)
    for lnk in collector:
        linked_doc = lnk.GetLinkDocument()
        if linked_doc is not None:
            links.append((lnk, linked_doc))
    return links


def get_elevations_from_doc(linked_doc):
    """Retourne toutes les vues Elevation et Interior Elevation d'un document."""
    views = []
    collector = FilteredElementCollector(linked_doc).OfClass(View)
    for v in collector:
        if v.IsTemplate:
            continue
        vt = v.ViewType
        if vt in (ViewType.Elevation, ViewType.Section):
            # On ne prend que les vues qui ressemblent a des elevations
            # (pas les coupes, identifiees par leur ViewType = Section)
            views.append(v)
        # Interior elevation = aussi ViewType.Elevation
    return views


def get_elevation_views_only(linked_doc):
    """Retourne uniquement les vues de type Elevation (ext. et int.)."""
    views = []
    collector = FilteredElementCollector(linked_doc).OfClass(View)
    for v in collector:
        if v.IsTemplate:
            continue
        if v.ViewType == ViewType.Elevation:
            views.append(v)
    return views


def get_associated_sheet_info(view, linked_doc):
    """Retourne le numero de feuille associe a une vue, si place."""
    try:
        vports = FilteredElementCollector(linked_doc).OfClass(Viewport)
        for vp in vports:
            if vp.ViewId == view.Id:
                sheet = linked_doc.GetElement(vp.SheetId)
                if sheet:
                    sheet_num = sheet.get_Parameter(
                        BuiltInParameter.SHEET_NUMBER).AsString() or ""
                    sheet_name = sheet.get_Parameter(
                        BuiltInParameter.SHEET_NAME).AsString() or ""
                    return u"{} - {}".format(sheet_num, sheet_name)
    except Exception:
        pass
    return u""


def get_view_scale_str(view):
    try:
        scale = view.Scale
        if scale > 0:
            return u"1:{}".format(scale)
    except Exception:
        pass
    return u""


def get_view_level_name(view):
    try:
        p = view.get_Parameter(BuiltInParameter.PLAN_VIEW_LEVEL)
        if p:
            return p.AsString() or u""
    except Exception:
        pass
    try:
        p = view.LookupParameter("Associated Level")
        if p:
            return p.AsString() or u""
    except Exception:
        pass
    return u""


def view_already_exists(document, view_name):
    """Verifie si une vue de ce nom existe deja dans le document courant."""
    collector = FilteredElementCollector(document).OfClass(View)
    for v in collector:
        if not v.IsTemplate and v.Name == view_name:
            return True
    return False


def get_elevation_vft(document):
    """Retourne le ViewFamilyType Elevation disponible dans le document."""
    collector = FilteredElementCollector(document).OfClass(ViewFamilyType)
    for vft in collector:
        if vft.ViewFamily == ViewFamily.Elevation:
            return vft
    return None


def get_section_vft(document):
    """Retourne le ViewFamilyType Section disponible dans le document."""
    collector = FilteredElementCollector(document).OfClass(ViewFamilyType)
    for vft in collector:
        if vft.ViewFamily == ViewFamily.Section:
            return vft
    return None


def copy_elevation_to_host(host_doc, linked_doc, link_instance, source_view):
    """
    Recree une elevation dans le document hote via ViewSection.CreateSection().
    Compose la Transform du CropBox source avec celle du lien,
    puis tente 3 approches pour assigner la Transform au BoundingBoxXYZ.
    Retourne (True, nom_final) ou (False, message_erreur).
    """
    try:
        lnk_tr = link_instance.GetTotalTransform()

        # --- CropBox source et sa Transform ---
        src_cb     = source_view.CropBox
        src_cb_tr  = src_cb.Transform
        cb_min     = src_cb.Min
        cb_max     = src_cb.Max

        # Composer : monde_hote = lnk_tr * src_cb_tr
        composed_tr = lnk_tr.Multiply(src_cb_tr)

        # Creer le BoundingBoxXYZ avec Min/Max identiques a la source
        section_bb = BoundingBoxXYZ()
        section_bb.Min = cb_min
        section_bb.Max = cb_max

        # --- Tentative 1 : setter direct ---
        transform_ok = False
        try:
            section_bb.Transform = composed_tr
            transform_ok = True
        except Exception:
            pass

        if not transform_ok:
            # --- Tentative 2 : modifier le getter in-place ---
            try:
                t_ref = section_bb.Transform
                t_ref.Origin = composed_tr.Origin
                t_ref.BasisX = composed_tr.BasisX
                t_ref.BasisY = composed_tr.BasisY
                t_ref.BasisZ = composed_tr.BasisZ
                transform_ok = True
            except Exception:
                pass

        if not transform_ok:
            # --- Tentative 3 : reflection .NET SetValue ---
            try:
                bb_type = clr.GetClrType(BoundingBoxXYZ)
                prop = bb_type.GetProperty("Transform")
                if prop and prop.CanWrite:
                    prop.SetValue(section_bb, composed_tr, None)
                    transform_ok = True
            except Exception:
                pass

        if not transform_ok:
            return False, u"Impossible d'assigner la Transform au BoundingBoxXYZ."

        # --- ViewFamilyType Section ---
        vft = get_section_vft(host_doc)
        if vft is None:
            try:
                vft_id = host_doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
                if vft_id != ElementId.InvalidElementId:
                    vft = host_doc.GetElement(vft_id)
            except Exception:
                pass
        if vft is None:
            return False, u"Aucun ViewFamilyType Section trouve."

        try:
            scale = source_view.Scale
        except Exception:
            scale = 100

        target_name = source_view.Name

        # --- Transaction ---
        t = Transaction(host_doc, u"STR - Copie elevation depuis lien")
        try:
            t.Start()

            new_view = ViewSection.CreateSection(host_doc, vft.Id, section_bb)
            if new_view is None:
                t.RollBack()
                return False, u"Echec CreateSection."

            new_view.Scale = scale

            try:
                new_view.CropBoxActive  = True
                new_view.CropBoxVisible = False
            except Exception:
                pass

            final_name = target_name
            suffix = 1
            existing_names = set()
            for v in FilteredElementCollector(host_doc).OfClass(View):
                if not v.IsTemplate:
                    existing_names.add(v.Name)
            while final_name in existing_names:
                final_name = u"{} ({})".format(target_name, suffix)
                suffix += 1
            try:
                new_view.Name = final_name
            except Exception:
                pass

            t.Commit()
            return True, final_name

        except Exception as ex:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            return False, traceback.format_exc()

    except Exception as ex:
        return False, traceback.format_exc()





# =============================================================================
# CLASSE ROW DATAGRID
# =============================================================================

class ElevRow(object):
    def __init__(self, view, linked_doc, link_instance):
        self._view         = view
        self._linked_doc   = linked_doc
        self._link_instance = link_instance
        self.IsSelected    = False

        self.Nom     = view.Name
        vt           = view.ViewType
        self.TypeVue = u"Elevation interieure" if vt == ViewType.Elevation and self._is_interior(view) \
                       else u"Elevation"
        self.Echelle = get_view_scale_str(view)
        self.Niveau  = get_view_level_name(view)
        self.Feuille = get_associated_sheet_info(view, linked_doc)
        # Statut : existe deja dans host ? (nom d'origine conserve)
        self.Statut  = u"Deja copie" if view_already_exists(revit.doc, view.Name) \
                       else u"A copier"

    def _is_interior(self, view):
        try:
            fam_name = view.get_Parameter(BuiltInParameter.VIEW_FAMILY).AsString() or ""
            return "interior" in fam_name.lower()
        except Exception:
            return False

    def toggle(self):
        self.IsSelected = not self.IsSelected


# =============================================================================
# MAIN
# =============================================================================

def main():
    # --- Recuperer les liens charges ---
    links = get_link_instances(doc)
    if not links:
        MessageBox.Show(
            u"Aucune maquette liee chargee dans le projet.",
            u"{} [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
            MessageBoxButton.OK, MessageBoxImage.Warning
        )
        return

    # --- Charger XAML ---
    window = load_xaml(XAML)
    window.Title = TOOL_NAME
    window.FindName("lbl_footer").Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # Libelles (accents apres chargement XAML)
    window.FindName("lbl_link_label").Text = u"Maquette liee :"
    window.FindName("lbl_type_label").Text = u"Type :"
    window.FindName("chk_all").Content     = u"Tout selectionner"
    window.FindName("btn_refresh").Content  = u"Actualiser"
    window.FindName("btn_copy").Content     = u"Copier la selection"
    window.FindName("btn_close").Content    = u"Fermer"
    window.FindName("lbl_info").Text = (
        u"Selectionnez une maquette liee, choisissez les elevations a copier, "
        u"puis cliquez sur 'Copier la selection'."
    )

    # Headers colonnes
    dg = window.FindName("dg_main")
    dg.FindName("col_sel").Header     = u""
    dg.FindName("col_nom").Header     = u"Nom de la vue"
    dg.FindName("col_type").Header    = u"Type"
    dg.FindName("col_echelle").Header = u"Echelle"
    dg.FindName("col_niveau").Header  = u"Niveau"
    dg.FindName("col_feuille").Header = u"Feuille"
    dg.FindName("col_statut").Header  = u"Statut"

    # Remplir combo liens
    cmb_links = window.FindName("cmb_links")
    cmb_type  = window.FindName("cmb_type")
    lbl_count = window.FindName("lbl_count")

    for lnk, lnk_doc in links:
        item = ComboBoxItem()
        item.Content = lnk_doc.Title
        item.Tag     = (lnk, lnk_doc)
        cmb_links.Items.Add(item)

    if cmb_links.Items.Count > 0:
        cmb_links.SelectedIndex = 0

    # Remplir combo type filtrage
    for label in [u"Toutes les elevations", u"Elevation exterieure", u"Elevation interieure"]:
        item = ComboBoxItem()
        item.Content = label
        cmb_type.Items.Add(item)
    cmb_type.SelectedIndex = 0

    # Etat interne
    state = {"rows": [], "ok": False, "busy": False}

    def update_count():
        nb = sum(1 for r in state["rows"] if r.IsSelected)
        total = len(state["rows"])
        lbl_count.Text = u"{} / {} selectionnee(s)".format(nb, total)

    def refresh_grid(sender=None, e=None):
        if cmb_links.SelectedItem is None:
            return
        lnk, lnk_doc = cmb_links.SelectedItem.Tag
        type_filter   = cmb_type.SelectedIndex  # 0=tout, 1=ext, 2=int

        pnl_progress = window.FindName("pnl_progress")
        pb            = window.FindName("pb_main")
        lbl_prog      = window.FindName("lbl_progress")
        dispatcher    = window.Dispatcher

        # Desactiver les controles pendant le chargement
        cmb_links.IsEnabled = False
        cmb_type.IsEnabled  = False
        window.FindName("btn_refresh").IsEnabled = False
        window.FindName("btn_copy").IsEnabled    = False
        dg.ItemsSource = None

        # Afficher la barre de progression
        pnl_progress.Visibility = System.Windows.Visibility.Visible
        pb.Value = 0
        lbl_prog.Text = u"Lecture..."
        do_events(dispatcher)

        try:
            all_views = get_elevation_views_only(lnk_doc)
        except Exception as ex:
            pnl_progress.Visibility = System.Windows.Visibility.Collapsed
            cmb_links.IsEnabled = True
            cmb_type.IsEnabled  = True
            window.FindName("btn_refresh").IsEnabled = True
            window.FindName("btn_copy").IsEnabled    = True
            MessageBox.Show(
                u"Erreur lecture des vues :\n{}".format(str(ex)),
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error
            )
            return

        total_views = len(all_views)
        pb.Maximum  = max(total_views, 1)
        rows = []

        # Construction des lignes avec mise a jour progressive
        for i, v in enumerate(all_views):
            row = ElevRow(v, lnk_doc, lnk)
            if type_filter == 1 and "interieure" in row.TypeVue:
                continue
            if type_filter == 2 and "interieure" not in row.TypeVue:
                continue
            rows.append(row)
            # Rafraichir UI tous les 20 elements
            if i % 20 == 0:
                pb.Value = i + 1
                lbl_prog.Text = u"{} / {}".format(i + 1, total_views)
                do_events(dispatcher)

        pb.Value = total_views
        lbl_prog.Text = u"{} / {}".format(total_views, total_views)
        do_events(dispatcher)

        rows.sort(key=lambda r: r.Nom)
        state["rows"] = rows
        dg.ItemsSource = rows
        window.FindName("chk_all").IsChecked = False
        update_count()

        # Masquer la barre et re-activer les controles
        pnl_progress.Visibility = System.Windows.Visibility.Collapsed
        cmb_links.IsEnabled = True
        cmb_type.IsEnabled  = True
        window.FindName("btn_refresh").IsEnabled = True
        window.FindName("btn_copy").IsEnabled    = True
        lbl_count.Text = u"{} vues chargees".format(len(rows))
        do_events(dispatcher)

    def on_chk_all_changed(sender, e):
        checked = window.FindName("chk_all").IsChecked
        val     = bool(checked) if checked is not None else False
        for row in state["rows"]:
            row.IsSelected = val
        # Forcer refresh DataGrid
        dg.ItemsSource = None
        dg.ItemsSource = state["rows"]
        update_count()

    def on_cell_changed(sender, e):
        if state["busy"]:
            return
        if dg.CurrentColumn is None:
            return
        if dg.CurrentColumn.DisplayIndex == 0 and dg.CurrentItem is not None:
            state["busy"] = True
            try:
                dg.CurrentItem.toggle()
                src = dg.ItemsSource
                dg.ItemsSource = None
                dg.ItemsSource = src
            finally:
                state["busy"] = False
        update_count()

    def on_copy(sender, e):
        selected = [r for r in state["rows"] if r.IsSelected]
        if not selected:
            MessageBox.Show(
                u"Aucune elevation selectionnee.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning
            )
            return

        nb_ok  = 0
        errors = []
        for row in selected:
            ok, msg = copy_elevation_to_host(doc, row._linked_doc, row._link_instance, row._view)
            if ok:
                nb_ok += 1
                row.Statut = u"Copie : {}".format(msg)
            else:
                errors.append(u"[{}]\n{}".format(row.Nom, msg))
                row.Statut = u"ECHEC"

        dg.ItemsSource = None
        dg.ItemsSource = state["rows"]
        update_count()

        nb_err = len(errors)
        summary = u"{} elevation(s) copiee(s) avec succes.".format(nb_ok)
        if errors:
            # Fenetre scrollable pour voir les tracebacks complets
            err_win = Window()
            err_win.Title   = u"{} - Rapport d'erreurs".format(TOOL_NAME)
            err_win.Width   = 680
            err_win.Height  = 420
            err_win.ResizeMode = ResizeMode.CanResize
            err_win.WindowStartupLocation = WindowStartupLocation.CenterScreen
            err_win.Background = SolidColorBrush(Color.FromRgb(255,255,255))
            sp = StackPanel()
            sp.Margin = Thickness(10, 10, 10, 6)
            lbl_s = TextBlock()
            lbl_s.Text = summary + u"  |  {} erreur(s).".format(nb_err)
            lbl_s.FontWeight = System.Windows.FontWeights.Bold
            lbl_s.Margin = Thickness(0, 0, 0, 8)
            sp.Children.Add(lbl_s)
            sv = ScrollViewer()
            sv.Height = 280
            sv.HorizontalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
            sv.VerticalScrollBarVisibility   = System.Windows.Controls.ScrollBarVisibility.Auto
            tb = TextBlock()
            tb.Text       = u"\n\n".join(errors)
            tb.FontFamily = System.Windows.Media.FontFamily("Consolas")
            tb.FontSize   = 11
            tb.TextWrapping = System.Windows.TextWrapping.Wrap
            sv.Content  = tb
            sp.Children.Add(sv)
            btn_ok = Button()
            btn_ok.Content    = u"OK"
            btn_ok.Width      = 80
            btn_ok.Height     = 26
            btn_ok.Margin     = Thickness(0, 8, 0, 0)
            btn_ok.Background = SolidColorBrush(Color.FromRgb(52,152,219))
            btn_ok.Foreground = SolidColorBrush(Color.FromRgb(255,255,255))
            btn_ok.BorderThickness = Thickness(0)
            btn_ok.HorizontalAlignment = HorizontalAlignment.Right
            btn_ok.Click += lambda s, e: err_win.Close()
            sp.Children.Add(btn_ok)
            err_win.Content = sp
            err_win.ShowDialog()
        else:
            MessageBox.Show(summary, TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Information)

    # Connecter evenements
    cmb_links.SelectionChanged += refresh_grid
    cmb_type.SelectionChanged  += refresh_grid
    window.FindName("chk_all").Checked   += on_chk_all_changed
    window.FindName("chk_all").Unchecked += on_chk_all_changed
    window.FindName("btn_refresh").Click += refresh_grid
    window.FindName("btn_copy").Click    += on_copy
    window.FindName("btn_close").Click   += lambda s, e: window.Close()
    dg.CurrentCellChanged                += on_cell_changed

    # Chargement initial
    refresh_grid()

    window.ShowDialog()


main()