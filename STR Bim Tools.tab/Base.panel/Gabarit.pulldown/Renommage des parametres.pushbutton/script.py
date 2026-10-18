# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "3.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Renommage Parametres Partages"
# =============================================================================
__title__ = "Renommage\nParametres"
__doc__ = "Renomme les parametres partages du projet (modifie le fichier .txt puis recree la liaison)."
__version__ = "3.0"

import os, shutil, unicodedata, clr
from datetime import datetime

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

from System.Windows.Markup import XamlReader
from System.Windows.Controls import DataGridEditingUnit
from System.Collections.ObjectModel import ObservableCollection

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import (
    Transaction, SubTransaction,
    FilteredElementCollector, SharedParameterElement,
    LabelUtils, BuiltInParameterGroup
)

doc    = revit.doc
app    = doc.Application
output = script.get_output()


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation
# ─────────────────────────────────────────────────────────────────────────────
def normalize(text):
    text = text.upper()
    nfkd = unicodedata.normalize('NFKD', text)
    text = u''.join(c for c in nfkd if not unicodedata.combining(c))
    for ch in u'(),!\'"':
        text = text.replace(ch, u'')
    text = text.replace(u'\xb0', u'')
    text = text.replace(u' ', u'_')
    while u'__' in text:
        text = text.replace(u'__', u'_')
    return text.strip(u'_')


