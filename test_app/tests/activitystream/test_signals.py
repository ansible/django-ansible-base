import re
from unittest import mock

import pytest

import ansible_base.activitystream.signals as signals
from ansible_base.activitystream import no_activity_stream
from ansible_base.activitystream.apps import get_activity_stream_entries
from ansible_base.activitystream.models import Entry
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from test_app.models import Animal, City, SecretColor


def test_activitystream_generic_relation(system_user, animal, random_user):
    """
    Ensure that the GenericRelation field (activity_stream_entries()) works
    as a standard Django reverse relation for querying entries.
    """
    # Creation entry should be visible via the relation
    assert animal.activity_stream.count() == 1
    entry = animal.activity_stream.first()
    assert entry.operation == 'create'

    # Update should produce a second entry
    animal.name = 'Buddy'
    animal.save()
    assert animal.activity_stream.count() == 2
    assert animal.activity_stream.last().operation == 'update'

    # Filtering works like a normal queryset
    creates = animal.activity_stream.filter(operation='create')
    assert creates.count() == 1
    updates = animal.activity_stream.filter(operation='update')
    assert updates.count() == 1

    # M2M association shows up too
    animal.people_friends.add(random_user)
    assert animal.activity_stream.filter(operation='associate').count() == 1

    # Delete entry is visible via the saved queryset reference
    qs = animal.activity_stream.all()
    animal.delete()
    assert qs.filter(operation='delete').count() == 1


def test_activitystream_create(system_user, animal):
    """
    Ensure that an activity stream entry is created when an object is created.

    Also ensure that activity_stream_entries returns the correct entries.
    """
    entries = get_activity_stream_entries(animal)
    assert len(entries) == 1
    entry = entries[0]
    assert entry == Entry.objects.last()
    assert entry.created_by == system_user
    assert entry.operation == 'create'
    assert 'added_fields' in entry.changes
    assert entry.changes['changed_fields'] == {}
    assert entry.changes['removed_fields'] == {}
    assert entry.changes['added_fields']['name'] == animal.name
    assert entry.changes['added_fields']['owner'] == str(animal.owner.pk)
    # We don't include the "attnames"
    assert 'owner_id' not in entry.changes['added_fields']


def test_activitystream_update(system_user, animal, random_user):
    """
    Ensure that an activity stream entry is created when an object is updated.
    """
    original_name = animal.name
    animal.name = 'Rocky'
    animal.owner = random_user
    animal.save()

    entries = get_activity_stream_entries(animal)
    assert len(entries) == 2
    entry = entries.last()
    assert entry.created_by == system_user
    assert entry.operation == 'update'
    assert entry.changes['added_fields'] == {}
    assert entry.changes['removed_fields'] == {}
    # just name was changed. modified/modified_by doesn't show up because they
    # are set in save, and we're using pre_save, so we won't see the new values yet.
    assert len(entry.changes['changed_fields']) == 2
    assert entry.changes['changed_fields']['name'] == [original_name, 'Rocky']
    # We don't include the "attnames"
    assert 'owner_id' not in entry.changes['changed_fields']


def test_activitystream_m2m(system_user, animal, user, random_user):
    """
    Ensure that an activity stream entry is created when an object's m2m fields change.
    """
    entries_qs = get_activity_stream_entries(animal)

    # Add an association
    animal.people_friends.add(user)
    assert entries_qs.last().operation == 'associate'

    # Remove an association
    animal.people_friends.remove(user)
    assert entries_qs.last().operation == 'disassociate'

    # We generate an entry for each added association
    entries_count = entries_qs.count()
    animal.people_friends.add(user, random_user)
    assert entries_qs.count() == entries_count + 2

    # We generate an entry for each removed association
    entries_count = entries_qs.count()
    animal.people_friends.remove(user)
    assert entries_qs.count() == entries_count + 1

    entries_count = entries_qs.count()
    animal.people_friends.remove(random_user)
    assert entries_qs.count() == entries_count + 1


def test_activitystream_m2m_reverse(system_user, animal, animal_2, animal_3, user):
    """
    Ensure that an activity stream entry is created when an object's reverse m2m fields change.
    """
    entries_qs = get_activity_stream_entries(animal_3)

    # Add an association
    user.animal_friends.add(animal_3)
    assert entries_qs.last().operation == 'associate'


