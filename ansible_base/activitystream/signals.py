from ansible_base.lib.utils.models import diff


def _store_activitystream_entry(old, new, operation):
    from ansible_base.activitystream.models import Entry

    delta = diff(old, new)

    if delta["added_fields"] == {} and delta["changed_fields"] == {} and delta["removed_fields"] == {}:
        # No changes to store
        return

    return Entry.objects.create(
        content_object=new,
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
