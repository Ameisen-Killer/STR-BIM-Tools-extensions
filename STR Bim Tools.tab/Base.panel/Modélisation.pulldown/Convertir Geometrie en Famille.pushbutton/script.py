# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.1"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Geom vers Famille"
# =============================================================================
import sys, os, io, traceback, clr, tempfile
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
import System.IO
import System.Text
import System.Windows.Markup

from System.Windows import (
    Window, MessageBox, MessageBoxButton, MessageBoxImage,
    HorizontalAlignment, VerticalAlignment,
    WindowStartupLocation, ResizeMode, Thickness
)
from System.Windows.Controls import (
    Grid, StackPanel, TextBlock, Button, Border,
    RowDefinition, ColumnDefinition, Label, TextBox,
    GroupBox, CheckBox, ComboBox, ComboBoxItem,
    ScrollViewer, Separator
)
from System.Windows.Media import SolidColorBrush, Color

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, TransactionStatus,
    BuiltInCategory, BuiltInParameter,
    Options, GeometryInstance, Solid,
    BooleanOperationsType, BooleanOperationsUtils,
    Transform, XYZ,
    SaveAsOptions,
    ElementId,
    IFamilyLoadOptions, FamilySource
)

try:
    from Autodesk.Revit.DB import UnitUtils, UnitTypeId
    USE_FORGE_UNITS = True
except ImportError:
    USE_FORGE_UNITS = False

from pyrevit import revit, script as pyscript

doc   = revit.doc
uidoc = revit.uidoc
app   = doc.Application

# =============================================================================
# GABARITS DE FAMILLE — chemins standards Revit FR / EN
# =============================================================================
GABARIT_NAMES = [
    u"Modèle générique métrique.rft",   # accent FR correct
    u"Modele generique metrique.rft",                        # sans accents
    u"Generic Model.rft",
    u"Generic Model Metric.rft",
    u"Modele generique.rft",
    u"Modèle générique.rft",
]

# Chemin connu sur ce poste — prioritaire
GABARIT_PATH_DIRECT = r"C:\ProgramData\Autodesk\RVT 2024\Family Templates\French"

def find_template():
    """Cherche le gabarit Modele generique dans les dossiers Revit standards."""
    candidates = []

    # 0. Chemin direct connu sur ce poste — prioritaire
    candidates.append(GABARIT_PATH_DIRECT)

    # 1. Chemin declare par l'application Revit elle-meme
    try:
        fam_tpl = app.FamilyTemplatePath
        if fam_tpl:
            candidates.append(fam_tpl)
            # Aussi tester les sous-dossiers French/English
            for sub in ["French", "English"]:
                candidates.append(os.path.join(fam_tpl, sub))
    except Exception:
        pass

    # 2. Dossier d'installation Revit — via le chemin de l'executable
    try:
        import System.Reflection
        revit_exe = System.Reflection.Assembly.GetEntryAssembly().Location
        if revit_exe:
            revit_dir = os.path.dirname(revit_exe)
            for sub in [u"Family Templates", u"Family Templates"]:
                candidates.append(os.path.join(revit_dir, "Family Templates", "French"))
                candidates.append(os.path.join(revit_dir, "Family Templates", "English"))
                candidates.append(os.path.join(revit_dir, "Family Templates"))
    except Exception:
        pass

    # 3. ProgramData standard
    prog = os.environ.get("ProgramData", r"C:\ProgramData")
    for ver in ["2025", "2024", "2023", "2022"]:
        for sub in ["French", "English", ""]:
            p = os.path.join(prog, "Autodesk", "RVT {}".format(ver), "Family Templates")
            candidates.append(os.path.join(p, sub) if sub else p)

    # 4. Program Files direct (certaines installations)
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    for ver in ["2025", "2024", "2023", "2022"]:
        base = os.path.join(pf, "Autodesk", "Revit {}".format(ver), "Family Templates")
        for sub in ["French", "English", ""]:
            candidates.append(os.path.join(base, sub) if sub else base)

    # 5. Recherche glob si tout echoue (lent mais exhaustif)
    try:
        import glob
        for drive in ["C:", "D:"]:
            for nm in ["Modele generique metrique.rft", "Generic Model.rft"]:
                pats = glob.glob(os.path.join(drive, os.sep,
                                 "**", "Family Templates", "**", nm),
                                 recursive=True)
                if pats:
                    return pats[0]
    except Exception:
        pass

    for folder in candidates:
        if not folder or not os.path.isdir(folder):
            continue
        # Comparaison par nom exact (liste GABARIT_NAMES)
        for name in GABARIT_NAMES:
            full = os.path.join(folder, name)
            if os.path.isfile(full):
                return full
        # Comparaison souple : lister le dossier et chercher "generique" ou "generic model"
        try:
            for f in os.listdir(folder):
                fl = f.lower()
                if f.lower().endswith('.rft') and (
                    (u"g" in fl and u"n" in fl and u"rique" in fl and u"trique" in fl
                     and u"(" not in fl)  # exclure variantes (face), (mur)...
                    or fl == u"generic model.rft"
                ):
                    return os.path.join(folder, f)
        except Exception:
            pass

    return None


