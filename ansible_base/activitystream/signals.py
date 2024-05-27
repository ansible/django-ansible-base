import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger('ansible_base.activitystream.signals')


class ActivityStreamEnabled(threading.local):
    def __init__(self):
        self.enabled = True

    def __bool__(self):
        return self.enabled


activitystream_enabled = ActivityStreamEnabled()


@contextmanager
def no_activity_stream():
    previous_value = activitystream_enabled.enabled
    activitystream_enabled.enabled = False
    try:
        yield
    finally:
        activitystream_enabled.enabled = previous_value


def _store_activitystream_entry(old, new, operation):
    if not activitystream_enabled:
        return

    from ansible_base.activitystream.models import Entry
    from ansible_base.lib.utils.models import diff

    if operation not in ('create', 'update', 'delete'):
        raise ValueError("Invalid operation: {}".format(operation))

    excluded = getattr(new, 'activity_stream_excluded_field_names', [])
    limit = getattr(new, 'activity_stream_limit_field_names', [])
    delta = diff(old, new, exclude_fields=excluded, limit_fields=limit, all_values_as_strings=True)

    if not delta:
        # No changes to store
        return

    # If only one of old or new is None, then use the existing one as content_object
    # The case where both are None is handled above (no changes to store)
    if new is None:
        content_object = old
    else:
        content_object = new

    return Entry.objects.create(
        content_object=content_object,
        operation=operation,
        changes=delta.dict(),
    )


def _store_activitystream_m2m(given_instance, model, operation, pk_set, reverse, field_name):
    if not activitystream_enabled:
        return

    from ansible_base.activitystream.models import Entry
    from ansible_base.lib.utils.models import current_user_or_system_user

    if operation not in ('associate', 'disassociate'):
        raise ValueError("Invalid operation: {}".format(operation))

    instances = model.objects.filter(pk__in=pk_set)
    user = current_user_or_system_user()
    entries = []

    for instance in instances:
        entry = Entry(
            content_object=instance if reverse else given_instance,
            operation=operation,
            related_content_object=given_instance if reverse else instance,
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

    _store_activitystream_entry(old, instance, 'update')


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
            pk_set = model.objects.filter(**{field_name: instance}).values_list('pk', flat=True)
        else:
            # If we're not reversing, then we're clearing the forward relation. So it's easy to get the PKs,
            # given we have the field name and the instance.
            pk_set = getattr(instance, field_name).all().values_list('pk', flat=True)

    _store_activitystream_m2m(instance, model, operation, pk_set, reverse, field_name)