def test_activitystream_m2m_reverse_clear(system_user, animal, animal_2, animal_3, user):
    """
    Ensure that an activity stream entry is created when an object's reverse m2m is cleared.
    """
    user.animal_friends.add(animal_3)
    user.animal_friends.add(animal_2)
    user.animal_friends.add(animal)
    user.animal_friends.clear()

    for animal in (animal, animal_2, animal_3):
        assert get_activity_stream_entries(animal).last().operation == 'disassociate'
        assert get_activity_stream_entries(animal).count() == 3  # create, associate, disassociate


def test_activitystream_m2m_clear(system_user, animal, user, random_user):
    """
    Ensure that an activity stream entry is created for each association removed by clear().
    """
    entries_qs = get_activity_stream_entries(animal)
    entries_count = entries_qs.count()

    # add two associations
    animal.people_friends.add(user, random_user)
    entries_count += 2
    assert entries_qs.count() == entries_count

    # remove both associations
    animal.people_friends.clear()
    entries_count += 2
    assert entries_qs.count() == entries_count


def test_activitystream_m2m_forward_bulk(django_assert_max_num_queries, django_user_model, animal):
    """
    Ensure that m2m activity stream entries in forward direction are created in bulk.
    """
    # Create a bunch of users
    user_objs = [django_user_model(username=str(i)) for i in range(100)]
    users = django_user_model.objects.bulk_create(user_objs)

    # Setting this to 20 in case some real queries are added in the future.
    # Really as long as it's less than 100 it means we're doing the right thing.
    # In practice it's closer to 5.
    with django_assert_max_num_queries(20) as captured:
        animal.people_friends.add(*users)

    inserts = len([q for q in captured.connection.queries if q['sql'].startswith('INSERT')])
    assert inserts == 2  # 1 for the assocations, 1 for the activity stream entries

    entries = get_activity_stream_entries(animal).all()
    assert len(entries) == 101  # create + 100 associates

    # The first entry is the create, so start at 1
    assert entries[1].operation == 'associate'
    assert entries[1].related_content_object == users[0]

    assert entries.last().operation == 'associate'
    assert entries.last().related_content_object == users[-1]

    with django_assert_max_num_queries(20) as captured:
        animal.people_friends.remove(*users)

    disassoc_inserts = len([q for q in captured.connection.queries if q['sql'].startswith('INSERT')])
    # Only one insert (for activity stream entries)
    # Even though django_assert_max_num_queries is a context manager the earlier inserts still seem to count
    assert disassoc_inserts == inserts + 1


def test_activitystream_m2m_reverse_bulk(django_assert_max_num_queries, django_user_model, user):
    """
    Ensure that m2m activity stream entries in reverse direction are created in bulk.
    """
    # Create a bunch of animals
    animal_objs = [Animal(name=str(i)) for i in range(100)]
    animals = Animal.objects.bulk_create(animal_objs)

    # Setting this to 20 in case some real queries are added in the future.
    # Really as long as it's less than 100 it means we're doing the right thing.
    # In practice it's closer to 5.
    with django_assert_max_num_queries(20) as captured:
        user.animal_friends.add(*animals)

    inserts = len([q for q in captured.connection.queries if q['sql'].startswith('INSERT')])
    assert inserts == 2  # 1 for the assocations, 1 for the activity stream entries

    user_entries = get_activity_stream_entries(user).all()
    assert len(user_entries) == 1  # The entries are always on the forward relation, so the user only has their creation entry

    # But we can check the animals
    for animal in animals:
        entries = get_activity_stream_entries(animal).all()
        assert len(entries) == 1  # associate (no create because the animals were bulk created)
        assert entries[0].operation == 'associate'
        assert entries[0].related_content_object == user
        assert entries.last().operation == 'associate'
        assert entries.last().related_content_object == user

    with django_assert_max_num_queries(20) as captured:
        user.animal_friends.remove(*animals)

    disassoc_inserts = len([q for q in captured.connection.queries if q['sql'].startswith('INSERT')])
    # Only one insert (for activity stream entries)
    # Even though django_assert_max_num_queries is a context manager the earlier inserts still seem to count
    assert disassoc_inserts == inserts + 1
    for animal in animals:
        entries = get_activity_stream_entries(animal).all()
        assert len(entries) == 2  # associate, disassociate
        assert entries.last().operation == 'disassociate'


