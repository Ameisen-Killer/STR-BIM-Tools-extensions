# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Ferraillage semelle"
# =============================================================================
#  v1.0.0 - Semelles isolees : nappe inferieure en U, L alternes ou droite,
#           nappe superieure, ceinture, attentes du poteau pose dessus
#           (reprend sa configuration s'il a ete ferraille) et cadres.
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

    CATEGORIE = BuiltInCategory.OST_StructuralFoundation
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
                u"Sélectionne la ou les semelles isolées à ferrailler, puis Terminer")
        except OperationCanceledException:
            return []
        return [doc.GetElement(r.ElementId) for r in refs]

    def fmt(v, dec=0):
        return FER.fmt_nombre(v, dec)

    OUTIL = RE.OUTIL_SEMELLE
    LIRE = RE.lire_semelle
    DEFAUTS = ELEM.semelle_defaut()
    PARTITION = u"Fondations"
    ETRIERS = True
    COLONNES = [
        (u"a x b x ép. cm", lambda i: u"{0} x {1} x {2}".format(
            fmt(i["a"]), fmt(i["b"]), fmt(i["ep"])), 120),
        (u"Poteau", lambda i: i["poteau_txt"], 230),
    ]
    FORMES = [(u"U (relevés aux 2 bouts)", "U"), (u"L alternés", "L"),
              (u"Droites", "droite")]
    LITS = [(u"Auto (plus grand débord)", "auto"), (u"Barres selon a (X)", "X"),
            (u"Barres selon b (Y)", "Y")]
    SECTIONS = [
        (u"Nappe inférieure", [
            {"cle": "d_x", "libelle": u"Ø selon a (X)", "type": "diam"},
            {"cle": "e_x", "libelle": u"e selon a (cm)", "type": "nombre"},
            {"cle": "d_y", "libelle": u"Ø selon b (Y)", "type": "diam"},
            {"cle": "e_y", "libelle": u"e selon b (cm)", "type": "nombre"},
            {"cle": "forme", "libelle": u"Forme des barres", "type": "choix", "choix": FORMES},
            {"cle": "lit_bas", "libelle": u"Lit du dessous", "type": "choix", "choix": LITS},
        ]),
        (u"Nappe supérieure et ceinture", [
            {"cle": "sup", "libelle": u"Nappe supérieure (droites)", "type": "case"},
            {"cle": "d_sup", "libelle": u"Ø nappe sup.", "type": "diam"},
            {"cle": "e_sup", "libelle": u"e nappe sup. (cm)", "type": "nombre"},
            {"cle": "ceinture", "libelle": u"Cadre de ceinture à mi-hauteur", "type": "case"},
            {"cle": "d_ceint", "libelle": u"Ø ceinture", "type": "diam"},
        ]),
        (u"Attentes du poteau", [
            {"cle": "attentes", "libelle": u"Attentes si un poteau est posé dessus", "type": "case"},
            {"cle": "n_x", "libelle": u"Barres face b (nb)", "type": "entier", "aide": u"Ignoré si le poteau a déjà été ferraillé (sa configuration est reprise)"},
            {"cle": "n_y", "libelle": u"Barres face h (nb)", "type": "entier", "aide": u"Ignoré si le poteau a déjà été ferraillé"},
            {"cle": "d_att", "libelle": u"Ø attentes", "type": "diam", "aide": u"Ignoré si le poteau a déjà été ferraillé"},
            {"cle": "l_att", "libelle": u"Dépassement (cm)", "type": "nombre", "aide": u"Au-dessus de la semelle ; 0 = 50 Ø"},
            {"cle": "pied", "libelle": u"Pied horizontal (cm)", "type": "nombre"},
            {"cle": "c_pot", "libelle": u"Enrobage poteau (cm)", "type": "nombre"},
            {"cle": "d_cadre", "libelle": u"Ø cadres de maintien", "type": "diam"},
            {"cle": "nb_cadres", "libelle": u"Cadres de maintien (nb)", "type": "entier"},
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
