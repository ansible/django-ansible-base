import django.apps
from django.core.checks import Error, register
from django.db import models

from ansible_base.lib.fields import BoundedTextField


@register()
def check_charfield_has_max_length(app_configs, **kwargs):
    errors = []
    for model in django.apps.apps.get_models():
        for field in model._meta.fields:
            if isinstance(field, models.CharField) and field.max_length is None:
                errors.append(
                    Error(
                        'CharField must have a max_length',
                        hint=f"Add max_length parameter for field '{field.name}' in {model.__name__}",
                        id='ansible_base.E001',
                    )
                )
    return errors


def _referenced_field_names(expressions):
    "Field names referenced by index/constraint expressions, e.g. Index(Lower('name'))."
    names = set()
    for expression in expressions or ():
        for subexpression in expression.flatten():
            if isinstance(subexpression, models.F) and '__' not in subexpression.name:
                names.add(subexpression.name)
    return names


def _is_indexed_or_unique(field, model):
    "Return True if the field is indexed or made unique at the field, Meta, or constraint level."
    if field.db_index or field.unique:
        return True
    unique_together = [set(ut) for ut in model._meta.unique_together]
    if any(field.name in fields for fields in unique_together):
        return True
    for constraint in model._meta.constraints:
        if isinstance(constraint, models.UniqueConstraint) and (
            field.name in (constraint.fields or []) or field.name in _referenced_field_names(constraint.expressions)
        ):
            return True
    for index in model._meta.indexes:
        if field.name in {name.lstrip('-') for name in index.fields} or field.name in _referenced_field_names(index.expressions):
            return True
    return False


@register()
def check_textfield_indexed_is_bounded(app_configs, **kwargs):
    "Error on TextFields that carry an index or unique constraint in ansible_base apps; SQL Server cannot index nvarchar(max)."
    errors = []
    for model in django.apps.apps.get_models():
        if model._meta.proxy or model._meta.abstract:
            continue
        # app_label is dab_rbac / dab_resource_registry / etc.; the module path is the reliable DAB scope test
        if not django.apps.apps.get_app_config(model._meta.app_label).name.startswith('ansible_base.'):
            continue
        for field in model._meta.fields:
            if field.auto_created:
                continue
            if isinstance(field, models.TextField) and not isinstance(field, BoundedTextField) and _is_indexed_or_unique(field, model):
                errors.append(
                    Error(
                        f'{model._meta.label}.{field.name} is an indexed or unique TextField',
                        hint=f"Use BoundedTextField for '{field.name}' in {model._meta.label}; SQL Server cannot index nvarchar(max).",
                        obj=model,
                        id='ansible_base.E002',
                    )
                )
    return errors