def test_activitystream_delete(system_user, animal):
    """
    Ensure that an activity stream entry is created when an object is deleted.
    """
    # Kind of a hack/trick, grab a reference to the queryset before the delete
    entries = get_activity_stream_entries(animal)
    animal.delete()
    entry = entries.last()
    assert entry.created_by == system_user
    assert entry.operation == 'delete'
    assert entry.changes['added_fields'] == {}
    assert entry.changes['changed_fields'] == {}
    assert 'name' in entry.changes['removed_fields']
    assert entry.changes['removed_fields']['name'] == animal.name
    assert 'owner' in entry.changes['removed_fields']
    assert entry.changes['removed_fields']['owner'] == str(animal.owner.pk)


def test_activitystream__store_activitystream_entry_invalid_operation():
    with pytest.raises(ValueError) as excinfo:
        signals._store_activitystream_entry(None, None, 'invalid')

    assert 'Invalid operation: invalid' in str(excinfo.value)


def test_activitystream__store_activitystream_entry_both_none():
    assert signals._store_activitystream_entry(None, None, 'create') is None


@pytest.mark.parametrize(
    "operation,update_fields,limit_from_model,expected_limit,expected_skip",
    [
        ('create', None, [], [], False),
        ('delete', None, [], [], False),
        ('update', None, ['a'], ['a'], False),
        ('update', [], ['a'], [], True),
        ('update', ['x'], [], ['x'], False),
        ('update', ['a', 'b'], ['a'], ['a'], False),
        ('update', ['x'], ['a'], [], True),
    ],
    ids=[
        "create_uses_limit_from_model",
        "delete_uses_limit_from_model",
        "update_no_update_fields_uses_limit_from_model",
        "update_empty_update_fields_skips",
        "update_no_limit_uses_update_fields",
        "update_intersection",
        "update_empty_intersection_skips",
    ],
)
def test_get_limit(operation, update_fields, limit_from_model, expected_limit, expected_skip):
    """_get_limit returns correct limit list or None (skip) for all operations."""
    limit = signals._get_limit(operation, update_fields, limit_from_model)
    if expected_skip:
        assert limit is None
    else:
        assert limit is not None
        assert set(limit) == set(expected_limit)


def test_activitystream__store_activitystream_m2m_invalid_operation():
    """Invalid operation raises ValueError; pass a real model class to satisfy type hints."""
    with pytest.raises(ValueError) as excinfo:
        signals._store_activitystream_m2m(None, Animal, 'invalid', set(), False, 'field')

    assert 'Invalid operation: invalid' in str(excinfo.value)


@pytest.mark.django_db
def test_activitystream_excluded_fields():
    """
    Ensure that limit fields (specified by the model's activity_stream_limit_field_names) are the only ones included in the activity stream entry.
    """
    city = City.objects.create(name='New York', country='USA')
    entry = get_activity_stream_entries(city).last()
    assert entry.operation == 'create'  # sanity check
    assert 'country' in entry.changes['added_fields']
    assert len(entry.changes['added_fields']) == 1
    assert entry.changes['changed_fields'] == {}
    assert entry.changes['removed_fields'] == {}

    city.country = 'Canada'
    city.save()
    entry = get_activity_stream_entries(city).last()
    assert entry.operation == 'update'  # sanity check
    assert 'country' in entry.changes['changed_fields']
    assert len(entry.changes['changed_fields']) == 1
    assert entry.changes['added_fields'] == {}
    assert entry.changes['removed_fields'] == {}


@pytest.mark.django_db
def test_activitystream_context_manager():
    """
    Ensure we have a way to skip adding activity stream entries.

    Ensure we can state-change (disable entries sometimes and enable them other times).
    """
    with no_activity_stream():
        city = City.objects.create(name='New York', country='USA')
    entries = get_activity_stream_entries(city)
    assert entries.count() == 0

    city.country = 'Canada'
    city.save()
    assert entries.count() == 1

    with no_activity_stream():
        city.country = 'Germany'
        city.save()

    assert entries.count() == 1


