import psycopg.sql
import pytest

from ansible_base.lib.utils.db import (
    _render_identifier,
    _render_params,
    _render_placeholder,
    _resolve_markers,
    build_safe_sql,
)


# ---------------------------------------------------------------------------
# _render_identifier
# ---------------------------------------------------------------------------
class TestRenderIdentifier:
    @pytest.mark.parametrize(
        "vendor, name, expected_type, expected_str",
        [
            pytest.param("sqlite", "my_table", str, '"my_table"', id="sqlite-valid"),
            pytest.param("postgresql", "my_table", psycopg.sql.Identifier, '"my_table"', id="postgresql-valid"),
        ],
    )
    def test_supported_vendors(self, vendor, name, expected_type, expected_str):
        result = _render_identifier(vendor, name)
        assert isinstance(result, expected_type)
        if vendor == "postgresql":
            assert result.as_string(None) == expected_str
        else:
            assert result == expected_str

    def test_sqlite_unsafe_name_raises(self):
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            _render_identifier("sqlite", "table; DROP")

    def test_unknown_vendor_raises(self):
        with pytest.raises(RuntimeError, match="not supported"):
            _render_identifier("oracle", "my_table")


# ---------------------------------------------------------------------------
# _render_placeholder
# ---------------------------------------------------------------------------
class TestRenderPlaceholder:
    def test_sqlite(self):
        assert _render_placeholder("sqlite") == "%s"

    def test_postgresql(self):
        result = _render_placeholder("postgresql")
        assert isinstance(result, psycopg.sql.Placeholder)

    def test_unknown_vendor_raises(self):
        with pytest.raises(RuntimeError, match="not supported"):
            _render_placeholder("oracle")


# ---------------------------------------------------------------------------
# _render_params
# ---------------------------------------------------------------------------
class TestRenderParams:
    def test_sqlite_count_3(self):
        assert _render_params("sqlite", 3) == "%s,%s,%s"

    def test_postgresql_count_3(self):
        result = _render_params("postgresql", 3)
        assert isinstance(result, psycopg.sql.Composed)

    def test_unknown_vendor_raises(self):
        with pytest.raises(RuntimeError, match="not supported"):
            _render_params("oracle", 3)


# ---------------------------------------------------------------------------
# _resolve_markers
# ---------------------------------------------------------------------------
class TestResolveMarkers:
    def test_slot_count_mismatch_raises(self):
        with pytest.raises(ValueError, match="marker"):
            _resolve_markers("sqlite", "SELECT {I}, {I}", ["only_one"])

    def test_identifier_marker_non_str_raises(self):
        with pytest.raises(TypeError, match="expects str"):
            _resolve_markers("sqlite", "SELECT {I}", [123])

    def test_placeholder_marker_non_int_raises(self):
        with pytest.raises(TypeError, match="expects int"):
            _resolve_markers("sqlite", "IN ({P})", ["not_an_int"])

    @pytest.mark.parametrize(
        "count, match_text",
        [
            pytest.param(0, "positive", id="zero"),
            pytest.param(-1, "positive", id="negative"),
        ],
    )
    def test_placeholder_marker_non_positive_raises(self, count, match_text):
        with pytest.raises(ValueError, match=match_text):
            _resolve_markers("sqlite", "IN ({P})", [count])


# ---------------------------------------------------------------------------
# build_safe_sql
# ---------------------------------------------------------------------------
class TestBuildSafeSql:
    def test_sqlite_full_template(self):
        result = build_safe_sql(
            "sqlite",
            "DELETE FROM {I} WHERE {I} = {} AND {I} IN ({P})",
            ["my_table", "content_type_id", "object_id", 3],
        )
        assert result == 'DELETE FROM "my_table" WHERE "content_type_id" = %s AND "object_id" IN (%s,%s,%s)'

    def test_postgresql_full_template(self):
        result = build_safe_sql(
            "postgresql",
            "DELETE FROM {I} WHERE {I} = {} AND {I} IN ({P})",
            ["my_table", "content_type_id", "object_id", 3],
        )
        assert result == 'DELETE FROM "my_table" WHERE "content_type_id" = %s AND "object_id" IN (%s,%s,%s)'

    def test_unknown_vendor_raises(self):
        with pytest.raises(RuntimeError, match="not supported"):
            build_safe_sql("oracle", "SELECT {I}", ["t"])

    def test_slot_count_mismatch_raises(self):
        with pytest.raises(ValueError, match="marker"):
            build_safe_sql("sqlite", "SELECT {I}, {I}", ["only_one"])

    @pytest.mark.parametrize(
        "vendor",
        [
            pytest.param("sqlite", id="sqlite-case-insensitive"),
            pytest.param("postgresql", id="postgresql-case-insensitive"),
        ],
    )
    def test_case_insensitivity(self, vendor):
        result_lower = build_safe_sql(vendor, "SELECT {i} WHERE {i} IN ({p})", ["col_a", "col_b", 2])
        result_upper = build_safe_sql(vendor, "SELECT {I} WHERE {I} IN ({P})", ["col_a", "col_b", 2])
        if vendor == "postgresql":
            # Both produce the same rendered string
            assert result_lower == result_upper
        else:
            assert result_lower == result_upper
