# -*- coding: utf-8 -*-
"""
HAUTEUR D'ÉTAYAGE — SOL SÉLECTIONNÉ
=====================================
Pour le sol sélectionné dans Revit :
  - Calcule la distance vers la dalle immédiatement inférieure
  - Affiche les valeurs actuelles de STR_Hauteur_Etayage_Auto et _Manuel
  - Permet d'enregistrer la valeur calculée dans STR_Hauteur_Etayage_Auto
  - Permet de saisir et enregistrer une valeur dans STR_Hauteur_Etayage_Manuel

Revit 2024 / pyRevit / IronPython 2.7
"""
__doc__ = "Calcule la hauteur d'étayage sous la dalle sélectionnée."

import os
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    Transaction, ExternalDefinitionCreationOptions,
    CategorySet, StorageType, BuiltInParameter, ElementId,
    View3D, ViewFamilyType, ViewFamily, BoundingBoxXYZ, XYZ
)
from System.Collections.Generic import List as DotNetList

# Groupe "Cotes" : GroupTypeId.Geometry (Revit 2024+) | PG_GEOMETRY (Revit <2024)
try:
    from Autodesk.Revit.DB import GroupTypeId
    try:
        PARAM_GROUP = GroupTypeId.Geometry
    except AttributeError:
        PARAM_GROUP = GroupTypeId.Data
except ImportError:
    from Autodesk.Revit.DB import BuiltInParameterGroup
    PARAM_GROUP = BuiltInParameterGroup.PG_GEOMETRY

try:
    from Autodesk.Revit.DB import SpecTypeId
    PARAM_SPEC = SpecTypeId.String.Text
    USE_FORGE_SPEC = True
except ImportError:
    from Autodesk.Revit.DB import ParameterType
    USE_FORGE_SPEC = False

from System.Windows.Markup import XamlReader

from pyrevit import revit, forms, script

# ─── CONFIG ────────────────────────────────────────────────────────────────────

SCRIPT_VERSION       = u"1.2"
SCRIPT_AUTHOR        = u"Tony Varin"
TOOL_NAME            = u"Hauteur Etayage Individuel"
PARAM_AUTO           = "STR_Hauteur_Etayage_Auto"
PARAM_MANUEL         = "STR_Hauteur_Etayage_Manuel"
PARAMS_NEEDED        = [PARAM_AUTO, PARAM_MANUEL]
SHARED_PARAM_GROUP_NAME = "STR - Étayage"
NO_SLAB_BELOW_TEXT   = "Aucune dalle inférieure"
Z_TOLERANCE_FT       = 0.001 / 0.3048   # 1 mm en pieds

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def feet_to_cm(v):
    return v * 30.48

def centroid_inside_bbox_xy(cx, cy, bb):
    if bb is None:
        return False
    return (bb.Min.X <= cx <= bb.Max.X) and (bb.Min.Y <= cy <= bb.Max.Y)

def get_param_by_name(element, name):
    for p in element.Parameters:
        if p.Definition.Name == name:
            return p
    return None

def read_param(element, name):
    p = get_param_by_name(element, name)
    if p is None:
        return u"\u2014"
    v = p.AsString()
    return v if v else u"\u2014"

def write_param(doc, element, name, value):
    t = Transaction(doc, u"\u00c9criture {}".format(name))
    t.Start()
    try:
        p = get_param_by_name(element, name)
        if p and p.StorageType == StorageType.String:
            p.Set(value)
            t.Commit()
            return True
        t.RollBack()
        return False
    except Exception as e:
        t.RollBack()
        forms.alert(u"Erreur \u00e9criture :\n{}".format(str(e)))
        return False

# ─── GESTION PARAMÈTRES PARTAGÉS ───────────────────────────────────────────────

def get_bound_param_names(doc):
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        names.add(it.Key.Name)
    return names

