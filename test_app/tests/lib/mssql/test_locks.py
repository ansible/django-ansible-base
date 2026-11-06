import importlib
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from zlib import crc32

import pytest
from django.db import OperationalError

from ansible_base.lib.mssql import locks
from ansible_base.lib.utils import db


def make_mssql_connection(monkeypatch, result, raw_connection=object(), execute_error=None):
    cursor = Mock()
    cursor.fetchone.return_value = result
    if execute_error is not None:
        cursor.execute.side_effect = execute_error

    connection = Mock()
    connection.connection = raw_connection
    connection.cursor.return_value = cursor
    monkeypatch.setattr(locks, "connections", {"default": connection, "replica": connection})
    return connection, cursor


def test_modules_import_without_pyodbc(monkeypatch):
    "db.py and lib/mssql must import on postgres-only installs (no pyodbc)."
    monkeypatch.setitem(sys.modules, "pyodbc", None)  # forces ImportError on 'import pyodbc'
    importlib.reload(importlib.import_module("ansible_base.lib.mssql.locks"))
    importlib.reload(importlib.import_module("ansible_base.lib.utils.db"))


@pytest.mark.parametrize(
    ("lock_id", "expected"),
    [
        ("short_name", "short_name"),
        ("x" * 260, "x" * 255),
        (12, "dab_lock_12"),
        ([1, 2], "dab_lock_1_2"),
        ((3, 4), "dab_lock_3_4"),
    ],
)
def test_convert_lock_id_to_sql_server_resource_name(lock_id, expected):
    assert locks.convert_lock_id_to_resource_name(lock_id) == expected


def test_convert_lock_id_hashes_other_types():
    lock_id = SimpleNamespace(name="lock")
    expected = f"dab_lock_{crc32(str(lock_id).encode('utf-8'))}"

    assert locks.convert_lock_id_to_resource_name(lock_id) == expected


@pytest.mark.parametrize("lock_id", [(1,), ("a", "b"), [1, 2, 3]])
def test_convert_lock_id_rejects_invalid_sequences(lock_id):
    with pytest.raises(ValueError):
        locks.convert_lock_id_to_resource_name(lock_id)


def test_mssql_advisory_lock_acquires_and_releases(monkeypatch):
    connection, cursor = make_mssql_connection(monkeypatch, (0,), raw_connection=None)

    with locks.mssql_advisory_lock((12, 34), shared=True, lock_session_timeout_milliseconds=500, using="replica") as acquired:
        assert acquired is True

    connection.ensure_connection.assert_called_once()
    assert cursor.execute.call_count == 2
    assert cursor.execute.call_args_list[0].args[1] == ["dab_lock_12_34", "Shared", 500]
    assert cursor.execute.call_args_list[1].args[1] == ["dab_lock_12_34"]
    cursor.close.assert_called_once()


def test_mssql_advisory_lock_timeout_returns_not_acquired_when_not_waiting(monkeypatch):
    _, cursor = make_mssql_connection(monkeypatch, (-1,))

    with locks.mssql_advisory_lock("lock", wait=False) as acquired:
        assert acquired is False

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == ["lock", "Exclusive", 0]


def test_mssql_advisory_lock_timeout_raises_when_waiting(monkeypatch):
    _, cursor = make_mssql_connection(monkeypatch, (-1,))
    lock_context = locks.mssql_advisory_lock("lock", wait=True, lock_session_timeout_milliseconds=500)

    with pytest.raises(OperationalError, match="timed out"):
        with lock_context:
            pass

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[1] == ["lock", "Exclusive", 500]
    cursor.close.assert_called_once()


@pytest.mark.parametrize(("row", "code"), [(None, -999), ((-3,), -3)])
def test_mssql_advisory_lock_raises_for_failed_acquisition(monkeypatch, row, code):
    _, cursor = make_mssql_connection(monkeypatch, row)
    lock_context = locks.mssql_advisory_lock("lock")

    with pytest.raises(OperationalError, match=str(code)):
        with lock_context:
            pass

    cursor.close.assert_called_once()
    assert cursor.execute.call_count == 1


def test_mssql_advisory_lock_propagates_execute_errors(monkeypatch):
    """Verify database errors during lock acquisition propagate correctly."""
    _, cursor = make_mssql_connection(monkeypatch, None, execute_error=RuntimeError("connection failed"))
    lock_context = locks.mssql_advisory_lock("lock")

    with pytest.raises(RuntimeError, match="connection failed"):
        with lock_context:
            pass

    cursor.close.assert_called_once()


