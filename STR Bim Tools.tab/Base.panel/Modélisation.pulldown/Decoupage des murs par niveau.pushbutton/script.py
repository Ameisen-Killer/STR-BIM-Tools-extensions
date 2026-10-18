# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Decoupage Murs par Niveaux"
# =============================================================================
"""
split_wall_by_levels.py
-----------------------
Découpe un mur sélectionné par les niveaux qu'il traverse.
Tous les paramètres d'instance du mur original sont copiés dans chaque segment.

Usage PyRevit : sélectionner UN mur dans Revit, puis lancer le script.
Compatibilité : Revit 2024 / IronPython 2.7 (pyRevit)
"""

__title__ = "Découpe le mur par les niveaux"
__author__ = "Tony Varin"
__doc__ = "Découpe le mur sélectionné par les niveaux qu'il traverse."

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from pyrevit import revit, DB, script, forms

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

# ---------------------------------------------------------------------------
# Paramètres BuiltIn à NE PAS copier :
#   - contraintes géométriques gérées manuellement (base/tête/offset/hauteur)
#   - paramètres structurels passés dans Wall.Create
#   - identifiants lecture seule
# ---------------------------------------------------------------------------
SKIP_BIPS = {
    DB.BuiltInParameter.WALL_BASE_CONSTRAINT,
    DB.BuiltInParameter.WALL_BASE_OFFSET,
    DB.BuiltInParameter.WALL_HEIGHT_TYPE,
    DB.BuiltInParameter.WALL_TOP_OFFSET,
    DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM,
    DB.BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM,
    DB.BuiltInParameter.ID_PARAM,
    DB.BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM,
    DB.BuiltInParameter.ELEM_FAMILY_PARAM,
    DB.BuiltInParameter.ELEM_TYPE_PARAM,
    DB.BuiltInParameter.SYMBOL_ID_PARAM,
}


# ---------------------------------------------------------------------------
# Utilitaire : capture un snapshot des paramètres d'instance
# ---------------------------------------------------------------------------
def snapshot_instance_params(element):
    """
    Retourne un dict { clé : valeur_brute } pour tous les paramètres
    d'instance modifiables de l'élément.

    Clé = DB.Guid  pour les shared parameters
          BuiltInParameter  pour les paramètres natifs
    """
    snapshot = {}
    for param in element.Parameters:
        if param.IsReadOnly:
            continue
        if param.StorageType == DB.StorageType.None:
            continue

        # Déterminer la clé
        if param.IsShared:
            key = param.GUID
        else:
            try:
                bip = param.Definition.BuiltInParameter
            except Exception:
                continue
            if bip in SKIP_BIPS:
                continue
            key = bip

        # Capturer la valeur brute
        try:
            st = param.StorageType
            if st == DB.StorageType.ElementId:
                snapshot[key] = param.AsElementId()
            elif st == DB.StorageType.Double:
                snapshot[key] = param.AsDouble()
            elif st == DB.StorageType.Integer:
                snapshot[key] = param.AsInteger()
            elif st == DB.StorageType.String:
                snapshot[key] = param.AsString()
        except Exception:
            pass  # certains params lèvent même sans IsReadOnly

    return snapshot


# ---------------------------------------------------------------------------
# Utilitaire : applique un snapshot sur un élément cible
# ---------------------------------------------------------------------------
def apply_snapshot(element, snapshot):
    """
    Applique le snapshot sur l'élément cible.
    Retourne (nb_ok, nb_skipped, liste_messages_erreur).
    """
    nb_ok = 0
    nb_skip = 0
    errors = []

    for key, value in snapshot.items():
        # Récupérer le paramètre cible (shared ou natif)
        if isinstance(key, DB.Guid):
            param = element.get_Parameter(key)
        else:
            param = element.get_Parameter(key)

        if param is None or param.IsReadOnly:
            nb_skip += 1
            continue

        try:
            st = param.StorageType
            if st == DB.StorageType.ElementId:
                param.Set(value)
            elif st == DB.StorageType.Double:
                param.Set(value)
            elif st == DB.StorageType.Integer:
                param.Set(value)
            elif st == DB.StorageType.String:
                if value is not None:
                    param.Set(value)
            nb_ok += 1
        except Exception as exc:
            nb_skip += 1
            try:
                param_name = param.Definition.Name
            except Exception:
                param_name = str(key)
            errors.append("{} : {}".format(param_name, exc))

    return nb_ok, nb_skip, errors


# ===========================================================================
# 1. Récupération du mur sélectionné
# ===========================================================================
selection = uidoc.Selection.GetElementIds()

if len(selection) != 1:
    forms.alert(
        "Sélectionne exactement UN mur avant de lancer le script.",
        exitscript=True
    )

wall = doc.GetElement(list(selection)[0])

if not isinstance(wall, DB.Wall):
    forms.alert(
        "L'élément sélectionné n'est pas un mur.",
        exitscript=True
    )

# ===========================================================================
# 2. Géométrie du mur : Z bas et Z haut
# ===========================================================================
bb = wall.get_BoundingBox(None)
if bb is None:
    forms.alert("Impossible de récupérer la BoundingBox du mur.", exitscript=True)

z_bottom = bb.Min.Z
z_top    = bb.Max.Z

output.print_md("## Mur sélectionné")
output.print_md("**ID :** {}".format(wall.Id))
output.print_md("**Z bas :** {:.4f} ft  |  **Z haut :** {:.4f} ft".format(z_bottom, z_top))

