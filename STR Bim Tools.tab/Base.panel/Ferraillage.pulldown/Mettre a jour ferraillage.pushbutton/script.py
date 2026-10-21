# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Mettre à jour ferraillage"
# =============================================================================
#  v1.0.0 - Recalcule le ferraillage STR des murs (configuration enregistree
#           dans chaque mur par "Ferraillage mur") apres une modification :
#           geometrie, mur du dessus ajoute ou supprime...
#  v1.1.0 - Poutres, poteaux et semelles ferrailles par les outils du menu
#           aussi recalcules.
# =============================================================================

import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommonButtons,
                               TaskDialogResult)


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + str(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


try:
    from Autodesk.Revit.DB import (FilteredElementCollector, Wall, View3D,
                                   Transaction, TransactionStatus)

    import str_ferraillage_revit as FR
    import str_ferraillage_revit_elem as RE

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document

    _FOOTER = u"v{0} | STR BIM Tools by Tony VARIN".format(SCRIPT_VERSION)

    def dialogue(texte, detail=u"", boutons=TaskDialogCommonButtons.Close):
        td = TaskDialog(TOOL_NAME)
        td.MainInstruction = TOOL_NAME
        td.MainContent = texte
        if detail:
            td.ExpandedContent = detail
        td.FooterText = _FOOTER
        td.CommonButtons = boutons
        return td.Show()

    def a_traiter():
        """(murs, [(element, outil, config)], depuis la selection)."""
        sel = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
        if sel:
            murs = [m for m in sel if isinstance(m, Wall) and FR.config_du_mur(m)]
            autres = []
            for el in sel:
                outil, cfg = RE.donnees_element(el)
                if outil:
                    autres.append((el, outil, cfg))
            return murs, autres, True
        murs = [w for w in FilteredElementCollector(doc).OfClass(Wall)
                if FR.config_du_mur(w)]
        return murs, RE.elements_ferrailles(doc), False

    murs, autres, depuis_selection = a_traiter()
    if not murs and not autres:
        dialogue(u"Aucun élément ferraillé avec les outils du menu Ferraillage "
                 + (u"dans la sélection." if depuis_selection
                    else u"dans le projet."))
    else:
        rep = TaskDialogResult.Yes
        if not depuis_selection:
            rep = dialogue(u"Rien n'est sélectionné : mettre à jour le "
                           u"ferraillage des {0} élément(s) ferraillés du projet ?"
                           .format(len(murs) + len(autres)), boutons=
                           TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)
        if rep == TaskDialogResult.Yes:
            barres = FR.types_barres(doc)
            tous = FR.lire_tous_murs(doc)
            vue3d = doc.ActiveView if isinstance(doc.ActiveView, View3D) else None
            echecs, nb_jeux, nb_murs = [], 0, 0
            t = Transaction(doc, u"STR - Mise à jour ferraillage")
            try:
                t.Start()
                for w in murs:
                    info = FR.preparer_mur(FR.lire_mur(w), tous)
                    if info.get("erreur"):
                        echecs.append(u"Mur {0} : {1}".format(info["id"], info["erreur"]))
                        continue
                    ids, _, err, _ = FR.ferrailler_mur(
                        doc, info, FR.config_du_mur(w), barres, vue3d)
                    nb_jeux += len(ids)
                    nb_murs += 1
                    echecs.extend(u"Mur {0} : {1}".format(info["id"], m) for m in err)
                for el, outil, cfg in autres:
                    info = RE.LECTEURS[outil](el)
                    if info.get("erreur"):
                        echecs.append(u"{0} : {1}".format(info["id"], info["erreur"]))
                        continue
                    ids, _, err = RE.ferrailler(doc, info, cfg, barres, vue3d)
                    nb_jeux += len(ids)
                    nb_murs += 1
                    echecs.extend(u"{0} : {1}".format(info["id"], m) for m in err)
                if t.GetStatus() == TransactionStatus.Started:
                    t.Commit()
            except Exception:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
                raise
            dialogue(u"{0} élément(s) mis à jour, {1} jeux de barres recréés."
                     .format(nb_murs, nb_jeux)
                     + (u"\n{0} avertissement(s).".format(len(echecs)) if echecs else u""),
                     u"\n".join(echecs))

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