# =============================================================================
# EXTRACTION DES SOLIDES
# =============================================================================
def _collect_solids_from_geom(geom_iter, result):
    """Parcourt recursivement une geometrie et collecte les Solid non vides."""
    if geom_iter is None:
        return
    for obj in geom_iter:
        if isinstance(obj, Solid):
            if obj.Volume > 1e-9:
                result.append(obj)
        elif isinstance(obj, GeometryInstance):
            # Essayer GetInstanceGeometry ET GetSymbolGeometry
            for geom_fn in [obj.GetInstanceGeometry, obj.GetSymbolGeometry]:
                try:
                    sub_geom = geom_fn()
                    if sub_geom:
                        _collect_solids_from_geom(sub_geom, result)
                except Exception:
                    pass


def extract_solids(elements):
    """
    Extrait tous les Solid non vides des elements selectionnes.
    Tente plusieurs strategies pour maximiser la capture (elements systeme, families).
    """
    from Autodesk.Revit.DB import ViewDetailLevel

    # Vue active pour les options liees a une vue
    active_view = None
    try:
        active_view = uidoc.ActiveView
    except Exception:
        pass

    seen_ids = set()  # eviter les doublons de solides
    solids   = []

    for el in elements:
        el_solids = []

        # Strategie 1 : Options sans vue (DetailLevel.Fine)
        try:
            opt1 = Options()
            opt1.ComputeReferences   = False
            opt1.IncludeNonVisibleObjects = False
            opt1.DetailLevel         = ViewDetailLevel.Fine
            geom = el.get_Geometry(opt1)
            _collect_solids_from_geom(geom, el_solids)
        except Exception:
            pass

        # Strategie 2 : Options avec vue active (debloque certains elements systeme)
        if not el_solids and active_view is not None:
            try:
                opt2 = Options()
                opt2.View                    = active_view
                opt2.ComputeReferences       = False
                opt2.IncludeNonVisibleObjects = True
                geom = el.get_Geometry(opt2)
                _collect_solids_from_geom(geom, el_solids)
            except Exception:
                pass

        # Strategie 3 : IncludeNonVisibleObjects = True sans vue
        if not el_solids:
            try:
                opt3 = Options()
                opt3.ComputeReferences        = False
                opt3.IncludeNonVisibleObjects  = True
                opt3.DetailLevel              = ViewDetailLevel.Fine
                geom = el.get_Geometry(opt3)
                _collect_solids_from_geom(geom, el_solids)
            except Exception:
                pass

        solids.extend(el_solids)

    return solids


