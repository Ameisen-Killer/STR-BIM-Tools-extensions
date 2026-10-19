# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_export.py - Export XLSX du controle de conformite BEP FGH.
#
# Trois niveaux de lecture dans un seul classeur :
#   - « Synthese »  : contexte de la maquette, KPI, taux par categorie ;
#   - « Regles »    : une ligne par regle, son statut et son nombre d'ecarts ;
#   - un onglet par CATEGORIE : le detail des constats, element par element,
#     avec l'ElementId pour retrouver l'objet dans Revit.
#
# Ce module DEPEND de xlsxwriter (natif pyRevit), PAS de l'API Revit ni de WPF.
# IronPython 2.7 compatible.
# =============================================================================

import re

import xlsxwriter

import fgh_bep_regles as R

# Onglet Excel : 31 caracteres maximum, et [ ] : * ? / \ interdits.
_INTERDITS_ONGLET = re.compile(u"[\\[\\]:*?/\\\\]")

C_BLEU   = "#2F6496"
C_ENTETE = "#D0E4F7"
C_ALT    = "#E8F0FA"
C_VERT   = "#1a7c3e"
C_ORANGE = "#b85c00"
C_ROUGE  = "#cc0000"
C_GRIS   = "#888888"


def _nom_onglet(libelle, pris):
    """Nom d'onglet valide et unique."""
    base = _INTERDITS_ONGLET.sub(u"_", libelle or u"Détail")[:31].strip() or u"Détail"
    nom, i = base, 2
    while nom.lower() in pris:
        suffixe = u"_{0}".format(i)
        nom = base[:31 - len(suffixe)] + suffixe
        i += 1
    pris.add(nom.lower())
    return nom


def _formats(wb):
    return {
        "titre":  wb.add_format({"bold": True, "font_size": 14,
                                 "font_color": C_BLEU}),
        "hdr":    wb.add_format({"bold": True, "bg_color": C_BLEU,
                                 "font_color": "#FFFFFF", "border": 1,
                                 "align": "center", "valign": "vcenter",
                                 "text_wrap": True}),
        "sous":   wb.add_format({"bold": True, "bg_color": C_ENTETE, "border": 1}),
        "cell":   wb.add_format({"border": 1, "valign": "top", "text_wrap": True}),
        "alt":    wb.add_format({"border": 1, "bg_color": C_ALT,
                                 "valign": "top", "text_wrap": True}),
        "num":    wb.add_format({"border": 1, "align": "right"}),
        "num_alt": wb.add_format({"border": 1, "align": "right",
                                  "bg_color": C_ALT}),
        "pct":    wb.add_format({"border": 1, "align": "right",
                                 "num_format": "0.0 %"}),
        "ok":     wb.add_format({"border": 1, "font_color": C_VERT,
                                 "bold": True}),
        "ko":     wb.add_format({"border": 1, "font_color": C_ROUGE,
                                 "bold": True}),
        "na":     wb.add_format({"border": 1, "font_color": C_GRIS,
                                 "italic": True}),
        "label":  wb.add_format({"bold": True}),
        "note":   wb.add_format({"font_size": 9, "font_color": C_GRIS,
                                 "italic": True}),
    }


def _format_statut(fmt, statut):
    if statut == R.STATUT_CONFORME:
        return fmt["ok"]
    if statut == R.STATUT_NON_CONFORME:
        return fmt["ko"]
    return fmt["na"]


def exporter(chemin, resultat, version):
    """
    Ecrit le classeur. Retourne (nb_onglets, nb_constats_ecrits).
    Leve si le fichier ne peut pas etre ecrit : l'appelant le signale.
    """
    wb = xlsxwriter.Workbook(chemin, {"constant_memory": False})
    fmt = _formats(wb)
    try:
        n_constats = 0
        _feuille_synthese(wb, fmt, resultat, version)
        _feuille_regles(wb, fmt, resultat)
        pris = set([u"synthese", u"regles"])
        onglets = 2
        for cat in resultat["categories"]:
            lignes = [l for l in resultat["regles"]
                      if l["categorie"] == cat["nom"] and l["constats"]]
            if not lignes:
                continue
            n_constats += _feuille_detail(wb, fmt, _nom_onglet(cat["nom"], pris),
                                          cat["nom"], lignes)
            onglets += 1
        return onglets, n_constats
    finally:
        wb.close()