def create_shared_parameters(doc, app, params_to_create):
    spf_path = app.SharedParametersFilename
    if not spf_path or not os.path.exists(spf_path):
        spf_path = os.path.join(
            os.environ.get("TEMP", "C:\\Temp"),
            "pyrevit_etayage_shared_params.txt"
        )
        with open(spf_path, "w") as f:
            f.write("# This is a Revit shared parameter file.\n")
            f.write("# Do not edit manually.\n")
            f.write("*META\tVERSION\tMINVERSION\n")
            f.write("META\t2\t1\n")
        app.SharedParametersFilename = spf_path

    spf = app.OpenSharedParameterFile()
    if spf is None:
        forms.alert(u"Impossible d'ouvrir le fichier de param\u00e8tres partag\u00e9s.",
                    exitscript=True)
        return False

    grp = spf.Groups.get_Item(SHARED_PARAM_GROUP_NAME)
    if grp is None:
        grp = spf.Groups.Create(SHARED_PARAM_GROUP_NAME)

    floors_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Floors)
    cat_set = CategorySet()
    cat_set.Insert(floors_cat)
    instance_binding = app.Create.NewInstanceBinding(cat_set)

    for param_name in params_to_create:
        ext_defn = grp.Definitions.get_Item(param_name)
        if ext_defn is None:
            if USE_FORGE_SPEC:
                opts = ExternalDefinitionCreationOptions(param_name, PARAM_SPEC)
            else:
                opts = ExternalDefinitionCreationOptions(param_name, ParameterType.Text)
            opts.Visible = True
            ext_defn = grp.Definitions.Create(opts)

        t = Transaction(doc, u"Cr\u00e9er param\u00e8tre {}".format(param_name))
        t.Start()
        try:
            doc.ParameterBindings.Insert(ext_defn, instance_binding, PARAM_GROUP)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(u"\u00c9chec cr\u00e9ation {} :\n{}".format(param_name, str(e)),
                        exitscript=True)
            return False
    return True

# ─── CALCUL ────────────────────────────────────────────────────────────────────

def feet_to_m(feet_value):
    return feet_value * 0.3048

def fmt_topo(z_feet):
    """Formate une cote Z en pieds vers un niveau topo en mètres (ex: +3.450 m)."""
    m = feet_to_m(z_feet)
    sign = u"+" if m >= 0 else u""
    return u"{}{:.3f} m".format(sign, m)

def calculate_etayage(floor, all_floors):
    """
    Retourne (distance_cm, z_sous_face_cur_ft, z_surface_inf_ft) ou
    (None, z_sous_face_cur_ft, None) si aucune dalle en dessous.
    """
    bb_cur = floor.get_BoundingBox(None)
    if bb_cur is None:
        return None, None, None, None

    z_min_cur = bb_cur.Min.Z
    cx_cur    = (bb_cur.Min.X + bb_cur.Max.X) / 2.0
    cy_cur    = (bb_cur.Min.Y + bb_cur.Max.Y) / 2.0

    best_z_max = None
    best_floor = None

    for other in all_floors:
        if other.Id == floor.Id:
            continue
        bb_cand = other.get_BoundingBox(None)
        if bb_cand is None:
            continue
        z_max_cand = bb_cand.Max.Z
        if z_max_cand >= z_min_cur - Z_TOLERANCE_FT:
            continue
        if not centroid_inside_bbox_xy(cx_cur, cy_cur, bb_cand):
            continue
        if best_z_max is None or z_max_cand > best_z_max:
            best_z_max = z_max_cand
            best_floor = other

    if best_z_max is None:
        return None, z_min_cur, None, None
    return feet_to_cm(z_min_cur - best_z_max), z_min_cur, best_z_max, best_floor

# ─── VUE 3D ────────────────────────────────────────────────────────────────────

