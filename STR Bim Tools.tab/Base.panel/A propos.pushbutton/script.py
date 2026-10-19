# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"À propos"
SITE           = u"www.str-bim-tools.com"
# =============================================================================
#  v1.1.0 - Fenetre reduite a l'embleme STR BIM Tools (logo.png) et au lien
#           vers le site.
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
    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import os

    from System import Uri
    from System.Diagnostics import Process
    from System.Windows import (Window, Thickness, WindowStartupLocation,
                                ResizeMode, SizeToContent, HorizontalAlignment)
    from System.Windows.Controls import Grid, StackPanel, Image
    from System.Windows.Documents import Hyperlink, Run
    from System.Windows.Media import RenderOptions, BitmapScalingMode
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

    import str_ui as UI

    LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    TAILLE_LOGO = 300
    # Fond du corps = bleu nuit des coins de l'embleme : le cercle flotte
    # sans cadre carre autour.
    FOND = "#010F27"
    LIEN = "#7FB8FF"

    def _image_logo():
        """Embleme en TAILLE_LOGO px, ou None si le fichier manque : la
        fenetre s'ouvre quand meme avec le seul lien."""
        if not os.path.isfile(LOGO):
            return None
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.UriSource = Uri(LOGO)
        bmp.CacheOption = BitmapCacheOption.OnLoad   # ne verrouille pas le fichier
        bmp.EndInit()
        img = Image()
        img.Source = bmp
        img.Width = TAILLE_LOGO
        img.Height = TAILLE_LOGO
        RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.HighQuality)
        return img

    class APropos(Window):

        def __init__(self):
            self.Title = u"STR BIM Tools - {0}".format(TOOL_NAME)
            self.SizeToContent = SizeToContent.WidthAndHeight
            self.WindowStartupLocation = WindowStartupLocation.CenterScreen
            self.ResizeMode = ResizeMode.NoResize
            self.Background = UI.couleur("fond")
            self._construire()

        def _construire(self):
            root = Grid()
            for h in ["*", "Auto"]:
                root.RowDefinitions.Add(UI.rd(h))
            self.Content = root

            corps = StackPanel()
            corps.Background = UI.hex_brush(FOND)
            img = _image_logo()
            if img is not None:
                img.Margin = Thickness(24, 20, 24, 4)
                corps.Children.Add(img)

            # Lien cliquable : un TextBlock ne suffit pas, il faut un
            # Hyperlink et l'ouverture par le navigateur du poste.
            lien_tb = UI.texte(u"", 13, marge=Thickness(24, 4, 24, 18))
            lien_tb.HorizontalAlignment = HorizontalAlignment.Center
            lien = Hyperlink(Run(SITE))
            lien.Foreground = UI.hex_brush(LIEN)
            try:
                lien.NavigateUri = Uri(u"https://" + SITE)
            except Exception:
                pass
            lien.RequestNavigate += self._on_lien
            lien_tb.Inlines.Add(lien)
            corps.Children.Add(lien_tb)

            Grid.SetRow(corps, 0)
            root.Children.Add(corps)

            footer, sp_btns, grid_f = UI.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 1)
            root.Children.Add(footer)
            sp_btns.Children.Add(UI.footer_btn(u"Fermer", "fermer", 90,
                                               lambda s, e: self.Close()))
            grid_f.Children.Add(sp_btns)

        def _on_lien(self, sender, e):
            """Ouvre le site dans le navigateur par défaut. Un lien mort ne
            doit pas faire tomber la fenêtre."""
            try:
                Process.Start(e.Uri.AbsoluteUri)
            except Exception:
                pass
            e.Handled = True

    APropos().ShowDialog()

except Exception as _ex:
    _show_fatal(u"STR BIM Tools - {0} - Erreur de chargement".format(TOOL_NAME),
                _ex)
