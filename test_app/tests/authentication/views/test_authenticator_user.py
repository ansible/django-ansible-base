from functools import partial

import pytest
from django.test.utils import override_settings

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
    query_set = view.get_queryset(**{'authenticator_id': None})
    assert query_set.count() == 0


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
