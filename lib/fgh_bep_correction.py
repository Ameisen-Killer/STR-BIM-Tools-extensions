# -*- coding: utf-8 -*-
# =============================================================================
# fgh_bep_correction.py - Application des corrections de nommage BEP.
#
# Appele par le bouton « Enregistrer les corrections » de la fenetre de
# resultats. Il ne decide rien : la regle a propose un nom, l'utilisateur l'a
# valide (case cochee) et eventuellement modifie, ce module se contente de
# l'ecrire dans la maquette.
#
# Trois garde-fous avant d'ecrire, parce qu'un renommage refuse par Revit au
# milieu d'un lot laisse un travail a moitie fait :
#   1. le nom doit passer le jeu de caracteres du referentiel BEP ;
#   2. il ne doit contenir aucun caractere que Revit refuse lui-meme (voir
#      _CARACTERES_REVIT : l'incident des quatre vues 3D CAN 241) ;
#   3. il doit etre unique dans le lot, Revit refusant les homonymes.
# Ce qui ne passe pas est rapporte ligne par ligne, jamais avale.
#
# UNE transaction pour tout le lot : un echec isole n'annule pas les autres
# renommages, mais l'ensemble reste annulable d'un seul Ctrl+Z.
#
# Ce module DEPEND de l'API Revit, pas de WPF. IronPython 2.7 compatible.
# =============================================================================

import re

from Autodesk.Revit.DB import (Transaction, TransactionStatus, Element,
                               FilteredWorksetCollector, WorksetKind,
                               WorksetTable)

# Caracteres que Revit refuse dans le nom d'un element, quel que soit le BEP.
# Les avoir laisses passer a casse les quatre vues 3D du projet CAN 241 :
# le controle est fait ici meme si le referentiel devenait plus permissif.
_CARACTERES_REVIT = u"\\:{}[]|;<>?`~"


class Correction(object):
    """Un renommage demande depuis la fenetre de resultats."""

    def __init__(self, type_objet, eid, nom_actuel, nouveau_nom):
        self.type_objet = type_objet
        self.eid = eid
        self.nom_actuel = nom_actuel
        self.nouveau_nom = nouveau_nom


def verifier(nouveau_nom, nom_actuel, motif_bep=None):
    """Motif de refus (unicode) si le nom ne peut pas etre ecrit, sinon None."""
    nom = (nouveau_nom or u"").strip()
    if not nom:
        return u"nom vide"
    if nom == nom_actuel:
        return u"nom inchangé"
    fautifs = sorted(set(c for c in nom if c in _CARACTERES_REVIT))
    if fautifs:
        return u"caractères refusés par Revit : {0}".format(u" ".join(fautifs))
    if motif_bep:
        try:
            if not re.match(motif_bep, nom):
                return u"nom non conforme au jeu de caractères du BEP"
        except Exception:
            pass
    return None


def _renommer_workset(doc, nom_actuel, nouveau_nom):
    """Les sous-projets n'ont pas d'ElementId exploitable dans les constats :
    on les retrouve par leur nom, qui est unique dans le document."""
    for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
        if ws.Name == nom_actuel:
            WorksetTable.RenameWorkset(doc, ws.Id, nouveau_nom)
            return True
    raise Exception(u"sous-projet introuvable")


# Familles de noms a espace PLAT : deux objets de ce genre ne peuvent pas
# porter le meme nom dans un document, un doublon dans le lot est donc une
# erreur certaine. Les TYPES en sont absents : leur nom n'a besoin d'etre
# unique que dans leur famille, deux categories peuvent legitimement porter
# le meme nom de type. Pour eux, c'est Revit qui tranche, et son refus est
# rapporte tel quel.
_ESPACES_PLATS = (u"Famille", u"Matériau", u"Sous-projet", u"Feuille",
                  u"Vue", u"Nomenclature")


def _ecrire_nom(el, nom):
    """Ecrit Element.Name. La propriete est redefinie sur ElementType, ce qui
    rend l'acces direct ambigu en IronPython : le meme piege que la LECTURE
    (AttributeError sur certains types) vaut pour l'ecriture, d'ou le repli
    explicite sur le descripteur de la classe de base."""
    try:
        el.Name = nom
        return
    except AttributeError:
        pass
    Element.Name.__set__(el, nom)


def appliquer(doc, corrections, motifs_par_type=None):
    """
    Ecrit les renommages. Retourne (nb_reussis, [(nom, nouveau, motif), ...]).

    `motifs_par_type` = {libelle de nature d'objet: expression reguliere}. Le
    jeu de caracteres se reglant par nature d'objet, un nom de type edite a la
    main se valide avec le jeu des types, pas avec celui des familles. Une
    nature absente du dictionnaire n'est verifiee que sur les caracteres que
    Revit lui-meme refuse.

    Les refus previsibles sont filtres AVANT d'ouvrir la transaction : ouvrir
    puis annuler un lot entier parce qu'une ligne etait vide serait une
    mauvaise surprise pour les autres lignes.
    """
    motifs_par_type = motifs_par_type or {}
    echecs = []
    a_ecrire = []
    vus = {}
    for c in corrections:
        motif = verifier(c.nouveau_nom, c.nom_actuel,
                         motifs_par_type.get(c.type_objet))
        if motif is None and c.type_objet in _ESPACES_PLATS:
            cle = (c.type_objet, (c.nouveau_nom or u"").strip().lower())
            if cle in vus:
                motif = u"nom déjà proposé pour « {0} »".format(vus[cle])
            else:
                vus[cle] = c.nom_actuel
        if motif is not None:
            echecs.append((c.nom_actuel, c.nouveau_nom, motif))
            continue
        a_ecrire.append(c)

    if not a_ecrire:
        return 0, echecs

    reussis = 0
    t = Transaction(doc, u"STR - Correction des nommages BEP")
    try:
        t.Start()
        for c in a_ecrire:
            nom = c.nouveau_nom.strip()
            try:
                if c.eid is not None:
                    el = doc.GetElement(c.eid)
                    if el is None:
                        raise Exception(u"élément introuvable")
                    _ecrire_nom(el, nom)
                elif c.type_objet == u"Sous-projet":
                    _renommer_workset(doc, c.nom_actuel, nom)
                else:
                    raise Exception(u"objet non renommable par l'outil")
                reussis += 1
            except Exception as ex:
                # Le plus frequent : un homonyme existe deja dans la maquette.
                echecs.append((c.nom_actuel, nom,
                               u"refus de Revit : {0}".format(ex)))
        if t.GetStatus() == TransactionStatus.Started:
            if reussis:
                t.Commit()
            else:
                t.RollBack()
    except Exception:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        raise
    return reussis, echecs
