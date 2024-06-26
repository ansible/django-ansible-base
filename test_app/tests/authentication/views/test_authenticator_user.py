from functools import partial

import pytest
from django.http import Http404
from django.test.utils import override_settings
from django.urls import reverse

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.views.authenticator_users import get_authenticator_user_view


def test_authenticator_user_view_get_parent_view_unset_value(expected_log):
    with override_settings(ANSIBLE_BASE_USER_VIEWSET=None):
        expected_log = partial(expected_log, "ansible_base.authentication.views.authenticator_users.logger")
        with expected_log('debug', 'ANSIBLE_BASE_USER_VIEWSET was not specified'):
            view = get_authenticator_user_view()
            assert view is None


@pytest.mark.parametrize(
    'setting',
    (
        ('junk.views'),
        ('ansible_base.authentication.views'),
    ),
)
def test_authenticator_user_view_get_parent_view_bad_value(setting, expected_log):
    with override_settings(ANSIBLE_BASE_USER_VIEWSET=setting):
        expected_log = partial(expected_log, "ansible_base.authentication.views.authenticator_users.logger")
        with expected_log('error', 'ANSIBLE_BASE_USER_VIEWSET was not an APIView'):
            view = get_authenticator_user_view()
            assert view is None


def test_authenticator_user_view_get_parent_view_good_value():
    with override_settings(ANSIBLE_BASE_USER_VIEWSET='ansible_base.authentication.views.AuthenticatorViewSet'):
        view = get_authenticator_user_view()
        assert view is not None


@pytest.mark.django_db
def test_authenticator_user_view_no_authenticator_id():
    view_class = get_authenticator_user_view()
    view = view_class()
    with pytest.raises(Http404):
        view.get_queryset(**{'authenticator_id': None})


@pytest.mark.django_db
def test_authenticator_user_view_authenticator_user_count(local_authenticator, django_user_model, randname):
    from ansible_base.authentication.models import AuthenticatorUser

    num_users = 10
    for index in range(0, num_users):
        user = django_user_model.objects.create_user(username=randname(f"user{index}"), password="password")
        AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    view_class = get_authenticator_user_view()
    view = view_class()
    query_set = view.get_queryset(**{'pk': local_authenticator.id})
    assert query_set.count() == num_users


@pytest.mark.parametrize(
    "client_fixture",
    [
        "unauthenticated_api_client",
        "user_api_client",
        "admin_api_client",
    ],
)
def test_authenticator_related_users_view(request, client_fixture, local_authenticator, user):
    """
    Test that we can list users related to an authenticator via /authenticators/:pk/users
    """
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    client = request.getfixturevalue(client_fixture)
    url = reverse("authenticator-users-list", kwargs={"pk": local_authenticator.pk})
    response = client.get(url)

    if client_fixture == "unauthenticated_api_client":
        assert response.status_code == 401
    elif client_fixture == "user_api_client":
        assert response.status_code == 403
    else:
        assert response.status_code == 200
        usernames = [user['username'] for user in response.data['results']]
        assert user.username in usernames


def test_authenticator_users_bad_pk(admin_api_client):
    url = reverse("authenticator-users-list", kwargs={"pk": 10397})
    response = admin_api_client.get(url)
    assert response.status_code == 404
