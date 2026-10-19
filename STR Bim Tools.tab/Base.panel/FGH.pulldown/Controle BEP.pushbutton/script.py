# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.7.1"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"FGH - Contrôle BEP"
# NB : toutes les valeurs imposees par le BEP (niveaux, zones, attributs,
# coordonnees, jeu de caracteres...) sont dans fgh_bep_config.json a la racine
# de l'extension. Les regles elles-memes sont dans lib/fgh_bep_regles.py.
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
    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import fgh_bep_regles
    import fgh_bep_dashboard
    # Fenetre de progression generique (lib/str_progression.py, copie publique
    # de can241_progress : l'outil marche sans le module prive CAN 241).
    import str_progression

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app   = __revit__.Application
    _FOOTER = u"v{0} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    def analyse():
        prog = str_progression.Progression(
            u"Contrôle de conformité BEP...", _FOOTER, 0)
        prog.demarrer(texte=u"Lecture de la maquette...")
        try:
            def on_progress(n, total=0, libelle=u""):
                if total and total != prog.total:
                    prog.sous_total(total)
                prog.avancer(n, u"{0}/{1}  {2}".format(n, total, libelle))
            return fgh_bep_regles.analyser(doc, app, progress=on_progress)
        finally:
            prog.fin()

    def main():
        # Le dashboard rend True quand la configuration a change et que
        # l'utilisateur veut voir le resultat mis a jour : on repart d'une
        # analyse complete, les regles relisant le referentiel a chaque appel.
        while True:
            resultat = analyse()
            if not fgh_bep_dashboard.afficher(uidoc, resultat,
                                              SCRIPT_VERSION, TOOL_NAME):
                break

    main()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur de chargement".format(TOOL_NAME,
                                                         SCRIPT_VERSION), _ex)
