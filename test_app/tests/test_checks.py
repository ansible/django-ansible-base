from unittest import mock

from django.db import models
from django.db.models.functions import Lower
from django.test import override_settings

from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.lib.checks import _index_key_width, check_bounded_textfield_index_key_size, check_charfield_has_max_length, check_textfield_indexed_is_bounded
from ansible_base.rbac.models import DABContentType, ObjectRole, RoleDefinition
from test_app.models import MetadataTestModel


def test_check_charfield_has_max_length_fails():
    with mock.patch.object(Authenticator._meta.get_field('type'), 'max_length', new=None):
        errors = check_charfield_has_max_length(None)
        assert len(errors) == 1
        assert errors[0].id == 'ansible_base.E001'


def test_check_clean_after_adoption():
    assert check_textfield_indexed_is_bounded(None) == []


def test_check_flags_indexed_plain_textfield():
    field = RoleDefinition._meta.get_field('description')
    with mock.patch.object(field, 'db_index', new=True):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']
        assert 'RoleDefinition.description' in errors[0].msg


def test_check_flags_index_declared_in_meta():
    # ObjectRole.object_id carries no field-level db_index; its index is on Meta
    with mock.patch.object(RoleDefinition._meta, 'indexes', [models.Index(fields=['description'])]):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']


def test_check_flags_expression_index_on_plain_textfield():
    # fields-based indexes leave Index.expressions empty; expression-based ones leave fields empty
    with mock.patch.object(RoleDefinition._meta, 'indexes', [models.Index(Lower('description'), name='desc_lower_idx')]):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']


def test_check_flags_expression_unique_constraint_on_plain_textfield():
    with mock.patch.object(RoleDefinition._meta, 'constraints', [models.UniqueConstraint(Lower('description'), name='uniq_desc_lower')]):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']


def test_check_ignores_consumer_apps():
    # test_app is not an ansible_base.* app even when it violates the rule
    field = MetadataTestModel._meta.get_field('description')
    with mock.patch.object(field, 'db_index', new=True):
        assert check_textfield_indexed_is_bounded(None) == []


def test_check_clean_on_index_key_size():
    assert check_bounded_textfield_index_key_size(None) == []


def test_check_flags_indexed_bound_over_key_size():
    # nvarchar is 2 bytes per UTF-16 code unit: a bound of 851 needs 1702 bytes of
    # index key, over SQL Server's 1700-byte nonclustered limit
    field = RoleDefinition._meta.get_field('name')
    with mock.patch.object(field, 'sql_server_max_length', new=851):
        errors = check_bounded_textfield_index_key_size(None)
        assert [e.id for e in errors] == ['ansible_base.E004']
        assert 'RoleDefinition.name' in errors[0].msg


def test_check_allows_indexed_bound_at_key_size_limit():
    field = RoleDefinition._meta.get_field('name')
    with mock.patch.object(field, 'sql_server_max_length', new=850):
        assert check_bounded_textfield_index_key_size(None) == []


def test_check_ignores_unindexed_oversized_bound():
    field = RoleDefinition._meta.get_field('name')
    with (
        mock.patch.object(field, 'db_index', new=False),
        mock.patch.object(field, 'unique', new=False),
        mock.patch.object(field, 'sql_server_max_length', new=4000),
    ):
        assert check_bounded_textfield_index_key_size(None) == []


def test_check_flags_composite_key_over_budget():
    # two bounded columns in one constraint: (450 + 450) code units = 1800 bytes of key
    with mock.patch.object(ObjectRole._meta, 'constraints', [models.UniqueConstraint(fields=['object_id', 'parent_reference'], name='test_composite')]):
        with mock.patch.object(ObjectRole._meta.get_field('object_id'), 'sql_server_max_length', new=450):
            with mock.patch.object(ObjectRole._meta.get_field('parent_reference'), 'sql_server_max_length', new=450):
                errors = check_bounded_textfield_index_key_size(None)
                assert [e.id for e in errors] == ['ansible_base.E004']
                assert 'test_composite' in errors[0].msg


def test_check_flags_expression_composite_key_over_budget():
    index = models.Index(Lower('object_id'), Lower('parent_reference'), name='test_composite_expr')
    with mock.patch.object(ObjectRole._meta, 'indexes', [index]):
        with mock.patch.object(ObjectRole._meta.get_field('object_id'), 'sql_server_max_length', new=450):
            with mock.patch.object(ObjectRole._meta.get_field('parent_reference'), 'sql_server_max_length', new=450):
                errors = check_bounded_textfield_index_key_size(None)
                assert [e.id for e in errors] == ['ansible_base.E004']


