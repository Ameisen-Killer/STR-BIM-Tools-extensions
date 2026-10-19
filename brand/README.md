# STR BIM Tools — identité visuelle

Marque de l'extension pyRevit **STR BIM Tools**, par Tony Varin.
Concept retenu le 2026-08-04 : **le bloc** — le monogramme `STR` réservé en
blanc dans un carré plein.

Le carré portant déjà STR, le mot-symbole à côté se réduit à **« BIM TOOLS »** :
répéter STR affaiblirait les deux.

## Couleurs

| Rôle | Hex | RVB | Usage |
|---|---|---|---|
| Bleu de marque | `#2F6496` | 47 · 100 · 150 | Le carré. **Déjà la couleur des bandeaux de fenêtres et des en-têtes Excel** — le logo n'introduit aucune couleur nouvelle. |
| Encre | `#1A1F26` | 26 · 31 · 38 | « BIM TOOLS » |
| Gris signature | `#7A838F` | 122 · 131 · 143 | « BY TONY VARIN » |

Pas de dégradé, pas d'ombre portée, pas de contour.

## Construction

Sur une grille de **64 unités** (le côté du carré) :

- Monogramme `STR`, Arial Bold, interlettrage 0,055 cadratin, **largeur d'encre
  exactement 40 unités** — 12 unités de réserve de chaque côté. La taille de
  corps en découle (19,34), elle n'a pas été choisie à l'œil.
- Centrage **sur l'encre et non sur les chasses** : le S et le R n'ont pas les
  mêmes approches, un centrage sur les chasses paraîtrait décalé.
- Verticalement, c'est la **hauteur de capitale** qui est centrée, pas la ligne
  de base.
- Lockup : carré + 20 unités de blanc + mot-symbole. Ratio **3,56 : 1**
  (228 × 64 unités). Symbole seul : **carré**.

## Les fichiers

Les SVG sont les **masters** : le texte y est **vectorisé**, donc aucune police
n'est requise à l'affichage et l'interlettrage ne peut pas se refermer selon la
visionneuse. Les PNG sont sur fond **transparent**, tous rasterisés depuis la
même géométrie — jamais l'un redimensionné depuis l'autre.

| Fichier | Pour quoi |
|---|---|
| `STR_BIM_Tools_logo.svg` · `_1x/2x/4x.png` | Lockup complet, fond clair. **C'est celui des en-têtes Excel.** |
| `STR_BIM_Tools_logo_compact.svg` · `_2x.png` | Sans la signature. À préférer en petit format. |
| `STR_BIM_Tools_logo_inverse.svg` · `_2x.png` | Lockup blanc, pour fond bleu ou sombre. |
| `STR_BIM_Tools_logo_compact_inverse.svg` · `_2x.png` | Les deux à la fois. |
| `STR_BIM_Tools_mark.svg` · `_64/128/256.png` | Symbole seul : icône, favicon, filigrane. |
| `STR_BIM_Tools_mark_inverse.svg` · `_inverse_128.png` | Symbole **ajouré** : le carré est blanc, les lettres laissent passer le fond. Tient sur n'importe quelle couleur, sans second fichier. |

## Règles d'emploi

**Zone de protection** — un demi-côté du carré (32 unités, soit la moitié de la
hauteur du logo) sur les quatre côtés. Aucun texte, filet ou bord de cellule ne
doit y pénétrer.

**Tailles minimales**, mesurées à l'épreuve. Un monogramme a un plancher de
lisibilité plus haut qu'un pictogramme : trois lettres doivent tenir dans la
largeur du carré, là où une forme n'en aurait qu'une.

| | Minimum | Confortable | Ce qui lâche en dessous |
|---|---|---|---|
| Lockup complet | **32 px** de haut | 40 px | « BY TONY VARIN » se bouche. |
| Lockup compact | **24 px** de haut | 32 px | Le monogramme devient une tache. |
| Symbole seul | **28 px** | 32 px | Idem — à 14 px, `STR` n'est plus lisible. |

Sous 28 px, ne pas utiliser le symbole seul : préférer le lockup compact, dont
le mot-symbole reste lisible même quand le carré faiblit.

**Sur fond sombre** : toujours la version inversée. Le lockup positif y devient
illisible — l'encre `#1A1F26` disparaît.

**Monochrome** : éprouvé en noir pur, tient sans retouche. Aucun fichier dédié —
convertir en niveaux de gris suffit.

**Ce qu'on ne fait pas** : recolorer le carré, étirer le lockup (les proportions
sont fixes), remplacer le monogramme par un autre serrage, séparer le carré du
mot-symbole pour les recomposer autrement, ajouter un contour ou une ombre.

## Régénérer

Tout le jeu sort d'un seul script, `make_bloc.py <dossier>` : la géométrie n'est
définie qu'une fois, les PNG passent par Pillow et les SVG par fontTools, si
bien qu'un PNG et un SVG de même nom sont rigoureusement le même dessin. Le
script vit hors du dépôt (dossier de travail temporaire) ; il ne sert qu'à
refaire le jeu si les proportions changent.

Typographie : **Arial Bold** et **Arial Regular**, vectorisées — aucune police
n'est distribuée avec l'extension.
