# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.2.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Rechercher Reservation"
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
    from System.Collections.Generic import List as ClrList

    from Autodesk.Revit.DB import (
        FilteredElementCollector, FamilyInstance, Family, RevitLinkInstance,
        BuiltInParameter, StorageType, ElementId, XYZ, BoundingBoxXYZ,
        View3D, ViewFamilyType, ViewFamily, Transaction, TransactionStatus,
        UnitUtils, UnitTypeId
    )

    import xlsxwriter

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # CONSTANTES METIER
    # =========================================================================
    FAMILY_PREFIX    = "FGH_RES"
    ADN_PARAM        = "CONTROL_NE_PAS_TOUCHER"
    PARAM_NUM        = "PVA_RES_DEM_NumReservation"
    PARAM_DEMANDEUR  = "PVA_RES_DEM_Demandeur"
    PARAM_DATE       = "PVA_RES_DEM_Date"
    PARAM_NIVEAU     = "WSP_NiveauAssocie"
    PARAM_VAL_STATUT = "PVA_RES_VAL_Statut"
    PARAM_VAL_DATE   = "PVA_RES_VAL_Date"
    PARAM_COMMENT    = "PVA_RES_DEM_Commentaire"

    SRC_LOCALE = u"Maquette courante"

    VIEW_3D_NAME  = "STR_Recherche_Reservations"
    VIEW_3D_MARGE = 1.0   # metres autour de la boite englobante

    # Structure de l'ADN : <N°>_<date>_<heure>_STATUT_<n>_<maquette>_R<rev>
    # Le N° porte par l'ADN peut differer du parametre (3 cas mesures sur 5805) :
    # la recherche interroge donc les deux.
    ADN_SEG_STATUT  = u"STATUT"
    ADN_RE_REVISION = r"_R\d+$"

    # La liste des parametres proposes est construite a partir des reservations
    # reellement presentes : aucune liste figee a maintenir.
    PARAM_DEFAUT = PARAM_NUM

    MODES = [u"contient", u"exact", u"commence par"]

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")
    _LAZY = {}

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

    def _p_str_any(el, pname):
        """Valeur d'un parametre d'occurrence, a defaut du type."""
        v = _p_str(el, pname)
        if v:
            return v
        try:
            t = el.Document.GetElement(el.GetTypeId())
            if t is not None:
                return _p_str(t, pname)
        except Exception:
            pass
        return u""

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

    def _re_revision():
        if "rev" not in _LAZY:
            _LAZY["rev"] = re.compile(ADN_RE_REVISION)
        return _LAZY["rev"]

    def parse_adn(adn):
        """(numero, maquette sans revision) ou (u"", u"") si non parsable."""
        if not adn:
            return u"", u""
        parts = adn.split(u"_")
        try:
            i = parts.index(ADN_SEG_STATUT)
        except ValueError:
            return u"", u""
        if i < 2 or len(parts) < i + 3:
            return u"", u""
        return parts[0], _re_revision().sub(u"", u"_".join(parts[i + 2:]))

    def _norm(txt):
        return (txt or u"").strip().lower().replace(u" ", u"")

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
    # COLLECTE — maquette courante + tous les liens charges
    # =========================================================================
    def _a_des_familles_res(document):
        """Pre-filtre : inutile de balayer un lien qui n'a aucune famille FGH_RES."""
        try:
            for f in FilteredElementCollector(document).OfClass(Family):
                if _safe_name(f).startswith(FAMILY_PREFIX):
                    return True
        except Exception:
            pass
        return False

    def _collect_dans(document):
        res = []
        try:
            for e in FilteredElementCollector(document).OfClass(FamilyInstance).ToElements():
                try:
                    if _family_name(e).startswith(FAMILY_PREFIX):
                        res.append(e)
                except Exception:
                    pass
        except Exception:
            pass
        return res

    def collecter_sources():
        """
        Retourne [(libelle_source, document, transform_ou_None, elements)].
        Fonctionne indifferemment depuis la maquette STR (copies locales + lien
        SPV) et depuis la maquette de percement (reservations locales).
        """
        sources = []
        locaux = _collect_dans(doc)
        if locaux:
            sources.append((SRC_LOCALE, doc, None, locaux))

        for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
            try:
                ldoc = lnk.GetLinkDocument()
                if ldoc is None:
                    continue
                if not _a_des_familles_res(ldoc):
                    continue
                elems = _collect_dans(ldoc)
                if elems:
                    sources.append((u"Lien : {}".format(_safe_name(lnk)),
                                    ldoc, lnk.GetTotalTransform(), elems))
            except Exception:
                pass
        return sources

    def lister_parametres(sources):
        """
        Noms de tous les parametres interrogeables, occurrence et type confondus.
        Echantillonne une occurrence par type de famille : les parametres sont
        identiques d'une occurrence a l'autre, inutile de balayer 5000 elements.
        """
        noms      = set()
        vus_types = set()
        for libelle, document, transform, elems in sources:
            for e in elems:
                try:
                    tid = _eid_int(e.GetTypeId())
                    if tid in vus_types:
                        continue
                    vus_types.add(tid)
                    cibles = [e]
                    try:
                        t = document.GetElement(e.GetTypeId())
                        if t is not None:
                            cibles.append(t)
                    except Exception:
                        pass
                    for src in cibles:
                        for p in src.Parameters:
                            try:
                                nom = p.Definition.Name
                                if nom:
                                    noms.add(nom)
                            except Exception:
                                pass
                except Exception:
                    pass
        return sorted(noms, key=lambda n: n.lower())

    # =========================================================================
    # RECHERCHE
    # =========================================================================
    def correspond(valeurs, terme, mode):
        """Une des valeurs correspond-elle au terme selon le mode choisi ?"""
        t = _norm(terme)
        if not t:
            return False
        for v in valeurs:
            n = _norm(v)
            if not n:
                continue
            if mode == u"exact" and n == t:
                return True
            if mode == u"commence par" and n.startswith(t):
                return True
            if mode == u"contient" and t in n:
                return True
        return False

    class ResRow(object):
        """Une reservation trouvee."""
        def __init__(self, source, el, transform, criteres):
            self._el        = el
            self._transform = transform
            self._local     = transform is None

            # Une colonne de valeur par critere actif ; les autres restent vides
            # et leur colonne est masquee.
            self.Val1 = self.Val2 = self.Val3 = u""
            for i, (param, mode, terme) in enumerate(criteres[:3]):
                setattr(self, u"Val{}".format(i + 1), _p_str_any(el, param))
            self.Source = source
            self.Adn    = _p_str(el, ADN_PARAM)
            num_adn, maq = parse_adn(self.Adn)
            self.Num    = _p_str(el, PARAM_NUM)
            self.NumAdn = num_adn
            self.Maq    = maq
            self.Fam    = _family_name(el)
            self.Typ    = _type_name(el)
            self.Niv    = _p_str(el, PARAM_NIVEAU)
            self.Val    = _p_str(el, PARAM_VAL_STATUT)
            self.ValDat = _p_str(el, PARAM_VAL_DATE)
            self.Dem    = _p_str(el, PARAM_DEMANDEUR)
            self.Dat    = _p_str(el, PARAM_DATE)
            self.Com    = _p_str(el, PARAM_COMMENT)
            self.Id     = u"{}".format(_eid_int(el.Id))

            p = self._point()
            self.X = u"{:.3f}".format(_to_m(p.X)) if p is not None else u""
            self.Y = u"{:.3f}".format(_to_m(p.Y)) if p is not None else u""
            self.Z = u"{:.3f}".format(_to_m(p.Z)) if p is not None else u""

            if self.NumAdn and self.Num and self.NumAdn != self.Num:
                self.Coherence = u"n° ADN ≠ paramètre"
                self.RowBg = "#FFF3CD"
            elif not self.Adn:
                self.Coherence = u"sans ADN"
                self.RowBg = "#FDDEDE"
            else:
                self.Coherence = u"ok"
                self.RowBg = "#FFFFFF"

        def _point(self):
            """Point d'insertion, ramene en coordonnees de la maquette courante."""
            p = None
            try:
                loc = self._el.Location
                if loc is not None:
                    p = getattr(loc, "Point", None)
            except Exception:
                p = None
            if p is None:
                bb = self.bbox_locale()
                if bb is None:
                    return None
                return XYZ((bb.Min.X + bb.Max.X) / 2.0,
                           (bb.Min.Y + bb.Max.Y) / 2.0,
                           (bb.Min.Z + bb.Max.Z) / 2.0)
            if self._transform is not None:
                try:
                    p = self._transform.OfPoint(p)
                except Exception:
                    pass
            return p

        def bbox_locale(self):
            try:
                return self._el.get_BoundingBox(None)
            except Exception:
                return None

        def coins_monde(self):
            """8 sommets de la boite englobante, en coordonnees maquette courante."""
            bb = self.bbox_locale()
            if bb is None:
                return []
            pts = []
            for x in (bb.Min.X, bb.Max.X):
                for y in (bb.Min.Y, bb.Max.Y):
                    for z in (bb.Min.Z, bb.Max.Z):
                        p = XYZ(x, y, z)
                        if bb.Transform is not None:
                            try:
                                p = bb.Transform.OfPoint(p)
                            except Exception:
                                pass
                        if self._transform is not None:
                            try:
                                p = self._transform.OfPoint(p)
                            except Exception:
                                pass
                        pts.append(p)
            return pts

    def _satisfait(e, param, mode, terme):
        valeurs = [_p_str_any(e, param)]
        # Le N° est porte a la fois par le parametre et par l'ADN, et les deux
        # divergent parfois : chercher un N° interroge aussi celui de l'ADN,
        # sinon la reservation reste introuvable.
        if param == PARAM_NUM:
            num_adn, _ = parse_adn(_p_str(e, ADN_PARAM))
            valeurs.append(num_adn)
        return correspond(valeurs, terme, mode)

    def rechercher(sources, criteres):
        """
        criteres : liste de (parametre, mode, terme) — les lignes laissees vides
        sont ignorees en amont. Les criteres se cumulent en ET : une reservation
        n'est retenue que si elle les satisfait tous.
        """
        rows = []
        if not criteres:
            return rows
        for libelle, document, transform, elems in sources:
            for e in elems:
                try:
                    garde = True
                    for param, mode, terme in criteres:
                        if not _satisfait(e, param, mode, terme):
                            garde = False
                            break
                    if garde:
                        rows.append(ResRow(libelle, e, transform, criteres))
                except Exception:
                    pass
        rows.sort(key=lambda r: (r.Val1, r.Val2, r.Val3, r.Num, r.Source, r.Id))
        return rows

    # =========================================================================
    # ACTIONS SUR LE MODELE
    # =========================================================================
    def selectionner(rows):
        """Selectionne et cadre les reservations locales. Retourne (nb, nb_liens)."""
        ids = ClrList[ElementId]()
        n_local = n_lien = 0
        for r in rows:
            if r._local:
                ids.Add(r._el.Id)
                n_local += 1
            else:
                n_lien += 1
        if n_local:
            try:
                uidoc.Selection.SetElementIds(ids)
                uidoc.ShowElements(ids)
            except Exception:
                pass
        return n_local, n_lien

    def _vue_3d_existante():
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if not v.IsTemplate and _safe_name(v) == VIEW_3D_NAME:
                    return v
            except Exception:
                pass
        return None

    def _type_vue_3d():
        for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            try:
                if t.ViewFamily == ViewFamily.ThreeDimensional:
                    return t
            except Exception:
                pass
        return None

    def cadrer_en_3d(rows):
        """
        Vue 3D dediee, boite de coupe autour des reservations trouvees.
        Fonctionne aussi pour des elements de lien, que l'on ne peut ni
        selectionner ni isoler mais que l'on peut cadrer.
        """
        pts = []
        for r in rows:
            pts.extend(r.coins_monde())
        if not pts:
            return None, u"Aucune géométrie exploitable pour cadrer."

        marge = VIEW_3D_MARGE / 0.3048
        mnx = min(p.X for p in pts) - marge
        mny = min(p.Y for p in pts) - marge
        mnz = min(p.Z for p in pts) - marge
        mxx = max(p.X for p in pts) + marge
        mxy = max(p.Y for p in pts) + marge
        mxz = max(p.Z for p in pts) + marge

        vue = _vue_3d_existante()
        t = Transaction(doc, u"STR - Vue 3D recherche réservations")
        t.Start()
        try:
            if vue is None:
                vft = _type_vue_3d()
                if vft is None:
                    t.RollBack()
                    return None, u"Aucun type de vue 3D disponible dans le projet."
                vue = View3D.CreateIsometric(doc, vft.Id)
                try:
                    vue.Name = VIEW_3D_NAME
                except Exception:
                    pass
            bb = BoundingBoxXYZ()
            bb.Min = XYZ(mnx, mny, mnz)
            bb.Max = XYZ(mxx, mxy, mxz)
            vue.IsSectionBoxActive = True
            vue.SetSectionBox(bb)
            t.Commit()
        except Exception as ex:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            return None, u"Création de la vue impossible : {}".format(ex)

        # Le changement de vue active se fait hors transaction
        try:
            uidoc.ActiveView = vue
        except Exception:
            pass
        return vue, u""

    # =========================================================================
    # EXPORT
    # =========================================================================
    COLS_BASE = [
        (u"Source", "Source", 30), (u"N° (paramètre)", "Num", 16),
        (u"N° (ADN)", "NumAdn", 16), (u"Cohérence", "Coherence", 20),
        (u"Famille", "Fam", 26), (u"Type", "Typ", 20),
        (u"Niveau", "Niv", 16), (u"Statut VAL", "Val", 14),
        (u"Date validation", "ValDat", 16),
        (u"Demandeur", "Dem", 16), (u"Date demande", "Dat", 14),
        (u"Commentaire", "Com", 34),
        (u"Maquette d'origine", "Maq", 30),
        (u"X (m)", "X", 12), (u"Y (m)", "Y", 12), (u"Z (m)", "Z", 12),
        (u"ADN complet", "Adn", 70), (u"Id Revit", "Id", 12),
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

    def exporter(rows, criteres, chemin):
        # Une colonne par critere actif, en tete du tableau, puis les colonnes fixes.
        cols = []
        for i, (param, mode, terme) in enumerate(criteres[:3]):
            cols.append((param, u"Val{}".format(i + 1), 26))
        cols = cols + COLS_BASE

        wb = xlsxwriter.Workbook(chemin)
        fmt_hdr = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                 "font_color": "#FFFFFF", "border": 1,
                                 "align": "center", "valign": "vcenter",
                                 "text_wrap": True})
        fmt_std  = wb.add_format({"border": 1})
        fmt_alt  = wb.add_format({"bg_color": "#E8F0FA", "border": 1})
        fmt_warn = wb.add_format({"bg_color": "#FFF3CD", "border": 1})
        fmt_ko   = wb.add_format({"bg_color": "#FDDEDE", "border": 1})
        fmt_tit  = wb.add_format({"bold": True, "font_size": 12,
                                  "font_color": "#2F6496"})

        ws = wb.add_worksheet(u"Recherche")
        for i, (titre, attr, largeur) in enumerate(cols):
            ws.set_column(i, i, largeur)
            ws.write(0, i, titre, fmt_hdr)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, max(len(rows), 1), len(cols) - 1)
        for r, row in enumerate(rows, start=1):
            bg = getattr(row, "RowBg", "#FFFFFF")
            fmt = fmt_ko if bg == "#FDDEDE" else (
                  fmt_warn if bg == "#FFF3CD" else (
                  fmt_alt if (r % 2 == 0) else fmt_std))
            for c, (titre, attr, largeur) in enumerate(cols):
                ws.write(r, c, _cell_value(getattr(row, attr, u"")), fmt)

        ws2 = wb.add_worksheet(u"Resume")
        ws2.set_column(0, 0, 46)
        ws2.set_column(1, 1, 40)
        ws2.write(0, 0, u"Recherche de réservations", fmt_tit)
        lignes = [(u"Date", System.DateTime.Now.ToString("dd/MM/yyyy HH:mm")),
                  (u"Maquette", doc.Title),
                  (u"Critères cumulés (ET)", len(criteres))]
        for i, (param, mode, terme) in enumerate(criteres[:3], start=1):
            lignes.append((u"   Critère {} — paramètre".format(i), param))
            lignes.append((u"   Critère {} — {}".format(i, mode), terme))
        lignes.append((u"Résultats", len(rows)))
        for i, (lib, val) in enumerate(lignes, start=2):
            ws2.write(i, 0, lib, fmt_std)
            ws2.write(i, 1, _cell_value(val), fmt_std)
        wb.close()

    # =========================================================================
    # UI
    # =========================================================================
    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1450" Height="700" MinWidth="900" MinHeight="500"
    WindowStartupLocation="CenterScreen" Background="White" ResizeMode="CanResize">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#2F6496" Padding="14,9">
      <TextBlock x:Name="lbl_titre" FontSize="13" FontWeight="SemiBold" Foreground="White"/>
    </Border>

    <Border Grid.Row="1" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="10,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock x:Name="lbl_crit" Grid.Row="0" Grid.Column="0" FontSize="11"
                   VerticalAlignment="Center" Margin="0,0,6,0"/>
        <ComboBox x:Name="cb_param1" Grid.Row="0" Grid.Column="1" Width="250" Height="26"
                  Margin="0,0,10,0" IsTextSearchEnabled="True" MaxDropDownHeight="420"/>
        <ComboBox x:Name="cb_mode1" Grid.Row="0" Grid.Column="2" Width="120" Height="26"
                  Margin="0,0,10,0"/>
        <TextBox x:Name="tb_terme1" Grid.Row="0" Grid.Column="3" Width="230" Height="26"
                 Margin="0,0,10,0" FontSize="13" VerticalContentAlignment="Center"/>
        <Button x:Name="btn_go" Grid.Row="0" Grid.Column="4" Grid.RowSpan="3"
                Width="120" Height="26" Margin="4,0,14,0" VerticalAlignment="Center"
                Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        <TextBlock x:Name="lbl_count" Grid.Row="0" Grid.Column="5" Grid.RowSpan="3"
                   FontSize="11" Foreground="#2F6496" TextWrapping="Wrap"
                   VerticalAlignment="Center" FontWeight="SemiBold"/>

        <TextBlock x:Name="lbl_et2" Grid.Row="1" Grid.Column="0" FontSize="11"
                   VerticalAlignment="Center" Margin="0,6,6,0" Foreground="#2F6496"/>
        <ComboBox x:Name="cb_param2" Grid.Row="1" Grid.Column="1" Width="250" Height="26"
                  Margin="0,6,10,0" IsTextSearchEnabled="True" MaxDropDownHeight="420"/>
        <ComboBox x:Name="cb_mode2" Grid.Row="1" Grid.Column="2" Width="120" Height="26"
                  Margin="0,6,10,0"/>
        <TextBox x:Name="tb_terme2" Grid.Row="1" Grid.Column="3" Width="230" Height="26"
                 Margin="0,6,10,0" FontSize="13" VerticalContentAlignment="Center"/>

        <TextBlock x:Name="lbl_et3" Grid.Row="2" Grid.Column="0" FontSize="11"
                   VerticalAlignment="Center" Margin="0,6,6,0" Foreground="#2F6496"/>
        <ComboBox x:Name="cb_param3" Grid.Row="2" Grid.Column="1" Width="250" Height="26"
                  Margin="0,6,10,0" IsTextSearchEnabled="True" MaxDropDownHeight="420"/>
        <ComboBox x:Name="cb_mode3" Grid.Row="2" Grid.Column="2" Width="120" Height="26"
                  Margin="0,6,10,0"/>
        <TextBox x:Name="tb_terme3" Grid.Row="2" Grid.Column="3" Width="230" Height="26"
                 Margin="0,6,10,0" FontSize="13" VerticalContentAlignment="Center"/>
      </Grid>
    </Border>

    <Border Grid.Row="2" Background="#FAFCFF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="12,6">
      <TextBlock x:Name="lbl_src" FontSize="11" Foreground="#444444" TextWrapping="Wrap"/>
    </Border>

    <DataGrid x:Name="dg_main" Grid.Row="3" Margin="8,8,8,4"
              AutoGenerateColumns="False" IsReadOnly="True"
              GridLinesVisibility="Horizontal" BorderBrush="#C0D0E0"
              HeadersVisibility="Column" SelectionMode="Extended"
              CanUserResizeColumns="True" CanUserSortColumns="True" FontSize="12">
      <DataGrid.RowStyle>
        <Style TargetType="DataGridRow">
          <Setter Property="Background" Value="{Binding RowBg}"/>
        </Style>
      </DataGrid.RowStyle>
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#D0E4F7"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,3"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <DataGridTextColumn x:Name="c_v1"  Binding="{Binding Val1}"      Width="*" MinWidth="120"/>
        <DataGridTextColumn x:Name="c_v2"  Binding="{Binding Val2}"      Width="120" Visibility="Collapsed"/>
        <DataGridTextColumn x:Name="c_v3"  Binding="{Binding Val3}"      Width="120" Visibility="Collapsed"/>
        <DataGridTextColumn x:Name="c_src" Binding="{Binding Source}"    Width="*" MinWidth="130"/>
        <DataGridTextColumn x:Name="c_num" Binding="{Binding Num}"       Width="85"/>
        <DataGridTextColumn x:Name="c_nua" Binding="{Binding NumAdn}"    Width="85"/>
        <DataGridTextColumn x:Name="c_coh" Binding="{Binding Coherence}" Width="95"/>
        <DataGridTextColumn x:Name="c_fam" Binding="{Binding Fam}"       Width="130"/>
        <DataGridTextColumn x:Name="c_niv" Binding="{Binding Niv}"       Width="95"/>
        <DataGridTextColumn x:Name="c_val" Binding="{Binding Val}"       Width="75"/>
        <DataGridTextColumn x:Name="c_dem" Binding="{Binding Dem}"       Width="85"/>
        <DataGridTextColumn x:Name="c_x"   Binding="{Binding X}"         Width="65"/>
        <DataGridTextColumn x:Name="c_y"   Binding="{Binding Y}"         Width="65"/>
        <DataGridTextColumn x:Name="c_z"   Binding="{Binding Z}"         Width="65"/>
        <DataGridTextColumn x:Name="c_id"  Binding="{Binding Id}"        Width="65"/>
      </DataGrid.Columns>
    </DataGrid>

    <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_sel" Width="150" Height="28" Margin="4,0,0,0"
                  Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_3d" Width="110" Height="28" Margin="6,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_exp" Width="130" Height="28" Margin="6,0,0,0"
                  Background="#E67E22" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close" Width="90" Height="28" Margin="6,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

    def run_window(sources, parametres):
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        win = System.Windows.Markup.XamlReader.Load(stream)

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text  = u"{}  |  Revit {}".format(TOOL_NAME, app.VersionNumber)
        win.FindName("lbl_footer").Text = _FOOTER
        win.FindName("lbl_crit").Text   = u"Paramètre :"
        win.FindName("btn_go").Content  = u"Rechercher"
        win.FindName("btn_sel").Content = u"Sélectionner et cadrer"
        win.FindName("btn_3d").Content  = u"Vue 3D"
        win.FindName("btn_exp").Content = u"Exporter Excel"
        win.FindName("btn_close").Content = u"Fermer"

        win.FindName("lbl_et2").Text = u"et"
        win.FindName("lbl_et3").Text = u"et"

        for nm, txt in ((u"c_src", u"Source"), (u"c_num", u"N° réservation"),
                        (u"c_nua", u"N° (ADN)"), (u"c_coh", u"Cohérence"),
                        (u"c_fam", u"Famille"), (u"c_niv", u"Niveau"),
                        (u"c_val", u"Statut VAL"), (u"c_dem", u"Demandeur"),
                        (u"c_x", u"X (m)"), (u"c_y", u"Y (m)"), (u"c_z", u"Z (m)"),
                        (u"c_id", u"Id Revit")):
            c = win.FindName(nm)
            if c is not None:
                c.Header = txt
        cols_valeur = [win.FindName(u"c_v1"), win.FindName(u"c_v2"), win.FindName(u"c_v3")]

        detail = u"   |   ".join([u"{} : {} réservation(s)".format(s[0], len(s[3]))
                                  for s in sources])
        win.FindName("lbl_src").Text = u"Sources interrogées — " + detail

        prefs = _load_prefs()

        def _defaut_param(i):
            """Ligne 1 : dernier paramètre utilisé, sinon le n°. Lignes 2 et 3 : vides."""
            if i > 0:
                return prefs.get(u"parametre{}".format(i + 1), u"")
            voulu = prefs.get("parametre", PARAM_DEFAUT)
            if voulu not in parametres:
                voulu = PARAM_DEFAUT if PARAM_DEFAUT in parametres else parametres[0]
            return voulu

        cb_pars, cb_modes, tbs = [], [], []
        for i in range(3):
            cbp = win.FindName(u"cb_param{}".format(i + 1))
            for p in parametres:
                cbp.Items.Add(p)
            voulu = _defaut_param(i)
            try:
                cbp.SelectedIndex = parametres.index(voulu) if voulu in parametres else (
                    0 if i == 0 else -1)
            except Exception:
                cbp.SelectedIndex = 0 if i == 0 else -1
            cb_pars.append(cbp)

            cbm = win.FindName(u"cb_mode{}".format(i + 1))
            for m in MODES:
                cbm.Items.Add(m)
            try:
                cbm.SelectedIndex = MODES.index(
                    prefs.get(u"mode{}".format(i + 1), prefs.get("mode", MODES[0])))
            except Exception:
                cbm.SelectedIndex = 0
            cb_modes.append(cbm)

            tbs.append(win.FindName(u"tb_terme{}".format(i + 1)))

        dg        = win.FindName("dg_main")
        tb        = tbs[0]
        lbl_count = win.FindName("lbl_count")
        etat      = {"rows": [], "criteres": []}

        def _criteres_actifs():
            """Lignes réellement renseignées : paramètre choisi ET valeur saisie."""
            actifs = []
            for i in range(3):
                param = cb_pars[i].SelectedItem
                terme = (tbs[i].Text or u"").strip()
                if param and terme:
                    actifs.append((param, cb_modes[i].SelectedItem or MODES[0], terme))
            return actifs

        def lancer(sender=None, e=None):
            criteres = _criteres_actifs()
            etat["criteres"] = criteres

            # Une colonne de valeur par critère actif, les autres masquées.
            # Un en-tête WPF interprète le premier "_" comme touche d'accès et
            # l'avale : PVA_RES_... s'afficherait PVARES_... Il faut le doubler.
            for i, col in enumerate(cols_valeur):
                if col is None:
                    continue
                if i < len(criteres):
                    col.Header     = criteres[i][0].replace(u"_", u"__")
                    col.Visibility = SW.Visibility.Visible
                else:
                    col.Visibility = SW.Visibility.Collapsed

            if not criteres:
                lbl_count.Text = u"Saisissez au moins une valeur à chercher"
                dg.ItemsSource = None
                etat["rows"] = []
                return

            rows = rechercher(sources, criteres)
            etat["rows"] = rows
            dg.ItemsSource = None
            dg.ItemsSource = rows
            n_loc = len([r for r in rows if r._local])
            txt = u"{} résultat(s) — {} dans la maquette, {} dans un lien".format(
                len(rows), n_loc, len(rows) - n_loc)
            if len(criteres) > 1:
                txt += u"\n{} critères cumulés (ET)".format(len(criteres))
            lbl_count.Text = txt

            prefs["parametre"] = criteres[0][0]
            prefs["mode"]      = criteres[0][1]
            for i in range(3):
                prefs[u"parametre{}".format(i + 1)] = cb_pars[i].SelectedItem or u""
                prefs[u"mode{}".format(i + 1)]      = cb_modes[i].SelectedItem or MODES[0]
            _save_prefs(prefs)

        def _cibles():
            """Lignes selectionnees, a defaut tous les resultats."""
            sel = [r for r in dg.SelectedItems] if dg.SelectedItems else []
            return sel if sel else etat["rows"]

        def on_sel(s, e):
            cibles = _cibles()
            if not cibles:
                SW.MessageBox.Show(u"Aucun résultat à sélectionner.", TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
                return
            n_loc, n_lien = selectionner(cibles)
            if n_loc == 0:
                SW.MessageBox.Show(
                    u"Les {} réservation(s) trouvée(s) sont dans un lien : elles ne "
                    u"peuvent pas être sélectionnées.\n\nUtilisez « Vue 3D » pour les "
                    u"cadrer.".format(n_lien),
                    TOOL_NAME, SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
                return
            if n_lien:
                SW.MessageBox.Show(
                    u"{} réservation(s) sélectionnée(s).\n\n{} autre(s) sont dans un "
                    u"lien et ne peuvent pas l'être.".format(n_loc, n_lien),
                    TOOL_NAME, SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
            win.Close()

        def on_3d(s, e):
            cibles = _cibles()
            if not cibles:
                SW.MessageBox.Show(u"Aucun résultat à cadrer.", TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
                return
            vue, err = cadrer_en_3d(cibles)
            if err:
                SW.MessageBox.Show(err, TOOL_NAME, SW.MessageBoxButton.OK,
                                   SW.MessageBoxImage.Warning)
                return
            win.Close()

        def on_exp(s, e):
            cibles = _cibles()
            if not cibles:
                SW.MessageBox.Show(u"Aucun résultat à exporter.", TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Information)
                return
            try:
                clr.AddReference("System.Windows.Forms")
                from System.Windows.Forms import SaveFileDialog, DialogResult
                dlg = SaveFileDialog()
                dlg.Title    = "Exporter les résultats"
                dlg.Filter   = "Classeur Excel (*.xlsx)|*.xlsx"
                dlg.FileName = "Recherche_reservations.xlsx"
                last = prefs.get("last_folder", u"")
                if last and os.path.isdir(last):
                    dlg.InitialDirectory = last
                if dlg.ShowDialog() != DialogResult.OK or not dlg.FileName:
                    return
                exporter(cibles, etat.get("criteres", []), dlg.FileName)
                prefs["last_folder"] = os.path.dirname(dlg.FileName)
                _save_prefs(prefs)
                SW.MessageBox.Show(u"Export réussi :\n{}".format(dlg.FileName),
                                   TOOL_NAME, SW.MessageBoxButton.OK,
                                   SW.MessageBoxImage.Information)
            except Exception as ex:
                SW.MessageBox.Show(u"Erreur d'export :\n{}".format(ex), TOOL_NAME,
                                   SW.MessageBoxButton.OK, SW.MessageBoxImage.Error)

        def on_key(sender, args):
            try:
                if args.Key == SW.Input.Key.Enter:
                    lancer()
            except Exception:
                pass

        win.FindName("btn_go").Click    += lancer
        win.FindName("btn_sel").Click   += on_sel
        win.FindName("btn_3d").Click    += on_3d
        win.FindName("btn_exp").Click   += on_exp
        win.FindName("btn_close").Click += lambda s, e: win.Close()
        for _tb in tbs:
            _tb.KeyDown += on_key

        lbl_count.Text = u"Saisissez au moins une valeur à chercher"
        tb.Focus()
        win.ShowDialog()

    # =========================================================================
    # MAIN
    # =========================================================================
    def main():
        sources = collecter_sources()
        if not sources:
            TaskDialog.Show(TOOL_NAME,
                            u"Aucune reservation « {}* » trouvee, ni dans la maquette "
                            u"courante ni dans les liens charges.".format(FAMILY_PREFIX))
            return
        parametres = lister_parametres(sources)
        if not parametres:
            TaskDialog.Show(TOOL_NAME, u"Aucun parametre lisible sur les reservations.")
            return
        run_window(sources, parametres)

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
