# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Console Python"
# =============================================================================

import sys
import io
import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction
)
from Autodesk.Revit.UI import TaskDialog

import System
import System.IO
import System.Text
from System.Windows import (
    Window, GridLength, GridUnitType, Thickness,
    HorizontalAlignment, VerticalAlignment,
    WindowStartupLocation, FontWeights
)
from System.Windows.Controls import (
    Grid, StackPanel, TextBlock, Button, Border,
    ScrollViewer, RowDefinition, ColumnDefinition,
    TextBox, ScrollBarVisibility
)
from System.Windows.Media import SolidColorBrush, Color, FontFamily
from System.Windows.Markup import XamlReader

# ---------------------------------------------------------------------------
# Acces Revit
# ---------------------------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
app   = __revit__.Application

# ---------------------------------------------------------------------------
# XAML  (ASCII strict — les textes accentues sont assignes apres chargement)
# ---------------------------------------------------------------------------
XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Width="820" Height="640"
    MinWidth="600" MinHeight="400"
    Background="White"
    ResizeMode="CanResize"
    WindowStartupLocation="CenterScreen">

  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>   <!-- label editeur -->
      <RowDefinition Height="3*"/>     <!-- editeur de code -->
      <RowDefinition Height="4"/>      <!-- separateur -->
      <RowDefinition Height="Auto"/>   <!-- label sortie -->
      <RowDefinition Height="*"/>      <!-- zone de sortie -->
      <RowDefinition Height="Auto"/>   <!-- footer -->
    </Grid.RowDefinitions>

    <!-- === LABEL EDITEUR === -->
    <TextBlock x:Name="lbl_editor" Grid.Row="0"
               FontSize="11" FontWeight="SemiBold"
               Foreground="#2C3E50" Margin="8,8,8,2"/>

    <!-- === EDITEUR CODE === -->
    <Border Grid.Row="1" BorderBrush="#C0D0E0" BorderThickness="1" Margin="8,0,8,0">
      <TextBox x:Name="txt_code"
               AcceptsReturn="True"
               AcceptsTab="True"
               HorizontalScrollBarVisibility="Auto"
               VerticalScrollBarVisibility="Auto"
               FontFamily="Consolas"
               FontSize="12"
               Padding="6"
               Background="#FAFCFF"
               Foreground="#1A1A2E"
               BorderThickness="0"/>
    </Border>

    <!-- === SEPARATEUR === -->
    <Border Grid.Row="2" Background="#C0D0E0" Margin="8,4"/>

    <!-- === LABEL SORTIE === -->
    <TextBlock x:Name="lbl_output" Grid.Row="3"
               FontSize="11" FontWeight="SemiBold"
               Foreground="#2C3E50" Margin="8,2,8,2"/>

    <!-- === ZONE DE SORTIE === -->
    <Border Grid.Row="4" BorderBrush="#C0D0E0" BorderThickness="1" Margin="8,0,8,0">
      <TextBox x:Name="txt_output"
               IsReadOnly="True"
               AcceptsReturn="True"
               HorizontalScrollBarVisibility="Auto"
               VerticalScrollBarVisibility="Auto"
               FontFamily="Consolas"
               FontSize="11"
               Padding="6"
               Background="#F5F5F5"
               Foreground="#1A1A2E"
               BorderThickness="0"/>
    </Border>

    <!-- === FOOTER === -->
    <Border Grid.Row="5" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer"
                   FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_clear"
                  Width="90" Height="26" Margin="0,0,6,0"
                  FontSize="12"/>
          <Button x:Name="btn_run"
                  Width="110" Height="26" Margin="0,0,0,0"
                  FontSize="12" FontWeight="SemiBold"/>
        </StackPanel>
      </Grid>
    </Border>

  </Grid>
