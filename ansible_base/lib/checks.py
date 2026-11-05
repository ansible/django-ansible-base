import django.apps
from django.core.checks import Error, register
from django.core.exceptions import FieldDoesNotExist
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


def _dab_models():
    "Concrete, non-proxy models of ansible_base apps (app_label is dab_rbac etc.; the module path is the reliable DAB scope test)."
    for model in django.apps.apps.get_models():
        if not model._meta.proxy and not model._meta.abstract and django.apps.apps.get_app_config(model._meta.app_label).name.startswith('ansible_base.'):
            yield model


def _local_fields(model):
    "The model's declared, non-auto-created fields."
    return [field for field in model._meta.fields if not field.auto_created]


@register()
def check_textfield_indexed_is_bounded(app_configs, **kwargs):
    "Error on TextFields that carry an index or unique constraint in ansible_base apps; SQL Server cannot index nvarchar(max)."
    errors = []
    for model in _dab_models():
        for field in _local_fields(model):
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


# SQL Server limits index keys to 1700 bytes for the nonclustered indexes Django creates
# for Index, UniqueConstraint, and unique_together. (The 900-byte clustered limit governs
# the primary key, which a BoundedTextField never is.) The budget is shared by every
# column in a composite key, so the check counts them all, not just the bounded ones.
MSSQL_INDEX_KEY_BYTES = 1700
NVARCHAR_BYTES_PER_CODE_UNIT = 2

# Storage widths, in bytes, of the fixed-width SQL Server column types that appear in indexes.
MSSQL_FIELD_WIDTHS = {
    models.BooleanField: 1,
    models.SmallIntegerField: 2,
    models.IntegerField: 4,
    models.BigIntegerField: 8,
    models.DateField: 3,
    models.DateTimeField: 8,
    models.TimeField: 5,
    models.UUIDField: 16,
}


def _index_key_width(field):
    "Bytes of SQL Server index key that field's column occupies (0 for types not worth counting, e.g. plain TextField)."
    if isinstance(field, BoundedTextField):
        return NVARCHAR_BYTES_PER_CODE_UNIT * field.sql_server_max_length
    if isinstance(field, models.CharField):
        # mssql-django maps CharField to nvarchar(max_length)
        return NVARCHAR_BYTES_PER_CODE_UNIT * (field.max_length or 0)
    if isinstance(field, models.ForeignKey):
        # a foreign key column mirrors the width of the target's primary key
        return _index_key_width(field.target_field)
    # walk the type's own mro so subclasses count as themselves before their parents (DateTimeField inherits DateField but is wider)
    for field_type in type(field).__mro__:
        if field_type in MSSQL_FIELD_WIDTHS:
            return MSSQL_FIELD_WIDTHS[field_type]
    return 0


def _index_key_fields(model, field_names):
    "Resolve field_names to model fields, skipping names that do not resolve."
    fields = []
    for name in field_names:
        try:
            fields.append(model._meta.get_field(name))
        except FieldDoesNotExist:
            continue
    return fields


def _keyed_field_names(index_or_constraint):
    "Field names an index or unique constraint keys on, via fields or expressions."
    names = {name.lstrip('-') for name in (index_or_constraint.fields or [])}
    names |= _referenced_field_names(getattr(index_or_constraint, 'expressions', None))
    return names


def _model_keys(model):
    "The model's unique_together entries, unique constraints, and indexes."
    yield from model._meta.unique_together
    yield from (constraint for constraint in model._meta.constraints if isinstance(constraint, models.UniqueConstraint))
    yield from model._meta.indexes


def _field_key_size_error(model, field):
    "E004 for a field-level indexed or unique BoundedTextField whose column alone exceeds the budget, or None."
    if not (isinstance(field, BoundedTextField) and (field.db_index or field.unique)):
        return None
    key_bytes = _index_key_width(field)
    if key_bytes <= MSSQL_INDEX_KEY_BYTES:
        return None
    return Error(
        f'{model._meta.label}.{field.name} needs {key_bytes} bytes of SQL Server index key',
        hint=f"Lower sql_server_max_length on '{field.name}' in {model._meta.label} to 850 or less; "
        f"nvarchar takes 2 bytes per code unit and SQL Server limits nonclustered index keys to {MSSQL_INDEX_KEY_BYTES} bytes.",
        obj=model,
        id='ansible_base.E004',
    )


def _composite_key_size_error(model, key):
    "E004 for an index or unique constraint whose columns together exceed the budget, or None. Keys without a BoundedTextField are E002's concern."
    field_names = _keyed_field_names(key) if hasattr(key, 'fields') else set(key)  # unique_together entries are plain tuples of names
    fields = _index_key_fields(model, field_names)
    if not any(isinstance(field, BoundedTextField) for field in fields):
        return None
    key_bytes = sum(_index_key_width(field) for field in fields)
    if key_bytes <= MSSQL_INDEX_KEY_BYTES:
        return None
    name = getattr(key, 'name', key)  # unique_together entries are plain tuples
    return Error(
        f'{model._meta.label} key {name} needs {key_bytes} bytes of SQL Server index key',
        hint=f"Lower the sql_server_max_length of the BoundedTextField columns in {name}; "
        f"SQL Server limits nonclustered index keys to {MSSQL_INDEX_KEY_BYTES} bytes, shared by every column in the key.",
        obj=model,
        id='ansible_base.E004',
    )


@register()
def check_bounded_textfield_index_key_size(app_configs, **kwargs):
    "Error when an index or unique constraint containing a BoundedTextField exceeds SQL Server's index key-size budget."
    " A bound within E003's range can still be undeployable."
    errors = []
    for model in _dab_models():
        for field in _local_fields(model):
            if error := _field_key_size_error(model, field):
                errors.append(error)
        for key in _model_keys(model):
            if error := _composite_key_size_error(model, key):
                errors.append(error)
    return errors
