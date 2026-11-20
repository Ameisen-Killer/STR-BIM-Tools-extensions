# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.0.2"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = u"Contrôle Position Réservations"
# =============================================================================
# Titre du bouton, tooltip et version : voir bundle.yaml (pas de __title__ ici)
#
# POURQUOI CET OUTIL
# ------------------
# « Sync Reservations » compare la PRESENCE des reservations (appariement par
# ADN) et huit PARAMETRES texte, dont WSP_PositionX/Y/Z_NM95. Ces coordonnees
# sont des valeurs ecrites par le script des mandataires : une reservation
# deplacee ou redimensionnee a la main dans la maquette RES garde ses anciens
# parametres, et la synchro la declare OK.
#
# Ici on mesure la GEOMETRIE reelle des deux cotes, dans le repere de la
# maquette STR (transformation du lien appliquee) :
#   - position    : distance entre les centres de gravite des solides ;
#   - volumetrie  : encombrement X/Y/Z et volume des solides.
# Aucune ecriture dans la maquette, sauf le bouton « Recaler sur le lien ».

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
    import os, io, json, re, math

    clr.AddReference('PresentationFramework')
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')
    clr.AddReference('System')

    import System, System.IO, System.Text, System.Windows.Markup
    import System.Windows as SW
    from System.Collections.Generic import List as ClrList

    from Autodesk.Revit.DB import (
        FilteredElementCollector, FamilyInstance, RevitLinkInstance,
        StorageType, ElementId, XYZ, BoundingBoxXYZ,
        View3D, ViewFamilyType, ViewFamily, Transaction, TransactionStatus,
        Options, ViewDetailLevel, Solid, GeometryInstance,
        ElementTransformUtils
    )

    import xlsxwriter

    uidoc = __revit__.ActiveUIDocument
    doc   = uidoc.Document
    app   = __revit__.Application

    _FOOTER = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    # =========================================================================
    # CONSTANTES METIER — alignees sur l'outil Sync Reservations v3.5.0
    # La population controlee doit etre EXACTEMENT celle que compare la synchro
    # (memes filtres, meme appariement), sinon les deux outils ne parlent pas
    # des memes reservations.
    # =========================================================================
    LINK_MODEL_PREFIX = "FGH_RES_SPV"
    FAMILY_PREFIX     = "FGH_RES"
    ADN_PARAM         = "CONTROL_NE_PAS_TOUCHER"
    ADN_FILTER_VAL    = "_STATUT"
    MUTUALISE_PARAM   = "FGH_MUTUALISE"

    PARAM_NUM         = "PVA_RES_DEM_NumReservation"
    PARAM_DEMANDEUR   = "PVA_RES_DEM_Demandeur"
    PARAM_NIVEAU      = "WSP_NiveauAssocie"
    PARAM_VAL_STATUT  = "PVA_RES_VAL_Statut"
    PARAM_MODIFIE     = "PVA_RES_DEM_Modifie"
    PARAM_SUPPRIME    = "PVA_RES_DEM_Supprime"

    STATUT_SUPPRIMEE  = "SUPPRIMEE"

    ADN_SEG_STATUT    = u"STATUT"
    ADN_RE_REVISION   = r"_R\d+$"

    VIEW_3D_NAME      = "STR_Reservations"   # meme vue que Sync Reservations
    VIEW_3D_TEMPLATE  = "3D_STR+RES"
    VIEW_3D_MARGE_M   = 0.5

    # Tolerances par defaut (modifiables dans la fenetre, gardees par poste)
    TOL_POSITION_CM   = 1.0    # ecart entre centres de gravite
    TOL_DIMENSION_CM  = 1.0    # ecart d'encombrement sur un axe
    TOL_VOLUME_PCT    = 2.0    # ecart de volume

    # Decalage commun : part minimale des paires deplacees, et part de celles-ci
    # qui doivent partager le meme vecteur, pour soupconner un lien deplace.
    DECALAGE_MIN_PAIRES = 5
    DECALAGE_PART_PAIRES = 0.5
    DECALAGE_PART_COMMUN = 0.8

    PIED_CM  = 30.48
    PIED3_L  = 28.316846592

    V_OK      = u"Conforme"
    V_DEP     = u"Déplacée"
    V_VOL     = u"Volumétrie différente"
    V_DEPVOL  = u"Déplacée + volumétrie"
    V_NM      = u"Non mesurable"

    BG = {V_OK: "#FFFFFF", V_DEP: "#FDDEDE", V_VOL: "#FFF3CD",
          V_DEPVOL: "#F5C6CB", V_NM: "#E2E3E5"}
    ORDRE = {V_DEPVOL: 0, V_DEP: 1, V_VOL: 2, V_NM: 3, V_OK: 4}

    F_ECARTS, F_ADN, F_REPLI, F_TOUT, F_DEP, F_VOL, F_NM, F_OK = range(8)
    FILTRES = [u"Écarts seulement", u"Écarts — ADN identique",
               u"Écarts — repli N° + maquette", u"Tout afficher", u"Déplacées",
               u"Volumétrie différente", u"Non mesurables", u"Conformes"]

    # Mode d'appariement, affiche sur chaque ligne : un ecart n'a pas le meme sens
    # selon que l'ADN est identique (meme soumission, donc deplacement reel) ou que
    # la paire vient du repli (ADN refige : la reservation a ete resoumise, un
    # ecart est attendu et se traite dans Sync Reservations).
    APP_ADN   = u"ADN identique"
    APP_RESOU = u"Repli N° + maquette"

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefs.json")

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

    def _nombre(texte, defaut):
        """Texte saisi -> nombre positif, sinon la valeur par defaut."""
        try:
            v = float((texte or u"").strip().replace(u",", u"."))
            if v >= 0.0:
                return v
        except Exception:
            pass
        return defaut

    def _mediane(valeurs):
        s = sorted(valeurs)
        n = len(s)
        if not n:
            return 0.0
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    # =========================================================================
    # COLLECTE ET APPARIEMENT — identiques a Sync Reservations
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

    def collect_link(ldoc):
        """FGH_RES* du lien : ADN contient _STATUT, hors FGH_MUTUALISE = 1."""
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

    def _adn_key(el):
        return (_p_str(el, ADN_PARAM) or u"").strip()

    def _fallback_key(el, rx):
        """N° + maquette d'origine sans revision : reconnait un percement resoumis."""
        adn = _adn_key(el)
        if not adn:
            return None
        parts = adn.split(u"_")
        try:
            i = parts.index(ADN_SEG_STATUT)
        except ValueError:
            return None
        if i < 2 or len(parts) < i + 3:
            return None
        return u"{}|{}".format(parts[0], rx.sub(u"", u"_".join(parts[i + 2:])))

    def apparier(host_elems, link_elems):
        """
        Meme regle que Sync Reservations :
          1. ADN identique ;
          2. repli resoumission : meme N° + maquette, une seule candidate de
             chaque cote.
        Retourne ([(e_host, e_link, mode)], nb_lien_seul, nb_str_seul).
        """
        rx = re.compile(ADN_RE_REVISION)

        link_by_adn = {}
        for e in link_elems:
            k = _adn_key(e)
            if k:
                link_by_adn[k] = e

        host_by_adn, nb_str_seul = {}, 0
        for e in host_elems:
            k = _adn_key(e)
            if k:
                host_by_adn[k] = e
            else:
                nb_str_seul += 1

        paires, pris_h, pris_l = [], set(), set()
        for adn in sorted(link_by_adn.keys()):
            h = host_by_adn.get(adn)
            if h is not None:
                paires.append((h, link_by_adn[adn], APP_ADN))
                pris_h.add(_eid_int(h.Id))
                pris_l.add(adn)

        fb_link, fb_host = {}, {}
        for adn, e in link_by_adn.items():
            if adn in pris_l:
                continue
            k = _fallback_key(e, rx)
            if k:
                fb_link.setdefault(k, []).append((adn, e))
        for adn, h in host_by_adn.items():
            if _eid_int(h.Id) in pris_h:
                continue
            k = _fallback_key(h, rx)
            if k:
                fb_host.setdefault(k, []).append(h)
        for k in sorted(fb_link.keys()):
            cl, ch = fb_link[k], fb_host.get(k)
            if ch and len(cl) == 1 and len(ch) == 1:
                paires.append((ch[0], cl[0][1], APP_RESOU))
                pris_h.add(_eid_int(ch[0].Id))
                pris_l.add(cl[0][0])

        nb_str_seul += len([1 for h in host_by_adn.values()
                            if _eid_int(h.Id) not in pris_h])
        nb_lien_seul = len(link_by_adn) - len(pris_l)
        return paires, nb_lien_seul, nb_str_seul

    # =========================================================================
    # MESURE GEOMETRIQUE
    # =========================================================================
    def _collect_solids(gel, out):
        if gel is None:
            return
        for g in gel:
            try:
                if isinstance(g, Solid):
                    if g.Volume > 1.0e-9 and g.Faces.Size > 0:
                        out.append(g)
                elif isinstance(g, GeometryInstance):
                    _collect_solids(g.GetInstanceGeometry(), out)
            except Exception:
                pass

    def _solids(el):
        res = []
        try:
            opts = Options()
            opts.ComputeReferences        = False
            opts.IncludeNonVisibleObjects = False
            opts.DetailLevel              = ViewDetailLevel.Fine
            _collect_solids(el.get_Geometry(opts), res)
        except Exception:
            pass
        return res

    def mesurer(el, transform):
        """
        Mesure un element dans le repere de la maquette STR.
        transform : transformation du lien, None pour un element local.
        Retourne None si rien n'est mesurable, sinon un dict en unites internes
        (pieds) : c = centre de gravite, mn / mx = encombrement, vol = volume,
        approx = True quand la mesure vient de la boite englobante faute de solide.

        L'encombrement vient des sommets des solides, transformes un a un : la
        boite englobante d'un element de lien tourne serait fausse.
        """
        pts, vol, sx, sy, sz, approx = [], 0.0, 0.0, 0.0, 0.0, False
        for s in _solids(el):
            try:
                v = s.Volume
                g = s.ComputeCentroid()
                loc = []
                for edge in s.Edges:
                    for p in edge.Tessellate():
                        loc.append(p)
                if not loc:
                    continue
                pts.extend(loc)
                vol += v
                sx += g.X * v
                sy += g.Y * v
                sz += g.Z * v
            except Exception:
                pass

        if vol > 1.0e-9 and pts:
            centre = XYZ(sx / vol, sy / vol, sz / vol)
        else:
            # Famille sans solide lisible (vide seul, geometrie masquee...)
            approx = True
            try:
                bb = el.get_BoundingBox(None)
            except Exception:
                bb = None
            if bb is None:
                return None
            a, b = bb.Min, bb.Max
            pts = [XYZ(x, y, z) for x in (a.X, b.X) for y in (a.Y, b.Y) for z in (a.Z, b.Z)]
            centre = XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, (a.Z + b.Z) / 2.0)
            vol = abs((b.X - a.X) * (b.Y - a.Y) * (b.Z - a.Z))

        if transform is not None:
            centre = transform.OfPoint(centre)
            pts = [transform.OfPoint(p) for p in pts]

        xs = [p.X for p in pts]
        ys = [p.Y for p in pts]
        zs = [p.Z for p in pts]
        return {"c": (centre.X, centre.Y, centre.Z),
                "mn": (min(xs), min(ys), min(zs)),
                "mx": (max(xs), max(ys), max(zs)),
                "vol": vol, "approx": approx}

    def _dims_cm(m):
        return [(m["mx"][i] - m["mn"][i]) * PIED_CM for i in range(3)]

    def _recouvrement(a, b):
        """Part commune des deux encombrements (intersection / union), en %."""
        inter, va, vb = 1.0, 1.0, 1.0
        for i in range(3):
            inter *= max(0.0, min(a["mx"][i], b["mx"][i]) - max(a["mn"][i], b["mn"][i]))
            va *= (a["mx"][i] - a["mn"][i])
            vb *= (b["mx"][i] - b["mn"][i])
        union = va + vb - inter
        return 100.0 * inter / union if union > 1.0e-12 else 0.0

    # =========================================================================
    # LIGNES
    # =========================================================================
    class Row(object):
        """Une reservation presente des deux cotes."""
        def __init__(self, e_host, e_link, mode, transform):
            self._host = e_host
            self.NumStr = _p_str(e_host, PARAM_NUM)
            self.NumSpv = _p_str(e_link, PARAM_NUM)
            self.Num    = self.NumSpv or self.NumStr
            self.AdnStr = _adn_key(e_host)
            self.AdnSpv = _adn_key(e_link)
            self.Fam   = _family_name(e_host)
            self.Niv   = _p_str(e_link, PARAM_NIVEAU)
            self.Val   = _p_str(e_link, PARAM_VAL_STATUT)
            self.Dem   = _p_str(e_link, PARAM_DEMANDEUR)
            self.App   = mode
            self.IdStr = u"{}".format(_eid_int(e_host.Id))
            self.IdSpv = u"{}".format(_eid_int(e_link.Id))
            marques = []
            if _p_int(e_link, PARAM_MODIFIE) == 1:
                marques.append(u"Modifié")
            if _p_int(e_link, PARAM_SUPPRIME) == 1:
                marques.append(u"Supprimé")
            self.Marque = u" + ".join(marques)
            try:
                self.Epingle = u"Oui" if e_host.Pinned else u"Non"
            except Exception:
                self.Epingle = u""
            self._ml = mesurer(e_link, transform)
            self.mesurer_hote()

        def mesurer_hote(self):
            self._mh = mesurer(self._host, None)
            self._calculer()

        def _calculer(self):
            a, b = self._mh, self._ml
            self.Mesurable = a is not None and b is not None
            if not self.Mesurable:
                self.Ecart = self.DX = self.DY = self.DZ = None
                self.DDim = self.DVol = self.Recouv = None
                self.VolStr = self.VolSpv = None
                self.DimStr = self.DimSpv = u""
                self._ddims = [0.0, 0.0, 0.0]
                self.Approx = u""
                return
            # Ecart = position SPV - position STR : ou la reservation est partie.
            d = [(b["c"][i] - a["c"][i]) * PIED_CM for i in range(3)]
            self.DX, self.DY, self.DZ = d
            self.Ecart = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
            da, db = _dims_cm(a), _dims_cm(b)
            self._ddims = [db[i] - da[i] for i in range(3)]
            self.DDim = max(abs(x) for x in self._ddims)
            self.VolStr = a["vol"] * PIED3_L
            self.VolSpv = b["vol"] * PIED3_L
            ref = max(self.VolStr, 1.0e-9)
            self.DVol = 100.0 * (self.VolSpv - self.VolStr) / ref
            self.Recouv = _recouvrement(a, b)
            self.DimStr = u"{:.1f} x {:.1f} x {:.1f}".format(da[0], da[1], da[2])
            self.DimSpv = u"{:.1f} x {:.1f} x {:.1f}".format(db[0], db[1], db[2])
            self.Approx = u"Oui" if (a["approx"] or b["approx"]) else u""

        def classer(self, tol_pos, tol_dim, tol_vol):
            """Verdict selon les tolerances, puis textes d'affichage."""
            if not self.Mesurable:
                self.Verdict = V_NM
                self.Detail  = u"Géométrie illisible côté {}".format(
                    u"STR" if self._mh is None else u"SPV")
            else:
                dep = self.Ecart > tol_pos
                vol = self.DDim > tol_dim or abs(self.DVol) > tol_vol
                self.Verdict = V_DEPVOL if (dep and vol) else V_DEP if dep \
                    else V_VOL if vol else V_OK
                parts = []
                if dep:
                    parts.append(u"Centre SPV décalé de {:.1f} cm (X {:+.1f} / Y {:+.1f} / "
                                 u"Z {:+.1f})".format(self.Ecart, self.DX, self.DY, self.DZ))
                if vol:
                    parts.append(u"Encombrement STR {} cm → SPV {} cm, volume {:+.1f} %".format(
                        self.DimStr, self.DimSpv, self.DVol))
                if self.Approx:
                    parts.append(u"mesure approchée (boîte englobante, pas de solide lisible)")
                self.Detail = u" | ".join(parts)
            # Indices d'un mauvais appariement, en tete du detail
            alertes = []
            if self.NumStr != self.NumSpv:
                alertes.append(u"N° STR [{}] ≠ N° SPV [{}]".format(self.NumStr, self.NumSpv))
            if self.App == APP_RESOU and self.Verdict != V_OK:
                alertes.append(u"ADN refigé : réservation resoumise, à traiter dans Sync "
                               u"Reservations")
            if alertes:
                self.Detail = u" | ".join(alertes + ([self.Detail] if self.Detail else []))
            self.RowBg = BG[self.Verdict]
            self.Tri   = ORDRE[self.Verdict]

            def f1(v, signe=False):
                if v is None:
                    return u""
                return (u"{:+.1f}" if signe else u"{:.1f}").format(v)

            self.EcartT  = f1(self.Ecart)
            self.DXT     = f1(self.DX, True)
            self.DYT     = f1(self.DY, True)
            self.DZT     = f1(self.DZ, True)
            self.DDimT   = f1(self.DDim)
            self.DVolT   = f1(self.DVol, True)
            self.RecouvT = u"" if self.Recouv is None else u"{:.0f}".format(self.Recouv)
            # Cles de tri numeriques : les non mesurables restent en bas
            self.EcartS  = -1.0 if self.Ecart is None else self.Ecart
            self.DDimS   = -1.0 if self.DDim is None else self.DDim
            self.DVolS   = 0.0 if self.DVol is None else abs(self.DVol)
            self.DXS     = 0.0 if self.DX is None else self.DX
            self.DYS     = 0.0 if self.DY is None else self.DY
            self.DZS     = 0.0 if self.DZ is None else self.DZ
            self.RecouvS = -1.0 if self.Recouv is None else self.Recouv

        def recalable(self):
            """Deplacement pur : meme volumetrie, donc une translation suffit."""
            return self.Verdict == V_DEP

        def vecteur_recalage(self):
            a, b = self._mh["c"], self._ml["c"]
            return XYZ(b[0] - a[0], b[1] - a[1], b[2] - a[2])

        def coins(self):
            """Min et max des deux encombrements, pour cadrer la vue 3D."""
            out = []
            for m in (self._mh, self._ml):
                if m is not None:
                    out.append(m["mn"])
                    out.append(m["mx"])
            return out

    # =========================================================================
    # ANALYSES
    # =========================================================================
    def decalage_commun(rows, tol_pos):
        """
        Les reservations deplacees partagent-elles toutes le meme vecteur ?
        Si oui, ce ne sont pas des deplacements un a un : c'est le lien (ou son
        point de base) qui a bouge. Retourne (dx, dy, dz, nb, nb_deplacees) ou None.
        """
        mesurables = [r for r in rows if r.Mesurable]
        dep = [r for r in mesurables if r.Ecart > tol_pos]
        if len(dep) < DECALAGE_MIN_PAIRES or \
                len(dep) < DECALAGE_PART_PAIRES * len(mesurables):
            return None
        mx = _mediane([r.DX for r in dep])
        my = _mediane([r.DY for r in dep])
        mz = _mediane([r.DZ for r in dep])
        tol = max(tol_pos, 0.1)
        nb = len([r for r in dep if abs(r.DX - mx) <= tol and abs(r.DY - my) <= tol
                  and abs(r.DZ - mz) <= tol])
        if nb < DECALAGE_PART_COMMUN * len(dep):
            return None
        return mx, my, mz, nb, len(dep)

    def compter(rows):
        c = {V_OK: 0, V_DEP: 0, V_VOL: 0, V_DEPVOL: 0, V_NM: 0}
        for r in rows:
            c[r.Verdict] += 1
        return c

    # =========================================================================
    # ACTIONS SUR LE MODELE
    # =========================================================================
    def selectionner(rows):
        ids = ClrList[ElementId]()
        for r in rows:
            ids.Add(r._host.Id)
        try:
            uidoc.Selection.SetElementIds(ids)
            uidoc.ShowElements(ids)
        except Exception:
            pass
        return ids.Count

    def cadrer_en_3d(rows):
        """Vue 3D STR_Reservations, boite de coupe autour des deux positions."""
        pts = []
        for r in rows:
            pts.extend(r.coins())
        if not pts:
            return None, u"Aucune géométrie exploitable pour cadrer."
        marge = VIEW_3D_MARGE_M / 0.3048
        mn = [min(p[i] for p in pts) - marge for i in range(3)]
        mx = [max(p[i] for p in pts) + marge for i in range(3)]

        vue, gabarit, vft = None, None, None
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if v.IsTemplate and _safe_name(v) == VIEW_3D_TEMPLATE:
                    gabarit = v
                elif not v.IsTemplate and _safe_name(v) == VIEW_3D_NAME:
                    vue = v
            except Exception:
                pass
        if vue is None:
            for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                try:
                    if t.ViewFamily == ViewFamily.ThreeDimensional:
                        vft = t
                        break
                except Exception:
                    pass
            if vft is None:
                return None, u"Aucun type de vue 3D disponible dans le projet."

        t = Transaction(doc, u"STR - Vue 3D contrôle position réservations")
        t.Start()
        try:
            if vue is None:
                vue = View3D.CreateIsometric(doc, vft.Id)
                try:
                    vue.Name = VIEW_3D_NAME
                except Exception:
                    pass
            if gabarit is not None:
                try:
                    vue.ViewTemplateId = gabarit.Id
                except Exception:
                    pass
            bb = BoundingBoxXYZ()
            bb.Min = XYZ(mn[0], mn[1], mn[2])
            bb.Max = XYZ(mx[0], mx[1], mx[2])
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

    def recaler(rows):
        """
        Translate les reservations STR sur la position du lien. Une seule
        transaction : un Ctrl+Z annule tout le recalage.
        Retourne (nb_deplacees, [messages d'echec]).
        """
        echecs, faits = [], []
        t = Transaction(doc, u"STR - Recaler réservations sur le lien")
        t.Start()
        try:
            for r in rows:
                el = r._host
                epingle = False
                try:
                    epingle = el.Pinned
                    if epingle:
                        el.Pinned = False
                    ElementTransformUtils.MoveElement(doc, el.Id, r.vecteur_recalage())
                    faits.append(r)
                except Exception as ex:
                    echecs.append(u"{} : {}".format(r.Num or r.IdStr, ex))
                # Reepinglee meme si le deplacement a echoue
                if epingle:
                    try:
                        el.Pinned = True
                    except Exception:
                        pass
            doc.Regenerate()
            t.Commit()
        except Exception as ex:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            return 0, [u"Recalage annulé : {}".format(ex)]
        for r in faits:
            r.mesurer_hote()
        return len(faits), echecs

    # =========================================================================
    # EXPORT EXCEL
    # =========================================================================
    COLS = [
        (u"Verdict", "Verdict", 24), (u"N° réservation", "Num", 16),
        (u"Écart centre (cm)", "Ecart", 14),
        (u"ΔX (cm)", "DX", 10), (u"ΔY (cm)", "DY", 10), (u"ΔZ (cm)", "DZ", 10),
        (u"Écart encombrement max (cm)", "DDim", 16),
        (u"Encombrement STR X x Y x Z (cm)", "DimStr", 26),
        (u"Encombrement SPV X x Y x Z (cm)", "DimSpv", 26),
        (u"Volume STR (L)", "VolStr", 12), (u"Volume SPV (L)", "VolSpv", 12),
        (u"Δ volume (%)", "DVol", 12), (u"Recouvrement (%)", "Recouv", 14),
        (u"Famille", "Fam", 24), (u"Niveau", "Niv", 16),
        (u"Statut VAL", "Val", 14), (u"Marque SPV", "Marque", 16),
        (u"Demandeur", "Dem", 16), (u"Appariement", "App", 20),
        (u"N° STR", "NumStr", 16), (u"N° SPV", "NumSpv", 16),
        (u"ADN STR", "AdnStr", 70), (u"ADN SPV", "AdnSpv", 70),
        (u"Épinglée", "Epingle", 10), (u"Mesure approchée", "Approx", 12),
        (u"Détail", "Detail", 70),
        (u"Id STR", "IdStr", 12), (u"Id SPV", "IdSpv", 12),
    ]

    def exporter_excel(rows, resume, chemin):
        wb = xlsxwriter.Workbook(chemin)
        fmt_hdr = wb.add_format({"bold": True, "bg_color": "#2F6496",
                                 "font_color": "#FFFFFF", "border": 1,
                                 "align": "center", "valign": "vcenter",
                                 "text_wrap": True})
        fmts = {}
        for verdict, bg in BG.items():
            fmts[verdict] = (wb.add_format({"bg_color": bg, "border": 1}),
                             wb.add_format({"bg_color": bg, "border": 1,
                                            "num_format": "0.0"}))
        fmt_std = wb.add_format({"border": 1})
        fmt_tit = wb.add_format({"bold": True, "font_size": 12,
                                 "font_color": "#2F6496"})

        ws = wb.add_worksheet(u"Ecarts")
        for i, (titre, attr, largeur) in enumerate(COLS):
            ws.set_column(i, i, largeur)
            ws.write(0, i, titre, fmt_hdr)
        ws.set_row(0, 32)
        ws.freeze_panes(1, 2)
        ws.autofilter(0, 0, max(len(rows), 1), len(COLS) - 1)
        for l, row in enumerate(rows, start=1):
            f_txt, f_num = fmts[row.Verdict]
            for c, (titre, attr, largeur) in enumerate(COLS):
                v = getattr(row, attr, u"")
                if v is None:
                    ws.write(l, c, u"", f_txt)
                elif isinstance(v, float):
                    ws.write_number(l, c, v, f_num)
                else:
                    ws.write(l, c, v, f_txt)

        ws = wb.add_worksheet(u"Resume")
        ws.set_column(0, 0, 58)
        ws.set_column(1, 1, 44)
        ws.write(0, 0, u"Contrôle de position des réservations STR / SPV", fmt_tit)
        for l, (libelle, valeur) in enumerate(resume, start=2):
            ws.write(l, 0, libelle, fmt_std)
            ws.write(l, 1, valeur, fmt_std)
        wb.close()

    # =========================================================================
    # UI — XAML en ASCII pur, les libelles accentues sont poses par le code
    # =========================================================================
    XAML = """<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="PLACEHOLDER" Width="1380" Height="720" MinWidth="1000" MinHeight="520"
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

    <Border Grid.Row="1" Background="#FAFCFF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="12,8">
      <StackPanel>
        <TextBlock x:Name="lbl_r1" FontSize="12" FontWeight="SemiBold" Foreground="#2F6496"/>
        <TextBlock x:Name="lbl_r2" FontSize="11" Foreground="#444444" Margin="0,3,0,0"
                   TextWrapping="Wrap"/>
        <TextBlock x:Name="lbl_r3" FontSize="11" Foreground="#C0392B" Margin="0,3,0,0"
                   TextWrapping="Wrap" FontWeight="SemiBold"/>
      </StackPanel>
    </Border>

    <Border Grid.Row="2" Background="#F0F6FF" BorderBrush="#C0D0E0"
            BorderThickness="0,0,0,1" Padding="12,7">
      <WrapPanel Orientation="Horizontal">
        <TextBlock x:Name="lbl_f1" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <ComboBox x:Name="cb_filtre" Width="170" Height="24" Margin="0,0,14,0"/>
        <TextBlock x:Name="lbl_f2" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tb_search" Width="170" Height="24" Margin="0,0,20,0"
                 VerticalContentAlignment="Center"/>
        <TextBlock x:Name="lbl_t1" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tb_pos" Width="46" Height="24" Margin="0,0,12,0"
                 VerticalContentAlignment="Center" HorizontalContentAlignment="Right"/>
        <TextBlock x:Name="lbl_t2" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tb_dim" Width="46" Height="24" Margin="0,0,12,0"
                 VerticalContentAlignment="Center" HorizontalContentAlignment="Right"/>
        <TextBlock x:Name="lbl_t3" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tb_vol" Width="46" Height="24" Margin="0,0,10,0"
                 VerticalContentAlignment="Center" HorizontalContentAlignment="Right"/>
        <Button x:Name="btn_tol" Height="24" Padding="10,0" Margin="0,0,16,0"
                Background="#E0E0E0" BorderThickness="0"/>
        <TextBlock x:Name="lbl_count" FontSize="11" Foreground="#2F6496"
                   VerticalAlignment="Center" FontWeight="SemiBold"/>
      </WrapPanel>
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
        <DataGridTextColumn x:Name="c_ver" Binding="{Binding Verdict}" Width="150" SortMemberPath="Tri"/>
        <DataGridTextColumn x:Name="c_num" Binding="{Binding Num}"     Width="95"/>
        <DataGridTextColumn x:Name="c_app" Binding="{Binding App}"     Width="130"/>
        <DataGridTextColumn x:Name="c_eca" Binding="{Binding EcartT}"  Width="80" SortMemberPath="EcartS"/>
        <DataGridTextColumn x:Name="c_dx"  Binding="{Binding DXT}"     Width="62" SortMemberPath="DXS"/>
        <DataGridTextColumn x:Name="c_dy"  Binding="{Binding DYT}"     Width="62" SortMemberPath="DYS"/>
        <DataGridTextColumn x:Name="c_dz"  Binding="{Binding DZT}"     Width="62" SortMemberPath="DZS"/>
        <DataGridTextColumn x:Name="c_dd"  Binding="{Binding DDimT}"   Width="92" SortMemberPath="DDimS"/>
        <DataGridTextColumn x:Name="c_dv"  Binding="{Binding DVolT}"   Width="80" SortMemberPath="DVolS"/>
        <DataGridTextColumn x:Name="c_rec" Binding="{Binding RecouvT}" Width="92" SortMemberPath="RecouvS"/>
        <DataGridTextColumn x:Name="c_fam" Binding="{Binding Fam}"     Width="135"/>
        <DataGridTextColumn x:Name="c_niv" Binding="{Binding Niv}"     Width="95"/>
        <DataGridTextColumn x:Name="c_val" Binding="{Binding Val}"     Width="80"/>
        <DataGridTextColumn x:Name="c_mar" Binding="{Binding Marque}"  Width="85"/>
        <DataGridTextColumn x:Name="c_det" Binding="{Binding Detail}"  Width="*" MinWidth="260"/>
        <DataGridTextColumn x:Name="c_id"  Binding="{Binding IdStr}"   Width="75"/>
      </DataGrid.Columns>
    </DataGrid>

    <Border Grid.Row="4" BorderThickness="0,1,0,0" BorderBrush="#C0D0E0"
            Background="#F5F5F5" Padding="0,4">
      <Grid>
        <TextBlock x:Name="lbl_footer" FontSize="10" Foreground="#888888"
                   VerticalAlignment="Center" Margin="8,0,0,0"/>
        <StackPanel HorizontalAlignment="Right" Orientation="Horizontal" Margin="0,0,8,0">
          <Button x:Name="btn_recaler" Width="150" Height="28" Margin="4,0,0,0"
                  Background="#2ECC71" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_sel" Width="110" Height="28" Margin="6,0,0,0"
                  Background="#8E44AD" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_3d" Width="90" Height="28" Margin="6,0,0,0"
                  Background="#8E44AD" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_export" Width="130" Height="28" Margin="6,0,0,0"
                  Background="#E67E22" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="btn_close" Width="90" Height="28" Margin="6,0,0,0"
                  Background="#3498DB" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
        </StackPanel>
      </Grid>
    </Border>
  </Grid>
</Window>"""

    def run_window(rows, lien_nom, nb_lien_seul, nb_str_seul):
        stream = System.IO.MemoryStream(System.Text.Encoding.UTF8.GetBytes(XAML))
        win = System.Windows.Markup.XamlReader.Load(stream)

        prefs = _load_prefs()
        tol = {"pos": _nombre(u"{}".format(prefs.get("tol_pos", u"")), TOL_POSITION_CM),
               "dim": _nombre(u"{}".format(prefs.get("tol_dim", u"")), TOL_DIMENSION_CM),
               "vol": _nombre(u"{}".format(prefs.get("tol_vol", u"")), TOL_VOLUME_PCT)}

        win.Title = TOOL_NAME
        win.FindName("lbl_titre").Text = u"{}  |  STR vs {}".format(TOOL_NAME, lien_nom)
        win.FindName("lbl_footer").Text = _FOOTER

        for nm, txt in ((u"c_ver", u"Verdict"), (u"c_num", u"N° réservation"),
                        (u"c_app", u"Appariement"),
                        (u"c_eca", u"Écart (cm)"), (u"c_dx", u"ΔX"), (u"c_dy", u"ΔY"),
                        (u"c_dz", u"ΔZ"), (u"c_dd", u"Δ dim. (cm)"),
                        (u"c_dv", u"Δ vol. (%)"), (u"c_rec", u"Recouvr. (%)"),
                        (u"c_fam", u"Famille"), (u"c_niv", u"Niveau"),
                        (u"c_val", u"Statut VAL"), (u"c_mar", u"Marque SPV"),
                        (u"c_det", u"Détail"), (u"c_id", u"Id STR")):
            win.FindName(nm).Header = txt

        win.FindName("lbl_f1").Text = u"Afficher :"
        win.FindName("lbl_f2").Text = u"Recherche :"
        win.FindName("lbl_t1").Text = u"Tolérances — position (cm) :"
        win.FindName("lbl_t2").Text = u"dimension (cm) :"
        win.FindName("lbl_t3").Text = u"volume (%) :"
        win.FindName("btn_tol").Content     = u"Appliquer"
        win.FindName("btn_recaler").Content = u"Recaler sur le lien"
        win.FindName("btn_sel").Content     = u"Sélectionner"
        win.FindName("btn_3d").Content      = u"Vue 3D"
        win.FindName("btn_export").Content  = u"Exporter Excel"
        win.FindName("btn_close").Content   = u"Fermer"
        win.FindName("btn_recaler").ToolTip = (
            u"Translate les réservations STR sélectionnées sur la position du lien. "
            u"Seulement les lignes « Déplacée » : même volumétrie des deux côtés.")
        win.FindName("btn_sel").ToolTip = (
            u"Sélectionne les réservations STR des lignes choisies et ferme la fenêtre.")
        win.FindName("btn_3d").ToolTip = (
            u"Ouvre la vue « {} » avec une zone de coupe autour des deux positions, "
            u"STR et SPV, puis ferme la fenêtre.".format(VIEW_3D_NAME))
        win.FindName("lbl_t1").ToolTip = (
            u"Écart = distance entre les centres de gravité des solides, mesurés "
            u"dans le repère de la maquette STR. ΔX/ΔY/ΔZ = SPV − STR.")

        tb_pos = win.FindName("tb_pos")
        tb_dim = win.FindName("tb_dim")
        tb_vol = win.FindName("tb_vol")
        tb_pos.Text = u"{:g}".format(tol["pos"])
        tb_dim.Text = u"{:g}".format(tol["dim"])
        tb_vol.Text = u"{:g}".format(tol["vol"])

        cb = win.FindName("cb_filtre")
        for f in FILTRES:
            cb.Items.Add(f)
        cb.SelectedIndex = F_ECARTS

        dg = win.FindName("dg_main")
        tb = win.FindName("tb_search")
        lbl_count = win.FindName("lbl_count")

        def classer_tout():
            for r in rows:
                r.classer(tol["pos"], tol["dim"], tol["vol"])
            rows.sort(key=lambda r: (r.Tri, -r.EcartS, r.Num))

        def maj_resume():
            c = compter(rows)
            ecarts = c[V_DEP] + c[V_VOL] + c[V_DEPVOL]
            win.FindName("lbl_r1").Text = (
                u"{} réservation(s) présente(s) des deux côtés   |   Conformes : {}   |   "
                u"Déplacées : {}   |   Volumétrie différente : {}   |   Les deux : {}   |   "
                u"Non mesurables : {}".format(len(rows), c[V_OK], c[V_DEP], c[V_VOL],
                                              c[V_DEPVOL], c[V_NM]))
            win.FindName("lbl_r2").Text = (
                u"Hors contrôle, à traiter dans Sync Reservations — présentes dans le lien "
                u"seulement : {}   |   dans la STR seulement : {}".format(
                    nb_lien_seul, nb_str_seul))
            d = decalage_commun(rows, tol["pos"])
            if d is not None:
                win.FindName("lbl_r3").Text = (
                    u"⚠ Décalage commun : {} des {} réservations déplacées partagent le même "
                    u"vecteur (X {:+.1f} / Y {:+.1f} / Z {:+.1f} cm). C'est sans doute le lien "
                    u"ou son point de base qui a bougé, pas les réservations une à une : à "
                    u"vérifier avant tout recalage.".format(d[3], d[4], d[0], d[1], d[2]))
            elif ecarts:
                e_adn = len([r for r in rows if r.App == APP_ADN
                             and r.Verdict in (V_DEP, V_VOL, V_DEPVOL)])
                win.FindName("lbl_r3").Text = (
                    u"⚠ {} réservation(s) en écart : {} avec un ADN identique des deux côtés "
                    u"(même soumission, la synchronisation ne les voit pas), {} appariée(s) "
                    u"par repli N° + maquette (ADN refigé, resoumission à traiter dans Sync "
                    u"Reservations).".format(ecarts, e_adn, ecarts - e_adn))
            else:
                win.FindName("lbl_r3").Text = u""
            return c

        def visibles():
            f = cb.SelectedIndex
            q = (tb.Text or u"").strip().lower()
            out = []
            for r in rows:
                v = r.Verdict
                if f in (F_ECARTS, F_ADN, F_REPLI) and v in (V_OK, V_NM):
                    continue
                if f == F_ADN and r.App != APP_ADN:
                    continue
                if f == F_REPLI and r.App != APP_RESOU:
                    continue
                if f == F_DEP and v not in (V_DEP, V_DEPVOL):
                    continue
                if f == F_VOL and v not in (V_VOL, V_DEPVOL):
                    continue
                if f == F_NM and v != V_NM:
                    continue
                if f == F_OK and v != V_OK:
                    continue
                if q:
                    blob = u" ".join([r.NumStr, r.NumSpv, r.Fam, r.Niv, r.Val, r.Dem,
                                      r.Marque, r.IdStr, r.IdSpv, r.Verdict, r.App,
                                      r.AdnStr, r.AdnSpv]).lower()
                    if q not in blob:
                        continue
                out.append(r)
            return out

        def refresh(sender=None, e=None):
            vis = visibles()
            dg.ItemsSource = None
            dg.ItemsSource = vis
            lbl_count.Text = u"{} ligne(s) affichée(s) sur {}".format(len(vis), len(rows))

        def _cibles():
            """Lignes choisies dans le tableau ; a defaut, toutes les lignes affichees."""
            sel = [r for r in dg.SelectedItems]
            return sel if sel else visibles()

        def info(msg, image=None):
            SW.MessageBox.Show(msg, TOOL_NAME, SW.MessageBoxButton.OK,
                               image if image is not None else SW.MessageBoxImage.Information)

        def on_tol(s, e):
            tol["pos"] = _nombre(tb_pos.Text, tol["pos"])
            tol["dim"] = _nombre(tb_dim.Text, tol["dim"])
            tol["vol"] = _nombre(tb_vol.Text, tol["vol"])
            tb_pos.Text = u"{:g}".format(tol["pos"])
            tb_dim.Text = u"{:g}".format(tol["dim"])
            tb_vol.Text = u"{:g}".format(tol["vol"])
            prefs["tol_pos"], prefs["tol_dim"], prefs["tol_vol"] = \
                tol["pos"], tol["dim"], tol["vol"]
            _save_prefs(prefs)
            classer_tout()
            maj_resume()
            refresh()

        def on_sel(s, e):
            cibles = _cibles()
            if not cibles:
                info(u"Aucune ligne à sélectionner.")
                return
            selectionner(cibles)
            win.Close()

        def on_3d(s, e):
            cibles = _cibles()
            if not cibles:
                info(u"Aucune ligne à cadrer.")
                return
            vue, err = cadrer_en_3d(cibles)
            if err:
                info(err, SW.MessageBoxImage.Warning)
                return
            selectionner(cibles)
            win.Close()

        def on_recaler(s, e):
            choisies = [r for r in dg.SelectedItems]
            if not choisies:
                info(u"Choisissez d'abord dans le tableau les lignes à recaler "
                     u"(Ctrl ou Maj + clic pour plusieurs).")
                return
            cibles = [r for r in choisies if r.recalable()]
            ecartees = len(choisies) - len(cibles)
            if not cibles:
                info(u"Aucune des lignes choisies n'est un déplacement pur.\n\n"
                     u"Une réservation dont la volumétrie a changé ne se corrige pas par "
                     u"une translation : elle doit être resoumise et revalidée, puis "
                     u"remplacée par Sync Reservations.")
                return
            msg = (u"Recaler {} réservation(s) de la maquette STR sur la position du lien "
                   u"SPV ?\n\n"
                   u"  • plus grand déplacement : {:.1f} cm\n"
                   u"  • les réservations épinglées sont désépinglées le temps du "
                   u"déplacement, puis réépinglées\n"
                   u"  • une seule opération dans l'historique : Ctrl+Z annule tout\n\n"
                   u"Attention : la position validée par l'ingénieur était celle de la "
                   u"STR. Recaler, c'est accepter le déplacement fait par le mandataire "
                   u"sans nouvelle validation.".format(
                       len(cibles), max(r.Ecart for r in cibles)))
            if ecartees:
                msg += (u"\n\n{} ligne(s) choisie(s) sont laissées de côté "
                        u"(pas un déplacement pur).".format(ecartees))
            if SW.MessageBox.Show(msg, TOOL_NAME, SW.MessageBoxButton.OKCancel,
                                  SW.MessageBoxImage.Warning) != SW.MessageBoxResult.OK:
                return
            nb, echecs = recaler(cibles)
            classer_tout()
            maj_resume()
            refresh()
            restent = len([r for r in cibles if r.Verdict != V_OK])
            bilan = u"{} réservation(s) déplacée(s).".format(nb)
            if restent:
                bilan += (u"\n\n⚠ {} sont encore en écart après le déplacement (famille "
                          u"contrainte par son hôte ou son plan de travail ?) : elles "
                          u"restent dans le tableau.".format(restent))
            if echecs:
                bilan += u"\n\nÉchecs :\n" + u"\n".join(
                    u"  • {}".format(x) for x in echecs[:15])
                if len(echecs) > 15:
                    bilan += u"\n  • ... et {} autre(s)".format(len(echecs) - 15)
            info(bilan, SW.MessageBoxImage.Warning if (restent or echecs) else None)

        def on_export(s, e):
            cibles = visibles()
            if not cibles:
                info(u"Aucune ligne à exporter.")
                return
            try:
                clr.AddReference("System.Windows.Forms")
                from System.Windows.Forms import SaveFileDialog, DialogResult
                dlg = SaveFileDialog()
                dlg.Title    = "Exporter le controle de position"
                dlg.Filter   = "Classeur Excel (*.xlsx)|*.xlsx"
                dlg.FileName = "Controle_position_reservations_{}.xlsx".format(
                    System.DateTime.Now.ToString("yyyyMMdd_HHmm"))
                last = prefs.get("last_folder", u"")
                if last and os.path.isdir(last):
                    dlg.InitialDirectory = last
                if dlg.ShowDialog() != DialogResult.OK or not dlg.FileName:
                    return
                c = compter(rows)
                resume = [
                    (u"Date du contrôle", System.DateTime.Now.ToString("dd/MM/yyyy HH:mm")),
                    (u"Maquette STR", doc.Title),
                    (u"Lien SPV", lien_nom),
                    (u"Filtre exporté", FILTRES[cb.SelectedIndex]),
                    (u"Lignes exportées", u"{} sur {}".format(len(cibles), len(rows))),
                    (u"", u""),
                    (u"Tolérance de position (cm)", u"{:g}".format(tol["pos"])),
                    (u"Tolérance de dimension (cm)", u"{:g}".format(tol["dim"])),
                    (u"Tolérance de volume (%)", u"{:g}".format(tol["vol"])),
                    (u"", u""),
                    (u"Réservations présentes des deux côtés", u"{}".format(len(rows))),
                    (u"   Conformes", u"{}".format(c[V_OK])),
                    (u"   Déplacées", u"{}".format(c[V_DEP])),
                    (u"   Volumétrie différente", u"{}".format(c[V_VOL])),
                    (u"   Déplacées + volumétrie", u"{}".format(c[V_DEPVOL])),
                    (u"   Non mesurables", u"{}".format(c[V_NM])),
                    (u"   Appariées par ADN identique", u"{}".format(
                        len([r for r in rows if r.App == APP_ADN]))),
                    (u"   Appariées par repli N° + maquette (ADN refigé)", u"{}".format(
                        len([r for r in rows if r.App == APP_RESOU]))),
                    (u"", u""),
                    (u"Présentes dans le lien seulement (hors contrôle)",
                     u"{}".format(nb_lien_seul)),
                    (u"Présentes dans la STR seulement (hors contrôle)",
                     u"{}".format(nb_str_seul)),
                    (u"", u""),
                    (u"Lecture des écarts",
                     u"ΔX / ΔY / ΔZ = position SPV − position STR, repère de la STR"),
                ]
                exporter_excel(cibles, resume, dlg.FileName)
                prefs["last_folder"] = os.path.dirname(dlg.FileName)
                _save_prefs(prefs)
                info(u"Export réussi :\n{}".format(dlg.FileName))
            except Exception as ex:
                info(u"Erreur d'export :\n{}".format(ex), SW.MessageBoxImage.Error)

        cb.SelectionChanged += refresh
        tb.TextChanged      += refresh
        win.FindName("btn_tol").Click     += on_tol
        win.FindName("btn_recaler").Click += on_recaler
        win.FindName("btn_sel").Click     += on_sel
        win.FindName("btn_3d").Click      += on_3d
        win.FindName("btn_export").Click  += on_export
        win.FindName("btn_close").Click   += lambda s, e: win.Close()

        classer_tout()
        c = maj_resume()
        if not (c[V_DEP] + c[V_VOL] + c[V_DEPVOL]):
            # Rien a signaler : on montre tout plutot qu'un tableau vide
            cb.SelectedIndex = F_TOUT
        refresh()

        # Rattachee a Revit et passee au premier plan : sans proprietaire, la
        # fenetre peut s'ouvrir derriere Revit.
        try:
            from System.Windows.Interop import WindowInteropHelper
            WindowInteropHelper(win).Owner = __revit__.MainWindowHandle
        except Exception:
            pass

        def _activer(s, e):
            try:
                win.Activate()
                win.Topmost = True
                win.Topmost = False
            except Exception:
                pass

        win.Loaded += _activer
        win.ShowDialog()

    # =========================================================================
    # MAIN
    # =========================================================================
    def main():
        lnk = find_link_instance()
        if lnk is None:
            TaskDialog.Show(TOOL_NAME,
                            u"Aucune maquette liée dont le nom contient « {} » n'a été "
                            u"trouvée.\n\nVérifie que le lien est chargé.".format(
                                LINK_MODEL_PREFIX))
            return
        ldoc = lnk.GetLinkDocument()
        if ldoc is None:
            TaskDialog.Show(TOOL_NAME,
                            u"Le lien « {} » n'est pas chargé : rien à comparer.".format(
                                _safe_name(lnk)))
            return

        paires, nb_lien_seul, nb_str_seul = apparier(collect_host(), collect_link(ldoc))
        if not paires:
            TaskDialog.Show(TOOL_NAME,
                            u"Aucune réservation présente à la fois dans la maquette STR et "
                            u"dans le lien : rien à contrôler.")
            return

        transform = lnk.GetTotalTransform()
        rows = [Row(h, l, mode, transform) for h, l, mode in paires]
        run_window(rows, _safe_name(lnk), nb_lien_seul, nb_str_seul)

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} — Erreur de chargement".format(TOOL_NAME, SCRIPT_VERSION), _ex)
