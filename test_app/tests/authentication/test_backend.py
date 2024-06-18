from random import shuffle
from unittest import mock

import pytest

import ansible_base.authentication.backend as backend
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.social_auth import SOCIAL_AUTH_PIPELINE_FAILED_STATUS


@pytest.mark.django_db
def test_authenticator_backends_import_error(ldap_authenticator):
    # Load one item
    assert len(backend.get_authentication_backends("fake date")) == 1

    # Change the get_authenticator_plugin to fail, this will cause the backend to not be able to load
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        # Force the cache to get evicted by updating an authenticator.
        assert len(backend.get_authentication_backends("fake date2")) == 0


@pytest.mark.django_db
def test_authenticator_backends_cache(ldap_authenticator):
    last_modified = Authenticator.objects.values("modified").order_by("-modified").first()["modified"]

    # Load one item
    assert len(backend.get_authentication_backends(last_modified)) == 1

    # verify that the cache is evicted when an authenticator is updated.
    ldap_authenticator.name = "new_name"
    ldap_authenticator.save()

    last_modified = Authenticator.objects.values("modified").order_by("-modified").first()["modified"]
    authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
    assert authenticator.database_instance.name == "new_name"

    # verify that the cache is not updated if the last_modified date is the same
    with mock.patch('ansible_base.authentication.backend.get_authenticator_plugin', side_effect=OSError("Test Exception")):
        # If the function reruns, get_authenticator_plugin will throw an exception here
        authenticator = backend.get_authentication_backends(last_modified)[ldap_authenticator.pk]
        assert authenticator.database_instance.name == "new_name"


def shuffle_backends(backends):
    authenticator_ids = list(backends.keys())
    shuffle(authenticator_ids)

    for index, authenticator_id in enumerate(authenticator_ids):
        authenticator = Authenticator.objects.get(id=authenticator_id)
        authenticator.order = index
        authenticator.save()

    return authenticator_ids


@pytest.mark.django_db
def test_authenticator_order(
    github_authenticator,
    github_organization_authenticator,
    github_team_authenticator,
    github_enterprise_authenticator,
    github_enterprise_organization_authenticator,
    github_enterprise_team_authenticator,
    oidc_authenticator,
    ldap_authenticator,
    tacacs_authenticator,
    saml_authenticator,
    keycloak_authenticator,
    local_authenticator_map,
):
    # Get the authenticators from the backend (to filter out enabled or anything else its doing)
    authenticators = backend.get_authentication_backends(None)

    # Randomize the authenticators list
    ids_by_new_order = shuffle_backends(authenticators)

    # Get the backends form the code (which should respect order)
    # Note: that we need to specify a different value to not get a cached result
    ordered_authenticator_backends = backend.get_authentication_backends(1)

    # Convert the results to a list
    ordered_authenticator_id_list = []
    for authenticator_id, _authenticator_plugin in ordered_authenticator_backends.items():
        ordered_authenticator_id_list.append(authenticator_id)

    assert ordered_authenticator_id_list == ids_by_new_order


@pytest.mark.django_db
def test_authenticator_order_cached(
    github_authenticator,
    github_organization_authenticator,
    github_team_authenticator,
    github_enterprise_authenticator,
    github_enterprise_organization_authenticator,
    github_enterprise_team_authenticator,
    oidc_authenticator,
    ldap_authenticator,
    tacacs_authenticator,
    saml_authenticator,
    keycloak_authenticator,
    local_authenticator_map,
):
    # Get the authenticators from the backend (to filter out enabled or anything else its doing)
    backends = backend.get_authentication_backends(None)

    # Randomize the order of the authenticators
    shuffle_backends(backends)

    # test the cache
    cached_authenticators = backend.get_authentication_backends(None)
    assert cached_authenticators == backends

    # Bust the cache
    cached_authenticators = backend.get_authentication_backends(1)
    assert cached_authenticators != backends


@pytest.mark.parametrize(
    "github_auth_retval, is_active, expected",
    [
        ("random_user", None, "random_user"),
        ("random_user", False, None),
        ("random_user", True, "random_user"),
        (None, None, "random_user_1"),
        (None, False, "random_user_1"),
        (None, True, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, None, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, False, "random_user_1"),
        (SOCIAL_AUTH_PIPELINE_FAILED_STATUS, True, "random_user_1"),
    ],
)
def test_authenticate(request, local_authenticator, github_enterprise_authenticator, random_user, random_user_1, github_auth_retval, is_active, expected):
    with mock.patch(
        "ansible_base.authentication.backend.get_authentication_backends",
        return_value={github_enterprise_authenticator.id: github_enterprise_authenticator, local_authenticator.id: local_authenticator},
    ):
        # Set is_active flag for 1st authenticator's user
        if is_active is not None:
            setattr(random_user, "is_active", is_active)

        # Set response for 1st authenticator
        if github_auth_retval == "random_user":
            github_auth_retval = request.getfixturevalue(github_auth_retval)
        github_enterprise_authenticator.authenticate = mock.MagicMock(return_value=github_auth_retval)

        # If GitHub authenticator fails, next one always fits
        local_authenticator.authenticate = mock.MagicMock(return_value=random_user_1)

        auth_return = backend.AnsibleBaseAuth().authenticate(None)

        if expected is not None:
            expected = request.getfixturevalue(expected)

        assert auth_return == expected
