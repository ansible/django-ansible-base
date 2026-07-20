from ansible_base.activitystream.signals import no_activity_stream

__all__ = ['no_activity_stream', 'activity_stream_entries']


def activity_stream_entries():
    """
    Return a GenericRelation to the activity stream Entry model.

    The returned relation does not cascade-delete entries when the parent
    object is deleted, since activity stream records are an audit trail
    that must survive object deletion.

    Use this on your model to add a reverse relation for querying
    activity stream entries::

        from ansible_base.activitystream import activity_stream_entries

        class MyModel(CommonModel):
            activity_stream = activity_stream_entries()
    """
    from django.contrib.contenttypes.fields import GenericRelation

    class NonCascadingGenericRelation(GenericRelation):
        """A GenericRelation that does not cascade-delete related objects."""

        def bulk_related_objects(self, objs, using='default'):
            # Return an empty queryset so Django's deletion collector
            # never picks up (and deletes) the related entries.
            return self.remote_field.model._base_manager.db_manager(using).none()

    return NonCascadingGenericRelation(
        'dab_activitystream.Entry',
        content_type_field='content_type',
        object_id_field='object_id',
    )