# -----------------------------------------------------------------------------
def _feuille_synthese(wb, fmt, resultat, version):
    ws = wb.add_worksheet(u"Synthese")
    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 46)
    ws.set_column(2, 5, 14)

    k = resultat["kpi"]
    c = resultat["contexte"]

    ws.write(0, 0, u"Contrôle de conformité BEP - Fairmont Grand Hotel", fmt["titre"])
    ws.write(1, 0, u"STR BIM Tools v{0}".format(version), fmt["note"])

    # Aptitude au depot AVANT le taux : le taux pondere toutes les regles a
    # egalite et ne dit pas si la maquette est deposable.
    depot = resultat.get("depot") or {}
    r = 3
    if depot:
        ws.write(r, 0, u"APTITUDE AU DÉPÔT", fmt["sous"])
        ws.write(r, 1, u"", fmt["sous"])
        r += 1
        ws.write(r, 0, depot.get("code", u""), fmt["label"])
        ws.write(r, 1, depot.get("phrase", u""), fmt["cell"])
        r += 2
    ws.write(r, 0, u"Maquette", fmt["label"])
    ws.write(r, 1, c.get("titre", u""))
    r += 1
    ws.write(r, 0, u"Fichier", fmt["label"])
    ws.write(r, 1, c.get("chemin", u""))
    r += 1
    ws.write(r, 0, u"Taille", fmt["label"])
    ws.write(r, 1, c.get("taille", u"-"))
    r += 1
    ws.write(r, 0, u"Version Revit", fmt["label"])
    ws.write(r, 1, c.get("version_revit", u""))
    r += 1
    ws.write(r, 0, u"Maquette collaborative", fmt["label"])
    ws.write(r, 1, u"oui" if c.get("collaboratif") else u"non")
    r += 1
    ws.write(r, 0, u"Référentiel", fmt["label"])
    ws.write(r, 1, c.get("referentiel", u""))
    if c.get("erreur_referentiel"):
        r += 1
        ws.write(r, 0, u"Alerte référentiel", fmt["label"])
        ws.write(r, 1, c["erreur_referentiel"], fmt["ko"])

    # --- Tracabilite ---------------------------------------------------------
    # Sans ces lignes, le classeur atteste qu'un outil a produit un resultat,
    # pas contre quoi ni dans quelles conditions. Deux rapports portant la
    # meme version d'outil peuvent diverger par le seul jeu des reglages.
    r += 2
    ws.write(r, 0, u"TRAÇABILITÉ DU CONTRÔLE", fmt["sous"])
    ws.write(r, 1, u"", fmt["sous"])
    tracabilite = [
        (u"Date et heure", c.get("horodatage", u"")),
        (u"Lancé par", c.get("utilisateur", u"")),
        (u"Version de l'outil", u"STR BIM Tools v{0}".format(version)),
        (u"BEP contrôlé", u"{0} {1} — {2}".format(
            c.get("bep_emetteur", u""), c.get("bep_revision", u""),
            c.get("bep_date", u"")).strip(u" —")),
        (u"Document de référence", c.get("bep_fichier", u"")),
        (u"Empreinte du référentiel", c.get("empreinte_referentiel", u"")),
    ]
    empreinte_reglages = c.get("empreinte_reglages")
    derogations = c.get("derogations") or []
    if not derogations:
        etat = u"aucune — référentiel BEP appliqué tel quel"
    else:
        etat = u"{0} dérogation(s) active(s), empreinte {1}".format(
            len(derogations), empreinte_reglages or u"?")
    tracabilite.append((u"Réglages de projet", etat))
    for libelle, valeur in tracabilite:
        r += 1
        ws.write(r, 0, libelle, fmt["label"])
        ws.write(r, 1, valeur,
                 fmt["ko"] if (libelle == u"Réglages de projet" and derogations)
                 else fmt["cell"])

    # Le detail des derogations, faute de quoi l'empreinte ci-dessus
    # n'apprendrait rien a qui relit le rapport.
    if derogations:
        r += 2
        ws.write(r, 0, u"DÉROGATIONS AU RÉFÉRENTIEL BEP", fmt["sous"])
        for col in range(1, 3):
            ws.write(r, col, u"", fmt["sous"])
        r += 1
        ws.write_row(r, 0, [u"Réglage", u"Valeur du BEP", u"Valeur appliquée"],
                     fmt["hdr"])
        for i, (sujet, valeur_bep, valeur_appliquee) in enumerate(derogations):
            r += 1
            f = fmt["alt"] if i % 2 else fmt["cell"]
            ws.write(r, 0, sujet, f)
            ws.write(r, 1, valeur_bep, f)
            ws.write(r, 2, valeur_appliquee, fmt["ko"])

    r += 2
    ws.write(r, 0, u"INDICATEURS", fmt["sous"])
    ws.write(r, 1, u"", fmt["sous"])
    r += 1
    indicateurs = [
        (u"Éléments de modèle analysés", k["elements"]),
        (u"Règles contrôlées", k["regles"]),
        (u"Règles applicables", k["applicables"]),
        (u"Règles conformes", k["conformes"]),
        (u"Règles non conformes", k["non_conformes"]),
        (u"Règles non applicables", k["non_applicables"]),
        (u"Écarts relevés (éléments)", k["constats"]),
        (u"dont écarts bloquants", k["bloquants"]),
    ]
    for libelle, valeur in indicateurs:
        ws.write(r, 0, libelle, fmt["cell"])
        ws.write_number(r, 1, valeur, fmt["num"])
        r += 1
    ws.write(r, 0, u"Taux de conformité", fmt["cell"])
    ws.write_number(r, 1, k["taux"] / 100.0, fmt["pct"])

    r += 3
    ws.write(r, 0, u"TAUX PAR CATÉGORIE", fmt["sous"])
    for col in range(1, 6):
        ws.write(r, col, u"", fmt["sous"])
    r += 1
    entetes = [u"Catégorie", u"Règles", u"Conformes", u"Non conformes",
               u"Non applicables", u"Écarts"]
    ws.write_row(r, 0, entetes, fmt["hdr"])
    r += 1
    debut = r
    for i, cat in enumerate(resultat["categories"]):
        f = fmt["alt"] if i % 2 else fmt["cell"]
        fn = fmt["num_alt"] if i % 2 else fmt["num"]
        ws.write(r, 0, cat["nom"], f)
        ws.write_number(r, 1, cat["regles"], fn)
        ws.write_number(r, 2, cat["conformes"], fn)
        ws.write_number(r, 3, cat["non_conformes"], fn)
        ws.write_number(r, 4, cat["na"], fn)
        ws.write_number(r, 5, cat["constats"], fn)
        r += 1
    if r > debut:
        ws.conditional_format(debut, 3, r - 1, 3, {
            "type": "cell", "criteria": ">", "value": 0,
            "format": wb.add_format({"font_color": C_ROUGE, "bold": True})})
    ws.freeze_panes(debut, 0)


