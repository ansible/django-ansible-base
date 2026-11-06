from types import SimpleNamespace

from ansible_base.lib.mssql.vendor import is_mssql


def test_is_mssql_true_for_microsoft():
    assert is_mssql(SimpleNamespace(vendor="microsoft")) is True


def test_is_mssql_false_for_other_vendors():
    assert is_mssql(SimpleNamespace(vendor="postgresql")) is False
    assert is_mssql(SimpleNamespace(vendor="sqlite")) is False
