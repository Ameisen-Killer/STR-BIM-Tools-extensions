# Tutoriel — Outil Sync Réservations
## STR BIM Tools · v3.1.0 · Tony VARIN

---

> **Comment utiliser ce document**
> Les marqueurs `[CAPTURE X]` indiquent l'emplacement des captures d'écran à coller depuis le chat de session.
> Chaque marqueur est accompagné d'une description de ce que montre la capture.
>
> Une version courte, mise en page et prête à diffuser existe au format PDF :
> `doc/FGH_Sync_Reservations.pdf` (6 pages A4). Elle sert de notice de référence ;
> le présent document reste le support détaillé avec captures.

---

## Table des matières

1. [Contexte et objectif](#1-contexte-et-objectif)
2. [Prérequis avant lancement](#2-prérequis-avant-lancement)
3. [Lancement de l'outil](#3-lancement-de-loutil)
4. [Lecture de l'interface principale](#4-lecture-de-linterface-principale)
   - 4.1 Barre de titre
   - 4.2 Barre de statistiques
   - 4.3 Barre de filtres
   - 4.4 Le tableau de comparaison (DataGrid)
   - 4.5 Code couleur des lignes
   - 4.6 Colonnes disponibles
5. [Les quatre cas de synchronisation](#5-les-quatre-cas-de-synchronisation)
6. [Workflow pas à pas](#6-workflow-pas-à-pas)
   - 6.1 Analyser le tableau
   - 6.2 Filtrer et sélectionner
   - 6.3 Lancer la synchronisation
   - 6.4 Lire le résumé de résultat
   - 6.5 Vérifier après synchro
7. [Fonctions complémentaires](#7-fonctions-complémentaires)
   - 7.1 Vue 3D
   - 7.2 Export CSV
8. [Règles métier importantes](#8-règles-métier-importantes)
9. [Erreurs fréquentes et solutions](#9-erreurs-fréquentes-et-solutions)
10. [Points de vigilance — Administration](#10-points-de-vigilance--administration)

---

## 1. Contexte et objectif

Dans le flux BIM du projet, les **réservations de passage** sont créées et gérées dans la **maquette SPV** (architecte/coordinateur), sous forme de familles `FGH_RES*` avec leurs paramètres partagés.

La **maquette STR** (structure) reçoit ces réservations en **lecture seule via un lien Revit**. L'ingénieur STR doit les analyser, les valider ou les refuser, puis les intégrer dans la maquette STR pour que le ferraillage et les réservations coexistent géométriquement.

L'outil **Sync Réservations** automatise cette synchronisation en :

- **comparant** les réservations du lien SPV avec celles présentes dans la maquette STR ;
- **identifiant** les nouvelles, les modifiées, les supprimées et les invalidées ;
- **copiant** les éléments validés depuis le lien vers la maquette hôte ;
- **marquant** les éléments supprimés ou invalidés sans les effacer physiquement.

```
Maquette SPV (lien)          Outil Sync          Maquette STR (hôte)
  FGH_RES_V_RECT  ──────────────────────────▶  FGH_RES_V_RECT  (copié)
  FGH_RES_H_ROND  ──────────────────────────▶  FGH_RES_H_ROND  (copié)
  [Statut = VALIDE uniquement]                  Sous-projet : 03_STR_RESERVATIONS
```

---

## 2. Prérequis avant lancement

| Condition | Vérification |
|-----------|-------------|
| Maquette STR ouverte dans Revit 2024 | — |
| Lien SPV chargé (nom contenant `FGH_RES_SPV`) | Onglet Gérer › Liens Revit |
| Sous-projet `03_STR_RESERVATIONS` existant dans la maquette STR | Gérer › Sous-projets |
| Familles `FGH_RES*` chargées dans la maquette STR | Arborescence du projet |
| Paramètres partagés `PVA_RES_*` liés aux familles | Gérer › Paramètres partagés |

> **Important** : si le sous-projet `03_STR_RESERVATIONS` est absent, les éléments copiés atterriront dans le sous-projet actif. Un avertissement s'affiche en fin de sync.

---

## 3. Lancement de l'outil

L'outil se trouve dans le ruban pyRevit :

```
Onglet STR BIM Tools
  └─ Panneau Base
       └─ Bouton-menu FGH ▼
              └─ Sync Réservations
```

Au clic, le script :
1. Recherche automatiquement le lien dont le nom contient `FGH_RES_SPV`.
2. Collecte toutes les `FamilyInstance` dont le nom de famille commence par `FGH_RES` dans le lien **et** dans la maquette hôte.
3. Compare les deux ensembles via le paramètre `PVA_RES_DEM_NumReservation`.
4. Affiche la fenêtre principale avec le résultat de la comparaison.

---

## 4. Lecture de l'interface principale

### [CAPTURE 1]
> **Ce que montre cette capture** : la fenêtre principale après analyse. La barre de statistiques montre VALIDE : 533, REFUSÉ : 226, Absentes : 2 115, Invalidées : 49, OK : 529, STR seul : 5, Total lien : 2 768, Total hôte : 584, puis `Affichées : x / y` et `53 sélectionnée(s)`. En dessous, la barre de filtres. Le tableau affiche des lignes orangées (INVALIDE) et vertes (ABSENT VALIDE). Le pied de page indique `v3.1.0 | STR BIM Tools by Tony Varin`.

---

### 4.1 Barre de titre

```
Reservations RES vs STR                              (titre de la fenêtre)
Comparaison Réservations — STR (584 él.) vs SPV/FGH_RES_SPV_... (2768 él.)
```

La version de l'outil est affichée en bas à gauche, dans le pied de page :
`v3.1.0 | STR BIM Tools by Tony Varin`.

- **STR (584 él.)** : nombre d'éléments `FGH_RES*` trouvés dans la maquette hôte (hors éléments marqués Supprimé).
- **SPV/... (2768 él.)** : nombre d'éléments `FGH_RES*` trouvés dans le lien.

---

### 4.2 Barre de statistiques

| Compteur | Signification |
|----------|--------------|
| **VALIDE : 533** | Réservations du lien dont le statut validation = `VALIDE` |
| **REFUSÉ : 226** | Réservations du lien dont le statut = `REFUSE` |
| **✖ Absentes : 2 115** | Présentes dans le lien, absentes de la STR |
| **⛔ Invalidées : 49** | Présentes dans la STR mais dont la validation a été retirée ou refusée |
| **✔ OK : 529** | Présentes dans les deux modèles, identiques |
| **STR seul : 5** | Présentes dans la STR mais introuvables dans le lien |
| **Total lien / Total hôte** | Totaux bruts |
| **Affichées : 12 / 5014** | Lignes visibles après filtrage / total analysé |
| **12 sélectionnée(s)** | Lignes cochées, donc traitées par Synchroniser |

> **Lecture rapide** : à l'ouverture, les chiffres clés à surveiller sont **Absentes** (Cas A — à copier), **Invalidées** (Cas D — à purger) et **⚠ Différentes** (Cas B — à mettre à jour).

> **Attention au compteur de sélection** : si des lignes cochées sont masquées par un filtre, le compteur le signale — `48 sélectionnée(s) — dont 36 hors filtre`. Ces 36 lignes **seront quand même synchronisées** : Synchroniser traite toutes les lignes cochées, pas seulement celles affichées. Décocher ce qui ne doit pas partir avant de lancer.

---

### 4.3 Barre de filtres

Depuis la v3.1.0, une barre de filtres occupe le haut de la fenêtre, juste sous les statistiques. Elle sert à isoler un sous-ensemble de réservations puis à le cocher d'un seul clic.

```
Filtres :  [Statut VAL ▼]  [Date VAL ▼]  [Statut synchro ▼]  [Recherche____]
           ☐ Actionnables seulement   [Réinitialiser] | [Cocher affichés] [Décocher affichés]
```

| Contrôle | Rôle |
|----------|------|
| **Statut VAL** | `VALIDE`, `REFUSE`, `(vide)` ou tout autre statut présent dans le lien. L'effectif est indiqué entre parenthèses. |
| **Date VAL** | Dates de validation présentes dans le lien, **de la plus récente à la plus ancienne**. La liste est en cascade : elle ne montre que les dates du statut sélectionné, avec leur effectif. |
| **Statut synchro** | `INVALIDE`, `ABSENT`, `DIFFERENT`, `STR_SEUL`, `OK`. |
| **Recherche** | Recherche libre sur le n° de réservation, la famille, le niveau, le demandeur, le responsable et le commentaire de validation. |
| **Actionnables seulement** | Masque les lignes qui ne peuvent pas être synchronisées (`OK`, `STR_SEUL`). |
| **Réinitialiser** | Remet les quatre filtres à zéro. |
| **Cocher affichés** | Coche les lignes **actionnables actuellement visibles** — rien d'autre. |
| **Décocher affichés** | Décoche les lignes actuellement visibles. |

> **Cas d'usage principal** — traiter toutes les réservations validées d'une date de validation donnée :
> 1. `Statut VAL` → `VALIDE (772)`
> 2. `Date VAL` → `09/07/2026 (12)`
> 3. `Décocher affichés` puis `Cocher affichés` (pour partir d'une sélection propre)
> 4. Vérifier que le compteur indique bien `12 sélectionnée(s)` sans mention « hors filtre »
> 5. `Synchroniser`

Les filtres ne modifient **jamais** les cases à cocher : masquer une ligne ne la décoche pas. C'est pour cette raison que le compteur signale les coches hors filtre.

---

### 4.4 Le tableau de comparaison (DataGrid)

Le tableau liste **toutes les réservations concernées par une action** (ABSENT, DIFFERENT, INVALIDE, STR_SEUL). Les réservations déjà OK n'apparaissent pas par défaut.

Chaque ligne représente **une réservation identifiée par son numéro** `PVA_RES_DEM_NumReservation`.

La **case à cocher** en première colonne permet de sélectionner les lignes à synchroniser. Les en-têtes de colonnes sont cliquables pour trier ; les colonnes de dates sont triées chronologiquement, pas alphabétiquement.

---

### 4.5 Code couleur des lignes

| Couleur | Statut | Signification |
|---------|--------|--------------|
| 🟩 Vert | `ABSENT` | Présente dans le lien, absente de la STR — à copier |
| 🟧 Orange | `INVALIDE` | Présente dans la STR, validation retirée/refusée — à marquer Supprimé |
| 🟦 Bleu clair | `DIFFERENT` | Présente des deux côtés mais paramètres différents — à remplacer |
| ⬜ Blanc/gris | `STR_SEUL` | Dans la STR mais plus dans le lien — information |
| — | `OK` | Non affichée (tout va bien) |

> **Note couleurs** : une ligne verte `ABSENT VALIDE` est **copiable** (statut = VALIDE dans le lien). Une ligne verte `ABSENT REFUSÉ` n'est **pas** copiée (la synchro l'ignore).

---

### 4.6 Colonnes disponibles

Dans l'ordre d'affichage : le groupe validation (VAL, issu du lien SPV) d'abord, puis le groupe comparaison (STR).

| Colonne | Source | Description |
|---------|--------|-------------|
| ☑ | — | Case de sélection |
| **Statut VAL** | `PVA_RES_VAL_Statut` | `VALIDE` / `REFUSE` / vide |
| **Date VAL** | `PVA_RES_VAL_Date` | Date de validation — tri chronologique |
| **Commentaire VAL** | `PVA_RES_VAL_Commentaire` | Commentaire de validation |
| **Statut Synchro** | Calculé | `ABSENT` / `DIFFERENT` / `INVALIDE` / `STR_SEUL` / `OK` |
| **N° Réservation** | `PVA_RES_DEM_NumReservation` | Identifiant unique (ex. `15-707`) |
| **Famille** | Nom de famille Revit | `FGH_RES_V_RECT`, `FGH_RES_H_ROND`… |
| **Niveau** | `WSP_NiveauAssocie` | Niveau Revit associé |
| **Demandeur** | `PVA_RES_DEM_Demandeur` | Corps d'état demandeur |
| **Date dem.** | `PVA_RES_DEM_Date` | Date de la demande — tri chronologique |
| **RES Dem.** | `RES_Demandeur` | Responsable côté demandeur |
| **Responsable** | `RES_Responsable` | Responsable STR |
| **Détail / Différences** | Calculé | Explication textuelle du statut |

---

## 5. Les quatre cas de synchronisation

L'outil identifie automatiquement quatre situations, chacune déclenchant une action différente :

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    APPARIEMENT PAR N° DE RÉSERVATION                        │
│                                                                              │
│  Statut de validation = VALIDE                                               │
│    ├─ absent de la STR                              ──► CAS A (copier)      │
│    ├─ présent + params ≠ + DEM_Modifie = 1          ──► CAS B (remplacer)   │
│    └─ présent + params ≠ + DEM_Supprime = 1         ──► CAS C (marquer)     │
│                                                                              │
│  Statut de validation ≠ VALIDE (REFUSE, vide, …)                            │
│    └─ déjà présent dans la STR                      ──► CAS D (marquer)     │
│                                                                              │
│  Présent dans la STR, absent du lien                ──► STR_SEUL (aucune    │
│                                                          action possible)    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Cas A — Nouveaux à copier
- **Condition** : numéro présent dans le lien SPV, absent de la maquette STR, **statut VALIDE**, et `PVA_RES_DEM_Supprime` différent de 1 côté lien.
- **Action** : `CopyElements` de la géométrie + copie explicite des 14 paramètres partagés → sous-projet `03_STR_RESERVATIONS` → épinglage.
- **Écrit** : `PVA_RES_DEM_Nouveau = 1`, `PVA_RES_DEM_Modifie = 0` sur la copie.
- **Règle clé** : une réservation ABSENT REFUSÉ n'est **pas** copiée.

### Cas B — Modifiés à mettre à jour
- **Condition** : numéro présent dans les deux modèles, statut VALIDE, au moins un des huit paramètres comparés diffère, et `PVA_RES_DEM_Modifie = 1` côté lien.
- **Action** : copie du nouvel élément depuis le lien + marquage de l'ancienne version dans la STR.

### Cas C — Annulés par le demandeur
- **Condition** : numéro présent des deux côtés, statut VALIDE, paramètres divergents, et `PVA_RES_DEM_Supprime = 1` **côté lien**.
- **Action** : aucune copie ; l'élément STR est marqué.
- ⚠ Une réservation présente dans la STR mais **introuvable dans le lien** relève de `STR_SEUL`, pas du Cas C : elle n'est jamais synchronisable.

### Cas D — Validation retirée ou refusée
- **Condition** : élément déjà présent dans la STR dont le statut de validation ne vaut plus VALIDE (REFUSE, vide, ou toute autre valeur).
- **Action** : aucune copie ; l'élément STR est marqué.

### Ce que « marquer » veut dire, exactement
Pour les cas B (ancienne version), C et D, l'outil écrit sur l'élément de la maquette STR :

| Paramètre | Valeur écrite |
|-----------|--------------|
| `PVA_RES_VAL_Statut` | `SUPPRIMEE` — **c'est cette valeur, et elle seule, qui exclut l'élément de l'analyse au prochain lancement** |
| `PVA_RES_DEM_Modifie` | `0` |
| `PVA_RES_DEM_Nouveau` | `0` |
| `PVA_RES_DEM_Commentaire` | `Supprimé le : JJ/MM/AAAA` — ⚠ cette écriture **écrase** le commentaire du demandeur |

L'élément n'est **pas** effacé : il reste dans la maquette, épinglé, visible en vue 3D et sur les plans. Il n'est simplement plus comparé, ce qui fait repasser la liste Invalidées à 0 après synchro.

> Chaque cas ouvre sa propre transaction Revit (`STR - Sync Reservations Cas A`, `… Cas B`, etc.). Un Ctrl+Z annule donc **un cas à la fois**, pas la synchronisation entière.

---

## 6. Workflow pas à pas

### 6.1 Analyser le tableau

Dès l'ouverture de la fenêtre, lire les compteurs de la barre de statistiques :

```
Exemple de lecture typique :
  Absentes  : 4    → 4 nouvelles réservations VALIDE à intégrer (Cas A)
  Invalidées: 49   → 49 réservations dont la validation a été retirée (Cas D)
  Différentes: 0   → aucune mise à jour nécessaire
  OK        : 529  → 529 réservations déjà synchronisées
```

### [CAPTURE 1 — répétition ou zoom barre stats]
> Barre de statistiques montrant les compteurs avant la première synchronisation.

---

### 6.2 Filtrer et sélectionner

À l'ouverture, l'outil pré-coche ce qu'il traiterait : les lignes `INVALIDE` (Cas D) et les lignes `ABSENT` / `DIFFERENT` dont le statut de validation est `VALIDE`. Ce n'est qu'une proposition — c'est la sélection finale qui fait foi.

Méthode recommandée, par lot homogène :

1. **Décocher affichés** sans filtre actif, pour repartir de zéro.
2. Poser un filtre : par exemple `Statut VAL = VALIDE` + `Date VAL = 09/07/2026`, ou `Statut synchro = INVALIDE`.
3. **Cocher affichés**.
4. Contrôler le compteur : `12 sélectionnée(s)`. S'il indique `— dont N hors filtre`, des lignes cochées sont masquées et partiront quand même : lever le filtre pour les voir.
5. Synchroniser, puis recommencer avec le lot suivant.

> **Conseil** : travailler par type de cas. Un premier passage sur les `ABSENT`, vérifier le résultat dans Revit, puis les `INVALIDE`. Les lots par date de validation correspondent en général à une séance de coordination, ce qui rend le contrôle plus facile.

> La case **Actionnables seulement** masque les lignes `OK` et `STR_SEUL`, qui ne peuvent de toute façon pas être cochées.

---

### 6.3 Lancer la synchronisation

Cliquer le bouton **Synchroniser** (barre du bas, vert). Il est grisé et inactif tant qu'aucune ligne n'est cochée.

Une **boîte de confirmation** s'affiche avec le détail des actions :

### [CAPTURE 2 — Boîte de confirmation]
> **Ce que montre cette capture** : boîte de dialogue intitulée "Synchronisation : X élément(s) à traiter" listant les quatre cas :
> - Cas A - Nouveaux à copier : 4
> - Cas B - Modifiés à mettre à jour : 0
> - Cas C - à marquer supprimés : 0
> - Cas D - Validation retirée/refusée : 49
>
> Avec le texte : "Seules les réservations VALID sont copiées. Les Cas D seront marqués Supprimé dans la STR. Confirmer ?"

Lire attentivement les chiffres avant de cliquer **OK**.

> **Règle de sécurité** : si un chiffre semble anormal (ex. Cas C = 500 alors qu'il y en avait 0 avant), **annuler** et investiguer. La synchro ne supprime jamais physiquement d'éléments, mais marque beaucoup d'éléments Supprimé.

---

### 6.4 Lire le résumé de résultat

Après validation, la synchro s'exécute et affiche le résumé :

### [CAPTURE 3 — Boîte de résultat]
> **Ce que montre cette capture** : boîte de dialogue "Synchronisation terminée" :
> - Cas A - Nouveaux copiés : 4
> - Cas B - Modifiés copiés : 0
> - Cas B - Anciennes supprimées : 0
> - Cas C - Marqués supprimés : 0
> - Cas D - Invalides marqués supprimés : 49
>
> Total copiés : 4 | Total marqués : 49

---

### 6.5 Vérifier après synchro

Après fermeture du résumé, la fenêtre se rafraîchit automatiquement.

### [CAPTURE 4 — Interface après sync]
> **Ce que montre cette capture** : la fenêtre après synchronisation. La barre de statistiques affiche maintenant :
> - Invalidées : 0 (les 49 ont été traitées)
> - Absentes : 2 164 (dont les 4 Cas A qui apparaissent encore comme ABSENT)
> - Total hôte : 534 (584 − 49 − 1 = environ 534 selon filtre)
> - Barre de sélection : 4 sélectionnée(s)
>
> Les 4 lignes restantes ABSENT correspondent aux éléments copiés dont le paramètre NumReservation n'a pas encore été relu (problème résolu en v3.0.0 avec la copie explicite des paramètres).

**Points à contrôler** :

| Vérification | Résultat attendu |
|-------------|-----------------|
| Invalidées après sync | **0** |
| Absentes VALIDE après sync | Doit diminuer du nombre de Cas A traités |
| Éléments dans Revit (vue 3D) | Les nouveaux éléments sont épinglés (punaise) dans `03_STR_RESERVATIONS` |
| Sous-projet des copies | `03_STR_RESERVATIONS` |

---

## 7. Fonctions complémentaires

### 7.1 Vue 3D

Le bouton **Vue 3D** (violet) crée ou met à jour automatiquement une vue 3D nommée `STR_Reservations` :

1. Cocher une ou plusieurs lignes dans le tableau. La vue se cale sur les **lignes cochées**, filtre ou pas — comme la synchro.
2. Cliquer **Vue 3D**.
3. La vue s'ouvre avec une **zone de coupe (section box)** ajustée autour des éléments sélectionnés, avec une marge de 0,5 m.
4. Le gabarit de vue `3D_STR+RES` est appliqué automatiquement s'il existe dans le projet.

> **Usage typique** : sélectionner toutes les lignes ABSENT ou DIFFERENT, cliquer Vue 3D pour voir les zones concernées avant de synchroniser.

---

### 7.2 Export CSV

Le bouton **Exporter CSV** (orange) génère un fichier CSV avec les lignes **actuellement affichées** — le filtre en place s'applique donc aussi à l'export. Le message de fin rappelle combien de lignes ont été écrites sur le total.

- Format : `StatutVAL;StatutSTR;Numero;Famille;Niveau;Demandeur;DateDem;RESDem;Responsable;DateVal;CommentaireVAL;Detail`
- Encodage : UTF-8 avec BOM (compatible Excel)
- Emplacement : le **Bureau** de l'utilisateur, sous le nom `STR_Reservations_Analyse_AAAAMMJJ_HHMM.csv`. L'horodatage évite d'écraser l'export précédent.

> **Usage typique** : exporter avant de synchroniser pour garder une trace de l'état avant/après. Combiné aux filtres, permet de sortir la liste des réservations validées d'une séance donnée pour la réunion de coordination.

---

## 8. Règles métier importantes

### Seules les VALIDE sont copiées
Une réservation dont le statut de validation ne signifie pas `VALIDE` n'est **jamais** copiée dans la STR, même si elle est cochée et classée ABSENT.

```
Statut lien   │  Action Cas A
──────────────┼──────────────
VALIDE        │  Copie + paramètres
REFUSE        │  Ignorée (ligne affichée mais non copiée)
vide          │  Ignorée
INVALIDE      │  Ignorée
NON VALIDE    │  Ignorée
```

> **Corrigé en v3.1.0** : le test se faisait sur la présence de la sous-chaîne `VALID`. Or `INVALIDE` et `NON VALIDE` la contiennent aussi — ces réservations étaient donc traitées comme validées et copiées dans la STR. Le test exclut désormais explicitement les formes négatives.

### Les éléments ne sont jamais effacés
L'outil ne supprime **jamais** physiquement d'élément Revit. Il écrit `SUPPRIMEE` dans `PVA_RES_VAL_Statut`, ce qui exclut l'élément des analyses suivantes sans le retirer de la maquette. L'effacement réel, si nécessaire, se fait manuellement ou via l'outil **Purge Réservations**.

### Copie géométrie + paramètres
Depuis la v3.0.0, la copie d'un élément depuis le lien inclut :
- la **géométrie** (via `ElementTransformUtils.CopyElements`) ;
- **tous les paramètres partagés** : numéro, demandeur, date, niveau, coordonnées, statut de validation, commentaires, etc.

Sans ce transfert explicite, les éléments copiés n'auraient pas de numéro et resteraient ABSENT à la prochaine ouverture, générant des doublons.

### Familles : le nom doit commencer par `FGH_RES`
L'outil ne reconnaît que les familles dont le **nom commence par `FGH_RES`**. Si une famille est renommée lors du chargement (ex. `FGH_RES_V_RECT3` → `STR_RES_V_RECT`), elle devient **invisible** pour l'outil et ses éléments n'apparaissent pas dans le tableau.

> ⚠ **Vigilance** : toujours charger les familles depuis le fichier source SPV sans renommer. Si la famille a été chargée sous un autre nom, la purger et recharger avec le bon nom.

### Épinglage automatique
Tous les éléments copiés sont **épinglés** (pin Revit) dans la STR. Cela empêche leur déplacement ou suppression accidentelle. Pour déplacer ou supprimer un élément copié, il faut d'abord le désépingler manuellement.

---

## 9. Erreurs fréquentes et solutions

### ❌ "Aucune maquette liée dont le nom contient 'FGH_RES_SPV' n'a été trouvée"

**Cause** : le lien Revit n'est pas chargé ou son nom ne correspond pas au préfixe attendu.

**Solution** :
1. Gérer › Liens Revit → vérifier que le lien SPV est chargé (statut = Chargé).
2. Vérifier que le nom du fichier RVT lié contient bien `FGH_RES_SPV`.

---

### ❌ Les éléments Cas A restent ABSENT après sync

**Cause probable** : le paramètre `PVA_RES_DEM_NumReservation` n'a pas été copié.

**Ce qui se passe en v3.0.0** : la copie des paramètres est effectuée automatiquement après chaque `CopyElements`. Si des doublons s'accumulent dans la maquette, c'est un symptôme d'une version antérieure à v3.0.0.

**Solution** : passer en v3.0.0 ou ultérieure. Nettoyer manuellement les doublons en vue 3D (filtrer par famille, vérifier les épinglés sans numéro).

---

### ❌ Les Invalidées repassent à un chiffre élevé à chaque ouverture

**Cause** : une version antérieure à la correction Option A collectait les éléments marqués Supprimé dans la maquette hôte, les reclassait comme INVALIDE, et relançait la boucle.

**Solution** : passer en v3.0.0 ou ultérieure. La collecte hôte exclut désormais les éléments dont `PVA_RES_VAL_Statut` vaut `SUPPRIMEE`.

---

### ❌ "⚠ AVERTISSEMENT : le sous-projet '03_STR_RESERVATIONS' est introuvable"

**Cause** : le sous-projet n'existe pas encore dans la maquette STR.

**Solution** :
1. Gérer › Sous-projets → créer le sous-projet `03_STR_RESERVATIONS`.
2. Relancer la sync.

Les éléments déjà copiés dans le mauvais sous-projet doivent être déplacés manuellement (sélectionner, Propriétés, changer le sous-projet).

---

### ❌ Les éléments copiés ont les mauvais paramètres (valeurs mélangées)

**Cause** : lors de la copie, Revit peut réordonnancer les `ElementId` retournés par `CopyElements` si les familles source et destination ne sont pas strictement identiques (version, paramètres intégrés différents). L'outil appariait alors la copie n° 1 avec la source n° 1, la copie n° 2 avec la source n° 2, etc. — un décalage suffisait à écrire les paramètres d'une réservation sur une autre.

**Indicateur** : dans le diagnostic, on voit `src='15-707' → dst='15-513'` (numéros non correspondants).

**Ce qui se passe en v3.1.0** : l'appariement se fait par n° de réservation quand le paramètre a survécu à la copie, et ne retombe sur l'ordre positionnel que si aucun numéro n'est exploitable. L'ordre de retour de Revit n'a donc plus d'incidence.

**Solution complémentaire** : vérifier que la famille chargée dans la STR est **exactement la même version** que dans le SPV. Purger la famille STR et recharger depuis la source SPV.

---

### ⚠ « Contrôle des N° de réservation » à l'ouverture

**Cause** : l'outil indexe les réservations par `PVA_RES_DEM_NumReservation`. Deux éléments portant le même numéro s'écrasent mutuellement dans l'index (seul le dernier rencontré est comparé), et un élément sans numéro est purement ignoré. Ce message signale la situation avant la comparaison — il n'y a **aucun** blocage, l'analyse se poursuit.

**Solution** : corriger les numéros côté SPV, ou identifier les éléments concernés via la recherche libre de la barre de filtres. Un doublon dans la maquette STR provient en général d'un ancien élément copié dont le numéro n'a pas été transféré (bug antérieur à la v3.0.0).

---

## 10. Points de vigilance — Administration

### Familles sources
Les familles `FGH_RES*` doivent être chargées dans la maquette STR **depuis les fichiers .rfa du projet**, jamais depuis une maquette différente (risque de renommage automatique par Revit).

### Déploiement de l'extension
L'extension STR BIM Tools se déploie en copiant le dossier dans :

```
%APPDATA%\pyRevit-Master\extensions\STR Bim Tools.extension\
```

Ce chemin est valide pour **tout utilisateur Windows**, quel que soit son nom de session, grâce à la variable d'environnement `%APPDATA%`.

### Mise à jour de l'outil
Pour mettre à jour uniquement le script :

```
Remplacer les fichiers :
%APPDATA%\pyRevit-Master\extensions\STR Bim Tools.extension\
  STR Bim Tools.tab\Base.panel\FGH.pulldown\
  Transfert Reservations.pushbutton\script.py
  Transfert Reservations.pushbutton\bundle.yaml
```

Puis recharger pyRevit : **pyRevit › Reload** (ou utiliser le bouton Reload de l'onglet STR BIM Tools).

> Depuis la v3.1.0, le titre du bouton, l'infobulle et le numéro de version sont déclarés dans `bundle.yaml` et non plus dans `script.py`. Les deux fichiers doivent être déployés ensemble, et `version:` du `bundle.yaml` doit rester synchronisé avec `SCRIPT_VERSION` du script.

### Version actuelle

`v3.1.0` :
- Barre de filtres en haut de la fenêtre : statut de validation, date de validation en cascade avec effectifs, statut de synchronisation, recherche libre, « Actionnables seulement »
- `Cocher / Décocher affichés` remplacent `Tout cocher / Tout décocher` et n'agissent que sur les lignes visibles
- Compteur `Affichées : x / y` et signalement des coches masquées par un filtre
- Correction : `INVALIDE` et `NON VALIDE` ne sont plus interprétés comme validés
- Correction : appariement source ↔ copie par n° de réservation au lieu de l'ordre de retour de `CopyElements`
- Contrôle des N° en doublon et des éléments sans N° au lancement
- Export CSV limité à la vue filtrée, nom de fichier horodaté
- Filet de sécurité `TaskDialog` sur les erreurs de chargement et d'exécution
- `bundle.yaml` : titre, infobulle et version sortis du script

`v3.0.0` :
- Workset : utilisation de `.IntegerValue` pour l'assignation au sous-projet
- Option A : exclusion des éléments Supprimé de la collecte hôte (fin de la boucle infinie Invalidées)
- Copie explicite des paramètres partagés après `CopyElements` (fin des doublons sans numéro)
- Transactions vides supprimées de la pile Annuler
- Conformité STR BIM Tools v1 : footer, couleur bouton Export, docstrings

---

*Document créé le 28/05/2026, mis à jour le 11/08/2026 — STR BIM Tools v3.1.0*