def merge_solids(solids):
    """
    Fusionne une liste de Solid en un seul via BooleanUnion.
    Retourne le solid fusionné ou le premier si échec.
    """
    if not solids:
        return None
    result = solids[0]
    for s in solids[1:]:
        try:
            result = BooleanOperationsUtils.ExecuteBooleanOperation(
                result, s, BooleanOperationsType.Union
            )
        except Exception:
            pass  # On ignore les unions echouees (geometries disjointes OK)
    return result


# =============================================================================
# EXPORT SAT DEPUIS DOC COURANT + IMPORT DANS FAMILLE
# =============================================================================

def _get_or_create_3d_view(target_doc):
    """Retourne une vue 3D non-gabarit existante, ou None."""
    from Autodesk.Revit.DB import View3D
    views = FilteredElementCollector(target_doc).OfClass(View3D).ToElements()
    for v in views:
        try:
            if not v.IsTemplate:
                return v
        except Exception:
            pass
    return None


def export_solids_to_sat(solids, sat_path):
    """
    Strategie robuste Revit 2024 :
    1. Creer un DirectShape temporaire dans le DOC COURANT
    2. Exporter en SAT via une vue 3D existante du doc courant
    3. Supprimer le DirectShape apres export
    Retourne le chemin reel du fichier SAT genere, ou None si echec.
    """
    from Autodesk.Revit.DB import DirectShape, GeometryObject, View3D
    try:
        from Autodesk.Revit.DB import SATExportOptions
    except ImportError:
        return False

    # Trouver une vue 3D dans le doc courant
    view3d = _get_or_create_3d_view(doc)
    if view3d is None:
        return False

    ds_id = None
    t = Transaction(doc, "STR - DirectShape temp SAT")
    try:
        t.Start()
        ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
        shape_list = System.Collections.Generic.List[GeometryObject]()
        for s in solids:
            shape_list.Add(s)
        ds.SetShape(shape_list)
        ds_id = ds.Id
        t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return False

    # Export SAT — isoler le DirectShape dans la vue avant export
    # Strategie : HideAllExcept(ds_id) + Export + RestoreHiddenElements
    real_path = [None]
    sat_export_dir = None
    view_state_restored = [False]

    try:
        import uuid
        sat_export_dir = os.path.join(tempfile.gettempdir(), "str_sat_" + str(uuid.uuid4())[:8])
        os.makedirs(sat_export_dir)

        # Isoler le DirectShape dans la vue 3D (Hide all except ds_id)
        t_iso = Transaction(doc, "STR - Isolation vue SAT")
        try:
            t_iso.Start()
            # Cacher tous les elements sauf le DirectShape
            all_visible = FilteredElementCollector(doc, view3d.Id)                .WhereElementIsNotElementType().ToElementIds()
            to_hide = System.Collections.Generic.List[ElementId]()
            for eid in all_visible:
                if eid.IntegerValue != ds_id.IntegerValue:
                    try:
                        el = doc.GetElement(eid)
                        if el and el.CanBeHidden(view3d):
                            to_hide.Add(eid)
                    except Exception:
                        pass
            if to_hide.Count > 0:
                view3d.HideElements(to_hide)
            t_iso.Commit()
        except Exception:
            try: t_iso.RollBack()
            except: pass

        # Export SAT avec seulement le DirectShape visible
        sat_opt  = SATExportOptions()
        sat_name = "str_geom_export"
        view_ids = System.Collections.Generic.List[ElementId]()
        view_ids.Add(view3d.Id)
        doc.Export(sat_export_dir, sat_name, view_ids, sat_opt)

        # Restaurer la visibilite
        t_restore = Transaction(doc, "STR - Restauration vue SAT")
        try:
            t_restore.Start()
            view3d.UnhideElements(to_hide)
            t_restore.Commit()
            view_state_restored[0] = True
        except Exception:
            try: t_restore.RollBack()
            except: pass

        # Trouver le SAT genere
        sat_files = [f for f in os.listdir(sat_export_dir) if f.lower().endswith('.sat')]
        if sat_files:
            sat_files.sort(key=lambda f: os.path.getsize(
                os.path.join(sat_export_dir, f)), reverse=True)
            real_path[0] = os.path.join(sat_export_dir, sat_files[0])

    except Exception:
        real_path[0] = None
        # Tenter restauration d'urgence
        if not view_state_restored[0]:
            try:
                t_urg = Transaction(doc, "STR - Restauration urgence")
                t_urg.Start()
                view3d.UnhideElements(to_hide)
                t_urg.Commit()
            except Exception:
                pass

    # Nettoyage : supprimer le DirectShape temporaire
    t2 = Transaction(doc, "STR - Nettoyage DirectShape temp")
    try:
        t2.Start()
        doc.Delete(ds_id)
        t2.Commit()
    except Exception:
        try:
            t2.RollBack()
        except Exception:
            pass

    return real_path[0]


