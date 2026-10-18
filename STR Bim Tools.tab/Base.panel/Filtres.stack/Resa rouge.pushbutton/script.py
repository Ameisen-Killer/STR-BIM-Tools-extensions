# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Résa Rouge"
FILTER_NAME    = u"STR_RES_H_CIRC/RECT"
RED            = (255, 0, 10)
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
    import sys
    from Autodesk.Revit.DB import (
        FilteredElementCollector, ParameterFilterElement,
        OverrideGraphicSettings, Transaction
    )
    from Autodesk.Revit.DB import Color as RvtColor

    doc         = __revit__.ActiveUIDocument.Document
    uidoc       = __revit__.ActiveUIDocument
    active_view = uidoc.ActiveView

    if active_view is None or not hasattr(active_view, "GetFilters"):
        td = TaskDialog(TOOL_NAME)
        td.MainContent   = u"La vue active ne supporte pas les filtres de visibilité."
        td.CommonButtons = TaskDialogCommonButtons.Close
        td.Show()
        sys.exit()

    target_filter = None
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements():
        if f.Name == FILTER_NAME:
            target_filter = f
            break

    if target_filter is None:
        td = TaskDialog(TOOL_NAME)
        td.MainContent   = u"Filtre introuvable dans le projet :\n« {} »".format(FILTER_NAME)
        td.CommonButtons = TaskDialogCommonButtons.Close
        td.Show()
        sys.exit()

    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(RvtColor(RED[0], RED[1], RED[2]))
    try:
        ogs.SetSurfaceForegroundPatternVisible(False)
    except Exception:
        pass
    try:
        ogs.SetSurfaceBackgroundPatternVisible(False)
    except Exception:
        pass

    existing_ids    = set(fid.IntegerValue for fid in active_view.GetFilters())
    already_in_view = target_filter.Id.IntegerValue in existing_ids

    t = Transaction(doc, u"STR - Filtre Démol {}".format(FILTER_NAME))
    t.Start()
    try:
        if not already_in_view:
            active_view.AddFilter(target_filter.Id)
            active_view.SetFilterVisibility(target_filter.Id, True)
        active_view.SetFilterOverrides(target_filter.Id, ogs)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        raise ex

    action = u"ajouté et " if not already_in_view else u""
    td = TaskDialog(TOOL_NAME)
    td.MainContent = (
        u"Filtre « {} » {}appliqué sur la vue « {} ».\n\n"
        u"  • Lignes projection  →  rouge RVB({},{},{})\n"
        u"  • Motifs surface premier plan  →  masqué\n"
        u"  • Motifs surface deuxième plan →  masqué"
    ).format(FILTER_NAME, action, active_view.Name, *RED)
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.Show()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
