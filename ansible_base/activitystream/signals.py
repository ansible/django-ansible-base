from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional, Set, Tuple, Type, Union

from ansible_base.lib.logging import log_auth_event

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser
    from django.db.models import Model

logger = logging.getLogger('ansible_base.activitystream.signals')


class ActivityStreamEnabled(threading.local):
    def __init__(self):
        self.enabled = True

    def __bool__(self):
        return self.enabled


activitystream_enabled = ActivityStreamEnabled()


class _DeferredActivityStream(threading.local):
    def __init__(self) -> None:
        self.active: bool = False
        self.entries: list = []
        self.audit_lines: list[str] = []


_deferred_activity_stream = _DeferredActivityStream()


@contextmanager
def no_activity_stream() -> Generator[None, None, None]:
    previous_value = activitystream_enabled.enabled
    activitystream_enabled.enabled = False
    try:
        yield
    finally:
        activitystream_enabled.enabled = previous_value


def _flush_deferred_activity_stream(entries: list, audit_lines: list[str]) -> None:
    """Flush accumulated activity stream entries and audit log lines.

    Bulk-creates Entry objects (filling in created_by where missing) and
    schedules audit lines for emission via transaction.on_commit so they
    only fire after the enclosing transaction commits.
    """
    if entries:
        from ansible_base.activitystream.models import Entry
        from ansible_base.lib.utils.models import current_user_or_system_user

        user = current_user_or_system_user()
        for entry in entries:
            if entry.created_by is None:
                entry.created_by = user

        Entry.objects.bulk_create(entries)
        logger.debug('Bulk-created %d deferred activity stream entries', len(entries))

    if audit_lines:
        from django.db import connection

        def _emit_audit_lines(lines=audit_lines):
            for line in lines:
                log_auth_event(line)

        connection.on_commit(_emit_audit_lines)


@contextmanager
def deferred_activity_stream() -> Generator[None, None, None]:
    """Defer activity stream entries and audit log lines during bulk operations.

    While active, _store_activitystream_entry accumulates Entry objects and
    audit log lines in thread-local lists instead of writing them immediately.
    On successful exit, Entry objects are bulk-created and audit lines are
    emitted via transaction.on_commit (so they only fire after the enclosing
    transaction commits — a rollback silently discards them).
    Re-entrant: inner calls are no-ops (outermost caller owns the flush).
    """
    if _deferred_activity_stream.active:
        yield
        return
    _deferred_activity_stream.active = True
    try:
        yield
    except BaseException:
        _deferred_activity_stream.active = False
        _deferred_activity_stream.entries = []
        _deferred_activity_stream.audit_lines = []
        raise
    else:
        entries = _deferred_activity_stream.entries
        audit_lines = _deferred_activity_stream.audit_lines
        _deferred_activity_stream.active = False
        _deferred_activity_stream.entries = []
        _deferred_activity_stream.audit_lines = []
        _flush_deferred_activity_stream(entries, audit_lines)


def _get_actor_user_and_username() -> Tuple[Optional[AbstractUser], str]:
    """Return (current user, username) or (None, 'unknown') if outside request."""
    from ansible_base.lib.utils.models import current_user_or_system_user

    user = current_user_or_system_user()
    return (user, user.username if user else "unknown")


def _format_audit_lines(
    prefix: str,
    operation: str,
    model_name: str,
    obj_str: str,
    changes: Union[Dict[str, Any], str],
) -> list[str]:
    """Build audit log line(s) for a single object change.

    For m2m associate/disassociate, *changes* is a plain string appended to the
    line.  For create/delete it is a dict collapsed into a single summary line.
    For update it is a dict expanded into one line per field.
    """
    if isinstance(changes, str):
        return [f"{prefix}{operation} {model_name} {obj_str} {changes}"]

    if operation in ('create', 'delete'):
        all_fields: Dict[str, Any] = {}
        if operation == 'create':
            all_fields.update(changes.get('added_fields', {}))
        else:
            all_fields.update(changes.get('removed_fields', {}))
        changed = changes.get('changed_fields', {})
        all_fields.update({k: v[1] if operation == 'create' else v[0] for k, v in changed.items()})
        return [f"{prefix}{operation} {model_name} {obj_str} {all_fields}"]

    lines = []
    for field_name, value in changes.get('added_fields', {}).items():
        lines.append(f"{prefix}{operation} {model_name} {obj_str} added {field_name}='{value}'")
    for field_name, value in changes.get('removed_fields', {}).items():
        lines.append(f"{prefix}{operation} {model_name} {obj_str} removed {field_name} (was '{value}')")
    for field_name, (old_val, new_val) in changes.get('changed_fields', {}).items():
        lines.append(f"{prefix}{operation} {model_name} {obj_str} changed {field_name} from '{old_val}' to '{new_val}'")
    return lines