def create_3d_view(doc, uidoc, floor_sup, floor_inf):
    """Crée une vue 3D isométrique isolant les deux dalles avec une section box ajustée."""

    # Trouver un ViewFamilyType 3D
    vft = next(
        (v for v in FilteredElementCollector(doc)
             .OfClass(ViewFamilyType).ToElements()
         if v.ViewFamily == ViewFamily.ThreeDimensional),
        None
    )
    if vft is None:
        forms.alert(u"Aucun type de vue 3D trouvé dans le projet.")
        return

    bb1 = floor_sup.get_BoundingBox(None)
    bb2 = floor_inf.get_BoundingBox(None)

    # Bounding box englobante avec marge de 1 m (≈ 3.28 ft)
    margin = 3.28084
    sbox = BoundingBoxXYZ()
    sbox.Min = XYZ(
        min(bb1.Min.X, bb2.Min.X) - margin,
        min(bb1.Min.Y, bb2.Min.Y) - margin,
        min(bb1.Min.Z, bb2.Min.Z) - margin
    )
    sbox.Max = XYZ(
        max(bb1.Max.X, bb2.Max.X) + margin,
        max(bb1.Max.Y, bb2.Max.Y) + margin,
        max(bb1.Max.Z, bb2.Max.Z) + margin
    )

    view_name = u"Etayage_{}_{}".format(
        floor_sup.Id.IntegerValue, floor_inf.Id.IntegerValue)

    ids = DotNetList[ElementId]()
    ids.Add(floor_sup.Id)
    ids.Add(floor_inf.Id)

    t = Transaction(doc, u"Cr\u00e9er vue 3D \u00e9tayage")
    t.Start()
    try:
        view3d = View3D.CreateIsometric(doc, vft.Id)
        # Nommage unique : ajouter suffixe si nom déjà pris
        try:
            view3d.Name = view_name
        except Exception:
            view3d.Name = view_name + u"_{}".format(view3d.Id.IntegerValue)
        view3d.SetSectionBox(sbox)
        view3d.IsSectionBoxActive = True
        view3d.IsolateElementsTemporary(ids)
        t.Commit()
    except Exception as e:
        t.RollBack()
        forms.alert(u"Erreur cr\u00e9ation vue :\n{}".format(str(e)))
        return

    # Ouvrir la vue
    uidoc.ActiveView = view3d


# ─── INTERFACE WPF ─────────────────────────────────────────────────────────────

XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Hauteur d&#x27;&#xe9;tayage" Height="540" Width="500"
    WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
    FontFamily="Segoe UI" FontSize="13">
    <Window.Resources>
        <Style x:Key="BtnGreen" TargetType="Button">
            <Setter Property="Background"  Value="#1a6e3c"/>
            <Setter Property="Foreground"  Value="White"/>
            <Setter Property="BorderBrush" Value="#1a6e3c"/>
            <Setter Property="Padding"     Value="0,7"/>
            <Setter Property="Cursor"      Value="Hand"/>
        </Style>
        <Style x:Key="BtnBlue" TargetType="Button">
            <Setter Property="Background"  Value="#1e4fa3"/>
            <Setter Property="Foreground"  Value="White"/>
            <Setter Property="BorderBrush" Value="#1e4fa3"/>
            <Setter Property="Padding"     Value="0,7"/>
            <Setter Property="Cursor"      Value="Hand"/>
        </Style>
        <Style x:Key="BtnGray" TargetType="Button">
            <Setter Property="Padding" Value="0,7"/>
            <Setter Property="Cursor"  Value="Hand"/>
        </Style>
        <Style x:Key="BtnRed" TargetType="Button">
            <Setter Property="Background"  Value="#c0392b"/>
            <Setter Property="Foreground"  Value="White"/>
            <Setter Property="BorderBrush" Value="#c0392b"/>
            <Setter Property="Padding"     Value="0,7"/>
            <Setter Property="Cursor"      Value="Hand"/>
        </Style>
        <Style x:Key="Label" TargetType="TextBlock">
            <Setter Property="Foreground"       Value="#555555"/>
            <Setter Property="VerticalAlignment" Value="Center"/>
        </Style>
    </Window.Resources>

    <StackPanel Margin="28,22,28,22">

        <!-- Titre -->
        <TextBlock Text="Hauteur d&#x27;&#xe9;tayage &#x2014; Sol s&#xe9;lectionn&#xe9;"
                   FontSize="15" FontWeight="Bold" Margin="0,0,0,20"/>

        <!-- Tableau des valeurs -->
        <Border Background="#f5f5f5" CornerRadius="4" Padding="14,10" Margin="0,0,0,18">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="150"/>
                </Grid.ColumnDefinitions>
                <Grid.RowDefinitions>
                    <RowDefinition Height="34"/>
                    <RowDefinition Height="34"/>
                    <RowDefinition Height="34"/>
                    <RowDefinition Height="34"/>
                    <RowDefinition Height="34"/>
                </Grid.RowDefinitions>

                <TextBlock Grid.Row="0" Grid.Column="0" Text="Sous-face dalle s&#xe9;lectionn&#xe9;e"
                           Style="{StaticResource Label}"/>
                <TextBlock Grid.Row="0" Grid.Column="1" Name="LblNiveauSup"
                           VerticalAlignment="Center" Foreground="#333"/>

                <Separator Grid.Row="0" Grid.Column="0" Grid.ColumnSpan="2"
                           VerticalAlignment="Bottom" Margin="-14,0"/>

                <TextBlock Grid.Row="1" Grid.Column="0" Text="Surface dalle d&#xe9;tect&#xe9;e dessous"
                           Style="{StaticResource Label}"/>
                <TextBlock Grid.Row="1" Grid.Column="1" Name="LblNiveauInf"
                           VerticalAlignment="Center" Foreground="#333"/>

                <Separator Grid.Row="1" Grid.Column="0" Grid.ColumnSpan="2"
                           VerticalAlignment="Bottom" Margin="-14,0"/>

                <TextBlock Grid.Row="2" Grid.Column="0" Text="Valeur calcul&#xe9;e"
                           Style="{StaticResource Label}"/>
                <TextBlock Grid.Row="2" Grid.Column="1" Name="LblCalc"
                           FontWeight="Bold" FontSize="14" Foreground="#1a6e3c"
                           VerticalAlignment="Center"/>

                <Separator Grid.Row="2" Grid.Column="0" Grid.ColumnSpan="2"
                           VerticalAlignment="Bottom" Margin="-14,0"/>

                <TextBlock Grid.Row="3" Grid.Column="0"
                           Text="Auto (valeur actuelle)" Style="{StaticResource Label}"/>
                <TextBlock Grid.Row="3" Grid.Column="1" Name="LblAuto"
                           VerticalAlignment="Center" Foreground="#333"/>

                <Separator Grid.Row="3" Grid.Column="0" Grid.ColumnSpan="2"
                           VerticalAlignment="Bottom" Margin="-14,0"/>

                <TextBlock Grid.Row="4" Grid.Column="0"
                           Text="Manuel (valeur actuelle)" Style="{StaticResource Label}"/>
                <TextBlock Grid.Row="4" Grid.Column="1" Name="LblManuel"
                           VerticalAlignment="Center" Foreground="#333"/>
            </Grid>
        </Border>

        <!-- Action : valeur calculée → Auto -->
        <DockPanel Margin="0,0,0,12">
            <Button Name="BtnApplyCalc" DockPanel.Dock="Right"
                    Style="{StaticResource BtnGreen}"
                    Content="Appliquer" Width="110"/>
            <TextBlock VerticalAlignment="Center" Margin="0,0,12,0"
                       Text="Enregistrer la valeur calcul&#xe9;e dans Auto :"/>
        </DockPanel>

        <Separator Margin="0,4,0,14"/>

        <!-- Action : saisie manuelle → Manuel -->
        <TextBlock Text="Saisir une valeur dans Manuel (cm) :"
                   Margin="0,0,0,8" Foreground="#333"/>
        <DockPanel>
            <Button Name="BtnApplyManuel" DockPanel.Dock="Right"
                    Style="{StaticResource BtnBlue}"
                    Content="Enregistrer" Width="110"/>
            <Button Name="BtnPurgeManuel" DockPanel.Dock="Right"
                    Style="{StaticResource BtnRed}"
                    Content="Purger" Width="80" Margin="0,0,8,0"/>
            <TextBox Name="TxtManuel" Margin="0,0,10,0"
                     Padding="8,6" FontSize="13" VerticalContentAlignment="Center"/>
        </DockPanel>

        <!-- Bas : Vue 3D + Fermer -->
        <DockPanel Margin="0,20,0,0">
            <Button Name="BtnFermer" DockPanel.Dock="Right"
                    Style="{StaticResource BtnGray}"
                    Content="Fermer" Width="100"/>
            <Button Name="BtnVue3D" DockPanel.Dock="Right"
                    Style="{StaticResource BtnGray}"
                    Content="Vue 3D" Width="120" Margin="0,0,8,0"
                    Background="#5b4fa3" Foreground="White" BorderBrush="#5b4fa3"/>
        </DockPanel>

        <!-- Footer -->
        <TextBlock Name="LblVersion"
                   Foreground="#999999" FontSize="11"
                   Margin="0,14,0,0" HorizontalAlignment="Left"/>

    </StackPanel>