def test_check_flags_mixed_composite_key_over_budget():
    # regression: columns that are not BoundedTextField count toward the budget too —
    # a bounded column at the limit plus its integer ForeignKey partner exceeds 1700 bytes
    with (
        mock.patch.object(ObjectRole._meta, 'indexes', []),
        mock.patch.object(ObjectRole._meta, 'constraints', [models.UniqueConstraint(fields=['object_id', 'content_type'], name='test_mixed')]),
        mock.patch.object(ObjectRole._meta.get_field('object_id'), 'sql_server_max_length', new=850),
    ):
        errors = check_bounded_textfield_index_key_size(None)
        assert [e.id for e in errors] == ['ansible_base.E004']
        assert 'test_mixed' in errors[0].msg


def test_check_ignores_composite_key_without_bounded_columns():
    # keys without a bounded column are E002's charter, not this check's
    with (
        mock.patch.object(DABContentType._meta.get_field('service'), 'max_length', new=900),
        mock.patch.object(DABContentType._meta.get_field('model'), 'max_length', new=900),
    ):
        assert check_bounded_textfield_index_key_size(None) == []


def test_index_key_width_counts_charfield_columns():
    # mssql-django maps CharField to nvarchar: 2 bytes per character
    assert _index_key_width(DABContentType._meta.get_field('service')) == 200


def test_index_key_width_matches_mssql_django_ddl():
    # mssql-django 2.0.0 maps UUIDField to char(32) and, under USE_TZ (DAB's default),
    # DateTimeField to datetimeoffset, which carries a 2-byte zone offset on top of datetime2.
    # DateTimeField also inherits DateField; the mro walk must match it as itself (10, not 3).
    assert _index_key_width(models.UUIDField()) == 32
    assert _index_key_width(models.DateTimeField()) == 10
    assert _index_key_width(models.DateField()) == 3
    with override_settings(USE_TZ=False):
        assert _index_key_width(models.DateTimeField()) == 8


def test_check_flags_bounded_textfield_plus_datetime_over_budget():
    # BTF(846) = 1692 bytes + datetimeoffset(10) = 1702, over the 1700-byte budget;
    # counting datetime2's 8 bytes let this key pass at exactly 1700
    with mock.patch.object(RoleDefinition._meta, 'constraints', [models.UniqueConstraint(fields=['name', 'created'], name='test_datetimeoffset')]):
        with mock.patch.object(RoleDefinition._meta.get_field('name'), 'sql_server_max_length', new=846):
            errors = check_bounded_textfield_index_key_size(None)
            assert [e.id for e in errors] == ['ansible_base.E004']
            assert 'test_datetimeoffset' in errors[0].msg


def test_check_ignores_invalid_bound_in_key_size():
    # E003 reports invalid bounds like None; E004 must not crash while summing key widths
    field = RoleDefinition._meta.get_field('name')
    with mock.patch.object(field, 'sql_server_max_length', new=None):
        assert check_bounded_textfield_index_key_size(None) == []


def test_check_flags_root_f_index_on_plain_textfield():
    # Django wraps positional index strings in F, and F has no flatten() — the
    # reference-name walk must treat a root F as itself instead of crashing
    with mock.patch.object(RoleDefinition._meta, 'indexes', [models.Index(models.F('description'), name='desc_f_idx')]):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']


def test_check_flags_root_f_unique_constraint_on_plain_textfield():
    with mock.patch.object(RoleDefinition._meta, 'constraints', [models.UniqueConstraint(models.F('description'), name='uniq_desc_f')]):
        errors = check_textfield_indexed_is_bounded(None)
        assert [e.id for e in errors] == ['ansible_base.E002']


def test_check_flags_root_f_expression_composite_key_over_budget():
    index = models.Index(models.F('object_id'), models.F('parent_reference'), name='test_f_composite')
    with mock.patch.object(ObjectRole._meta, 'indexes', [index]):
        with mock.patch.object(ObjectRole._meta.get_field('object_id'), 'sql_server_max_length', new=450):
            with mock.patch.object(ObjectRole._meta.get_field('parent_reference'), 'sql_server_max_length', new=450):
                errors = check_bounded_textfield_index_key_size(None)
                assert [e.id for e in errors] == ['ansible_base.E004']


def test_check_ignores_consumer_apps_on_key_size():
    # no ansible_base model is involved: test_app violations never fire
    field = MetadataTestModel._meta.get_field('description')
    with mock.patch.object(field, 'db_index', new=True):
        assert check_bounded_textfield_index_key_size(None) == []
