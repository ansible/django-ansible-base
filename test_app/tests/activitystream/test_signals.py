from ansible_base.activitystream.models import Entry


def test_activitystream_create(system_user, animal):
    """
    Ensure that an activity stream entry is created when an object is created.

    Also ensure that AuditableModel.activity_stream_entries returns the correct entries.
    """
    entries = animal.activity_stream_entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry == Entry.objects.last()
    assert entry.created_by == system_user
    assert entry.operation == 'create'
    assert 'added_fields' in entry.changes
    assert entry.changes['changed_fields'] == {}
    assert entry.changes['removed_fields'] == {}
    assert entry.changes['added_fields']['name'] == animal.name
    assert entry.changes['added_fields']['owner'] == animal.owner.username
    assert entry.changes['added_fields']['owner_id'] == animal.owner.id


def test_activitystream_update(system_user, animal):
    """
    Ensure that an activity stream entry is created when an object is updated.
    """
    original_name = animal.name
    animal.name = 'Rocky'
    animal.save()

    entries = animal.activity_stream_entries
    assert len(entries) == 2
    entry = entries.last()
    assert entry.created_by == system_user
    assert entry.operation == 'update'
    assert entry.changes['added_fields'] == {}
    assert entry.changes['removed_fields'] == {}
    assert len(entry.changes['changed_fields']) == 2  # name and modified_on
    assert entry.changes['changed_fields']['name'] == [original_name, 'Rocky']
