from unittest import mock

from django.db import models
from django.db.models.functions import Lower

from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.lib.checks import check_charfield_has_max_length, check_textfield_indexed_is_bounded
from ansible_base.rbac.models import RoleDefinition
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
