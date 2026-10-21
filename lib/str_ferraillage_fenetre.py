# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_fenetre.py - Fenetre commune des outils "Ferraillage
# poutre", "Ferraillage poteau" et "Ferraillage semelle".
#
# Chaque bouton decrit ses champs (sections, types, valeurs par defaut) et
# les colonnes du tableau des elements ; cette fenetre construit le
# formulaire, affiche l'apercu (barres, poids, alertes) et cree le
# ferraillage via str_ferraillage_revit_elem.
#
# Champs : dict(cle, libelle, type, choix=None, aide=None), type parmi
#   "diam" (diametres disponibles), "nombre", "entier", "choix", "case".
# Compatible IronPython 2.7 (Revit 2024) et IronPython 3.4 (Revit 2025+).
# =============================================================================

import io
import json
import traceback

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("RevitAPI")

from System.Collections.Generic import List as NetList
from System.Windows import (Window, Thickness, WindowStartupLocation,
                            ResizeMode, MessageBox, MessageBoxButton,
                            MessageBoxImage, MessageBoxResult, TextWrapping)
from System.Windows.Controls import (Grid, StackPanel, DataGrid, WrapPanel,
                                     DataGridTextColumn, DataGridLength,
                                     DataGridLengthUnitType, ScrollViewer,
                                     ScrollBarVisibility,
                                     DataGridGridLinesVisibility,
                                     DataGridHeadersVisibility)
from System.Windows.Data import Binding

from Autodesk.Revit.DB import ElementId, View3D, Transaction, TransactionStatus

import str_ui as UI
import str_ferraillage as FER
import str_ferraillage_elements as ELEM
import str_ferraillage_revit_elem as RE


def charger_prefs(chemin):
    try:
        with io.open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def sauver_prefs(chemin, prefs):
    try:
        with io.open(chemin, "w", encoding="utf-8") as f:
            f.write(FER.vers_json(prefs))
    except Exception:
        pass


class _Ligne(object):
    """Ligne du tableau des elements (proprietes C0, C1... liees)."""

    def __init__(self, info, colonnes, existants):
        self.info = info
        self.Type = info.get("type", u"")
        self.Id = info["id"]
        for i, (_, fn, _) in enumerate(colonnes):
            try:
                val = u"" if info.get("erreur") else fn(info)
            except Exception:
                val = u"?"
            setattr(self, "C{0}".format(i), val)
        enr = info.get("enrobages") or {}
        self.Enrobages = u"" if info.get("erreur") else u" / ".join(
            u"-" if enr.get(k) is None else FER.fmt_nombre(enr[k], 1)
            for k in ("haut", "bas", "autre"))
        n_str, autres = existants or (0, 0)
        self.Existants = u"{0} STR".format(n_str) if n_str else u""
        if autres:
            self.Existants += (u" + " if n_str else u"") + \
                u"{0} autre(s)".format(autres)
        self.Remarque = info.get("erreur", u"")


