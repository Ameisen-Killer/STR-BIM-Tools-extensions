# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.1"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Nettoyer Control"

# Parametres figes (ex-entrees Dynamo IN[0]/IN[1]/IN[2])
FAMILY_PREFIX = u"FGH_RES_"
PARAM_NAME    = u"CONTROL_NE_PAS_TOUCHER"
MARKER        = u"_R2"
# =============================================================================

# Hors filet - strict minimum pour afficher les erreurs fatales
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogIcon


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


def _show_info(title, message):
    td = TaskDialog(title)
    td.MainContent   = message
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.MainIcon      = TaskDialogIcon.TaskDialogIconInformation
    td.Show()


try:
    import System, System.IO, System.Text, System.Windows.Markup
    clr.AddReference('PresentationFramework'); clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase'); clr.AddReference('System')
    import System.Windows as SW
    import System.Windows.Controls as SWC
    from System.Windows import Thickness
    from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
                                   FamilyInstance, StorageType, Transaction,
                                   TransactionStatus, Element)

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application
    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    def _elem_name(el):
        """Nom d'un Element/ElementType. Contournement necessaire car FamilySymbol
        (et ElementType en general) redeclare Name d'une facon qui provoque un
        AttributeError sur l'acces direct .Name en IronPython."""
        if el is None:
            return u""
        try:
            return el.Name
        except AttributeError:
            return Element.Name.__get__(el)

    def substring_to_marker(text):
        """Tronque `text` jusqu'au marqueur inclus, plus un caractere supplementaire."""
        index = text.find(MARKER)
        if index == -1:
            return text
        return text[:index + len(MARKER) + 1]

    # --- Collecte des instances "Modele generique" dont la famille commence par FAMILY_PREFIX ---
    def collect_targets():
        collector = (FilteredElementCollector(doc)
                     .OfCategory(BuiltInCategory.OST_GenericModel)
                     .OfClass(FamilyInstance))
        targets = []
        for inst in collector:
            symbol = inst.Symbol
            if not symbol:
                continue
            family = symbol.Family
            if not family:
                continue
            fam_name = _elem_name(family)
            if fam_name and fam_name.startswith(FAMILY_PREFIX):
                targets.append(inst)
        return targets

    # ⚠️ Donnees legeres uniquement dans le constructeur (pas d'appel API lourd)
    class Row(object):
        def __init__(self, elem_id, famille, type_nom, valeur_actuelle, valeur_modifiee):
            self.Id              = elem_id.IntegerValue
            self.ElemId          = elem_id
            self.Famille         = famille
            self.Type            = type_nom
            self.ValeurActuelle  = valeur_actuelle
            self.ValeurModifiee  = valeur_modifiee
            self.IsSelected      = True

        def toggle(self):
            self.IsSelected = not self.IsSelected

    def build_rows(targets):
        rows = []
        skipped_no_param = 0
        for inst in targets:
            p = inst.LookupParameter(PARAM_NAME)
            if not p or p.IsReadOnly or p.StorageType != StorageType.String:
                skipped_no_param += 1
                continue
            old_value = p.AsString()
            if old_value is None:
                skipped_no_param += 1
                continue
            new_value = substring_to_marker(old_value)
            symbol = inst.Symbol
            famille  = _elem_name(symbol.Family) if symbol else u""
            type_nom = _elem_name(symbol) if symbol else u""
            rows.append(Row(inst.Id, famille, type_nom, old_value, new_value))
        return rows, skipped_no_param

    XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="900" Height="560" MinWidth="700" MinHeight="380"
        WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
          <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
        </Border>
        <Border Grid.Row="1" Background="#F0F6FF" BorderBrush="#C0D0E0"
                BorderThickness="0,0,0,1" Padding="8,7">
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="Auto"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBox x:Name="txt_filtre" Grid.Column="0" Height="26" VerticalContentAlignment="Center"
                     Padding="6,0" Margin="0,0,8,0" BorderBrush="#C0D0E0"/>
            <Button x:Name="btn_tout_cocher" Grid.Column="1" Width="110" Height="26" Margin="0,0,6,0"
                    Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
            <Button x:Name="btn_tout_decocher" Grid.Column="2" Width="110" Height="26" Margin="0,0,10,0"
                    Background="#E74C3C" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
            <TextBlock x:Name="lbl_compteur" Grid.Column="3" FontSize="11" Foreground="#2F6496"
                       FontWeight="SemiBold" VerticalAlignment="Center"/>
          </Grid>
        </Border>
        <DataGrid x:Name="dg_main" Grid.Row="2" Margin="8,8,8,4"
                  AutoGenerateColumns="False" IsReadOnly="False"
                  AlternatingRowBackground="#E8F0FA" RowBackground="White"
                  GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
                  HeadersVisibility="Column" CanUserResizeColumns="True" CanUserSortColumns="True"
                  SelectionMode="Extended" SelectionUnit="Cell" FontSize="12">
          <DataGrid.ColumnHeaderStyle>
            <Style TargetType="DataGridColumnHeader">
              <Setter Property="Background" Value="#D0E4F7"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
              <Setter Property="Padding" Value="6,3"/>
            </Style>
          </DataGrid.ColumnHeaderStyle>
          <DataGrid.Columns>
            <DataGridCheckBoxColumn x:Name="col_sel" Binding="{Binding IsSelected}" Width="40" SortMemberPath="IsSelected"/>
            <DataGridTextColumn x:Name="col_id" Binding="{Binding Id}" Width="70" IsReadOnly="True"/>
            <DataGridTextColumn x:Name="col_famille" Binding="{Binding Famille}" Width="180" IsReadOnly="True"/>
            <DataGridTextColumn x:Name="col_type" Binding="{Binding Type}" Width="150" IsReadOnly="True"/>
            <DataGridTextColumn x:Name="col_avant" Binding="{Binding ValeurActuelle}" Width="*" IsReadOnly="True"/>
            <DataGridTextColumn x:Name="col_apres" Binding="{Binding ValeurModifiee}" Width="*" IsReadOnly="True"/>
          </DataGrid.Columns>
        </DataGrid>
        <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,4">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="8,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
              <Button x:Name="btn_annuler" Width="100" Height="28" Margin="4,0,0,0"
                      Background="#E74C3C" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
              <Button x:Name="btn_appliquer" Width="100" Height="28" Margin="6,0,0,0"
                      Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    def main():
        targets = collect_targets()
        if not targets:
            _show_info(TOOL_NAME, u"Aucune instance de famille commencant par \"{}\" "
                                   u"trouvee dans le projet.".format(FAMILY_PREFIX))
            return

        all_rows, skipped = build_rows(targets)
        # On n'affiche que les lignes ou la troncature change reellement quelque chose
        changed_rows = [r for r in all_rows if r.ValeurModifiee != r.ValeurActuelle]

        if not changed_rows:
            msg = (u"{} instance(s) \"{}\" trouvee(s), mais aucune valeur de "
                   u"\"{}\" ne necessite de troncature (marqueur \"{}\" absent "
                   u"ou valeur deja a jour).").format(len(all_rows), FAMILY_PREFIX,
                                                       PARAM_NAME, MARKER)
            if skipped:
                msg += u"\n({} instance(s) ignoree(s) : parametre absent, protege ou vide.)".format(skipped)
            _show_info(TOOL_NAME, msg)
            return

        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)

        window.Title = TOOL_NAME
        window.FindName("lbl_titre").Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        window.FindName("lbl_footer").Text = _FOOTER
        window.FindName("btn_tout_cocher").Content   = u"Tout cocher"
        window.FindName("btn_tout_decocher").Content = u"Tout decocher"
        window.FindName("btn_annuler").Content   = u"Annuler"
        window.FindName("btn_appliquer").Content = u"Appliquer"
        window.FindName("txt_filtre").Tag = u"Filtrer (famille, type, valeur)..."

        col_famille = window.FindName("col_famille")
        col_type    = window.FindName("col_type")
        col_avant   = window.FindName("col_avant")
        col_apres   = window.FindName("col_apres")
        if col_famille is not None: col_famille.Header = u"Famille"
        if col_type    is not None: col_type.Header    = u"Type"
        if col_avant   is not None: col_avant.Header   = u"Valeur actuelle"
        if col_apres   is not None: col_apres.Header   = u"Valeur modifiee"
        window.FindName("col_id").Header = u"ID"

        dg = window.FindName("dg_main")
        lbl_compteur = window.FindName("lbl_compteur")
        txt_filtre   = window.FindName("txt_filtre")

        state = {"applied": False}

        def refresh_counter():
            n_sel = sum(1 for r in changed_rows if r.IsSelected)
            lbl_compteur.Text = u"{} / {} selectionne(s)".format(n_sel, len(changed_rows))

        def apply_filter():
            txt = (txt_filtre.Text or u"").strip().lower()
            if not txt:
                visible = changed_rows
            else:
                visible = [r for r in changed_rows if
                           txt in r.Famille.lower() or
                           txt in r.Type.lower() or
                           txt in r.ValeurActuelle.lower() or
                           txt in r.ValeurModifiee.lower()]
            dg.ItemsSource = None
            dg.ItemsSource = visible

        def on_filter_changed(sender, args):
            apply_filter()

        def on_cell_changed(sender, args):
            # Coche/decoche via la colonne 0 -> source de verite = objet Row (set Python-like)
            if dg.CurrentColumn and dg.CurrentColumn.DisplayIndex == 0 and dg.CurrentItem:
                dg.CurrentItem.toggle()
                refresh_counter()
                src = dg.ItemsSource
                dg.ItemsSource = None
                dg.ItemsSource = src

        def on_tout_cocher(sender, args):
            for r in changed_rows:
                r.IsSelected = True
            apply_filter()
            refresh_counter()

        def on_tout_decocher(sender, args):
            for r in changed_rows:
                r.IsSelected = False
            apply_filter()
            refresh_counter()

        def on_annuler(sender, args):
            window.Close()

        def on_appliquer(sender, args):
            selection = [r for r in changed_rows if r.IsSelected]
            if not selection:
                _show_info(TOOL_NAME, u"Aucune ligne cochee.")
                return

            t = Transaction(doc, u"STR - Nettoyer {}".format(PARAM_NAME))
            errors = 0
            try:
                t.Start()
                for r in selection:
                    inst = doc.GetElement(r.ElemId)
                    if inst is None:
                        errors += 1
                        continue
                    p = inst.LookupParameter(PARAM_NAME)
                    if not p or p.IsReadOnly:
                        errors += 1
                        continue
                    p.Set(r.ValeurModifiee)
                if t.GetStatus() == TransactionStatus.Started:
                    t.Commit()
            except Exception:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                raise

            state["applied"] = True
            window.Close()

            msg = u"{} element(s) modifie(s).".format(len(selection) - errors)
            if errors:
                msg += u"\n{} element(s) n'ont pas pu etre modifies (parametre protege ou introuvable).".format(errors)
            _show_info(TOOL_NAME, msg)

        apply_filter()
        refresh_counter()

        txt_filtre.TextChanged += on_filter_changed
        dg.CurrentCellChanged  += on_cell_changed
        window.FindName("btn_tout_cocher").Click   += on_tout_cocher
        window.FindName("btn_tout_decocher").Click += on_tout_decocher
        window.FindName("btn_annuler").Click   += on_annuler
        window.FindName("btn_appliquer").Click += on_appliquer

        window.ShowDialog()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
