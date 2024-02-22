from ansible_base.lib.utils.models import diff


def _store_activitystream_entry(old, new, operation):
    from ansible_base.activitystream.models import Entry

    delta = diff(old, new)

    if delta["added_fields"] == {} and delta["changed_fields"] == {} and delta["removed_fields"] == {}:
        # No changes to store
        return

    content_object = new

    # If only one of old or new is None, then use the existing one as content_object
    if old is None and new is None:
        # This doesn't make sense
        raise ValueError("Both old and new objects are None")
    elif old is None:
        content_object = new
    elif new is None:
        content_object = old

    return Entry.objects.create(
        content_object=content_object,
        operation=operation,
        changes=delta,
    )


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

    This signal only handles creation of new objects (created=True). For
    updates, use the activitystream_update signal, where we can compare the
    old and new objects to determine what has changed.
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

    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    _store_activitystream_entry(old, None, 'delete')
