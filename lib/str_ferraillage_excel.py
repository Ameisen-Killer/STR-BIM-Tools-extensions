# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_excel.py - Ecriture de la liste de fer en XLSX (xlsxwriter).
#
# Mise en page A4 portrait reprenant les listes de fer du bureau :
#   cartouche (objet, n° de liste, n° de plan, date, dessin/verif, adresse,
#   acier), recapitulation par diametre (barres droites / faconnees), puis
#   liste des positions avec la figure de faconnage (image PNG par position,
#   cotes exterieures en cm). Une 2e feuille "Donnees" donne la liste a plat.
#
# Sans API Revit ni WPF : testable hors Revit avec CPython + xlsxwriter.
# =============================================================================

import str_ferraillage as FER

# Colonnes : A Pos | B Nombre | C ø | D Long. | E Long. totale | F:I Figure
_LARGEURS = [7.5, 8.5, 6.0, 8.0, 10.5, 12.0, 12.0, 12.0, 12.0]
_FIG = (5, 8)                       # colonnes F..I (index 0)
_HT_LIGNE_POS = 36                  # pt, ligne des valeurs
_HT_LIGNE_REM = 26                  # pt, ligne de remarque
# Zone image en pixels (colonnes F:I a 12 car. ~ 89 px chacune)
FIGURE_LARGEUR_PX = 340
FIGURE_HAUTEUR_PX = 80

CHAMPS_CARTOUCHE = [
    # cle, libelle, valeur par defaut
    ("objet1", u"Objet (ligne 1)", u""),
    ("objet2", u"Objet (ligne 2)", u""),
    ("objet3", u"Objet (ligne 3)", u""),
    ("objet4", u"Objet (ligne 4)", u"Liste"),
    ("entreprise", u"Entreprise", u""),
    ("no_liste", u"N° liste", u""),
    ("no_plan", u"N° plan", u""),
    ("adresse1", u"Adresse (ligne 1)", u""),
    ("adresse2", u"Adresse (ligne 2)", u""),
    ("date", u"Date", u""),
    ("dessin", u"Dessin.", u""),
    ("verif", u"Vérif.", u""),
    ("norme", u"Norme", u"SIA 262"),
    ("acier", u"Acier", u"B500B"),
    ("remarque", u"Remarque", u""),
]


def _fmt(wb, **kw):
    base = {"font_name": "Arial", "font_size": 9, "valign": "vcenter"}
    base.update(kw)
    return wb.add_format(base)


