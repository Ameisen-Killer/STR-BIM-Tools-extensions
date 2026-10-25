# -*- coding: utf-8 -*-
__title__   = "Rapport Ossature"
__doc__ = "Quantifie les ossatures et les poteaux."
__author__  = "Tony VARIN"
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Quantification Ossatures & Poteaux"
# =============================================================================

# --- Imports standard IronPython (TOUS en tete) ---
import sys
import os
import io
import traceback
import re

# --- Imports .NET / WPF ---
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

import System
import System.IO
import System.Text
import System.Collections.Generic

from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                            HorizontalAlignment, VerticalAlignment,
                            Visibility)
from System.Windows.Controls import (
    Grid, StackPanel, DataGrid, TextBlock, Button, ScrollViewer,
    Label, Border, DataGridTextColumn, DataGridCheckBoxColumn,
    RowDefinition, ColumnDefinition,
    ComboBox, ComboBoxItem, CheckBox, ListBox, ListBoxItem,
    DataGridSelectionMode,
)
from System.Windows.Controls.Primitives import (
    Popup as WpfPopup, PlacementMode,
)
from System.Windows.Data             import Binding
from System.Windows.Markup           import XamlReader
from System.Windows.Media            import SolidColorBrush, Color
from System.Collections.ObjectModel  import ObservableCollection
from System.Windows.Forms            import SaveFileDialog, DialogResult

# --- Imports Revit ---
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Transaction,
    TransactionStatus,
    BuiltInCategory,
    BuiltInParameter,
    FamilyInstance,
    BoundingBoxXYZ,
    XYZ,
    View3D,
    ViewFamilyType,
    ViewFamily,
    ElementId,
)

try:
    from Autodesk.Revit.DB import UnitUtils, UnitTypeId
    USE_FORGE_UNITS = True
except ImportError:
    USE_FORGE_UNITS = False

# --- pyRevit ---
from pyrevit import revit, DB, script as pyscript, forms
doc   = revit.doc
uidoc = revit.uidoc

# =============================================================================
# CONSTANTES METIER
# =============================================================================

# Ordre de priorite : Flocage AVANT Acier (sinon "Flocage_HEA120" matche HEA -> Acier)
# La detection cherche d'abord dans le nom de FAMILLE, puis dans le nom de TYPE.
# Chaque entree : (materiau, [mots-cles])
MATERIAU_PRIORITY = [
    (u"Flocage", [u"FLOCAGE", u"FLOC"]),
    (u"Acier",   [u"ACIER", u"HEA", u"HEB", u"HEM", u"HEP", u"IPE", u"IPN",
                  u"UPN", u"UAP", u"UPE", u"RHS", u"SHS", u"CHS",
                  u"CORNIERE", u"TUBE", u"PROFILE", u"LAMINEE"]),
    (u"Beton",   [u"BETON", u"BA", u"BP", u"PREFAB", u"BETON_ARME"]),
    (u"Bois",    [u"BOIS", u"GL", u"KVH", u"CLT"]),
]
# Conserve aussi le dict pour la ComboBox materiaux (compatibilite)
MATERIAU_KEYWORDS = {mat: kws for mat, kws in MATERIAU_PRIORITY}

PARAM_BATIMENT = u"#STR_BATIMENT"
CATEG_FRAMING  = u"Ossatures"
CATEG_COLUMNS  = u"Poteaux"
FEET3_TO_M3    = 0.3048 ** 3

# =============================================================================
# LOGIQUE METIER
# =============================================================================

def _detect_materiau(fam_name, type_name=u""):
    """
    Extrait le materiau depuis le nom de famille.
    Convention projet : STR_POU_[MATERIAU]_[PROFIL] ou STR_POT_[MATERIAU]_[PROFIL]
    → le 3eme segment (index 2) apres split '_' est le materiau.
    Fallback : recherche par mots-cles si la convention n'est pas respectee.
    """
    KNOWN = [u"Acier", u"Beton", u"Flocage", u"Bois"]

    # --- Methode 1 : extraction du 3eme segment (convention STR_XXX_MATERIAU_...) ---
    parts = fam_name.split(u"_")
    if len(parts) >= 3:
        seg = parts[2].strip()
        # Normalisation casse : Acier, Beton, Flocage, Bois
        for k in KNOWN:
            if seg.upper() == k.upper():
                return k

    # --- Methode 2 : fallback par mots-cles (familles hors convention) ---
    for source in (fam_name, type_name):
        src_upper = source.upper()
        for mat, keywords in MATERIAU_PRIORITY:
            for kw in keywords:
                if kw.upper() in src_upper:
                    return mat

    return u"Autres"


def _get_str_batiment(element):
    p = element.LookupParameter(PARAM_BATIMENT)
    if p is not None and p.HasValue:
        v = p.AsString()
        if v:
            return v.strip()
    return u""


def _volume_m3(element):
    p = element.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED)
    if p is None:
        p = element.get_Parameter(BuiltInParameter.STRUCTURAL_SECTION_AREA)
    if p is not None and p.HasValue:
        return p.AsDouble() * FEET3_TO_M3
    return 0.0