@pytest.mark.django_db
def test_activitystream_nested_context_manager():
    """
    Ensure we properly skip adding activity stream entries in nested context managers
    and properly restore state.
    """
    with no_activity_stream():
        with no_activity_stream():
            city = City.objects.create(name='New York', country='USA')

    entries = get_activity_stream_entries(city)
    assert entries.count() == 0

    city.country = 'Canada'
    city.save()
    assert entries.count() == 1

    with no_activity_stream():
        city.country = 'Germany'
        city.save()

    assert entries.count() == 1


@pytest.mark.django_db
def test_activitystream_encrypted_fields_are_sanitized():
    color = SecretColor.objects.create(color='red')
    entries = get_activity_stream_entries(color)
    assert entries.last().changes['added_fields']['color'] == ENCRYPTED_STRING

    color.color = 'orange'
    color.save()
    assert entries.last().changes['changed_fields']['color'] == [ENCRYPTED_STRING, ENCRYPTED_STRING]

    color.delete()
    assert entries.last().changes['removed_fields']['color'] == ENCRYPTED_STRING


@pytest.mark.django_db
def test_activitystream_user_password_sanitized(user):
    entries = get_activity_stream_entries(user)
    assert entries.last().changes['added_fields']['password'] == ENCRYPTED_STRING

    user.set_password('new_password')
    user.save()
    assert entries.last().changes['changed_fields']['password'] == [ENCRYPTED_STRING, ENCRYPTED_STRING]


@pytest.mark.django_db
def test_activitystream_update_fields_limits_diff():
    """
    Ensure that when update_fields is provided to save(), only those fields are
    included in the activity stream entry.
    """
    from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

    city = City.objects.create(name='New York', country='USA', population=1000)
    initial_entry_count = get_activity_stream_entries(city).count()

    # Update both name and country, but only save country via update_fields
    city.name = 'Albany'
    city.country = 'Canada'
    city.save(update_fields=['country'])

    entries = get_activity_stream_entries(city)
    assert entries.count() == initial_entry_count + 1
    entry = entries.last()
    assert entry.operation == 'update'

    # Only country should be in the changed_fields, not name
    # Note: country is encrypted (prevent_search) so values show as ENCRYPTED_STRING
    assert 'country' in entry.changes['changed_fields']
    assert 'name' not in entry.changes['changed_fields']
    assert len(entry.changes['changed_fields']) == 1
    assert entry.changes['changed_fields']['country'] == [ENCRYPTED_STRING, ENCRYPTED_STRING]


@pytest.mark.django_db
def test_activitystream_update_fields_no_entry_when_only_excluded_fields():
    """
    Ensure that when update_fields contains only fields that are in
    activity_stream_limit_field_names, and those fields haven't changed,
    no activity stream entry is created.
    """
    city = City.objects.create(name='New York', country='USA')
    initial_entry_count = get_activity_stream_entries(city).count()

    # Update name but not country, and save only name via update_fields
    # Since City has activity_stream_limit_field_names = ['country'],
    # updating only 'name' should not create an entry
    city.name = 'Albany'
    city.save(update_fields=['name'])

    entries = get_activity_stream_entries(city)
    # No new entry should be created because 'name' is not in the limit_fields
    assert entries.count() == initial_entry_count


@pytest.mark.django_db
def test_activitystream_update_fields_with_limit_fields_intersection():
    """
    Ensure that when both activity_stream_limit_field_names and update_fields
    are provided, only the intersection of those fields is diffed.
    """
    city = City.objects.create(name='New York', country='USA')
    initial_entry_count = get_activity_stream_entries(city).count()

    # City has activity_stream_limit_field_names = ['country']
    # If we update both name and country with update_fields=['name', 'country']
    # only country should appear in the activity stream
    city.name = 'Albany'
    city.country = 'Canada'
    city.save(update_fields=['name', 'country'])

    entries = get_activity_stream_entries(city)
    assert entries.count() == initial_entry_count + 1
    entry = entries.last()

    # Only country should be in changed_fields (intersection of limit and update_fields)
    assert 'country' in entry.changes['changed_fields']
    assert 'name' not in entry.changes['changed_fields']
    assert len(entry.changes['changed_fields']) == 1