</Window>
"""

# ---------------------------------------------------------------------------
# Chargement WPF
# ---------------------------------------------------------------------------
stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
window = XamlReader.Load(stream)

# ---------------------------------------------------------------------------
# Recuperation des controles
# ---------------------------------------------------------------------------
lbl_editor = window.FindName("lbl_editor")
txt_code   = window.FindName("txt_code")
lbl_output = window.FindName("lbl_output")
txt_output = window.FindName("txt_output")
lbl_footer = window.FindName("lbl_footer")
btn_clear  = window.FindName("btn_clear")
btn_run    = window.FindName("btn_run")

# ---------------------------------------------------------------------------
# Textes (assigns apres chargement pour supporter les accents)
# ---------------------------------------------------------------------------
window.Title          = TOOL_NAME
lbl_editor.Text       = u"Code Python :"
lbl_output.Text       = u"Sortie / Erreurs :"
lbl_footer.Text       = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
btn_clear.Content     = u"Effacer"
btn_run.Content       = u"Executer"

# Couleurs boutons
def _brush(r, g, b):
    c = Color()
    c.R, c.G, c.B, c.A = r, g, b, 255
    return SolidColorBrush(c)

btn_run.Background   = _brush(46, 204, 113)   # vert
btn_run.Foreground   = _brush(255, 255, 255)
btn_clear.Background = _brush(231, 76, 60)    # rouge
btn_clear.Foreground = _brush(255, 255, 255)

# Texte d'accueil dans l'editeur
PLACEHOLDER = u"""# Coller ici le code Python a executer.
# Les variables suivantes sont disponibles directement :
#   doc   -> Document Revit actif
#   uidoc -> UIDocument
#   app   -> Application Revit
#   Transaction, FilteredElementCollector, ...
#
# Exemple :
# walls = FilteredElementCollector(doc).OfCategory(
#     BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()
# print(len(walls))
"""
txt_code.Text = PLACEHOLDER

# ---------------------------------------------------------------------------
# Redirection stdout / stderr
# ---------------------------------------------------------------------------
class _OutputRedirect(object):
    """Redirige sys.stdout et sys.stderr vers le TextBox de sortie."""
    def __init__(self, textbox):
        self._tb = textbox
        self._buf = []

    def write(self, msg):
        self._buf.append(msg)
        self._tb.Text += msg

    def flush(self):
        pass

    def clear(self):
        self._buf = []
        self._tb.Text = u""

# ---------------------------------------------------------------------------
# Gestionnaire "Effacer"
# ---------------------------------------------------------------------------
def on_clear(sender, e):
    txt_code.Text = u""
    txt_output.Text = u""
    txt_code.Focus()

btn_clear.Click += on_clear

# ---------------------------------------------------------------------------
# Gestionnaire "Executer"
# ---------------------------------------------------------------------------
def on_run(sender, e):
    code = txt_code.Text
    if not code.strip():
        txt_output.Text = u"(aucun code a executer)"
        return

    # Préparer la redirection
    out_redirect = _OutputRedirect(txt_output)
    txt_output.Text = u""

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = out_redirect
    sys.stderr = out_redirect

    # Construire le contexte d execution
    exec_globals = {
        "__builtins__"                  : __builtins__,
        "doc"                           : doc,
        "uidoc"                         : uidoc,
        "app"                           : app,
        "Transaction"                   : Transaction,
        "FilteredElementCollector"      : FilteredElementCollector,
    }

    # Injecter les imports courants de la Revit API
    try:
        from Autodesk.Revit.DB import (
            BuiltInCategory, BuiltInParameter, ElementId,
            Level, Wall, Floor, FamilyInstance,
            FilteredWorksetCollector, WorksetKind
        )
        exec_globals.update({
            "BuiltInCategory"            : BuiltInCategory,
            "BuiltInParameter"           : BuiltInParameter,
            "ElementId"                  : ElementId,
            "Level"                      : Level,
            "Wall"                       : Wall,
            "Floor"                      : Floor,
            "FamilyInstance"             : FamilyInstance,
            "FilteredWorksetCollector"   : FilteredWorksetCollector,
            "WorksetKind"                : WorksetKind,
        })
    except Exception:
        pass

    try:
        exec(compile(code, "<console>", "exec"), exec_globals)
    except Exception:
        sys.stderr.write(u"\n--- ERREUR ---\n")
        sys.stderr.write(traceback.format_exc())
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Scroll vers le bas de la sortie
    txt_output.ScrollToEnd()

    # Feedback si rien ne s'est affiche
    if not txt_output.Text.strip():
        txt_output.Text = u"(execution terminee sans sortie)"

btn_run.Click += on_run

# ---------------------------------------------------------------------------
# Lancement de la fenetre
# ---------------------------------------------------------------------------
window.ShowDialog()