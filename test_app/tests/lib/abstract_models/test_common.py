from functools import partial
from unittest.mock import patch

import pytest
from crum import impersonate
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import override_settings
from django.test.client import RequestFactory

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from test_app.models import City, EncryptionModel, Organization, RelatedFieldsTestModel, User


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


@override_settings(SYSTEM_USERNAME=None)
@pytest.mark.django_db
def test_save_attribution_no_system_username():
    model = Organization.objects.create(name='foo-org')

    model = Organization()
    model.save()
    assert model.created_by is None
    assert model.modified_by is None

    model.refresh_from_db()
    assert model.created_by is None
    assert model.modified_by is None


@pytest.mark.django_db
@override_settings(SYSTEM_USERNAME='_not_system')
def test_save_attribution_with_system_username_set_but_nonexistent_as_false(system_user, organization, expected_log):
    expected_log = partial(expected_log, "ansible_base.lib.abstract_models.common.logger")

    with expected_log("error", "no user with that username exists", assert_not_called=True):
        organization.save()

    from ansible_base.lib.utils.models import get_system_user

    not_system_user = get_system_user()
    assert organization.created_by == system_user
    assert organization.modified_by == not_system_user, "org modified by should have been not_system_user"

    organization.refresh_from_db()
    assert organization.created_by == system_user
    assert organization.modified_by == not_system_user, "org modified by should have been not_system_user after refresh"


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

    with patch('ansible_base.lib.abstract_models.common.get_relative_url') as reverse:
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


@pytest.mark.django_db
def test_resave_of_model_with_no_created(expected_log, system_user):
    # Create a random model and save it without warning and no system user
    model = Organization()
    with override_settings(SYSTEM_USERNAME='_not_system'):
        from ansible_base.lib.utils.models import get_system_user

        not_system_user = get_system_user()
        model.save()

    assert model.created_by == not_system_user, "First created_by was not the correct user"

    model.save()
    assert model.modified_by == system_user, "Second created_by was not the correct user"

    model.delete()


def test_attributable_user_anonymous_user(system_user):
    # If we are an AnonymousUser and we call _attributable_error we should get the system user back
    model = User()
    with impersonate(AnonymousUser()):
        model.save()

    assert model.created_by == system_user
    model.delete()


@pytest.mark.django_db
def test_cascade_behavior_for_created_by(user, user_api_client):
    rd = RoleDefinition.objects.create_from_permissions(name='global-add-org', permissions=['add_organization'], content_type=None)
    rd.give_global_permission(user)
    url = get_relative_url('organization-list')
    r = user_api_client.post(url, data={'name': 'foo'})
    assert r.status_code == 201, r.data
    org = Organization.objects.get(id=r.data['id'])
    assert org.created_by == user
    connection.check_constraints()  # issue replication - show constraint violation introduced
    user.delete()
    org.refresh_from_db()
    assert org.created_by is None  # the SET_NULL behavior now implemented
    connection.check_constraints()


def test_do_not_update_modified_by_on_login(system_user, user, user_api_client):
    user.refresh_from_db()
    assert user.modified_by == system_user
    with impersonate(user):
        user_api_client.login(username=user.username, password='password')
    user.refresh_from_db()
    assert user.modified_by == system_user


def test_modified_by_respects_given_value(system_user, random_user, user, animal):
    animal.save()
    assert animal.modified_by == system_user
    with impersonate(user):
        animal.modified_by = random_user
        animal.save(update_fields=['modified_by'])
    animal.refresh_from_db()
    assert animal.modified_by == random_user