def _masse_volumique_kg_m3(element):
    """
    Lit '#STR_Masse volumique' (avec espace) sur le TYPE de l'element.
    Revit stocke la densite en unites internes kg/pied3.
    Conversion : val_interne * 35.3147 = kg/m3.
    Acier : 222.287 kg/ft3 * 35.3147 = 7850 kg/m3.
    """
    PARAM_NAME = u"#STR_Masse volumique"
    try:
        p = None
        el_type = doc.GetElement(element.GetTypeId())
        if el_type is not None:
            p = el_type.LookupParameter(PARAM_NAME)
        if p is None or not p.HasValue:
            p = element.LookupParameter(PARAM_NAME)
        if p is None or not p.HasValue:
            return None

        val_raw = p.AsDouble()
        if val_raw <= 0:
            return None

        # Conversion kg/ft3 -> kg/m3 : 1 ft3 = 0.0283168 m3 → facteur = 35.3147
        return val_raw * 35.3147

    except Exception:
        pass
    return None


def _mass_kg(element, volume_m3=0.0):
    """
    Calcule la masse en kg = volume_m3 x masse_volumique (kg/m3).
    masse_volumique lue depuis #STR_Masse_volumique sur le type.
    Retourne None si le parametre est absent ou invalide.
    """
    rho = _masse_volumique_kg_m3(element)
    if rho is None:
        return None
    return volume_m3 * rho


def collect_all_elements():
    """Collecte ossatures et poteaux."""
    framing = list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    columns = list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_StructuralColumns)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    return {CATEG_FRAMING: framing, CATEG_COLUMNS: columns}


def _get_type_names(element):
    """Retourne (fam_name, type_name, modele) pour un element."""
    fam_name  = u""
    type_name = u""
    modele    = u""
    try:
        el_type = doc.GetElement(element.GetTypeId())
        if el_type is not None:
            fp = el_type.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
            if fp:
                fam_name = fp.AsString() or u""
            tp = el_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if tp:
                type_name = tp.AsString() or u""
            mp = el_type.get_Parameter(BuiltInParameter.ALL_MODEL_MODEL)
            if mp and mp.HasValue:
                modele = mp.AsString() or u""
    except Exception:
        pass
    return fam_name, type_name, modele


