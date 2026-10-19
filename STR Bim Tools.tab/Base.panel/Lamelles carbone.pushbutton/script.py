# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Quantification Lamelles carbone"
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
    import os, io, re, json, datetime

    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase");           clr.AddReference("System.Windows.Forms")
    import System, System.Diagnostics
    import System.Windows.Forms as WinForms
    import System.Windows as SW
    from System.Windows import (Window, GridLength, GridUnitType, Thickness,
                                MessageBox, MessageBoxButton, MessageBoxImage,
                                MessageBoxResult, Clipboard,
                                HorizontalAlignment, VerticalAlignment,
                                WindowStartupLocation, ResizeMode,
                                FontWeights, TextWrapping)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Button,
                                         Border, DataGridTextColumn, RowDefinition,
                                         DataGridLength, DataGridRow, Orientation,
                                         DataGridHeadersVisibility,
                                         DataGridGridLinesVisibility,
                                         DataGridSelectionMode,
                                         TextBox, ComboBox, ComboBoxItem,
                                         TabControl, TabItem, ScrollBarVisibility)
    from System.Windows.Controls.Primitives import DataGridColumnHeader
    from System.Windows.Media import SolidColorBrush, Color, FontFamily
    from System.Windows.Data import Binding
    from System.Collections.ObjectModel import ObservableCollection
    from System.Collections.Generic import List as NetList

    from Autodesk.Revit.DB import (FilteredElementCollector, FamilyInstance, Level,
                                   BuiltInCategory, BuiltInParameter, Element,
                                   ElementId, StorageType, UnitUtils, UnitTypeId,
                                   LocationPoint)
    try:
        from Autodesk.Revit.DB import SpecTypeId
        HAS_SPEC = True
    except ImportError:
        HAS_SPEC = False

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app   = __revit__.Application

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")
    _FOOTER     = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # Parametrage metier
    # =========================================================================
    FAMILLE_CIBLE  = u"STR_Lamelle_Collée_S&P"
    MOT_CLE_REPLI  = u"lamelle"      # si la famille exacte est introuvable
    SEUIL_GROS_MM  = 90.0            # largeur >= 9 cm -> gros ancrage

    # Nom du type : ...<largeur sur 3 chiffres><epaisseur sur 2 chiffres>
    # Ex. LA15012014 -> serie "LA150", largeur 120 mm, epaisseur 14 -> 1.4 mm
    # Un separateur entre largeur et epaisseur est tolere (LA150_120_14).
    RE_TYPE = re.compile(r"^(.*?)(\d{3})[\s_.\-]*(\d{2})\s*$")

    P_LONGUEUR    = u"AB. Longueur"
    P_ANC         = u"AB. Ancrage {}"
    P_ANC_LARGE   = u"AB. Ancrage Large {}"
    P_ANC_SMALL   = u"AB. Ancrage Small {}"
    COTES         = [(u"gauche", u"Gauche"), (u"droite", u"Droite")]

    GROS  = u"Gros"
    PETIT = u"Petit"
    AUCUN = u"—"
    DASH  = u"—"

    # =========================================================================
    # Helpers UI
    # =========================================================================
    def hex_brush(h):
        h = h.lstrip("#")
        return SolidColorBrush(Color.FromRgb(
            int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    def rgb(r, g, b):
        return SolidColorBrush(Color.FromRgb(r, g, b))

    def _rd(h):
        rd = RowDefinition()
        rd.Height = (GridLength(1, GridUnitType.Star) if h == "*" else GridLength.Auto)
        return rd

    def _footer_btn(text, color, width, handler):
        b = Button()
        b.Content = text; b.Width = width; b.Height = 28
        b.Background = hex_brush(color); b.Foreground = hex_brush("#FFFFFF")
        b.FontWeight = FontWeights.SemiBold; b.BorderThickness = Thickness(0)
        b.Click += handler
        return b

    def _make_footer():
        brd = Border()
        brd.BorderThickness = Thickness(0, 1, 0, 0)
        brd.BorderBrush = hex_brush("#C0D0E0")
        brd.Background  = hex_brush("#F5F5F5")
        brd.Padding = Thickness(0, 6, 0, 6)
        g = Grid()
        lbl = TextBlock()
        lbl.Text = _FOOTER
        lbl.FontSize = 10; lbl.Foreground = hex_brush("#888888")
        lbl.VerticalAlignment = VerticalAlignment.Center
        lbl.Margin = Thickness(10, 0, 0, 0)
        g.Children.Add(lbl)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Right
        sp.Margin = Thickness(0, 0, 10, 0)
        brd.Child = g
        return brd, sp, g

    def _label(txt, taille=11, gras=False, couleur="#333333", marge=None):
        tb = TextBlock()
        tb.Text = txt
        tb.FontSize = taille
        if gras:
            tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = hex_brush(couleur)
        tb.VerticalAlignment = VerticalAlignment.Center
        if marge is not None:
            tb.Margin = marge
        return tb

    def _combo(largeur):
        cb = ComboBox()
        cb.Width = largeur; cb.Height = 24; cb.FontSize = 11
        cb.VerticalContentAlignment = VerticalAlignment.Center
        cb.Margin = Thickness(0, 0, 12, 0)
        return cb

    def _remplir_combo(cb, libelles):
        cb.Items.Clear()
        for lib in libelles:
            it = ComboBoxItem()
            it.Content = lib
            cb.Items.Add(it)
        if cb.Items.Count:
            cb.SelectedIndex = 0

    def _valeur_combo(cb):
        it = cb.SelectedItem
        return it.Content if it is not None else None

    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(data):
        try:
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # =========================================================================
    # Helpers texte / nombres
    # =========================================================================
    _ACCENTS = {u"é": u"e", u"è": u"e", u"ê": u"e", u"ë": u"e",
                u"à": u"a", u"â": u"a", u"ä": u"a",
                u"î": u"i", u"ï": u"i",
                u"ô": u"o", u"ö": u"o",
                u"û": u"u", u"ù": u"u", u"ü": u"u",
                u"ç": u"c"}

    def _sans_accent(s):
        s = s or u""
        for a, b in _ACCENTS.items():
            s = s.replace(a, b)
        return s

    def _cle(s):
        """Cle de comparaison : minuscules, sans accent, sans ponctuation ni espace."""
        s = _sans_accent((s or u"").lower())
        return u"".join([c for c in s if c.isalnum()])

    def _norm_txt(s):
        """Normalisation souple pour le filtre texte de la fenetre."""
        return _sans_accent((s or u"").lower())

    CLE_FAMILLE = _cle(FAMILLE_CIBLE)
    CLE_REPLI   = _cle(MOT_CLE_REPLI)

    def fmt_num(val, dec=1):
        """Formatage sans unicode() : IronPython 3.4 (Revit 2025) ne l'expose plus."""
        if val is None:
            return DASH
        if dec <= 0:
            return u"{:.0f}".format(float(val))
        if dec == 1:
            return u"{:.1f}".format(float(val))
        return u"{:.2f}".format(float(val))

    def _nom_fichier_sur(nom):
        return u"".join([c if (c.isalnum() or c in u"-_ ") else u"_" for c in (nom or u"")]).strip()

    # =========================================================================
    # Lecture des parametres Revit
    # =========================================================================
    def _nom_element(el):
        """
        Nom d'un element, ElementType compris.

        PIEGE VERIFIE SUR CE MOTEUR : `.Name` sur un ElementType (donc sur un
        FamilySymbol) leve AttributeError — l'API Revit redeclare la propriete
        en `new` sur ElementType et la resolution de membre IronPython echoue.
        Sur une occurrence et sur Family, `.Name` repond normalement.
        Le repli passe par l'accesseur .NET de Element.Name.
        """
        if el is None:
            return u""
        try:
            return el.Name or u""
        except Exception:
            pass
        try:
            return Element.Name.GetValue(el) or u""
        except Exception:
            pass
        for nom_bip in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
            bip = getattr(BuiltInParameter, nom_bip, None)
            if bip is None:
                continue
            try:
                p = el.get_Parameter(bip)
                if p:
                    v = p.AsString() or u""
                    if v:
                        return v
            except Exception:
                pass
        return u""

    def _params_map(el):
        """{cle normalisee: Parameter} pour l'occurrence puis le type (repli)."""
        res = {}
        sources = []
        try:
            et = doc.GetElement(el.GetTypeId())
            if et is not None:
                sources.append(et)          # d'abord le type : ecrase par l'occurrence
        except Exception:
            pass
        sources.append(el)
        for src in sources:
            try:
                for p in src.Parameters:
                    try:
                        res[_cle(p.Definition.Name)] = p
                    except Exception:
                        pass
            except Exception:
                pass
        return res

    def _est_longueur(p):
        """True si le parametre porte une unite de longueur (donc valeur en pieds)."""
        if HAS_SPEC:
            try:
                return p.Definition.GetDataType() == SpecTypeId.Length
            except Exception:
                pass
        try:
            return p.GetUnitTypeId() is not None
        except Exception:
            return False

    def lire_longueur_m(p):
        """Longueur en metres. Un nombre nu (sans unite) est interprete en cm."""
        if p is None:
            return None
        try:
            if p.StorageType == StorageType.Double:
                d = p.AsDouble()
                if _est_longueur(p):
                    return float(UnitUtils.ConvertFromInternalUnits(d, UnitTypeId.Meters))
                return float(d) / 100.0
            if p.StorageType == StorageType.Integer:
                return float(p.AsInteger()) / 100.0
        except Exception:
            pass
        return None

    def lire_bool(p):
        """True / False, ou None si le parametre est absent ou non renseigne."""
        if p is None:
            return None
        try:
            if p.StorageType == StorageType.Integer:
                return p.AsInteger() != 0
            if p.StorageType == StorageType.Double:
                return p.AsDouble() != 0.0
            if p.StorageType == StorageType.String:
                v = (p.AsString() or u"").strip().lower()
                if v in (u"1", u"oui", u"yes", u"true", u"vrai"):
                    return True
                if v in (u"0", u"non", u"no", u"false", u"faux"):
                    return False
        except Exception:
            pass
        return None

    # =========================================================================
    # Niveaux
    # =========================================================================
    def _charger_niveaux():
        lst = []
        try:
            for lv in FilteredElementCollector(doc).OfClass(Level).ToElements():
                try:
                    lst.append((lv.Elevation, _nom_element(lv)))
                except Exception:
                    pass
        except Exception:
            pass
        lst.sort()
        return lst

    NIVEAUX = _charger_niveaux()
    ELEV_PAR_NOM = {}
    for _e, _n in NIVEAUX:
        ELEV_PAR_NOM[_n] = _e

    _BIP_NIVEAU = ["SCHEDULE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM",
                   "INSTANCE_REFERENCE_LEVEL_PARAM", "FAMILY_BASE_LEVEL_PARAM",
                   "LEVEL_PARAM"]

    def _niveau_par_parametre(el):
        for nom_bip in _BIP_NIVEAU:
            bip = getattr(BuiltInParameter, nom_bip, None)
            if bip is None:
                continue
            try:
                p = el.get_Parameter(bip)
                if p and p.AsElementId() != ElementId.InvalidElementId:
                    lv = doc.GetElement(p.AsElementId())
                    if lv is not None:
                        return _nom_element(lv)
            except Exception:
                pass
        try:
            lid = el.LevelId
            if lid is not None and lid != ElementId.InvalidElementId:
                lv = doc.GetElement(lid)
                if lv is not None:
                    return _nom_element(lv)
        except Exception:
            pass
        return None

    def _z_element(el):
        try:
            loc = el.Location
            if isinstance(loc, LocationPoint) and loc.Point is not None:
                return loc.Point.Z
        except Exception:
            pass
        try:
            bb = el.get_BoundingBox(None)
            if bb is not None:
                return (bb.Min.Z + bb.Max.Z) / 2.0
        except Exception:
            pass
        return None

    def _niveau_par_altitude(z_ft):
        if z_ft is None or not NIVEAUX:
            return None
        tol = 0.05                         # ~15 mm
        choisi = None
        for elev, nom in NIVEAUX:
            if elev <= z_ft + tol:
                choisi = nom
            else:
                break
        return choisi or NIVEAUX[0][1]

    def get_niveau(el):
        """(nom_niveau, origine) — parametre, hote, ou altitude."""
        nom = _niveau_par_parametre(el)
        if nom:
            return nom, u"paramètre"
        try:
            hote = el.Host
            if hote is not None:
                nom = _niveau_par_parametre(hote)
                if nom:
                    return nom, u"hôte"
        except Exception:
            pass
        nom = _niveau_par_altitude(_z_element(el))
        if nom:
            return nom, u"altitude"
        return DASH, u"introuvable"

    # =========================================================================
    # Decodage du nom de type
    # =========================================================================
    def parse_type(nom):
        """(serie, largeur_mm, epaisseur_mm) — largeur/epaisseur None si illisible."""
        m = RE_TYPE.match((nom or u"").strip())
        if not m:
            return (nom or DASH), None, None
        serie = m.group(1).strip(u" _-.")
        return (serie or DASH), float(m.group(2)), float(m.group(3)) / 10.0

    # =========================================================================
    # Modele de donnees
    # =========================================================================
    class Lamelle(object):
        def __init__(self, el):
            self.element_id  = el.Id.IntegerValue
            self.famille     = u""
            self.type_name   = u""
            self.serie       = DASH
            self.largeur_mm  = None
            self.epaisseur   = None
            self.longueur_m  = None
            self.niveau      = DASH
            self.niveau_src  = u""
            self.anc         = {u"gauche": AUCUN, u"droite": AUCUN}
            self.anc_src     = {u"gauche": u"", u"droite": u""}
            self.remarques   = []

        @property
        def nb_gros(self):
            return len([1 for c in self.anc.values() if c == GROS])

        @property
        def nb_petits(self):
            return len([1 for c in self.anc.values() if c == PETIT])

        @property
        def nb_ancrages(self):
            return self.nb_gros + self.nb_petits

        @property
        def remarque(self):
            return u" ; ".join(self.remarques)

    class Groupe(object):
        def __init__(self, lam):
            self.type_name  = lam.type_name
            self.serie      = lam.serie
            self.largeur_mm = lam.largeur_mm
            self.epaisseur  = lam.epaisseur
            self.niveau     = lam.niveau
            self.nb         = 0
            self.longueur   = 0.0
            self.gros       = 0
            self.petits     = 0
            self.ids        = []

        def ajouter(self, lam):
            self.nb += 1
            self.longueur += (lam.longueur_m or 0.0)
            self.gros     += lam.nb_gros
            self.petits   += lam.nb_petits
            self.ids.append(lam.element_id)

        @property
        def nb_ancrages(self):
            return self.gros + self.petits

    # =========================================================================
    # Analyse
    # =========================================================================
    def _taille_ancrage(pmap, cote, largeur_mm, lam):
        """Taille de l'ancrage d'un cote : parametres de la famille, repli largeur."""
        present = lire_bool(pmap.get(_cle(P_ANC.format(cote))))
        if present is None:
            lam.remarques.append(
                u"paramètre \"{}\" introuvable : ancrage compté absent".format(
                    P_ANC.format(cote)))
            return AUCUN, u""
        if present is False:
            return AUCUN, u""
        large = lire_bool(pmap.get(_cle(P_ANC_LARGE.format(cote))))
        small = lire_bool(pmap.get(_cle(P_ANC_SMALL.format(cote))))
        if large is True and small is not True:
            return GROS, u"famille"
        if small is True and large is not True:
            return PETIT, u"famille"
        if large is True and small is True:
            lam.remarques.append(u"ancrage {} : Small et Large coches".format(cote))
        elif large is None and small is None:
            lam.remarques.append(u"ancrage {} : paramètres Small/Large absents".format(cote))
        else:
            lam.remarques.append(u"ancrage {} : taille non renseignée".format(cote))
        if largeur_mm is None:
            lam.remarques.append(u"taille d'ancrage {} indéterminée".format(cote))
            return AUCUN, u"indéterminé"
        return (GROS if largeur_mm >= SEUIL_GROS_MM else PETIT), u"largeur"

    def analyser(el, nom_famille, nom_type):
        lam = Lamelle(el)
        lam.famille   = nom_famille
        lam.type_name = nom_type
        lam.serie, lam.largeur_mm, lam.epaisseur = parse_type(nom_type)
        if lam.largeur_mm is None:
            lam.remarques.append(u"type illisible : largeur / épaisseur non décodées")

        pmap = _params_map(el)

        lam.longueur_m = lire_longueur_m(pmap.get(_cle(P_LONGUEUR)))
        if lam.longueur_m is None:
            lam.remarques.append(u"paramètre \"{}\" introuvable".format(P_LONGUEUR))
        elif lam.longueur_m <= 0:
            lam.remarques.append(u"longueur nulle")

        for cote, _lib in COTES:
            taille, src = _taille_ancrage(pmap, cote, lam.largeur_mm, lam)
            lam.anc[cote]     = taille
            lam.anc_src[cote] = src

        lam.niveau, lam.niveau_src = get_niveau(el)
        return lam

    def _noms_famille_type(el):
        """
        (famille, type, origine de la lecture).

        Nom de famille et nom de type sont lus SEPAREMENT, chacun dans son
        propre try. Les regrouper est le bug qui a fait echouer les 26 956
        elements du modele : `.Name` sur un ElementType leve AttributeError
        (voir _nom_element), l'exception sortait du bloc avant la lecture du
        nom de famille, pourtant parfaitement accessible.
        """
        fam, orig = u"", u""
        try:
            et = doc.GetElement(el.GetTypeId())
        except Exception:
            et = None

        # --- nom de famille : trois routes independantes ---------------------
        if et is not None:
            try:
                fam = getattr(et, "FamilyName", u"") or u""
                if fam:
                    orig = u"ElementType.FamilyName"
            except Exception:
                pass
        if not fam:
            try:
                sym = el.Symbol
                if sym is not None and sym.Family is not None:
                    fam = sym.Family.Name or u""
                    if fam:
                        orig = u"Symbol.Family.Name"
            except Exception:
                pass
        if not fam:
            try:
                p = el.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if p:
                    fam = p.AsString() or u""
                    if fam:
                        orig = u"ALL_MODEL_FAMILY_NAME"
            except Exception:
                pass

        # --- nom de type -----------------------------------------------------
        typ = _nom_element(et) or _nom_element(el)

        return fam, typ, (orig or u"introuvable")

    def _candidats():
        """
        Occurrences a examiner. Deux collecteurs cumules et dedoublonnes :
        les FamilyInstance du modele, et la categorie Assemblages structurels
        (dont les elements ne sont pas toujours des FamilyInstance).
        """
        vus, res = set(), []
        for collecteur in (
            lambda: FilteredElementCollector(doc).OfClass(FamilyInstance)
                    .WhereElementIsNotElementType().ToElements(),
            lambda: FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_StructConnections)
                    .WhereElementIsNotElementType().ToElements(),
        ):
            try:
                lot = collecteur()
            except Exception:
                continue
            for el in lot:
                try:
                    eid = el.Id.IntegerValue
                except Exception:
                    continue
                if eid in vus:
                    continue
                vus.add(eid)
                res.append(el)
        return res

    def scanner():
        """(liste de Lamelle, mode de recherche, nb occurrences balayees)."""
        exactes, replis = [], []
        nb_inst = 0
        inventaire, sans_nom = {}, []
        for el in _candidats():
            nb_inst += 1
            fam, typ, _orig = _noms_famille_type(el)
            if not fam:
                if len(sans_nom) < 20:
                    sans_nom.append(el)
                continue
            inventaire[fam] = inventaire.get(fam, 0) + 1
            k = _cle(fam)
            if k == CLE_FAMILLE:
                exactes.append((el, fam, typ))
            elif CLE_REPLI in k:
                replis.append((el, fam, typ))
        STATE["inventaire"] = inventaire
        STATE["sans_nom"]   = sans_nom

        if exactes:
            retenus, mode = exactes, u"famille exacte"
        elif replis:
            retenus, mode = replis, u"repli sur le mot-clé \"{}\"".format(MOT_CLE_REPLI)
        else:
            retenus, mode = [], u"aucune correspondance"

        lamelles = []
        for el, fam, typ in retenus:
            try:
                lamelles.append(analyser(el, fam, typ))
            except Exception:
                pass
        lamelles.sort(key=lambda x: (x.type_name, -ELEV_PAR_NOM.get(x.niveau, -1e9),
                                     x.element_id))
        return lamelles, mode, nb_inst

    def grouper(lamelles):
        index, ordre = {}, []
        for lam in lamelles:
            cle = (lam.type_name, lam.niveau)
            g = index.get(cle)
            if g is None:
                g = Groupe(lam)
                index[cle] = g
                ordre.append(g)
            g.ajouter(lam)
        ordre.sort(key=lambda g: (g.type_name, -ELEV_PAR_NOM.get(g.niveau, -1e9)))
        return ordre

    def totaux(lamelles):
        nb  = len(lamelles)
        lg  = sum([(l.longueur_m or 0.0) for l in lamelles])
        gr  = sum([l.nb_gros   for l in lamelles])
        pt  = sum([l.nb_petits for l in lamelles])
        return nb, float(lg), gr, pt

    # =========================================================================
    # Etat
    # =========================================================================
    STATE = {
        "lamelles":   [],    # toutes
        "filtrees":   [],    # apres filtres
        "groupes":    [],    # groupes des filtrees
        "mode":       u"",
        "nb_inst":    0,
        "inventaire": {},    # nom de famille -> nb d'occurrences
        "sans_nom":   [],    # elements dont le nom de famille reste illisible
    }

    # =========================================================================
    # Lignes DataGrid
    # =========================================================================
    BG_WHITE = rgb(255, 255, 255)
    BG_ALT   = rgb(232, 240, 250)
    BG_WARN  = rgb(255, 235, 200)
    FG_DARK  = rgb(30, 30, 30)
    W_NORMAL = FontWeights.Normal
    W_BOLD   = FontWeights.Bold

    class LigneSynthese(object):
        def __init__(self, g, idx):
            self.ids       = g.ids
            self.Num       = u"{}".format(idx)
            self.Type      = g.type_name
            self.Serie     = g.serie
            self.Largeur   = fmt_num(g.largeur_mm, 0)
            self.Ep        = fmt_num(g.epaisseur, 1)
            self.Niveau    = g.niveau
            self.Nb        = u"{}".format(g.nb)
            self.Longueur  = fmt_num(g.longueur, 2)
            self.Gros      = u"{}".format(g.gros)
            self.Petits    = u"{}".format(g.petits)
            self.Ancrages  = u"{}".format(g.nb_ancrages)
            self.LargeurN  = g.largeur_mm if g.largeur_mm is not None else -1.0
            self.EpN       = g.epaisseur  if g.epaisseur  is not None else -1.0
            self.NivN      = ELEV_PAR_NOM.get(g.niveau, -1e9)
            self.NbN       = g.nb
            self.LongueurN = g.longueur
            self.GrosN     = g.gros
            self.PetitsN   = g.petits
            self.AncragesN = g.nb_ancrages
            suspect        = (g.largeur_mm is None or g.longueur <= 0)
            self.RowBg     = BG_WARN if suspect else (BG_WHITE if idx % 2 == 1 else BG_ALT)
            self.RowFg     = FG_DARK
            self.RowWeight = W_BOLD if suspect else W_NORMAL

    class LigneDetail(object):
        def __init__(self, lam, idx):
            self.ids       = [lam.element_id]
            self.Id        = u"{}".format(lam.element_id)
            self.Type      = lam.type_name
            self.Largeur   = fmt_num(lam.largeur_mm, 0)
            self.Ep        = fmt_num(lam.epaisseur, 1)
            self.Longueur  = fmt_num(lam.longueur_m, 2)
            self.Niveau    = lam.niveau
            self.AncG      = lam.anc[u"gauche"]
            self.AncD      = lam.anc[u"droite"]
            self.NbAnc     = u"{}".format(lam.nb_ancrages)
            self.Remarque  = lam.remarque or u""
            self.IdN       = lam.element_id
            self.LargeurN  = lam.largeur_mm if lam.largeur_mm is not None else -1.0
            self.EpN       = lam.epaisseur  if lam.epaisseur  is not None else -1.0
            self.LongueurN = lam.longueur_m if lam.longueur_m is not None else -1.0
            self.NivN      = ELEV_PAR_NOM.get(lam.niveau, -1e9)
            self.NbAncN    = lam.nb_ancrages
            suspect        = bool(lam.remarques)
            self.RowBg     = BG_WARN if suspect else (BG_WHITE if idx % 2 == 1 else BG_ALT)
            self.RowFg     = FG_DARK
            self.RowWeight = W_BOLD if suspect else W_NORMAL

    # =========================================================================
    # Diagnostic
    # =========================================================================
    def _valeur_lisible(p):
        try:
            if p.StorageType == StorageType.String:
                return p.AsString() or u"(vide)"
            if p.StorageType == StorageType.Integer:
                return u"{}".format(p.AsInteger())
            if p.StorageType == StorageType.Double:
                return u"{:.6f} brut  |  affiche : {}".format(
                    p.AsDouble(), p.AsValueString() or u"-")
            if p.StorageType == StorageType.ElementId:
                eid = p.AsElementId()
                cible = doc.GetElement(eid)
                return u"Id {} -> {}".format(
                    eid.IntegerValue, _nom_element(cible) or u"-")
        except Exception:
            pass
        return u"(illisible)"

    def _sonder(el):
        """
        Joue chaque route de lecture isolement et renvoie la trace complete,
        exception comprise. Couteux : reserve au diagnostic, jamais au scan.
        """
        sondes = [
            (u"el.Name",                     lambda: el.Name),
            (u"el.Symbol",                   lambda: el.Symbol),
            (u"el.Symbol.Name",              lambda: el.Symbol.Name),
            (u"el.Symbol.Family",            lambda: el.Symbol.Family),
            (u"el.Symbol.Family.Name",       lambda: el.Symbol.Family.Name),
            (u"el.GetTypeId().IntegerValue", lambda: el.GetTypeId().IntegerValue),
            (u"doc.GetElement(typeId)",      lambda: doc.GetElement(el.GetTypeId())),
            (u"ElementType.Name",            lambda: doc.GetElement(el.GetTypeId()).Name),
            (u"ElementType.FamilyName",      lambda: doc.GetElement(el.GetTypeId()).FamilyName),
            (u"BIP ALL_MODEL_FAMILY_NAME",
             lambda: el.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME).AsString()),
            (u"BIP ALL_MODEL_TYPE_NAME",
             lambda: el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()),
            (u"doc.GetElement(el.Id) retrouve l'element",
             lambda: doc.GetElement(el.Id) is not None),
            (u"el.Document.Title",           lambda: el.Document.Title),
        ]
        L = []
        for nom, fn in sondes:
            try:
                v = fn()
                if v is None:
                    aff = u"None"
                elif isinstance(v, bool):
                    aff = u"OUI" if v else u"non"
                else:
                    aff = u"\"{}\"".format(v)
                L.append(u"      {:42} -> {}".format(nom, aff))
            except Exception as ex:
                L.append(u"      {:42} -> ERREUR {} : {}".format(
                    nom, type(ex).__name__, ex))
        return L

    def _decrire(el, tous_params=False):
        L = []
        try:
            eid = el.Id.IntegerValue
        except Exception:
            eid = -1
        fam, typ, orig = _noms_famille_type(el)
        try:
            cat = el.Category.Name if el.Category is not None else u"(sans categorie)"
        except Exception:
            cat = u"(illisible)"
        k = _cle(fam)
        L.append(u"  Id {}  |  classe .NET : {}".format(eid, type(el).__name__))
        L.append(u"    Categorie : {}".format(cat))
        L.append(u"    Famille   : \"{}\"   (lue via {})".format(fam, orig))
        L.append(u"    Type      : \"{}\"".format(typ))
        L.append(u"    Cle calculee : \"{}\"".format(k))
        L.append(u"    Cle attendue : \"{}\"".format(CLE_FAMILLE))
        L.append(u"    -> exacte : {}   |   repli \"{}\" : {}".format(
            u"OUI" if k == CLE_FAMILLE else u"non", MOT_CLE_REPLI,
            u"OUI" if CLE_REPLI in k else u"non"))
        serie, larg, ep = parse_type(typ)
        L.append(u"    Decodage du type : serie={}  largeur={} mm  epaisseur={} mm".format(
            serie, fmt_num(larg, 0), fmt_num(ep, 1)))
        L.append(u"    Routes de lecture, une par une :")
        L.extend(_sonder(el))

        motifs = [u"ancrage", u"longueur"]
        lignes = []
        try:
            et = doc.GetElement(el.GetTypeId())
        except Exception:
            et = None
        for src, lbl in [(et, u"TYPE"), (el, u"INST")]:
            if src is None:
                continue
            try:
                params = list(src.Parameters)
            except Exception:
                continue
            for p in params:
                try:
                    nm = p.Definition.Name
                except Exception:
                    continue
                if not tous_params and not any(m in _norm_txt(nm) for m in motifs):
                    continue
                lignes.append(u"      [{}] {} = {}".format(lbl, nm, _valeur_lisible(p)))
        L.append(u"    Parametres {} :".format(
            u"(tous)" if tous_params else u"contenant ancrage / longueur"))
        L.extend(lignes[:100] or [u"      (aucun)"])
        return L

    def rapport_diagnostic():
        L = []
        L.append(u"Projet : {}".format(doc.Title))
        L.append(u"Revit {}  —  {} v{}".format(app.VersionNumber, TOOL_NAME, SCRIPT_VERSION))
        L.append(u"")
        L.append(u"Famille recherchee : \"{}\"".format(FAMILLE_CIBLE))
        L.append(u"  -> cle de comparaison : \"{}\"".format(CLE_FAMILLE))
        L.append(u"Mot-cle de repli   : \"{}\"  (cle \"{}\")".format(MOT_CLE_REPLI, CLE_REPLI))
        L.append(u"")
        L.append(u"Occurrences balayees : {}".format(STATE["nb_inst"]))
        L.append(u"Familles distinctes  : {}".format(len(STATE["inventaire"])))
        L.append(u"Sans nom de famille lisible : {}".format(len(STATE["sans_nom"])))
        L.append(u"Lamelles retenues : {}   —   mode : {}".format(
            len(STATE["lamelles"]), STATE["mode"]))
        L.append(u"")

        L.append(u"=== Etat du document ===")
        for lib, fn in [
            (u"doc.Title",                lambda: doc.Title),
            (u"doc.PathName",             lambda: doc.PathName),
            (u"doc.IsLinked",             lambda: doc.IsLinked),
            (u"doc.IsFamilyDocument",     lambda: doc.IsFamilyDocument),
            (u"doc.IsWorkshared",         lambda: doc.IsWorkshared),
            (u"uidoc.Document.Title",     lambda: uidoc.Document.Title),
            (u"uidoc.Document == doc",    lambda: uidoc.Document.Equals(doc)),
            (u"doc.ActiveView.Name",      lambda: doc.ActiveView.Name),
        ]:
            try:
                L.append(u"  {:26} = {}".format(lib, fn()))
            except Exception as ex:
                L.append(u"  {:26} = ERREUR {} : {}".format(
                    lib, type(ex).__name__, ex))
        L.append(u"")

        L.append(u"=== Selection Revit courante ===")
        try:
            ids = list(uidoc.Selection.GetElementIds())
        except Exception:
            ids = []
        if not ids:
            L.append(u"  (aucune selection)")
            L.append(u"")
            L.append(u"  >>> Selectionnez UNE lamelle dans Revit, puis relancez l'outil :")
            L.append(u"      le detail complet de l'element s'affichera ici (famille reelle,")
            L.append(u"      classe .NET, categorie et tous ses parametres).")
        else:
            L.append(u"  {} element(s) selectionne(s), {} detaille(s) :".format(
                len(ids), min(3, len(ids))))
            for eid in ids[:3]:
                el = doc.GetElement(eid)
                if el is None:
                    continue
                L.append(u"")
                L.extend(_decrire(el, True))
        L.append(u"")

        L.append(u"=== Familles dont le nom evoque une lamelle ===")
        motifs = [u"lam", u"carbon", u"renfort", u"colle"]
        proches = []
        for nom in sorted(STATE["inventaire"].keys()):
            k = _cle(nom)
            if any(m in k for m in motifs):
                proches.append(u"  {:6d} x  \"{}\"    (cle \"{}\")".format(
                    STATE["inventaire"][nom], nom, k))
        L.extend(proches or [u"  (aucune)"])
        L.append(u"")

        # Scan des types, sans passer par les occurrences : discrimine une panne
        # de resolution occurrence -> type d'une panne de lecture des noms.
        L.append(u"=== Scan des TYPES (ElementType) du projet ===")
        try:
            types = (FilteredElementCollector(doc)
                     .WhereElementIsElementType().ToElements())
        except Exception:
            types = []
        nb_t, vides, fams_t = 0, 0, {}
        err_t = u""
        for et in types:
            nb_t += 1
            f = u""
            try:
                f = getattr(et, "FamilyName", u"") or u""
            except Exception as ex:
                if not err_t:
                    err_t = u"{} : {}".format(type(ex).__name__, ex)
            if f:
                fams_t[f] = fams_t.get(f, 0) + 1
            else:
                vides += 1
        L.append(u"  {} type(s)  |  {} sans FamilyName lisible  |  {} famille(s) "
                 u"distincte(s)".format(nb_t, vides, len(fams_t)))
        if err_t:
            L.append(u"  Premiere erreur rencontree : {}".format(err_t))
        proches_t = [n for n in sorted(fams_t.keys())
                     if any(m in _cle(n) for m in motifs)]
        L.append(u"  Familles (niveau type) evoquant une lamelle :")
        L.extend([u"    {:6d} x  \"{}\"".format(fams_t[n], n) for n in proches_t]
                 or [u"    (aucune)"])
        L.append(u"  15 premieres familles (niveau type) :")
        for n in sorted(fams_t.keys())[:15]:
            L.append(u"    {:6d} x  \"{}\"".format(fams_t[n], n))
        L.append(u"")

        L.append(u"=== Categorie Assemblages structurels ===")
        try:
            conns = (FilteredElementCollector(doc)
                     .OfCategory(BuiltInCategory.OST_StructConnections)
                     .WhereElementIsNotElementType().ToElements())
        except Exception:
            conns = []
        inv2 = {}
        for el in conns:
            f, _t, o = _noms_famille_type(el)
            c = u"\"{}\"   (lue via {})".format(f or u"(sans nom)", o)
            inv2[c] = inv2.get(c, 0) + 1
        L.append(u"  {} element(s)".format(len(conns)))
        for c in sorted(inv2.keys())[:60]:
            L.append(u"  {:6d} x  {}".format(inv2[c], c))
        L.append(u"")

        if STATE["sans_nom"]:
            L.append(u"=== Elements sans nom de famille : sondage route par route ===")
            for el in STATE["sans_nom"][:3]:
                L.extend(_decrire(el))
                L.append(u"")

        L.append(u"=== Familles les plus nombreuses (60 max) ===")
        tri = sorted(STATE["inventaire"].items(), key=lambda kv: -kv[1])
        for nom, n in tri[:60]:
            L.append(u"  {:6d} x  \"{}\"".format(n, nom))

        return u"\n".join(L)

    def afficher_diagnostic(sous_titre):
        try:
            txt = rapport_diagnostic()
        except Exception:
            txt = u"Diagnostic en echec :\n\n" + traceback.format_exc()

        d = Window()
        d.Title = TOOL_NAME
        d.Width = 900; d.Height = 640
        d.WindowStartupLocation = WindowStartupLocation.CenterScreen
        d.Background = hex_brush("#FFFFFF")
        droot = Grid()
        for h in ["Auto", "*", "Auto"]:
            droot.RowDefinitions.Add(_rd(h))
        d.Content = droot

        hdr = Border(); hdr.Background = hex_brush("#2F6496")
        hdr.Padding = Thickness(14, 8, 14, 8)
        Grid.SetRow(hdr, 0); droot.Children.Add(hdr)
        htb = TextBlock()
        htb.Text = sous_titre
        htb.FontSize = 12; htb.FontWeight = FontWeights.SemiBold
        htb.Foreground = hex_brush("#FFFFFF")
        hdr.Child = htb

        box = TextBox()
        box.Text = txt
        box.IsReadOnly = True
        box.FontFamily = FontFamily("Consolas")
        box.FontSize = 11
        box.Margin = Thickness(10, 8, 10, 6)
        box.TextWrapping = TextWrapping.NoWrap
        box.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
        box.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        box.BorderBrush = hex_brush("#C0D0E0")
        Grid.SetRow(box, 1); droot.Children.Add(box)

        dfooter, dsp, dgf = _make_footer()
        Grid.SetRow(dfooter, 2); droot.Children.Add(dfooter)

        def _copier(s, e):
            try:
                Clipboard.SetText(txt)
            except Exception:
                pass
        btn_cp = _footer_btn(u"Copier", "#E67E22", 100, _copier)
        btn_cp.Margin = Thickness(0, 0, 6, 0)
        dsp.Children.Add(btn_cp)
        dsp.Children.Add(_footer_btn(u"Fermer", "#3498DB", 90, lambda s, e: d.Close()))
        dgf.Children.Add(dsp)
        d.ShowDialog()

    # =========================================================================
    # Export XLSX
    # =========================================================================
    def _choisir_fichier():
        prefs = _load_prefs()
        try:
            dlg = WinForms.SaveFileDialog()
            dlg.Title  = u"Exporter la quantification des lamelles"
            dlg.Filter = u"Classeur Excel (*.xlsx)|*.xlsx"
            dlg.FileName = u"{}_lamelles_carbone.xlsx".format(
                _nom_fichier_sur(doc.Title) or u"quantification")
            dossier = prefs.get("last_export_folder", u"")
            if dossier and os.path.isdir(dossier):
                dlg.InitialDirectory = dossier
            if dlg.ShowDialog() == WinForms.DialogResult.OK:
                prefs["last_export_folder"] = os.path.dirname(dlg.FileName)
                _save_prefs(prefs)
                return dlg.FileName
        except Exception:
            pass
        return None

    def export_xlsx(resume_filtres):
        lamelles, groupes = STATE["filtrees"], STATE["groupes"]
        if not lamelles:
            MessageBox.Show(u"Rien à exporter avec les filtres actuels.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return None
        try:
            import xlsxwriter
        except Exception:
            MessageBox.Show(u"Le module xlsxwriter n'est pas disponible.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Error)
            return None

        chemin = _choisir_fichier()
        if not chemin:
            return None

        nb, lg_tot, gros_tot, petits_tot = totaux(lamelles)

        wb  = xlsxwriter.Workbook(chemin)
        ws  = wb.add_worksheet(u"Synthese")
        wsd = wb.add_worksheet(u"Detail")
        ws2 = wb.add_worksheet(u"Recapitulatif")

        fmt_title = wb.add_format({"bold": True, "font_size": 14, "font_name": "Calibri"})
        fmt_hdr   = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                   "font_color": "#FFFFFF", "border": 1,
                                   "font_name": "Calibri", "align": "center",
                                   "valign": "vcenter", "text_wrap": True})
        fmt_txt   = wb.add_format({"font_name": "Calibri"})
        fmt_int   = wb.add_format({"font_name": "Calibri", "align": "center"})
        fmt_n0    = wb.add_format({"num_format": "#,##0",     "font_name": "Calibri"})
        fmt_n1    = wb.add_format({"num_format": "#,##0.0",   "font_name": "Calibri"})
        fmt_n2    = wb.add_format({"num_format": "#,##0.00",  "font_name": "Calibri"})
        fmt_tot   = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                   "font_color": "#FFFFFF", "font_name": "Calibri"})
        fmt_tot_i = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                   "font_color": "#FFFFFF", "font_name": "Calibri",
                                   "align": "center"})
        fmt_tot_2 = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                   "font_color": "#FFFFFF", "font_name": "Calibri",
                                   "num_format": "#,##0.00"})
        KFMT = {"n0": fmt_n0, "n1": fmt_n1, "n2": fmt_n2}

        def ecrire(sheet, r, cellules):
            for c, paire in enumerate(cellules):
                val, kind = paire
                if kind == "txt":
                    sheet.write(r, c, val if val else DASH, fmt_txt)
                elif kind == "int":
                    sheet.write_number(r, c, val, fmt_int)
                elif val is None:
                    sheet.write(r, c, DASH, fmt_txt)
                else:
                    sheet.write_number(r, c, float(val), KFMT[kind])

        # ---------------- Feuille 1 : synthese ---------------------------------
        entetes = [u"N", u"Type", u"Série", u"Largeur (mm)", u"Épaisseur (mm)",
                   u"Niveau", u"Nb lamelles", u"Longueur totale (m)",
                   u"Ancrages gros", u"Ancrages petits", u"Ancrages total"]
        ws.set_row(0, 32)
        ws.write_row(0, 0, entetes, fmt_hdr)
        ws.freeze_panes(1, 0)
        ws.set_column(0, 0, 5);  ws.set_column(1, 1, 26); ws.set_column(2, 2, 12)
        ws.set_column(3, 4, 15); ws.set_column(5, 5, 26); ws.set_column(6, 6, 13)
        ws.set_column(7, 7, 19); ws.set_column(8, 10, 15)

        for i, g in enumerate(groupes, start=1):
            ecrire(ws, i, [
                (i, "int"), (g.type_name, "txt"), (g.serie, "txt"),
                (g.largeur_mm, "n0"), (g.epaisseur, "n1"), (g.niveau, "txt"),
                (g.nb, "int"), (g.longueur, "n2"),
                (g.gros, "int"), (g.petits, "int"), (g.nb_ancrages, "int"),
            ])

        tr = len(groupes) + 2
        for c in range(0, len(entetes)):
            ws.write(tr, c, u"", fmt_tot)
        ws.write(tr, 1, u"TOTAL", fmt_tot)
        ws.write(tr, 5, u"{} ligne(s)".format(len(groupes)), fmt_tot)
        ws.write_number(tr, 6, nb, fmt_tot_i)
        ws.write_number(tr, 7, lg_tot, fmt_tot_2)
        ws.write_number(tr, 8, gros_tot, fmt_tot_i)
        ws.write_number(tr, 9, petits_tot, fmt_tot_i)
        ws.write_number(tr, 10, gros_tot + petits_tot, fmt_tot_i)

        # ---------------- Feuille 2 : detail -----------------------------------
        entetes_d = [u"ElementId", u"Famille", u"Type", u"Série", u"Largeur (mm)",
                     u"Épaisseur (mm)", u"Longueur (m)", u"Niveau", u"Origine niveau",
                     u"Ancrage gauche", u"Ancrage droite", u"Nb ancrages",
                     u"Source taille ancrage", u"Remarque"]
        wsd.set_row(0, 32)
        wsd.write_row(0, 0, entetes_d, fmt_hdr)
        wsd.freeze_panes(1, 0)
        wsd.set_column(0, 0, 12); wsd.set_column(1, 2, 26); wsd.set_column(3, 3, 12)
        wsd.set_column(4, 6, 15); wsd.set_column(7, 7, 26); wsd.set_column(8, 8, 15)
        wsd.set_column(9, 11, 15); wsd.set_column(12, 12, 20); wsd.set_column(13, 13, 46)

        for i, lam in enumerate(lamelles, start=1):
            srcs = [s for s in [lam.anc_src[u"gauche"], lam.anc_src[u"droite"]] if s]
            ecrire(wsd, i, [
                (lam.element_id, "int"), (lam.famille, "txt"), (lam.type_name, "txt"),
                (lam.serie, "txt"), (lam.largeur_mm, "n0"), (lam.epaisseur, "n1"),
                (lam.longueur_m, "n2"), (lam.niveau, "txt"), (lam.niveau_src, "txt"),
                (lam.anc[u"gauche"], "txt"), (lam.anc[u"droite"], "txt"),
                (lam.nb_ancrages, "int"),
                (u" / ".join(sorted(set(srcs))), "txt"), (lam.remarque, "txt"),
            ])

        # ---------------- Feuille 3 : recapitulatif ----------------------------
        try:
            nom_projet = doc.Title or DASH
        except Exception:
            nom_projet = DASH

        r = 0
        ws2.set_column(1, 1, 34); ws2.set_column(2, 2, 40)
        ws2.write(r, 1, u"Quantification lamelles carbone — Récapitulatif", fmt_title)
        r += 2
        for lib, val in [
            (u"Projet", nom_projet),
            (u"Date", datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
            (u"Famille recherchée", FAMILLE_CIBLE),
            (u"Mode de recherche", STATE["mode"]),
            (u"Filtres appliqués", resume_filtres),
            (u"Seuil gros ancrage", u"largeur >= {:.0f} mm".format(SEUIL_GROS_MM)),
        ]:
            ws2.write(r, 1, lib, fmt_hdr); ws2.write(r, 2, val, fmt_txt); r += 1

        for lib, val, kind in [
            (u"Nb lamelles", nb, "int"),
            (u"Nb couples type x niveau", len(groupes), "int"),
            (u"Longueur totale (m)", lg_tot, "n2"),
            (u"Gros ancrages", gros_tot, "int"),
            (u"Petits ancrages", petits_tot, "int"),
            (u"Ancrages total", gros_tot + petits_tot, "int"),
        ]:
            ws2.write(r, 1, lib, fmt_hdr)
            if kind == "int":
                ws2.write_number(r, 2, val, fmt_int)
            else:
                ws2.write_number(r, 2, float(val), fmt_n2)
            r += 1
        r += 1

        # Recapitulatif par type (tous niveaux confondus)
        par_type = {}
        for lam in lamelles:
            d = par_type.setdefault(lam.type_name, {"nb": 0, "lg": 0.0, "gr": 0, "pt": 0})
            d["nb"] += 1
            d["lg"] += (lam.longueur_m or 0.0)
            d["gr"] += lam.nb_gros
            d["pt"] += lam.nb_petits
        ws2.write_row(r, 1, [u"Type", u"Nb", u"Longueur (m)", u"Gros", u"Petits"], fmt_hdr)
        r += 1
        for k in sorted(par_type.keys()):
            d = par_type[k]
            ws2.write(r, 1, k, fmt_txt)
            ws2.write_number(r, 2, d["nb"], fmt_int)
            ws2.write_number(r, 3, d["lg"], fmt_n2)
            ws2.write_number(r, 4, d["gr"], fmt_int)
            ws2.write_number(r, 5, d["pt"], fmt_int)
            r += 1

        wb.close()
        return chemin

    def _ouvrir_apres_export(chemin):
        res = MessageBox.Show(
            u"Export terminé :\n{}\n\nOuvrir le fichier ?".format(chemin),
            TOOL_NAME, MessageBoxButton.YesNo, MessageBoxImage.Information)
        if res == MessageBoxResult.Yes:
            try:
                # UseShellExecute explicite : sous .NET 8 (Revit 2025) Process.Start
                # sur un chemin de document echoue sans ce drapeau.
                psi = System.Diagnostics.ProcessStartInfo(chemin)
                psi.UseShellExecute = True
                System.Diagnostics.Process.Start(psi)
            except Exception:
                pass

    # =========================================================================
    # Fenetre
    # =========================================================================
    def _style_entete(align):
        s = SW.Style(DataGridColumnHeader)
        s.Setters.Add(SW.Setter(DataGridColumnHeader.BackgroundProperty, hex_brush("#D0E4F7")))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.FontWeightProperty, FontWeights.SemiBold))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.PaddingProperty, Thickness(6, 3, 6, 3)))
        s.Setters.Add(SW.Setter(DataGridColumnHeader.HorizontalContentAlignmentProperty, align))
        return s

    HDR_G = _style_entete(HorizontalAlignment.Left)
    HDR_C = _style_entete(HorizontalAlignment.Center)
    HDR_D = _style_entete(HorizontalAlignment.Right)

    def _style_cellule(align):
        s = SW.Style(TextBlock)
        s.Setters.Add(SW.Setter(TextBlock.TextAlignmentProperty, align))
        s.Setters.Add(SW.Setter(TextBlock.ForegroundProperty, Binding("RowFg")))
        s.Setters.Add(SW.Setter(TextBlock.FontWeightProperty, Binding("RowWeight")))
        return s

    def _col(entete, champ, largeur, align=SW.TextAlignment.Left, hdr=None, tri=None):
        c = DataGridTextColumn()
        c.Header  = entete
        c.Binding = Binding(champ)
        c.Width   = DataGridLength(largeur)
        c.ElementStyle = _style_cellule(align)
        c.HeaderStyle  = hdr if hdr is not None else HDR_G
        if tri:
            c.SortMemberPath = tri
        return c

    def _nouvelle_grille():
        dg = DataGrid()
        dg.AutoGenerateColumns = False
        dg.IsReadOnly          = True
        dg.CanUserSortColumns  = True
        dg.CanUserResizeColumns = True
        dg.HeadersVisibility   = DataGridHeadersVisibility.Column
        dg.RowBackground       = BG_WHITE
        dg.BorderBrush         = hex_brush("#C0D0E0")
        dg.BorderThickness     = Thickness(1)
        dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
        dg.FrozenColumnCount   = 1
        dg.SelectionMode       = DataGridSelectionMode.Single
        dg.FontSize            = 12
        style = SW.Style(DataGridRow)
        style.Setters.Add(SW.Setter(DataGridRow.BackgroundProperty, Binding("RowBg")))
        dg.RowStyle = style
        return dg

    def construire_fenetre():
        C = SW.TextAlignment.Center
        D = SW.TextAlignment.Right

        win = Window()
        win.Title  = TOOL_NAME
        win.Width  = 1180
        win.Height = 660
        win.MinWidth  = 900
        win.MinHeight = 480
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen
        win.ResizeMode = ResizeMode.CanResize
        win.Background = hex_brush("#FFFFFF")

        root = Grid()
        for h in ["Auto", "Auto", "*", "Auto"]:
            root.RowDefinitions.Add(_rd(h))
        win.Content = root

        # ---- barre de titre ------------------------------------------------
        hdr = Border()
        hdr.Background = hex_brush("#2F6496")
        hdr.Padding = Thickness(14, 9, 14, 9)
        tb = TextBlock()
        tb.Text = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        tb.FontSize = 13; tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = hex_brush("#FFFFFF")
        hdr.Child = tb
        Grid.SetRow(hdr, 0); root.Children.Add(hdr)

        # ---- barre de filtres ----------------------------------------------
        flt = Border()
        flt.Background = hex_brush("#F0F6FF")
        flt.BorderBrush = hex_brush("#C0D0E0")
        flt.BorderThickness = Thickness(0, 0, 0, 1)
        flt.Padding = Thickness(10, 8, 10, 8)
        Grid.SetRow(flt, 1); root.Children.Add(flt)

        flt_sp = StackPanel()
        flt.Child = flt_sp
        ligne1 = StackPanel()
        ligne1.Orientation = Orientation.Horizontal
        flt_sp.Children.Add(ligne1)

        ligne1.Children.Add(_label(u"Niveau :", marge=Thickness(0, 0, 6, 0)))
        cb_niv = _combo(200)
        ligne1.Children.Add(cb_niv)

        ligne1.Children.Add(_label(u"Type :", marge=Thickness(0, 0, 6, 0)))
        cb_typ = _combo(200)
        ligne1.Children.Add(cb_typ)

        ligne1.Children.Add(_label(u"Recherche :", marge=Thickness(0, 0, 6, 0)))
        txt_flt = TextBox()
        txt_flt.Width = 190; txt_flt.Height = 24; txt_flt.FontSize = 11
        txt_flt.Padding = Thickness(4, 2, 4, 2)
        txt_flt.BorderBrush = hex_brush("#C0D0E0")
        txt_flt.VerticalContentAlignment = VerticalAlignment.Center
        txt_flt.Margin = Thickness(0, 0, 8, 0)
        ligne1.Children.Add(txt_flt)

        btn_raz = Button()
        btn_raz.Content = u"Réinitialiser"
        btn_raz.Height = 24; btn_raz.FontSize = 11
        btn_raz.Padding = Thickness(8, 0, 8, 0)
        btn_raz.Background = hex_brush("#E0E0E0")
        btn_raz.BorderThickness = Thickness(0)
        ligne1.Children.Add(btn_raz)

        lbl_info = TextBlock()
        lbl_info.FontSize = 11; lbl_info.FontWeight = FontWeights.SemiBold
        lbl_info.Foreground = hex_brush("#2F6496")
        lbl_info.Margin = Thickness(0, 7, 0, 0)
        flt_sp.Children.Add(lbl_info)

        lbl_hint = TextBlock()
        lbl_hint.FontSize = 10; lbl_hint.Foreground = hex_brush("#666666")
        lbl_hint.TextWrapping = TextWrapping.Wrap
        lbl_hint.Margin = Thickness(0, 3, 0, 0)
        flt_sp.Children.Add(lbl_hint)

        # ---- onglets --------------------------------------------------------
        tabs = TabControl()
        tabs.Margin = Thickness(8, 8, 8, 4)
        tabs.BorderBrush = hex_brush("#C0D0E0")
        tabs.Background = hex_brush("#FFFFFF")
        Grid.SetRow(tabs, 2); root.Children.Add(tabs)

        dg_syn = _nouvelle_grille()
        dg_syn.Columns.Add(_col(u"N",                  "Num",      42, C, HDR_C))
        dg_syn.Columns.Add(_col(u"Type",               "Type",    210))
        dg_syn.Columns.Add(_col(u"Série",              "Serie",    80))
        dg_syn.Columns.Add(_col(u"Largeur (mm)",       "Largeur",  95, D, HDR_D, "LargeurN"))
        dg_syn.Columns.Add(_col(u"Épaisseur (mm)",     "Ep",      100, D, HDR_D, "EpN"))
        dg_syn.Columns.Add(_col(u"Niveau",             "Niveau",  180, SW.TextAlignment.Left,
                                HDR_G, "NivN"))
        dg_syn.Columns.Add(_col(u"Nb",                 "Nb",       55, C, HDR_C, "NbN"))
        dg_syn.Columns.Add(_col(u"Longueur tot. (m)",  "Longueur", 120, D, HDR_D, "LongueurN"))
        dg_syn.Columns.Add(_col(u"Gros ancrages",      "Gros",     105, C, HDR_C, "GrosN"))
        dg_syn.Columns.Add(_col(u"Petits ancrages",    "Petits",   110, C, HDR_C, "PetitsN"))
        dg_syn.Columns.Add(_col(u"Ancrages total",     "Ancrages", 105, C, HDR_C, "AncragesN"))

        dg_det = _nouvelle_grille()
        dg_det.Columns.Add(_col(u"Id",             "Id",        85, C, HDR_C, "IdN"))
        dg_det.Columns.Add(_col(u"Type",           "Type",     190))
        dg_det.Columns.Add(_col(u"Largeur (mm)",   "Largeur",   95, D, HDR_D, "LargeurN"))
        dg_det.Columns.Add(_col(u"Épaisseur (mm)", "Ep",       100, D, HDR_D, "EpN"))
        dg_det.Columns.Add(_col(u"Longueur (m)",   "Longueur",  95, D, HDR_D, "LongueurN"))
        dg_det.Columns.Add(_col(u"Niveau",         "Niveau",   170, SW.TextAlignment.Left,
                                HDR_G, "NivN"))
        dg_det.Columns.Add(_col(u"Ancrage gauche", "AncG",     105, C, HDR_C))
        dg_det.Columns.Add(_col(u"Ancrage droite", "AncD",     105, C, HDR_C))
        dg_det.Columns.Add(_col(u"Nb ancrages",    "NbAnc",     90, C, HDR_C, "NbAncN"))
        dg_det.Columns.Add(_col(u"Remarque",       "Remarque", 260))

        onglet1 = TabItem(); onglet1.Header = u"Synthèse par type"; onglet1.Content = dg_syn
        onglet2 = TabItem(); onglet2.Header = u"Détail par lamelle"; onglet2.Content = dg_det
        onglet1.FontSize = 12; onglet2.FontSize = 12
        tabs.Items.Add(onglet1); tabs.Items.Add(onglet2)

        # ---- footer ----------------------------------------------------------
        footer, sp_btns, grid_f = _make_footer()
        Grid.SetRow(footer, 3); root.Children.Add(footer)

        lbl_tot = TextBlock()
        lbl_tot.FontSize = 11; lbl_tot.FontWeight = FontWeights.SemiBold
        lbl_tot.Foreground = hex_brush("#1F497D")
        lbl_tot.VerticalAlignment   = VerticalAlignment.Center
        lbl_tot.HorizontalAlignment = HorizontalAlignment.Center
        grid_f.Children.Add(lbl_tot)

        # ---- logique de filtrage --------------------------------------------
        def resume_filtres():
            parts = []
            niv = _valeur_combo(cb_niv)
            typ = _valeur_combo(cb_typ)
            if niv and niv != TOUS:
                parts.append(u"niveau = {}".format(niv))
            if typ and typ != TOUS:
                parts.append(u"type = {}".format(typ))
            if (txt_flt.Text or u"").strip():
                parts.append(u"recherche = \"{}\"".format(txt_flt.Text.strip()))
            return u" ; ".join(parts) or u"aucun"

        def appliquer_filtres():
            niv = _valeur_combo(cb_niv)
            typ = _valeur_combo(cb_typ)
            rech = _norm_txt((txt_flt.Text or u"").strip())
            res = []
            for lam in STATE["lamelles"]:
                if niv and niv != TOUS and lam.niveau != niv:
                    continue
                if typ and typ != TOUS and lam.type_name != typ:
                    continue
                if rech:
                    blob = _norm_txt(u"{} {} {} {} {}".format(
                        lam.element_id, lam.type_name, lam.serie,
                        lam.niveau, lam.remarque))
                    if rech not in blob:
                        continue
                res.append(lam)
            STATE["filtrees"] = res
            STATE["groupes"]  = grouper(res)

        def rafraichir():
            appliquer_filtres()
            col_s = ObservableCollection[object]()
            for i, g in enumerate(STATE["groupes"], start=1):
                col_s.Add(LigneSynthese(g, i))
            dg_syn.ItemsSource = None
            dg_syn.ItemsSource = col_s

            col_d = ObservableCollection[object]()
            for i, lam in enumerate(STATE["filtrees"], start=1):
                col_d.Add(LigneDetail(lam, i))
            dg_det.ItemsSource = None
            dg_det.ItemsSource = col_d

            nb, lg, gr, pt = totaux(STATE["filtrees"])
            resume = (u"{} lamelle(s)   |   {} m   |   {} gros ancrage(s)   |   "
                      u"{} petit(s) ancrage(s)   |   {} type(s) x niveau").format(
                          nb, fmt_num(lg, 2), gr, pt, len(STATE["groupes"]))
            lbl_info.Text = resume
            lbl_tot.Text  = resume

            nb_alerte = len([1 for l in STATE["filtrees"] if l.remarques])
            alerte = u""
            if nb_alerte:
                alerte = (u"  {} ligne(s) sur fond orange : voir la colonne "
                          u"Remarque de l'onglet Détail.").format(nb_alerte)
            lbl_hint.Text = (
                u"Famille \"{}\" — recherche : {}. {} occurrence(s) trouvée(s) sur "
                u"{} instance(s) balayée(s).\n"
                u"Largeur et épaisseur décodées du nom de type (3 chiffres = largeur mm, "
                u"2 derniers = épaisseur en dixièmes de mm). Taille d'ancrage lue sur les "
                u"paramètres Small / Large de la famille, repli sur la largeur "
                u"(>= {:.0f} mm = gros).{}"
            ).format(FAMILLE_CIBLE, STATE["mode"], len(STATE["lamelles"]),
                     STATE["nb_inst"], SEUIL_GROS_MM, alerte)

        def on_filtre(s, e):
            rafraichir()

        def on_raz(s, e):
            cb_niv.SelectedIndex = 0
            cb_typ.SelectedIndex = 0
            txt_flt.Text = u""
            rafraichir()

        def on_select(s, e):
            grille = dg_syn if tabs.SelectedIndex == 0 else dg_det
            sel = grille.SelectedItem
            if sel is None:
                MessageBox.Show(u"Sélectionnez d'abord une ligne dans la liste.",
                                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            try:
                ids = NetList[ElementId]()
                for eid in sel.ids:
                    ids.Add(ElementId(eid))
                uidoc.Selection.SetElementIds(ids)
                uidoc.ShowElements(ids)
            except Exception:
                MessageBox.Show(u"Sélection impossible :\n\n{}".format(traceback.format_exc()),
                                TOOL_NAME, MessageBoxButton.OK, MessageBoxImage.Error)

        def on_export(s, e):
            chemin = export_xlsx(resume_filtres())
            if chemin:
                _ouvrir_apres_export(chemin)

        cb_niv.SelectionChanged += on_filtre
        cb_typ.SelectionChanged += on_filtre
        txt_flt.TextChanged     += on_filtre
        btn_raz.Click           += on_raz

        btn_diag  = _footer_btn(u"Diagnostic",    "#607D8B", 105,
                                lambda s, e: afficher_diagnostic(
                                    u"Diagnostic — lecture des lamelles carbone"))
        btn_sel   = _footer_btn(u"Sélectionner", "#8E44AD", 115, on_select)
        btn_xlsx  = _footer_btn(u"Exporter XLSX", "#E67E22", 130, on_export)
        btn_close = _footer_btn(u"Fermer",        "#3498DB",  90, lambda s, e: win.Close())
        btn_diag.Margin = Thickness(0, 0, 6, 0)
        btn_sel.Margin  = Thickness(0, 0, 6, 0)
        btn_xlsx.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(btn_diag)
        sp_btns.Children.Add(btn_sel)
        sp_btns.Children.Add(btn_xlsx)
        sp_btns.Children.Add(btn_close)
        grid_f.Children.Add(sp_btns)

        return win, cb_niv, cb_typ, rafraichir

    TOUS = u"(tous)"

    # =========================================================================
    # Main
    # =========================================================================
    lamelles, mode, nb_inst = scanner()
    STATE["lamelles"] = lamelles
    STATE["mode"]     = mode
    STATE["nb_inst"]  = nb_inst

    if not lamelles:
        # Pas de boite de dialogue aveugle : on ouvre directement le diagnostic,
        # qui dit ce que le modele contient reellement.
        afficher_diagnostic(
            u"Aucune lamelle trouvée — diagnostic de lecture du modèle")
    else:
        win, cb_niv, cb_typ, rafraichir = construire_fenetre()

        noms_niv = list(set([l.niveau for l in lamelles]))
        noms_niv.sort(key=lambda n: -ELEV_PAR_NOM.get(n, -1e9))
        _remplir_combo(cb_niv, [TOUS] + noms_niv)

        noms_typ = list(set([l.type_name for l in lamelles]))
        noms_typ.sort()
        _remplir_combo(cb_typ, [TOUS] + noms_typ)

        rafraichir()
        win.ShowDialog()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
