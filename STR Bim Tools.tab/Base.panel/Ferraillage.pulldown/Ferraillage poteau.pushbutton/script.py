# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Ferraillage poteau"
# =============================================================================
#  v1.0.0 - Poteaux rectangulaires verticaux : barres longitudinales par face,
#           attentes en tete si un poteau ou un mur est detecte au-dessus,
#           cadres exterieur et interieurs en 3 zones.
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

    CATEGORIE = BuiltInCategory.OST_StructuralColumns
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
                u"Sélectionne le ou les poteaux à ferrailler, puis Terminer")
        except OperationCanceledException:
            return []
        return [doc.GetElement(r.ElementId) for r in refs]

    def fmt(v, dec=0):
        return FER.fmt_nombre(v, dec)

    OUTIL = RE.OUTIL_POTEAU
    LIRE = RE.lire_poteau
    DEFAUTS = ELEM.poteau_defaut()
    PARTITION = u"Poteaux"
    ETRIERS = True
    COLONNES = [
        (u"b x h cm", lambda i: u"{0} x {1}".format(fmt(i["b"]), fmt(i["h"])), 80),
        (u"Haut. m", lambda i: fmt((i["z_haut"] - i["z_bas"]) / 100.0, 2), 65),
        (u"Z bas m", lambda i: fmt(i["z_bas"] / 100.0, 3), 70),
        (u"Au-dessus", lambda i: u"Oui ({0})".format(i["dessus_id"])
         if i["dessus"] else u"Non", 100),
    ]
    ATTENTES = [(u"Auto : si un élément est au-dessus", ELEM.ATTENTE_AUTO),
                (u"Toujours", ELEM.ATTENTE_TOUJOURS), (u"Jamais", ELEM.ATTENTE_JAMAIS)]
    SECTIONS = [
        (u"Barres longitudinales", [
            {"cle": "n_x", "libelle": u"Barres face b (nb)", "type": "entier", "aide": u"Coins compris, le long de b"},
            {"cle": "n_y", "libelle": u"Barres face h (nb)", "type": "entier", "aide": u"Coins compris, le long de h"},
            {"cle": "d_long", "libelle": u"Ø longitudinales", "type": "diam"},
            {"cle": "attente", "libelle": u"Attentes en tête", "type": "choix", "choix": ATTENTES},
            {"cle": "l_att", "libelle": u"Recouvrement (cm)", "type": "nombre", "aide": u"0 = 50 Ø arrondi à 5 cm"},
            {"cle": "att_pied", "libelle": u"Attente en pied (cm)", "type": "nombre", "aide": u"0 = barres arrêtées à l'enrobage (attentes déjà dans la semelle)"},
        ]),
        (u"Cadres", [
            {"cle": "d_etr", "libelle": u"Ø cadres", "type": "diam"},
            {"cle": "e_zone", "libelle": u"e aux extrémités (cm)", "type": "nombre"},
            {"cle": "e_courant", "libelle": u"e courant (cm)", "type": "nombre"},
            {"cle": "zone", "libelle": u"Zone d'extrémité (cm)", "type": "nombre", "aide": u"0 = max(H/6, plus grande dimension, 50 cm)"},
            {"cle": "cadre_int", "libelle": u"Cadres intérieurs (4 barres ou plus par face)", "type": "case"},
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