def _log_audit_entry(
    *,
    content_object: Model,
    operation: str,
    changes: Union[Dict[str, Any], str],
) -> None:
    """Emit audit log lines if content_object has audit_log_enabled.

    For create/update/delete, *changes* is a dict (added_fields,
    removed_fields, changed_fields).  For m2m associate/disassociate,
    *changes* is the rest of the line as a string
    (e.g. ``'with Team Parent (2)'``).
    """
    if not getattr(content_object, 'audit_log_enabled', False):
        return

    model_name = content_object.__class__.__name__
    obj_str = f"{content_object} ({content_object.pk})"
    _, actor_username = _get_actor_user_and_username()
    prefix = f"User: {actor_username} "

    lines = _format_audit_lines(prefix, operation, model_name, obj_str, changes)

    if _deferred_activity_stream.active:
        _deferred_activity_stream.audit_lines.extend(lines)
    else:
        for line in lines:
            log_auth_event(line)


def _get_limit(
    operation: str,
    update_fields: Optional[Any],
    limit_from_model: list,
) -> Optional[list]:
    """
    Return the list of fields to include in the diff, or None to skip storing an entry.
    For create/delete (or update without update_fields), returns limit_from_model.
    For update with update_fields: empty update_fields or empty intersection returns None.
    """
    # If we are not in an update, return whatever the model limit is.
    if operation != 'update' or update_fields is None:
        return limit_from_model
    # If we are an update but we don't have any update fields, then we don't want to store an entry.
    if not update_fields:
        return None
    # We only want to diff the fields that were updated, so we take the intersection of
    # the limited fields and the update fields.
    if not limit_from_model:
        # If limit is otherwise empty (meaning no pre-existing limit), then we just need
        # to make the updated fields the limit.
        return list(update_fields)
    limit = list(set(limit_from_model).intersection(set(update_fields)))
    # If only a non-included field is updated, we can be certain that the delta will be
    # empty; continuing with the diff would introduce a bug where we diff all
    # non-excluded fields.
    return limit if limit else None


def _store_activitystream_entry(
    old: Optional[Model],
    new: Optional[Model],
    operation: str,
    update_fields: Optional[Any] = None,
) -> Optional[Any]:
    if not activitystream_enabled:
        return None

    from ansible_base.activitystream.models import Entry
    from ansible_base.lib.utils.models import diff

    if operation not in ('create', 'update', 'delete'):
        raise ValueError("Invalid operation: {}".format(operation))

    # Excluded/limit come from new (for create/update); for delete new is None so getattr returns []
    excluded = getattr(new, 'activity_stream_excluded_field_names', [])
    limit_from_model = getattr(new, 'activity_stream_limit_field_names', [])

    limit = _get_limit(operation, update_fields, limit_from_model)
    if limit is None:
        return None

    delta = diff(old, new, exclude_fields=excluded, limit_fields=limit, all_values_as_strings=True)
    if not delta:
        # There were no changes to store, so we return None
        return None

    # If only one of old or new is None, then use the existing one as content_object
    # The case where both are None is handled above (no changes to store)
    content_object = new or old
    _log_audit_entry(
        content_object=content_object,
        operation=operation,
        changes=delta.dict(),
    )

    if getattr(content_object, 'activity_stream_enabled', True):
        from django.contrib.contenttypes.models import ContentType

        entry_kwargs = {
            'content_type': ContentType.objects.get_for_model(content_object),
            'object_id': str(content_object.pk),
            'operation': operation,
            'changes': delta.dict(),
        }
        if _deferred_activity_stream.active:
            _deferred_activity_stream.entries.append(Entry(**entry_kwargs))
            return None
        return Entry.objects.create(**entry_kwargs)
    return None


