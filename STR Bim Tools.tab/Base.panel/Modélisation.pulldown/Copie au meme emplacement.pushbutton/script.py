# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Copie au meme emplacement"
# =============================================================================
__title__ = "Copie au même emplacement"
__doc__ = """Copie un élément sélectionné dans une maquette liée
vers la maquette en cours, au même emplacement.

- Éléments standards : CopyElements avec transform du lien
- Familles in-situ   : CopyElements avec Transform.Identity
  (la géométrie in-situ est déjà en coordonnées absolues)
- Phases création / démolition copiées à l'identique (par nom)
"""

import clr
clr.AddReference('System')
from System.Collections.Generic import List

from pyrevit import revit, DB, forms
from Autodesk.Revit.DB import (
    ElementId,
    RevitLinkInstance,
    ElementTransformUtils,
    CopyPasteOptions,
    FamilyInstance,
    BuiltInCategory,
    BuiltInParameter,
    Transform,
    Options,
    ViewDetailLevel,
    GeometryInstance,
    Solid,
    SolidUtils,
    DirectShape,
    GeometryObject,
)
from Autodesk.Revit.UI.Selection import ObjectType
import traceback

doc   = revit.doc
uidoc = revit.uidoc


# ---------------------------------------------------------------------------
# Détection famille in-situ
# ---------------------------------------------------------------------------

def is_in_place(element):
    try:
        return isinstance(element, FamilyInstance) and element.Symbol.Family.IsInPlace
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def get_phase_by_name(target_doc, phase_name):
    """Recherche une phase dans un document par son nom."""
    for phase in target_doc.Phases:
        if phase.Name == phase_name:
            return phase
    return None


def read_phases(linked_element, linked_doc):
    """
    Retourne (created_phase_name, demolished_phase_name) depuis l'élément lié.
    demolished_phase_name vaut None si l'élément n'est pas démoli.
    """
    created_name    = None
    demolished_name = None

    try:
        c_id = linked_element.CreatedPhaseId
        if c_id and c_id != ElementId.InvalidElementId:
            phase = linked_doc.GetElement(c_id)
            if phase:
                created_name = phase.Name
    except Exception:
        pass

    try:
        d_id = linked_element.DemolishedPhaseId
        if d_id and d_id != ElementId.InvalidElementId:
            phase = linked_doc.GetElement(d_id)
            if phase:
                demolished_name = phase.Name
    except Exception:
        pass

    return created_name, demolished_name


def apply_phases(new_ids, created_name, demolished_name):
    """
    Applique les phases de création / démolition aux éléments copiés.
    La correspondance se fait par nom de phase.
    """
    if not created_name:
        return

    warnings = []

    host_created    = get_phase_by_name(doc, created_name)
    host_demolished = get_phase_by_name(doc, demolished_name) if demolished_name else None

    if not host_created:
        warnings.append("Phase de création '{}' introuvable dans la maquette hôte.".format(created_name))

    if demolished_name and not host_demolished:
        warnings.append("Phase de démolition '{}' introuvable dans la maquette hôte.".format(demolished_name))

    with revit.Transaction("Appliquer phases"):
        for eid in new_ids:
            elem = doc.GetElement(eid)
            if not elem:
                continue

            if host_created:
                p = elem.get_Parameter(BuiltInParameter.PHASE_CREATED)
                if p and not p.IsReadOnly:
                    p.Set(host_created.Id)

            if host_demolished:
                p = elem.get_Parameter(BuiltInParameter.PHASE_DEMOLISHED)
                if p and not p.IsReadOnly:
                    p.Set(host_demolished.Id)

    if warnings:
        forms.alert("\n".join(warnings), title="Avertissement — phases")


# ---------------------------------------------------------------------------
# Fallback DirectShape (dernier recours — géométrie non éditable)
# ---------------------------------------------------------------------------

def extract_solids(element, link_transform):
    opt = Options()
    opt.ComputeReferences = False
    opt.DetailLevel       = ViewDetailLevel.Fine
    geo_elem = element.get_Geometry(opt)
    if not geo_elem:
        return []
    solids = []
    for geo_obj in geo_elem:
        if isinstance(geo_obj, Solid) and geo_obj.Volume > 1e-9:
            solids.append(SolidUtils.CreateTransformed(geo_obj, link_transform))
        elif isinstance(geo_obj, GeometryInstance):
            for inner in geo_obj.GetInstanceGeometry():
                if isinstance(inner, Solid) and inner.Volume > 1e-9:
                    solids.append(SolidUtils.CreateTransformed(inner, link_transform))
    return solids


def copy_as_directshape(linked_element, link_transform):
    solids = extract_solids(linked_element, link_transform)
    if not solids:
        return None
    try:
        cat_id = linked_element.Category.Id
    except Exception:
        cat_id = ElementId(BuiltInCategory.OST_GenericModel)
    shape_list = List[GeometryObject]()
    for s in solids:
        shape_list.Add(s)
    new_ids = List[ElementId]()
    with revit.Transaction("Copier → DirectShape"):
        ds = DirectShape.CreateElement(doc, cat_id)
        ds.SetShape(shape_list)
        if ds and ds.IsValidObject:
            new_ids.Add(ds.Id)
    return new_ids if new_ids.Count > 0 else None


