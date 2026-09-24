"""Audit logging for bulk ORM writes that bypass post_save validation signals.

Django does not fire ``post_save`` for ``bulk_create()`` / ``bulk_update()`` /
``QuerySet.update()``. Services should call these helpers at sync/import sites so
violations are logged with the same validators and a similar format as
``validation_bypass_logger``.
"""

from collections.abc import Callable
from typing import Any, Iterable

from django.db.models import Model, QuerySet

from ansible_base.lib.utils.validation_signals import (
    _get_caller_info,
    _get_text_fields,
    _protected_models,
    _validate_field,
    log_orm_bypass_violation,
)


def _log_bulk_violation(
    operation: str,
    field_name: str,
    resource_type: str,
    tier: str,
    caller_info: str,
    reason: str,
) -> None:
    log_orm_bypass_violation(operation, field_name, resource_type, tier, caller_info, reason)


def _audit_registered_model_fields(
    *,
    operation: str,
    caller_info: str | None,
    model: type[Model],
    resource_type: str,
    name_fields: frozenset,
    excluded_fields: frozenset,
    get_field_value: Callable[[str], object],
    fields_to_audit: frozenset[str] | None = None,
) -> str | None:
    text_fields, _json_fields = _get_text_fields(model)
    if not text_fields:
        return caller_info
    resolved_caller = caller_info
    for field_name in text_fields:
        if fields_to_audit is not None and field_name not in fields_to_audit:
            continue
        if field_name in excluded_fields:
            continue
        value = get_field_value(field_name)
        if value is None or not isinstance(value, str):
            continue
        violation = _validate_field(field_name, value, name_fields)
        if violation:
            tier, reason = violation
            if resolved_caller is None:
                resolved_caller = _get_caller_info()
            _log_bulk_violation(operation, field_name, resource_type, tier, resolved_caller, reason)
    return resolved_caller


def audit_bulk_model_instances(
    instances: Iterable[Model],
    *,
    operation: str = "bulk_create",
    update_fields: Iterable[str] | None = None,
) -> list[Model]:
    """Log validation violations for instances about to be bulk-written (non-blocking).

    Returns a list of the same instances (materialized) so callers may pass a generator
    and reuse the result for ``bulk_create()`` / ``bulk_update()``.
    """
    materialized = list(instances)
    fields_to_audit = frozenset(update_fields) if update_fields is not None else None
    caller_info = None
    for instance in materialized:
        protected = _protected_models.get(type(instance))
        if protected is None:
            continue
        name_fields, excluded_fields = protected
        resource_type = f"{instance._meta.app_label}.{instance._meta.object_name}"
        caller_info = _audit_registered_model_fields(
            operation=operation,
            caller_info=caller_info,
            model=type(instance),
            resource_type=resource_type,
            name_fields=name_fields,
            excluded_fields=excluded_fields,
            get_field_value=lambda field_name, inst=instance: getattr(inst, field_name, None),
            fields_to_audit=fields_to_audit,
        )
    return materialized


def audit_bulk_item_dicts(
    model: type[Model],
    items: Iterable[dict],
    *,
    operation: str = "bulk_create",
) -> list[dict]:
    """Log validation violations for dict payloads before ``bulk_create(**item)``.

    Returns a materialized list of item dicts for reuse after auditing.
    """
    materialized = list(items)
    protected = _protected_models.get(model)
    if protected is None:
        return materialized
    name_fields, excluded_fields = protected
    text_fields, _json_fields = _get_text_fields(model)
    if not text_fields:
        return materialized
    caller_info = None
    resource_type = f"{model._meta.app_label}.{model._meta.object_name}"
    for item in materialized:
        caller_info = _audit_registered_model_fields(
            operation=operation,
            caller_info=caller_info,
            model=model,
            resource_type=resource_type,
            name_fields=name_fields,
            excluded_fields=excluded_fields,
            get_field_value=item.get,
        )
    return materialized


def audit_queryset_update(model: type[Model], update_kwargs: dict[str, Any]) -> None:
    """Log Tier 1/2 violations for literal strings in ``QuerySet.update()`` kwargs.

    Non-string values (``F()``, ``Case``, subqueries, etc.) are skipped because the
    resulting SQL value is not known without a ``SELECT``. Does not block the update.
    """
    if not update_kwargs:
        return
    protected = _protected_models.get(model)
    if protected is None:
        return
    name_fields, excluded_fields = protected
    resource_type = f"{model._meta.app_label}.{model._meta.object_name}"
    _audit_registered_model_fields(
        operation="queryset_update",
        caller_info=None,
        model=model,
        resource_type=resource_type,
        name_fields=name_fields,
        excluded_fields=excluded_fields,
        get_field_value=update_kwargs.get,
        fields_to_audit=frozenset(update_kwargs),
    )


def audited_queryset_update(queryset: QuerySet, **update_kwargs: Any) -> int:
    """Audit ``update_kwargs`` then run ``queryset.update(**update_kwargs)``."""
    audit_queryset_update(queryset.model, update_kwargs)
    return queryset.update(**update_kwargs)
