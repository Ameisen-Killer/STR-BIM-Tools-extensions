# -*- coding: utf-8 -*-
"""
Déjoindre la géométrie des éléments sélectionnés
UnjoinGeometry sur tous les couples joints détectés

Extension  : AB.extension
Tab        : TVa.tab
Panel      : Tony V..panel
Script     : unjoin_selected.py
Revit      : 2024
Engine     : IronPython 2.7
"""

# ── CONFIG ─────────────────────────────────────────────────────────────────────
SCRIPT_VERSION          = u"3.2"
SCRIPT_AUTHOR           = u"Tony Varin"
TOOL_NAME               = u"Detacher Geometrie"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    Transaction,
    JoinGeometryUtils,
    ElementId,
    FilteredElementCollector,
)
from Autodesk.Revit.UI import TaskDialog

import System
from System.Windows import (
    Window, WindowStartupLocation, SizeToContent,
    Thickness, HorizontalAlignment, VerticalAlignment,
    TextWrapping,
)
from System.Windows.Controls import (
    StackPanel, TextBlock, ListBox, ListBoxItem,
    Button, ScrollViewer, Orientation, Grid, ColumnDefinition,
)
from System.Windows import GridLength, GridUnitType
from System.Windows.Media import SolidColorBrush, Color

# ── Contexte PyRevit ────────────────────────────────────────────────────────
doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


# ── Rapport WPF ─────────────────────────────────────────────────────────────
def show_report(ok_count, skipped, errors):
    """Affiche un résumé WPF après traitement."""
    win = Window()
    win.Title = TOOL_NAME
    win.Width = 480
    win.SizeToContent = SizeToContent.Height
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.MaxHeight = 600
    win.Padding = Thickness(0)

    root = StackPanel()
    root.Margin = Thickness(16)
    root.Orientation = Orientation.Vertical

    # Titre
    title = TextBlock()
    title.Text = u"Résultat du détachement"
    title.FontSize = 15
    title.FontWeight = System.Windows.FontWeights.Bold
    title.Margin = Thickness(0, 0, 0, 10)
    root.Children.Add(title)

    # Ligne de stats
    stats = TextBlock()
    stats.TextWrapping = TextWrapping.Wrap
    stats.Margin = Thickness(0, 0, 0, 8)
    stats.Text = u"✔  Couples déjoints : {0}     ⚠  Ignorés : {1}     ✖  Erreurs : {2}".format(
        ok_count, len(skipped), len(errors)
    )
    root.Children.Add(stats)

    def add_section(label, items, color_hex):
        if not items:
            return
        hdr = TextBlock()
        hdr.Text = label
        hdr.FontWeight = System.Windows.FontWeights.SemiBold
        hdr.Margin = Thickness(0, 8, 0, 4)
        root.Children.Add(hdr)

        sv = ScrollViewer()
        sv.MaxHeight = 140
        sv.Margin = Thickness(0, 0, 0, 4)

        lb = ListBox()
        lb.BorderThickness = Thickness(1)
        for msg in items:
            item = ListBoxItem()
            tb = TextBlock()
            tb.Text = msg
            tb.TextWrapping = TextWrapping.Wrap
            tb.Padding = Thickness(4, 2, 4, 2)
            item.Content = tb
            lb.Items.Add(item)

        sv.Content = lb
        root.Children.Add(sv)

    add_section(u"⚠  Éléments ignorés (déjà séparés ou non joints)", skipped, "#FFA500")
    add_section(u"✖  Erreurs", errors, "#CC0000")

    # ── Footer : métadonnées à gauche, bouton à droite ──────────────────────
    footer = Grid()
    footer.Margin = Thickness(0, 14, 0, 0)

    col_left  = ColumnDefinition()
    col_left.Width = GridLength(1, GridUnitType.Star)
    col_right = ColumnDefinition()
    col_right.Width = GridLength.Auto
    footer.ColumnDefinitions.Add(col_left)
    footer.ColumnDefinitions.Add(col_right)

    meta = TextBlock()
    meta.Text = u"v{} | STR BIM Tools by Tony Varin".format(SCRIPT_VERSION)
    meta.FontSize = 10
    meta.Foreground = SolidColorBrush(Color.FromRgb(0x88, 0x88, 0x88))
    meta.VerticalAlignment = VerticalAlignment.Center
    Grid.SetColumn(meta, 0)
    footer.Children.Add(meta)

    btn = Button()
    btn.Content = u"Fermer"
    btn.Width = 90
    btn.Click += lambda s, e: win.Close()
    Grid.SetColumn(btn, 1)
    footer.Children.Add(btn)

    root.Children.Add(footer)

    win.Content = root
    win.ShowDialog()


# ── Logique principale ───────────────────────────────────────────────────────
def main():
    # 1. Récupérer la sélection
    sel_ids = list(uidoc.Selection.GetElementIds())

    if not sel_ids:
        TaskDialog.Show(
            u"Déjoindre géométrie",
            u"Aucun élément sélectionné.\nSélectionne des éléments dans le modèle puis relance le script."
        )
        return

    elements = [doc.GetElement(eid) for eid in sel_ids]

    # 2. Construire tous les couples (A, B) joints parmi la sélection
    #    + couples entre sélection et reste du modèle
    ok_count = 0
    skipped  = []
    errors   = []
    processed_pairs = set()  # évite de traiter (A,B) et (B,A)

    def pair_key(id_a, id_b):
        a, b = id_a.IntegerValue, id_b.IntegerValue
        return (min(a, b), max(a, b))

    # Collecte tous les éléments du doc pour chercher les voisins joints
    all_ids = set(
        e.Id.IntegerValue
        for e in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
        if e is not None and e.IsValidObject
    )

    with Transaction(doc, u"Déjoindre géométrie — sélection") as t:
        t.Start()

        for elem in elements:
            if elem is None or not elem.IsValidObject:
                continue

            try:
                joined_ids = JoinGeometryUtils.GetJoinedElements(doc, elem)
            except Exception as ex:
                errors.append(u"ID {0} — impossible de lire les joins : {1}".format(
                    elem.Id.IntegerValue, str(ex)))
                continue

            if not joined_ids or joined_ids.Count == 0:
                skipped.append(u"ID {0} ({1}) — aucun élément joint".format(
                    elem.Id.IntegerValue,
                    elem.Category.Name if elem.Category else u"?"
                ))
                continue

            for other_id in joined_ids:
                key = pair_key(elem.Id, other_id)
                if key in processed_pairs:
                    continue
                processed_pairs.add(key)

                other = doc.GetElement(other_id)
                if other is None or not other.IsValidObject:
                    continue

                try:
                    if JoinGeometryUtils.AreElementsJoined(doc, elem, other):
                        JoinGeometryUtils.UnjoinGeometry(doc, elem, other)
                        ok_count += 1
                except Exception as ex:
                    errors.append(u"IDs {0}↔{1} — {2}".format(
                        elem.Id.IntegerValue,
                        other_id.IntegerValue,
                        str(ex)
                    ))

        t.Commit()

    # 3. Rapport
    show_report(ok_count, skipped, errors)


# ── Point d'entrée ───────────────────────────────────────────────────────────
main()