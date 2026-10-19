# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.1.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Doublons N° Reservation"
# =============================================================================

# Hors filet : strict minimum pour pouvoir afficher une erreur fatale
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
    import os, io, json, re

    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import System, System.IO, System.Text, System.Windows.Markup
    import System.Windows as SW

    from Autodesk.Revit.DB import (
        FilteredElementCollector, FamilyInstance, RevitLinkInstance,
        BuiltInParameter, StorageType, XYZ, UnitUtils, UnitTypeId
    )

    import xlsxwriter

    doc = __revit__.ActiveUIDocument.Document
    app = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # CONSTANTES METIER — alignees sur l'outil Sync Reservations v3.2.0
    # La population auditee doit etre EXACTEMENT celle que compare la synchro,
    # sinon les compteurs des deux outils divergent sans explication.
    # =========================================================================
    LINK_MODEL_PREFIX = "FGH_RES_SPV"
    FAMILY_PREFIX     = "FGH_RES"
    ADN_PARAM         = "CONTROL_NE_PAS_TOUCHER"
    ADN_FILTER_VAL    = "_STATUT"
    MUTUALISE_PARAM   = "FGH_MUTUALISE"

    PARAM_NUM         = "PVA_RES_DEM_NumReservation"
    PARAM_DEMANDEUR   = "PVA_RES_DEM_Demandeur"
    PARAM_DATE        = "PVA_RES_DEM_Date"
    PARAM_NIVEAU      = "WSP_NiveauAssocie"
    PARAM_X           = "WSP_PositionX_NM95"
    PARAM_Y           = "WSP_PositionY_NM95"
    PARAM_Z           = "WSP_PositionZ_NM95"
    PARAM_VAL_STATUT  = "PVA_RES_VAL_Statut"

    STATUT_SUPPRIMEE  = "SUPPRIMEE"

    SRC_SPV = u"SPV"
    SRC_STR = u"STR"

    # Deux jumeaux au-dela de cet ecart sont deux reservations distinctes qui
    # partagent un numero : la seconde est perdue par la synchro.
    TOL_POSITION_CM = 1.0

    VERDICT_MEME = u"Même position"
    VERDICT_DIFF = u"Positions différentes"

    FILTRES = [u"Tout afficher", u"Positions différentes", u"Même position",
               u"Lien SPV seulement", u"Maquette STR seulement"]

    # Structure de l'ADN (CONTROL_NE_PAS_TOUCHER), constatee sur donnees reelles :
    #   <numero>_<jj/mm/aaaa>_<hh/mm/ss>_STATUT_<n>_<maquette d'origine>_R<rev>
    # ex. 04-0252_19/03/2026_14/06/13_STATUT_1_FGH_ELE_MAB_51_MOD_TTD_TTZ_R24
    # C'est une empreinte de SOUMISSION : l'horodatage change a chaque refigeage,
    # l'ADN brut ne peut donc pas servir de cle d'identite.
    SEG_STATUT   = u"STATUT"
    RE_REVISION  = r"_R\d+$"

    # Nombre de lignes ADN affichees dans la fenetre (l'export Excel est complet)
    MAX_LIGNES_ADN = 500

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

    _LAZY = {}

    def _re_revision():
        if "rev" not in _LAZY:
            _LAZY["rev"] = re.compile(RE_REVISION)
        return _LAZY["rev"]

    # =========================================================================
    # HELPERS
    # =========================================================================
    def _eid_int(eid):
        if eid is None:
            return -1
        try:
            return eid.IntegerValue
        except Exception:
            pass
        try:
            return eid.Value
        except Exception:
            return -1

    def _safe_name(el):
        try:
            return el.Name
        except Exception:
            return u""

    def _p_str(el, pname):
        try:
            p = el.LookupParameter(pname)
            if p and p.HasValue:
                if p.StorageType == StorageType.String:
                    return (p.AsString() or u"").strip()
                v = p.AsValueString()
                if v:
                    return v.strip()
                v = p.AsString()
                if v:
                    return v.strip()
        except Exception:
            pass
        return u""

    def _p_int(el, pname):
        try:
            p = el.LookupParameter(pname)
            if p and p.HasValue and p.StorageType == StorageType.Integer:
                return p.AsInteger()
        except Exception:
            pass
        return None

    def _family_name(el):
        try:
            return el.Symbol.Family.Name
        except Exception:
            return u""

    def _type_name(el):
        try:
            return _safe_name(el.Symbol)
        except Exception:
            return u""

    def _to_m(ft):
        try:
            return float(UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Meters))
        except Exception:
            return float(ft) * 0.3048

    def _point_of(el):
        """Point caracteristique : point d'insertion, a defaut centre de la boite."""
        try:
            loc = el.Location
            if loc is not None:
                p = getattr(loc, "Point", None)
                if p is not None:
                    return p
        except Exception:
            pass
        try:
            bb = el.get_BoundingBox(None)
            if bb is not None:
                return XYZ((bb.Min.X + bb.Max.X) / 2.0,
                           (bb.Min.Y + bb.Max.Y) / 2.0,
                           (bb.Min.Z + bb.Max.Z) / 2.0)
        except Exception:
            pass
        return None

    def _dist_cm(p1, p2):
        if p1 is None or p2 is None:
            return None
        try:
            d = XYZ(p1.X - p2.X, p1.Y - p2.Y, p1.Z - p2.Z).GetLength()
            return _to_m(d) * 100.0
        except Exception:
            return None

    def _load_prefs():
        try:
            with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(d):
        try:
            txt = json.dumps(d, ensure_ascii=False)
            try:
                txt = txt.decode("utf-8")
            except Exception:
                pass
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                f.write(txt)
        except Exception:
            pass

    # =========================================================================
    # ANALYSE DE L'ADN
    # =========================================================================
    def parse_adn(adn):
        """
        Decompose l'ADN. Retourne un dict, ou None si la chaine ne suit pas la
        structure attendue — jamais de repli silencieux : le non-parsable est
        compte et affiche.
        """
        if not adn:
            return None
        parts = adn.split(u"_")
        try:
            i = parts.index(SEG_STATUT)
        except ValueError:
            return None
        if i < 2 or len(parts) < i + 3:
            return None
        maquette = u"_".join(parts[i + 2:])
        return {
            "num":      parts[0],
            "date":     parts[1] if i > 1 else u"",
            "heure":    parts[2] if i > 2 else u"",
            "statut":   parts[i + 1],
            "maquette": maquette,
            "maq_sr":   _re_revision().sub(u"", maquette),
        }

    def cle_proposee(info):
        """Cle d'identite : numero + maquette d'origine, revision retiree.

        Unique par construction : le script VDC controle l'unicite des
        identifiants A L'INTERIEUR de chaque maquette traitee ; qualifier le
        numero par sa maquette rebouche son seul trou, l'absence de controle
        entre maquettes. Stable : le numero est fige, le nom de maquette ne
        bouge pas, et le suffixe de revision est retire.
        """
        if info is None:
            return None
        return u"{}|{}".format(info["num"], info["maq_sr"])

    # =========================================================================
    # COLLECTE — filtres identiques a Sync Reservations
    # =========================================================================
    def find_link_instance():
        for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
            try:
                if LINK_MODEL_PREFIX in lnk.Name:
                    return lnk
            except Exception:
                pass
        return None

    def collect_host():
        """FGH_RES* de la STR, hors elements marques SUPPRIMEE."""
        res = []
        for e in FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements():
            try:
                if not _family_name(e).startswith(FAMILY_PREFIX):
                    continue
                if _p_str(e, PARAM_VAL_STATUT) == STATUT_SUPPRIMEE:
                    continue
                res.append(e)
            except Exception:
                pass
        return res

    def collect_link(link_instance):
        """FGH_RES* du lien : ADN contient _STATUT, hors FGH_MUTUALISE = 1."""
        ldoc = link_instance.GetLinkDocument()
        if not ldoc:
            return []
        res = []
        for e in FilteredElementCollector(ldoc).OfClass(FamilyInstance).ToElements():
            try:
                if not _family_name(e).startswith(FAMILY_PREFIX):
                    continue
                if ADN_FILTER_VAL not in (_p_str(e, ADN_PARAM) or u""):
                    continue
                if _p_int(e, MUTUALISE_PARAM) == 1:
                    continue
                res.append(e)
            except Exception:
                pass
        return res

    # =========================================================================
    # LIGNES
    # =========================================================================
    class DupRow(object):
        """Une occurrence impliquee dans un numero en doublon."""
        def __init__(self, num, source, el, ecart_cm, est_ref, verdict, cle):
            self.Num      = num
            self.Source   = source
            self.Fam      = _family_name(el)
            self.Typ      = _type_name(el)
            self.Niv      = _p_str(el, PARAM_NIVEAU)
            self.Val      = _p_str(el, PARAM_VAL_STATUT)
            self.Dem      = _p_str(el, PARAM_DEMANDEUR)
            self.Dat      = _p_str(el, PARAM_DATE)
            self.Id       = u"{}".format(_eid_int(el.Id))
            self.Verdict  = verdict
            self.Cle      = cle or u"(non parsable)"
            if est_ref:
                self.Ecart = u"réf."
            elif ecart_cm is None:
                self.Ecart = u"?"
            else:
                self.Ecart = u"{:.1f}".format(ecart_cm)

            p = _point_of(el)
            self.Xg = u"{:.3f}".format(_to_m(p.X)) if p is not None else u""
            self.Yg = u"{:.3f}".format(_to_m(p.Y)) if p is not None else u""
            self.Zg = u"{:.3f}".format(_to_m(p.Z)) if p is not None else u""
            self.Xn = _p_str(el, PARAM_X)
            self.Yn = _p_str(el, PARAM_Y)
            self.Zn = _p_str(el, PARAM_Z)

            self.RowBg = "#FDDEDE" if verdict == VERDICT_DIFF else "#FFFFFF"

    class CleRow(object):
        """Une clé candidate évaluée sur une population."""
        def __init__(self, cle, source, total, distinct, en_double,
                     objets_double, non_parsables):
            self.Cle    = cle
            self.Source = source
            self.Total  = u"{}".format(total)
            self.Dist   = u"{}".format(distinct)
            self.Dbl    = u"{}".format(en_double)
            self.Obj    = u"{}".format(objets_double)
            self.NP     = u"{}".format(non_parsables)
            base = total - non_parsables
            pct  = (100.0 * distinct / base) if base else 0.0
            self.Unic   = u"{:.2f} %".format(pct)
            self.Verdict = u"unique" if (en_double == 0 and non_parsables == 0) \
                else (u"{} collision(s)".format(en_double) if en_double
                      else u"{} non parsable(s)".format(non_parsables))
            if en_double == 0 and non_parsables == 0:
                self.RowBg = "#DFF0D8"
            elif en_double == 0:
                self.RowBg = "#FFF3CD"
            else:
                self.RowBg = "#FDDEDE"

    class AdnRow(object):
        """Une valeur d'ADN decomposee."""
        def __init__(self, source, el, adn, info, num_param):
            self.Source = source
            self.Adn    = adn
            self.NumP   = num_param
            self.Id     = u"{}".format(_eid_int(el.Id))
            if info is None:
                self.Num = self.Dat = self.Heu = self.Sta = u""
                self.Maq = self.MaqSR = self.Cle = u""
                self.Coherent = u"ADN non parsable"
                self.RowBg = "#FDDEDE"
            else:
                self.Num   = info["num"]
                self.Dat   = info["date"]
                self.Heu   = info["heure"]
                self.Sta   = info["statut"]
                self.Maq   = info["maquette"]
                self.MaqSR = info["maq_sr"]
                self.Cle   = cle_proposee(info)
                if num_param and info["num"] != num_param:
                    self.Coherent = u"n° ADN ≠ paramètre"
                    self.RowBg = "#FFF3CD"
                else:
                    self.Coherent = u"ok"
                    self.RowBg = "#FFFFFF"

    # =========================================================================
    # ANALYSES
    # =========================================================================
    def lire_population(elements, source):
        """Une seule passe de lecture API. Retourne une liste de dicts legers."""
        out = []
        for e in elements:
            adn  = _p_str(e, ADN_PARAM)
            info = parse_adn(adn)
            out.append({
                "el":     e,
                "source": source,
                "adn":    adn,
                "info":   info,
                "num_p":  _p_str(e, PARAM_NUM),
                "cle":    cle_proposee(info),
            })
        return out

    def _stats(valeurs):
        """valeurs : liste de cles (None = non parsable / absent)."""
        counts, non_parsables = {}, 0
        for v in valeurs:
            if not v:
                non_parsables += 1
                continue
            counts[v] = counts.get(v, 0) + 1
        distinct  = len(counts)
        en_double = len([k for k in counts if counts[k] > 1])
        objets    = 0
        for k in counts:
            if counts[k] > 1:
                objets += counts[k]
        return distinct, en_double, objets, non_parsables

    def analyser_cles(pop, source):
        """Compare les trois cles candidates sur une population."""
        rows  = []
        total = len(pop)
        for libelle, extract in (
                (u"N° réservation (clé actuelle)", lambda d: d["num_p"]),
                (u"ADN brut", lambda d: d["adn"]),
                (u"N° + maquette d'origine", lambda d: d["cle"])):
            vals = [extract(d) for d in pop]
            distinct, en_double, objets, np_ = _stats(vals)
            rows.append(CleRow(libelle, source, total, distinct, en_double,
                               objets, np_))
        return rows

    def analyser_stabilite(pop_link, pop_host):
        """
        L'ADN survit-il a l'import, et la cle proposee est-elle stable ?
        Appariement par n° (seule cle commune disponible aujourd'hui), en
        ignorant les n° en doublon pour ne comparer que des paires certaines.
        """
        def index_unique(pop):
            idx, dbl = {}, set()
            for d in pop:
                n = d["num_p"]
                if not n:
                    continue
                if n in idx:
                    dbl.add(n)
                else:
                    idx[n] = d
            for n in dbl:
                idx.pop(n, None)
            return idx

        il, ih = index_unique(pop_link), index_unique(pop_host)
        communs = [n for n in il if n in ih]

        adn_id = adn_diff = cle_id = cle_diff = adn_vide = 0
        exemples = []
        for n in sorted(communs):
            a, b = il[n], ih[n]
            if not a["adn"] or not b["adn"]:
                adn_vide += 1
                continue
            if a["adn"] == b["adn"]:
                adn_id += 1
            else:
                adn_diff += 1
                if len(exemples) < 10:
                    exemples.append(u"n° {} : SPV [{}] / STR [{}]".format(
                        n, a["adn"], b["adn"]))
            if a["cle"] and b["cle"] and a["cle"] == b["cle"]:
                cle_id += 1
            else:
                cle_diff += 1
        return {"communs": len(communs), "adn_id": adn_id, "adn_diff": adn_diff,
                "cle_id": cle_id, "cle_diff": cle_diff, "adn_vide": adn_vide,
                "exemples": exemples}

    def analyser_doublons(pop, source):
        """
        Groupes de n° portes par plusieurs objets.
        Retourne (rows, nb_num, nb_objets, nb_sans_num, nb_groupes_diff).
        """
        par_num, sans_num = {}, 0
        for d in pop:
            n = d["num_p"]
            if not n:
                sans_num += 1
                continue
            par_num.setdefault(n, []).append(d)

        rows, nb_num, nb_objets, nb_diff = [], 0, 0, 0
        for num in sorted(par_num.keys()):
            groupe = par_num[num]
            if len(groupe) < 2:
                continue
            nb_num    += 1
            nb_objets += len(groupe)

            ref_pt = _point_of(groupe[0]["el"])
            ecarts, emax, inconnu = [None], 0.0, False
            for d in groupe[1:]:
                dist = _dist_cm(ref_pt, _point_of(d["el"]))
                ecarts.append(dist)
                if dist is None:
                    inconnu = True
                elif dist > emax:
                    emax = dist

            if inconnu:
                verdict = u"Position indéterminée"
            elif emax > TOL_POSITION_CM:
                verdict = VERDICT_DIFF
                nb_diff += 1
            else:
                verdict = VERDICT_MEME

            for i, d in enumerate(groupe):
                rows.append(DupRow(num, source, d["el"], ecarts[i],
                                   i == 0, verdict, d["cle"]))

        return rows, nb_num, nb_objets, sans_num, nb_diff

    # =========================================================================
    # EXPORT EXCEL
    # =========================================================================
    COLS_DUP = [
        (u"N° réservation", "Num",     18), (u"Source",  "Source",  10),
        (u"Verdict groupe", "Verdict", 22), (u"Écart (cm)", "Ecart", 12),
        (u"Clé n° + maquette", "Cle",   38),
        (u"Famille",        "Fam",     28), (u"Type",    "Typ",     22),
        (u"Niveau",         "Niv",     16), (u"Statut VAL", "Val",  14),
        (u"Demandeur",      "Dem",     18), (u"Date",    "Dat",     12),
        (u"X projet (m)",   "Xg",      14), (u"Y projet (m)", "Yg",  14),
        (u"Z projet (m)",   "Zg",      14),
        (u"X NM95", "Xn", 14), (u"Y NM95", "Yn", 14), (u"Z NM95", "Zn", 14),
        (u"Id Revit",       "Id",      12),
    ]

    COLS_CLE = [
        (u"Clé candidate", "Cle", 32), (u"Source", "Source", 10),
        (u"Éléments", "Total", 12), (u"Valeurs distinctes", "Dist", 18),
        (u"Valeurs en doublon", "Dbl", 18), (u"Objets concernés", "Obj", 18),
        (u"Non parsables", "NP", 14), (u"Unicité", "Unic", 12),
        (u"Verdict", "Verdict", 22),
    ]

    COLS_ADN = [
        (u"Source", "Source", 10), (u"ADN complet", "Adn", 72),
        (u"N° (ADN)", "Num", 16), (u"N° (paramètre)", "NumP", 16),
        (u"Cohérence", "Coherent", 20),
        (u"Date", "Dat", 14), (u"Heure", "Heu", 12), (u"Statut", "Sta", 10),
        (u"Maquette d'origine", "Maq", 34),
        (u"Maquette sans révision", "MaqSR", 34),
        (u"Clé n° + maquette", "Cle", 38), (u"Id Revit", "Id", 12),
    ]

    def _cell_value(text):
        if text is None or text == u"":
            return u""
        clean = u"{}".format(text).strip().replace(u" ", u"").replace(u"\xa0", u"")
        try:
            return int(clean)
        except (ValueError, TypeError):
            pass
        try:
            return float(clean.replace(u",", u"."))
        except (ValueError, TypeError):
            pass
        return text

    def _ecrire_feuille(wb, nom, cols, rows, fmt_hdr, fmt_std, fmt_alt, colorer):
        ws = wb.add_worksheet(nom)
        for i, (titre, attr, largeur) in enumerate(cols):
            ws.set_column(i, i, largeur)
            ws.write(0, i, titre, fmt_hdr)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, max(len(rows), 1), len(cols) - 1)
        for r, row in enumerate(rows, start=1):
            fmt = colorer(row, r, fmt_std, fmt_alt)
            for c, (titre, attr, largeur) in enumerate(cols):
                ws.write(r, c, _cell_value(getattr(row, attr, u"")), fmt)
        return ws

    def exporter_excel(rows_dup, rows_cle, rows_adn, resume, chemin):
        wb = xlsxwriter.Workbook(chemin)
        fmt_hdr = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                 "font_color": "#FFFFFF", "border": 1,
                                 "align": "center", "valign": "vcenter",
                                 "text_wrap": True})
        fmt_std  = wb.add_format({"border": 1})
        fmt_alt  = wb.add_format({"bg_color": "#E8F0FA", "border": 1})
        fmt_ko   = wb.add_format({"bg_color": "#FDDEDE", "border": 1})
        fmt_warn = wb.add_format({"bg_color": "#FFF3CD", "border": 1})
        fmt_ok   = wb.add_format({"bg_color": "#DFF0D8", "border": 1})
        fmt_tit  = wb.add_format({"bold": True, "font_size": 12,
                                  "font_color": "#2F6496"})

        def par_rowbg(row, r, std, alt):
            bg = getattr(row, "RowBg", "#FFFFFF")
            if bg == "#FDDEDE":
                return fmt_ko
            if bg == "#FFF3CD":
                return fmt_warn
            if bg == "#DFF0D8":
                return fmt_ok
            return alt if (r % 2 == 0) else std

        _ecrire_feuille(wb, u"Cles", COLS_CLE, rows_cle,
                        fmt_hdr, fmt_std, fmt_alt, par_rowbg)
        _ecrire_feuille(wb, u"Doublons", COLS_DUP, rows_dup,
                        fmt_hdr, fmt_std, fmt_alt, par_rowbg)
        _ecrire_feuille(wb, u"ADN", COLS_ADN, rows_adn,
                        fmt_hdr, fmt_std, fmt_alt, par_rowbg)

        ws = wb.add_worksheet(u"Resume")
        ws.set_column(0, 0, 62)
        ws.set_column(1, 1, 22)
        ws.write(0, 0, u"Audit des identifiants de réservation", fmt_tit)
        ligne = 2
        for libelle, valeur in resume:
            ws.write(ligne, 0, libelle, fmt_std)
            ws.write(ligne, 1, _cell_value(valeur), fmt_std)
            ligne += 1
        wb.close()

    # =========================================================================
    # UI
    # =========================================================================
    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1240" Height="700" MinWidth="960" MinHeight="520"
    WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
  <Window.Resources>
    <Style x:Key="GridStyle" TargetType="DataGrid">
      <Setter Property="AutoGenerateColumns" Value="False"/>
      <Setter Property="IsReadOnly" Value="True"/>
      <Setter Property="GridLinesVisibility" Value="Horizontal"/>
      <Setter Property="BorderBrush" Value="#C0D0E0"/>
      <Setter Property="HeadersVisibility" Value="Column"/>
      <Setter Property="CanUserResizeColumns" Value="True"/>
      <Setter Property="CanUserSortColumns" Value="True"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>
    <Style x:Key="HdrStyle" TargetType="DataGridColumnHeader">
      <Setter Property="Background" Value="#D0E4F7"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="6,3"/>
    </Style>
    <Style x:Key="RowStyle" TargetType="DataGridRow">
      <Setter Property="Background" Value="{Binding RowBg}"/>
    </Style>
  </Window.Resources>
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
      <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
    </Border>

    <Border Grid.Row="1" Background="#FAFCFF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="12,8">
      <StackPanel>
        <TextBlock x:Name="lbl_r1" FontSize="12" FontWeight="SemiBold" Foreground="#2F6496"/>
        <TextBlock x:Name="lbl_r2" FontSize="11" Foreground="#444444" Margin="0,3,0,0"/>
        <TextBlock x:Name="lbl_r3" FontSize="11" Foreground="#C0392B" Margin="0,3,0,0"
                   TextWrapping="Wrap" FontWeight="SemiBold"/>
      </StackPanel>
    </Border>

    <TabControl x:Name="tabs" Grid.Row="2" Margin="8,8,8,4" BorderBrush="#C0D0E0"
                Background="White">
      <TabItem x:Name="tab_cles">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <DataGrid x:Name="dg_cles" Grid.Row="0" Margin="0,6,0,6"
                    Style="{StaticResource GridStyle}"
                    ColumnHeaderStyle="{StaticResource HdrStyle}"
                    RowStyle="{StaticResource RowStyle}">
            <DataGrid.Columns>
              <DataGridTextColumn x:Name="k_cle"  Binding="{Binding Cle}"     Width="*" MinWidth="220"/>
              <DataGridTextColumn x:Name="k_src"  Binding="{Binding Source}"  Width="70"/>
              <DataGridTextColumn x:Name="k_tot"  Binding="{Binding Total}"   Width="90"/>
              <DataGridTextColumn x:Name="k_dis"  Binding="{Binding Dist}"    Width="130"/>
              <DataGridTextColumn x:Name="k_dbl"  Binding="{Binding Dbl}"     Width="130"/>
              <DataGridTextColumn x:Name="k_obj"  Binding="{Binding Obj}"     Width="130"/>
              <DataGridTextColumn x:Name="k_np"   Binding="{Binding NP}"      Width="110"/>
              <DataGridTextColumn x:Name="k_uni"  Binding="{Binding Unic}"    Width="90"/>
              <DataGridTextColumn x:Name="k_ver"  Binding="{Binding Verdict}" Width="170"/>
            </DataGrid.Columns>
          </DataGrid>
          <TextBlock x:Name="lbl_stab_t" Grid.Row="1" FontSize="12" FontWeight="SemiBold"
                     Foreground="#2F6496" Margin="2,10,0,4"/>
          <Border Grid.Row="2" BorderBrush="#C0D0E0" BorderThickness="1"
                  Background="#FAFCFF" Padding="10,8">
            <TextBlock x:Name="lbl_stab" FontSize="11" Foreground="#444444"
                       TextWrapping="Wrap"/>
          </Border>
        </Grid>
      </TabItem>

      <TabItem x:Name="tab_dup">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <Border Grid.Row="0" Background="#F0F6FF" BorderBrush="#C0D0E0"
                  BorderThickness="0,0,0,1" Padding="8,7">
            <StackPanel Orientation="Horizontal">
              <TextBlock x:Name="lbl_f1" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
              <ComboBox x:Name="cb_filtre" Width="190" Height="24" Margin="0,0,14,0"/>
              <TextBlock x:Name="lbl_f2" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
              <TextBox x:Name="tb_search" Width="220" Height="24" Margin="0,0,14,0"
                       VerticalContentAlignment="Center"/>
              <TextBlock x:Name="lbl_count" FontSize="11" Foreground="#2F6496"
                         VerticalAlignment="Center" FontWeight="SemiBold"/>
            </StackPanel>
          </Border>
          <DataGrid x:Name="dg_main" Grid.Row="1" Margin="0,6,0,0"
                    Style="{StaticResource GridStyle}"
                    ColumnHeaderStyle="{StaticResource HdrStyle}"
                    RowStyle="{StaticResource RowStyle}">
            <DataGrid.Columns>
              <DataGridTextColumn x:Name="col_num" Binding="{Binding Num}"     Width="110"/>
              <DataGridTextColumn x:Name="col_src" Binding="{Binding Source}"  Width="65"/>
              <DataGridTextColumn x:Name="col_ver" Binding="{Binding Verdict}" Width="150"/>
              <DataGridTextColumn x:Name="col_eca" Binding="{Binding Ecart}"   Width="85"/>
              <DataGridTextColumn x:Name="col_cle" Binding="{Binding Cle}"     Width="*" MinWidth="230"/>
              <DataGridTextColumn x:Name="col_fam" Binding="{Binding Fam}"     Width="*" MinWidth="150"/>
              <DataGridTextColumn x:Name="col_niv" Binding="{Binding Niv}"     Width="110"/>
              <DataGridTextColumn x:Name="col_val" Binding="{Binding Val}"     Width="90"/>
              <DataGridTextColumn x:Name="col_dem" Binding="{Binding Dem}"     Width="110"/>
              <DataGridTextColumn x:Name="col_id"  Binding="{Binding Id}"      Width="80"/>
            </DataGrid.Columns>
          </DataGrid>
        </Grid>
      </TabItem>

      <TabItem x:Name="tab_adn">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock x:Name="lbl_adn" Grid.Row="0" FontSize="11" Foreground="#444444"
                     Margin="2,8,0,6" TextWrapping="Wrap"/>
          <DataGrid x:Name="dg_adn" Grid.Row="1"
                    Style="{StaticResource GridStyle}"
                    ColumnHeaderStyle="{StaticResource HdrStyle}"
                    RowStyle="{StaticResource RowStyle}">
            <DataGrid.Columns>
              <DataGridTextColumn x:Name="a_src" Binding="{Binding Source}"   Width="60"/>
              <DataGridTextColumn x:Name="a_adn" Binding="{Binding Adn}"      Width="*" MinWidth="320"/>
              <DataGridTextColumn x:Name="a_num" Binding="{Binding Num}"      Width="105"/>
              <DataGridTextColumn x:Name="a_nup" Binding="{Binding NumP}"     Width="105"/>
              <DataGridTextColumn x:Name="a_coh" Binding="{Binding Coherent}" Width="140"/>
              <DataGridTextColumn x:Name="a_dat" Binding="{Binding Dat}"      Width="95"/>
              <DataGridTextColumn x:Name="a_heu" Binding="{Binding Heu}"      Width="80"/>
              <DataGridTextColumn x:Name="a_msr" Binding="{Binding MaqSR}"    Width="*" MinWidth="200"/>
            </DataGrid.Columns>
          </DataGrid>
        </Grid>
      </TabItem>
    </TabControl>

    <Border Grid.Row="3" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_export" Width="150" Height="28" Margin="4,0,0,0"
                  Background="#E67E22" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close" Width="90" Height="28" Margin="6,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

    def run_window(rows_dup, rows_cle, rows_adn, rows_adn_all, resume, stats, stab):
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        win = System.Windows.Markup.XamlReader.Load(stream)

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        win.FindName("lbl_footer").Text = _FOOTER

        win.FindName("tab_cles").Header = u"Clés candidates"
        win.FindName("tab_dup").Header  = u"Doublons de n°"
        win.FindName("tab_adn").Header  = u"ADN décomposé"

        win.FindName("lbl_r1").Text = (
            u"Lien SPV : {} n° en doublon ({} objets)   |   "
            u"Maquette STR : {} n° en doublon ({} objets)".format(
                stats["spv_num"], stats["spv_obj"], stats["str_num"], stats["str_obj"]))
        win.FindName("lbl_r2").Text = (
            u"Sans n° (ignorés par la synchro) — SPV : {}   |   STR : {}       "
            u"Tolérance de position : {:.0f} cm".format(
                stats["spv_sans"], stats["str_sans"], TOL_POSITION_CM))

        perdues = stats["spv_diff"] + stats["str_diff"]
        if perdues:
            win.FindName("lbl_r3").Text = (
                u"⚠ {} groupe(s) à positions différentes : autant de réservations "
                u"réellement perdues par la synchronisation.".format(perdues))
        else:
            win.FindName("lbl_r3").Text = (
                u"Tous les groupes sont à la même position : doublons superposés, "
                u"aucune réservation perdue.")

        for nm, txt in ((u"k_cle", u"Clé candidate"), (u"k_src", u"Source"),
                        (u"k_tot", u"Éléments"), (u"k_dis", u"Valeurs distinctes"),
                        (u"k_dbl", u"Valeurs en doublon"), (u"k_obj", u"Objets concernés"),
                        (u"k_np", u"Non parsables"), (u"k_uni", u"Unicité"),
                        (u"k_ver", u"Verdict"),
                        (u"col_num", u"N° réservation"), (u"col_src", u"Source"),
                        (u"col_ver", u"Verdict groupe"), (u"col_eca", u"Écart (cm)"),
                        (u"col_cle", u"Clé n° + maquette"), (u"col_fam", u"Famille"),
                        (u"col_niv", u"Niveau"), (u"col_val", u"Statut VAL"),
                        (u"col_dem", u"Demandeur"), (u"col_id", u"Id Revit"),
                        (u"a_src", u"Source"), (u"a_adn", u"ADN complet"),
                        (u"a_num", u"N° (ADN)"), (u"a_nup", u"N° (paramètre)"),
                        (u"a_coh", u"Cohérence"), (u"a_dat", u"Date"),
                        (u"a_heu", u"Heure"), (u"a_msr", u"Maquette sans révision")):
            c = win.FindName(nm)
            if c is not None:
                c.Header = txt

        win.FindName("lbl_f1").Text = u"Filtre :"
        win.FindName("lbl_f2").Text = u"Recherche :"
        win.FindName("btn_export").Content = u"Exporter Excel"
        win.FindName("btn_close").Content  = u"Fermer"

        win.FindName("lbl_stab_t").Text = u"Stabilité de l'ADN entre le lien et la maquette STR"
        if stab["communs"] == 0:
            txt_stab = (u"Aucune réservation appariable : il faut un n° présent des deux "
                        u"côtés et non dupliqué pour pouvoir comparer.")
        else:
            txt_stab = (
                u"{} réservation(s) appariée(s) par n° unique.\n"
                u"ADN identique entre SPV et STR : {}   |   ADN différent : {}   |   "
                u"ADN absent d'un côté : {}\n"
                u"Clé « n° + maquette » identique : {}   |   différente : {}".format(
                    stab["communs"], stab["adn_id"], stab["adn_diff"],
                    stab["adn_vide"], stab["cle_id"], stab["cle_diff"]))
            if stab["adn_diff"]:
                txt_stab += u"\n\nExemples d'ADN divergents :\n" + u"\n".join(stab["exemples"])
            if stab["adn_diff"] and not stab["cle_diff"]:
                txt_stab += (u"\n\n→ L'ADN brut bouge entre le lien et la STR, mais la clé "
                             u"« n° + maquette » tient. C'est exactement le comportement "
                             u"attendu : l'ADN est une empreinte de soumission, la clé est "
                             u"une identité.")
        win.FindName("lbl_stab").Text = txt_stab

        win.FindName("lbl_adn").Text = (
            u"Structure : n° _ date _ heure _ STATUT _ n _ maquette d'origine _ révision.   "
            u"{} ligne(s) affichée(s) sur {} — l'export Excel est complet.".format(
                len(rows_adn), len(rows_adn_all)))

        win.FindName("dg_cles").ItemsSource = rows_cle
        win.FindName("dg_adn").ItemsSource  = rows_adn

        cb = win.FindName("cb_filtre")
        for f in FILTRES:
            cb.Items.Add(f)
        cb.SelectedIndex = 0

        dg = win.FindName("dg_main")
        tb = win.FindName("tb_search")
        lbl_count = win.FindName("lbl_count")

        def visibles():
            f = cb.SelectedItem or FILTRES[0]
            q = (tb.Text or u"").strip().lower()
            out = []
            for r in rows_dup:
                if f == FILTRES[1] and r.Verdict != VERDICT_DIFF:
                    continue
                if f == FILTRES[2] and r.Verdict != VERDICT_MEME:
                    continue
                if f == FILTRES[3] and r.Source != SRC_SPV:
                    continue
                if f == FILTRES[4] and r.Source != SRC_STR:
                    continue
                if q:
                    blob = u" ".join([r.Num, r.Fam, r.Typ, r.Niv, r.Dem,
                                      r.Val, r.Id, r.Cle]).lower()
                    if q not in blob:
                        continue
                out.append(r)
            return out

        def refresh(sender=None, e=None):
            vis = visibles()
            dg.ItemsSource = None
            dg.ItemsSource = vis
            lbl_count.Text = u"{} ligne(s) affichée(s) sur {}".format(len(vis), len(rows_dup))

        cb.SelectionChanged += refresh
        tb.TextChanged      += refresh

        def on_export(s, e):
            try:
                clr.AddReference("System.Windows.Forms")
                from System.Windows.Forms import SaveFileDialog, DialogResult
                dlg = SaveFileDialog()
                dlg.Title    = "Exporter l'audit des identifiants"
                dlg.Filter   = "Classeur Excel (*.xlsx)|*.xlsx"
                dlg.FileName = "Audit_identifiants_reservations.xlsx"
                prefs = _load_prefs()
                last  = prefs.get("last_folder", u"")
                if last and os.path.isdir(last):
                    dlg.InitialDirectory = last
                if dlg.ShowDialog() != DialogResult.OK or not dlg.FileName:
                    return
                exporter_excel(visibles(), rows_cle, rows_adn_all, resume, dlg.FileName)
                prefs["last_folder"] = os.path.dirname(dlg.FileName)
                _save_prefs(prefs)
                SW.MessageBox.Show(u"Export réussi :\n{}".format(dlg.FileName),
                                   TOOL_NAME, SW.MessageBoxButton.OK,
                                   SW.MessageBoxImage.Information)
            except Exception as ex:
                SW.MessageBox.Show(u"Erreur d'export :\n{}".format(ex), TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Error)

        win.FindName("btn_export").Click += on_export
        win.FindName("btn_close").Click  += lambda s, e: win.Close()

        refresh()
        win.ShowDialog()

    # =========================================================================
    # MAIN
    # =========================================================================
    def main():
        lnk = find_link_instance()
        if lnk is None:
            TaskDialog.Show(TOOL_NAME,
                            u"Lien « {}* » introuvable : seule la maquette STR "
                            u"sera analysee.".format(LINK_MODEL_PREFIX))
            link_elems = []
        else:
            link_elems = collect_link(lnk)

        host_elems = collect_host()
        if not link_elems and not host_elems:
            TaskDialog.Show(TOOL_NAME, u"Aucune reservation a analyser.")
            return

        pop_l = lire_population(link_elems, SRC_SPV)
        pop_h = lire_population(host_elems, SRC_STR)

        rows_cle = []
        if pop_l:
            rows_cle += analyser_cles(pop_l, SRC_SPV)
        if pop_h:
            rows_cle += analyser_cles(pop_h, SRC_STR)

        stab = analyser_stabilite(pop_l, pop_h)

        rows_l, n_l, o_l, s_l, d_l = analyser_doublons(pop_l, SRC_SPV)
        rows_h, n_h, o_h, s_h, d_h = analyser_doublons(pop_h, SRC_STR)
        rows_dup = rows_l + rows_h

        rows_adn_all = []
        for d in pop_l + pop_h:
            rows_adn_all.append(AdnRow(d["source"], d["el"], d["adn"],
                                       d["info"], d["num_p"]))
        # Les valeurs anormales d'abord : c'est ce qu'on vient regarder.
        rows_adn_all.sort(key=lambda r: (r.Coherent == u"ok", r.Source, r.Adn))
        rows_adn = rows_adn_all[:MAX_LIGNES_ADN]

        stats = {"spv_num": n_l, "spv_obj": o_l, "spv_sans": s_l, "spv_diff": d_l,
                 "str_num": n_h, "str_obj": o_h, "str_sans": s_h, "str_diff": d_h}

        def _cle_stat(source, libelle, attr):
            for r in rows_cle:
                if r.Source == source and r.Cle == libelle:
                    return getattr(r, attr)
            return u"-"

        resume = [
            (u"Date de l'audit", System.DateTime.Now.ToString("dd/MM/yyyy HH:mm")),
            (u"Maquette STR", doc.Title),
            (u"Lien SPV", _safe_name(lnk) if lnk is not None else u"(absent)"),
            (u"", u""),
            (u"Réservations analysées — lien SPV", len(link_elems)),
            (u"Réservations analysées — maquette STR", len(host_elems)),
            (u"", u""),
            (u"UNICITE DES CLES CANDIDATES (lien SPV)", u""),
            (u"   N° réservation — valeurs en doublon",
             _cle_stat(SRC_SPV, u"N° réservation (clé actuelle)", "Dbl")),
            (u"   ADN brut — valeurs en doublon",
             _cle_stat(SRC_SPV, u"ADN brut", "Dbl")),
            (u"   N° + maquette — valeurs en doublon",
             _cle_stat(SRC_SPV, u"N° + maquette d'origine", "Dbl")),
            (u"   N° + maquette — ADN non parsables",
             _cle_stat(SRC_SPV, u"N° + maquette d'origine", "NP")),
            (u"", u""),
            (u"STABILITE ENTRE LIEN ET STR", u""),
            (u"   Réservations appariées par n° unique", stab["communs"]),
            (u"   ADN identique", stab["adn_id"]),
            (u"   ADN différent", stab["adn_diff"]),
            (u"   Clé n° + maquette identique", stab["cle_id"]),
            (u"   Clé n° + maquette différente", stab["cle_diff"]),
            (u"", u""),
            (u"DOUBLONS DE N°", u""),
            (u"   N° en doublon — lien SPV", n_l),
            (u"   Objets concernés — lien SPV", o_l),
            (u"   Groupes à positions différentes — lien SPV", d_l),
            (u"   Sans n° — lien SPV", s_l),
            (u"   N° en doublon — maquette STR", n_h),
            (u"   Objets concernés — maquette STR", o_h),
            (u"   Groupes à positions différentes — maquette STR", d_h),
            (u"   Sans n° — maquette STR", s_h),
            (u"", u""),
            (u"Tolérance de position (cm)", TOL_POSITION_CM),
            (u"Réservations perdues par la synchro", d_l + d_h),
        ]

        run_window(rows_dup, rows_cle, rows_adn, rows_adn_all, resume, stats, stab)

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
