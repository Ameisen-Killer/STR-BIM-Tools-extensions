# FGH — Règles BEP applicables à la maquette STR (AB Ingénieurs)

Source : `FGH_BIM_SPV_51_CDC_000_NNA_0001_01_BIM Execution Plan V014.pdf` (V01.4, 30.06.2026, SPVA).
Référentiel destiné à cadrer l'outil de contrôle de conformité de la maquette STR.

Colonne **Auto** : `OUI` = contrôlable par script dans Revit / `PART` = partiellement / `NON` = procédural, hors outil.

---

## A. Identité de la maquette et du fichier

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| A01 | Nom de MN = `FGH_STR_ABI_51_MOD_<Découpage>_<Zone>_R24_<Statut>` (A_Projet, B_Discipline, C_Émetteur, D_Phase SIA, E_Type doc, F_Découpage, G_Zone coord., H_Type/version fichier, I_Statut) | §2.7 | OUI |
| A02 | B = `STR` (structure/génie civil) ; C = `ABI` (AB Ingénieurs) ; D = `51`/`52`/`53` ; E = `MOD` ; H = `R24` ; I = `T`/`V`/`R` | §2.7 | OUI |
| A03 | F_Découpage parmi : AMI, AMX, ENV, FAC, GEN, HOT, PIE, PLT, SOC, SOU, H01..H0x, TTD | §2.7 | OUI |
| A04 | G_Zone de coordination parmi la liste Zxx / TTZ du BEP | §2.7, §3.3.5 | OUI |
| A05 | Version Revit 2024 (R24) imposée ; tout changement de version soumis à accord écrit de la cellule BIM | §4.1.2 | OUI |
| A06 | Taille de fichier ≤ 350 Mo (natif comme IFC) | §4.2 | OUI |

## B. Géoréférencement, niveaux, quadrillages

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| B01 | Coordonnées partagées de la MN IMP importées obligatoirement dans la MN STR | §3.3.1 | PART |
| B02 | Point topographique : X 2500600.0000 / Y 1118400.0000 / Z 374.2100 (MN95) | §3.3.1 | OUI |
| B03 | Point de base projet : X 2500599.3589 / Y 1118404.4675 / Z 374.21 ; angle au Nord géographique 308.5047886° | §3.3.1 | OUI |
| B04 | Cube de repérage `SPV_IMP_RepereImplantationMN.rfa` présent et implanté dans la MN | §3.3.2 | OUI |
| B05 | Niveaux copiés/contrôlés depuis la MN IMP, noms et altitudes exacts (voir tables ci-dessous) | §3.3.3 | OUI |
| B06 | Aucun niveau supplémentaire (demi-niveaux, arases) sans validation écrite de la cellule BIM | §3.3.3 | OUI |
| B07 | Tous les objets rattachés à un étage fini de la liste (pas de niveau hors liste) | §3.3.3, §3.4.1 | OUI |
| B08 | Quadrillages présents et conformes à la MN IMP (copiés/contrôlés) | §3.3.4 | PART |

### Niveaux imposés — bâtiment FGH

| Code | Nom étage | Altitude MN95 |
|------|-----------|---------------|
| FGH_060 | FGH S3 (Sous-sol 3) | 362.010 (en cours de calage) |
| FGH_070 | FGH_S2 (Sous-sol 2) | 364.860 |
| FGH_080 | FGH_S1 (Sous-sol 1) | 367.700 |
| FGH_090 | FGH_GF_INF (RDC inférieur) | 370.480 |
| FGH_100 | FGH_GF (Rez de Chaussée) | 374.210 |
| FGH_110 | FGH_N1 (Etage 1) | 377.450 |
| FGH_120 | FGH_N2 (Etage 2) | 380.850 |
| FGH_130 | FGH_N3 (Etage 3) | 384.470 |
| FGH_140 | FGH_N4 (Etage 4) | 387.310 |
| FGH_150 | FGH_N5 (Etage 5) | 390.160 |
| FGH_160 | FGH_N6 (Etage 6) | 393.010 |
| FGH_170 | FGH_N7 (Etage 7) | 395.860 |
| FGH_180 | FGH_N8 (Etage 8) | 398.700 |
| FGH_190 | FGH_N9 (Etage 9) | 401.030 |
| 0.00 | 0.00 — **absent du BEP**, présent dans la maquette de référence | 374.210 |
| TOITURE | TOITURE — **absent du BEP**, présent dans la maquette de référence | 402.010 |

