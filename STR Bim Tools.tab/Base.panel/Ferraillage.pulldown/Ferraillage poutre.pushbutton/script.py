# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Ferraillage poutre"
# =============================================================================
#  v1.0.0 - Poutres droites horizontales rectangulaires : barres inferieures (1 ou
#           2 lits) et superieures ancrees en equerre dans les appuis
#           detectes (poteau, mur, poutre porteuse), etriers fermes en 3
#           zones, barres de peau des poutres hautes.
#           Inspire de RFT-Tools d'Essam Kader (licence MIT).
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
    import os

    from Autodesk.Revit.DB import BuiltInCategory
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
    from Autodesk.Revit.Exceptions import OperationCanceledException

    import str_ferraillage as FER
    import str_ferraillage_elements as ELEM
    import str_ferraillage_revit as FR
    import str_ferraillage_revit_elem as RE
    import str_ferraillage_fenetre as FEN

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document

    _FOOTER = u"v{0} | STR BIM Tools by Tony VARIN".format(SCRIPT_VERSION)

    CATEGORIE = BuiltInCategory.OST_StructuralFraming
    PREFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    class Filtre(ISelectionFilter):
        def AllowElement(self, el):
            return RE.categorie_est(el, CATEGORIE)

        def AllowReference(self, ref, pt):
            return False

    def selection():
        els = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
        els = [e for e in els if RE.categorie_est(e, CATEGORIE)]
        if els:
            return els
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element, Filtre(),
                u"Sélectionne la ou les poutres à ferrailler, puis Terminer")
        except OperationCanceledException:
            return []
        return [doc.GetElement(r.ElementId) for r in refs]

    def fmt(v, dec=0):
        return FER.fmt_nombre(v, dec)

    OUTIL = RE.OUTIL_POUTRE
    LIRE = RE.lire_poutre
    DEFAUTS = ELEM.poutre_defaut()
    PARTITION = u"Poutres"
    ETRIERS = True
    COLONNES = [
        (u"Long. m", lambda i: fmt(i["L"] / 100.0, 2), 65),
        (u"b x h cm", lambda i: u"{0} x {1}".format(fmt(i["b"]), fmt(i["h"])), 80),
        (u"Appuis début / fin", lambda i: i["appuis_txt"], 260),
    ]
    ANCRAGES = [(u"Équerre dans l'appui", "equerre"), (u"Droit", "droit")]
    PEAU = [(u"Auto (h > 70 cm)", "auto"), (u"Oui", "oui"), (u"Non", "non")]
    SECTIONS = [
        (u"Barres longitudinales", [
            {"cle": "n_inf", "libelle": u"Inférieures (nb)", "type": "entier"},
            {"cle": "d_inf", "libelle": u"Ø inférieures", "type": "diam"},
            {"cle": "n_inf2", "libelle": u"2e lit inférieur (nb)", "type": "entier", "aide": u"0 = pas de 2e lit"},
            {"cle": "n_sup", "libelle": u"Supérieures (nb)", "type": "entier"},
            {"cle": "d_sup", "libelle": u"Ø supérieures", "type": "diam"},
            {"cle": "ancrage", "libelle": u"Ancrage", "type": "choix", "choix": ANCRAGES},
            {"cle": "lb", "libelle": u"Ancrage lb (x Ø)", "type": "nombre", "aide": u"Longueur d'ancrage en diamètres (SIA 262)"},
        ]),
        (u"Étriers", [
            {"cle": "d_etr", "libelle": u"Ø étriers", "type": "diam"},
            {"cle": "e_appui", "libelle": u"e près des appuis (cm)", "type": "nombre"},
            {"cle": "e_travee", "libelle": u"e en travée (cm)", "type": "nombre"},
            {"cle": "zone_appui", "libelle": u"Zone d'appui (cm)", "type": "nombre", "aide": u"0 = quart de la portée libre"},
        ]),
        (u"Barres de peau", [
            {"cle": "peau", "libelle": u"Barres de peau", "type": "choix", "choix": PEAU},
            {"cle": "d_peau", "libelle": u"Ø peau", "type": "diam"},
            {"cle": "e_peau", "libelle": u"e max peau (cm)", "type": "nombre"},
        ]),
    ]

    # =========================================================================
    # Main
    # =========================================================================
    elements = selection()
    if elements:
        barres = FR.types_barres(doc)
        if not barres:
            td = TaskDialog(TOOL_NAME)
            td.MainContent = u"Aucun type de barre d'armature dans le projet."
            td.FooterText = _FOOTER
            td.Show()
        else:
            infos = []
            for el in elements:
                try:
                    infos.append(LIRE(el))
                except Exception as ex:
                    infos.append({"id": FR.idval(el.Id), "elem": el, "type": u"?",
                                  "erreur": u"Lecture impossible : {0}".format(ex)})
            FEN.FenetreElements({
                "outil": OUTIL, "titre": TOOL_NAME, "version": SCRIPT_VERSION,
                "doc": doc, "uidoc": uidoc, "infos": infos,
                "existants": RE.armatures_par_hote(doc), "barres": barres,
                "crochets": RE.types_crochets(doc), "colonnes": COLONNES,
                "sections": SECTIONS, "defauts": DEFAUTS, "prefs": PREFS,
                "partition": PARTITION, "etriers": ETRIERS}).ShowDialog()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION),
                _ex)