def _store_activitystream_m2m(
    given_instance: Model,
    model: Type[Model],
    operation: str,
    pk_set: Set[Any],
    reverse: bool,
    field_name: str,
) -> None:
    if not activitystream_enabled:
        return

    from ansible_base.activitystream.models import Entry

    if operation not in ('associate', 'disassociate'):
        raise ValueError("Invalid operation: {}".format(operation))

    user, _ = _get_actor_user_and_username()
    instances = model.objects.filter(pk__in=pk_set)
    entries = []

    for instance in instances:
        content_object = instance if reverse else given_instance
        related_object = given_instance if reverse else instance

        # Audit logging for m2m changes
        related_model_name = related_object.__class__.__name__
        related_str = f"{related_object} ({related_object.pk})"
        preposition = 'with' if operation == 'associate' else 'from'
        _log_audit_entry(
            content_object=content_object,
            operation=operation,
            changes=f"{preposition} {related_model_name} {related_str}",
        )

        entry = Entry(
            content_object=content_object,
            operation=operation,
            related_content_object=related_object,
            related_field_name=field_name,
            created_by=user,
        )
        entries.append(entry)

    Entry.objects.bulk_create(entries)


# post_save
def activitystream_create(sender, instance, created, **kwargs):
    """
    This signal is registered via the activity stream AuditableModel abstract
    model/class. It is called after save() of any model that inherits from
    AuditableModel. (It is registered as a post_save signal.)

    This signal only handles creation of new objects (created=True). For
    updates, use the activitystream_update signal, where we can compare the
    old and new objects to determine what has changed.
    """
    if not created:
        # We only want to create an activity stream entry for new objects
        # Update events are handled by the activitystream_update receiver
        return

    _store_activitystream_entry(None, instance, 'create')


# pre_save
def activitystream_update(sender, instance, raw, using, update_fields, **kwargs):
    """
    This signal is registered via the activity stream AuditableModel abstract
    model/class. It is called before save() of any model that inherits from
    AuditableModel. (It is registered as a pre_save signal.)

    This signal only handles updates of existing objects. For creation of
    objects, see the above activitystream_create().
    """
    if instance.pk is None:
        # We only want to create an activity stream entry for existing objects
        # Creation events are handled by the activitystream_create receiver
        return

    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    _store_activitystream_entry(old, instance, 'update', update_fields=update_fields)


# pre_delete
def activitystream_delete(sender, instance, using, origin, **kwargs):
    """
    This signal is registered via the activity stream AuditableModel abstract
    model/class. It is called before delete() of any model that inherits from
    AuditableModel. (It is registered as a pre_delete signal.)
    """
    if instance.pk is None:
        return

    _store_activitystream_entry(instance, None, 'delete')


# m2m_changed
def activitystream_m2m_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    This signal is registered via the activity stream AuditableModel abstract
    model/class. It is called when a many-to-many relationship is changed
    (added or removed) for any model that inherits from AuditableModel. (It is
    registered as a m2m_changed signal.)
    """
    if action not in ('post_add', 'post_remove', 'pre_clear'):
        return

    if 'field_name' not in kwargs:
        # Theory says we should never get here, the field name is established when the signal is connected.
        raise ValueError(
            f"Missing field_name in kwargs while trying to store activity stream {action} event for instance={instance}, model={model}, sender={sender}"
        )

    field_name = kwargs['field_name']
    operation = 'associate' if action == 'post_add' else 'disassociate'

    if action == 'pre_clear':
        # This is called if someone calls .clear() on a m2m field. But we need to handle the forward and reverse
        # relations differently.
        if reverse:
            # Okay. We need to talk. Just you - the reader trying to understand this code - and I.
            # Look. We want to always store the activity stream entry on the forward relation.
            # Let's assume we have an Animal model with a 'people_friends' field which is a m2m pointing to User.
            # This is the forward relation.
            # If we do: user.animal_friends.clear() - the reverse relation - we need to get the PKs of
            # every animal that is being removed from the user's animal_friends.
            # Note that in this case, model is the Animal model, and instance is the user.
            pk_set = set(model.objects.filter(**{field_name: instance}).values_list('pk', flat=True))
        else:
            # If we're not reversing, then we're clearing the forward relation. So it's easy to get the PKs,
            # given we have the field name and the instance.
            pk_set = set(getattr(instance, field_name).all().values_list('pk', flat=True))

    # Django may pass pk_set as a QuerySet (e.g. for pre_clear); normalize to set for type consistency
    if not isinstance(pk_set, set):
        pk_set = set(pk_set)
    _store_activitystream_m2m(instance, model, operation, pk_set, reverse, field_name)