# =============================================================================
# CREATION DE LA FAMILLE
# =============================================================================
def create_family_from_solids(solids, rfa_path, template_path):
    """
    Cree un document famille Modele Generique, importe les solides via SAT,
    et sauvegarde en .rfa.
    Retourne (True, "") ou (False, message_erreur).
    """
    # 1. Exporter les solides en SAT depuis le doc courant
    tmp_dir      = tempfile.gettempdir()
    sat_hint     = os.path.join(tmp_dir, "str_geom_export.sat")
    # Nettoyer les .sat precedents dans le dossier temp pour eviter confusion
    try:
        for f in os.listdir(tmp_dir):
            if f.startswith("str_geom_export") and f.endswith(".sat"):
                os.remove(os.path.join(tmp_dir, f))
    except Exception:
        pass

    # export_solids_to_sat retourne le chemin reel du SAT genere (ou None)
    real_sat_path = export_solids_to_sat(solids, sat_hint) if solids else None
    sat_ok        = real_sat_path is not None

    # 2. Creer le document famille depuis le gabarit
    try:
        fam_doc = app.NewFamilyDocument(template_path)
    except Exception as ex:
        return False, u"Impossible de creer le doc famille :\n{}".format(ex)

    # 3. Si SAT disponible, l'importer dans la famille puis exploser en geometrie native
    if sat_ok:
        try:
            from Autodesk.Revit.DB import ImportPlacement

            # SAT/ACIS : utiliser la bonne classe d'import
            imp_opt = None
            for cls_name in ["SADImportOptions", "SATImportOptions",
                              "ACADImportOptions", "ACADEImportOptions"]:
                try:
                    mod = __import__("Autodesk.Revit.DB", fromlist=[cls_name])
                    cls = getattr(mod, cls_name)
                    imp_opt = cls()
                    break
                except Exception:
                    continue

            if imp_opt is None:
                raise Exception(u"Aucune classe d'import SAT/ACIS trouvee")

            imp_opt.Placement    = ImportPlacement.Origin
            imp_opt.ThisViewOnly = False

            # Import SAT -> retourne l'Id de l'Import Symbol
            imp_id = [None]
            with Transaction(fam_doc, "STR - Import SAT") as t:
                t.Start()
                imp_id[0] = fam_doc.Import(real_sat_path, imp_opt, fam_doc.ActiveView)
                t.Commit()

            # Exploser l'Import Symbol en geometrie native Revit
            # PartiallyExplode decompose en solides DirectShape natifs
            if imp_id[0] is not None:
                with Transaction(fam_doc, "STR - Explosion Import Symbol") as t:
                    t.Start()
                    try:
                        # Methode 1 : PartiallyExplode (Revit 2024+)
                        imp_inst = fam_doc.GetElement(imp_id[0])
                        if imp_inst and hasattr(imp_inst, "PartiallyExplode"):
                            imp_inst.PartiallyExplode()
                        elif imp_inst and hasattr(imp_inst, "Explode"):
                            imp_inst.Explode()
                        else:
                            # Methode 2 : via ImportInstance.FullyExplode()
                            from Autodesk.Revit.DB import ImportInstance
                            all_imports = FilteredElementCollector(fam_doc)                                .OfClass(ImportInstance).ToElements()
                            for ii in all_imports:
                                try:
                                    ii.FullyExplode()
                                except Exception:
                                    try:
                                        ii.PartiallyExplode()
                                    except Exception:
                                        pass
                        t.Commit()
                    except Exception:
                        t.RollBack()
                        # L'import Symbol reste mais la famille est utilisable

        except Exception as ex:
            sat_ok = False

    # 4. Sauvegarder la RFA
    try:
        save_opt = SaveAsOptions()
        save_opt.OverwriteExistingFile = True
        fam_doc.SaveAs(rfa_path, save_opt)
        fam_doc.Close(False)
    except Exception as ex:
        try:
            fam_doc.Close(False)
        except Exception:
            pass
        return False, u"Echec sauvegarde RFA :\n{}".format(ex)

    # Nettoyage SAT temp (fichier + dossier dedie)
    try:
        if real_sat_path and os.path.isfile(real_sat_path):
            sat_dir_tmp = os.path.dirname(real_sat_path)
            os.remove(real_sat_path)
            # Supprimer le dossier dedie s'il est vide
            try:
                if os.path.isdir(sat_dir_tmp) and not os.listdir(sat_dir_tmp):
                    os.rmdir(sat_dir_tmp)
            except Exception:
                pass
    except Exception:
        pass

    if not sat_ok:
        return False, (
            u"La famille a ete creee mais sans geometrie.\n\n"
            u"Chemin : {}\n\n"
            u"Cause probable : aucune vue 3D disponible dans le projet,\n"
            u"ou export SAT non supporte pour ces elements.\n\n"
            u"Workflow manuel :\n"
            u"1. Fichier > Exporter > ACIS SAT (depuis une vue 3D)\n"
            u"2. Ouvrir la RFA > Inserer > Importer CAO > choisir le .sat"
        ).format(rfa_path)

    return True, u""


