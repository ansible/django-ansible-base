from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ansible_base.rbac import pipeline


class FakeQuerySet:
    def __init__(self, objects):
        self.objects = objects

    def values_list(self, field_name, flat=False):
        assert field_name == 'pk'
        assert flat is True
        return [obj.pk for obj in self.objects]

    def __iter__(self):
        return iter(self.objects)


class FakeManager:
    def __init__(self):
        self.objects = []
        self.filters = []
        self.chunk_size = pipeline.SQL_SERVER_PAIR_FILTER_BATCH_SIZE

    def filter(self, query):
        call_index = len(self.filters)
        self.filters.append(query)
        if call_index < 2:
            return FakeQuerySet([])
        start = (call_index - 2) * self.chunk_size
        return FakeQuerySet(self.objects[start : start + self.chunk_size])


class FakeAssignment:
    def __init__(self, **fields):
        self.__dict__.update(fields)
        self.pk = None


@pytest.mark.parametrize('actor_field', ['user', 'team'])
def test_create_assignments_chunks_large_mssql_batches(monkeypatch, actor_field):
    assignment_class = type(f'Fake{actor_field.title()}Assignment', (FakeAssignment,), {})
    manager = FakeManager()
    assignment_class.objects = manager
    assignment_model_name = 'RoleUserAssignment' if actor_field == 'user' else 'RoleTeamAssignment'
    monkeypatch.setattr(pipeline, assignment_model_name, assignment_class)
    monkeypatch.setattr(pipeline, 'connection', SimpleNamespace(vendor='microsoft'))
    monkeypatch.setattr(pipeline, 'current_user_or_system_user', lambda: 'system-user')
    audit_log = Mock()
    monkeypatch.setattr(pipeline, '_audit_log_created', audit_log)

    safe_bulk_create = Mock(side_effect=lambda model, objects, **kwargs: _record_created(model, objects))
    monkeypatch.setattr(pipeline, 'bulk_create_db_safe', safe_bulk_create)

    role_definition = SimpleNamespace(pk=1)
    content_type = SimpleNamespace(app_label='test_app', model='inventory')
    resolved = [
        pipeline.ResolvedAssignment(
            role_definition=role_definition,
            actor=SimpleNamespace(pk=index),
            content_type=content_type,
            object_id=str(index),
            parent_reference='',
        )
        for index in range(pipeline.SQL_SERVER_PAIR_FILTER_BATCH_SIZE + 1)
    ]
    lookup = {(role_definition.pk, item.object_id): SimpleNamespace(pk=item.object_id) for item in resolved}
    object_ansible_ids = {('test_app', 'inventory', '0'): 'ansible-0'}

    assignments = pipeline._create_assignments(
        resolved if actor_field == 'user' else [],
        resolved if actor_field == 'team' else [],
        lookup,
        object_ansible_ids,
        fire_signals_on_create=False,
    )

    assert len(assignments) == pipeline.SQL_SERVER_PAIR_FILTER_BATCH_SIZE + 1
    assert assignments[0].object_ansible_id == 'ansible-0'
    assert assignments[1].object_ansible_id is None
    assert len(manager.filters) == 4
    safe_bulk_create.assert_called_once_with(assignment_class, assignments, ignore_conflicts=True)
    audit_log.assert_called_once_with(assignments, set())


def test_find_assignments_returns_empty_when_no_roles_match():
    resolved = [SimpleNamespace(role_definition=SimpleNamespace(pk=1), object_id='1', actor=SimpleNamespace(pk=1))]
    model = SimpleNamespace(objects=SimpleNamespace(filter=Mock()))

    assert pipeline._find_assignments(resolved, {}, model, 'user') == []
    model.objects.filter.assert_not_called()


def test_pair_filter_chunks_stay_under_sql_server_parameter_limit(monkeypatch):
    monkeypatch.setattr(pipeline, 'connection', SimpleNamespace(vendor='microsoft'))
    pairs = [(index, index) for index in range(2101)]

    filters = list(pipeline._pair_filter_chunks(pairs, 'object_role_id', 'user_id'))

    assert len(filters) > 1
    assert sum(len(query_filter.children) for query_filter in filters) == len(pairs)
    assert all(len(query_filter.children) * pipeline.PARAMETERS_PER_PAIR_FILTER < pipeline.SQL_SERVER_MAX_QUERY_PARAMETERS for query_filter in filters)


def test_find_assignments_returns_matching_objects_for_small_batches(monkeypatch):
    monkeypatch.setattr(pipeline, 'connection', SimpleNamespace(vendor='postgresql'))
    role_definition = SimpleNamespace(pk=1)
    actor = SimpleNamespace(pk=2)
    resolved = [pipeline.ResolvedAssignment(role_definition, actor, None, '3', '')]
    object_role = SimpleNamespace(pk=4)
    expected = [SimpleNamespace(pk=5)]
    model = SimpleNamespace(objects=SimpleNamespace(filter=Mock(return_value=expected)))

    result = pipeline._find_assignments(resolved, {(1, '3'): object_role}, model, 'user')

    assert result == expected
    model.objects.filter.assert_called_once()


def test_find_assignments_chunks_large_mssql_batches(monkeypatch):
    monkeypatch.setattr(pipeline, 'connection', SimpleNamespace(vendor='microsoft'))
    role_definition = SimpleNamespace(pk=1)
    resolved = [
        pipeline.ResolvedAssignment(role_definition, SimpleNamespace(pk=index), None, str(index), '')
        for index in range(pipeline.SQL_SERVER_PAIR_FILTER_BATCH_SIZE + 1)
    ]
    lookup = {(1, item.object_id): SimpleNamespace(pk=index) for index, item in enumerate(resolved)}
    first_batch = [SimpleNamespace(pk=1)]
    second_batch = [SimpleNamespace(pk=2)]
    model = SimpleNamespace(objects=SimpleNamespace(filter=Mock(side_effect=[first_batch, second_batch])))

    result = pipeline._find_assignments(resolved, lookup, model, 'user')

    assert result == first_batch + second_batch
    assert model.objects.filter.call_count == 2


def _record_created(model, objects):
    for index, obj in enumerate(objects, start=1):
        obj.pk = index
    model.objects.objects = list(objects)


def test_find_assignments_returns_empty_when_no_lookup_matches():
    resolved = [pipeline.ResolvedAssignment(SimpleNamespace(pk=1), SimpleNamespace(pk=2), None, '3', '')]
    model = SimpleNamespace(objects=SimpleNamespace(filter=Mock()))

    assert pipeline._find_assignments(resolved, {}, model, 'user') == []
    model.objects.filter.assert_not_called()


def test_find_assignments_uses_one_filter_for_small_batches(monkeypatch):
    monkeypatch.setattr(pipeline, 'connection', SimpleNamespace(vendor='postgresql'))
    resolved = [pipeline.ResolvedAssignment(SimpleNamespace(pk=1), SimpleNamespace(pk=2), None, '3', '')]
    role = SimpleNamespace(pk=4)
    found = [SimpleNamespace(pk=5)]
    manager = SimpleNamespace(filter=Mock(return_value=found))

    result = pipeline._find_assignments(resolved, {(1, '3'): role}, SimpleNamespace(objects=manager), 'user')

    assert result == found
    manager.filter.assert_called_once()