> Les deux derniers niveaux sont un oubli du tableau du BEP : ils existent dans la maquette IMP. L'outil les accepte (`"tolere": true` dans le référentiel), contrôle leur altitude s'ils sont présents, et ne reproche pas leur absence. À faire corriger dans la prochaine version du BEP.

### Niveaux imposés — bâtiment Plantamour

| Code | Nom étage | Altitude MN95 |
|------|-----------|---------------|
| PLT_050 | PLT_S4 (Sous-sol 4) | 360.730 |
| PLT_060 | PLT_S3 (Sous-sol 3) | 363.280 |
| PLT_070 | PLT_S2 (Sous-sol 2) | 365.850 |
| PLT_080 | PLT_S1 (Sous-sol 1) | 368.410 |
| PLT_090 | PLT_GF_INF (RDC inférieur) | 370.960 |
| PLT_100 | PLT_GF (RDC) | 374.150 |
| PLT_110 | PLT_N1 (Etage 1) | 377.430 |
| PLT_120 | PLT_N2 (Etage 2) | 380.330 |
| PLT_130 | PLT_N3 (Etage 3) | 383.430 |
| PLT_140 | PLT_N4 (Etage 4) | 386.710 |
| PLT_150 | PLT_N5 (Etage 5) | 390.000 |
| PLT_160 | PLT_N6 (Etage 6) | 392.920 |

## C. Structuration par sous-projets

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| C01 | Sous-projets géomètre copiés/contrôlés avec préfixe de spécialité : axes, cube de référence, niveaux | §3.1.2.1 | OUI |
| C02 | Liens dans des sous-projets `01_LIEN_MN <spécialité>` (un par maquette liée) | §3.1.2.2 | OUI |
| C03 | Sous-projets dédiés : `02_VOLUMES_EXCLUSION`, `02_GABARITS_PASSAGE`, `02_ZONES_COORDINATION` | §3.1.2.3 | OUI |
| C04 | Sous-projets de travail nommés `03_STR_<Contenu>` (ex. `03_STR_FONDATIONS`) | §3.1.2.4 | OUI |
| C05 | Aucun élément dans le sous-projet par défaut ; tout élément dans une couche déclarée | §3.4.2 | OUI |
| C06 | Structuration par couches déclarée à la cellule BIM en début de projet | §3.4.2 | NON |

## D. Nommage et jeu de caractères

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| D01 | Tout nom d'objet BIM (famille, type, matériau, paramètre, sous-projet, vue, feuille) commence par le trigramme de spécialité : `STR_...` | §3.1.1 | OUI |
| D02 | Caractères autorisés uniquement : `A-Z`, `a-z`, `0-9`, `_` | §2.10 | OUI |
| D03 | Interdits : espace, accents (à é è ü û â ô), et les caractères spéciaux `- + * / ( ) @ % & = . , ; ! " £ $ ^ { } [ ] < > ? \| \ ' ~ #` | §2.10, §3.1.1 | OUI |
| D04 | Seul séparateur admis : `_` | §2.10 | OUI |
| D05 | Toutes les informations en français et univoques | §3.1.1 | NON |
| D06 | Matériaux préfixés `STR_` (ex. `STR_BET4`) | §3.1.1 | OUI |

> Contradiction interne du BEP : §3.1.1 autorise le tiret `-` (« requis par la CDE Kairnial ») alors que §2.10 l'interdit explicitement. La codification des livrables (§2.11.4) utilise elle-même le tiret comme séparateur. À trancher avec la cellule BIM.