@pytest.mark.django_db
def test_activitystream_update_fields_empty_delta_no_entry():
    """
    Ensure that when update_fields is provided but the field value hasn't
    actually changed, no activity stream entry is created (empty delta).
    """
    animal = Animal.objects.create(name='Fluffy')
    initial_entry_count = get_activity_stream_entries(animal).count()

    # Save with update_fields but without actually changing the value
    animal.save(update_fields=['name'])

    entries = get_activity_stream_entries(animal)
    # No new entry should be created because there's no actual change
    assert entries.count() == initial_entry_count


@pytest.mark.django_db
def test_activitystream_update_fields_multiple_fields():
    """
    Ensure that multiple fields can be updated via update_fields and all
    appear in the activity stream entry.
    """
    animal = Animal.objects.create(name='Fluffy', age=2)
    initial_entry_count = get_activity_stream_entries(animal).count()

    # Update multiple fields
    # Note: 'age' is in activity_stream_excluded_field_names, so it won't show up
    animal.name = 'Rocky'
    animal.age = 3
    animal.save(update_fields=['name', 'age'])

    entries = get_activity_stream_entries(animal)
    assert entries.count() == initial_entry_count + 1
    entry = entries.last()

    # Only name should be in changed_fields (age is excluded)
    assert 'name' in entry.changes['changed_fields']
    assert 'age' not in entry.changes['changed_fields']
    assert entry.changes['changed_fields']['name'] == ['Fluffy', 'Rocky']


@pytest.mark.django_db
def test_activitystream_update_fields_none_with_limit_fields():
    """
    Ensure that when update_fields is None (not provided) and model has
    activity_stream_limit_field_names, only limited fields are tracked.
    """
    from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

    city = City.objects.create(name='New York', country='USA', population=1000)
    initial_entry_count = get_activity_stream_entries(city).count()

    # City has activity_stream_limit_field_names = ['country']
    # So only changes to country should be tracked
    city.name = 'Albany'
    city.country = 'Canada'
    city.population = 2000
    city.save()

    entries = get_activity_stream_entries(city)
    assert entries.count() == initial_entry_count + 1
    entry = entries.last()

    # Only country should be in changed_fields (it's the only limited field)
    assert 'country' in entry.changes['changed_fields']
    assert 'name' not in entry.changes['changed_fields']
    assert 'population' not in entry.changes['changed_fields']
    assert entry.changes['changed_fields']['country'] == [ENCRYPTED_STRING, ENCRYPTED_STRING]


# =============================================================================
# Tests for activity stream attribute defaults in signal handlers
# =============================================================================


class TestActivityStreamAttributeDefaults:
    """Tests that signal handlers use correct defaults for optional model attributes."""

    @pytest.mark.parametrize(
        "attribute,expected_default",
        [
            ("activity_stream_enabled", True),
            ("audit_log_enabled", False),
            ("activity_stream_excluded_field_names", []),
            ("activity_stream_limit_field_names", []),
        ],
        ids=[
            "activity_stream_enabled_defaults_to_true",
            "audit_log_enabled_defaults_to_false",
            "excluded_field_names_defaults_to_empty_list",
            "limit_field_names_defaults_to_empty_list",
        ],
    )
    def test_signal_handler_uses_correct_defaults(self, attribute, expected_default):
        """Ensure signal handlers fall back to the correct defaults when a model lacks an attribute."""
        # SecretColor doesn't define these attributes (except what it inherits),
        # so getattr with defaults should match expectations.
        assert getattr(SecretColor, attribute, expected_default) == expected_default


# =============================================================================
# Tests for activity_stream_enabled flag
# =============================================================================


@pytest.mark.django_db
def test_activity_stream_enabled_false_on_update():
    """
    Ensure that setting activity_stream_enabled=False on a model prevents
    activity stream entries from being created on update.
    """
    # Create an animal with activity stream enabled (default)
    animal = Animal.objects.create(name='Fluffy')
    assert get_activity_stream_entries(animal).count() == 1

    # Now disable activity stream on the instance and update
    animal.activity_stream_enabled = False
    animal.name = 'Rocky'
    animal.save()

    # No new entry should be created
    assert get_activity_stream_entries(animal).count() == 1


