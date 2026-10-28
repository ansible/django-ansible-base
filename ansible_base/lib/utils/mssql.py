"""SQL Server field limits shared by schema conversion and API validation."""

from django.db import models


def get_mssql_textfield_max_length(field_name: str | None) -> int:
    """Return the SQL Server column length selected for a constrained TextField."""
    field_name = (field_name or '').lower()
    if 'codename' in field_name:
        return 100
    if any(part in field_name for part in ('object_id', 'parent_reference')):
        return 450
    if field_name == 'name':
        return 255
    if any(part in field_name for part in ('singleton', 'role_field')):
        return 64
    return 450


def get_mssql_constrained_textfield_max_length(field, model) -> int | None:
    """Return the SQL Server length if a TextField is indexed or constrained."""
    if not isinstance(field, models.TextField):
        return None
    if getattr(field, 'db_index', False) or getattr(field, 'unique', False):
        return get_mssql_textfield_max_length(field.name)

    model_meta = getattr(model, '_meta', None)
    if model_meta is None:
        return None

    field_name = field.name
    in_unique_together = any(field_name in fields for fields in getattr(model_meta, 'unique_together', []))
    in_unique_constraint = any(
        isinstance(constraint, models.UniqueConstraint) and field_name in getattr(constraint, 'fields', [])
        for constraint in getattr(model_meta, 'constraints', [])
    )
    in_index = any(field_name in [index_field.lstrip('-') for index_field in getattr(index, 'fields', [])] for index in getattr(model_meta, 'indexes', []))
    if in_unique_together or in_unique_constraint or in_index:
        return get_mssql_textfield_max_length(field_name)
    return None