def build_rows(all_elements, active_categs, active_bats, active_mats=None):
    """
    active_categs : set {"Ossatures", "Poteaux"}
    active_bats   : set de labels batiment ; {"Tous"} = pas de filtre
    active_mats   : None = tous, sinon set de chaines materiau
    Tri : Materiau > Categorie > Type
    Retourne les lignes de detail + sous-totaux par (materiau, categorie) + total global.
    """
    from collections import defaultdict, OrderedDict
    groups = defaultdict(lambda: {
        "elements": [], "volume": 0.0,
        "masse": 0.0, "nb_sans_masse": 0,
        "categorie": u"", "modele": u"",
    })

    tous_bats = (u"Tous" in active_bats)

    for categ_name, elements in all_elements.items():
        if categ_name not in active_categs:
            continue
        for el in elements:
            try:
                fam_name, type_name, modele = _get_type_names(el)
                mat = _detect_materiau(fam_name + u" " + type_name)

                if active_mats is not None and mat not in active_mats:
                    continue

                bat = _get_str_batiment(el)
                bat_key = bat if bat else u"(non renseigne)"

                if not tous_bats and bat_key not in active_bats:
                    continue

                vol   = _volume_m3(el)
                masse = _mass_kg(el, vol)
                label = type_name if type_name else fam_name
                # Cle : Materiau > Categorie > Type > Modele (tri dans cet ordre)
                key   = u"{}||{}||{}||{}".format(mat, categ_name, label, modele)

                groups[key]["elements"].append(el.Id.IntegerValue)
                groups[key]["volume"]    += vol
                groups[key]["categorie"]  = categ_name
                groups[key]["modele"]     = modele
                if masse is not None:
                    groups[key]["masse"] += masse
                else:
                    groups[key]["nb_sans_masse"] += 1
            except Exception:
                pass

    # --- Construire les lignes de detail triees (Materiau > Categorie > Type) ---
    detail_rows = []
    for key in sorted(groups.keys()):
        g = groups[key]
        parts    = key.split(u"||", 3)
        mat_lbl  = parts[0] if len(parts) > 0 else u""
        cat_lbl  = parts[1] if len(parts) > 1 else u""
        type_lbl = parts[2] if len(parts) > 2 else u""
        mod_lbl  = g["modele"]
        nb       = len(g["elements"])
        vol      = g["volume"]
        nb_sans  = g["nb_sans_masse"]
        if g["masse"] > 0:
            masse_str = u"{:.0f} kg".format(g["masse"])
            if nb_sans > 0:
                masse_str += u" (*)"
        else:
            masse_str = u"\u2014"

        detail_rows.append({
            "categorie":   cat_lbl,
            "materiau":    mat_lbl,
            "type":        type_lbl,
            "modele":      mod_lbl,
            "nb":          nb,
            "volume":      vol,
            "volume_str":  u"{:.3f} m\u00b3".format(vol),
            "masse_str":   masse_str,
            "masse":       g["masse"],
            "element_ids": list(g["elements"]),
            "is_total":    False,
            "is_subtotal": False,
            "checked":     True,
        })

    # --- Intercaler les sous-totaux par (materiau, categorie) ---
    rows = []
    total_vol = total_masse = 0.0

    subtotal_groups = OrderedDict()
    for r in detail_rows:
        key = (r["materiau"], r["categorie"])
        if key not in subtotal_groups:
            subtotal_groups[key] = {"rows": [], "vol": 0.0, "masse": 0.0,
                                    "nb": 0, "ids": []}
        subtotal_groups[key]["rows"].append(r)
        subtotal_groups[key]["vol"]   += r["volume"]
        subtotal_groups[key]["masse"] += r["masse"]
        subtotal_groups[key]["nb"]    += r["nb"]
        subtotal_groups[key]["ids"].extend(r["element_ids"])

    for (mat_lbl, cat_lbl), grp in subtotal_groups.items():
        rows.extend(grp["rows"])
        total_vol   += grp["vol"]
        total_masse += grp["masse"]

        st_masse_str = (u"{:.0f} kg".format(grp["masse"])
                        if grp["masse"] > 0 else u"\u2014")
        rows.append({
            "categorie":   cat_lbl,
            "materiau":    mat_lbl,
            "type":        u"Sous-total {} {}".format(mat_lbl, cat_lbl),
            "modele":      u"",
            "nb":          grp["nb"],
            "volume":      grp["vol"],
            "volume_str":  u"{:.3f} m\u00b3".format(grp["vol"]),
            "masse_str":   st_masse_str,
            "masse":       grp["masse"],
            "element_ids": list(grp["ids"]),   # ids pour la visu 3D
            "is_total":    False,
            "is_subtotal": True,
            "checked":     True,               # sous-totaux cochables
        })

    # Supprimer les sous-totaux si un seul groupe
    if len(subtotal_groups) <= 1:
        rows = [r for r in rows if not r["is_subtotal"]]

    # --- Ligne TOTAL global ---
    rows.append({
        "categorie":   u"",
        "materiau":    u"",
        "type":        u"TOTAL",
        "modele":      u"",
        "nb":          sum(r["nb"] for r in rows if not r["is_subtotal"] and not r["is_total"]),
        "volume":      total_vol,
        "volume_str":  u"{:.3f} m\u00b3".format(total_vol),
        "masse_str":   (u"{:.0f} kg".format(total_masse)
                        if total_masse > 0 else u"\u2014"),
        "masse":       total_masse,
        "element_ids": [],
        "is_total":    True,
        "is_subtotal": False,
        "checked":     False,
    })

    return rows


# =============================================================================
# EXPORT XLSX
# =============================================================================

