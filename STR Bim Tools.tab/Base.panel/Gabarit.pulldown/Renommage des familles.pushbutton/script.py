# -*- coding: utf-8 -*-
# =============================================================================
# CONFIG
# =============================================================================
SCRIPT_VERSION = "2.1"
SCRIPT_AUTHOR  = "Tony VARIN"
TOOL_NAME      = "Renommage Familles"
# =============================================================================
__title__ = "Majuscules\nFamilles"
__doc__ = "Renomme familles et types : majuscules, sans accents, espaces -> _, sans parentheses ni caracteres speciaux."
__version__ = "2.1"

from pyrevit import revit, DB, forms, script
from pyrevit.forms import ProgressBar
from Autodesk.Revit.DB import Transaction, FilteredElementCollector, Family, ElementType
import unicodedata

doc = revit.doc
output = script.get_output()


def normalize(text):
    text = text.upper()
    # Supprimer les accents via decomposition NFKD
    nfkd = unicodedata.normalize('NFKD', text)
    text = u''.join(c for c in nfkd if not unicodedata.combining(c))
    # Supprimer les caracteres speciaux
    text = text.replace('(', '').replace(')', '')
    text = text.replace(u'\xb0', '')   # degre
    text = text.replace(',', '')
    text = text.replace('!', '')
    text = text.replace("'", '')
    # Espaces -> underscore
    text = text.replace(' ', '_')
    # Nettoyer les doubles underscores
    while '__' in text:
        text = text.replace('__', '_')
    return text.strip('_')


def get_type_name(elem_type):
    try:
        p = elem_type.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p and p.AsString():
            return p.AsString()
    except:
        pass
    try:
        p = elem_type.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.AsString():
            return p.AsString()
    except:
        pass
    return None


def set_type_name(elem_type, new_name):
    try:
        DB.Element.Name.SetValue(elem_type, new_name)
        return True
    except:
        pass
    try:
        prop = elem_type.GetType().GetProperty("Name")
        if prop and prop.CanWrite:
            prop.SetValue(elem_type, new_name, None)
            return True
    except:
        pass
    return False


# --- Collecte ---
families = list(FilteredElementCollector(doc).OfClass(Family).ToElements())

all_elem_types = list(FilteredElementCollector(doc).OfClass(ElementType).ToElements())
system_types = [
    et for et in all_elem_types
    if et.GetType().Name != 'FamilySymbol'
    and et.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM) is not None
]

total = len(families) + len(system_types)

renamed_families     = []
renamed_types        = []
renamed_system_types = []
errors               = []
cancelled            = False


with ProgressBar(cancellable=True, step=1,
                 title='Renommage v{} ({{value}} of {{max_value}})'.format(__version__)) as pb:
    with Transaction(doc, "Renommage majuscules sans accents v{}".format(__version__)) as t:
        t.Start()

        # --- Familles chargees + leurs types ---
        for counter, family in enumerate(families):
            if pb.cancelled:
                cancelled = True
                break

            pb.update_progress(counter, total)

            old_fam_name = family.Name
            new_fam_name = normalize(old_fam_name)

            if new_fam_name != old_fam_name:
                try:
                    family.Name = new_fam_name
                    renamed_families.append((old_fam_name, new_fam_name))
                except Exception as e:
                    errors.append(u"Famille '{}' : {}".format(old_fam_name, str(e)))

            for type_id in family.GetFamilySymbolIds():
                fam_symbol = doc.GetElement(type_id)
                if fam_symbol is None:
                    continue

                param = fam_symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                if param is None:
                    continue

                old_type_name = param.AsString()
                if old_type_name is None:
                    continue

                new_type_name = normalize(old_type_name)

                if new_type_name != old_type_name:
                    try:
                        fam_symbol.Name = new_type_name
                        renamed_types.append((family.Name, old_type_name, new_type_name))
                    except Exception as e:
                        errors.append(u"Type '{}' (famille '{}'): {}".format(
                            old_type_name, old_fam_name, str(e)))

        # --- Types systeme ---
        if not cancelled:
            for counter, elem_type in enumerate(system_types):
                if pb.cancelled:
                    cancelled = True
                    break

                pb.update_progress(len(families) + counter, total)

                old_name = get_type_name(elem_type)
                if old_name is None:
                    continue

                new_name = normalize(old_name)
                if new_name == old_name:
                    continue

                try:
                    fam_name_param = elem_type.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
                    fam_label = fam_name_param.AsString() if fam_name_param else "Systeme"
                except:
                    fam_label = "Systeme"

                if set_type_name(elem_type, new_name):
                    renamed_system_types.append((fam_label, old_name, new_name))
                else:
                    errors.append(u"[{}] '{}' : impossible de renommer".format(fam_label, old_name))

        if cancelled:
            t.RollBack()
        else:
            t.Commit()


# --- Rapport ---
if cancelled:
    output.print_md("# Renommage annule par l'utilisateur")
    output.print_md("Aucune modification appliquee (transaction annulee).")
else:
    output.print_md("# Resultat du renommage v{}".format(__version__))

    output.print_md("## Familles renommees ({})".format(len(renamed_families)))
    if renamed_families:
        for old, new in renamed_families:
            output.print_md(u"- `{}` -> `{}`".format(old, new))
    else:
        output.print_md("_Aucune famille renommee_")

    output.print_md("## Types de familles chargees ({})".format(len(renamed_types)))
    if renamed_types:
        for fam, old, new in renamed_types:
            output.print_md(u"- [{}] `{}` -> `{}`".format(fam, old, new))
    else:
        output.print_md("_Aucun type renomme_")

    output.print_md("## Types systeme ({})".format(len(renamed_system_types)))
    if renamed_system_types:
        for fam, old, new in renamed_system_types:
            output.print_md(u"- [{}] `{}` -> `{}`".format(fam, old, new))
    else:
        output.print_md("_Aucun type systeme renomme_")

    if errors:
        output.print_md("## Erreurs ({})".format(len(errors)))
        for err in errors:
            output.print_md(u"- {}".format(err))

    forms.alert(
        u"{} famille(s), {} type(s) charges, {} type(s) systeme renommes. {} erreur(s).".format(
            len(renamed_families), len(renamed_types), len(renamed_system_types), len(errors)
        ),
        title="Renommage termine v{}".format(__version__)
    )