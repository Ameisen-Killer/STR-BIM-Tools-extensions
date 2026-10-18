# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Transparence"
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
    from System.Windows import Thickness
    from System.Windows.Media import SolidColorBrush, Color
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import Transaction, TransactionStatus, ElementId

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application
    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # Niveaux de transparence proposes (%) et couleur du bouton associee.
    # Couleur = interpolation lineaire entre le bleu charte #2F6496 (0%)
    # et le blanc #FFFFFF (80%) -> previsualisation directe du niveau.
    _BASE = (47, 100, 150)
    _WHITE = (255, 255, 255)

    def _lerp_hex(level):
        t = level / 100.0
        r = int(round(_BASE[0] + t * (_WHITE[0] - _BASE[0])))
        g = int(round(_BASE[1] + t * (_WHITE[1] - _BASE[1])))
        b = int(round(_BASE[2] + t * (_WHITE[2] - _BASE[2])))
        return "#{:02X}{:02X}{:02X}".format(r, g, b)

    LEVELS = [0, 20, 40, 60, 80]

    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    def apply_transparency(elem_ids, level):
        t = Transaction(doc, u"STR - Transparence {}%".format(level))
        try:
            t.Start()
            view = doc.ActiveView
            for eid in elem_ids:
                ovr = view.GetElementOverrides(eid)
                ovr.SetSurfaceTransparency(level)
                view.SetElementOverrides(eid, ovr)
            if t.GetStatus() == TransactionStatus.Started:
                t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise

    # Gabarit XAML obligatoire : barre titre bleue + corps + footer (ASCII strict)
    XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PLACEHOLDER" Width="400" Height="190" MinWidth="400" MinHeight="190"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen" Background="White">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
          <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
        </Border>
        <StackPanel Grid.Row="1" Orientation="Vertical" Margin="14,12,14,8">
          <TextBlock x:Name="lbl_hint" FontSize="11" Foreground="#555555" Margin="0,0,0,10"/>
          <StackPanel x:Name="sp_btns" Orientation="Horizontal" HorizontalAlignment="Center"/>
        </StackPanel>
        <Border Grid.Row="2" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
                Background="#F5F5F5" Padding="0,4">
          <Grid>
            <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                       VerticalAlignment="Center" Margin="8,0,0,0"/>
          </Grid>
        </Border>
      </Grid>
    </Window>"""

    def main():
        sel_ids = list(uidoc.Selection.GetElementIds())
        if not sel_ids:
            _show_info(TOOL_NAME, u"Aucun element selectionne.\n\n"
                                   u"Selectionnez un ou plusieurs elements dans la vue "
                                   u"avant de lancer l'outil.")
            return

        view = doc.ActiveView
        valid_ids = []
        for eid in sel_ids:
            try:
                view.GetElementOverrides(eid)
                valid_ids.append(eid)
            except Exception:
                pass

        if not valid_ids:
            _show_info(TOOL_NAME, u"Aucun des elements selectionnes ne supporte "
                                   u"les surcharges graphiques de vue.")
            return

        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        window = System.Windows.Markup.XamlReader.Load(stream)

        # Version UNIQUEMENT dans le footer - PAS dans le titre de la fenetre OS
        window.Title = TOOL_NAME
        window.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        window.FindName("lbl_hint").Text   = u"Appliquer la transparence a {} element(s) selectionne(s) :".format(len(valid_ids))
        window.FindName("lbl_footer").Text = _FOOTER

        sp_btns = window.FindName("sp_btns")

        def make_handler(level):
            def _on_click(sender, args):
                try:
                    apply_transparency(valid_ids, level)
                except Exception as ex:
                    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), ex)
                    return
                uidoc.Selection.SetElementIds(List[ElementId]())
                window.Close()
            return _on_click

        for level in LEVELS:
            bg_hex = _lerp_hex(level)
            fg_hex = "#2F6496" if level >= 60 else "#FFFFFF"
            btn = SW.Controls.Button()
            btn.Content = u"{} %".format(level)
            btn.Width = 62
            btn.Height = 34
            btn.Margin = Thickness(4, 0, 4, 0)
            btn.Background = hex_brush(bg_hex)
            btn.Foreground = hex_brush(fg_hex)
            btn.FontWeight = SW.FontWeights.SemiBold
            btn.BorderBrush = hex_brush("#C0D0E0")
            btn.BorderThickness = Thickness(1)
            btn.Click += make_handler(level)
            sp_btns.Children.Add(btn)

        window.ShowDialog()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
