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

    def filter(self, query):
        call_index = len(self.filters)
        self.filters.append(query)
        if call_index < 2:
            return FakeQuerySet([])
        start = (call_index - 2) * 1000
        return FakeQuerySet(self.objects[start : start + 1000])


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
        for index in range(1001)
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

    assert len(assignments) == 1001
    assert assignments[0].object_ansible_id == 'ansible-0'
    assert assignments[1].object_ansible_id is None
    assert len(manager.filters) == 4
    safe_bulk_create.assert_called_once_with(assignment_class, assignments, ignore_conflicts=True)
    audit_log.assert_called_once_with(assignments, set())


def _record_created(model, objects):
    for index, obj in enumerate(objects, start=1):
        obj.pk = index
    model.objects.objects = list(objects)
