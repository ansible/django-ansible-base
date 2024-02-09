from functools import partial
from unittest.mock import patch

import pytest
from django.test import override_settings

from test_app.models import EncryptionModel, Organization, RelatedFieldsTestModel


@pytest.mark.django_db
def test_save_encryption():
    model = EncryptionModel.objects.create(testing1='c')
    model.save()

    saved_model = EncryptionModel.objects.first()
    assert saved_model.testing2 == 'b'
    assert saved_model.testing1 == 'c'


@pytest.mark.django_db
def test_name_in_summary_fields():
    model = EncryptionModel.objects.create()
    assert 'name' in model.summary_fields()


@pytest.mark.django_db
def test_save_attribution_no_system_username():
    model = Organization.objects.create()
    model.save()
    assert model.created_by is None
    assert model.modified_by is None

    model.refresh_from_db()
    assert model.created_by is None
    assert model.modified_by is None


@pytest.mark.django_db
@override_settings(SYSTEM_USERNAME='_system')
@pytest.mark.parametrize(
    'warn_nonexistent_system_user',
    (True, False),
)
def test_save_attribution_with_system_username_set_but_nonexistent(organization, expected_log, warn_nonexistent_system_user):
    expected_log = partial(expected_log, "ansible_base.lib.abstract_models.common.logger")

    assert organization.created_by is None
    assert organization.modified_by is None

    with expected_log("warn", "no user with that username exists", assert_not_called=not warn_nonexistent_system_user):
        organization.save(warn_nonexistent_system_user=warn_nonexistent_system_user)

    assert organization.created_by is None
    assert organization.modified_by is None

    organization.refresh_from_db()
    assert organization.created_by is None
    assert organization.modified_by is None


@pytest.mark.django_db
def test_save_attribution_with_system_user(system_user, organization):
    # This test looks weird, it's just testing a fixture, but it's because we
    # don't want to create objects manually here - otherwise deleting system_user at teardown
    # will trigger an IntegrityError because of the attribution fields of our object pointing
    # to it and the fact that we don't have on_delete=SET_NULL on those fields.
    assert organization.created_by == system_user
    assert organization.modified_by == system_user


@pytest.mark.django_db
def test_save_attribution_created_by_set_manually_and_retained(django_user_model, system_user, user, random_user):
    assert random_user.created_by == system_user
    assert random_user.modified_by == system_user

    random_user.created_by = user
    random_user.save()

    assert random_user.created_by == user
    assert random_user.modified_by == system_user

    random_user.refresh_from_db()
    assert random_user.created_by == user
    assert random_user.modified_by == system_user


@pytest.mark.django_db
def test_related_fields_view_resolution(shut_up_logging):
    model = RelatedFieldsTestModel.objects.create()

    with patch('ansible_base.lib.abstract_models.common.reverse') as reverse:
        model.related_fields(None)

    # First off, we should never have 'teams_with_no_view' as an arg to reverse
    for call in reverse.call_args_list:
        assert 'teams_with_no_view' not in call[0][0]

    # But it should have been called with related_fields_test_model-users-list
    # (default since we don't override it for the 'users' field)
    assert 'related_fields_test_model-users-list' in [call[0][0] for call in reverse.call_args_list]

    # And it should have been called with related_fields_test_model-more_teams-list
    # (overridden for the 'more_teams' field)
    assert 'related_fields_test_model-more_teams-list' in [call[0][0] for call in reverse.call_args_list]
