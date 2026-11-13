# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "1.4.0"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "FGH - Import Validation RES"
# =============================================================================
# Applique dans la maquette RES le fichier JSON ecrit par la page
# str-bim-tools.com/fgh/ (format STR_FGH_RES_VALIDATION) : statut, date et
# commentaire de validation (PVA_RES_VAL_*) changes par l'ingenieur.
#
# Appariement (voir lib/fgh_res.py) :
#   1. ADN (CONTROL_NE_PAS_TOUCHER) identique, le UniqueId departageant un
#      ADN en doublon ;
#   2. sinon le meme element (UniqueId) : ADN raccourci par « Nettoyer
#      Control » = accepte ; ADN different = reservation resoumise depuis
#      l'export, ligne decochee (l'ingenieur a juge l'ancienne demande).
# Une valeur changee dans Revit depuis l'export est signalee et decochee.
# Plusieurs fichiers (un par ingenieur) ou un fichier partage : par
# reservation et parametre, la decision la plus recente gagne ; un avis
# different d'un autre ingenieur decoche la ligne. Les decisions annulees
# (« retire ») ne sont jamais appliquees.
# Une ligne par reservation (1.4.0) : statut, date et commentaire avant /
# apres sur la meme ligne ; la case applique tous ses changements.
# Rien n'est ecrit sans validation, en une seule transaction.
# =============================================================================

