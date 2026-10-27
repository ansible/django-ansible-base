from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import IntegrityError
from django.db.models.signals import post_save, pre_save

from ansible_base.lib.utils import db


class FakeManager:
    db = 'default'

    def __init__(self, result=None):
        self.bulk_create = Mock(return_value=result)
        self.using_calls = []
        self.alias_manager = self

    def using(self, alias):
        self.using_calls.append(alias)
        return self.alias_manager


def make_model(manager):
    return type('FakeModel', (), {'objects': manager})


def make_object(save_side_effect=None):
    obj = SimpleNamespace(_state=SimpleNamespace(db=None, adding=True))
    obj.save = Mock(side_effect=save_side_effect)
    return obj


def set_connection_features(monkeypatch, *, can_return_rows=True, supports_ignore_conflicts=True):
    connection = SimpleNamespace(
        features=SimpleNamespace(
            can_return_rows_from_bulk_insert=can_return_rows,
            supports_ignore_conflicts=supports_ignore_conflicts,
        ),
        needs_rollback=False,
    )
    monkeypatch.setattr(db, 'connections', {'default': connection, 'replica': connection})
    return connection


def patch_savepoints(monkeypatch, savepoint_ids=(1,)):
    savepoint = Mock(side_effect=savepoint_ids)
    commit = Mock()
    rollback = Mock()
    monkeypatch.setattr(db.transaction, 'savepoint', savepoint)
    monkeypatch.setattr(db.transaction, 'savepoint_commit', commit)
    monkeypatch.setattr(db.transaction, 'savepoint_rollback', rollback)
    return savepoint, commit, rollback


def test_bulk_create_with_returning_rows_uses_manager_and_marks_database(monkeypatch):
    set_connection_features(monkeypatch)
    obj = make_object()
    manager = FakeManager(result=[obj])
    model = make_model(manager)

    created = db.bulk_create_db_safe(model, [obj], ignore_conflicts=False)

    manager.bulk_create.assert_called_once_with([obj], ignore_conflicts=False)
    assert created == [obj]
    assert obj._state.db == 'default'


def test_bulk_create_with_explicit_alias_uses_alias_manager(monkeypatch):
    set_connection_features(monkeypatch)
    obj = make_object()
    default_manager = FakeManager()
    alias_manager = FakeManager(result=[obj])
    default_manager.alias_manager = alias_manager
    model = make_model(default_manager)

    created = db.bulk_create_db_safe(model, [obj], ignore_conflicts=False, using='replica')

    assert default_manager.using_calls == ['replica']
    alias_manager.bulk_create.assert_called_once_with([obj], ignore_conflicts=False)
    assert created == [obj]
    assert obj._state.db == 'replica'


def test_ignore_conflicts_with_native_support_uses_manager(monkeypatch):
    set_connection_features(monkeypatch, supports_ignore_conflicts=True)
    obj = make_object()
    manager = FakeManager(result=[obj])
    model = make_model(manager)

    created = db.bulk_create_db_safe(model, [obj], ignore_conflicts=True)

    manager.bulk_create.assert_called_once_with([obj], ignore_conflicts=True)
    assert created == [obj]
    assert obj._state.db == 'default'


def test_bulk_create_without_returning_rows_saves_objects_without_signals(monkeypatch):
    set_connection_features(monkeypatch, can_return_rows=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ('batch-1',))
    pre_save_receivers = pre_save.receivers
    post_save_receivers = post_save.receivers
    objects = [make_object(), make_object()]
    manager = FakeManager()
    model = make_model(manager)

    created = db.bulk_create_db_safe(model, objects, ignore_conflicts=False)

    manager.bulk_create.assert_not_called()
    assert created == objects
    assert savepoint.call_count == 1
    commit.assert_called_once_with('batch-1', using='default')
    rollback.assert_not_called()
    assert [obj._state.db for obj in objects] == ['default', 'default']
    assert all(obj._state.adding is False for obj in objects)
    assert pre_save.receivers == pre_save_receivers
    assert post_save.receivers == post_save_receivers


def test_bulk_create_without_returning_rows_saves_in_multiple_batches(monkeypatch):
    set_connection_features(monkeypatch, can_return_rows=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ('batch-1', 'batch-2'))
    objects = [make_object() for _ in range(51)]
    model = make_model(FakeManager())

    created = db.bulk_create_db_safe(model, objects, ignore_conflicts=False)

    assert created == objects
    assert savepoint.call_count == 2
    assert commit.call_count == 2
    rollback.assert_not_called()
    assert all(obj._state.db == 'default' and obj._state.adding is False for obj in objects)


def test_bulk_create_without_returning_rows_rolls_back_failed_batch(monkeypatch):
    set_connection_features(monkeypatch, can_return_rows=False)
    _, commit, rollback = patch_savepoints(monkeypatch, ('batch-1',))
    pre_save_receivers = pre_save.receivers
    post_save_receivers = post_save.receivers
    obj = make_object(save_side_effect=RuntimeError('insert failed'))
    model = make_model(FakeManager())

    with pytest.raises(RuntimeError, match='insert failed'):
        db.bulk_create_db_safe(model, [obj], ignore_conflicts=False)

    commit.assert_not_called()
    rollback.assert_called_once_with('batch-1', using='default')
    assert pre_save.receivers == pre_save_receivers
    assert post_save.receivers == post_save_receivers


def test_ignore_conflicts_without_native_support_skips_integrity_errors(monkeypatch):
    connection = set_connection_features(monkeypatch, supports_ignore_conflicts=False)
    savepoint, commit, rollback = patch_savepoints(monkeypatch, ('duplicate', 'created'))
    duplicate = make_object(save_side_effect=IntegrityError('duplicate'))
    created = make_object()
    model = make_model(FakeManager())

    result = db.bulk_create_db_safe(model, [duplicate, created], ignore_conflicts=True)

    assert result == [created]
    assert savepoint.call_count == 2
    rollback.assert_called_once_with('duplicate', using='default')
    commit.assert_called_once_with('created', using='default')
    assert connection.needs_rollback is False
    assert created._state.db == 'default'
