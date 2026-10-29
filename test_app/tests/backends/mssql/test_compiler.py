"""Tests for SQL Server query compilation under a case-sensitive collation."""

import pytest
from django.db import connections
from django.db.models.fields.related_descriptors import _filter_prefetch_queryset

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application


def test_sliced_prefetch_select_aliases_match_case_sensitive_references(monkeypatch):
    connection = connections["default"]
    if connection.vendor != "microsoft":
        pytest.skip("This SQL alias compatibility case applies to SQL Server.")

    # SQL compilation only needs the server version for OFFSET support. Avoid
    # opening a connection so this regression test can check the emitted SQL.
    monkeypatch.setitem(connection.__dict__, "sql_server_version", 2022)
    monkeypatch.setitem(connection.__dict__, "to_azure_sql_db", False)

    queryset = OAuth2AccessToken.objects.order_by("id")[:10]
    queryset = _filter_prefetch_queryset(queryset, "application", [OAuth2Application(pk=40)])
    sql, _ = queryset.query.get_compiler(using=connection.alias).as_sql()

    # Django's outer QUALIFY wrapper references lowercase aliases. The inner
    # mssql-django compiler emits uppercase aliases unless normalized here.
    assert " AS Col1" not in sql
    assert " AS col1" in sql
    assert "[col1]" in sql