# ─────────────────────────────────────────────────────────────────────────────
# Fichier de parametres partages (.txt)
# ─────────────────────────────────────────────────────────────────────────────
def _read_bytes(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('latin-1', errors='replace'), 'latin-1'


def update_spf(filepath, guid_to_newname):
    """Reecrit le .txt avec les nouveaux noms (par GUID). Retourne chemin de la sauvegarde."""
    backup = filepath + u'.bak.' + datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(filepath, backup)

    text, orig_enc = _read_bytes(filepath)
    lines = []
    for line in text.splitlines(True):
        stripped = line.rstrip(u'\r\n')
        if stripped.startswith(u'PARAM\t'):
            parts = stripped.split(u'\t')
            if len(parts) >= 3:
                guid = parts[1].strip(u'{}').lower()
                if guid in guid_to_newname:
                    parts[2] = guid_to_newname[guid]
                    lines.append(u'\t'.join(parts) + u'\n')
                    continue
        lines.append(line)

    enc_out = 'utf-8' if orig_enc in ('utf-8-sig', 'utf-8') else 'latin-1'
    with open(filepath, 'wb') as f:
        f.write(u''.join(lines).encode(enc_out, errors='replace'))
    return backup


def reload_spf():
    """Force Revit a relire le fichier de parametres partages."""
    path = app.SharedParametersFilename
    app.SharedParametersFilename = u""
    app.SharedParametersFilename = path
    return app.OpenSharedParameterFile()


def guid_to_ext_defn_map(def_file):
    """Retourne {guid_clean: ExternalDefinition} depuis le fichier ouvert."""
    mapping = {}
    if def_file is None:
        return mapping
    for grp in def_file.Groups:
        for ext in grp.Definitions:
            try:
                mapping[ext.GUID.ToString().strip(u'{}').lower()] = ext
            except Exception:
                pass
    return mapping


# ─────────────────────────────────────────────────────────────────────────────
# Helpers API Revit
# ─────────────────────────────────────────────────────────────────────────────
def get_group_label(definition):
    try:
        return LabelUtils.GetLabelFor(definition.ParameterGroup)
    except Exception:
        pass
    try:
        return LabelUtils.GetLabelFor(definition.GetGroupTypeId())
    except Exception:
        return u""


def get_type_label(definition):
    try:
        return LabelUtils.GetLabelFor(definition.GetDataType())
    except Exception:
        pass
    try:
        return str(definition.ParameterType)
    except Exception:
        return u""


def get_param_group(definition):
    try:
        return definition.ParameterGroup
    except Exception:
        return BuiltInParameterGroup.PG_DATA


# ─────────────────────────────────────────────────────────────────────────────
# Modele de ligne pour le DataGrid
# ─────────────────────────────────────────────────────────────────────────────
class ParamRow(object):
    def __init__(self, elem_id, guid, name, group, datatype, param_group):
        self.ElemId     = elem_id
        self.Guid       = guid          # GUID brut du SharedParameterElement
        self.OldName    = name
        self.NewName    = name
        self.Groupe     = group
        self.TypeDonnee = datatype
        self.ParamGroup = param_group   # BuiltInParameterGroup pour le re-Insert


# ─────────────────────────────────────────────────────────────────────────────
# Interface WPF
# ─────────────────────────────────────────────────────────────────────────────
XAML = u"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Renommage des parametres partages"
    Width="960" Height="620"
    MinWidth="700" MinHeight="400"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E1E">

  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Titre + filtre + boutons -->
    <StackPanel Grid.Row="0" Margin="0,0,0,10">
      <TextBlock Text="Renommage des parametres partages du projet"
                 FontSize="16" FontWeight="Bold" Foreground="#DDDDDD" Margin="0,0,0,8"/>
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Filtrer :" Foreground="#AAAAAA" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="FilterBox" Width="220" Padding="5,3"
                 Background="#2A2A2A" Foreground="#CCCCCC" BorderBrush="#555555"/>
        <Button x:Name="BtnNormalize" Content="Normaliser" Margin="14,0,4,0" Padding="10,3"
                Background="#2D4A2D" Foreground="#AADDAA" BorderBrush="#4A7A4A"
                ToolTip="MAJUSCULES + sans accents + espaces en _ (selection ou tout si rien selectionne)"/>
        <Button x:Name="BtnReset" Content="Reinitialiser" Margin="4,0,0,0" Padding="10,3"
                Background="#3A3A3A" Foreground="#CCCCCC" BorderBrush="#555555"
                ToolTip="Restaure le nom d'origine"/>
      </StackPanel>
    </StackPanel>

    <!-- DataGrid -->
    <DataGrid x:Name="ParamGrid" Grid.Row="1"
              AutoGenerateColumns="False"
              CanUserAddRows="False" CanUserDeleteRows="False"
              CanUserResizeRows="False" CanUserSortColumns="True"
              SelectionMode="Extended" SelectionUnit="FullRow"
              Background="#252525" RowBackground="#2A2A2A"
              AlternatingRowBackground="#2F2F2F"
              Foreground="#CCCCCC" GridLinesVisibility="Horizontal"
              HorizontalGridLinesBrush="#3A3A3A"
              BorderBrush="#444444" BorderThickness="1"
              HeadersVisibility="Column" RowHeight="26">

      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#333333"/>
          <Setter Property="Foreground" Value="#CCCCCC"/>
          <Setter Property="Padding" Value="8,4"/>
          <Setter Property="BorderBrush" Value="#555555"/>
          <Setter Property="BorderThickness" Value="0,0,1,1"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>

      <DataGrid.CellStyle>
        <Style TargetType="DataGridCell">
          <Setter Property="BorderThickness" Value="0"/>
          <Setter Property="Padding" Value="6,2"/>
          <Style.Triggers>
            <Trigger Property="IsSelected" Value="True">
              <Setter Property="Background" Value="#1A3A5C"/>
            </Trigger>
          </Style.Triggers>
        </Style>
      </DataGrid.CellStyle>

      <DataGrid.Columns>
        <DataGridTextColumn Header="Groupe"      Binding="{Binding Groupe}"    IsReadOnly="True"  Width="160" MinWidth="80"/>
        <DataGridTextColumn Header="Nom actuel"  Binding="{Binding OldName}"   IsReadOnly="True"  Width="220" MinWidth="100"/>
        <DataGridTextColumn Header="Nouveau nom" Binding="{Binding NewName, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                            IsReadOnly="False" Width="220" MinWidth="100">
          <DataGridTextColumn.ElementStyle>
            <Style TargetType="TextBlock">
              <Setter Property="Foreground" Value="#7ECFF0"/>
            </Style>
          </DataGridTextColumn.ElementStyle>
          <DataGridTextColumn.EditingElementStyle>
            <Style TargetType="TextBox">
              <Setter Property="Background" Value="#1A3A5C"/>
              <Setter Property="Foreground" Value="#AADDFF"/>
              <Setter Property="BorderThickness" Value="0"/>
            </Style>
          </DataGridTextColumn.EditingElementStyle>
        </DataGridTextColumn>
        <DataGridTextColumn Header="Type"        Binding="{Binding TypeDonnee}" IsReadOnly="True" Width="120" MinWidth="60"/>
        <DataGridTextColumn Header="GUID"        Binding="{Binding Guid}"       IsReadOnly="True" Width="*"   MinWidth="80">
          <DataGridTextColumn.ElementStyle>
            <Style TargetType="TextBlock">
              <Setter Property="Foreground" Value="#555555"/>
              <Setter Property="FontSize" Value="10"/>
            </Style>
          </DataGridTextColumn.ElementStyle>
        </DataGridTextColumn>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Compteur -->
    <TextBlock x:Name="LblCount" Grid.Row="2" Foreground="#666666"
               FontSize="11" Margin="0,4,0,0"/>

    <!-- Boutons footer -->
    <Grid Grid.Row="3" Margin="0,8,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <Button x:Name="BtnCancel" Grid.Column="1" Content="Annuler"
              Width="110" Margin="0,0,8,0" Padding="8,5"
              Background="#3A3A3A" Foreground="#CCCCCC" BorderBrush="#555555"/>
      <Button x:Name="BtnApply" Grid.Column="2" Content="Appliquer"
              Width="110" Padding="8,5"
              Background="#1E5A99" Foreground="#FFFFFF" BorderBrush="#1A4A7A"
              FontWeight="SemiBold"/>
    </Grid>
  </Grid>
</Window>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Collecte des SharedParameterElement du projet
# ─────────────────────────────────────────────────────────────────────────────
raw_elems = list(
    FilteredElementCollector(doc).OfClass(SharedParameterElement).ToElements()
)

if not raw_elems:
    forms.alert(
        u"Aucun parametre partage trouve dans ce projet.\n\n"
        u"Les parametres partagees apparaissent ici une fois lies via "
        u"Gerer > Parametres du projet.",
        title=u"Aucun parametre", warn_icon=True
    )
    script.exit()

all_rows = []
for sp in raw_elems:
    try:
        defn = sp.GetDefinition()
        all_rows.append(ParamRow(
            elem_id    = sp.Id,
            guid       = sp.GuidValue.ToString().strip(u'{}').lower(),
            name       = sp.Name,
            group      = get_group_label(defn),
            datatype   = get_type_label(defn),
            param_group= get_param_group(defn),
        ))
    except Exception:
        pass

all_rows.sort(key=lambda r: (r.Groupe, r.OldName))


# ─────────────────────────────────────────────────────────────────────────────
# Fenetre WPF
# ─────────────────────────────────────────────────────────────────────────────
window        = XamlReader.Parse(XAML)
window.Title  = TOOL_NAME
param_grid    = window.FindName('ParamGrid')
filter_box    = window.FindName('FilterBox')
btn_normalize = window.FindName('BtnNormalize')
btn_reset     = window.FindName('BtnReset')
btn_apply     = window.FindName('BtnApply')
btn_cancel    = window.FindName('BtnCancel')
lbl_count     = window.FindName('LblCount')

master_col = ObservableCollection[ParamRow](all_rows)
param_grid.ItemsSource = master_col


def refresh_count():
    src   = param_grid.ItemsSource
    total = len(list(src)) if src else 0
    modif = sum(1 for r in all_rows if r.NewName != r.OldName)
    lbl_count.Text = u'{} parametre(s) affiches  |  {} modification(s) en attente'.format(total, modif)

refresh_count()


def get_target_rows():
    sel = list(param_grid.SelectedItems)
    if sel:
        return sel
    src = param_grid.ItemsSource
    return list(src) if src else []


def on_filter_changed(sender, e):
    text = filter_box.Text.strip().lower()
    col  = ObservableCollection[ParamRow]()
    for r in all_rows:
        if not text or text in r.OldName.lower() or text in r.Groupe.lower():
            col.Add(r)
    param_grid.ItemsSource = col
    refresh_count()

filter_box.TextChanged += on_filter_changed


def on_normalize(sender, e):
    for r in get_target_rows():
        r.NewName = normalize(r.OldName)
    param_grid.Items.Refresh()
    refresh_count()

btn_normalize.Click += on_normalize


def on_reset(sender, e):
    for r in get_target_rows():
        r.NewName = r.OldName
    param_grid.Items.Refresh()
    refresh_count()

btn_reset.Click += on_reset


result = {'ok': False}

def on_apply(sender, e):
    try:
        param_grid.CommitEdit(DataGridEditingUnit.Row, True)
    except Exception:
        pass
    result['ok'] = True
    window.Close()

def on_cancel(sender, e):
    window.Close()

btn_apply.Click += on_apply
btn_cancel.Click += on_cancel

window.ShowDialog()

if not result['ok']:
    script.exit()


# ─────────────────────────────────────────────────────────────────────────────
# Collecte des modifications
# ─────────────────────────────────────────────────────────────────────────────
changes = [r for r in all_rows if (r.NewName or u'').strip() and r.NewName.strip() != r.OldName]

if not changes:
    forms.alert(u"Aucune modification detectee.", title=u"Aucun changement")
    script.exit()


# ─────────────────────────────────────────────────────────────────────────────
# Verification du fichier de parametres partages
# ─────────────────────────────────────────────────────────────────────────────
spf_path = app.SharedParametersFilename
if not spf_path or not os.path.isfile(spf_path):
    forms.alert(
        u"Aucun fichier de parametres partages n'est configure.\n\n"
        u"La methode de renommage requiert l'acces au fichier .txt pour mettre a jour "
        u"la definition puis recreer la liaison.\n\n"
        u"Allez dans Gerer > Parametres partages pour configurer le fichier.",
        title=u"Fichier .txt introuvable", warn_icon=True
    )
    script.exit()


# ─────────────────────────────────────────────────────────────────────────────
# Capture des liaisons existantes AVANT toute modification
# (nom -> {defn, binding, param_group})
# ─────────────────────────────────────────────────────────────────────────────
binding_by_name = {}
it = doc.ParameterBindings.ForwardIterator()
while it.MoveNext():
    defn    = it.Key
    binding = it.Current
    try:
        binding_by_name[defn.Name] = {
            'defn':    defn,
            'binding': binding,
            'pg':      get_param_group(defn),
        }
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 1. Mise a jour du fichier .txt
# ─────────────────────────────────────────────────────────────────────────────
guid_to_new = {r.Guid: r.NewName.strip() for r in changes}
backup_path = None
try:
    backup_path = update_spf(spf_path, guid_to_new)
except Exception as exc:
    forms.alert(
        u"Impossible de modifier le fichier .txt :\n{}\n\n"
        u"Verifiez que le fichier n'est pas en lecture seule.".format(str(exc)),
        title=u"Erreur fichier", warn_icon=True
    )
    script.exit()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Rechargement du fichier dans Revit + mapping GUID -> ExternalDefinition
# ─────────────────────────────────────────────────────────────────────────────
try:
    def_file  = reload_spf()
    ext_defns = guid_to_ext_defn_map(def_file)
except Exception as exc:
    ext_defns = {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Suppression / recreation des liaisons dans une transaction
# ─────────────────────────────────────────────────────────────────────────────
renamed = []
errors  = []

try:
    with Transaction(doc, u"Renommage parametres partages v{}".format(__version__)) as t:
        t.Start()

        for row in changes:
            new_name   = row.NewName.strip()
            old_name   = row.OldName
            guid_clean = row.Guid

            # Verifier que la liaison est connue
            if old_name not in binding_by_name:
                errors.append(u"{} : liaison introuvable dans le projet".format(old_name))
                continue

            # Verifier que la nouvelle definition est dans le fichier .txt
            if guid_clean not in ext_defns:
                errors.append(
                    u"{} : GUID {} absent du fichier .txt "
                    u"(le parametre a peut-etre ete ajoute depuis un autre fichier)".format(
                        old_name, guid_clean)
                )
                continue

            info     = binding_by_name[old_name]
            new_defn = ext_defns[guid_clean]

            sub = SubTransaction(doc)
            sub.Start()
            try:
                doc.ParameterBindings.Remove(info['defn'])
                ok = doc.ParameterBindings.Insert(new_defn, info['binding'], info['pg'])
                if ok:
                    sub.Commit()
                    renamed.append((old_name, new_name))
                else:
                    sub.RollBack()
                    errors.append(u"{} : echec de la reinsertion (Insert retourne False)".format(old_name))
            except Exception as sub_exc:
                sub.RollBack()
                errors.append(u"{} : {}".format(old_name, str(sub_exc)))

        t.Commit()

except Exception as t_exc:
    errors.append(u"Transaction echouee : {}".format(str(t_exc)))


# ─────────────────────────────────────────────────────────────────────────────
# Rapport
# ─────────────────────────────────────────────────────────────────────────────
output.print_md(u"# Renommage des parametres partages v{}".format(__version__))
if backup_path:
    output.print_md(u"**Sauvegarde .txt :** `{}`".format(backup_path))

output.print_md(u"\n## Renommes ({})".format(len(renamed)))
for old, new in renamed:
    output.print_md(u"- `{}` --> `{}`".format(old, new))

if errors:
    output.print_md(u"\n## Erreurs ({})".format(len(errors)))
    for err in errors:
        output.print_md(u"- {}".format(err))

forms.alert(
    u"{} parametre(s) renomme(s).\n{} erreur(s).".format(len(renamed), len(errors)),
    title=u"Renommage termine v{}".format(__version__)
)
