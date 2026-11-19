"""Tests for ansible_base.lib.mssql.params.in_chunks — SQL Server parameter-limit chunking."""

from types import SimpleNamespace
from unittest.mock import Mock

from ansible_base.lib.mssql import params as params_module
from ansible_base.lib.mssql.params import (
    SQL_SERVER_MAX_QUERY_PARAMETERS,
    SQL_SERVER_QUERY_PARAMETER_HEADROOM,
    in_chunks,
)

SAFE_CHUNK = (SQL_SERVER_MAX_QUERY_PARAMETERS - SQL_SERVER_QUERY_PARAMETER_HEADROOM) // 1


def make_params_module(monkeypatch, vendor, replica_vendor="postgresql"):
    connections = {
        "default": SimpleNamespace(vendor=vendor),
        "replica": SimpleNamespace(vendor=replica_vendor),
    }
    monkeypatch.setattr(params_module, "connections", connections)
    return connections


def test_in_chunks_single_chunk_on_postgres(monkeypatch):
    make_params_module(monkeypatch, "postgresql")
    values = list(range(5000))
    chunks = list(in_chunks(values))
    assert chunks == [values]


def test_in_chunks_chunks_on_microsoft(monkeypatch):
    make_params_module(monkeypatch, "microsoft")
    values = list(range(5000))
    chunks = list(in_chunks(values))
    assert all(len(chunk) == SAFE_CHUNK for chunk in chunks[:-1])
    assert 0 < len(chunks[-1]) <= SAFE_CHUNK
    assert [value for chunk in chunks for value in chunk] == values


def test_in_chunks_respects_params_per_value(monkeypatch):
    make_params_module(monkeypatch, "microsoft")
    values = list(range(5000))
    chunks = list(in_chunks(values, params_per_value=2))
    assert all(len(chunk) <= SAFE_CHUNK // 2 for chunk in chunks)
    assert [value for chunk in chunks for value in chunk] == values


def test_in_chunks_empty_input_yields_nothing(monkeypatch):
    make_params_module(monkeypatch, "microsoft")
    assert list(in_chunks([])) == []
    assert list(in_chunks(set())) == []


def test_in_chunks_empty_input_issues_no_queries(monkeypatch):
    """A follow-through: a chunked filter loop over empty values must not query."""
    make_params_module(monkeypatch, "microsoft")
    queryset = Mock()
    for chunk in in_chunks([]):
        queryset.filter(pk__in=chunk)
    queryset.filter.assert_not_called()


def test_in_chunks_preserves_explicit_using(monkeypatch):
    make_params_module(monkeypatch, "postgresql", replica_vendor="microsoft")
    values = list(range(5000))
    # the default alias is postgres (single chunk) but "replica" is microsoft
    chunks = list(in_chunks(values, using="replica"))
    assert all(len(chunk) <= SAFE_CHUNK for chunk in chunks)
    assert [value for chunk in chunks for value in chunk] == values