## E. Attributs / LOI

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| E01 | `PVA_ALL_Zone` renseigné sur **tous** les objets de la MN, valeur = Zxx / TTZ de la liste | §3.3.5 | OUI |
| E02 | `PVA_ALL_InfraSuper` = `Infra` / `Super` (référence : fibre supérieure de la dalle sur S1) | §3.2.2 | OUI |
| E03 | `PVA_ALL_Etage` = nom du niveau | §3.2.2 | OUI |
| E04 | `PVA_ALL_Eccc_Bât` = valeur eCCC-Bât (format `X0x.0x`) | §3.2.2 | OUI |
| E05 | `PVA_ALL_CFC` = valeur CFC (format `CFCXXX.X`) | §3.2.2 | OUI |
| E06 | `PVA_ALL_Nom_type` = nom du type | §3.2.2 | OUI |
| E07 | `PVA_ALL_Phase` = `Nouvelle construction` / `existant` / `démoli` | §3.2.2 | OUI |
| E08 | `PVA_ALL_Resistance_feu` = `EI30` / `EI60` / `EI90`… sur les porteurs | §3.2.2, §3.4.8.3 | OUI |
| E09 | Objets de modification : `PVA_MOD_Numero`, `PVA_MOD_Nom`, `PVA_MOD_Date`, `PVA_MOD_Statut` (`Ouvert`/`en cours`/`Validé`) + nomenclature dédiée dans la MN | §4.5 | OUI |
| E10 | Les familles RFA ne contiennent que les attributs nécessaires au projet, nommés en français | §3.4.8.1 | PART |
| E11 | LOI conforme au tableau annexe par élément et par phase SIA ; toute déviation validée par écrit | §3.2.2, §3.4.8.1 | NON (annexe non fournie) |

