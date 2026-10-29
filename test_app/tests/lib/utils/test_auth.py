from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from django.core.exceptions import ImproperlyConfigured

from ansible_base.authentication.challenge import ChallengeAwareAuthenticationMixin
from ansible_base.lib.utils.auth import (
    get_authentication_challenge,
    get_model_from_settings,
    get_object_by_ansible_id,
    get_user_by_ansible_id,
    record_authentication_challenge,
)
from test_app.models import Organization, User


def test_get_model_from_settings_invalid_setting_name():
    with pytest.raises(ImproperlyConfigured):
        get_model_from_settings('jimbob')


@patch('ansible_base.lib.utils.auth.settings')
def test_get_model_from_settings_lookup_error(mock_settings):
    mock_settings.FOOBAR = 'no_such_model'
    with pytest.raises(ImproperlyConfigured):
        get_model_from_settings('FOOBAR')


@patch('ansible_base.lib.utils.auth.settings')
def test_get_model_from_settings_value_error(mock_settings):
    mock_settings.FOOBAR = 'User'
    with pytest.raises(ImproperlyConfigured):
        get_model_from_settings('FOOBAR')


@pytest.mark.django_db
def test_get_user_by_ansible_id():
    users = [User.objects.create(username=f'bob-{i}') for i in range(5)]
    for i in range(5):
        assert get_user_by_ansible_id(users[i].resource.ansible_id) == users[i]


@pytest.mark.django_db
def test_get_user_by_ansible_id_not_found():
    with pytest.raises(User.DoesNotExist):
        get_user_by_ansible_id('0a4a242a-a79b-420c-8584-7809eaa9cbcb')


@pytest.mark.django_db
def test_get_user_by_ansible_id_deleted_resource():
    users = [User.objects.create(username=f'bob-{i}') for i in range(5)]
    user_4_id = users[4].id
    resource = users[4].resource
    resource.delete()
    assert User.objects.filter(id=user_4_id).exists()  # sanity, user still exists

    # Even though user 4 can no longer be referenced by ansible_id, the others still work
    for i in range(3):
        found_user = get_user_by_ansible_id(users[i].resource.ansible_id)
        assert found_user == users[i]
        assert found_user.resource.ansible_id == users[i].resource.ansible_id


@pytest.mark.django_db
@pytest.mark.parametrize('arg_type', [str, UUID])
def test_get_by_ansible_id(organization, arg_type):
    resource = organization.resource
    assert type(resource.ansible_id) is UUID  # sanity, set expectation
    if isinstance(resource.ansible_id, arg_type):
        uuid_obj = resource.ansible_id
    else:
        uuid_obj = arg_type(resource.ansible_id)
    assert isinstance(uuid_obj, arg_type)
    assert get_object_by_ansible_id(Organization.objects.all(), organization.resource.ansible_id) == organization


def test_authentication_challenge_keeps_the_first_authenticator_to_claim_the_request():
    request = SimpleNamespace()

    record_authentication_challenge(request, "ServiceToken")
    record_authentication_challenge(request, 'Bearer realm="api"')

    assert get_authentication_challenge(request) == "ServiceToken"


def test_authentication_challenge_uses_the_provided_default_when_no_authenticator_claims_the_request():
    assert get_authentication_challenge(SimpleNamespace(), default="Session") == "Session"


def test_authentication_challenge_is_shared_between_drf_and_django_request_objects():
    django_request = SimpleNamespace()
    drf_request = SimpleNamespace(_request=django_request)

    record_authentication_challenge(drf_request, 'Basic realm="api"')

    assert get_authentication_challenge(drf_request) == 'Basic realm="api"'
    assert get_authentication_challenge(django_request) == 'Basic realm="api"'


def test_challenge_aware_authenticator_returns_the_first_recorded_challenge():
    class TestAuthentication(ChallengeAwareAuthenticationMixin):
        def get_default_authentication_challenge(self, request):
            return "Session"

    request = SimpleNamespace()
    authenticator = TestAuthentication()
    authenticator.record_authentication_challenge(request, "ServiceToken")
    authenticator.record_authentication_challenge(request, 'Bearer realm="api"')

    assert authenticator.authenticate_header(request) == "ServiceToken"
    assert authenticator.authenticate_header(SimpleNamespace()) == "Session"