</Window>
"""

# ─── SCRIPT PRINCIPAL ──────────────────────────────────────────────────────────

doc   = revit.doc
app   = doc.Application
uidoc = revit.uidoc

# 1. Vérifier la sélection
floors_cat_id = ElementId(BuiltInCategory.OST_Floors)
selected_floors = [
    doc.GetElement(eid)
    for eid in uidoc.Selection.GetElementIds()
    if doc.GetElement(eid) is not None
    and doc.GetElement(eid).Category is not None
    and doc.GetElement(eid).Category.Id == floors_cat_id
]

if len(selected_floors) == 0:
    forms.alert(
        u"Aucun sol s\u00e9lectionn\u00e9.\n"
        u"S\u00e9lectionnez un sol dans le mod\u00e8le puis relancez.",
        exitscript=True
    )
if len(selected_floors) > 1:
    forms.alert(
        u"{} sols s\u00e9lectionn\u00e9s.\nS\u00e9lectionnez un seul sol.".format(
            len(selected_floors)),
        exitscript=True
    )

floor = selected_floors[0]

# 2. Vérifier / créer les paramètres partagés
bound_names = get_bound_param_names(doc)
missing = [p for p in PARAMS_NEEDED if p not in bound_names]
if missing:
    msg = u"Les param\u00e8tres suivants sont absents du projet :\n\n"
    for m in missing:
        msg += u"  \u2022  {}\n".format(m)
    msg += (
        u"\nGroupe : Cotes | Cat\u00e9gorie : Sols | Instance\n\n"
        u"Voulez-vous les cr\u00e9er ?"
    )
    if not forms.alert(msg, yes=True, no=True, title=u"Param\u00e8tres manquants"):
        script.exit()
    create_shared_parameters(doc, app, missing)

# 3. Collecter toutes les dalles pour le calcul
all_floors = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_Floors)
    .WhereElementIsNotElementType()
    .ToElements()
)

# 4. Calcul de la hauteur d'étayage
calc_result, z_sous_face, z_surface_inf, floor_below = calculate_etayage(floor, all_floors)
calc_str    = u"{:.1f} cm".format(calc_result) if calc_result is not None else NO_SLAB_BELOW_TEXT

niveau_sup = fmt_topo(z_sous_face) if z_sous_face is not None else u"\u2014"
niveau_inf = fmt_topo(z_surface_inf) if z_surface_inf is not None else u"\u2014"

val_auto   = read_param(floor, PARAM_AUTO)
val_manuel = read_param(floor, PARAM_MANUEL)

# 5. Construire et afficher la fenêtre WPF
window = XamlReader.Parse(XAML)

window.FindName('LblVersion').Text   = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
window.FindName('LblNiveauSup').Text = niveau_sup
window.FindName('LblNiveauInf').Text = niveau_inf
window.FindName('LblCalc').Text      = calc_str
window.FindName('LblAuto').Text      = val_auto
window.FindName('LblManuel').Text    = val_manuel

# Préremplir le champ manuel avec la valeur courante si elle existe
if val_manuel != u"\u2014":
    window.FindName('TxtManuel').Text = val_manuel

# ── Handlers ──

def on_apply_calc(sender, args):
    if calc_result is None:
        forms.alert(u"Aucune dalle inf\u00e9rieure d\u00e9tect\u00e9e \u2014 rien \u00e0 enregistrer.")
        return
    value = u"{:.1f}".format(calc_result)
    if write_param(doc, floor, PARAM_AUTO, value):
        window.Close()

def on_apply_manuel(sender, args):
    raw = window.FindName('TxtManuel').Text.strip().replace(',', '.')
    if not raw:
        forms.alert(u"Saisissez une valeur avant d\u2019enregistrer.")
        return
    try:
        val = float(raw)
    except ValueError:
        forms.alert(u"Valeur invalide. Entrez un nombre (ex\u00a0: 312.5).")
        return
    value = u"{:.1f}".format(val)
    if write_param(doc, floor, PARAM_MANUEL, value):
        window.Close()

def on_purge_manuel(sender, args):
    if write_param(doc, floor, PARAM_MANUEL, u""):
        window.Close()

def on_vue_3d(sender, args):
    if floor_below is None:
        forms.alert(u"Aucune dalle inf\u00e9rieure d\u00e9tect\u00e9e \u2014 impossible de cr\u00e9er la vue.")
        return
    window.Close()
    create_3d_view(doc, uidoc, floor, floor_below)

def on_fermer(sender, args):
    window.Close()

window.FindName('BtnApplyCalc').Click    += on_apply_calc
window.FindName('BtnApplyManuel').Click  += on_apply_manuel
window.FindName('BtnPurgeManuel').Click  += on_purge_manuel
window.FindName('BtnVue3D').Click        += on_vue_3d
window.FindName('BtnFermer').Click       += on_fermer

window.ShowDialog()