import clr, traceback
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(title, ex):
    td = TaskDialog(title)
    td.MainContent     = u"Erreur : " + u"{}".format(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons   = TaskDialogCommonButtons.Close
    td.Show()


try:
    import io, os, json
    clr.AddReference("PresentationFramework"); clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase"); clr.AddReference("System")
    import System
    import System.Windows as SW
    from System.Windows import (Window, Thickness, MessageBox, MessageBoxButton,
                                MessageBoxImage, MessageBoxResult, WindowStartupLocation,
                                SystemColors)
    from System.Windows.Controls import (Grid, StackPanel, DataGrid, TextBlock, Border,
                                         DataGridTextColumn, DataGridCheckBoxColumn,
                                         Orientation, DataGridLength, DataGridLengthUnitType,
                                         DataGridHeadersVisibility, DataGridGridLinesVisibility,
                                         DataGridSelectionMode, DataGridSelectionUnit)
    from System.Windows.Data import Binding
    from Microsoft.Win32 import OpenFileDialog
    from Autodesk.Revit.DB import (Transaction, TransactionStatus, ElementId,
                                   StorageType, WorksharingUtils)
    from System.Collections.Generic import List
    import str_ui
    import fgh_res

    doc = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    app = __revit__.Application

    PRET, A_JOUR, CONFLIT, RESOUMISE, AMBIGU, INTROUVABLE, ABSENT, REFUSE, DIVERGENT, RETRAIT = (
        u"Prêt", u"Déjà à jour", u"Changé dans Revit depuis l'export",
        u"Demande resoumise depuis l'export", u"Clé en double, élément incertain",
        u"Réservation introuvable", u"Paramètre absent ou verrouillé", u"Paramètre non autorisé",
        u"Avis divergents entre ingénieurs",
        u"Retire une validation : Sync la supprimera de la STR")
    COCHABLES = (PRET, CONFLIT, RESOUMISE, DIVERGENT, RETRAIT, A_JOUR)

    # --- Index de la maquette ------------------------------------------------------
    class Index(object):
        def __init__(self):
            self.par_adn = {}
            self.par_uid = {}
            for e in fgh_res.reservations(doc, avec_supprimees=True):
                self.par_uid[e.UniqueId] = e
                k = fgh_res.adn(e)
                if k:
                    self.par_adn.setdefault(k, []).append(e)

        def trouver(self, cle, uid):
            """(element ou None, correspondance, statut force ou None)."""
            cle = (cle or u"").strip()
            cands = self.par_adn.get(cle, []) if cle else []
            if len(cands) == 1:
                return cands[0], u"ADN", None
            if len(cands) > 1:
                for e in cands:
                    if e.UniqueId == uid:
                        return e, u"ADN + UniqueId", None
                return None, u"ADN ×{}".format(len(cands)), AMBIGU
            e = self.par_uid.get(uid) if uid else None
            if e is None:
                return None, u"", INTROUVABLE
            actuel = fgh_res.adn(e)
            if cle and actuel and (actuel.startswith(cle) or cle.startswith(actuel)):
                return e, u"UniqueId (ADN raccourci)", None
            return e, u"UniqueId", RESOUMISE

    # --- Lignes ------------------------------------------------------------------
    def norm(v):
        return (u"{}".format(v) if v is not None else u"").strip()

    class Change(object):
        """Un parametre a changer sur une reservation (une entree du JSON)."""
        def __init__(self, m, index):
            self.Param = m.get(u"parametre") or u""
            self.Libelle = fgh_res.LIBELLES_VAL.get(self.Param, self.Param)
            self.Num = norm(m.get(u"numero"))
            self.Famille = norm(m.get(u"famille"))
            self.Niveau = norm(m.get(u"niveau"))
            self.Cle = norm(m.get(u"cle"))
            self.Uid = norm(m.get(u"unique_id"))
            self.Ancien = None if m.get(u"ancien") is None else norm(m.get(u"ancien"))
            self.Nouveau = norm(m.get(u"nouveau"))
            self.Par = norm(m.get(u"par"))
            self.Avis = norm(m.get(u"_avis"))
            self.ElemId = None
            self.Actuel = u""
            el, self.Corresp, force = index.trouver(self.Cle, self.Uid)
            if el is not None:
                self.ElemId = el.Id
                self.Id = u"{}".format(fgh_res.id_int(el.Id))
                self.Num = fgh_res.texte_param(el, fgh_res.PARAM_NUM) or self.Num
                self.Famille = fgh_res.famille(el) or self.Famille
                self.Niveau = fgh_res.niveau(doc, el) or self.Niveau
            else:
                self.Id = norm(m.get(u"element_id"))
            if self.Param not in fgh_res.PARAMS_VAL:
                self.Statut = REFUSE
            elif el is None:
                self.Statut = force
            else:
                p = el.LookupParameter(self.Param)
                if p is None or p.IsReadOnly or p.StorageType != StorageType.String:
                    self.Statut = ABSENT
                else:
                    self.Actuel = norm(p.AsString())
                    if self.Actuel == self.Nouveau:
                        self.Statut = A_JOUR
                    elif force:
                        self.Statut = force
                    elif self.Ancien is not None and not fgh_res.meme_texte(self.Actuel, self.Ancien):
                        # aux blancs pres : l'IFC lu par la page a change les retours a la ligne en espaces
                        self.Statut = CONFLIT
                    elif self.Avis:
                        self.Statut = DIVERGENT
                    elif self.Param == fgh_res.P_STATUT and fgh_res.est_valide(self.Actuel) \
                            and fgh_res.retire_validation(self.Nouveau):
                        # VALIDE -> refuse / vide : si la reservation est deja copiee dans la STR,
                        # Sync Reservations la marquera supprimee (cas D, coche d'office la-bas) : decochee ici
                        self.Statut = RETRAIT
                    else:
                        self.Statut = PRET
            self.AncienTxt = u"?" if self.Ancien is None else (self.Ancien or u"(vide)")
            self.NouveauTxt = self.Nouveau or u"(vide)"
            self.Modifiable = self.Statut in COCHABLES

        @property
        def ActuelTxt(self):
            return self.Actuel or (u"(vide)" if self.ElemId is not None else u"")

        @property
        def a_ecrire(self):
            return self.Modifiable and self.Statut != A_JOUR and self.ElemId is not None

    # gravite pour choisir l'etat affiche d'une reservation (le plus grave gagne)
    GRAVITE = [INTROUVABLE, AMBIGU, ABSENT, REFUSE, RETRAIT, CONFLIT, RESOUMISE, DIVERGENT, PRET, A_JOUR]
    RISQUES = (CONFLIT, RESOUMISE, DIVERGENT, RETRAIT)

    class Groupe(object):
        """Une ligne de la fenetre : une reservation et ses changements
        (statut, date, commentaire), chacun avec sa valeur avant / apres."""
        def __init__(self, changes):
            ordre_p = dict((p, i) for i, p in enumerate(fgh_res.PARAMS_VAL))
            self.changes = sorted(changes, key=lambda c: ordre_p.get(c.Param, 9))
            c0 = self.changes[0]
            self.ElemId = c0.ElemId
            self.Num, self.Famille, self.Niveau, self.Id, self.Corresp = (
                c0.Num, c0.Famille, c0.Niveau, c0.Id, c0.Corresp)
            self.Par = u", ".join(sorted(set(c.Par for c in self.changes if c.Par)))
            self.Avis = u" ; ".join(u"{} : {}".format(c.Libelle, c.Avis) for c in self.changes if c.Avis)
            self.AvisInfo = self.Avis or None
            self.maj()
            # cochee seulement si tout est sur : aucun changement a risque
            self.IsSelected = self.Modifiable and any(c.Statut == PRET for c in self.changes) \
                and not any(c.Statut in RISQUES for c in self.changes)

        def change(self, param):
            for c in self.changes:
                if c.Param == param:
                    return c
            return None

        def maj(self):
            self.Modifiable = any(c.a_ecrire for c in self.changes)
            el = doc.GetElement(self.ElemId) if self.ElemId is not None else None
            for nom, param in ((u"Statut", fgh_res.P_STATUT), (u"Date", fgh_res.P_DATE),
                               (u"Comm", fgh_res.P_COMMENT)):
                c = self.change(param)
                if c is not None:
                    avant, apres = c.ActuelTxt, c.NouveauTxt
                    info = u"Avant : {}\nAprès : {}\nÀ l'export : {}".format(avant or u"(vide)", apres, c.AncienTxt)
                    if c.Statut != PRET:
                        info += u"\n" + c.Statut
                else:
                    # pas de changement : valeur actuelle seule, colonne apres vide
                    p = el.LookupParameter(param) if el is not None else None
                    avant = norm(p.AsString()) if p is not None and p.StorageType == StorageType.String else u""
                    apres, info = u"", u"Pas de changement."
                setattr(self, nom + u"Avant", avant)
                setattr(self, nom + u"Apres", apres)
                setattr(self, nom + u"Info", info)
            etats = [c.Statut for c in self.changes]
            pire = min(etats, key=lambda x: GRAVITE.index(x) if x in GRAVITE else 0)
            if len(set(etats)) > 1:
                self.Etat = u"{} ({})".format(pire, u", ".join(c.Libelle for c in self.changes
                                                                if c.Statut == pire))
            else:
                self.Etat = pire
            self.EtatInfo = u"\n".join(u"{} : {}".format(c.Libelle, c.Statut) for c in self.changes)
            self.EtatTri = GRAVITE.index(pire) if pire in GRAVITE else 0

        def toggle(self):
            if self.Modifiable:
                self.IsSelected = not self.IsSelected

    def regrouper(changes):
        groupes, ordre = {}, []
        for c in changes:
            k = (u"id", fgh_res.id_int(c.ElemId)) if c.ElemId is not None else (u"cle", c.Cle or c.Uid)
            if k not in groupes:
                groupes[k] = []; ordre.append(k)
            groupes[k].append(c)
        return [Groupe(groupes[k]) for k in ordre]

    def lire_fichier(chemin):
        with io.open(chemin, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        if not isinstance(d, dict) or d.get(u"format") != fgh_res.FORMAT:
            raise ValueError(u"Ce fichier ne vient pas de la page de validation des réservations FGH.")
        if int(d.get(u"version") or 0) > fgh_res.FORMAT_VERSION:
            raise ValueError(u"Fichier créé par une version plus récente de la page : "
                             u"fais « Mise à jour » de l'extension.")
        return d

    def fusionner(docs):
        """Decisions de plusieurs fichiers : par (reservation, parametre), la plus
        recente gagne (champ quand, sinon date du fichier). Les avis differents
        des autres ingenieurs sont notes dans _avis. Les annulations ne gardent
        rien a appliquer."""
        groupes = {}
        for d in docs:
            date_doc = norm(d.get(u"date"))
            for m in (d.get(u"modifications") or []):
                if not isinstance(m, dict):
                    continue
                cle = (norm(m.get(u"cle")) or u"uid:" + norm(m.get(u"unique_id")), norm(m.get(u"parametre")))
                m = dict(m)
                m[u"_q"] = norm(m.get(u"quand")) or date_doc
                if not norm(m.get(u"par")):
                    m[u"par"] = norm(d.get(u"auteur"))
                groupes.setdefault(cle, []).append(m)
        out = []
        for cle in groupes:
            l = sorted(groupes[cle], key=lambda x: x[u"_q"])
            m = l[-1]
            if m.get(u"retire"):
                continue
            autres = []
            for x in l[:-1]:
                if not x.get(u"retire") and norm(x.get(u"nouveau")) != norm(m.get(u"nouveau")) \
                        and norm(x.get(u"par")) != norm(m.get(u"par")):
                    t = u"{} : {}".format(norm(x.get(u"par")) or u"?", norm(x.get(u"nouveau")) or u"(vide)")
                    if t not in autres:
                        autres.append(t)
            m[u"_avis"] = u" ; ".join(autres)
            out.append(m)
        return out

    def ecrire(groupes):
        cibles = [c for g in groupes for c in g.changes if c.a_ecrire]
        n = ko = 0
        if doc.IsWorkshared:
            try:
                WorksharingUtils.CheckoutElements(doc, List[ElementId]([r.ElemId for r in cibles]))
            except Exception:
                pass
        t = Transaction(doc, u"STR - FGH : import des validations RES")
        try:
            t.Start()
            for r in cibles:
                el = doc.GetElement(r.ElemId)
                p = el.LookupParameter(r.Param) if el is not None else None
                try:
                    if p is None or p.IsReadOnly or p.Set(r.Nouveau) is False:
                        raise Exception()
                    r.Actuel = r.Nouveau; r.Statut = A_JOUR
                    n += 1
                except Exception:
                    ko += 1
            if t.GetStatus() == TransactionStatus.Started:
                t.Commit()
            for g in groupes:
                g.IsSelected = False; g.maj()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise
        return n, ko

    # --- Fenetre ---------------------------------------------------------------
    def fenetre(chemins, d, rows):
        win = Window()
        win.Title = u"{}  [v{}]".format(TOOL_NAME, SCRIPT_VERSION)
        win.Width = 1500; win.Height = 700; win.MinWidth = 1000; win.MinHeight = 400
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen
        win.Background = str_ui.couleur("fond")
        root = Grid()
        for h in ("Auto", "Auto", "*", "Auto"):
            root.RowDefinitions.Add(str_ui.rd(h))
        win.Content = root

        titre = str_ui.barre_titre(u"{}  |  {}  |  Revit {}".format(TOOL_NAME, doc.Title, app.VersionNumber))
        Grid.SetRow(titre, 0); root.Children.Add(titre)

        fb = Border()
        fb.Background = str_ui.couleur("fond_filtre"); fb.BorderBrush = str_ui.couleur("bordure")
        fb.BorderThickness = Thickness(0, 0, 0, 1); fb.Padding = Thickness(8, 7, 8, 7)
        Grid.SetRow(fb, 1); root.Children.Add(fb)
        col = StackPanel(); fb.Child = col
        info = TextBlock(); info.TextWrapping = SW.TextWrapping.Wrap; info.FontSize = 11.5
        maq = d.get(u"maquette") or {}
        par = sorted(set(c.Par for r in rows for c in r.changes if c.Par))
        info.Text = u"Fichier{} : {}\nValidé par : {}   |   IFC exporté le {} depuis « {} »".format(
            u"s" if len(chemins) > 1 else u"", u", ".join(os.path.basename(c) for c in chemins),
            u", ".join(par) or d.get(u"auteur") or u"(non renseigné)",
            maq.get(u"export_du") or u"?", maq.get(u"nom") or u"?")
        col.Children.Add(info)
        nom_maq = (maq.get(u"nom") or u"").strip().lower()
        if nom_maq and nom_maq not in (doc.Title or u"").lower() and (doc.Title or u"").lower() not in nom_maq:
            warn = TextBlock(); warn.TextWrapping = SW.TextWrapping.Wrap; warn.FontSize = 11.5
            warn.Foreground = str_ui.couleur("erreur"); warn.FontWeight = SW.FontWeights.SemiBold
            warn.Margin = Thickness(0, 4, 0, 0)
            warn.Text = (u"Attention : ces validations portent sur la maquette « {} », pas sur celle "
                         u"ouverte. Vérifie avant d'appliquer.").format(maq.get(u"nom"))
            col.Children.Add(warn)
        note = TextBlock(); note.TextWrapping = SW.TextWrapping.Wrap; note.FontSize = 11
        note.Foreground = str_ui.couleur("texte_gris"); note.Margin = Thickness(0, 4, 0, 6)
        note.Text = (u"Une ligne par réservation : statut, date et commentaire avant (Revit) et après (page web), "
                     u"la case applique tous ses changements ; survole une valeur pour voir celle de l'export. "
                     u"Les lignes prêtes sont cochées. « Changé dans Revit depuis l'export » et « Demande "
                     u"resoumise » sont décochées par sécurité : l'ingénieur a vu une autre version. « Avis divergents » : "
                     u"deux ingénieurs ne sont pas d'accord, la décision la plus récente est proposée. "
                     u"« Retire une validation » : décochée, car Sync Reservations supprimerait la réservation "
                     u"de la STR si elle y est déjà. Après l'import : synchroniser la RES, recharger le lien "
                     u"dans la STR, puis « Sync Reservations ».")
        col.Children.Add(note)
        barre = StackPanel(); barre.Orientation = Orientation.Horizontal; col.Children.Add(barre)
        lbl = TextBlock(); lbl.VerticalAlignment = SW.VerticalAlignment.Center
        lbl.Foreground = str_ui.couleur("titre"); lbl.FontWeight = SW.FontWeights.SemiBold

        dg = DataGrid(); dg.Margin = Thickness(8, 8, 8, 4)
        dg.AutoGenerateColumns = False; dg.IsReadOnly = True
        dg.AlternatingRowBackground = str_ui.couleur("ligne_alternee")
        dg.RowBackground = str_ui.couleur("fond"); dg.BorderBrush = str_ui.couleur("bordure")
        dg.HeadersVisibility = DataGridHeadersVisibility.Column
        dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
        dg.CanUserResizeColumns = True; dg.CanUserSortColumns = True; dg.FontSize = 12
        dg.SelectionMode = DataGridSelectionMode.Extended
        dg.SelectionUnit = DataGridSelectionUnit.FullRow
        for k, v in ((SystemColors.HighlightBrushKey, "#CFE3F7"),
                     (SystemColors.InactiveSelectionHighlightBrushKey, "#DDEBF8"),
                     (SystemColors.HighlightTextBrushKey, "#1A1A1A"),
                     (SystemColors.InactiveSelectionHighlightTextBrushKey, "#1A1A1A")):
            dg.Resources.Add(k, str_ui.hex_brush(v))
        cc = DataGridCheckBoxColumn(); cc.Header = u""; cc.Binding = Binding("IsSelected")
        cc.Width = DataGridLength(36); cc.SortMemberPath = "IsSelected"
        dg.Columns.Add(cc)

        def colonne(entete, champ, w, etoile=False, info=None, gras=False, tri=None):
            c = DataGridTextColumn(); c.Header = entete; c.Binding = Binding(champ)
            c.Width = DataGridLength(w, DataGridLengthUnitType.Star) if etoile else DataGridLength(w)
            if tri:
                c.SortMemberPath = tri
            if info or gras:
                st = SW.Style(TextBlock)
                if info:
                    st.Setters.Add(SW.Setter(SW.FrameworkElement.ToolTipProperty, Binding(info)))
                if gras:
                    st.Setters.Add(SW.Setter(TextBlock.FontWeightProperty, SW.FontWeights.SemiBold))
                st.Setters.Add(SW.Setter(TextBlock.TextTrimmingProperty, SW.TextTrimming.CharacterEllipsis))
                c.ElementStyle = st
            dg.Columns.Add(c)
        colonne(u"N° réservation", "Num", 100)
        colonne(u"Famille", "Famille", 135)
        colonne(u"Niveau", "Niveau", 70)
        colonne(u"Id", "Id", 65)
        colonne(u"Statut avant", "StatutAvant", 85, info="StatutInfo")
        colonne(u"Statut après", "StatutApres", 85, info="StatutInfo", gras=True)
        colonne(u"Date avant", "DateAvant", 78, info="DateInfo")
        colonne(u"Date après", "DateApres", 78, info="DateInfo", gras=True)
        colonne(u"Commentaire avant", "CommAvant", 1, True, info="CommInfo")
        colonne(u"Commentaire après", "CommApres", 1, True, info="CommInfo", gras=True)
        colonne(u"Par", "Par", 60)
        colonne(u"Autres avis", "Avis", 110, info="AvisInfo")
        colonne(u"Trouvée par", "Corresp", 95)
        colonne(u"État", "Etat", 190, info="EtatInfo", tri="EtatTri")
        Grid.SetRow(dg, 2); root.Children.Add(dg)

        footer, sp_btns, grid_f = str_ui.make_footer(SCRIPT_VERSION)
        Grid.SetRow(footer, 3); root.Children.Add(footer)

        def compteur():
            n = {}
            for r in rows:
                for c in r.changes:
                    n[c.Statut] = n.get(c.Statut, 0) + 1
            coche = sum(1 for r in rows if r.IsSelected)
            lbl.Text = u"{} réservation(s)  -  changements : {}  -  {} cochée(s)".format(
                len(rows), u", ".join(u"{} {}".format(v, k.lower())
                                     for k, v in sorted(n.items(), key=lambda x: -x[1])), coche)

        def redraw():
            dg.ItemsSource = None; dg.ItemsSource = rows
            compteur()

        def tout(s, e):
            for r in rows:
                if r.Modifiable:
                    r.IsSelected = True
            redraw()

        def rien(s, e):
            for r in rows:
                r.IsSelected = False
            redraw()
        barre.Children.Add(str_ui.small_btn(u"Tout cocher", tout))
        barre.Children.Add(str_ui.small_btn(u"Tout décocher", rien))
        barre.Children.Add(lbl)

        def sur_cellule(sender, e):
            try:
                if dg.CurrentColumn is not None and dg.CurrentColumn.DisplayIndex == 0 \
                        and dg.CurrentItem is not None:
                    dg.CurrentItem.toggle(); redraw()
            except Exception:
                pass
        dg.CurrentCellChanged += sur_cellule

        def voir(s, e):
            sel = [r for r in (list(dg.SelectedItems) or rows) if r.ElemId is not None]
            ids = List[ElementId]([r.ElemId for r in sel])
            if ids.Count == 0:
                return
            try:
                uidoc.Selection.SetElementIds(ids)
                uidoc.ShowElements(ids)
            except Exception:
                pass
            win.Close()

        def appliquer(s, e):
            cibles = [r for r in rows if r.IsSelected and r.Modifiable]
            nb = sum(1 for r in cibles for c in r.changes if c.a_ecrire)
            if not cibles:
                MessageBox.Show(u"Aucune ligne cochée.", TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Information)
                return
            n_risque = sum(1 for r in cibles if any(c.Statut in (CONFLIT, RESOUMISE, DIVERGENT)
                                                    for c in r.changes))
            n_retrait = sum(1 for r in cibles if any(c.Statut == RETRAIT for c in r.changes))
            msg = u"Écrire {} valeur(s) sur {} réservation(s) dans la maquette RES ?".format(nb, len(cibles))
            if n_risque:
                msg += (u"\n\nDont {} réservation(s) changée(s) dans Revit, resoumise(s) ou contestée(s) depuis l'export : "
                        u"la valeur actuelle sera remplacée.").format(n_risque)
            if n_retrait:
                msg += (u"\n\nDont {} réservation(s) VALIDE passée(s) à refusée ou vide : si elles sont déjà "
                        u"dans la STR, « Sync Reservations » proposera de les supprimer.").format(n_retrait)
            if MessageBox.Show(msg, TOOL_NAME, MessageBoxButton.YesNo,
                               MessageBoxImage.Question) != MessageBoxResult.Yes:
                return
            n, ko = ecrire(cibles)
            txt = (u"{} valeur(s) écrite(s).\n\nEnsuite : synchronise la maquette RES avec le fichier central, "
                   u"puis dans la maquette STR recharge le lien RES avant de lancer « Sync Reservations » "
                   u"(il lit le lien, pas cette maquette).").format(n)
            if ko:
                txt += u"\n{} écriture(s) impossible(s) (élément pris par un autre utilisateur ?).".format(ko)
            MessageBox.Show(txt, TOOL_NAME, MessageBoxButton.OK,
                            MessageBoxImage.Warning if ko else MessageBoxImage.Information)
            redraw()

        sp_btns.Children.Add(str_ui.footer_btn(u"Fermer", "fermer", 90, lambda s, e: win.Close()))
        bv = str_ui.footer_btn(u"Sélectionner dans Revit", "secondaire", 170, voir)
        bv.Foreground = str_ui.couleur("texte"); bv.Margin = Thickness(6, 0, 0, 0)
        sp_btns.Children.Add(bv)
        ba = str_ui.footer_btn(u"Appliquer", "appliquer", 110, appliquer)
        ba.Margin = Thickness(6, 0, 0, 0)
        sp_btns.Children.Add(ba)
        grid_f.Children.Add(sp_btns)
        redraw()
        return win

    def main():
        if not fgh_res.est_maquette_res(doc):
            MessageBox.Show(u"Ouvre la maquette RES ({}…) : c'est elle que lit « Sync Reservations ». "
                            u"Une validation écrite dans une autre maquette ne serait jamais reprise.".format(
                                fgh_res.MAQUETTE_RES_PREFIXE), TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        dlg = OpenFileDialog()
        dlg.Title = u"Fichier(s) de validation des réservations (str-bim-tools.com/fgh)"
        dlg.Multiselect = True
        dlg.Filter = u"Validation RES (*.json)|*.json|Tous les fichiers (*.*)|*.*"
        dl = os.path.join(os.environ.get("USERPROFILE", u""), u"Downloads")
        if os.path.isdir(dl):
            dlg.InitialDirectory = dl
        if not dlg.ShowDialog():
            return
        chemins = list(dlg.FileNames)
        docs = []
        for chemin in chemins:
            try:
                docs.append(lire_fichier(chemin))
            except Exception as ex:
                MessageBox.Show(u"Fichier illisible : {}\n{}".format(os.path.basename(chemin), ex), TOOL_NAME,
                                MessageBoxButton.OK, MessageBoxImage.Warning)
                return
        index = Index()
        changes = [Change(m, index) for m in fusionner(docs)]
        if not changes:
            MessageBox.Show(u"Le fichier ne contient aucune modification.", TOOL_NAME,
                            MessageBoxButton.OK, MessageBoxImage.Information)
            return
        rows = regrouper(changes)
        ordre = {PRET: 0, RETRAIT: 1, DIVERGENT: 2, CONFLIT: 3, RESOUMISE: 4, A_JOUR: 5}
        rows.sort(key=lambda r: (ordre.get(GRAVITE[r.EtatTri], 5), r.Niveau, r.Num))
        fenetre(chemins, docs[0], rows).ShowDialog()

    main()

except Exception as _ex:
    _show_fatal(u"{} v{} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
