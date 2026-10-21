# -*- coding: utf-8 -*-
# =============================================================================
# str_ferraillage_figure.py - Dessin PNG des figures de faconnage (WPF).
#
# La mise en page (traits + cotes, en pixels) est calculee par
# str_ferraillage.mise_en_page_figure ; ce module ne fait que la dessiner
# dans un DrawingVisual et l'enregistrer en PNG (resolution x2 pour un rendu
# net une fois insere a 50 % dans Excel).
#
# Depend de WPF uniquement (pas de l'API Revit).
# Compatible IronPython 2.7 (Revit 2024) et IronPython 3.4 (Revit 2025+).
# =============================================================================

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Globalization import CultureInfo
from System.IO import FileStream, FileMode
from System.Windows import (FlowDirection, FontStretches, FontStyles,
                            FontWeights, Point, Rect)
from System.Windows.Media import (Brushes, DrawingVisual, FontFamily,
                                  FormattedText, Pen, PenLineCap,
                                  PenLineJoin, PixelFormats, Typeface)
from System.Windows.Media.Imaging import (BitmapFrame, PngBitmapEncoder,
                                          RenderTargetBitmap)

import str_ferraillage as FER

ECHELLE = 2.0                   # pixels PNG par pixel de mise en page
_POLICE = Typeface(FontFamily(u"Arial"), FontStyles.Normal,
                   FontWeights.Normal, FontStretches.Normal)


def _texte(contenu, taille):
    """FormattedText compatible .NET 4.8 et .NET 8 (pixelsPerDip)."""
    try:
        return FormattedText(contenu, CultureInfo.InvariantCulture,
                             FlowDirection.LeftToRight, _POLICE, taille,
                             Brushes.Black, 1.0)
    except Exception:
        return FormattedText(contenu, CultureInfo.InvariantCulture,
                             FlowDirection.LeftToRight, _POLICE, taille,
                             Brushes.Black)


def dessiner_png(chemin, forme, mandrin_mm=None, largeur=340, hauteur=80):
    """Enregistre la figure d'une position en PNG. Retourne le chemin."""
    mep = FER.mise_en_page_figure(forme, largeur, hauteur)
    k = ECHELLE
    dv = DrawingVisual()
    dc = dv.RenderOpen()
    try:
        dc.DrawRectangle(Brushes.White, None,
                         Rect(0, 0, largeur * k, hauteur * k))
        pen = Pen(Brushes.Black, 1.6 * k)
        pen.StartLineCap = PenLineCap.Round
        pen.EndLineCap = PenLineCap.Round
        pen.LineJoin = PenLineJoin.Round
        for trait in mep["traits"]:
            for a, b in zip(trait[:-1], trait[1:]):
                dc.DrawLine(pen, Point(a[0] * k, a[1] * k),
                            Point(b[0] * k, b[1] * k))
        for x, y, txt, ancrage in mep["textes"]:
            ft = _texte(txt, 10.0 * k)
            w, h = ft.Width, ft.Height
            x, y = x * k, y * k
            if ancrage == "b":
                pos = Point(x - w / 2.0, y)
            elif ancrage == "h":
                pos = Point(x - w / 2.0, y - h)
            elif ancrage == "g":
                pos = Point(x - w, y - h / 2.0)
            elif ancrage == "d":
                pos = Point(x, y - h / 2.0)
            else:
                pos = Point(x - w / 2.0, y - h / 2.0)
            dc.DrawText(ft, pos)
        if mandrin_mm and not forme.get("droite"):
            ft = _texte(u"Ø{0}".format(int(round(mandrin_mm))), 8.0 * k)
            dc.DrawText(ft, Point(2 * k, 1 * k))
    finally:
        dc.Close()

    bmp = RenderTargetBitmap(int(largeur * k), int(hauteur * k), 96.0, 96.0,
                             PixelFormats.Pbgra32)
    bmp.Render(dv)
    enc = PngBitmapEncoder()
    enc.Frames.Add(BitmapFrame.Create(bmp))
    fs = FileStream(chemin, FileMode.Create)
    try:
        enc.Save(fs)
    finally:
        fs.Close()
    return chemin