## F. Règles de modélisation STR

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| F01 | **Tous** les éléments porteurs portent la capacité structurelle dans le paramètre IFC `LoadBearing` | §3.4.8.3 | OUI |
| F02 | Les éléments porteurs ne sont pas dupliqués dans les autres maquettes (ARC notamment) | §3.4.8.3, §3.4.8.1 | NON (inter-maquettes) |
| F03 | Volumes d'exclusion de percement modélisés (contraintes parasismiques, têtes de poinçonnement…) | §3.4.8.3 | PART |
| F04 | Porteurs renseignés en **réaction** et **résistance** au feu | §3.4.8.3 | OUI |
| F05 | Plans d'armature non extraits de la MN, mais liés à la MN aux étapes d'archivage (MNR) | §3.4.8.3 | NON |
| F06 | Classification IFC obligatoire — **modèles génériques interdits** sauf accord écrit (pas d'`IfcBuildingElementProxy` ; attention aux DirectShape et familles Modèle générique) | §3.4.8.1 | OUI |
| F07 | Modélisation réaliste : éléments modélisés tels que construits, murs de dalle à dalle sans les traverser | §3.4.3 | PART |
| F08 | Éléments, surfaces et volumes séparés par étage ; colonnes montantes prennent les propriétés du point bas | §3.4.1 | OUI |
| F09 | Exhaustivité : tous les ouvrages nécessaires à la réalisation du lot, y compris volumes d'exclusion et supportages | §3.4.4 | NON |
| F10 | Unités du modèle : longueur **cm**, surface **m²**, volume **m³**, angle **°** | §3.4.7 | OUI |
| F11 | Modélisation à l'échelle 1:1 | §3.4.7 | OUI |
| F12 | Prise en lien de la MN PIE et cohérence des éléments avec les pièces/espaces | §3.4.8.5 | PART |
| F13 | MN livrée **sans collision interne** | §4.3.2 | PART |
| F14 | MN as-built mise à jour dans les 2 semaines suivant l'exécution (si sans impact coordination) | §3.4.5 | NON |

## G. Réservations / percements (rôle de validateur STR)

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| G01 | Numérotation `<NumMandataire>-<compteur>`. STR_ABI = **02** donc `02-001`… Unicité obligatoire | §3.06.2 | OUI |
| G02 | Paramètres de demande : `PVA_RES_DEM_Demandeur`, `_Date`, `_Statut` (Nouveau/Modifié/Supprimé), `_Hauteur`, `_Largeur`, `_Profondeur`, `_Diametre`, `_Carotage`, `_Calfeutrement`, `_Commentaire`, `_PercSTR`, `_PercARC`, `_NumMandataire`, `_NumPercement` | §3.06.1-2 | OUI |
| G03 | Paramètres de validation à remplir par l'ingénieur civil : `PVA_RES_VAL_Date`, `PVA_RES_VAL_Statut` (Refusé/Validé/En cours), `PVA_RES_VAL_Commentaire` | §3.06.03 | OUI |
| G04 | Toute demande dont `PercSTR = Oui` doit avoir un statut de validation non vide au moment du dépôt | §3.06.03 | OUI |
| G05 | Les demandes ne sont soumises qu'après résolution des clashs de la zone | §3.06.1 | NON |

> Les outils du pulldown `FGH` couvrent déjà une partie de ce bloc (Doublons Réservations, Transfert, Purge, Recherche).

## H. Vues, feuilles et livrables

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| H01 | Tous les livrables extraits de la MN ; plans conformes à la norme SIA 400 | §2.11.4 | PART |
| H02 | Codification livrable : `FGH-STR-ABI-<PhaseSIA>-<Type>-<CodeEtage>-<Zone>-<Numéro>-<Indice>_<Titre>` | §2.11.4 | OUI (paramètres `SPVA_GED_A`…`H` déjà présents sur les feuilles) |
| H03 | E_Type de document parmi la liste BEP (`PLA`, `CPE`, `ELV`, `DET`, `ARM`, `NDC`, `LIS`, `SCH`, `TAB`, `MOD`…) | §2.11.4 | OUI |
| H04 | F_Code étage : 3 chiffres (`000` tous niveaux, `050` à `190`) | §2.11.4 | OUI |
| H05 | G_Zone impression : `A00`, `B00`, `A01` à `A04`, `TTZ`, `NNA`, ou `Zxx` | §2.11.4 | OUI |
| H06 | H_Numéro livrable : 4 chiffres ; I_Indice de révision : 2 chiffres (`00` = 1ère publication) | §2.11.4 | OUI |
| H07 | La liste des livrables doit exister dans la MN sous forme de **nomenclatures de vues et de feuilles** portant les mêmes attributs | §2.11.4 | OUI |
| H08 | Étiquettes et annotations obligatoirement basées sur les attributs des éléments — **toute information saisie manuellement est interdite** sur les plans extraits | §3.4.8.1 | OUI |

## I. Export et dépôt

| ID | Règle | Réf. | Auto |
|----|-------|------|------|
| I01 | Dépôt au minimum au format natif `.rvt` **et** `.ifc` (IFC **4**), `.nwc` si demandé | §2.8.1, §4.1.1 | PART |
| I02 | Fréquence minimale de dépôt : 1x/semaine pour les fichiers TTZ ; « aussi souvent que nécessaire » par zone | §2.8.1 | NON |
| I03 | Toute MN déposée avec sa **fiche de conformité** remplie, sinon non prise en compte | §3.4.10, §4.3.5 | NON |
| I04 | Contrôle interne obligatoire avant chaque dépôt : avancement, conformité BEP, absence de collisions internes | §4.3.1 | PART |
| I05 | Non-conformités relevées par la cellule BIM à corriger sous 4 jours ouvrés | §4.3.5 | NON |
| I06 | Collaboration sur les problèmes au format BCF v2.1 | §4.1.1 | NON |
| I07 | Documents intégrés à la MN (LOP) fournis en format natif au dépôt, dans leur dernière version | §3.2.4 | NON |
| I08 | Une fois la MN passée MIV (validée) : aucune modification hors demande de la cellule BIM ou processus de modification | §4.3.3, §4.5 | NON |
| I09 | Extractions (plans, quantités) réalisées impérativement depuis les MIR | §4.3.3, §4.01 | NON |

## Ce que l'outil contrôle (FGH — Controle BEP v1.1.0)

38 règles automatiques (30 règles fixes + une par attribut PVA du référentiel), regroupées en 9 catégories dans le dashboard. Les identifiants ci-dessous sont ceux affichés dans la colonne « ID ».

| Catégorie | Règles | Couvre |
|---|---|---|
| Projet et fichier | A05, A06, F10 | version Revit, taille, unités |
| Géoréférencement | B02, B03, B04 | point topo, point de base + angle, cube de repérage |
| Niveaux | B05a, B05b, B05c, B06, B07 | présence, altitudes, calage global, niveaux hors liste, éléments rattachés |
| Sous-projets | C03, C04, C05 | sous-projets obligatoires, nommage, éléments hors couche |
| Nommage | D01, D03 | préfixe de spécialité, caractères interdits |
| Attributs PVA | E01 à E08 | une règle par attribut du référentiel |
| Modélisation STR | F01, F06a, F06b, F08 | LoadBearing, modèles génériques, DirectShape, éléments sans niveau |
| Réservations | G01a, G01b, G02, G03, G04, G05 | format et unicité du numéro, paramètres de demande et de validation, percements en attente de validation STR, statut hors liste |
| Feuilles et livrables | H02, H06, H07, H08 | codification `SPVA_GED_A`…`H`, indice de révision, nomenclatures de livrables, annotations manuelles |

Non couvert, et pourquoi : **F02** (duplication des porteurs entre maquettes) et **F13** (collisions internes) demandent une comparaison inter-maquettes qui relève de Solibri/Navisworks ; **B01**, **B08**, **F03**, **F07**, **F12** demandent un jugement géométrique ou une comparaison à la MN IMP ; **H01** (SIA 400) et tout le bloc **I** sont procéduraux.

**G01b** (doublons de numéro) ne contrôle que la maquette STR. L'outil « Doublons Reservations » va plus loin : il compare à la maquette SPV liée et juge les positions. La règle du dashboard est un voyant, pas un remplaçant.

## J. Points à confirmer avec la cellule BIM

1. **Tiret autorisé ou non** — §2.10 vs §3.1.1 (voir D03).
2. **Accents dans les paramètres imposés** — `PVA_ALL_Eccc_Bât`, `PVA_MOD_Numéro` contiennent des accents, interdits par §2.10 et §3.1.1. Quelle orthographe exacte retenir ?
3. **Fichier de paramètres partagés SPVA** — annoncé (§3.2.2) mais non reçu ; sans lui, les GUID des paramètres `PVA_*` ne sont pas garantis.
4. **Tableaux LOI et LOG détaillés** — annoncés en annexe, absents du PDF. Nécessaires pour contrôler le LOI par élément et par phase SIA.
5. **Attribut de zone** — le BEP écrit `PVA_ALL_Zone` (§3.3.5) alors que le tableau §3.2.2 le note avec un espace parasite. Vérifier l'orthographe exacte.
6. **Liste définitive des sous-projets `03_STR_*`** — à figer en séance BIM.
7. **Zone Z85** — libellé vide dans le BEP.
8. **Cohérence des noms de paramètres réservations** — le BEP nomme `PVA_RES_DEM_NumPercement`, les scripts existants utilisent `PVA_RES_DEM_NumReservation`. L'outil accepte les deux.
9. **Statuts de validation des percements** — le BEP écrit `Refusé / Validé / En cours`, la maquette utilise `VALIDE / REFUSE / SUPPRIMEE` (majuscules sans accent, plus une valeur `SUPPRIMEE` que le BEP ne prévoit pas). Les deux jeux sont admis par l'outil, mais la liste officielle mérite d'être tranchée.
10. **Niveaux `0.00` et `TOITURE` absents du tableau du BEP** alors qu'ils sont dans la maquette de référence (0.00 = 374.21, TOITURE = 402.01). À corriger dans la prochaine version du BEP.
