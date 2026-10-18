# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Mise a jour STR BIM Tools"
# =============================================================================
#
# Met a jour l'extension depuis son depot GitHub (git fetch + pull via
# l'updater pyRevit, qui reutilise le token enregistre dans le gestionnaire
# d'extensions), puis recharge pyRevit.
#
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


def _show_info(title, message, warning=False):
    td = TaskDialog(title)
    td.MainContent   = message
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.MainIcon      = (TaskDialogIcon.TaskDialogIconWarning if warning
                        else TaskDialogIcon.TaskDialogIconInformation)
    td.Show()


try:
    import os
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    import System, System.IO, System.Text, System.Windows.Markup
    from System.Windows.Input import Cursors, Mouse

    from pyrevit.coreutils import git as libgit
    from pyrevit.versionmgr import updater
    from pyrevit.loader import sessionmgr

    app = __revit__.Application
    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    _TITRE  = u"Mise à jour STR BIM Tools"

    # script.py > Mise a jour.pushbutton > Base.panel > .tab > racine extension
    EXT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Width="640" Height="440" MinWidth="480" MinHeight="320"
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
                BorderThickness="0,0,0,1" Padding="12,8">
          <StackPanel>
            <TextBlock x:Name="lbl_statut" FontSize="12" FontWeight="SemiBold"
                       Foreground="#2F6496" TextWrapping="Wrap"/>
            <TextBlock x:Name="lbl_local" FontSize="11" Foreground="#555555"
                       Margin="0,4,0,0" TextWrapping="Wrap"/>
            <TextBlock x:Name="lbl_alerte" FontSize="11" Foreground="#C0392B"
                       Margin="0,4,0,0" TextWrapping="Wrap" Visibility="Collapsed"/>
          </StackPanel>
        </Border>
        <DataGrid x:Name="dg_commits" Grid.Row="2" Margin="8,8,8,4"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  AlternatingRowBackground="#E8F0FA" RowBackground="White"
                  GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
                  HeadersVisibility="Column" CanUserResizeColumns="True"
                  CanUserSortColumns="False" FontSize="12">
          <DataGrid.ColumnHeaderStyle>
            <Style TargetType="DataGridColumnHeader">
              <Setter Property="Background" Value="#D0E4F7"/>
              <Setter Property="FontWeight" Value="SemiBold"/>
              <Setter Property="Padding" Value="6,3"/>
            </Style>
          </DataGrid.ColumnHeaderStyle>
          <DataGrid.Columns>
            <DataGridTextColumn x:Name="col_date" Binding="{Binding Date}" Width="120"/>
            <DataGridTextColumn x:Name="col_msg" Binding="{Binding Message}" Width="*"/>
          </DataGrid.Columns>
        </DataGrid>
        <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,6">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="10,0,0,0"/>
            <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,10,0">
              <Button x:Name="btn_update" Width="120" Height="28" Margin="0,0,6,0"
                      Background="#2ECC71" Foreground="White" FontWeight="SemiBold"
                      BorderThickness="0"/>
              <Button x:Name="btn_close" Width="90" Height="28"
                      Background="#3498DB" Foreground="White" FontWeight="SemiBold"
                      BorderThickness="0"/>
            </StackPanel>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    class CommitRow(object):
        def __init__(self, commit):
            self.Date    = commit.Author.When.LocalDateTime.ToString("dd.MM.yyyy HH:mm")
            self.Message = commit.MessageShort

    def _fmt_commit(commit):
        return u"{} du {}".format(
            commit.Id.Sha[:7],
            commit.Author.When.LocalDateTime.ToString("dd.MM.yyyy HH:mm"))

    def _nouveaux_commits(repo):
        """Commits du depot distant absents de la version installee."""
        filt = libgit.libgit.CommitFilter()
        filt.IncludeReachableFrom = repo.Head.TrackedBranch.Tip
        filt.ExcludeReachableFrom = repo.Head.Tip
        filt.SortBy = libgit.libgit.CommitSortStrategies.Time
        return list(repo.Commits.QueryBy(filt))

    def _a_modifs_locales(repo):
        """Fichiers suivis modifies sur ce poste (les non suivis sont ignores)."""
        try:
            opts = libgit.libgit.StatusOptions()
            opts.IncludeUntracked = False
            return repo.RetrieveStatus(opts).IsDirty
        except Exception:
            return False

    def main():
        repo_path = libgit.libgit.Repository.Discover(EXT_ROOT)
        if not repo_path:
            _show_info(_TITRE,
                       u"Cette copie de STR BIM Tools n'a pas été installée depuis "
                       u"GitHub, elle ne peut donc pas être mise à jour ici.\n\n"
                       u"Installe-la avec le gestionnaire d'extensions pyRevit "
                       u"(URL Git + token).\n\nDossier : " + EXT_ROOT,
                       warning=True)
            return

        repo_info = libgit.get_repo(repo_path)
        repo = repo_info.repo
        if repo.Head.TrackedBranch is None:
            _show_info(_TITRE,
                       u"La branche locale « {} » ne suit aucune branche distante."
                       .format(repo_info.branch), warning=True)
            return

        Mouse.OverrideCursor = Cursors.Wait
        try:
            ok = updater.get_updates(repo_info)
        finally:
            Mouse.OverrideCursor = None
        if not ok:
            _show_info(_TITRE,
                       u"Impossible de contacter le dépôt GitHub.\n\n"
                       u"Vérifie ta connexion internet. Si elle fonctionne, le token "
                       u"a peut-être expiré : saisis-en un nouveau dans le "
                       u"gestionnaire d'extensions pyRevit.", warning=True)
            return

        nouveaux = _nouveaux_commits(repo)
        div      = libgit.compare_branch_heads(repo_info)
        en_avance = (div.AheadBy or 0) if div is not None else 0

        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)
        window.Title = _TITRE
        window.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(_TITRE, app.VersionNumber)
        window.FindName("lbl_footer").Text = _FOOTER
        window.FindName("col_date").Header = u"Date"
        window.FindName("col_msg").Header  = u"Nouveautés"
        window.FindName("lbl_local").Text  = u"Version installée : " + _fmt_commit(repo.Head.Tip)

        btn_update = window.FindName("btn_update")
        btn_close  = window.FindName("btn_close")
        btn_update.Content = u"Mettre à jour"
        btn_close.Content  = u"Fermer"

        if nouveaux:
            window.FindName("lbl_statut").Text = (
                u"{} nouveauté(s) disponible(s).".format(len(nouveaux)))
            window.FindName("dg_commits").ItemsSource = [CommitRow(c) for c in nouveaux]
        else:
            window.FindName("lbl_statut").Text = u"STR BIM Tools est à jour."
            btn_update.IsEnabled = False
            btn_update.Opacity   = 0.5

        alertes = []
        if _a_modifs_locales(repo):
            alertes.append(u"Des fichiers de l'extension ont été modifiés sur ce poste : "
                           u"la mise à jour peut échouer s'ils ont aussi changé sur GitHub.")
        if en_avance:
            alertes.append(u"{} modification(s) locale(s) n'ont pas été envoyées sur GitHub."
                           .format(en_avance))
        if alertes:
            lbl = window.FindName("lbl_alerte")
            lbl.Text = u"\n".join(alertes)
            lbl.Visibility = System.Windows.Visibility.Visible

        state = {"updated": False}

        def on_update(sender, args):
            window.Cursor = Cursors.Wait
            try:
                updater.update_repo(repo_info)
                state["updated"] = True
                window.Close()
            except Exception as ex:
                window.Cursor = None
                _show_info(_TITRE,
                           u"La mise à jour a échoué :\n\n{}".format(ex), warning=True)

        btn_update.Click += on_update
        btn_close.Click  += lambda s, e: window.Close()
        window.ShowDialog()

        if state["updated"]:
            sessionmgr.reload_pyrevit()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
