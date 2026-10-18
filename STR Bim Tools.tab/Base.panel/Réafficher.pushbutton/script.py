# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Reafficher"
# =============================================================================

# Hors filet - strict minimum pour afficher les erreurs fatales
import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogIcon


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


def _show_info(title, message):
    td = TaskDialog(title)
    td.MainContent   = message
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.MainIcon      = TaskDialogIcon.TaskDialogIconInformation
    td.Show()


try:
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import (FilteredElementCollector, Transaction,
                                   TransactionStatus, ElementId)

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document

    def main():
        view = doc.ActiveView

        # Pas de selection requise : on reaffiche tous les elements masques
        # individuellement (View.HideElements) dans la vue active. Un
        # element hors-categorie/type non graphique est ignore silencieusement.
        hidden_ids = List[ElementId]()
        for el in FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                if el.IsHidden(view):
                    hidden_ids.Add(el.Id)
            except Exception:
                pass

        if hidden_ids.Count == 0:
            _show_info(TOOL_NAME, u"Aucun element masque dans cette vue.")
            return

        t = Transaction(doc, u"STR - Reafficher element(s)")
        try:
            t.Start()
            view.UnhideElements(hidden_ids)
            if t.GetStatus() == TransactionStatus.Started:
                t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
