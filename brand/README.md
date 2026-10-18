# STR BIM Tools — identité visuelle

Marque de l'extension pyRevit **STR BIM Tools**, par Tony Varin.
Concept retenu le 2026-08-04 : le **profilé**, une section en I ajourée dans un
carré plein.

## Couleurs

| Rôle | Hex | RVB | Usage |
|---|---|---|---|
| Bleu de marque | `#2F6496` | 47 · 100 · 150 | Le carré. **Déjà la couleur des bandeaux de fenêtres et des en-têtes Excel** — le logo n'introduit aucune couleur nouvelle. |
| Encre | `#1A1F26` | 26 · 31 · 38 | « STR BIM TOOLS » |
| Gris signature | `#7A838F` | 122 · 131 · 143 | « BY TONY VARIN » |

Pas de dégradé, pas d'ombre portée, pas de contour. La marque est faite de
quatre rectangles ; toute épaisseur ajoutée la trahit.

## Les fichiers

Les SVG sont les **masters** : le texte y est **vectorisé**, donc aucune police
n'est requise à l'affichage et l'interlettrage ne peut pas se refermer selon la
visionneuse. Les PNG sont sur fond **transparent** et tous rasterisés depuis la
même géométrie — jamais l'un redimensionné depuis l'autre.

| Fichier | Pour quoi |
|---|---|
| `STR_BIM_Tools_logo.svg` · `_1x/2x/4x.png` | Lockup complet, fond clair. **C'est celui des en-têtes Excel.** |
| `STR_BIM_Tools_logo_compact.svg` · `_2x.png` | Sans la signature. **À préférer sous 32 px de hauteur.** |
| `STR_BIM_Tools_logo_inverse.svg` · `_2x.png` | Lockup blanc, pour fond bleu ou sombre. |
| `STR_BIM_Tools_logo_compact_inverse.svg` · `_2x.png` | Les deux à la fois. |
| `STR_BIM_Tools_mark.svg` · `_64/128/256.png` | Symbole seul : icône, favicon, filigrane. |
| `STR_BIM_Tools_mark_inverse.svg` · `_inverse_128.png` | Symbole ajouré : le carré est blanc, le profilé laisse passer le fond. Tient sur n'importe quelle couleur. |

Proportions : lockup **4,51 : 1** (288,5 × 64 unités) · symbole **carré**.

## Règles d'emploi

**Zone de protection** — un demi-côté du carré (32 unités, soit la moitié de la
hauteur du logo) sur les quatre côtés. Aucun texte, filet ou bord de cellule ne
doit y pénétrer.

**Tailles minimales**, mesurées à l'épreuve :

| | Minimum | Pourquoi |
|---|---|---|
| Lockup complet | **32 px** de haut | En dessous, « BY TONY VARIN » se bouche. |
| Lockup compact | **20 px** de haut | |
| Symbole seul | **14 px** | En dessous, les ailes du profilé se referment sur l'âme. |

**Sur fond sombre** : toujours la version inversée. Le lockup positif y devient
illisible — l'encre `#1A1F26` disparaît.

**Monochrome** : le logo a été éprouvé en noir pur, il tient sans retouche.
Aucun fichier dédié n'est fourni ; convertir en niveaux de gris suffit.

**Ce qu'on ne fait pas** : recolorer le carré, étirer le lockup (les proportions
sont fixes), séparer le symbole du texte pour les recomposer autrement, poser le
logo sur une photo chargée, ajouter un contour ou une ombre.

## Régénérer

Les fichiers sont produits par deux scripts, la géométrie n'étant définie qu'une
seule fois en unités (marque = 64 × 64) :

- `make_logo.py <dossier>` — les PNG, via Pillow.
- `make_svg.py <dossier>` — les SVG, texte vectorisé via fontTools.

Ils vivent hors du dépôt (dossier de travail temporaire) : ils ne servent qu'à
refaire le jeu si les proportions changent. La typographie est **Arial Bold** et
**Arial Regular**, vectorisées — aucune police n'est distribuée avec l'extension.