# ===========================================================================
# 3. Snapshot des paramètres d'instance — AVANT toute transaction
# ===========================================================================
param_snapshot = snapshot_instance_params(wall)
output.print_md("**Paramètres d'instance capturés :** {}".format(len(param_snapshot)))

# ===========================================================================
# 4. Collecte des niveaux intermédiaires
# ===========================================================================
TOLERANCE = 5.0 / 304.8   # 5 mm en pieds

all_levels = (
    DB.FilteredElementCollector(doc)
    .OfClass(DB.Level)
    .ToElements()
)

cut_levels = sorted(
    [lvl for lvl in all_levels
     if (z_bottom + TOLERANCE) < lvl.Elevation < (z_top - TOLERANCE)],
    key=lambda l: l.Elevation
)

if not cut_levels:
    forms.alert(
        "Aucun niveau intermédiaire trouvé dans la hauteur du mur.\n"
        "Le mur ne sera pas découpé.",
        exitscript=True
    )

output.print_md("**Niveaux de découpe trouvés :** {}".format(len(cut_levels)))
for lvl in cut_levels:
    output.print_md("  • {} → {:.4f} ft".format(lvl.Name, lvl.Elevation))

# ===========================================================================
# 5. Confirmation utilisateur
# ===========================================================================
level_names = "\n".join(["  • {}".format(l.Name) for l in cut_levels])
confirm = forms.alert(
    "Le mur sera découpé en {} segments par les niveaux :\n\n{}"
    "\n\nTous les paramètres d'instance ({} au total) seront copiés."
    "\n\nContinuer ?".format(
        len(cut_levels) + 1, level_names, len(param_snapshot)
    ),
    yes=True, no=True
)
if not confirm:
    script.exit()

# ===========================================================================
# 6. Données géométriques du mur original
# ===========================================================================
location_curve = wall.Location
if not isinstance(location_curve, DB.LocationCurve):
    forms.alert("Le mur ne possède pas de LocationCurve.", exitscript=True)

wall_curve    = location_curve.Curve
wall_type_id  = wall.GetTypeId()
wall_level_id = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
wall_flip     = wall.Flipped
structural    = wall.StructuralUsage != DB.Structure.StructuralWallUsage.NonBearing

# ===========================================================================
# 7. Construction des segments
#    segment 0 : z_bottom → cut_levels[0]
#    segment i : cut_levels[i-1] → cut_levels[i]
#    segment N : cut_levels[-1] → z_top
# ===========================================================================
elevations     = [z_bottom] + [l.Elevation for l in cut_levels] + [z_top]
segments       = list(zip(elevations[:-1], elevations[1:]))
base_level_ids = [wall_level_id] + [l.Id for l in cut_levels]

output.print_md("---")
output.print_md("## Création des {} segments".format(len(segments)))

# ===========================================================================
# 8. Transaction unique : créer + copier params + supprimer l'original
# ===========================================================================
created_walls = []
copy_report   = []  # [(seg_num, nb_ok, nb_skip, errors)]

with DB.Transaction(doc, "Découper mur par niveaux") as t:
    t.Start()

    for i, ((z_bas, z_haut), base_lvl_id) in enumerate(zip(segments, base_level_ids)):

        height          = z_haut - z_bas
        base_level      = doc.GetElement(base_lvl_id)
        base_elev       = base_level.Elevation
        new_base_offset = z_bas - base_elev

        # ── Création du segment ──────────────────────────────────────────
        new_wall = DB.Wall.Create(
            doc,
            wall_curve,
            wall_type_id,
            base_lvl_id,
            height,
            new_base_offset,
            wall_flip,
            structural
        )

        # ── Forcer contrainte haute = Non connecté ───────────────────────
        p_top = new_wall.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE)
        if p_top and not p_top.IsReadOnly:
            p_top.Set(DB.ElementId.InvalidElementId)

        # ── Copie de tous les paramètres d'instance ──────────────────────
        nb_ok, nb_skip, errs = apply_snapshot(new_wall, param_snapshot)
        copy_report.append((i + 1, nb_ok, nb_skip, errs))

        created_walls.append(new_wall)
        output.print_md(
            "  ✔ Segment {} — base : **{}** | offset base : {:.4f} ft | "
            "hauteur : {:.4f} ft | params : {}/{} ok".format(
                i + 1, base_level.Name,
                new_base_offset, height,
                nb_ok, nb_ok + nb_skip
            )
        )

    # ── Suppression du mur original ─────────────────────────────────────
    doc.Delete(wall.Id)
    output.print_md("\n**Mur original supprimé (Id {}).**".format(wall.Id))

    t.Commit()

# ===========================================================================
# 9. Rapport détaillé des paramètres non copiés
# ===========================================================================
all_errors = [(seg, err) for seg, _, _, errs in copy_report for err in errs]
if all_errors:
    output.print_md("---")
    output.print_md("### ⚠ Paramètres non copiés")
    for seg_num, err_msg in all_errors:
        output.print_md("  Segment {} — `{}`".format(seg_num, err_msg))
else:
    output.print_md("\n_Aucune erreur de copie de paramètres._")

# ===========================================================================
# 10. Résumé final
# ===========================================================================
output.print_md("---")
output.print_md("## ✅ Découpe terminée — {} segments créés".format(len(created_walls)))

total_ok   = sum(r[1] for r in copy_report)
total_skip = sum(r[2] for r in copy_report)
output.print_md(
    "Paramètres copiés au total : **{}** ok / {} ignorés".format(
        total_ok, total_skip
    )
)
output.print_md(
    "> **Rappel :** vérifie les contraintes de tête et les joints de mur "
    "si certains segments doivent être connectés à un niveau supérieur."
)