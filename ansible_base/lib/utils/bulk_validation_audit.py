"""Audit logging for bulk ORM writes that bypass post_save validation signals.

Django does not fire ``post_save`` for ``bulk_create()`` / ``bulk_update()`` /
``QuerySet.update()``. Services should call these helpers at sync/import sites so
violations are logged with the same validators and a similar format as
``validation_bypass_logger``.
"""

from collections.abc import Callable
from typing import Iterable

from django.db.models import Model

from ansible_base.lib.utils.validation_signals import (
    _get_caller_info,
    _get_text_fields,
    _protected_models,
    _validate_field,
    logger,
)


def _log_bulk_violation(
    operation: str,
    field_name: str,
    resource_type: str,
    tier: str,
    caller_info: str,
    reason: str,
) -> None:
    logger.warning(
        "ORM bypass (%s): validation rejected '%s' on %s (violates %s) [caller: %s]: %s",
        operation,
        field_name,
        resource_type,
        tier,
        caller_info,
        reason,
    )


def _audit_registered_model_fields(
    *,
    operation: str,
    caller_info: str,
    model: type[Model],
    resource_type: str,
    name_fields: frozenset,
    excluded_fields: frozenset,
    get_field_value: Callable[[str], object],
) -> None:
    text_fields, _json_fields = _get_text_fields(model)
    if not text_fields:
        return
    for field_name in text_fields:
        if field_name in excluded_fields:
            continue
        value = get_field_value(field_name)
        if value is None or not isinstance(value, str):
            continue
        violation = _validate_field(field_name, value, name_fields)
        if violation:
            tier, reason = violation
            _log_bulk_violation(operation, field_name, resource_type, tier, caller_info, reason)


def audit_bulk_model_instances(
    instances: Iterable[Model],
    *,
    operation: str = "bulk_create",
) -> None:
    """Log validation violations for instances about to be bulk-written (non-blocking)."""
    caller_info = _get_caller_info()
    for instance in instances:
        protected = _protected_models.get(type(instance))
        if protected is None:
            continue
        name_fields, excluded_fields = protected
        resource_type = f"{instance._meta.app_label}.{instance._meta.object_name}"
        _audit_registered_model_fields(
            operation=operation,
            caller_info=caller_info,
            model=type(instance),
            resource_type=resource_type,
            name_fields=name_fields,
            excluded_fields=excluded_fields,
            get_field_value=lambda field_name, inst=instance: getattr(inst, field_name, None),
        )


def audit_bulk_item_dicts(
    model: type[Model],
    items: Iterable[dict],
    *,
    operation: str = "bulk_create",
) -> None:
    """Log validation violations for dict payloads before ``bulk_create(**item)``."""
    protected = _protected_models.get(model)
    if protected is None:
        return
    name_fields, excluded_fields = protected
    text_fields, _json_fields = _get_text_fields(model)
    if not text_fields:
        return
    caller_info = _get_caller_info()
    resource_type = f"{model._meta.app_label}.{model._meta.object_name}"
    for item in items:
        _audit_registered_model_fields(
            operation=operation,
            caller_info=caller_info,
            model=model,
            resource_type=resource_type,
            name_fields=name_fields,
            excluded_fields=excluded_fields,
            get_field_value=item.get,
        )
