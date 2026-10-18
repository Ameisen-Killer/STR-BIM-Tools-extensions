# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "3.6.2"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Export IFC"
# =============================================================================
#
# Export IFC par lot depuis les vues 3D du projet.
#
# Reecriture complete de la v2.4.1. Ce que la version precedente faisait mal :
#
#  1. Elle ne transmettait a l'exporteur que 4 options (version, quantites,
#     decoupage, espaces). Les ~30 autres options du panneau Revit n'etaient
#     jamais envoyees, donc l'exporteur appliquait ses replis internes : les
#     elements acier etaient omis, la geometrie etait triangulee grossierement
#     (niveau de detail bas, pas de representation solide), les jeux de
#     proprietes Revit et IFC manquaient. D'ou des IFC incomplets et moins
#     precis qu'un export lance depuis le menu Revit.
#     -> Corrige dans lib/str_ifc.py : toutes les options sont transmises.
#
#  2. Le "moteur Open IFC" importait IFCExportConfiguration depuis
#     Autodesk.Revit.DB.IFC, ou cette classe n'existe pas. L'import echouait
#     donc toujours en silence et l'option restait grisee.
#     -> Corrige : chargement de Autodesk.IFC.Export.UI.dll, ce qui permet de
#        reprendre les setups IFC enregistres dans le modele.
#
#  3. Divers : transfert des parametres par fichier JSON temporaire a nom fixe,
#     fuite d'un thread de chronometre par vue, attente de demarrage non bornee
#     pouvant figer Revit, faux succes quand un ancien fichier restait present,
#     collisions de noms de fichiers silencieuses, aucun try/finally autour de
#     la boucle d'export, traces d'erreur invisibles a cause de "nowindow".
#     -> Tout cela est repris ici et dans lib/str_progress_sta.py.
#
# =============================================================================

# Hors filet : strict minimum pour pouvoir afficher une erreur fatale.
import clr
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons


def _show_fatal(titre, ex):
    td = TaskDialog(titre)
    td.MainContent = u"Erreur : " + u"{0}".format(ex)
    td.ExpandedContent = traceback.format_exc()
    td.CommonButtons = TaskDialogCommonButtons.Close
    td.Show()