def test_mssql_advisory_lock_release_error_preserves_body_exception_and_closes_connection(
    monkeypatch,
):
    connection, cursor = make_mssql_connection(monkeypatch, (0,))
    cursor.execute.side_effect = [None, OperationalError("release failed")]
    body_error = RuntimeError("body failed")

    with pytest.raises(RuntimeError, match="body failed"):
        with locks.mssql_advisory_lock("lock", using="replica"):
            raise body_error

    connection.close.assert_called_once()
    cursor.close.assert_called_once()


def test_advisory_lock_dispatches_to_mssql_and_passes_options(monkeypatch):
    connection = SimpleNamespace(vendor="microsoft", close_if_unusable_or_obsolete=Mock())
    monkeypatch.setattr(db, "connections", {"default": connection, "replica": connection})
    called = {}

    @contextmanager
    def fake_mssql_lock(lock_id, **kwargs):
        called["lock_id"] = lock_id
        called["kwargs"] = kwargs
        yield True

    monkeypatch.setattr(locks, "mssql_advisory_lock", fake_mssql_lock)
    with db.advisory_lock(
        "lock",
        shared=True,
        wait=False,
        lock_session_timeout_milliseconds=5,
        using="replica",
    ) as acquired:
        assert acquired is True

    assert called == {
        "lock_id": "lock",
        "kwargs": {
            "shared": True,
            "wait": False,
            "lock_session_timeout_milliseconds": 5,
            "using": "replica",
        },
    }


def test_advisory_lock_preserves_positional_options_for_mssql(monkeypatch):
    default_connection = SimpleNamespace(vendor="microsoft", close_if_unusable_or_obsolete=Mock())
    replica_connection = SimpleNamespace(vendor="microsoft", close_if_unusable_or_obsolete=Mock())
    monkeypatch.setattr(
        db,
        "connections",
        {"default": default_connection, "replica": replica_connection},
    )
    called = {}

    @contextmanager
    def fake_mssql_lock(lock_id, **kwargs):
        called["lock_id"] = lock_id
        called["kwargs"] = kwargs
        yield False

    monkeypatch.setattr(locks, "mssql_advisory_lock", fake_mssql_lock)
    with db.advisory_lock("lock", True, False, "replica") as acquired:
        assert acquired is False

    assert called == {
        "lock_id": "lock",
        "kwargs": {
            "shared": True,
            "wait": False,
            "lock_session_timeout_milliseconds": 0,
            "using": "replica",
        },
    }


def test_advisory_lock_closes_connection_after_mssql_error(monkeypatch):
    connection = SimpleNamespace(vendor="microsoft", close_if_unusable_or_obsolete=Mock())
    monkeypatch.setattr(db, "connections", {"default": connection})

    class FailedLock:
        def __enter__(self):
            raise OperationalError("lock failed")

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(locks, "mssql_advisory_lock", lambda *args, **kwargs: FailedLock())
    with pytest.raises(OperationalError, match="lock failed"):
        with db.advisory_lock("lock"):
            pass

    connection.close_if_unusable_or_obsolete.assert_called_once()


def test_advisory_lock_closes_using_alias_after_mssql_error(monkeypatch):
    default_connection = Mock(vendor="microsoft")
    replica_connection = Mock(vendor="microsoft")
    cursor = replica_connection.cursor.return_value
    cursor.fetchone.return_value = (0,)
    monkeypatch.setattr(db, "connection", default_connection)
    monkeypatch.setattr(
        db,
        "connections",
        {"default": default_connection, "replica": replica_connection},
    )
    monkeypatch.setattr(
        locks,
        "connections",
        {"default": default_connection, "replica": replica_connection},
    )
    body_error = OperationalError("body failed")

    with pytest.raises(OperationalError, match="body failed"):
        with db.advisory_lock("lock", using="replica"):
            raise body_error

    replica_connection.close_if_unusable_or_obsolete.assert_called_once()
    default_connection.close_if_unusable_or_obsolete.assert_not_called()


def test_advisory_lock_requires_lock_id_for_mssql(monkeypatch):
    monkeypatch.setattr(db, "connections", {"default": SimpleNamespace(vendor="microsoft")})

    with pytest.raises(ValueError, match="lock identifier"):
        with db.advisory_lock():
            pass