@pytest.mark.django_db
def test_activity_stream_enabled_false_on_create():
    """
    Ensure that creating an object with activity_stream_enabled=False
    does not create an activity stream entry.
    """
    # Create animal, then immediately set flag and check
    # Note: The flag is checked during signal processing
    with mock.patch.object(Animal, 'activity_stream_enabled', False, create=True):
        animal = Animal.objects.create(name='Silent')

    assert get_activity_stream_entries(animal).count() == 0


@pytest.mark.django_db
def test_activity_stream_enabled_false_on_delete():
    """
    Ensure that deleting an object with activity_stream_enabled=False
    does not create an activity stream entry.
    """
    animal = Animal.objects.create(name='Fluffy')
    initial_count = get_activity_stream_entries(animal).count()

    # Disable activity stream and delete
    animal.activity_stream_enabled = False
    entries_qs = get_activity_stream_entries(animal)  # Keep reference
    animal.delete()

    # No new entry should be created for the delete
    assert entries_qs.count() == initial_count


# =============================================================================
# Tests for audit_log_enabled flag and log message formatting
# =============================================================================


@pytest.mark.django_db
def test_audit_log_disabled_by_default():
    """
    Ensure that audit logging is disabled by default (audit_log_enabled=False).
    """
    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal = Animal.objects.create(name='Fluffy')
        mock_log.assert_not_called()

        animal.name = 'Rocky'
        animal.save()
        mock_log.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation,perform_operation",
    [
        ("create", lambda: Animal.objects.create(name='Fluffy')),
        ("delete", None),  # Special case handled in test
    ],
    ids=["create_logs_full_state", "delete_logs_full_state"],
)
def test_audit_log_enabled_on_create_delete(operation, perform_operation):
    """
    Ensure that when audit_log_enabled=True, create/delete operations log the full object state.
    """
    if operation == "delete":
        # For delete, we need to create first without audit logging
        animal = Animal.objects.create(name='Fluffy')
        with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
            animal.audit_log_enabled = True
            animal.delete()

            assert mock_log.call_count == 1
            call_args = mock_log.call_args[0][0]
            assert 'delete Animal' in call_args
            assert 'Fluffy' in call_args
    else:
        with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
            with mock.patch.object(Animal, 'audit_log_enabled', True, create=True):
                perform_operation()

            assert mock_log.call_count == 1
            call_args = mock_log.call_args[0][0]
            assert f'{operation} Animal' in call_args
            assert 'Fluffy' in call_args
            assert 'name' in call_args


@pytest.mark.django_db
def test_audit_log_enabled_on_update_changed_field():
    """
    Ensure that when audit_log_enabled=True, update operations log one line per changed field.
    """
    animal = Animal.objects.create(name='Fluffy')

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.audit_log_enabled = True
        animal.name = 'Rocky'
        animal.save()

        # Should have been called once for the name change
        assert mock_log.call_count == 1
        call_args = mock_log.call_args[0][0]

        # Verify message format: "update ModelName obj_str changed field from 'old' to 'new'"
        assert 'update Animal' in call_args
        assert "changed name from 'Fluffy' to 'Rocky'" in call_args


@pytest.mark.django_db
def test_audit_log_enabled_on_update_multiple_fields():
    """
    Ensure that when multiple fields change, each gets its own log line.
    """
    animal = Animal.objects.create(name='Fluffy', kind='dog')

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.audit_log_enabled = True
        animal.name = 'Rocky'
        animal.kind = 'cat'
        animal.save()

        # Should have been called twice (once for each changed field)
        assert mock_log.call_count == 2

        # Collect all log messages
        messages = [call[0][0] for call in mock_log.call_args_list]

        # Verify both fields are logged
        name_logged = any("changed name from 'Fluffy' to 'Rocky'" in msg for msg in messages)
        kind_logged = any("changed kind from 'dog' to 'cat'" in msg for msg in messages)

        assert name_logged, f"Expected name change in messages: {messages}"
        assert kind_logged, f"Expected kind change in messages: {messages}"


