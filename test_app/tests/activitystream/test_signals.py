#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import pytest

import ansible_base.activitystream.signals as signals
from ansible_base.activitystream.models import Entry
from test_app.models import Animal, City


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
    # just name was changed. modified/modified_by doesn't show up because they
    # are set in save, and we're using pre_save, so we won't see the new values yet.
    assert len(entry.changes['changed_fields']) == 1
    assert entry.changes['changed_fields']['name'] == [original_name, 'Rocky']


def test_activitystream_m2m(system_user, animal, user, random_user):
    """
    Ensure that an activity stream entry is created when an object's m2m fields change.
    """
    entries_qs = animal.activity_stream_entries

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
    entries_qs = animal_3.activity_stream_entries

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
        assert animal.activity_stream_entries.last().operation == 'disassociate'
        assert animal.activity_stream_entries.count() == 3  # create, associate, disassociate


def test_activitystream_m2m_clear(system_user, animal, user, random_user):
    """
    Ensure that an activity stream entry is created for each association removed by clear().
    """
    entries_qs = animal.activity_stream_entries
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

    entries = animal.activity_stream_entries.all()
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

    user_entries = user.activity_stream_entries.all()
    assert len(user_entries) == 1  # The entries are always on the forward relation, so the user only has their creation entry

    # But we can check the animals
    for animal in animals:
        entries = animal.activity_stream_entries.all()
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
        entries = animal.activity_stream_entries.all()
        assert len(entries) == 2  # associate, disassociate
        assert entries.last().operation == 'disassociate'


def test_activitystream_delete(system_user, animal):
    """
    Ensure that an activity stream entry is created when an object is deleted.
    """
    # Kind of a hack/trick, grab a reference to the queryset before the delete
    entries = animal.activity_stream_entries
    animal.delete()
    entry = entries.last()
    assert entry.created_by == system_user
    assert entry.operation == 'delete'
    assert entry.changes['added_fields'] == {}
    assert entry.changes['changed_fields'] == {}
    assert 'name' in entry.changes['removed_fields']
    assert entry.changes['removed_fields']['name'] == animal.name
    assert 'owner' in entry.changes['removed_fields']
    assert entry.changes['removed_fields']['owner'] == animal.owner.username


def test_activitystream__store_activitystream_entry_invalid_operation():
    with pytest.raises(ValueError) as excinfo:
        signals._store_activitystream_entry(None, None, 'invalid')

    assert 'Invalid operation: invalid' in str(excinfo.value)


def test_activitystream__store_activitystream_entry_both_none():
    assert signals._store_activitystream_entry(None, None, 'create') is None


def test_activitystream__store_activitystream_m2m_invalid_operation():
    with pytest.raises(ValueError) as excinfo:
        signals._store_activitystream_m2m(None, None, 'invalid', [], False, 'field')

    assert 'Invalid operation: invalid' in str(excinfo.value)


@pytest.mark.django_db
def test_activitystream_excluded_fields():
    """
    Ensure that limit fields (specified by the model's activity_stream_limit_field_names) are the only ones included in the activity stream entry.
    """
    city = City.objects.create(name='New York', country='USA')
    entry = city.activity_stream_entries.last()
    assert entry.operation == 'create'  # sanity check
    assert 'country' in entry.changes['added_fields']
    assert len(entry.changes['added_fields']) == 1
    assert entry.changes['changed_fields'] == {}
    assert entry.changes['removed_fields'] == {}

    city.country = 'Canada'
    city.save()
    entry = city.activity_stream_entries.last()
    assert entry.operation == 'update'  # sanity check
    assert 'country' in entry.changes['changed_fields']
    assert len(entry.changes['changed_fields']) == 1
    assert entry.changes['added_fields'] == {}
    assert entry.changes['removed_fields'] == {}