def ecrire_liste(chemin, positions, recap, cartouche, images, pied_page,
                 titre_feuille=u"Liste de fer"):
    """
    chemin    : fichier .xlsx a creer
    positions : liste de str_ferraillage.Position (deja triee)
    recap     : str_ferraillage.recapituler(positions)
    cartouche : dict (cles de CHAMPS_CARTOUCHE)
    images    : dict id(position) -> chemin PNG (figure), absent = texte
    pied_page : texte du pied de page (outil, version, auteur)
    """
    import xlsxwriter

    c = dict((k, d) for k, _, d in CHAMPS_CARTOUCHE)
    c.update(dict((k, v) for k, v in (cartouche or {}).items() if v is not None))

    wb = xlsxwriter.Workbook(chemin)
    ws = wb.add_worksheet(titre_feuille[:31])

    f_lbl = _fmt(wb, font_size=8, font_color="#444444", valign="top")
    f_obj = _fmt(wb, bold=True, font_size=10, bottom=1)
    f_big = _fmt(wb, bold=True, font_size=12, align="center")
    f_val = _fmt(wb, bold=True, font_size=10, align="center")
    f_txt = _fmt(wb, bold=True, font_size=9)
    f_band = _fmt(wb, bg_color="#E8E8EE", align="center", top=1, bottom=1)
    f_sub = _fmt(wb, align="center", bottom=1)
    f_hdr = _fmt(wb, align="center", text_wrap=True, bottom=1)
    f_hdr_c = _fmt(wb, align="center", text_wrap=True, bottom=1, top=1)
    f_d = _fmt(wb, bold=True, align="center", bottom=1, bottom_color="#BBBBBB")
    f_n3 = _fmt(wb, bold=True, num_format="0.000", align="center",
                bottom=1, bottom_color="#BBBBBB")
    f_n2 = _fmt(wb, bold=True, num_format="#,##0.00", align="center",
                bottom=1, bottom_color="#BBBBBB")
    f_tot = _fmt(wb, bottom=1)
    f_tot_n = _fmt(wb, num_format="#,##0.00", align="center", bottom=1)
    f_tot_b = _fmt(wb, bold=True, num_format="#,##0.00", align="center",
                   bottom=1)
    f_part = _fmt(wb, font_size=10, bottom=1)
    f_pos = _fmt(wb, font_size=10, align="center")
    f_nb = _fmt(wb, font_size=10, bold=True, align="center")
    f_num = _fmt(wb, font_size=10, num_format="0.00", align="center")
    f_num_tot = _fmt(wb, font_size=10, num_format="#,##0.00", align="center")
    f_rem = _fmt(wb, font_size=9, text_wrap=True, valign="top", bottom=1)
    f_fig = _fmt(wb, font_size=9, align="center", bottom=1, text_wrap=True)
    f_alerte = _fmt(wb, font_size=8, font_color="#CC0000", text_wrap=True,
                    valign="top", bottom=1)

    for i, w in enumerate(_LARGEURS):
        ws.set_column(i, i, w)

    # --- Mise en page --------------------------------------------------------
    ws.set_paper(9)                     # A4
    ws.set_portrait()
    ws.set_margins(left=0.5, right=0.4, top=0.7, bottom=0.6)
    ws.fit_to_pages(1, 0)
    ws.center_horizontally()
    ws.hide_gridlines(2)
    entete = u"&L&8N° liste : &\"Arial,Bold\"{0}&\"Arial,Regular\"" \
             u"&R&8N° plan : &\"Arial,Bold\"{1}".format(
                 _echap(c["no_liste"]), _echap(c["no_plan"]))
    ws.set_header(entete)
    ws.set_footer(u"&L&7{0}&R&8&P/&N".format(_echap(pied_page)))

    # --- Cartouche -----------------------------------------------------------
    r = 0
    ws.write(r, 0, u"Objet :", f_lbl)
    ws.write(r, 4, u"N° liste :", f_lbl)
    ws.write(r, 7, u"Date :", f_lbl)
    ws.set_row(r, 12)
    for i, k in enumerate(("objet1", "objet2", "objet3", "objet4")):
        ws.merge_range(r + 1 + i, 0, r + 1 + i, 3, c[k], f_obj)
        ws.set_row(r + 1 + i, 16)
    ws.merge_range(r + 1, 4, r + 2, 6, c["no_liste"], f_big)
    ws.merge_range(r + 1, 7, r + 2, 8, c["date"], f_big)
    ws.write(r + 3, 4, u"N° plan :", f_lbl)
    ws.write(r + 3, 7, u"Dessin. :", f_lbl)
    ws.write(r + 3, 8, u"Vérif. :", f_lbl)
    ws.merge_range(r + 4, 4, r + 4, 6, c["no_plan"], f_big)
    ws.write(r + 4, 7, c["dessin"], f_val)
    ws.write(r + 4, 8, c["verif"], f_val)
    r = 5
    ws.write(r, 0, u"Entreprise :", f_lbl)
    ws.write(r, 4, u"Adresse :", f_lbl)
    ws.write(r, 7, u"Acier :", f_lbl)
    ws.set_row(r, 12)
    ws.merge_range(r + 1, 0, r + 1, 3, c["entreprise"], f_txt)
    ws.merge_range(r + 1, 4, r + 1, 6, c["adresse1"], f_txt)
    ws.merge_range(r + 2, 4, r + 2, 6, c["adresse2"], f_txt)
    ws.merge_range(r + 1, 7, r + 1, 8, c["norme"], f_big)
    ws.merge_range(r + 2, 7, r + 2, 8, c["acier"], f_big)
    r = 8
    ws.write(r, 0, u"Remarque :", f_lbl)
    ws.merge_range(r, 1, r, 8, c["remarque"], _fmt(wb, bottom=1))
    r = 10

    # --- Recapitulation ------------------------------------------------------
    ws.merge_range(r, 0, r, 8, u"Récapitulation par diamètre(s)", f_band)
    ws.set_row(r, 16)
    r += 1
    ws.merge_range(r, 0, r, 4, u"Barres de longueur fixe et de stock", f_sub)
    ws.merge_range(r, 5, r, 8, u"Barres façonnées", f_sub)
    r += 1
    for cols in ((0, 1, (2, 3), 4), (5, 6, 7, 8)):
        _ecrire_cellule(ws, r, cols[0], u"ø\nmm", f_hdr)
        _ecrire_cellule(ws, r, cols[1], u"Poids/m\nkg/m", f_hdr)
        _ecrire_cellule(ws, r, cols[2], u"Long.\nm", f_hdr)
        _ecrire_cellule(ws, r, cols[3], u"Poids\nkg", f_hdr)
    ws.set_row(r, 24)
    r += 1
    nb_lignes = max(len(recap["droites"]), len(recap["faconnees"]), 1)
    for i in range(nb_lignes):
        for table, cols in ((recap["droites"], (0, 1, (2, 3), 4)),
                            (recap["faconnees"], (5, 6, 7, 8))):
            if i < len(table):
                d, kgm, lg, pds = table[i]
                _ecrire_cellule(ws, r, cols[0], d, f_d)
                _ecrire_cellule(ws, r, cols[1], round(kgm, 3), f_n3)
                _ecrire_cellule(ws, r, cols[2], round(lg, 2), f_n2)
                _ecrire_cellule(ws, r, cols[3], round(pds, 2), f_n2)
            else:
                for cc in cols:
                    _ecrire_cellule(ws, r, cc, u"", f_d)
        ws.set_row(r, 16)
        r += 1
    ws.write(r, 0, u"Total", f_tot)
    ws.write(r, 1, u"", f_tot)
    ws.merge_range(r, 2, r, 3, round(recap["tot_droites"][0], 2), f_tot_n)
    ws.write(r, 4, round(recap["tot_droites"][1], 2), f_tot_n)
    ws.write(r, 5, u"Total", f_tot)
    ws.write(r, 6, u"", f_tot)
    ws.write(r, 7, round(recap["tot_faconnees"][0], 2), f_tot_n)
    ws.write(r, 8, round(recap["tot_faconnees"][1], 2), f_tot_n)
    ws.set_row(r, 16)
    r += 1
    ws.write(r, 0, recap["nb_positions"], _fmt(wb, bold=True, align="right",
                                               bottom=1))
    ws.merge_range(r, 1, r, 3, u" positions", f_tot)
    ws.write(r, 4, u"ø {0}".format(FER.fmt_nombre(recap["d_moyen"])),
             _fmt(wb, bold=True, align="center", bottom=1))
    ws.write(r, 5, u"Total liste", f_tot)
    ws.write(r, 6, u"", f_tot)
    ws.write(r, 7, u"{0} m".format(FER.fmt_nombre(recap["total"][0])),
             _fmt(wb, bold=True, align="center", bottom=1))
    ws.write(r, 8, u"{0} kg".format(FER.fmt_nombre(recap["total"][1])),
             _fmt(wb, bold=True, align="center", bottom=1))
    ws.set_row(r, 18)
    r += 2

    # --- Liste des positions -------------------------------------------------
    ws.merge_range(r, 0, r, 8, u"Liste des positions", f_band)
    ws.set_row(r, 16)
    r += 1
    ligne_entete = r
    for col, txt in enumerate((u"Pos.", u"Nombre", u"ø", u"Long.\nm",
                               u"Long. totale\nm")):
        ws.write(r, col, txt, f_hdr_c)
    ws.merge_range(r, _FIG[0], r, _FIG[1],
                   u"Figure de façonnage\nDimensions extérieures en cm",
                   f_hdr_c)
    ws.set_row(r, 26)
    ws.repeat_rows(ligne_entete)
    r += 1

    partition = None
    for p in positions:
        if p.partition != partition:
            partition = p.partition
            if partition:
                ws.merge_range(r, 0, r, 8, partition, f_part)
                ws.set_row(r, 20)
                r += 1
        ws.set_row(r, _HT_LIGNE_POS)
        ws.set_row(r + 1, _HT_LIGNE_REM)
        ws.write(r, 0, p.repere, f_pos)
        ws.write(r, 1, p.nb, f_nb)
        ws.write(r, 2, p.d_int, f_pos)
        ws.write(r, 3, round(p.longueur_m, 2), f_num)
        ws.write(r, 4, round(p.longueur_tot_m, 2), f_num_tot)
        rem = p.remarque
        if p.alertes:
            ws.merge_range(r + 1, 0, r + 1, 4,
                           (rem + u"\n" if rem else u"") +
                           u"! " + u" ; ".join(p.alertes), f_alerte)
        else:
            ws.merge_range(r + 1, 0, r + 1, 4, rem, f_rem)
        img = images.get(id(p)) if images else None
        if img:
            ws.merge_range(r, _FIG[0], r + 1, _FIG[1], u"", f_fig)
            ws.insert_image(r, _FIG[0], img, {
                "x_offset": 4, "y_offset": 3,
                "x_scale": 0.5, "y_scale": 0.5,
                "object_position": 1})
        else:
            ws.merge_range(r, _FIG[0], r + 1, _FIG[1], p.cotes, f_fig)
        r += 2

    _feuille_donnees(wb, positions)
    wb.close()
    return chemin