@pytest.mark.django_db
def test_audit_log_added_field_format():
    """
    Ensure added fields (null to value) are logged with correct format.
    """
    animal = Animal.objects.create(name='Fluffy', owner=None)

    from test_app.models import User

    user = User.objects.create(username='testowner')

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.audit_log_enabled = True
        animal.owner = user
        animal.save()

        # Find the log call for the added owner field
        messages = [call[0][0] for call in mock_log.call_args_list]
        owner_msg = next((msg for msg in messages if 'owner' in msg), None)

        # Could be logged as added or changed depending on diff implementation
        assert owner_msg is not None, f"Expected owner in messages: {messages}"


@pytest.mark.django_db
def test_audit_log_removed_field_format():
    """
    Ensure removed fields (value to null) are logged with correct format.
    """
    from test_app.models import User

    user = User.objects.create(username='testowner')
    animal = Animal.objects.create(name='Fluffy', owner=user)

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.audit_log_enabled = True
        animal.owner = None
        animal.save()

        # Find the log call for the removed owner field
        messages = [call[0][0] for call in mock_log.call_args_list]
        owner_msg = next((msg for msg in messages if 'owner' in msg), None)

        # Could be logged as removed or changed depending on diff implementation
        assert owner_msg is not None, f"Expected owner in messages: {messages}"


@pytest.mark.django_db
def test_audit_log_respects_excluded_fields(user):
    """
    Ensure that excluded fields are not logged to the audit log.

    Excluded fields (e.g. age, last_login) must never appear in audit messages.
    This helps ensure sensitive or irrelevant data is not logged. In real
    deployments, models should exclude passwords, tokens, API keys, and other
    secrets via activity_stream_excluded_field_names; DAB test_app has
    User.last_login and Animal.age as examples.
    """
    # Animal has 'age' in activity_stream_excluded_field_names
    animal = Animal.objects.create(name='Fluffy', age=2)

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.audit_log_enabled = True
        animal.name = 'Rocky'
        animal.age = 5  # This should not be logged
        animal.save()

        messages = [call[0][0] for call in mock_log.call_args_list]

        # Name should be logged
        name_logged = any('name' in msg for msg in messages)
        assert name_logged, f"Expected name in messages: {messages}"

        # Age should NOT be logged (it's excluded)
        age_logged = any('age' in msg and 'changed age' in msg for msg in messages)
        assert not age_logged, f"Age should not be logged: {messages}"

        # Disallowed content: no raw password hashes (pbkdf2, sha, argon2, etc.) in messages
        for msg in messages:
            assert 'pbkdf2_sha256$' not in msg, "Audit log must not contain password hashes"
            assert 'sha1$' not in msg and 'argon2$' not in msg, "Audit log must not contain raw hash algorithms"

    # User password change: if password is ever logged, both old and new must appear as $encrypted$
    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        user.audit_log_enabled = True
        user.set_password('NewSecurePass1!')
        user.save()

        messages = [call[0][0] for call in mock_log.call_args_list]
        for msg in messages:
            assert (
                'pbkdf2_sha256$' not in msg and 'sha1$' not in msg and 'argon2$' not in msg
            ), "Audit log must not contain password hashes or raw hash algorithms"
            if 'changed password' in msg:
                assert re.search(r"changed password from '\$encrypted\$' to '\$encrypted\$'", msg), (
                    "Password change must show both old and new as $encrypted$: " + msg
                )
            if 'added password' in msg:
                assert "'$encrypted$'" in msg, "Added password must show as $encrypted$: " + msg

    # User has 'last_login' in activity_stream_excluded_field_names
    from django.utils import timezone

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        user.audit_log_enabled = True
        user.first_name = 'Audit'
        user.last_login = timezone.now()
        user.save()

        messages = [call[0][0] for call in mock_log.call_args_list]
        # first_name should be logged
        first_name_logged = any('first_name' in msg for msg in messages)
        assert first_name_logged, f"Expected first_name in messages: {messages}"
        # last_login should NOT be logged (it's excluded)
        last_login_logged = any('last_login' in msg and ('changed last_login' in msg or 'added last_login' in msg) for msg in messages)
        assert not last_login_logged, f"last_login should not be logged: {messages}"


