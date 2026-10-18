# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Hauteur Etayage"
# =============================================================================
"""
HAUTEUR D'ÉTAYAGE ENTRE DALLES
================================
Pour chaque dalle du modèle :
  - Détecte la dalle immédiatement inférieure (dont le centroïde XY de la dalle
    courante se trouve au-dessus de l'emprise bounding box XY de la dalle inf.)
  - Mesure : Face supérieure dalle inf. → Face inférieure dalle sup.
  - Écrit la valeur en cm dans le paramètre partagé "STR_Hauteur_Etayage_Auto"
  - Si aucune dalle en dessous → écrit "Aucune dalle inférieure"

Paramètre créé avec confirmation si absent (Text, instance, catégorie Floors).
Revit 2024 / pyRevit / IronPython 2.7
"""

import os
import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    Transaction, ExternalDefinitionCreationOptions,
    CategorySet, StorageType, BuiltInParameter
)

# Revit 2024 : BuiltInParameterGroup → GroupTypeId
# Revit 2024 : ParameterType        → SpecTypeId (ForgeTypeId)
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

from pyrevit import revit, forms, script

# ─── CONFIG ────────────────────────────────────────────────────────────────────

PARAM_NAME              = "STR_Hauteur_Etayage_Auto"
SHARED_PARAM_GROUP_NAME = "STR - Étayage"
NO_SLAB_BELOW_TEXT      = "Aucune dalle inférieure"
Z_TOLERANCE_FT          = 0.001 / 0.3048   # 1 mm en pieds

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def feet_to_cm(feet_value):
    return feet_value * 30.48


def centroid_inside_bbox_xy(cx, cy, bb):
    if bb is None:
        return False
    return (bb.Min.X <= cx <= bb.Max.X) and (bb.Min.Y <= cy <= bb.Max.Y)


def get_param_by_name(element, name):
    for p in element.Parameters:
        if p.Definition.Name == name:
            return p
    return None


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
        forms.alert(u"Impossible d'ouvrir le fichier de paramètres partagés.",
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

        t = Transaction(doc, u"Créer paramètre {}".format(param_name))
        t.Start()
        try:
            doc.ParameterBindings.Insert(ext_defn, instance_binding, PARAM_GROUP)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(u"Échec création {} :\n{}".format(param_name, str(e)),
                        exitscript=True)
            return False
    return True


# ─── SCRIPT PRINCIPAL ──────────────────────────────────────────────────────────

doc    = revit.doc
app    = doc.Application
output = script.get_output()

output.print_md(u"# Hauteur d'étayage entre dalles")
output.print_md(u"Paramètre cible : **{}**".format(PARAM_NAME))

# 1. Collecter toutes les dalles
all_floors = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_Floors)
    .WhereElementIsNotElementType()
    .ToElements()
)

output.print_md(u"**{}** dalle(s) trouvée(s) dans le modèle.".format(len(all_floors)))

if not all_floors:
    forms.alert(u"Aucune dalle trouvée dans le modèle.", exitscript=True)

# 2. Vérifier / créer le paramètre partagé
bound_names = get_bound_param_names(doc)
missing = [p for p in [PARAM_NAME] if p not in bound_names]
if missing:
    msg = u"Le paramètre suivant est absent du projet :\n\n"
    for m in missing:
        msg += u"  \u2022  {}\n".format(m)
    msg += u"\nGroupe : Cotes | Catégorie : Sols | Instance\n\nVoulez-vous le créer ?"
    if not forms.alert(msg, yes=True, no=True, title=u"Paramètre manquant"):
        script.exit()
    create_shared_parameters(doc, app, missing)
else:
    output.print_md(u"Paramètre **{}** présent.".format(PARAM_NAME))

# 3. Précalculer les données géométriques de chaque dalle
floor_data = {}  # ElementId → {z_min, z_max, cx, cy, bb, floor}
for floor in all_floors:
    bb = floor.get_BoundingBox(None)
    if bb is None:
        continue
    floor_data[floor.Id] = {
        "z_min":  bb.Min.Z,
        "z_max":  bb.Max.Z,
        "cx":     (bb.Min.X + bb.Max.X) / 2.0,
        "cy":     (bb.Min.Y + bb.Max.Y) / 2.0,
        "bb":     bb,
        "floor":  floor
    }

# 4. Pour chaque dalle, trouver la dalle immédiatement en dessous
#    Critères :
#      a) Le centroïde XY de la dalle courante est dans l'emprise XY de la candidate
#      b) z_max_candidate < z_min_dalle_courante  (strictement en dessous)
#      c) Parmi les candidates valides → prendre celle avec le z_max le plus élevé

results   = {}  # ElementId → valeur à écrire (str)
total_cal = len(floor_data)

output.print_md(u"Calcul des hauteurs d'étayage...")
for i, (fid, fdata) in enumerate(floor_data.items()):
    output.update_progress(i + 1, total_cal)

    z_min_cur = fdata["z_min"]
    cx_cur    = fdata["cx"]
    cy_cur    = fdata["cy"]

    best_candidate = None
    best_z_max     = None

    for cid, cdata in floor_data.items():
        if cid == fid:
            continue
        z_max_cand = cdata["z_max"]
        if z_max_cand >= z_min_cur - Z_TOLERANCE_FT:
            continue
        if not centroid_inside_bbox_xy(cx_cur, cy_cur, cdata["bb"]):
            continue
        if best_z_max is None or z_max_cand > best_z_max:
            best_z_max     = z_max_cand
            best_candidate = cdata

    if best_candidate is None:
        results[fid] = NO_SLAB_BELOW_TEXT
    else:
        distance_cm  = feet_to_cm(z_min_cur - best_candidate["z_max"])
        results[fid] = u"{:.1f}".format(distance_cm)

# 5. Écrire dans le paramètre
total_wri = len(all_floors)

output.print_md(u"Écriture des paramètres...")
t = Transaction(doc, u"Hauteur étayage - {}".format(PARAM_NAME))
t.Start()
try:
    written = 0
    skipped = 0
    for i, floor in enumerate(all_floors):
        output.update_progress(i + 1, total_wri)
        fid   = floor.Id
        value = results.get(fid, NO_SLAB_BELOW_TEXT)
        param = get_param_by_name(floor, PARAM_NAME)
        if param is None:
            output.print_md(u"⚠ Paramètre introuvable sur la dalle `{}` — ignorée.".format(fid))
            skipped += 1
            continue
        if param.StorageType == StorageType.String:
            param.Set(value)
            written += 1
        else:
            output.print_md(u"⚠ Dalle `{}` — type de stockage inattendu ({}).".format(
                fid, param.StorageType))
            skipped += 1
    t.Commit()
except Exception as e:
    t.RollBack()
    forms.alert(u"Erreur lors de l'écriture des paramètres :\n{}".format(str(e)),
                exitscript=True)

# 6. Rapport final
def get_mark(floor):
    p = floor.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
    return p.AsString() if p and p.AsString() else u"—"

output.print_md(u"---")
output.print_md(u"### \u2705 Terminé")
output.print_md(u"- **{}** dalle(s) mise(s) à jour".format(written))
output.print_md(u"- **{}** dalle(s) ignorée(s)".format(skipped))
output.print_md(u"")
output.print_md(u"#### Détail par dalle :")
output.print_table(
    table_data=[
        [
            output.linkify(fid),
            get_mark(floor_data[fid]["floor"]),
            results.get(fid, NO_SLAB_BELOW_TEXT)
        ]
        for fid in floor_data.keys()
    ],
    columns=["ElementId", "Repère", u"Valeur écrite ({})".format(PARAM_NAME)]
)