def _feuille_donnees(wb, positions):
    """Feuille a plat pour controle, filtres et tableaux croises."""
    ws = wb.add_worksheet(u"Donnees")
    f_h = wb.add_format({"bold": True, "bg_color": "#2F6496",
                         "font_color": "#FFFFFF", "border": 1,
                         "text_wrap": True, "valign": "vcenter"})
    f_t = wb.add_format({"border": 1})
    f_alt = wb.add_format({"border": 1, "bg_color": "#E8F0FA"})
    f_2 = wb.add_format({"border": 1, "num_format": "0.00"})
    f_2a = wb.add_format({"border": 1, "num_format": "0.00",
                          "bg_color": "#E8F0FA"})
    f_3 = wb.add_format({"border": 1, "num_format": "0.000"})
    f_3a = wb.add_format({"border": 1, "num_format": "0.000",
                          "bg_color": "#E8F0FA"})
    entetes = [u"Partition", u"Pos.", u"Nombre", u"ø mm", u"Long. m",
               u"Long. totale m", u"Poids/m kg/m", u"Poids kg", u"Façonnée",
               u"Cotes ext. cm", u"Ø mandrin mm", u"Remarque", u"Alertes",
               u"ID Revit"]
    largeurs = [20, 7, 8, 6, 9, 11, 10, 10, 9, 22, 10, 30, 30, 22]
    for i, w in enumerate(largeurs):
        ws.set_column(i, i, w)
    ws.write_row(0, 0, entetes, f_h)
    ws.set_row(0, 30)
    ws.freeze_panes(1, 0)
    for i, p in enumerate(positions):
        alt = i % 2 == 1
        ft, f2, f3 = (f_alt, f_2a, f_3a) if alt else (f_t, f_2, f_3)
        r = i + 1
        ws.write(r, 0, p.partition, ft)
        ws.write(r, 1, p.repere, ft)
        ws.write(r, 2, p.nb, ft)
        ws.write(r, 3, p.d_int, ft)
        ws.write(r, 4, round(p.longueur_m, 2), f2)
        ws.write(r, 5, round(p.longueur_tot_m, 2), f2)
        ws.write(r, 6, round(p.kg_m, 3), f3)
        ws.write(r, 7, round(p.poids_kg, 2), f2)
        ws.write(r, 8, u"Oui" if p.faconnee else u"Non", ft)
        ws.write(r, 9, p.cotes, ft)
        ws.write(r, 10, int(round(p.mandrin_mm)) if p.mandrin_mm else u"", ft)
        ws.write(r, 11, p.remarque, ft)
        ws.write(r, 12, u" ; ".join(p.alertes), ft)
        ws.write(r, 13, u", ".join(u"{0}".format(x) for x in p.ids), ft)
    if positions:
        ws.autofilter(0, 0, len(positions), len(entetes) - 1)


def _ecrire_cellule(ws, r, col, valeur, fmt):
    """col = index ou (debut, fin) a fusionner."""
    if isinstance(col, tuple):
        ws.merge_range(r, col[0], r, col[1], valeur, fmt)
    else:
        ws.write(r, col, valeur, fmt)


def _echap(texte):
    """Echappe '&' pour les en-tetes / pieds de page Excel."""
    return (texte or u"").replace(u"&", u"&&")
