"""Audit logging for bulk ORM writes that bypass post_save validation signals.

Django does not fire ``post_save`` for ``bulk_create()`` / ``bulk_update()`` /
``QuerySet.update()``. Services should call these helpers at sync/import sites so
violations are logged with the same validators and a similar format as
``validation_bypass_logger``.
"""

import logging
from typing import Iterable

from django.db.models import Model

from ansible_base.lib.utils.validation_signals import (
    _get_caller_info,
    _get_text_fields,
    _protected_models,
    _validate_field,
)

logger = logging.getLogger('ansible_base.lib.utils.validation_signals')


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
        text_fields, _json_fields = _get_text_fields(type(instance))
        if not text_fields:
            continue
        resource_type = f"{instance._meta.app_label}.{instance._meta.object_name}"
        for field_name in text_fields:
            if field_name in excluded_fields:
                continue
            value = getattr(instance, field_name, None)
            if value is None or not isinstance(value, str):
                continue
            violation = _validate_field(field_name, value, name_fields)
            if violation:
                tier, reason = violation
                _log_bulk_violation(operation, field_name, resource_type, tier, caller_info, reason)


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
        for field_name in text_fields:
            if field_name in excluded_fields:
                continue
            value = item.get(field_name)
            if value is None or not isinstance(value, str):
                continue
            violation = _validate_field(field_name, value, name_fields)
            if violation:
                tier, reason = violation
                _log_bulk_violation(operation, field_name, resource_type, tier, caller_info, reason)