class FenetreElements(Window):

    def __init__(self, p):
        """
        p : dict
            outil, titre, version, doc, uidoc, infos, existants, barres,
            crochets ([(libelle, type, angle)]), colonnes ([(entete, fn, larg)]),
            sections ([(titre, [champs])]), defauts (dict), prefs (chemin),
            partition (defaut), etriers (True si un crochet est a choisir)
        """
        self.p = p
        self.doc = p["doc"]
        self.Title = p["titre"]
        self.Width = 1080
        self.Height = 800
        self.MinWidth = 900
        self.MinHeight = 600
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.CanResize
        self.Background = UI.couleur("fond")
        self.prefs = charger_prefs(p["prefs"])
        self.config_elem = None
        for info in p["infos"]:
            if info.get("erreur"):
                continue
            outil, cfg = RE.donnees_element(info["elem"])
            if outil == p["outil"] and cfg:
                self.config_elem = cfg
                break
        self.controles = {}
        self.cree = 0
        self._construire()
        self._apercu()

    def _src(self, cle, defaut=None):
        if defaut is None:
            defaut = self.p["defauts"].get(cle)
        if self.config_elem and cle in self.config_elem:
            return self.config_elem[cle]
        return self.prefs.get(cle, defaut)

    # --- Construction ---------------------------------------------------------
    def _construire(self):
        root = Grid()
        for h in ["Auto", "*", "Auto"]:
            root.RowDefinitions.Add(UI.rd(h))
        self.Content = root
        titre = UI.barre_titre(u"{0}  |  Revit {1}".format(
            self.p["titre"], self.doc.Application.VersionNumber))
        Grid.SetRow(titre, 0)
        root.Children.Add(titre)

        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        corps = StackPanel()
        corps.Margin = Thickness(12, 4, 12, 8)
        sv.Content = corps
        Grid.SetRow(sv, 1)
        root.Children.Add(sv)

        corps.Children.Add(UI.section_hdr(u"Éléments sélectionnés"))
        corps.Children.Add(self._grille())

        wp = WrapPanel()
        for titre_s, champs in self.p["sections"] + [(u"Options", self._options())]:
            bloc = StackPanel()
            bloc.Width = 330
            bloc.Margin = Thickness(0, 0, 10, 0)
            bloc.Children.Add(UI.section_hdr(titre_s))
            gb = UI.group_box()
            sp = StackPanel()
            gb.Child = sp
            for ch in champs:
                sp.Children.Add(self._champ(ch))
            bloc.Children.Add(gb)
            wp.Children.Add(bloc)
        corps.Children.Add(wp)

        self.lbl_apercu = UI.texte(u"", 11, marge=Thickness(2, 4, 2, 0))
        self.lbl_apercu.TextWrapping = TextWrapping.Wrap
        corps.Children.Add(self.lbl_apercu)

        footer, sp_btns, grid_f = UI.make_footer(self.p["version"])
        Grid.SetRow(footer, 2)
        root.Children.Add(footer)
        for libelle, cle, larg, handler in (
                (u"Aperçu", "fermer", 90, self._on_apercu),
                (u"Créer le ferraillage", "appliquer", 160, self._on_creer),
                (u"Fermer", "annuler", 90, lambda s, e: self.Close())):
            b = UI.footer_btn(libelle, cle, larg, handler)
            b.Margin = Thickness(6, 0, 0, 0)
            sp_btns.Children.Add(b)
        grid_f.Children.Add(sp_btns)

    def _options(self):
        champs = [
            {"cle": "enrobage", "libelle": u"Enrobage (cm)", "type": "nombre",
             "aide": u"Utilisé si l'élément n'a pas d'enrobage Revit"},
            {"cle": "enrobage_revit", "libelle":
             u"Enrobages Revit de l'élément (haut / bas / autres)",
             "type": "case"},
        ]
        if self.p.get("etriers"):
            champs.append({"cle": "crochet", "libelle": u"Crochets étriers",
                           "type": "choix",
                           "choix": [(lib, lib) for lib, _, _ in self.p["crochets"]]})
        champs.append({"cle": "partition", "libelle": u"Partition", "type": "texte"})
        champs.append({"cle": "vue3d", "libelle":
                       u"Barres visibles dans la vue 3D active", "type": "case"})
        return champs

    def _champ(self, ch):
        cle, typ = ch["cle"], ch["type"]
        if cle == "partition":
            val = self._src(cle, self.p.get("partition", u""))
        elif cle == "vue3d":
            val = self.prefs.get("vue3d", True)
        elif cle == "crochet":
            val = self._src(cle, self.p["crochets"][0][0]
                            if self.p["crochets"] else u"")
        else:
            val = self._src(cle)
        if typ == "case":
            ctl = UI.checkbox(ch["libelle"], bool(val), ch.get("aide"))
            self.controles[cle] = (typ, ctl)
            return ctl
        if typ == "diam":
            diam = sorted(self.p["barres"]) or [12]
            ctl = UI.combo([(u"Ø{0}".format(d), d) for d in diam], 0, 120)
            if not UI.selectionner_valeur(ctl, int(val or 0)):
                proche = min(diam, key=lambda d: abs(d - int(val or 0)))
                UI.selectionner_valeur(ctl, proche)
        elif typ == "choix":
            ctl = UI.combo(ch["choix"], 0, 170)
            UI.selectionner_valeur(ctl, val)
        else:
            ctl = UI.zone_texte(120 if typ != "texte" else 170,
                                u"" if val is None else u"{0}".format(val))
        if ch.get("aide"):
            ctl.ToolTip = ch["aide"]
        self.controles[cle] = (typ, ctl)
        return UI.ligne_champ(ch["libelle"], ctl, 150)

    def _grille(self):
        dg = DataGrid()
        dg.AutoGenerateColumns = False
        dg.IsReadOnly = True
        dg.MaxHeight = 170
        dg.AlternatingRowBackground = UI.couleur("ligne_alternee")
        dg.RowBackground = UI.couleur("fond")
        dg.GridLinesVisibility = DataGridGridLinesVisibility.Horizontal
        dg.HeadersVisibility = DataGridHeadersVisibility.Column
        dg.BorderBrush = UI.couleur("bordure")
        dg.FontSize = 12
        cols = [(u"Type", "Type", 170), (u"ID", "Id", 75)]
        cols += [(ent, "C{0}".format(i), larg)
                 for i, (ent, _, larg) in enumerate(self.p["colonnes"])]
        cols += [(u"Enrobages haut/bas/autres cm", "Enrobages", 110),
                 (u"Armatures existantes", "Existants", 110),
                 (u"Remarque", "Remarque", 0)]
        for entete, prop, larg in cols:
            col = DataGridTextColumn()
            col.Header = entete
            col.Binding = Binding(prop)
            col.Width = DataGridLength(larg) if larg else \
                DataGridLength(1, DataGridLengthUnitType.Star)
            dg.Columns.Add(col)
        dg.ItemsSource = [_Ligne(i, self.p["colonnes"],
                                 self.p["existants"].get(i["id"]))
                          for i in self.p["infos"]]
        return dg

    # --- Lecture du formulaire -----------------------------------------------
    def _config(self):
        cfg = {}
        for cle, (typ, ctl) in self.controles.items():
            if typ == "case":
                cfg[cle] = bool(ctl.IsChecked)
            elif typ in ("diam", "choix"):
                cfg[cle] = UI.valeur_combo(ctl, self.p["defauts"].get(cle))
            elif typ == "texte":
                cfg[cle] = ctl.Text or u""
            else:
                txt = (ctl.Text or u"").strip().replace(u",", u".")
                if not txt:
                    cfg[cle] = self.p["defauts"].get(cle, 0)
                    continue
                try:
                    v = float(txt)
                except ValueError:
                    raise ValueError(u"Valeur invalide : {0}".format(txt))
                if v < 0:
                    raise ValueError(u"Valeur négative : {0}".format(txt))
                cfg[cle] = int(round(v)) if typ == "entier" else v
        vue3d = cfg.pop("vue3d", True)
        return cfg, vue3d

    def _calculer(self, config):
        res, alertes, nb, kg = [], [], 0, 0.0
        for info in self.p["infos"]:
            if info.get("erreur"):
                continue
            jeux, err, inf = RE.calculer(info, config)
            n, k = ELEM.poids_jeux(jeux, FER.kg_par_m)
            nb += n
            kg += k
            alertes.extend(u"{0} : {1}".format(info["id"], m) for m in err)
            if len(self.p["infos"]) == 1:
                alertes.extend(inf)
            res.append((info, jeux))
        return res, alertes, nb, kg

    def _apercu(self):
        try:
            config, _ = self._config()
        except ValueError as ex:
            self.lbl_apercu.Text = u"{0}".format(ex)
            return
        res, alertes, nb, kg = self._calculer(config)
        txt = u"Aperçu : {0} élément(s), {1} jeux de barres, {2} barres, " \
              u"environ {3} kg.".format(len(res), sum(len(j) for _, j in res),
                                        nb, FER.fmt_nombre(kg, 0))
        if alertes:
            txt += u"\n" + u"\n".join(alertes[:10])
        ignores = [i for i in self.p["infos"] if i.get("erreur")]
        if ignores:
            txt += u"\n{0} élément(s) ignoré(s) (voir Remarque).".format(len(ignores))
        self.lbl_apercu.Text = txt

    def _on_apercu(self, sender, e):
        try:
            self._apercu()
        except Exception as ex:
            self.lbl_apercu.Text = u"Erreur : {0}".format(ex)

    # --- Creation ---------------------------------------------------------------
    def _on_creer(self, sender, e):
        # Une exception dans un evenement WPF est avalee sans message.
        try:
            self._creer()
        except Exception as ex:
            MessageBox.Show(u"Création impossible :\n{0}\n\n{1}".format(
                ex, traceback.format_exc()), self.p["titre"],
                MessageBoxButton.OK, MessageBoxImage.Error)

    def _creer(self):
        titre = self.p["titre"]
        try:
            config, vue3d_ok = self._config()
        except ValueError as ex:
            MessageBox.Show(u"{0}".format(ex), titre, MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return
        self.prefs.update(config)
        self.prefs["vue3d"] = vue3d_ok
        sauver_prefs(self.p["prefs"], self.prefs)
        res, alertes, nb, kg = self._calculer(config)
        if not any(j for _, j in res):
            MessageBox.Show(u"Aucune barre à créer.", titre,
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        deja = [i for i, _ in res
                if (self.p["existants"].get(i["id"]) or (0, 0))[1]]
        if deja:
            r = MessageBox.Show(
                u"{0} élément(s) ont déjà des armatures non créées par cet "
                u"outil (elles sont conservées). Continuer ?".format(len(deja)),
                titre, MessageBoxButton.YesNo, MessageBoxImage.Question)
            if r != MessageBoxResult.Yes:
                return
        manquants = sorted(set(j["d"] for _, js in res for j in js
                               if j["d"] not in self.p["barres"]))
        if manquants:
            MessageBox.Show(u"Aucun type de barre Revit pour Ø {0}.".format(
                u", ".join(u"{0}".format(d) for d in manquants)), titre,
                MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        doc = self.doc
        vue3d = doc.ActiveView if (vue3d_ok and
                                   isinstance(doc.ActiveView, View3D)) else None
        t = Transaction(doc, u"STR - " + titre)
        echecs, crees, remplacees = [], [], 0
        try:
            t.Start()
            for info, _ in res:
                ids, nb_supp, err = RE.ferrailler(doc, info, config,
                                                  self.p["barres"], vue3d)
                crees.extend(ids)
                remplacees += nb_supp
                echecs.extend(u"{0} : {1}".format(info["id"], m) for m in err)
            if t.GetStatus() == TransactionStatus.Started:
                t.Commit()
        except Exception:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
            raise
        self.cree = len(crees)
        msg = u"{0} jeux de barres créés ({1} barres, environ {2} kg).".format(
            len(crees), nb, FER.fmt_nombre(kg, 0))
        if remplacees:
            msg += u"\n{0} jeu(x) STR précédent(s) remplacé(s).".format(remplacees)
        msg += u"\nConfiguration enregistrée dans l'élément : « Mettre à " \
               u"jour ferraillage » le recalcule après une modification."
        if echecs:
            msg += u"\n\n{0} alerte(s) :\n{1}".format(len(echecs),
                                                     u"\n".join(echecs[:10]))
        MessageBox.Show(msg, titre, MessageBoxButton.OK,
                        MessageBoxImage.Information if not echecs
                        else MessageBoxImage.Warning)
        if crees:
            ids = NetList[ElementId]()
            for i in crees:
                ids.Add(i)
            try:
                self.p["uidoc"].Selection.SetElementIds(ids)
            except Exception:
                pass
            self.Close()