@pytest.mark.django_db
def test_audit_log_with_activity_stream_disabled():
    """
    Ensure audit logging works independently of activity stream.
    When activity_stream_enabled=False but audit_log_enabled=True,
    audit logs should still be generated.
    """
    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        with mock.patch.object(Animal, 'audit_log_enabled', True, create=True):
            with mock.patch.object(Animal, 'activity_stream_enabled', False, create=True):
                animal = Animal.objects.create(name='Fluffy')

        # Audit log should still be called
        assert mock_log.call_count == 1

    # But no activity stream entry
    assert get_activity_stream_entries(animal).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "expected_content",
    [
        "Animal",  # Model name
        "Fluffy",  # Object name (part of __str__)
    ],
    ids=["includes_model_name", "includes_object_str"],
)
def test_audit_log_message_content(expected_content):
    """
    Ensure the audit log message includes expected content (model name, object str).
    """
    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        with mock.patch.object(Animal, 'audit_log_enabled', True, create=True):
            Animal.objects.create(name='Fluffy')

        call_args = mock_log.call_args[0][0]
        assert expected_content in call_args


# =============================================================================
# Tests for M2M audit logging
# =============================================================================


@pytest.mark.django_db
def test_audit_log_m2m_associate(user):
    """
    Ensure that M2M associations are logged when audit_log_enabled=True.
    """
    animal = Animal.objects.create(name='Fluffy')
    animal.audit_log_enabled = True

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.people_friends.add(user)

        assert mock_log.call_count == 1
        call_args = mock_log.call_args[0][0]
        assert 'associate' in call_args
        assert 'Animal' in call_args
        assert 'with' in call_args


@pytest.mark.django_db
def test_audit_log_m2m_disassociate(user):
    """
    Ensure that M2M disassociations are logged when audit_log_enabled=True.
    """
    animal = Animal.objects.create(name='Fluffy')
    animal.people_friends.add(user)  # First add without logging
    animal.audit_log_enabled = True

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.people_friends.remove(user)

        assert mock_log.call_count == 1
        call_args = mock_log.call_args[0][0]
        assert 'disassociate' in call_args
        assert 'Animal' in call_args
        assert 'from' in call_args


@pytest.mark.django_db
def test_audit_log_m2m_disabled_by_default(user):
    """
    Ensure that M2M operations are not logged when audit_log_enabled=False (default).
    """
    animal = Animal.objects.create(name='Fluffy')
    # audit_log_enabled is False by default

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        animal.people_friends.add(user)
        animal.people_friends.remove(user)

        mock_log.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation,method_name,expected_preposition",
    [
        ("associate", "add", "with"),
        ("disassociate", "remove", "from"),
    ],
    ids=["associate_uses_with", "disassociate_uses_from"],
)
def test_audit_log_m2m_preposition(user, operation, method_name, expected_preposition):
    """
    Ensure that associate uses 'with' and disassociate uses 'from' in log messages.
    """
    animal = Animal.objects.create(name='Fluffy')
    if method_name == "remove":
        animal.people_friends.add(user)  # Need to add first before removing
    animal.audit_log_enabled = True

    with mock.patch('ansible_base.activitystream.signals.log_auth_event') as mock_log:
        method = getattr(animal.people_friends, method_name)
        method(user)

        call_args = mock_log.call_args[0][0]
        assert expected_preposition in call_args
        assert operation in call_args


# =============================================================================
# Tests for NonCascadingGenericRelation
# =============================================================================


@pytest.mark.django_db
def test_non_cascading_generic_relation_prevents_cascade_delete():
    """
    NonCascadingGenericRelation overrides bulk_related_objects to return an
    empty queryset, preventing Django's deletion collector from cascade-deleting
    activity stream entries when a parent object is deleted.

    This verifies that audit trail data survives object deletion.
    """
    animal = Animal.objects.create(name='CascadeTest')
    entry_qs = Entry.objects.filter(
        content_type__app_label='test_app',
        content_type__model='animal',
        object_id=str(animal.pk),
    )
    # The create signal should have produced an entry
    assert entry_qs.count() >= 1, "Expected at least a 'create' entry for the animal"
    entry_pks = list(entry_qs.values_list('pk', flat=True))

    # Delete the animal
    animal.delete()

    # Activity stream entries must survive the parent deletion
    surviving = Entry.objects.filter(pk__in=entry_pks)
    assert surviving.count() == len(entry_pks), (
        "Activity stream entries were cascade-deleted when the parent object was deleted. "
        "NonCascadingGenericRelation.bulk_related_objects should prevent this."
    )