try:
    import io
    import json
    import os
    import time

    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")

    import System
    import System.Diagnostics
    import System.Windows as SW
    import System.Windows.Controls as SWC
    from System.Windows import (MessageBox, MessageBoxButton, MessageBoxImage,
                                MessageBoxResult, Thickness, Window)
    from System.Windows.Controls import (DockPanel, Grid, ListBox, ListBoxItem,
                                         Orientation, ScrollViewer,
                                         SelectionMode, StackPanel)
    from System.Windows.Forms import (DialogResult, FolderBrowserDialog,
                                      OpenFileDialog)

    from Autodesk.Revit.DB import (FailureProcessingResult, FailureSeverity,
                                   FilteredElementCollector,
                                   IFailuresPreprocessor, Transaction,
                                   TransactionStatus, View3D)
    # Capture des echecs au niveau application : secondaire (le prehandler de la
    # transaction fait le travail principal). Import defensif : un mecanisme de
    # diagnostic ne doit pas pouvoir empecher l'outil de demarrer.
    try:
        from Autodesk.Revit.DB.Events import FailuresProcessingEventArgs
    except ImportError:
        FailuresProcessingEventArgs = None

    import str_ifc
    import str_progress_revit
    import str_progress_sta
    import str_ui

    doc = __revit__.ActiveUIDocument.Document
    app = __revit__.Application

    _FOOTER = u"v{0} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)

    _PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "prefs.json")

    # Un IFC plus petit que ce seuil signale presque toujours une vue vide ou
    # une boite de coupe trop restrictive : on le remonte comme suspect.
    SEUIL_SUSPECT_OCTETS = 30 * 1024

    # Caracteres refuses par Windows, plus ceux que Revit lui-meme refuse dans
    # les noms d'elements et qui se retrouvent souvent dans les noms de vues.
    CAR_INTERDITS = u'\\/:*?"<>|{}[];~`\r\n\t'

    # Version du format de prefs.json. Passee a 4 quand les defauts sont devenus
    # la configuration en session verifiee (IFC 2x3 CV 2.0, seule avec laquelle
    # un export a abouti). Les reglages memorises par les versions precedentes
    # sont ignores au chargement, sinon ils masqueraient cette configuration -
    # ce sont justement ceux qui faisaient echouer l'export. Le dossier de sortie
    # et la selection de vues, eux, sont conserves.
    PREFS_VERSION = 4

    # ======================================================================
    # Preferences
    # ======================================================================
    def charger_prefs():
        """(reglages, dossier, noms_de_vues) - jamais d'exception."""
        reglages = str_ifc.reglages_par_defaut()
        brut = {}
        try:
            if os.path.isfile(_PREFS_FILE):
                with io.open(_PREFS_FILE, "r", encoding="utf-8") as f:
                    brut = json.load(f)
        except Exception:
            brut = {}

        try:
            version_prefs = int(brut.get("prefs_version", 1))
        except (TypeError, ValueError):
            version_prefs = 1
        if version_prefs < PREFS_VERSION:
            for clef in list(reglages.keys()):
                brut.pop(clef, None)

        for clef, defaut in list(reglages.items()):
            if clef not in brut:
                continue
            valeur = brut[clef]
            try:
                if isinstance(defaut, bool):
                    reglages[clef] = bool(valeur)
                elif isinstance(defaut, float):
                    reglages[clef] = float(valeur)
                elif isinstance(defaut, int):
                    reglages[clef] = int(valeur)
                else:
                    reglages[clef] = u"{0}".format(valeur)
            except (TypeError, ValueError):
                pass

        # "last_folder" : clef des versions <= 2.4.1, reprise pour ne pas
        # perdre le dossier deja memorise.
        dossier = brut.get("dossier") or brut.get("last_folder") or u""
        if not (dossier and os.path.isdir(dossier)):
            dossier = os.path.dirname(doc.PathName) if doc.PathName else u""
        if not (dossier and os.path.isdir(dossier)):
            dossier = os.path.expanduser(u"~\\Desktop")

        vues = brut.get("vues") or []
        if not isinstance(vues, list):
            vues = []
        return reglages, dossier, [u"{0}".format(v) for v in vues]

    def enregistrer_prefs(reglages, dossier, noms_vues):
        try:
            donnees = dict(reglages)
            donnees["prefs_version"] = PREFS_VERSION
            donnees["dossier"] = dossier
            donnees["vues"] = noms_vues
            # ensure_ascii=True : la sortie est du str pur ASCII, donc
            # ecrivable tel quel dans un flux unicode en IronPython 2 comme en
            # 3. Les accents sont echappes en \uXXXX et relus correctement.
            texte_json = json.dumps(donnees, ensure_ascii=True, indent=2,
                                    sort_keys=True)
            with io.open(_PREFS_FILE, "w", encoding="utf-8") as f:
                f.write(u"{0}".format(texte_json))
        except Exception:
            pass

    # ======================================================================
    # Vues et noms de fichiers
    # ======================================================================
    def collecter_vues():
        """Vues 3D exportables, triees par nom."""
        vues = []
        for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
            try:
                if v.IsTemplate or not v.CanBePrinted:
                    continue
                vues.append(v)
            except Exception:
                pass
        return sorted(vues, key=lambda v: v.Name.lower())

    def boite_de_coupe_active(vue):
        try:
            return bool(vue.IsSectionBoxActive)
        except Exception:
            return False

    def nom_gabarit(vue):
        try:
            gid = vue.ViewTemplateId
            if gid is not None and str_ifc.id_value(gid) > 0:
                gabarit = doc.GetElement(gid)
                if gabarit is not None:
                    return gabarit.Name
        except Exception:
            pass
        return None

    def nom_fichier_sur(nom):
        """
        Nom de vue -> nom de fichier valide, en restant lisible : les accents,
        espaces et tirets sont conserves, seuls les caracteres refuses par
        Windows sont remplaces.
        """
        propre = []
        for c in nom:
            propre.append(u"_" if (c in CAR_INTERDITS or ord(c) < 32) else c)
        txt = u"".join(propre)
        while u"__" in txt:
            txt = txt.replace(u"__", u"_")
        txt = txt.strip(u" _.")
        return txt or u"vue"

    def noms_cibles(vues, prefixe):
        """
        [(vue, radical_unique)] - deduplique les radicaux : deux vues dont les
        noms se normalisent pareil ecrivaient dans le meme fichier, le second
        ecrasant le premier tout en etant compte comme reussi.
        """
        resultat = []
        pris = {}
        for v in vues:
            radical = nom_fichier_sur(prefixe + nom_fichier_sur(v.Name))
            cle = radical.lower()
            if cle in pris:
                pris[cle] += 1
                radical = u"{0}_{1}".format(radical, pris[cle])
            else:
                pris[cle] = 1
            resultat.append((v, radical))
        return resultat

    def etat_fichier(chemin):
        """(existe, taille, mtime)."""
        try:
            if os.path.isfile(chemin):
                return True, os.path.getsize(chemin), os.path.getmtime(chemin)
        except Exception:
            pass
        return False, 0, 0.0

    def trouver_sortie(dossier, radical, extension):
        """
        Fichier reellement ecrit par l'exporteur. On ne suppose pas l'extension :
        selon le type de fichier demande, Revit ecrit .ifc, .ifcZIP, .ifcXML...
        """
        candidats = [radical + extension]
        for _nom, _lib, ext in str_ifc.TYPES_FICHIER:
            candidats.append(radical + ext)
        for c in candidats:
            chemin = os.path.join(dossier, c)
            if os.path.isfile(chemin):
                return chemin
        try:
            prefixe = (radical + u".").lower()
            for entree in os.listdir(dossier):
                if (entree.lower().startswith(prefixe)
                        and entree.lower().find(u".ifc") >= 0):
                    return os.path.join(dossier, entree)
        except Exception:
            pass
        return os.path.join(dossier, radical + extension)

    # ======================================================================
    # Fenetre principale
    # ======================================================================
    class DialogueExportIFC(Window):

        def __init__(self, vues, reglages, dossier, vues_memorisees):
            self._vues = vues
            self._reglages = reglages
            self._resultat = None
            self._ids_selectionnes = set()

            self._setups, self._diag_setups = str_ifc.setups_du_modele(doc)
            self._setups_par_nom = dict(self._setups)
            # Configuration en session = reglages du dernier export IFC manuel.
            # Toujours transmise a l'export pour etre tracee dans le journal,
            # meme quand elle n'est pas la configuration choisie.
            self._config_session = None
            for _nom, _cfg in self._setups:
                if _nom.lower().find(u"session") >= 0:
                    self._config_session = _cfg
                    break
            self._phases = str_ifc.phases_disponibles(doc)
            self._groupes_manuels = []

            self.Title = TOOL_NAME
            self.Width = 1040
            self.Height = 760
            self.MinWidth = 900
            self.MinHeight = 620
            self.ResizeMode = SW.ResizeMode.CanResizeWithGrip
            self.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
            self.Background = str_ui.couleur("fond")

            self._construire(dossier)
            self._preselectionner(vues_memorisees)
            self._maj_etat_setup(None, None)

        # ------------------------------------------------------------------
        def _construire(self, dossier):
            racine = Grid()
            for h in ["Auto", "*", "Auto"]:
                racine.RowDefinitions.Add(str_ui.rd(h))
            self.Content = racine

            titre = str_ui.barre_titre(
                u"{0}  |  Revit {1}".format(TOOL_NAME, app.VersionNumber),
                icone=u"\U0001f4c1")
            Grid.SetRow(titre, 0)
            racine.Children.Add(titre)

            corps = Grid()
            corps.Margin = Thickness(14, 6, 14, 6)
            corps.ColumnDefinitions.Add(str_ui.cd("*"))
            corps.ColumnDefinitions.Add(str_ui.cd(430))
            Grid.SetRow(corps, 1)
            racine.Children.Add(corps)

            colonne_vues = self._colonne_vues()
            Grid.SetColumn(colonne_vues, 0)
            corps.Children.Add(colonne_vues)

            colonne_options = self._colonne_options(dossier)
            colonne_options.Margin = Thickness(14, 0, 0, 0)
            Grid.SetColumn(colonne_options, 1)
            corps.Children.Add(colonne_options)

            footer, sp_btns, grid_f = str_ui.make_footer(SCRIPT_VERSION)
            Grid.SetRow(footer, 2)
            racine.Children.Add(footer)
            btn_annuler = str_ui.footer_btn(u"Annuler", "annuler", 90,
                                           self._on_annuler)
            btn_annuler.Margin = Thickness(0, 0, 6, 0)
            sp_btns.Children.Add(btn_annuler)
            sp_btns.Children.Add(str_ui.footer_btn(u"Exporter", "exporter", 110,
                                                  self._on_exporter))
            grid_f.Children.Add(sp_btns)

        # ------------------------------------------------------------------
        def _colonne_vues(self):
            grille = Grid()
            for h in ["Auto", "*"]:
                grille.RowDefinitions.Add(str_ui.rd(h))

            entete = str_ui.section_hdr(
                u"Vues 3D a exporter  ({0} disponibles)".format(len(self._vues)))
            Grid.SetRow(entete, 0)
            grille.Children.Add(entete)

            boite = str_ui.group_box(stretch=True)
            Grid.SetRow(boite, 1)
            grille.Children.Add(boite)

            interne = Grid()
            for h in ["Auto", "Auto", "*"]:
                interne.RowDefinitions.Add(str_ui.rd(h))
            boite.Child = interne

            # Filtre
            sp_filtre = StackPanel()
            sp_filtre.Orientation = Orientation.Horizontal
            sp_filtre.Margin = Thickness(0, 0, 0, 6)
            sp_filtre.Children.Add(str_ui.texte(u"Filtrer :",
                                                marge=Thickness(0, 0, 6, 0)))
            self.txt_filtre = str_ui.zone_texte(largeur=240)
            self.txt_filtre.TextChanged += self._on_filtre
            sp_filtre.Children.Add(self.txt_filtre)
            sp_filtre.Children.Add(str_ui.small_btn(u"x", self._on_filtre_vide,
                                                    u"Effacer le filtre"))
            self.lbl_compte = str_ui.texte(u"", brush=str_ui.couleur("texte_gris"),
                                           marge=Thickness(4, 0, 8, 0))
            sp_filtre.Children.Add(self.lbl_compte)
            self.lbl_selection = str_ui.texte(u"", gras=True,
                                              brush=str_ui.couleur("erreur"),
                                              marge=Thickness(0))
            sp_filtre.Children.Add(self.lbl_selection)
            Grid.SetRow(sp_filtre, 0)
            interne.Children.Add(sp_filtre)

            sp_boutons = StackPanel()
            sp_boutons.Orientation = Orientation.Horizontal
            sp_boutons.Margin = Thickness(0, 0, 0, 6)
            sp_boutons.Children.Add(str_ui.small_btn(
                u"Tout selectionner (filtre)", self._on_tout))
            sp_boutons.Children.Add(str_ui.small_btn(
                u"Tout deselectionner (filtre)", self._on_rien))
            Grid.SetRow(sp_boutons, 1)
            interne.Children.Add(sp_boutons)

            self.lst_vues = ListBox()
            self.lst_vues.SelectionMode = SelectionMode.Multiple
            self.lst_vues.Background = str_ui.couleur("fond")
            self.lst_vues.BorderBrush = str_ui.couleur("bordure")
            self.lst_vues.FontSize = 11
            for v in self._vues:
                item = ListBoxItem()
                suffixe = u"   [boite de coupe]" if boite_de_coupe_active(v) else u""
                item.Content = v.Name + suffixe
                item.Tag = v
                infos = [u"Vue 3D : {0}".format(v.Name)]
                if boite_de_coupe_active(v):
                    infos.append(u"Boite de coupe ACTIVE : seuls les elements "
                                 u"a l'interieur seront exportes.")
                gab = nom_gabarit(v)
                if gab:
                    infos.append(u"Gabarit de vue : {0}".format(gab))
                item.ToolTip = u"\n".join(infos)
                item.Selected += self._on_item_selectionne
                item.Unselected += self._on_item_deselectionne
                self.lst_vues.Items.Add(item)
            Grid.SetRow(self.lst_vues, 2)
            interne.Children.Add(self.lst_vues)
            return grille

        # ------------------------------------------------------------------
        def _colonne_options(self, dossier):
            defileur = ScrollViewer()
            defileur.VerticalScrollBarVisibility = SWC.ScrollBarVisibility.Auto
            defileur.HorizontalScrollBarVisibility = SWC.ScrollBarVisibility.Disabled
            pile = StackPanel()
            defileur.Content = pile
            r = self._reglages

            # --- Dossier ---
            pile.Children.Add(str_ui.section_hdr(u"Dossier de sortie"))
            grp = str_ui.group_box()
            dp = DockPanel()
            dp.LastChildFill = True
            btn = str_ui.small_btn(u"Parcourir...", self._on_parcourir)
            btn.Margin = Thickness(6, 0, 0, 0)
            DockPanel.SetDock(btn, SWC.Dock.Right)
            dp.Children.Add(btn)
            self.txt_dossier = str_ui.texte(dossier)
            self.txt_dossier.TextWrapping = SW.TextWrapping.Wrap
            dp.Children.Add(self.txt_dossier)
            grp.Child = dp
            pile.Children.Add(grp)

            # --- Configuration ---
            pile.Children.Add(str_ui.section_hdr(u"Configuration d'export"))
            grp_cfg = str_ui.group_box()
            sp_cfg = StackPanel()
            grp_cfg.Child = sp_cfg

            items_setup = [(u"Options manuelles (ci-dessous)", u"")]
            for nom, _cfg in self._setups:
                items_setup.append((nom, nom))
            infobulle = (u"Un setup est prioritaire sur les options manuelles : "
                         u"il reproduit l'export du panneau Revit.\n"
                         u"La configuration en session correspond aux reglages "
                         u"de ton dernier export IFC manuel sur ce modele.\n\n"
                         u"Sources lues :\n  " +
                         u"\n  ".join(self._diag_setups))
            self.cmb_setup = str_ui.combo(items_setup, largeur=250,
                                          infobulle=infobulle)
            self.cmb_setup.SelectionChanged += self._maj_etat_setup
            sp_cfg.Children.Add(str_ui.ligne_champ(u"Setup du modele :",
                                                   self.cmb_setup, 120))
            # Toujours afficher combien de setups ont ete lus : une liste
            # incomplete sans explication est pire qu'une liste vide.
            manque_modele = [l for l in self._diag_setups
                             if l.startswith(u"Aucun setup enregistre")]
            if self._setups and manque_modele:
                resume_setups = (u"{0} setup(s) lu(s), mais AUCUN du modele - "
                                 u"voir l'infobulle".format(len(self._setups)))
                teinte = "avertissement"
            elif self._setups:
                resume_setups = u"{0} setup(s) lu(s) - detail dans l'infobulle".format(
                    len(self._setups))
                teinte = "texte_gris"
            else:
                self.cmb_setup.IsEnabled = False
                resume_setups = u"Aucun setup lisible - detail dans l'infobulle"
                teinte = "avertissement"
            libelle_setups = str_ui.texte(resume_setups, taille=10,
                                          brush=str_ui.couleur(teinte))
            libelle_setups.ToolTip = infobulle
            sp_cfg.Children.Add(libelle_setups)
            if r["setup_modele"]:
                str_ui.selectionner_valeur(self.cmb_setup, r["setup_modele"])
            pile.Children.Add(grp_cfg)

            # --- Format ---
            pile.Children.Add(str_ui.section_hdr(u"Format"))
            grp_fmt = str_ui.group_box()
            sp_fmt = StackPanel()
            grp_fmt.Child = sp_fmt
            self._groupes_manuels.append(grp_fmt)

            self.cmb_version = str_ui.combo(
                [(lib, nom) for nom, lib in str_ifc.versions_disponibles()],
                largeur=250)
            str_ui.selectionner_valeur(self.cmb_version, r["version"])
            sp_fmt.Children.Add(str_ui.ligne_champ(u"Version IFC :",
                                                   self.cmb_version, 120))

            self.cmb_type = str_ui.combo(
                [(lib, nom) for nom, lib, _ext in str_ifc.TYPES_FICHIER],
                largeur=250)
            str_ui.selectionner_valeur(self.cmb_type, r["type_fichier"])
            sp_fmt.Children.Add(str_ui.ligne_champ(u"Type de fichier :",
                                                   self.cmb_type, 120))

            self.txt_prefixe = str_ui.zone_texte(largeur=250,
                                                 valeur=r["prefixe"])
            sp_fmt.Children.Add(str_ui.ligne_champ(u"Prefixe fichier :",
                                                   self.txt_prefixe, 120))
            pile.Children.Add(grp_fmt)

            # --- Perimetre ---
            pile.Children.Add(str_ui.section_hdr(u"Perimetre"))
            grp_per = str_ui.group_box()
            sp_per = StackPanel()
            grp_per.Child = sp_per

            # Le filtre de vue est applique par l'outil lui-meme : il reste
            # actif meme quand un setup du modele pilote le reste des options.
            self.chk_vue_seule = str_ui.checkbox(
                u"Limiter aux elements visibles dans la vue", r["vue_seule"],
                u"Decoche = tout le modele est exporte dans chaque fichier.")
            sp_per.Children.Add(self.chk_vue_seule)
            sp_per.Children.Add(str_ui.texte(
                u"Tout ce qui est masque dans la vue (categories, filtres, "
                u"boite de coupe) est absent de l'IFC.",
                taille=10, brush=str_ui.couleur("texte_gris")))

            sp_per_manuel = StackPanel()
            sp_per.Children.Add(sp_per_manuel)
            self._groupes_manuels.append(sp_per_manuel)

            self.chk_geometrie_vue = str_ui.checkbox(
                u"Utiliser la geometrie de la vue (boite de coupe)",
                r["geometrie_vue"],
                u"Coupe la geometrie a la boite de coupe au lieu d'exclure "
                u"seulement les elements hors boite.")
            sp_per_manuel.Children.Add(self.chk_geometrie_vue)

            items_phase = [(u"(toutes / defaut du modele)", -1)]
            for pid, pnom in self._phases:
                items_phase.append((pnom, pid))
            # Liste conservee cote Python : l'id de phase est relu par index et
            # non depuis le Tag WPF, pour ne dependre d'aucune conversion .NET.
            self._items_phase = items_phase
            self.cmb_phase = str_ui.combo(items_phase, largeur=230)
            if not str_ui.selectionner_valeur(self.cmb_phase, r["phase_id"]):
                self.cmb_phase.SelectedIndex = 0
            sp_per_manuel.Children.Add(str_ui.ligne_champ(u"Phase exportee :",
                                                          self.cmb_phase, 130))
            pile.Children.Add(grp_per)

            # --- Contenu ---
            pile.Children.Add(str_ui.section_hdr(u"Contenu"))
            grp_con = str_ui.group_box()
            sp_con = StackPanel()
            grp_con.Child = sp_con
            self.chk_acier = str_ui.checkbox(
                u"Inclure les elements acier (Steel)", r["acier"],
                u"Assemblages, platines et boulons de la categorie acier. "
                u"Decoche, ils sont absents de l'IFC.")
            self.chk_quantites = str_ui.checkbox(
                u"Exporter les quantites de base (BaseQuantities)",
                r["quantites"])
            self.chk_split = str_ui.checkbox(
                u"Decouper murs et poteaux par niveau", r["split_murs"])
            self.chk_parts = str_ui.checkbox(
                u"Exporter les Parts comme elements de construction",
                r["parts"])
            self.chk_armatures = str_ui.checkbox(
                u"Armatures : une entite IFC par barre", r["armatures_barres"],
                u"Sinon un jeu d'armatures uniforme sort en une seule entite.")
            self.chk_hote = str_ui.checkbox(
                u"Exporter l'hote et ses sous-elements en une entite",
                r["hote_entite_unique"])
            self.chk_2d = str_ui.checkbox(u"Exporter les elements 2D",
                                          r["elements_2d"])
            for cb in [self.chk_acier, self.chk_quantites, self.chk_split,
                       self.chk_parts, self.chk_armatures, self.chk_hote,
                       self.chk_2d]:
                sp_con.Children.Add(cb)

            self.cmb_espaces = str_ui.combo(
                [(u"Aucune", 0), (u"Niveau 1", 1), (u"Niveau 2", 2)],
                largeur=140)
            str_ui.selectionner_valeur(self.cmb_espaces, int(r["espaces"]))
            sp_con.Children.Add(str_ui.ligne_champ(u"Limites d'espaces :",
                                                   self.cmb_espaces, 130))
            self.chk_pieces = str_ui.checkbox(
                u"Exporter les pieces contenues dans la vue", r["pieces_vue"])
            sp_con.Children.Add(self.chk_pieces)
            pile.Children.Add(grp_con)
            self._groupes_manuels.append(grp_con)

            # --- Proprietes ---
            pile.Children.Add(str_ui.section_hdr(u"Jeux de proprietes"))
            grp_pset = str_ui.group_box()
            sp_pset = StackPanel()
            grp_pset.Child = sp_pset
            self.chk_psets_ifc = str_ui.checkbox(
                u"Jeux de proprietes IFC communs", r["psets_ifc"])
            self.chk_psets_revit = str_ui.checkbox(
                u"Parametres Revit internes", r["psets_revit"],
                u"Fait sortir les parametres du projet, dont les #STR_*.")
            self.chk_psets_mat = str_ui.checkbox(
                u"Proprietes des materiaux", r["psets_materiaux"])
            self.chk_psets_nom = str_ui.checkbox(
                u"Nomenclatures comme jeux de proprietes", r["psets_nomenc"])
            self.chk_nomenc_spec = str_ui.checkbox(
                u"Seulement celles avec IFC, Pset ou Common dans le titre",
                r["nomenc_specifiques"],
                u"Sans ce filtre, toutes les nomenclatures du projet partent "
                u"dans l'IFC.")
            self.chk_nomenc_spec.Margin = Thickness(18, 2, 0, 2)
            self.chk_psets_user = str_ui.checkbox(
                u"Jeux de proprietes personnalises (fichier)", r["psets_user"])
            for cb in [self.chk_psets_ifc, self.chk_psets_revit,
                       self.chk_psets_mat, self.chk_psets_nom,
                       self.chk_nomenc_spec, self.chk_psets_user]:
                sp_pset.Children.Add(cb)

            dp_pset = DockPanel()
            dp_pset.LastChildFill = True
            dp_pset.Margin = Thickness(0, 4, 0, 0)
            btn_pset = str_ui.small_btn(u"...", self._on_choisir_psets)
            btn_pset.Margin = Thickness(6, 0, 0, 0)
            DockPanel.SetDock(btn_pset, SWC.Dock.Right)
            dp_pset.Children.Add(btn_pset)
            self.txt_psets = str_ui.zone_texte(largeur=300,
                                               valeur=r["psets_user_fichier"])
            dp_pset.Children.Add(self.txt_psets)
            sp_pset.Children.Add(dp_pset)
            pile.Children.Add(grp_pset)
            self._groupes_manuels.append(grp_pset)

            # --- Geometrie ---
            pile.Children.Add(str_ui.section_hdr(u"Geometrie et precision"))
            grp_geo = str_ui.group_box()
            sp_geo = StackPanel()
            grp_geo.Child = sp_geo
            self.chk_solides = str_ui.checkbox(
                u"Exporter des solides quand c'est possible", r["solides"],
                u"Sans cette option, les formes complexes sortent en maillage "
                u"triangule : c'est la principale perte de precision.")
            self.chk_swept = str_ui.checkbox(
                u"Autoriser les balayages avances (IFC4)", r["swept_avances"])
            self.chk_triangulation = str_ui.checkbox(
                u"Triangulation uniquement", r["triangulation"],
                u"Force le maillage. A ne cocher que si le destinataire "
                u"refuse les BREP.")
            self.chk_bbox = str_ui.checkbox(
                u"Exporter la boite englobante", r["bbox"])
            for cb in [self.chk_solides, self.chk_swept,
                       self.chk_triangulation, self.chk_bbox]:
                sp_geo.Children.Add(cb)
            self.cmb_lod = str_ui.combo(
                [(u"Extra faible (0.25)", 0.25), (u"Faible (0.50)", 0.50),
                 (u"Moyen (0.75)", 0.75), (u"Eleve (1.00)", 1.0)],
                largeur=170,
                infobulle=u"Finesse de la tesselation des formes courbes.")
            if not str_ui.selectionner_valeur(self.cmb_lod, float(r["lod"])):
                self.cmb_lod.SelectedIndex = 3
            sp_geo.Children.Add(str_ui.ligne_champ(u"Niveau de detail :",
                                                   self.cmb_lod, 130))
            pile.Children.Add(grp_geo)
            self._groupes_manuels.append(grp_geo)

            # --- Georeferencement ---
            pile.Children.Add(str_ui.section_hdr(u"Georeferencement"))
            grp_geo_ref = str_ui.group_box()
            sp_ref = StackPanel()
            grp_geo_ref.Child = sp_ref
            self.cmb_placement = str_ui.combo(
                [(lib, nom) for nom, lib in str_ifc.placements_disponibles()],
                largeur=250,
                infobulle=u"Base de coordonnees du fichier IFC. Coordonnees "
                          u"partagees = systeme de coordonnees partage du "
                          u"projet (LV95 / MN95 si le projet est cale).")
            if not str_ui.selectionner_valeur(self.cmb_placement, r["placement"]):
                self.cmb_placement.SelectedIndex = 0
            sp_ref.Children.Add(str_ui.ligne_champ(u"Base du site :",
                                                   self.cmb_placement, 120))
            self.chk_altitude = str_ui.checkbox(
                u"Inclure l'altitude du site", r["altitude_site"])
            sp_ref.Children.Add(self.chk_altitude)
            pile.Children.Add(grp_geo_ref)
            self._groupes_manuels.append(grp_geo_ref)

            # --- Divers ---
            pile.Children.Add(str_ui.section_hdr(u"Divers"))
            grp_div = str_ui.group_box()
            sp_div = StackPanel()
            grp_div.Child = sp_div
            self.chk_guid = str_ui.checkbox(
                u"Memoriser les GUID IFC dans le modele", r["guid_ifc"],
                u"Stabilise les identifiants entre deux exports (utile pour "
                u"comparer des versions), mais modifie le modele.")
            self.chk_nom_type = str_ui.checkbox(
                u"Utiliser le nom de type seul pour IfcType", r["nom_type_seul"])
            self.chk_nom_visible = str_ui.checkbox(
                u"Utiliser le nom Revit visible comme nom d'entite",
                r["nom_visible"])
            self.chk_nom_famille = str_ui.checkbox(
                u"Utiliser la famille et le nom du type en reference",
                r["nom_famille_type"])
            for cb in [self.chk_guid, self.chk_nom_type, self.chk_nom_visible,
                       self.chk_nom_famille]:
                sp_div.Children.Add(cb)
            pile.Children.Add(grp_div)
            self._groupes_manuels.append(grp_div)

            # --- Outil (jamais pilote par un setup du modele) ---
            pile.Children.Add(str_ui.section_hdr(u"Outil"))
            grp_outil = str_ui.group_box()
            sp_outil = StackPanel()
            grp_outil.Child = sp_outil
            self.chk_journal = str_ui.checkbox(
                u"Ecrire un journal .log a cote des IFC", r["journal"],
                u"Consigne les options transmises et la raison de chaque echec.")
            sp_outil.Children.Add(self.chk_journal)
            pile.Children.Add(grp_outil)

            return defileur

        # ------------------------------------------------------------------
        # Etat / compteurs
        # ------------------------------------------------------------------
        def _maj_etat_setup(self, sender, e):
            """
            Un setup du modele est autoritaire : il desactive les options
            manuelles qu'il pilote. Le filtre de vue et le journal vivent hors
            de ces groupes, car ils restent geres par l'outil (dans WPF,
            IsEnabled d'un enfant ne peut pas contredire un parent desactive).
            """
            actif = bool(str_ui.valeur_combo(self.cmb_setup, u""))
            for groupe in self._groupes_manuels:
                groupe.IsEnabled = not actif

        def _preselectionner(self, noms):
            cibles = set([n.lower() for n in noms])
            for item in self.lst_vues.Items:
                if item.Tag.Name.lower() in cibles:
                    item.IsSelected = True
            self._maj_compteurs()

        def _visible(self, item):
            return item.Visibility == SW.Visibility.Visible

        def _maj_compteurs(self):
            visibles = 0
            masquees_selection = 0
            for item in self.lst_vues.Items:
                if self._visible(item):
                    visibles += 1
                elif item.IsSelected:
                    masquees_selection += 1
            self.lbl_compte.Text = u"{0} vue(s) affichee(s)".format(visibles)

            n = len(self._ids_selectionnes)
            txt = u"✓ {0} selectionnee(s)".format(n)
            if masquees_selection:
                txt += u" dont {0} masquee(s)".format(masquees_selection)
            self.lbl_selection.Text = txt
            self.lbl_selection.Foreground = (str_ui.couleur("ok") if n
                                             else str_ui.couleur("erreur"))

        # ------------------------------------------------------------------
        # Handlers
        # ------------------------------------------------------------------
        def _on_item_selectionne(self, sender, e):
            self._ids_selectionnes.add(str_ifc.id_value(sender.Tag.Id))
            self._maj_compteurs()

        def _on_item_deselectionne(self, sender, e):
            self._ids_selectionnes.discard(str_ifc.id_value(sender.Tag.Id))
            self._maj_compteurs()

        def _on_filtre(self, sender, e):
            requete = self.txt_filtre.Text.strip().lower()
            for item in self.lst_vues.Items:
                visible = (not requete) or (requete in item.Tag.Name.lower())
                item.Visibility = (SW.Visibility.Visible if visible
                                   else SW.Visibility.Collapsed)
            self._maj_compteurs()

        def _on_filtre_vide(self, sender, e):
            self.txt_filtre.Text = u""

        def _on_tout(self, sender, e):
            for item in self.lst_vues.Items:
                if self._visible(item):
                    item.IsSelected = True
            self._maj_compteurs()

        def _on_rien(self, sender, e):
            for item in self.lst_vues.Items:
                if self._visible(item):
                    item.IsSelected = False
            self._maj_compteurs()

        def _on_parcourir(self, sender, e):
            dlg = FolderBrowserDialog()
            dlg.SelectedPath = self.txt_dossier.Text
            dlg.Description = u"Dossier de destination des fichiers IFC"
            if dlg.ShowDialog() == DialogResult.OK:
                self.txt_dossier.Text = dlg.SelectedPath

        def _on_choisir_psets(self, sender, e):
            dlg = OpenFileDialog()
            dlg.Filter = u"Fichier de jeux de proprietes (*.txt)|*.txt|Tous (*.*)|*.*"
            dlg.Title = u"Fichier de jeux de proprietes personnalises"
            if dlg.ShowDialog() == DialogResult.OK:
                self.txt_psets.Text = dlg.FileName
                self.chk_psets_user.IsChecked = True

        def _on_annuler(self, sender, e):
            self._resultat = None
            self.Close()

        def _avertir(self, message, image=None):
            MessageBox.Show(message, TOOL_NAME, MessageBoxButton.OK,
                            image or MessageBoxImage.Warning)

        def _on_exporter(self, sender, e):
            carte = dict([(str_ifc.id_value(v.Id), v) for v in self._vues])
            vues = [carte[i] for i in self._ids_selectionnes if i in carte]
            if not vues:
                self._avertir(u"Aucune vue selectionnee.\nSelectionnez au "
                              u"moins une vue 3D avant d'exporter.")
                return
            vues.sort(key=lambda v: v.Name.lower())

            dossier = self.txt_dossier.Text.strip()
            if not os.path.isdir(dossier):
                self._avertir(u"Le dossier de sortie n'existe pas :\n{0}"
                              .format(dossier), MessageBoxImage.Error)
                return

            reglages = self._lire_reglages()

            if reglages["psets_user"]:
                chemin = reglages["psets_user_fichier"]
                if not (chemin and os.path.isfile(chemin)):
                    self._avertir(u"Jeux de proprietes personnalises coches, "
                                  u"mais le fichier est introuvable :\n{0}"
                                  .format(chemin or u"(vide)"))
                    return

            # Ecrasements : prevenir avant, pas apres.
            extension = str_ifc.extension_fichier(reglages["type_fichier"])
            existants = []
            for _v, radical in noms_cibles(vues, reglages["prefixe"]):
                chemin = os.path.join(dossier, radical + extension)
                if os.path.isfile(chemin):
                    existants.append(os.path.basename(chemin))
            if existants:
                apercu = u"\n".join([u"  - " + n for n in existants[:8]])
                if len(existants) > 8:
                    apercu += u"\n  - ... et {0} autre(s)".format(
                        len(existants) - 8)
                reponse = MessageBox.Show(
                    u"{0} fichier(s) seront ecrases :\n\n{1}\n\nContinuer ?"
                    .format(len(existants), apercu),
                    TOOL_NAME, MessageBoxButton.YesNo,
                    MessageBoxImage.Warning)
                if reponse != MessageBoxResult.Yes:
                    return

            self._resultat = {
                "dossier": dossier,
                "reglages": reglages,
                "vues": vues,
                "setup": self._setups_par_nom.get(reglages["setup_modele"]),
                "diagnostic_setups": self._diag_setups,
                "config_session": self._config_session,
            }
            self.Close()

        def _lire_reglages(self):
            r = dict(self._reglages)
            r["setup_modele"] = str_ui.valeur_combo(self.cmb_setup, u"") or u""
            r["version"] = str_ui.valeur_combo(self.cmb_version, r["version"])
            r["type_fichier"] = str_ui.valeur_combo(self.cmb_type,
                                                    r["type_fichier"])
            r["prefixe"] = self.txt_prefixe.Text
            r["vue_seule"] = bool(self.chk_vue_seule.IsChecked)
            r["geometrie_vue"] = bool(self.chk_geometrie_vue.IsChecked)
            index_phase = self.cmb_phase.SelectedIndex
            if 0 <= index_phase < len(self._items_phase):
                r["phase_id"] = int(self._items_phase[index_phase][1])
            else:
                r["phase_id"] = -1
            r["quantites"] = bool(self.chk_quantites.IsChecked)
            r["split_murs"] = bool(self.chk_split.IsChecked)
            r["espaces"] = int(str_ui.valeur_combo(self.cmb_espaces, 0))
            r["pieces_vue"] = bool(self.chk_pieces.IsChecked)
            r["acier"] = bool(self.chk_acier.IsChecked)
            r["parts"] = bool(self.chk_parts.IsChecked)
            r["elements_2d"] = bool(self.chk_2d.IsChecked)
            r["armatures_barres"] = bool(self.chk_armatures.IsChecked)
            r["hote_entite_unique"] = bool(self.chk_hote.IsChecked)
            r["psets_ifc"] = bool(self.chk_psets_ifc.IsChecked)
            r["psets_revit"] = bool(self.chk_psets_revit.IsChecked)
            r["psets_materiaux"] = bool(self.chk_psets_mat.IsChecked)
            r["psets_nomenc"] = bool(self.chk_psets_nom.IsChecked)
            r["nomenc_specifiques"] = bool(self.chk_nomenc_spec.IsChecked)
            r["psets_user"] = bool(self.chk_psets_user.IsChecked)
            r["psets_user_fichier"] = self.txt_psets.Text.strip()
            r["solides"] = bool(self.chk_solides.IsChecked)
            r["swept_avances"] = bool(self.chk_swept.IsChecked)
            r["triangulation"] = bool(self.chk_triangulation.IsChecked)
            r["bbox"] = bool(self.chk_bbox.IsChecked)
            r["lod"] = float(str_ui.valeur_combo(self.cmb_lod, 1.0))
            r["placement"] = str_ui.valeur_combo(self.cmb_placement,
                                                 r["placement"])
            r["altitude_site"] = bool(self.chk_altitude.IsChecked)
            r["guid_ifc"] = bool(self.chk_guid.IsChecked)
            r["nom_type_seul"] = bool(self.chk_nom_type.IsChecked)
            r["nom_visible"] = bool(self.chk_nom_visible.IsChecked)
            r["nom_famille_type"] = bool(self.chk_nom_famille.IsChecked)
            r["journal"] = bool(self.chk_journal.IsChecked)
            return r

        @property
        def resultat(self):
            return self._resultat

    # ======================================================================
    # Journal
    # ======================================================================
    class Journal(object):
        """Trace texte de l'export, ecrite a cote des IFC."""

        def __init__(self, actif, dossier, prefixe):
            self.lignes = []
            self.chemin = None
            if not actif:
                return
            nom = u"{0}Export IFC {1}.log".format(
                prefixe or u"", time.strftime("%Y-%m-%d %H%M%S"))
            self.chemin = os.path.join(dossier, nom_fichier_sur(nom))

        def ecrire(self, ligne):
            self.lignes.append(ligne)
            print(ligne)

        def entete(self, reglages, vues, dossier, setup, diagnostic_setups):
            self.ecrire(u"=" * 70)
            self.ecrire(u"{0} v{1}".format(TOOL_NAME, SCRIPT_VERSION))
            self.ecrire(u"Date      : {0}".format(
                time.strftime("%Y-%m-%d %H:%M:%S")))
            self.ecrire(u"Modele    : {0}".format(doc.PathName or doc.Title))
            self.ecrire(u"Revit     : {0}".format(app.VersionNumber))
            self.ecrire(u"Dossier   : {0}".format(dossier))
            self.ecrire(u"Vues      : {0}".format(len(vues)))
            for ligne in (diagnostic_setups or []):
                self.ecrire(u"Setups   : {0}".format(ligne))
            # Si aucun setup du modele n'a pu etre lu, inventorier le stockage
            # extensible : cela dit s'ils sont bien dans le modele et sous quel
            # schema, plutot que de laisser le doute.
            if any(l.startswith(u"Aucun setup enregistre")
                   for l in (diagnostic_setups or [])):
                self.ecrire(u"")
                self.ecrire(u"--- Inventaire du stockage extensible IFC ---")
                for ligne in str_ifc.inventaire_schemas_ifc(doc):
                    self.ecrire(u"    " + ligne)
            if setup is not None:
                self.ecrire(u"Setup du modele : {0}".format(
                    reglages["setup_modele"]))
            else:
                self.ecrire(u"Options manuelles :")
                for clef in sorted(reglages.keys()):
                    self.ecrire(u"    {0:<22} {1}".format(clef,
                                                          reglages[clef]))
            self.ecrire(u"=" * 70)

        def configuration(self, etiquette, cfg):
            """
            Vide toutes les proprietes d'une configuration de l'exporteur.
            A comparer avec le bloc "Options transmises" ci-dessous : l'ecart
            entre les deux designe l'option qui manque a l'outil.
            """
            if cfg is None:
                return
            self.ecrire(u"")
            self.ecrire(u"--- Configuration {0} : proprietes lues par "
                        u"reflexion ---".format(etiquette))
            for nom, valeur in str_ifc.decrire_configuration(cfg):
                self.ecrire(u"    {0:<40} {1}".format(nom, valeur))

        def options_transmises(self, reglages, view_id):
            self.ecrire(u"    Options transmises a l'exporteur :")
            for clef, valeur in str_ifc.options_transmises(reglages, view_id):
                self.ecrire(u"        {0} = {1}".format(clef, valeur))

        def sauver(self):
            if not self.chemin:
                return None
            try:
                with io.open(self.chemin, "w", encoding="utf-8") as f:
                    f.write(u"\n".join(self.lignes) + u"\n")
                return self.chemin
            except Exception:
                return None

    # ======================================================================
    # Export
    # ======================================================================
    class CapteurEchecsRevit(object):
        """
        Capte les echecs Revit pendant l'export, au niveau application.

        Pourquoi pas seulement le prehandler de la transaction : avec
        SetClearAfterRollback(True), Revit purge les echecs au moment du
        RollBack SANS appeler le prehandler. Resultat, un export qui echoue ne
        laissait aucune trace du motif - exactement ce qui s'est produit sur la
        vue ZNH. L'evenement FailuresProcessing, lui, se declenche pendant la
        transaction : c'est la seule facon de recuperer le texte de Revit.

        Les avertissements sont effaces, une erreur demande le rollback : pas de
        boite modale au milieu d'un lot.
        """

        MAX_MESSAGES = 50

        def __init__(self):
            self.messages = []
            self._delegue = None

        @property
        def branche(self):
            return self._delegue is not None

        def brancher(self):
            if FailuresProcessingEventArgs is None:
                self.messages.append(u"Capture des echecs Revit indisponible : "
                                     u"FailuresProcessingEventArgs absent.")
                return
            try:
                self._delegue = System.EventHandler[FailuresProcessingEventArgs](
                    self._sur_echecs)
                app.FailuresProcessing += self._delegue
            except Exception as ex:
                self._delegue = None
                self.messages.append(
                    u"Capture des echecs Revit indisponible : {0}".format(ex))

        def debrancher(self):
            if self._delegue is None:
                return
            try:
                app.FailuresProcessing -= self._delegue
            except Exception:
                pass
            self._delegue = None

        def _sur_echecs(self, sender, args):
            try:
                accesseur = args.GetFailuresAccessor()
                erreur = False
                for msg in list(accesseur.GetFailureMessages()):
                    try:
                        severite = msg.GetSeverity()
                    except Exception:
                        severite = None
                    # GetDescriptionText construit une chaine : couteux, et un
                    # export peut poster des milliers d'avertissements. Passe le
                    # plafond, on continue a les effacer (sans quoi Revit ouvre
                    # une boite modale) mais on cesse de les decrire.
                    if len(self.messages) < self.MAX_MESSAGES:
                        try:
                            texte = msg.GetDescriptionText()
                        except Exception:
                            texte = u"(message illisible)"
                        self.messages.append(u"{0} : {1}".format(severite,
                                                                 texte))
                        if len(self.messages) == self.MAX_MESSAGES:
                            self.messages.append(
                                u"... plafond de {0} messages atteint, les "
                                u"suivants ne sont plus detailles.".format(
                                    self.MAX_MESSAGES))
                    if severite == FailureSeverity.Warning:
                        try:
                            accesseur.DeleteWarning(msg)
                        except Exception:
                            pass
                    else:
                        erreur = True
                args.SetProcessingResult(
                    FailureProcessingResult.ProceedWithRollBack if erreur
                    else FailureProcessingResult.Continue)
            except Exception:
                pass

    def pistes_echec(reglages):
        """
        Suggestions concretes quand aucun fichier n'est produit.

        La duree n'est PAS un indice : un echec en 00:00 ne dit rien sur la
        cause, l'exporteur renonce des qu'il rencontre une erreur bloquante.
        """
        pistes = []
        if not reglages["setup_modele"]:
            pistes.append(u"selectionnez un setup du modele dans la liste "
                          u"(il transmet exactement ce que transmet le panneau "
                          u"Revit, options comprises que l'outil n'expose pas)")
        if reglages["geometrie_vue"]:
            pistes.append(u"decochez 'Utiliser la geometrie de la vue'")
        if reglages["psets_nomenc"]:
            pistes.append(u"decochez 'Nomenclatures comme jeux de proprietes'")
        if not pistes:
            return u""
        return u" | Pistes : " + u" ; puis ".join(pistes)

    def activer_vue(vue):
        """
        Rend la vue active dans Revit. Retourne (succes, motif).

        Obligatoire pour UseActiveViewGeometry : l'exporteur lit alors la
        geometrie de la vue ACTIVE de Revit, pas celle de FilterViewId. Avec
        l'option cochee sur une vue non active, l'export echoue sans produire de
        fichier. A ne jamais appeler avec une transaction ouverte.
        """
        try:
            uidoc = __revit__.ActiveUIDocument
            if str_ifc.id_value(uidoc.ActiveView.Id) == str_ifc.id_value(vue.Id):
                return True, u""
            uidoc.ActiveView = vue
            return True, u""
        except Exception as ex:
            return False, u"{0}".format(ex)

    class GestionEchecsExport(IFailuresPreprocessor):
        """
        Evite que Revit ouvre une boite de dialogue modale au milieu d'un lot.

        Sans ce prehandler, un echec d'export ("une erreur irrecuperable s'est
        produite lors de l'exportation") affiche une boite bloquante : sur huit
        vues, l'export s'arrete et attend un clic. Ici les avertissements sont
        effaces, et une erreur fait annuler la transaction sans dialogue : la
        vue est comptee en echec, le lot continue avec la suivante.

        Les textes Revit sont conserves et recopies dans le journal : c'est la
        seule source qui dit POURQUOI l'exporteur a renonce.
        """

        def __init__(self):
            self.messages = []

        def PreprocessFailures(self, accesseur):
            erreur = False
            try:
                echecs = list(accesseur.GetFailureMessages())
            except Exception:
                return FailureProcessingResult.Continue
            for msg in echecs:
                try:
                    texte = msg.GetDescriptionText()
                except Exception:
                    texte = u"(message illisible)"
                try:
                    severite = msg.GetSeverity()
                except Exception:
                    severite = None
                self.messages.append(u"{0} : {1}".format(severite, texte))
                if severite == FailureSeverity.Warning:
                    try:
                        accesseur.DeleteWarning(msg)
                    except Exception:
                        pass
                else:
                    erreur = True
            if erreur:
                return FailureProcessingResult.ProceedWithRollBack
            return FailureProcessingResult.Continue

    def exporter_une_vue(dossier, radical, opts, nom_vue, conserver_guid):
        """
        Lance doc.Export dans une transaction. Retourne les messages Revit
        remontes pendant l'export (liste vide si tout s'est bien passe).

        L'exporteur IFC modifie le document pendant l'export : sans transaction
        ouverte, Revit 2024 refuse avec "Modifying is forbidden because the
        document has no open transaction". La transaction est donc obligatoire,
        et non superflue comme je l'avais suppose.

        Elle est annulee par defaut, pour laisser le modele intact. Elle n'est
        validee que si l'utilisateur a demande la memorisation des GUID IFC :
        c'est le seul cas ou une modification du modele est voulue (un RollBack
        annulerait justement les GUID que l'exporteur vient d'ecrire).
        """
        t = Transaction(doc, u"STR - Export IFC : {0}".format(nom_vue))
        t.Start()

        gestion = GestionEchecsExport()
        try:
            # Seul le prehandler est installe.
            #
            # NE PAS ajouter SetForcedModalHandling(False) ni
            # SetClearAfterRollback(True) : ces deux reglages font annuler la
            # transaction en silence sans appeler le prehandler. C'est ce qui a
            # masque pendant trois versions l'erreur reelle de l'exporteur et
            # fait croire, a tort, a un echec instantane de configuration.
            options_echec = t.GetFailureHandlingOptions()
            options_echec = options_echec.SetFailuresPreprocessor(gestion)
            t.SetFailureHandlingOptions(options_echec)
        except Exception as ex:
            gestion.messages.append(
                u"Gestion des echecs non installee : {0}".format(ex))

        retour = None
        try:
            retour = doc.Export(dossier, radical, opts)
        finally:
            if t.GetStatus() == TransactionStatus.Started:
                if conserver_guid:
                    t.Commit()
                else:
                    t.RollBack()
            t.Dispose()
        return gestion.messages, retour

    def executer_export(demande):
        """
        Exporte les vues selectionnees.

        Retourne (reussis, echecs, annule, journal, duree_totale).
        """
        dossier = demande["dossier"]
        reglages = demande["reglages"]
        vues = demande["vues"]
        setup = demande["setup"]
        extension = str_ifc.extension_fichier(reglages["type_fichier"])

        journal = Journal(reglages["journal"], dossier, reglages["prefixe"])
        journal.entete(reglages, vues, dossier, setup,
                       demande.get("diagnostic_setups"))
        # La configuration en session est celle du dernier export manuel : c'est
        # la reference a comparer avec les options transmises par l'outil.
        journal.configuration(u"en session", demande.get("config_session"))
        if setup is not None:
            journal.configuration(
                u"selectionnee ({0})".format(reglages["setup_modele"]), setup)

        reussis = []
        echecs = []
        annule = False

        cibles = noms_cibles(vues, reglages["prefixe"])
        capteur = CapteurEchecsRevit()
        capteur.brancher()
        # Les messages produits par le branchement sont anterieurs a la premiere
        # vue : sans cette purge, un capteur qui n'arrive pas a s'abonner reste
        # invisible et l'on croit a tort qu'aucun echec n'a ete remonte.
        for ligne in capteur.messages:
            journal.ecrire(u"[AVERT] " + ligne)
        capteur.messages = []
        journal.ecrire(u"Capture des echecs Revit : {0}".format(
            u"active" if capteur.branche else u"INACTIVE"))

        vue_initiale = None
        try:
            vue_initiale = __revit__.ActiveUIDocument.ActiveView
        except Exception:
            vue_initiale = None

        prog = str_progress_sta.ProgressionSTA(len(cibles), TOOL_NAME,
                                               SCRIPT_VERSION)
        if not prog.disponible and prog.erreur_demarrage:
            journal.ecrire(u"[AVERT] Fenetre de progression indisponible : {0}"
                           .format(prog.erreur_demarrage))

        suivi = str_progress_revit.SuiviProgressionRevit(prog, app)
        suivi.brancher()
        for ligne in suivi.messages:
            journal.ecrire(u"[AVERT] " + ligne)
        journal.ecrire(u"Progression detaillee de l'export : {0}".format(
            u"active" if suivi.branche else u"INACTIVE"))

        try:
            for index, (vue, radical) in enumerate(cibles, 1):
                if prog.annulation_demandee:
                    annule = True
                    journal.ecrire(u"")
                    journal.ecrire(u"[ANNULE] Interrompu par l'utilisateur "
                                   u"apres {0} vue(s).".format(index - 1))
                    break

                view_id = str_ifc.id_value(vue.Id)
                chemin_attendu = os.path.join(dossier, radical + extension)
                avant = etat_fichier(chemin_attendu)

                journal.ecrire(u"")
                journal.ecrire(u"[VUE {0}/{1}] {2}".format(index, len(cibles),
                                                           vue.Name))
                journal.ecrire(u"    Fichier : {0}{1}".format(radical,
                                                              extension))
                journal.ecrire(u"    Boite de coupe active : {0}".format(
                    u"oui" if boite_de_coupe_active(vue) else u"non"))

                # Reglages propres a cette vue : l'option de geometrie de vue
                # n'est transmise que si la vue a pu devenir active.
                reglages_vue = dict(reglages)
                if reglages_vue["geometrie_vue"]:
                    active, motif = activer_vue(vue)
                    if active:
                        journal.ecrire(u"    Vue activee dans Revit "
                                       u"(geometrie de la vue demandee).")
                    else:
                        reglages_vue["geometrie_vue"] = False
                        journal.ecrire(
                            u"    [AVERT] Vue non activable, option "
                            u"'geometrie de la vue' desactivee pour cette "
                            u"vue : {0}".format(motif))

                prog.debut_element(vue.Name, index - 1)
                depart = time.time()
                depart_messages = len(capteur.messages)
                try:
                    anomalies = []
                    if setup is not None:
                        opts = str_ifc.options_depuis_setup(
                            setup, view_id, reglages_vue["vue_seule"],
                            anomalies)
                        if opts is None:
                            raise Exception(
                                u"Le setup '{0}' n'a pas pu etre applique : "
                                u"{1}".format(reglages_vue["setup_modele"],
                                              u" / ".join(anomalies)))
                    else:
                        opts, cfg_utilisee = str_ifc.construire_options(
                            reglages_vue, view_id, anomalies)
                        if cfg_utilisee is not None:
                            # Voie fiable : objet de configuration + UpdateOptions.
                            # Le vidage n'a d'interet qu'une fois, les reglages
                            # ne variant pas d'une vue a l'autre.
                            if index == 1:
                                journal.configuration(
                                    u"construite depuis les options manuelles",
                                    cfg_utilisee)
                        else:
                            journal.ecrire(u"    [AVERT] Repli sur la table "
                                           u"d'options nommees.")
                            journal.options_transmises(reglages_vue, view_id)
                    for ligne in anomalies:
                        journal.ecrire(u"    [AVERT] " + ligne)

                    messages_revit, retour_export = exporter_une_vue(
                        dossier, radical, opts, vue.Name,
                        reglages_vue["guid_ifc"])
                    messages_revit = (list(messages_revit)
                                      + capteur.messages[depart_messages:])
                    journal.ecrire(u"    doc.Export a retourne : {0}".format(
                        retour_export))
                    for ligne in messages_revit:
                        journal.ecrire(u"    [REVIT] " + ligne)

                    chemin = trouver_sortie(dossier, radical, extension)
                    existe, taille, mtime = etat_fichier(chemin)
                    duree = time.time() - depart

                    if not existe:
                        raise Exception(
                            u"Aucun fichier produit (attendu : {0}, "
                            u"doc.Export a retourne {1}){2}{3}"
                            .format(os.path.basename(chemin_attendu),
                                    retour_export,
                                    u" - " + messages_revit[0]
                                    if messages_revit else u"",
                                    pistes_echec(reglages_vue)))
                    if taille == 0:
                        raise Exception(u"Fichier vide (0 octet)")
                    if (avant[0] and taille == avant[1]
                            and mtime <= avant[2]):
                        raise Exception(u"Fichier non reecrit : le resultat "
                                        u"est l'ancien export")

                    note = u""
                    if taille < SEUIL_SUSPECT_OCTETS:
                        note = (u"fichier tres petit ({0}) - vue vide ou "
                                u"boite de coupe trop restrictive ?".format(
                                    str_ui.fmt_taille(taille)))
                        journal.ecrire(u"    [AVERT] " + note)

                    reussis.append({
                        "vue": vue.Name,
                        "chemin": chemin,
                        "taille": taille,
                        "duree": duree,
                        "note": note,
                    })
                    journal.ecrire(u"    [OK] {0}  -  {1}".format(
                        str_ui.fmt_duree(duree), str_ui.fmt_taille(taille)))

                except Exception as ex:
                    motif = u"{0}".format(ex)
                    echecs.append({"vue": vue.Name, "motif": motif})
                    journal.ecrire(u"    [ECHEC] " + motif)
                    for ligne in traceback.format_exc().splitlines():
                        journal.lignes.append(u"        " + ligne)

                prog.fin_element(index)
        finally:
            duree_totale = prog.duree_totale
            suivi.debrancher()
            prog.fermer()
            capteur.debrancher()
            # Rendre la main sur la vue d'origine : l'export a pu en activer
            # d'autres pour honorer l'option de geometrie de vue.
            if vue_initiale is not None:
                try:
                    uidoc_final = __revit__.ActiveUIDocument
                    if (str_ifc.id_value(uidoc_final.ActiveView.Id)
                            != str_ifc.id_value(vue_initiale.Id)):
                        uidoc_final.ActiveView = vue_initiale
                except Exception as ex:
                    journal.ecrire(u"[AVERT] Vue d'origine non restauree : "
                                   u"{0}".format(ex))

        journal.ecrire(u"")
        journal.ecrire(u"=" * 70)
        journal.ecrire(u"RESUME : {0} reussi(s) / {1} echec(s){2}  -  {3}"
                       .format(len(reussis), len(echecs),
                               u"  [ANNULE]" if annule else u"",
                               str_ui.fmt_duree(duree_totale)))
        journal.ecrire(u"=" * 70)
        journal.sauver()
        return reussis, echecs, annule, journal, duree_totale

    # ======================================================================
    # Fenetre de resume
    # ======================================================================
    def afficher_resume(dossier, reussis, echecs, annule, journal, duree):
        win = Window()
        win.Title = TOOL_NAME + u" - Resume"
        win.Width = 640
        win.Height = 470
        win.MinWidth = 520
        win.MinHeight = 320
        win.ResizeMode = SW.ResizeMode.CanResizeWithGrip
        win.WindowStartupLocation = SW.WindowStartupLocation.CenterScreen
        win.Background = str_ui.couleur("fond")

        racine = Grid()
        for h in ["Auto", "*", "Auto"]:
            racine.RowDefinitions.Add(str_ui.rd(h))
        win.Content = racine

        if echecs or annule:
            icone, teinte = u"⚠", "avertissement"
        else:
            icone, teinte = u"✔", "ok"

        entete = StackPanel()
        entete.Margin = Thickness(20, 16, 20, 8)
        Grid.SetRow(entete, 0)
        racine.Children.Add(entete)
        entete.Children.Add(str_ui.texte(
            u"{0}  {1} fichier(s) exporte(s)  -  {2}".format(
                icone, len(reussis), str_ui.fmt_duree(duree)),
            taille=13, gras=True, brush=str_ui.couleur(teinte),
            marge=Thickness(0, 0, 0, 6)))
        if annule:
            entete.Children.Add(str_ui.texte(
                u"Export interrompu par l'utilisateur.",
                brush=str_ui.couleur("avertissement"),
                marge=Thickness(0, 0, 0, 4)))
        entete.Children.Add(str_ui.texte(
            u"Dossier : {0}".format(dossier),
            brush=str_ui.couleur("texte_gris"), marge=Thickness(0, 0, 0, 2)))
        if journal.chemin and os.path.isfile(journal.chemin):
            entete.Children.Add(str_ui.texte(
                u"Journal : {0}".format(os.path.basename(journal.chemin)),
                taille=10, brush=str_ui.couleur("texte_gris")))

        defileur = ScrollViewer()
        defileur.VerticalScrollBarVisibility = SWC.ScrollBarVisibility.Auto
        defileur.HorizontalScrollBarVisibility = SWC.ScrollBarVisibility.Disabled
        defileur.Margin = Thickness(20, 0, 20, 0)
        Grid.SetRow(defileur, 1)
        racine.Children.Add(defileur)
        liste = StackPanel()
        defileur.Content = liste

        if reussis:
            liste.Children.Add(str_ui.texte(
                u"Fichiers exportes :", gras=True,
                brush=str_ui.couleur("titre"), marge=Thickness(0, 4, 0, 4)))
            for item in reussis:
                ligne = Grid()
                ligne.Margin = Thickness(0, 0, 0, 3)
                for w in ["*", "Auto", "Auto"]:
                    ligne.ColumnDefinitions.Add(str_ui.cd(w))
                nom = str_ui.texte(u"  " + item["vue"], marge=Thickness(0))
                nom.TextTrimming = SW.TextTrimming.CharacterEllipsis
                Grid.SetColumn(nom, 0)
                ligne.Children.Add(nom)
                taille = str_ui.texte(
                    str_ui.fmt_taille(item["taille"]),
                    brush=(str_ui.couleur("avertissement") if item["note"]
                           else str_ui.couleur("texte_gris")),
                    marge=Thickness(10, 0, 10, 0))
                Grid.SetColumn(taille, 1)
                ligne.Children.Add(taille)
                duree_txt = str_ui.texte(str_ui.fmt_duree(item["duree"]),
                                         gras=True,
                                         brush=str_ui.couleur("ok"),
                                         marge=Thickness(0))
                Grid.SetColumn(duree_txt, 2)
                ligne.Children.Add(duree_txt)
                if item["note"]:
                    ligne.ToolTip = item["note"]
                liste.Children.Add(ligne)

        if echecs:
            liste.Children.Add(str_ui.texte(
                u"Echecs :", gras=True, brush=str_ui.couleur("erreur"),
                marge=Thickness(0, 12, 0, 4)))
            for item in echecs:
                bloc = StackPanel()
                bloc.Margin = Thickness(0, 0, 0, 6)
                bloc.Children.Add(str_ui.texte(
                    u"  ✘  " + item["vue"], gras=True,
                    brush=str_ui.couleur("erreur"), marge=Thickness(0)))
                motif = str_ui.texte(u"      " + item["motif"], taille=10,
                                     brush=str_ui.couleur("texte_gris"),
                                     marge=Thickness(0))
                motif.TextWrapping = SW.TextWrapping.Wrap
                bloc.Children.Add(motif)
                liste.Children.Add(bloc)

        footer, sp_btns, grid_f = str_ui.make_footer(SCRIPT_VERSION)
        Grid.SetRow(footer, 2)
        racine.Children.Add(footer)

        def ouvrir_dossier(sender, e):
            try:
                System.Diagnostics.Process.Start("explorer.exe",
                                                 u"\"{0}\"".format(dossier))
            except Exception:
                pass

        btn_dossier = str_ui.footer_btn(u"Ouvrir le dossier", "fermer", 140,
                                       ouvrir_dossier)
        btn_dossier.Margin = Thickness(0, 0, 6, 0)
        sp_btns.Children.Add(btn_dossier)
        sp_btns.Children.Add(str_ui.footer_btn(u"OK", "fermer", 80,
                                               lambda s, e: win.Close()))
        grid_f.Children.Add(sp_btns)
        win.ShowDialog()

    # ======================================================================
    # main
    # ======================================================================
    def main():
        vues = collecter_vues()
        if not vues:
            MessageBox.Show(u"Aucune vue 3D exportable dans ce projet.",
                            TOOL_NAME, MessageBoxButton.OK,
                            MessageBoxImage.Information)
            return

        reglages, dossier, vues_memorisees = charger_prefs()
        dialogue = DialogueExportIFC(vues, reglages, dossier, vues_memorisees)
        dialogue.ShowDialog()
        demande = dialogue.resultat
        if demande is None:
            print(u"[INFO] Export annule.")
            return

        enregistrer_prefs(demande["reglages"], demande["dossier"],
                          [v.Name for v in demande["vues"]])

        reussis, echecs, annule, journal, duree = executer_export(demande)
        afficher_resume(demande["dossier"], reussis, echecs, annule, journal,
                        duree)

    main()

except Exception as _ex:
    _show_fatal(u"{0} v{1} - Erreur".format(TOOL_NAME, SCRIPT_VERSION), _ex)
