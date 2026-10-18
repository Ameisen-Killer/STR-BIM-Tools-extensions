# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Demi-teinte"
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
    from Autodesk.Revit.DB import Transaction, TransactionStatus, ElementId

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document

    def main():
        view = doc.ActiveView

        sel_ids = list(uidoc.Selection.GetElementIds())
        if not sel_ids:
            _show_info(TOOL_NAME, u"Aucun element selectionne.\n\n"
                                   u"Selectionnez un ou plusieurs elements dans la vue "
                                   u"avant de lancer l'outil.")
            return

        # Element(s) non supportes par les surcharges graphiques de vue (ex. elements
        # de type/categorie non graphique) -> on les ignore silencieusement.
        valid_ids = []
        for eid in sel_ids:
            try:
                view.GetElementOverrides(eid)
                valid_ids.append(eid)
            except Exception:
                pass

        if not valid_ids:
            _show_info(TOOL_NAME, u"Aucun des elements selectionnes ne supporte "
                                   u"les surcharges graphiques de vue.")
            return

        # Bascule individuelle : chaque element passe dans l'etat oppose
        # au sien (demi-teinte -> normal, normal -> demi-teinte).
        t = Transaction(doc, u"STR - Basculer demi-teinte")
        try:
            t.Start()
            for eid in valid_ids:
                ovr = view.GetElementOverrides(eid)
                ovr.SetHalftone(not ovr.Halftone)
                view.SetElementOverrides(eid, ovr)
            if t.GetStatus() == TransactionStatus.Started:
                t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise

        uidoc.Selection.SetElementIds(List[ElementId]())

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