# =============================================================================
# XAML INTERFACE
# =============================================================================
XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="560" Height="460" MinWidth="480" MinHeight="400"
    WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- HEADER info selection -->
    <Border Grid.Row="0" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="10,8">
      <StackPanel>
        <TextBlock x:Name="lbl_selection" FontSize="13" FontWeight="SemiBold"
                   Foreground="#2F6496"/>
        <TextBlock x:Name="lbl_solids" FontSize="11" Foreground="#555555" Margin="0,2,0,0"/>
      </StackPanel>
    </Border>

    <!-- CORPS -->
    <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto">
      <StackPanel Margin="12,10,12,6">

        <!-- Gabarit -->
        <GroupBox Margin="0,0,0,10" Padding="8,6">
          <GroupBox.Header>
            <TextBlock x:Name="lbl_grp_gabarit" FontWeight="SemiBold" FontSize="12"/>
          </GroupBox.Header>
          <StackPanel>
            <TextBlock x:Name="lbl_tpl_auto" FontSize="11" Foreground="#27AE60"
                       Margin="0,2,0,6" TextWrapping="Wrap"/>
            <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
              <TextBlock x:Name="lbl_tpl_custom" FontSize="11" VerticalAlignment="Center"
                         Margin="0,0,6,0"/>
              <TextBox x:Name="txt_template" Width="280" Height="24" FontSize="11"
                       VerticalContentAlignment="Center" Padding="4,0"
                       BorderBrush="#C0D0E0"/>
              <Button x:Name="btn_browse_tpl" Width="30" Height="24" Margin="4,0,0,0"
                      Background="#3498DB" Foreground="White" FontWeight="Bold"
                      BorderThickness="0" FontSize="14" Content="..."/>
            </StackPanel>
          </StackPanel>
        </GroupBox>

        <!-- Nom et destination -->
        <GroupBox Margin="0,0,0,10" Padding="8,6">
          <GroupBox.Header>
            <TextBlock x:Name="lbl_grp_dest" FontWeight="SemiBold" FontSize="12"/>
          </GroupBox.Header>
          <Grid>
            <Grid.RowDefinitions>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
              <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="100"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="36"/>
            </Grid.ColumnDefinitions>

            <TextBlock x:Name="lbl_nom" Grid.Row="0" Grid.Column="0"
                       FontSize="11" VerticalAlignment="Center" Margin="0,4,6,4"/>
            <TextBox x:Name="txt_nom" Grid.Row="0" Grid.Column="1" Grid.ColumnSpan="2"
                     Height="24" FontSize="11" VerticalContentAlignment="Center"
                     Padding="4,0" BorderBrush="#C0D0E0" Margin="0,4,0,4"/>

            <TextBlock x:Name="lbl_dossier" Grid.Row="1" Grid.Column="0"
                       FontSize="11" VerticalAlignment="Center" Margin="0,4,6,4"/>
            <TextBox x:Name="txt_dossier" Grid.Row="1" Grid.Column="1"
                     Height="24" FontSize="11" VerticalContentAlignment="Center"
                     Padding="4,0" BorderBrush="#C0D0E0" Margin="0,4,4,4"/>
            <Button x:Name="btn_browse_dest" Grid.Row="1" Grid.Column="2"
                    Height="24" Width="30" Background="#3498DB" Foreground="White"
                    FontWeight="Bold" BorderThickness="0" FontSize="14"
                    Content="..." Margin="0,4,0,4"/>

            <TextBlock x:Name="lbl_path_preview" Grid.Row="2" Grid.Column="0"
                       Grid.ColumnSpan="3" FontSize="10" Foreground="#888888"
                       TextWrapping="Wrap" Margin="0,2,0,4"/>
          </Grid>
        </GroupBox>

        <!-- Options -->
        <GroupBox Margin="0,0,0,10" Padding="8,6">
          <GroupBox.Header>
            <TextBlock x:Name="lbl_grp_options" FontWeight="SemiBold" FontSize="12"/>
          </GroupBox.Header>
          <StackPanel>
            <CheckBox x:Name="chk_open" IsChecked="True" Margin="0,4,0,4" FontSize="11"/>
            <CheckBox x:Name="chk_reload" IsChecked="False" Margin="0,4,0,4" FontSize="11"/>
          </StackPanel>
        </GroupBox>

      </StackPanel>
    </ScrollViewer>

    <!-- FOOTER -->
    <Border Grid.Row="2" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,5">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_create" Width="130" Height="28" Margin="4,0,0,0"
                  Background="#2ECC71" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0" FontSize="12"/>
          <Button x:Name="btn_cancel" Width="90" Height="28" Margin="6,0,0,0"
                  Background="#E74C3C" Foreground="White" FontWeight="SemiBold"
                  BorderThickness="0" FontSize="12"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""