# -----------------------------------------------------------------------------
def _feuille_regles(wb, fmt, resultat):
    ws = wb.add_worksheet(u"Règles")
    largeurs = [8, 20, 46, 11, 10, 16, 10, 40]
    for i, w in enumerate(largeurs):
        ws.set_column(i, i, w)
    entetes = [u"ID", u"Catégorie", u"Règle", u"Sévérité", u"Article BEP",
               u"Statut", u"Écarts", u"Commentaire"]
    ws.write_row(0, 0, entetes, fmt["hdr"])
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, max(1, len(resultat["regles"])), len(entetes) - 1)

    for i, l in enumerate(resultat["regles"]):
        r = i + 1
        f = fmt["alt"] if i % 2 else fmt["cell"]
        fn = fmt["num_alt"] if i % 2 else fmt["num"]
        commentaire = l.get("motif_na") or u""
        if l.get("erreur"):
            commentaire = u"contrôle interrompu : {0}".format(l["erreur"])
        elif l.get("tronque"):
            commentaire = u"INCOMPLET : garde-fou mémoire atteint, {0} "                           u"écarts conservés".format(len(l["constats"]))
        ws.write(r, 0, l["id"], f)
        ws.write(r, 1, l["categorie"], f)
        ws.write(r, 2, l["libelle"], f)
        ws.write(r, 3, l["severite"], f)
        ws.write(r, 4, l["reference"], f)
        ws.write(r, 5, l["statut"], _format_statut(fmt, l["statut"]))
        ws.write_number(r, 6, l["nb"], fn)
        ws.write(r, 7, commentaire, f)


# -----------------------------------------------------------------------------
def _feuille_detail(wb, fmt, nom_onglet, categorie, lignes):
    ws = wb.add_worksheet(nom_onglet)
    largeurs = [8, 34, 46, 22, 44, 40, 12]
    for i, w in enumerate(largeurs):
        ws.set_column(i, i, w)
    entetes = [u"ID", u"Règle", u"Objet", u"Type d'objet", u"Écart constaté",
               u"Attendu (BEP)", u"ElementId"]
    ws.write_row(0, 0, entetes, fmt["hdr"])
    ws.freeze_panes(1, 0)

    r = 1
    n = 0
    for l in lignes:
        for cst in l["constats"]:
            f = fmt["alt"] if n % 2 else fmt["cell"]
            fn = fmt["num_alt"] if n % 2 else fmt["num"]
            ws.write(r, 0, l["id"], f)
            ws.write(r, 1, l["libelle"], f)
            ws.write(r, 2, cst.objet, f)
            ws.write(r, 3, cst.type_objet, f)
            ws.write(r, 4, cst.detail, f)
            ws.write(r, 5, cst.attendu, f)
            eid = _eid_texte(cst.eid)
            if eid is None:
                ws.write(r, 6, u"", fn)
            else:
                ws.write_number(r, 6, eid, fn)
            r += 1
            n += 1
        if l.get("tronque"):
            # Ne doit jamais arriver : le detail est complet par construction.
            ws.write(r, 0, l["id"], fmt["cell"])
            ws.write(r, 1, l["libelle"], fmt["cell"])
            ws.write(r, 2, u"... {0} écarts au total, {1} conservés : le "
                     u"garde-fou mémoire a joué, ce détail est INCOMPLET"
                     .format(l["nb"], len(l["constats"])), fmt["note"])
            r += 1
    if r > 1:
        ws.autofilter(0, 0, r - 1, len(entetes) - 1)
    return n


def _eid_texte(eid):
    if eid is None:
        return None
    try:
        return int(eid.IntegerValue)
    except Exception:
        pass
    try:
        return int(eid.Value)                          # Revit 2024+ (Int64)
    except Exception:
        return None
