# Tutoriel — Outil Sync Réservations
## STR BIM Tools · v3.0.0 · Tony VARIN

---

> **Comment utiliser ce document**
> Les marqueurs `[CAPTURE X]` indiquent l'emplacement des captures d'écran à coller depuis le chat de session.
> Chaque marqueur est accompagné d'une description de ce que montre la capture.

---

## Table des matières

1. [Contexte et objectif](#1-contexte-et-objectif)
2. [Prérequis avant lancement](#2-prérequis-avant-lancement)
3. [Lancement de l'outil](#3-lancement-de-loutil)
4. [Lecture de l'interface principale](#4-lecture-de-linterface-principale)
   - 4.1 Barre de titre
   - 4.2 Barre de statistiques
   - 4.3 Le tableau de comparaison (DataGrid)
   - 4.4 Code couleur des lignes
   - 4.5 Colonnes disponibles
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
> **Ce que montre cette capture** : la fenêtre principale après analyse, avec le tableau de comparaison. La barre de titre indique `Reservations RES vs STR [v3.0.0]`. La barre de statistiques montre VALIDE : 533, REFUSÉ : 226, Absentes : 2 115, Invalidées : 49, OK : 529, STR seul : 5, Total lien : 2 768, Total hôte : 584. Le tableau affiche des lignes orangées (INVALIDE) et vertes (ABSENT VALIDE). La barre de sélection indique `53 sélectionnée(s)`.

---

### 4.1 Barre de titre

```
Reservations RES vs STR [v3.0.0]
Comparaison Réservations — STR (584 él.) vs SPV/FGH_RES_SPV_... (2768 él.)
```

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

> **Lecture rapide** : à l'ouverture, les chiffres clés à surveiller sont **Absentes** (Cas A — à copier), **Invalidées** (Cas D — à purger) et **⚠ Différentes** (Cas B — à mettre à jour).

---

### 4.3 Le tableau de comparaison (DataGrid)

Le tableau liste **toutes les réservations concernées par une action** (ABSENT, DIFFERENT, INVALIDE, STR_SEUL). Les réservations déjà OK n'apparaissent pas par défaut.

Chaque ligne représente **une réservation identifiée par son numéro** `PVA_RES_DEM_NumReservation`.

La **case à cocher** en première colonne permet de sélectionner les lignes à synchroniser. Les boutons **Tout cocher / Tout décocher** agissent sur le filtrage actif.

---

### 4.4 Code couleur des lignes

| Couleur | Statut | Signification |
|---------|--------|--------------|
| 🟩 Vert | `ABSENT` | Présente dans le lien, absente de la STR — à copier |
| 🟧 Orange | `INVALIDE` | Présente dans la STR, validation retirée/refusée — à marquer Supprimé |
| 🟦 Bleu clair | `DIFFERENT` | Présente des deux côtés mais paramètres différents — à remplacer |
| ⬜ Blanc/gris | `STR_SEUL` | Dans la STR mais plus dans le lien — information |
| — | `OK` | Non affichée (tout va bien) |

> **Note couleurs** : une ligne verte `ABSENT VALIDE` est **copiable** (statut = VALIDE dans le lien). Une ligne verte `ABSENT REFUSÉ` n'est **pas** copiée (la synchro l'ignore).

---

### 4.5 Colonnes disponibles

| Colonne | Source | Description |
|---------|--------|-------------|
| ☑ | — | Case de sélection |
| **Statut VAL** | Lien SPV | `VALIDE` / `REFUSE` / vide |
| **Statut Synchro** | Calculé | `ABSENT` / `DIFFERENT` / `INVALIDE` / `STR_SEUL` / `OK` |
| **N° Réservation** | `PVA_RES_DEM_NumReservation` | Identifiant unique (ex. `15-707`) |
| **Famille** | Nom de famille Revit | `FGH_RES_V_RECT`, `FGH_RES_H_ROND`… |
| **Niveau** | `WSP_NiveauAssocie` | Niveau Revit associé |
| **Demandeur** | `PVA_RES_DEM_Demandeur` | Corps d'état demandeur |
| **Date dem.** | `PVA_RES_DEM_Date` | Date de la demande |
| **RES Dem.** | `RES_Demandeur` | Responsable côté demandeur |
| **Responsable** | `RES_Responsable` | Responsable STR |
| **Date VAL** | `PVA_RES_VAL_Date` | Date de validation |
| **Commentaire VAL** | `PVA_RES_VAL_Commentaire` | Commentaire de validation |
| **Détail / Différences** | Calculé | Explication textuelle du statut |

---

## 5. Les quatre cas de synchronisation

L'outil identifie automatiquement quatre situations, chacune déclenchant une action différente :

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        COMPARAISON PAR NUMÉRO                          │
│                                                                         │
│  Lien SPV ────┐                                                         │
│               ├──► Absent de la STR + Statut VALIDE  ──► CAS A (copier)│
│               ├──► Présent dans STR, paramètres ≠     ──► CAS B (màj)  │
│               └──► Plus dans le lien                  ──► CAS C (marq) │
│                                                                         │
│  STR hôte ───► Présent + Statut devenu INVALIDE/vide  ──► CAS D (marq) │
└─────────────────────────────────────────────────────────────────────────┘
```

### Cas A — Nouveaux à copier
- **Condition** : numéro présent dans le lien SPV, absent de la maquette STR, **statut VALIDE**.
- **Action** : `CopyElements` de la géométrie + copie explicite de tous les paramètres partagés → placement dans le sous-projet `03_STR_RESERVATIONS` → épinglage.
- **Règle clé** : une réservation ABSENT REFUSÉ n'est **pas** copiée.

### Cas B — Modifiés à mettre à jour
- **Condition** : numéro présent dans les deux modèles, mais au moins un paramètre diffère (géométrie, niveau, demandeur…).
- **Action** : copie du nouvel élément depuis le lien + marquage Supprimé de l'ancienne version dans la STR.

### Cas C — Supprimés côté SPV
- **Condition** : numéro présent dans la STR mais introuvable dans le lien.
- **Action** : marquage `PVA_RES_DEM_Supprime = 1` dans la STR (l'élément n'est **pas** effacé physiquement).

### Cas D — Validation retirée ou refusée
- **Condition** : élément présent dans la STR avec un statut de validation qui est passé de VALIDE à REFUSE ou vide.
- **Action** : marquage `PVA_RES_DEM_Supprime = 1` + effacement du statut de validation.
- **Règle clé** : les éléments marqués Supprimé sont **exclus** de la collecte à la prochaine ouverture → la liste Invalidées repasse à 0 après synchro.

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

- Cliquer **Tout cocher** pour sélectionner toutes les lignes visibles.
- Ou cocher manuellement les lignes à traiter.
- La barre inférieure affiche en temps réel : `53 sélectionnée(s)`.

> **Conseil** : travailler par type de cas. Cocher uniquement les ABSENT un premier passage, vérifier, puis les INVALIDE.

---

### 6.3 Lancer la synchronisation

Cliquer le bouton **Synchroniser** (barre du bas, bleu).

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

Le bouton **Vue 3D** (vert) crée ou met à jour automatiquement une vue 3D nommée `STR_Reservations` :

1. Sélectionner une ou plusieurs lignes dans le tableau (éléments avec un local existant dans la STR).
2. Cliquer **Vue 3D**.
3. La vue s'ouvre avec une **zone de coupe (section box)** ajustée autour des éléments sélectionnés, avec une marge de 0,5 m.
4. Le gabarit de vue `3D_STR+RES` est appliqué automatiquement s'il existe dans le projet.

> **Usage typique** : sélectionner toutes les lignes ABSENT ou DIFFERENT, cliquer Vue 3D pour voir les zones concernées avant de synchroniser.

---

### 7.2 Export CSV

Le bouton **Exporter CSV** (orange) génère un fichier CSV avec toutes les lignes du tableau.

- Format : `StatutVAL;StatutSTR;Numero;Famille;Niveau;Demandeur;DateDem;RESDem;Responsable;DateVal;CommentaireVAL;Detail`
- Encodage : UTF-8 avec BOM (compatible Excel)
- L'emplacement du fichier est demandé via une boîte de dialogue standard Windows.

> **Usage typique** : exporter avant de synchroniser pour garder une trace de l'état avant/après. Utile pour les réunions de coordination.

---

## 8. Règles métier importantes

### Seules les VALIDE sont copiées
Une réservation dont le statut de validation n'est pas exactement `VALIDE` n'est **jamais** copiée dans la STR, même si elle est cochée et classée ABSENT.

```
Statut lien  │  Action Cas A
─────────────┼──────────────
VALIDE        │  Copie + paramètres
REFUSE        │  Ignorée (ligne affichée mais non copiée)
vide          │  Ignorée
```

### Les éléments ne sont jamais effacés
L'outil ne supprime **jamais** physiquement d'élément Revit. Il positionne uniquement le paramètre `PVA_RES_DEM_Supprime = 1`. L'effacement réel, si nécessaire, se fait manuellement.

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

**Solution** : passer en v3.0.0. Nettoyer manuellement les doublons en vue 3D (filtrer par famille, vérifier les épinglés sans numéro).

---

### ❌ Les Invalidées repassent à un chiffre élevé à chaque ouverture

**Cause** : une version antérieure à la correction Option A collectait les éléments marqués Supprimé dans la maquette hôte, les reclassait comme INVALIDE, et relançait la boucle.

**Solution** : passer en v3.0.0. La collecte hôte exclut désormais les éléments avec `PVA_RES_DEM_Supprime = 1`.

---

### ❌ "⚠ AVERTISSEMENT : le sous-projet '03_STR_RESERVATIONS' est introuvable"

**Cause** : le sous-projet n'existe pas encore dans la maquette STR.

**Solution** :
1. Gérer › Sous-projets → créer le sous-projet `03_STR_RESERVATIONS`.
2. Relancer la sync.

Les éléments déjà copiés dans le mauvais sous-projet doivent être déplacés manuellement (sélectionner, Propriétés, changer le sous-projet).

---

### ❌ Les éléments copiés ont les mauvais paramètres (valeurs mélangées)

**Cause** : lors de la copie, Revit peut réordonnancer les `ElementId` retournés par `CopyElements` si les familles source et destination ne sont pas strictement identiques (version, paramètres intégrés différents).

**Indicateur** : dans le diagnostic, on voit `src='15-707' → dst='15-513'` (numéros non correspondants).

**Solution** : vérifier que la famille chargée dans la STR est **exactement la même version** que dans le SPV. Purger la famille STR et recharger depuis la source SPV.

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
Remplacer le fichier :
%APPDATA%\pyRevit-Master\extensions\STR Bim Tools.extension\
  STR Bim Tools.tab\Base.panel\FGH.pulldown\
  Transfert_reservations.pushbutton\script.py
```

Puis recharger pyRevit : **pyRevit › Reload** (ou utiliser le bouton Reload de l'onglet STR BIM Tools).

### Version actuelle
`v3.0.0` — corrections incluses :
- Workset : utilisation de `.IntegerValue` pour l'assignation au sous-projet
- Option A : exclusion des éléments Supprimé de la collecte hôte (fin de la boucle infinie Invalidées)
- Copie explicite des paramètres partagés après `CopyElements` (fin des doublons sans numéro)
- Transactions vides supprimées de la pile Annuler
- Conformité STR BIM Tools v1 : footer, couleur bouton Export, docstrings

---

*Document généré le 28/05/2026 — STR BIM Tools v3.0.0*