# ---------------------------------------------------------------------------
# Copie in-situ (CopyElements sans transform — géométrie déjà en coords absolues)
# ---------------------------------------------------------------------------

def copy_inplace(linked_doc, linked_element_id):
    """
    Pour les familles in-situ, la géométrie est définie en coordonnées absolues
    dans le document lié. Appliquer link_transform la déformerait (double transform).
    On copie donc avec Transform.Identity pour préserver la géométrie et l'éditabilité.
    Note : si le lien est décalé/tourné par rapport au projet hôte, l'élément
    sera positionné selon les coordonnées absolues du document lié.
    """
    ids_to_copy = List[ElementId]()
    ids_to_copy.Add(linked_element_id)

    with revit.Transaction("Copier famille in-situ"):
        new_ids = ElementTransformUtils.CopyElements(
            linked_doc,
            ids_to_copy,
            doc,
            Transform.Identity,
            CopyPasteOptions()
        )
    return new_ids


# ---------------------------------------------------------------------------
# Copie standard (CopyElements)
# ---------------------------------------------------------------------------

def copy_standard(linked_doc, linked_element_id, link_transform):
    ids_to_copy = List[ElementId]()
    ids_to_copy.Add(linked_element_id)

    with revit.Transaction("Copier élément depuis maquette liée"):
        new_ids = ElementTransformUtils.CopyElements(
            linked_doc,
            ids_to_copy,
            doc,
            link_transform,
            CopyPasteOptions()
        )
    return new_ids


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def run():
    # 1. Sélection
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Cliquez sur un élément dans une maquette liée (Échap pour annuler)."
        )
    except Exception:
        return

    if not ref:
        return

    # 2. Instance de lien
    link_instance = doc.GetElement(ref.ElementId)
    if not isinstance(link_instance, RevitLinkInstance):
        forms.alert("L'objet sélectionné n'est pas dans une maquette liée.",
                    title="Erreur de sélection")
        return

    # 3. Document lié
    linked_doc = link_instance.GetLinkDocument()
    if not linked_doc:
        forms.alert("Maquette liée inaccessible (non chargée ?).",
                    title="Maquette inaccessible")
        return

    # 4. Élément lié
    linked_element = linked_doc.GetElement(ref.LinkedElementId)
    if not linked_element:
        forms.alert("Impossible de récupérer l'élément dans la maquette liée.",
                    title="Élément introuvable")
        return

    # 5. Lire les phases AVANT la copie
    created_name, demolished_name = read_phases(linked_element, linked_doc)

    # 6. Transformation lien → hôte
    link_transform = link_instance.GetTotalTransform()

    # 7. Copie
    new_ids = None
    method  = None

    if is_in_place(linked_element):
        # Famille in-situ : toujours Identity pour préserver géométrie et éditabilité
        try:
            new_ids = copy_inplace(linked_doc, ref.LinkedElementId)
            method  = "in-situ (éditable)"
        except Exception:
            forms.alert(
                "Erreur lors de la copie de la famille in-situ :\n\n{}".format(
                    traceback.format_exc()),
                title="Erreur"
            )
            return
    else:
        # Élément standard : essai avec link_transform, fallback Identity si échec
        try:
            new_ids = copy_standard(linked_doc, ref.LinkedElementId, link_transform)
            method  = "copie native"
        except Exception:
            # Certains éléments échouent avec link_transform → on retente sans transform
            try:
                new_ids = copy_inplace(linked_doc, ref.LinkedElementId)
                method  = "copie native (Identity)"
            except Exception:
                # CopyElements impossible dans les deux cas → proposer DirectShape
                cat_name = ""
                try:
                    cat_name = " ({})".format(linked_element.Category.Name)
                except Exception:
                    pass
                use_ds = forms.alert(
                    "Impossible de copier cet élément{} via l'API Revit.\n\n"
                    "Voulez-vous extraire la géométrie en DirectShape ?\n"
                    "(non éditable, mais positionné correctement)".format(cat_name),
                    title="Copie impossible",
                    yes=True, no=True
                )
                if not use_ds:
                    return
                new_ids = copy_as_directshape(linked_element, link_transform)
                if not new_ids:
                    forms.alert(
                        "Aucune géométrie solide extraite.",
                        title="Échec DirectShape"
                    )
                    return
                method = "DirectShape (géométrie uniquement)"

    if not new_ids or new_ids.Count == 0:
        forms.alert(
            "Aucun élément copié.\n"
            "Ce type d'élément n'est peut-être pas supporté.",
            title="Aucun élément copié"
        )
        return

    # 8. Appliquer les phases
    try:
        apply_phases(new_ids, created_name, demolished_name)
    except Exception:
        forms.alert(
            "Copie réussie, mais erreur lors de l'application des phases :\n\n{}".format(
                traceback.format_exc()
            ),
            title="Avertissement phases"
        )

    # 9. Résultat
    uidoc.Selection.SetElementIds(new_ids)

    phase_info = "Phase création : {}".format(created_name or "inconnue")
    if demolished_name:
        phase_info += "\nPhase démolition : {}".format(demolished_name)

    forms.alert(
        "{} élément(s) copié(s) — {}.\n\n{}".format(new_ids.Count, method, phase_info),
        title="Copie réussie"
    )


run()