def export_xlsx(rows, filepath, owner_window=None):
    """
    Exporte les donnees vers XLSX via xlsxwriter.
    Progression via forms.ProgressBar (barre de titre Revit — pas de fenetre separee).
    """
    try:
        import xlsxwriter
    except ImportError:
        forms.alert(
            u"Le module xlsxwriter n'est pas disponible dans cet environnement pyRevit.",
            title=u"Erreur export", warn_icon=True
        )
        return False

    data_rows   = [r for r in rows if not r["is_total"]]
    tot_row     = next((r for r in rows if r["is_total"]), None)
    total_steps = len(data_rows) + 4

    try:
        with forms.ProgressBar(
            title=u"Export XLSX — {{value}} / {{max_value}} lignes".format()
        ) as pb:
            pb.update_progress(0, total_steps)

            wb = xlsxwriter.Workbook(filepath)
            ws = wb.add_worksheet(u"Quantification")
            pb.update_progress(1, total_steps)

            # --- Formats ---
            fmt_hdr  = wb.add_format({
                "bold": True, "bg_color": "#2F6496", "font_color": "#FFFFFF",
                "border": 1, "font_name": "Calibri", "font_size": 11,
                "align": "center", "valign": "vcenter", "text_wrap": True,
            })
            fmt_alt    = wb.add_format({"bg_color": "#E8F0FA", "border": 1, "font_name": "Calibri", "font_size": 11})
            fmt_norm   = wb.add_format({"bg_color": "#FFFFFF",  "border": 1, "font_name": "Calibri", "font_size": 11})
            fmt_alt_r  = wb.add_format({"bg_color": "#E8F0FA", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right"})
            fmt_norm_r = wb.add_format({"bg_color": "#FFFFFF",  "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right"})
            # Formats numeriques : volume en m3 (3 decimales), masse en kg (entier)
            fmt_alt_vol  = wb.add_format({"bg_color": "#E8F0FA", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0.000"})
            fmt_norm_vol = wb.add_format({"bg_color": "#FFFFFF",  "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0.000"})
            fmt_alt_kg   = wb.add_format({"bg_color": "#E8F0FA", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0"})
            fmt_norm_kg  = wb.add_format({"bg_color": "#FFFFFF",  "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0"})
            fmt_tot    = wb.add_format({"bold": True, "bg_color": "#D0E4F7", "border": 1, "font_name": "Calibri", "font_size": 11})
            fmt_tot_r  = wb.add_format({"bold": True, "bg_color": "#D0E4F7", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right"})
            fmt_tot_vol = wb.add_format({"bold": True, "bg_color": "#D0E4F7", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0.000"})
            fmt_tot_kg  = wb.add_format({"bold": True, "bg_color": "#D0E4F7", "border": 1, "font_name": "Calibri", "font_size": 11, "align": "right", "num_format": "#,##0"})
            fmt_info   = wb.add_format({"italic": True, "font_color": "#888888", "font_name": "Calibri", "font_size": 9})

            # --- Largeurs colonnes ---
            ws.set_column(0, 0, 14); ws.set_column(1, 1, 14); ws.set_column(2, 2, 34)
            ws.set_column(3, 3, 34); ws.set_column(4, 4, 8);  ws.set_column(5, 5, 15)
            ws.set_column(6, 6, 15); ws.set_row(0, 28)

            # --- En-tete ---
            headers = [u"Catégorie", u"Matériau", u"Type", u"Modèle", u"Qte", u"Volume (m³)", u"Poids (kg)"]
            ws.write_row(0, 0, headers, fmt_hdr)
            pb.update_progress(2, total_steps)

            # --- Lignes de donnees ---
            for idx, row in enumerate(data_rows):
                pb.update_progress(3 + idx, total_steps)
                r_num  = idx + 1
                is_alt = (idx % 2 == 1)
                fmt_l   = fmt_alt    if is_alt else fmt_norm
                fmt_r   = fmt_alt_r  if is_alt else fmt_norm_r
                fmt_vol = fmt_alt_vol if is_alt else fmt_norm_vol
                fmt_kg  = fmt_alt_kg  if is_alt else fmt_norm_kg
                ws.write(r_num, 0, row["categorie"], fmt_l)
                ws.write(r_num, 1, row["materiau"],  fmt_l)
                ws.write(r_num, 2, row["type"],      fmt_l)
                ws.write(r_num, 3, row["modele"],    fmt_l)
                ws.write(r_num, 4, row["nb"],        fmt_r)
                ws.write_number(r_num, 5, row["volume"], fmt_vol)
                # Masse : valeur numerique si disponible, sinon cellule vide
                if row["masse"] > 0:
                    ws.write_number(r_num, 6, row["masse"], fmt_kg)
                else:
                    ws.write_blank(r_num, 6, fmt_kg)

            # --- Ligne TOTAL ---
            if tot_row:
                r_num = len(data_rows) + 1
                ws.write(r_num, 0, u"",            fmt_tot)
                ws.write(r_num, 1, u"",            fmt_tot)
                ws.write(r_num, 2, u"TOTAL",       fmt_tot)
                ws.write(r_num, 3, u"",            fmt_tot)
                ws.write(r_num, 4, tot_row["nb"],  fmt_tot_r)
                ws.write_number(r_num, 5, tot_row["volume"], fmt_tot_vol)
                if tot_row["masse"] > 0:
                    ws.write_number(r_num, 6, tot_row["masse"], fmt_tot_kg)
                else:
                    ws.write_blank(r_num, 6, fmt_tot_kg)

            # --- Pied de page ---
            ws.write(len(data_rows) + 3, 0,
                     u"STR BIM Tools v{}  |  Tony VARIN".format(SCRIPT_VERSION),
                     fmt_info)
            ws.freeze_panes(1, 0)
            wb.close()
            pb.update_progress(total_steps, total_steps)

        return True

    except Exception as ex:
        forms.alert(
            u"Erreur lors de l'export :\n{}".format(str(ex)),
            title=u"Erreur export", warn_icon=True
        )
        return False


# =============================================================================
# VUE 3D
# =============================================================================

VIEW_3D_NAME = u"STR_3D_Analyse quantites"


def compute_bounding_box(int_ids):
    minx = miny = minz =  1e18
    maxx = maxy = maxz = -1e18
    for eid in int_ids:
        el = doc.GetElement(ElementId(eid))
        if el is None:
            continue
        bb = el.get_BoundingBox(None)
        if bb is None:
            continue
        minx = min(minx, bb.Min.X); miny = min(miny, bb.Min.Y); minz = min(minz, bb.Min.Z)
        maxx = max(maxx, bb.Max.X); maxy = max(maxy, bb.Max.Y); maxz = max(maxz, bb.Max.Z)
    if minx >= 1e17:
        return None
    M = 2.0
    r = BoundingBoxXYZ()
    r.Min = XYZ(minx - M, miny - M, minz - M)
    r.Max = XYZ(maxx + M, maxy + M, maxz + M)
    return r


def show_3d_view(checked_rows):
    ids = []
    for r in checked_rows:
        ids.extend(r["element_ids"])
    if not ids:
        forms.alert(
            u"Aucun element coche a visualiser.",
            title=u"Visualisation 3D"
        )
        return False

    # Trouver le ViewFamilyType 3D (hors transaction)
    vft = None
    for vf in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if vf.ViewFamily == ViewFamily.ThreeDimensional:
            vft = vf
            break
    if vft is None:
        forms.alert(
            u"Aucun gabarit de vue 3D trouve.",
            title=u"Visualisation 3D", warn_icon=True
        )
        return False

    # Collecter les vues a supprimer (hors transaction)
    to_delete = [
        v.Id for v in FilteredElementCollector(doc).OfClass(View3D).ToElements()
        if not v.IsTemplate and v.Name == VIEW_3D_NAME
    ]

    # Si la vue a supprimer est la vue active, basculer sur une autre vue d'abord
    if to_delete:
        active_id = uidoc.ActiveView.Id if uidoc.ActiveView is not None else None
        if active_id is not None and active_id in to_delete:
            # Chercher n'importe quelle autre vue non-template pour s'y refugier
            fallback = None
            from Autodesk.Revit.DB import View
            for v in FilteredElementCollector(doc).OfClass(View).ToElements():
                if not v.IsTemplate and v.Id not in to_delete:
                    try:
                        uidoc.ActiveView = v
                        fallback = v
                        break
                    except Exception:
                        continue

    # Bounding box (hors transaction)
    bb = compute_bounding_box(ids)
    revit_ids_list = System.Collections.Generic.List[ElementId](
        [ElementId(i) for i in ids]
    )

    # Transaction 1 : supprimer l'ancienne vue si elle existe
    if to_delete:
        t_del = Transaction(doc, u"STR - Supprimer vue 3D existante")
        try:
            t_del.Start()
            for vid in to_delete:
                try:
                    doc.Delete(vid)
                except Exception:
                    pass
            if t_del.GetStatus() == TransactionStatus.Started:
                t_del.Commit()
        except Exception:
            if t_del.GetStatus() == TransactionStatus.Started:
                t_del.RollBack()
            traceback.print_exc()

    # Transaction 2 : creer la vue fraiche, appliquer section box et isolation
    t = Transaction(doc, u"STR - Vue 3D quantification")
    try:
        t.Start()
        view = View3D.CreateIsometric(doc, vft.Id)
        view.Name = VIEW_3D_NAME
        if bb is not None:
            view.IsSectionBoxActive = True
            view.SetSectionBox(bb)
        view.IsolateElementsTemporary(revit_ids_list)
        if t.GetStatus() == TransactionStatus.Started:
            t.Commit()
        uidoc.ActiveView = view
        return True
    except Exception:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        traceback.print_exc()
        return False


# =============================================================================
# VIEW MODEL — ligne DataGrid
# =============================================================================

class BeamRow(object):
    """Ligne DataGrid. IsChecked geree via Python set pour eviter les pieges WPF."""
    def __init__(self, data_dict, checked_set):
        self._data        = data_dict
        self._checked_set = checked_set
        self.RowKey       = id(data_dict)
        self.Categorie    = data_dict["categorie"]
        self.Materiau     = data_dict["materiau"]
        self.TypeNom      = data_dict["type"]
        self.ModeleStr    = data_dict["modele"]
        self.NbStr        = u"{}".format(data_dict["nb"])
        self.VolumeStr    = data_dict["volume_str"]
        self.MasseStr     = data_dict["masse_str"]
        self.IsTotal      = data_dict["is_total"]
        self.IsSubtotal   = data_dict["is_subtotal"]
        # Cocher les lignes de detail ET les sous-totaux (pas le TOTAL global)
        if not data_dict["is_total"]:
            self._checked_set.add(self.RowKey)

    @property
    def IsChecked(self):
        return (self.RowKey in self._checked_set)

    def toggle(self):
        if self.RowKey in self._checked_set:
            self._checked_set.discard(self.RowKey)
        else:
            self._checked_set.add(self.RowKey)


# =============================================================================
# POPUP MULTI-SELECTION AVEC CHECKBOXES
# =============================================================================

POPUP_XAML = """
<Popup xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
       xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
       StaysOpen="False" AllowsTransparency="True">
  <Border Background="White" BorderBrush="#C0D0E0" BorderThickness="1"
          CornerRadius="3" Padding="4">
    <StackPanel>
      <CheckBox x:Name="chk_all" FontWeight="SemiBold" Margin="4,4,4,2"/>
      <Rectangle Height="1" Fill="#C0D0E0" Margin="2,2"/>
      <ScrollViewer MaxHeight="220" VerticalScrollBarVisibility="Auto">
        <StackPanel x:Name="sp_items"/>
      </ScrollViewer>
    </StackPanel>
  </Border>
</Popup>
"""


class MultiCheckPopup(object):
    """Popup WPF avec checkboxes multi-selection."""

    def __init__(self, anchor_button, items, label_all, initial_selection=None):
        self._items    = list(items)
        self._sel      = set(initial_selection) if initial_selection is not None \
                         else set(self._items)
        self._checkboxes = {}
        self._busy       = [False]
        self.on_change   = None

        stream = System.IO.MemoryStream(
            System.Text.Encoding.UTF8.GetBytes(POPUP_XAML)
        )
        self._popup = XamlReader.Load(stream)
        self._popup.PlacementTarget = anchor_button
        self._popup.Placement = PlacementMode.Bottom

        self._chk_all = self._popup.FindName("chk_all")
        self._chk_all.Content  = label_all
        self._chk_all.Checked  += self._on_all_chk
        self._chk_all.Unchecked += self._on_all_unchk

        sp = self._popup.FindName("sp_items")
        for item in self._items:
            cb = CheckBox()
            cb.Content   = item
            cb.Margin    = Thickness(4, 2, 4, 2)
            cb.IsChecked = (item in self._sel)
            self._checkboxes[item] = cb
            cb.Checked   += self._on_item
            cb.Unchecked += self._on_item
            sp.Children.Add(cb)

        self._sync_all()

    def _sync_all(self):
        self._busy[0] = True
        n = len(self._sel)
        if n == len(self._items):
            self._chk_all.IsChecked = True
        elif n == 0:
            self._chk_all.IsChecked = False
        else:
            self._chk_all.IsChecked = None
        self._busy[0] = False

    def _on_all_chk(self, sender, e):
        if self._busy[0]: return
        self._busy[0] = True
        self._sel = set(self._items)
        for cb in self._checkboxes.values():
            cb.IsChecked = True
        self._busy[0] = False
        if self.on_change: self.on_change()

    def _on_all_unchk(self, sender, e):
        if self._busy[0]: return
        self._busy[0] = True
        self._sel = set()
        for cb in self._checkboxes.values():
            cb.IsChecked = False
        self._busy[0] = False
        if self.on_change: self.on_change()

    def _on_item(self, sender, e):
        if self._busy[0]: return
        lbl = sender.Content
        if sender.IsChecked:
            self._sel.add(lbl)
        else:
            self._sel.discard(lbl)
        self._sync_all()
        if self.on_change: self.on_change()

    def open(self):
        self._popup.IsOpen = True

    @property
    def selected(self):
        return set(self._sel)

    @property
    def all_selected(self):
        return len(self._sel) == len(self._items)

    def label_for_button(self):
        n     = len(self._sel)
        total = len(self._items)
        if n == 0:     return u"(aucun)"
        if n == total: return u"Tous"
        return u"{} / {}".format(n, total)


# =============================================================================
# XAML PRINCIPAL
# =============================================================================

XAML = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER_TITLE"
    Width="1040" Height="640"
    MinWidth="820" MinHeight="480"
    WindowStartupLocation="CenterScreen"
    Background="White"
    ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- BARRE DE FILTRES -->
    <Border Grid.Row="0" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="8,7">
      <StackPanel Orientation="Horizontal" VerticalAlignment="Center">

        <TextBlock x:Name="lbl_categ" VerticalAlignment="Center"
                   FontWeight="SemiBold" Margin="0,0,6,0"/>
        <Button x:Name="btn_categ" Width="140" Height="26"
                Background="White" BorderBrush="#A0B8D0" BorderThickness="1"
                HorizontalContentAlignment="Left" Padding="6,0" Margin="0,0,14,0"/>

        <TextBlock x:Name="lbl_mat" VerticalAlignment="Center"
                   FontWeight="SemiBold" Margin="0,0,6,0"/>
        <Button x:Name="btn_mat" Width="130" Height="26"
                Background="White" BorderBrush="#A0B8D0" BorderThickness="1"
                HorizontalContentAlignment="Left" Padding="6,0" Margin="0,0,14,0"/>

        <TextBlock x:Name="lbl_bat" VerticalAlignment="Center"
                   FontWeight="SemiBold" Margin="0,0,6,0"/>
        <Button x:Name="btn_bat" Width="160" Height="26"
                Background="White" BorderBrush="#A0B8D0" BorderThickness="1"
                HorizontalContentAlignment="Left" Padding="6,0" Margin="0,0,14,0"/>

        <Button x:Name="btn_refresh" Width="100" Height="26"
                Background="#2ECC71" Foreground="White"
                FontWeight="SemiBold" BorderThickness="0" Margin="0,0,20,0"/>

        <CheckBox x:Name="chk_select_all" VerticalAlignment="Center" Margin="0,0,5,0"/>
        <TextBlock x:Name="lbl_select_all" VerticalAlignment="Center"
                   FontSize="11" Foreground="#444444"/>

      </StackPanel>
    </Border>

    <!-- DATAGRID -->
    <DataGrid x:Name="dg_main" Grid.Row="1" Margin="8,8,8,4"
              AutoGenerateColumns="False" IsReadOnly="False"
              AlternatingRowBackground="#E8F0FA" RowBackground="White"
              GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
              HeadersVisibility="Column"
              SelectionMode="Single"
              CanUserResizeColumns="True" CanUserSortColumns="True"
              FontSize="12">
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,3"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.RowStyle>
        <Style TargetType="DataGridRow">
          <Style.Triggers>
            <DataTrigger Binding="{Binding IsSubtotal}" Value="True">
              <Setter Property="Background" Value="#C8DAF0"/>
              <Setter Property="FontWeight" Value="Bold"/>
            </DataTrigger>
            <DataTrigger Binding="{Binding IsTotal}" Value="True">
              <Setter Property="Background" Value="#D2E1F2"/>
              <Setter Property="FontWeight" Value="Bold"/>
            </DataTrigger>
          </Style.Triggers>
        </Style>
      </DataGrid.RowStyle>
      <DataGrid.Columns>
        <DataGridCheckBoxColumn x:Name="col_chk"
                                Binding="{Binding IsChecked}"
                                SortMemberPath="IsChecked"
                                Width="36"/>
        <DataGridTextColumn x:Name="col_categ"  Binding="{Binding Categorie}"  Width="100"/>
        <DataGridTextColumn x:Name="col_mat"    Binding="{Binding Materiau}"   Width="100"/>
        <DataGridTextColumn x:Name="col_type"   Binding="{Binding TypeNom}"    Width="220"/>
        <DataGridTextColumn x:Name="col_modele" Binding="{Binding ModeleStr}"  Width="220"/>
        <DataGridTextColumn x:Name="col_nb"     Binding="{Binding NbStr}"      Width="100"/>
        <DataGridTextColumn x:Name="col_vol"    Binding="{Binding VolumeStr}"  Width="100"/>
        <DataGridTextColumn x:Name="col_mass"   Binding="{Binding MasseStr}"   Width="100"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- FOOTER -->
    <Border Grid.Row="2" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer"
                   FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal"
                    Margin="0,0,8,0">
          <Button x:Name="btn_export3d" Width="150" Height="26" Margin="4,0,0,0"
                  Background="#9B59B6" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_export_xlsx" Width="110" Height="26" Margin="4,0,0,0"
                  Background="#E67E22" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close" Width="90" Height="26" Margin="4,0,0,0"
                  Background="#3498DB" Foreground="White"
                  FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>

  </Grid>
</Window>
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    # ---- Collecte avec barre de progression native Revit ----
    with forms.ProgressBar(title=u"STR BIM Tools — Chargement...") as pb:
        pb.update_progress(0, 3)

        pb.update_progress(1, 3)
        all_elements = collect_all_elements()

        if sum(len(v) for v in all_elements.values()) == 0:
            forms.alert(
                u"Aucune ossature ni poteau trouve dans le modele.",
                title=u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION)
            )
            return

        pb.update_progress(2, 3)
        materiaux_set = set()
        batiments_set = set()
        for categ_elems in all_elements.values():
            for el in categ_elems:
                try:
                    fn, tn, _mod = _get_type_names(el)
                    materiaux_set.add(_detect_materiau(fn + u" " + tn))
                    bat = _get_str_batiment(el)
                    batiments_set.add(bat if bat else u"(non renseigne)")
                except Exception:
                    pass

        sorted_mats = sorted(list(materiaux_set))
        sorted_bats = sorted(list(batiments_set))

        pb.update_progress(3, 3)

    # ---- Charger XAML ----
    stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
    window = XamlReader.Load(stream)

    # ---- Textes (accents hors XAML) ----
    window.Title = TOOL_NAME
    window.FindName("lbl_footer").Text = (
        u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    )
    window.FindName("lbl_categ").Text      = u"Categories :"
    window.FindName("lbl_mat").Text        = u"Materiau :"
    window.FindName("lbl_bat").Text        = u"Batiment :"
    window.FindName("lbl_select_all").Text = u"Tout cocher / decocher"
    window.FindName("btn_refresh").Content     = u"Actualiser"
    window.FindName("btn_export3d").Content    = u"Visualisation 3D"
    window.FindName("btn_export_xlsx").Content = u"Export XLSX"
    window.FindName("btn_close").Content       = u"Fermer"

    # ---- Colonnes DataGrid ----
    dg = window.FindName("dg_main")
    dg.FindName("col_chk").Header    = u""
    dg.FindName("col_categ").Header  = u"Categorie"
    dg.FindName("col_mat").Header    = u"Materiau"
    dg.FindName("col_type").Header   = u"Famille / Type"
    dg.FindName("col_modele").Header = u"Modele"
    dg.FindName("col_nb").Header     = u"Qte"
    dg.FindName("col_vol").Header    = u"Volume total"
    dg.FindName("col_mass").Header   = u"Poids total"

    # ---- Popup Categories ----
    btn_categ   = window.FindName("btn_categ")
    popup_categ = MultiCheckPopup(
        btn_categ,
        [CATEG_FRAMING, CATEG_COLUMNS],
        u"Toutes les categories",
        initial_selection=[CATEG_FRAMING, CATEG_COLUMNS]
    )

    # ---- Popup Materiau ----
    btn_mat   = window.FindName("btn_mat")
    popup_mat = MultiCheckPopup(
        btn_mat,
        sorted_mats,
        u"Tous les materiaux",
        initial_selection=set(sorted_mats)
    )

    # ---- Popup Batiment ----
    btn_bat   = window.FindName("btn_bat")
    popup_bat = MultiCheckPopup(
        btn_bat,
        sorted_bats,
        u"Tous les batiments",
        initial_selection=set(sorted_bats)
    )

    def _update_btn_labels():
        btn_categ.Content = popup_categ.label_for_button()
        btn_mat.Content   = popup_mat.label_for_button()
        btn_bat.Content   = popup_bat.label_for_button()

    _update_btn_labels()

    # ---- Etat global ----
    state = {"rows": [], "beam_rows": [], "checked_set": set()}

    chk_select_all = window.FindName("chk_select_all")
    updating_sa    = [False]

    def _sync_select_all():
        updating_sa[0] = True
        data_brs = [r for r in state["beam_rows"] if not r.IsTotal]
        if not data_brs:
            chk_select_all.IsChecked = False
        else:
            nb = sum(1 for r in data_brs if r.IsChecked)
            if nb == len(data_brs):
                chk_select_all.IsChecked = True
            elif nb == 0:
                chk_select_all.IsChecked = False
            else:
                chk_select_all.IsChecked = None
        updating_sa[0] = False

    def _rebuild_grid(rows):
        new_set = set()
        state["checked_set"] = new_set
        brs = [BeamRow(r, new_set) for r in rows]
        state["beam_rows"] = brs
        dg.ItemsSource = None
        dg.ItemsSource = brs
        _sync_select_all()

    def refresh_data():
        active_categs = popup_categ.selected
        active_bats   = popup_bat.selected
        if popup_bat.all_selected:
            active_bats = set([u"Tous"])

        active_mats = (None if popup_mat.all_selected
                       else popup_mat.selected)

        rows = build_rows(all_elements, active_categs, active_bats, active_mats)
        state["rows"] = rows
        _rebuild_grid(rows)
        _update_btn_labels()

    # Chargement initial
    refresh_data()

    # ---- Coches dans le DataGrid (CurrentCellChanged — pattern IronPython) ----
    def on_cell_changed(sender, e):
        if dg.CurrentColumn is None:
            return
        if dg.CurrentColumn.DisplayIndex != 0:
            return
        row_obj = dg.CurrentItem
        if row_obj is None or not hasattr(row_obj, "toggle"):
            return
        if row_obj.IsTotal:
            return
        row_obj.toggle()
        src = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = src
        _sync_select_all()

    dg.CurrentCellChanged += on_cell_changed

    # ---- Tout cocher / decocher ----
    def on_select_all(sender, e):
        if updating_sa[0]:
            return
        checked = (chk_select_all.IsChecked == True)
        cs = state["checked_set"]
        for r in state["beam_rows"]:
            if r.IsTotal:
                continue
            if checked:
                cs.add(r.RowKey)
            else:
                cs.discard(r.RowKey)
        src = dg.ItemsSource
        dg.ItemsSource = None
        dg.ItemsSource = src

    chk_select_all.Checked   += on_select_all
    chk_select_all.Unchecked += on_select_all

    # ---- Evenements boutons ----
    def on_btn_categ(sender, e):
        popup_categ.open()

    def on_btn_mat(sender, e):
        popup_mat.open()

    def on_btn_bat(sender, e):
        popup_bat.open()

    def on_refresh(sender, e):
        refresh_data()

    def on_export_xlsx(sender, e):
        dlg = SaveFileDialog()
        dlg.Title      = u"Exporter vers XLSX"
        dlg.Filter     = u"Fichier Excel (*.xlsx)|*.xlsx"
        dlg.DefaultExt = u"xlsx"
        dlg.FileName   = u"Quantification_Ossatures_Poteaux.xlsx"
        if dlg.ShowDialog() == DialogResult.OK:
            ok = export_xlsx(state["rows"], dlg.FileName, owner_window=window)
            if ok:
                forms.alert(
                    u"Export reussi :\n{}".format(dlg.FileName),
                    title=u"Export XLSX"
                )

    def on_export3d(sender, e):
        checked_rows = [
            r._data for r in state["beam_rows"]
            if not r.IsTotal and r.IsChecked
        ]
        ok = show_3d_view(checked_rows)
        if ok:
            window.Close()

    def on_close(sender, e):
        window.Close()

    btn_categ.Click                            += on_btn_categ
    btn_mat.Click                              += on_btn_mat
    btn_bat.Click                              += on_btn_bat
    window.FindName("btn_refresh").Click       += on_refresh
    window.FindName("btn_export_xlsx").Click   += on_export_xlsx
    window.FindName("btn_export3d").Click      += on_export3d
    window.FindName("btn_close").Click         += on_close

    window.ShowDialog()


if __name__ == "__main__":
    main()