# =============================================================================
# MAIN
# =============================================================================
def main():
    # --- 1. Recuperer la selection courante
    sel_ids  = uidoc.Selection.GetElementIds()
    elements = [doc.GetElement(eid) for eid in sel_ids if doc.GetElement(eid) is not None]

    if not elements:
        MessageBox.Show(
            u"Aucun element selectionne.\n\nSelectionnez des elements dans le modele avant de lancer l'outil.",
            u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
            MessageBoxButton.OK, MessageBoxImage.Warning
        )
        return

    # --- 2. Analyse des solides
    solids = extract_solids(elements)
    n_el   = len(elements)
    n_sol  = len(solids)

    # --- 3. Trouver gabarit automatiquement
    tpl_auto = find_template()

    # --- 4. Dossier destination par defaut : Bureau ou dossier projet
    try:
        desktop = os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "Desktop")
    except Exception:
        desktop = "C:\\"

    # Chemin projet pour suggestion de nom
    proj_name = u"Famille_STR"
    try:
        if doc.PathName:
            proj_name = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        pass

    default_name = u"{}_GeomFamille".format(proj_name)

    # --- 5. Construire la fenetre
    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
    window = System.Windows.Markup.XamlReader.Load(stream)
    window.Title = TOOL_NAME

    # Assigner textes (accents hors XAML)
    window.FindName("lbl_footer").Text    = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    window.FindName("btn_create").Content = u"Creer la famille"
    window.FindName("btn_cancel").Content = u"Annuler"

    window.FindName("lbl_selection").Text = u"{} element(s) selectionne(s)".format(n_el)
    window.FindName("lbl_solids").Text    = (
        u"{} solide(s) extrait(s)".format(n_sol) if n_sol > 0
        else u"Aucun solide extrait — verifier la selection"
    )

    window.FindName("lbl_grp_gabarit").Text  = u"Gabarit de famille"
    window.FindName("lbl_grp_dest").Text     = u"Destination"
    window.FindName("lbl_grp_options").Text  = u"Options"
    window.FindName("lbl_nom").Text          = u"Nom :"
    window.FindName("lbl_dossier").Text      = u"Dossier :"
    window.FindName("lbl_tpl_custom").Text   = u"Autre gabarit :"

    chk_open   = window.FindName("chk_open")
    chk_reload = window.FindName("chk_reload")
    chk_open.Content   = u"Ouvrir la famille apres creation"
    chk_reload.Content = u"Recharger dans le projet courant"

    txt_nom     = window.FindName("txt_nom")
    txt_dossier = window.FindName("txt_dossier")
    txt_tpl     = window.FindName("txt_template")
    lbl_preview = window.FindName("lbl_path_preview")
    lbl_tpl_auto = window.FindName("lbl_tpl_auto")

    txt_nom.Text     = default_name
    txt_dossier.Text = desktop

    if tpl_auto:
        lbl_tpl_auto.Text = u"Gabarit detecte : {}".format(os.path.basename(tpl_auto))
        txt_tpl.Text      = tpl_auto
        txt_tpl.IsEnabled = False
    else:
        lbl_tpl_auto.Text             = u"Gabarit non detecte — specifier manuellement"
        lbl_tpl_auto.Foreground       = SolidColorBrush(Color.FromRgb(192, 57, 43))
        txt_tpl.IsEnabled             = True

    def update_preview(s=None, e=None):
        nom     = txt_nom.Text.strip()
        dossier = txt_dossier.Text.strip()
        if nom and dossier:
            lbl_preview.Text = os.path.join(dossier, nom + ".rfa")
        else:
            lbl_preview.Text = u""

    txt_nom.TextChanged     += update_preview
    txt_dossier.TextChanged += update_preview
    update_preview()

    # Browse gabarit
    def on_browse_tpl(s, e):
        from System.Windows.Forms import OpenFileDialog, DialogResult
        dlg = OpenFileDialog()
        dlg.Title  = u"Choisir un gabarit de famille"
        dlg.Filter = u"Gabarit Revit (*.rft)|*.rft|Tous (*.*)|*.*"
        if dlg.ShowDialog() == DialogResult.OK:
            txt_tpl.Text = dlg.FileName

    # Browse dossier destination
    def on_browse_dest(s, e):
        from System.Windows.Forms import FolderBrowserDialog, DialogResult
        dlg = FolderBrowserDialog()
        dlg.Description = u"Choisir le dossier de destination"
        try:
            dlg.SelectedPath = txt_dossier.Text
        except Exception:
            pass
        if dlg.ShowDialog() == DialogResult.OK:
            txt_dossier.Text = dlg.SelectedPath
            update_preview()

    window.FindName("btn_browse_tpl").Click  += on_browse_tpl
    window.FindName("btn_browse_dest").Click += on_browse_dest

    # --- 6. Boutons action
    state = {"ok": False}

    def on_create(s, e):
        nom     = txt_nom.Text.strip()
        dossier = txt_dossier.Text.strip()
        tpl     = txt_tpl.Text.strip()

        # Validations
        if not nom:
            MessageBox.Show(u"Veuillez saisir un nom de famille.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        if not dossier or not os.path.isdir(dossier):
            MessageBox.Show(u"Le dossier de destination est invalide.",
                            TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        if not tpl or not os.path.isfile(tpl):
            MessageBox.Show(
                u"Gabarit de famille introuvable.\n\nSpecifiez un fichier .rft valide.",
                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning
            )
            return
        if n_sol == 0:
            rep = MessageBox.Show(
                u"Aucun solide n'a ete extrait.\n\nContinuer quand meme (famille vide) ?",
                TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Question
            )
            if str(rep) == "No":
                return

        rfa_path = os.path.join(dossier, nom + ".rfa")

        # Confirmation si fichier existe
        if os.path.isfile(rfa_path):
            rep = MessageBox.Show(
                u"Le fichier existe deja :\n{}\n\nEcraser ?".format(rfa_path),
                TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Question
            )
            if str(rep) == "No":
                return

        state["ok"]         = True
        state["rfa_path"]   = rfa_path
        state["tpl"]        = tpl
        state["open_after"] = chk_open.IsChecked
        state["reload"]     = chk_reload.IsChecked
        window.Close()

    def on_cancel(s, e):
        window.Close()

    window.FindName("btn_create").Click += on_create
    window.FindName("btn_cancel").Click += on_cancel

    window.ShowDialog()

    if not state.get("ok"):
        return

    # --- 7. Creer la famille
    rfa_path = state["rfa_path"]
    tpl_path = state["tpl"]

    # Fusionner les solides
    merged = merge_solids(solids) if solids else None
    solids_to_export = [merged] if merged else []

    ok, err = create_family_from_solids(solids_to_export, rfa_path, tpl_path)

    if not ok:
        MessageBox.Show(
            u"Attention :\n\n{}".format(err),
            u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
            MessageBoxButton.OK, MessageBoxImage.Warning
        )
        # On essaie quand meme d'ouvrir si la famille vide a ete creee
        if os.path.isfile(rfa_path) and state.get("open_after"):
            try:
                from Autodesk.Revit.DB import OpenOptions
                app.OpenDocumentFile(rfa_path)
            except Exception:
                pass
        return

    # --- 8. Post-actions
    msg_parts = [u"Famille creee avec succes :\n{}".format(rfa_path)]

    if state.get("open_after"):
        try:
            app.OpenDocumentFile(rfa_path)
            msg_parts.append(u"\nLa famille a ete ouverte dans Revit.")
        except Exception as ex:
            msg_parts.append(u"\nImpossible d'ouvrir automatiquement : {}".format(ex))

    if state.get("reload"):
        try:
            # IronPython passe les parametres ref de l'interface sous forme de
            # StrongBox : il faut renseigner .Value (reaffecter le nom ne fait rien).
            class LoadOpt(IFamilyLoadOptions):
                def OnFamilyFound(self, fam_in_doc, overwrite_param_values):
                    overwrite_param_values.Value = True
                    return True
                def OnSharedFamilyFound(self, sf, fam_exists, src, overwrite_param_values):
                    src.Value = FamilySource.Family
                    overwrite_param_values.Value = True
                    return True

            with Transaction(doc, u"STR - Recharger famille") as t:
                t.Start()
                fam_loaded = doc.LoadFamily(rfa_path, LoadOpt())
                t.Commit()
            msg_parts.append(u"\nFamille rechargee dans le projet.")
        except Exception as ex:
            msg_parts.append(u"\nEchec rechargement : {}".format(ex))

    MessageBox.Show(
        u"\n".join(msg_parts),
        u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
        MessageBoxButton.OK, MessageBoxImage.Information
    )


# =============================================================================
try:
    main()
except Exception as ex:
    MessageBox.Show(
        u"Erreur inattendue :\n\n{}\n\n{}".format(ex, traceback.format_exc()),
        u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION),
        MessageBoxButton.OK, MessageBoxImage.Error
    )