@pytest.mark.parametrize(
    'update_fields, expected_modified_by',
    [
        pytest.param(['population'], 'user', id='modified_by saved even if not in update_fields'),
        pytest.param(['state'], 'system_user', id='update_fields only lists non-editable fields, modified_by does not get set'),
        pytest.param(['state', 'population'], 'user', id='update_fields lists some non-editable fields, modified_by gets set'),
        pytest.param(None, 'user', id='update_fields is None, modified_by gets set'),
        pytest.param(False, 'user', id='update_fields not passed, modified_by gets set'),
        pytest.param([], 'system_user', id='update_fields empty, modified_by does not get set'),
    ],
)
def test_modified_by_not_set_if_update_fields_are_all_uneditable(system_user, user, update_fields, expected_modified_by):
    city = City.objects.create(name='Boston', state='MA')
    assert city.modified_by == system_user
    city.state = 'Ohio'
    city.population = 38
    with impersonate(user):
        if update_fields is False:
            city.save()
        else:
            city.save(update_fields=update_fields)
    city.refresh_from_db()
    assert city.modified_by == (user if expected_modified_by == 'user' else system_user)


def test_modified_by_gets_saved_even_if_not_in_update_fields(system_user, user, animal):
    animal.save()
    assert animal.modified_by == system_user
    animal.name = 'Bob The Fish'
    animal.kind = 'fish'
    with impersonate(user):
        animal.save(update_fields=['name', 'kind'])
    animal.refresh_from_db()
    assert animal.modified_by == user


def test_ignore_relations_in_summary_fields_and_related(team, admin_api_client):
    url = get_relative_url('team-detail', kwargs={'pk': team.pk})
    response = admin_api_client.get(url)
    summary_fields = response.data.get('summary_fields', {})
    assert summary_fields['organization']['name'] == team.organization.name
    assert 'organization' in response.data['related']

    with patch('test_app.models.Team.ignore_relations', new=['organization']):
        response = admin_api_client.get(url)
        assert 'organization' not in response.data['summary_fields']
        assert 'organization' not in response.data['related']


@pytest.mark.parametrize(
    "debug_mode,not_called",
    [
        (True, False),
        (False, True),
    ],
)
def test_related_view_log_message(debug_mode, not_called, expected_log):
    from test_app.models import RelatedFieldsTestModel

    rf = RequestFactory()
    request = rf.get('/')

    with override_settings(DEBUG=debug_mode):
        with expected_log('ansible_base.lib.abstract_models.common.logger', 'error', 'but view was missing', assert_not_called=not_called):
            model = RelatedFieldsTestModel()
            model.related_fields(request)


@pytest.mark.parametrize(
    "ignore_relation",
    [
        True,
        False,
    ],
)
@pytest.mark.django_db
def test_related_view_ignore_m2m_relations(ignore_relation, admin_user):
    rf = RequestFactory()
    request = rf.get('/')
    with patch('ansible_base.lib.abstract_models.common.get_relative_url', return_value='https://www.example.com/user'):
        if ignore_relation:
            admin_user.ignore_relations = ['member_of_organizations']
        else:
            admin_user.ignore_relations = []

        related = admin_user.related_fields(request)
        assert ('member_of_organizations' not in related) is ignore_relation


def test_jsonfield_can_be_encrypted(admin_user, local_authenticator):
    extra_data = {}

    from ansible_base.lib.utils.encryption import Fernet256

    encryptor = Fernet256()
    encrypted_extra_data = encryptor.encrypt_string(extra_data)

    with patch('ansible_base.lib.utils.encryption.ansible_encryption.encrypt_string', return_value=encrypted_extra_data) as m:
        from ansible_base.authentication.models import AuthenticatorUser

        AuthenticatorUser.objects.create(
            uid=admin_user.username,
            user=admin_user,
            provider=local_authenticator,
            extra_data=extra_data,
        )

    m.assert_called_with(extra_data)


@pytest.mark.parametrize(
    "input",
    [
        "test",
        None,
        {},
        [],
        True,
        False,
        {"value": 1, "value2": True, "value3": ["a", "b", "c"]},
        ["a", "list"],
    ],
)
def test_compare_data_types_after_decryption(input):
    from ansible_base.lib.utils.encryption import Fernet256

    decryptor = Fernet256()
    results = decryptor.decrypt_string(decryptor.encrypt_string(input))
    assert type(results) is type(input)
