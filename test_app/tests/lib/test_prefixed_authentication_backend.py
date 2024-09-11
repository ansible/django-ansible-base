import pytest
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url
from test_app.models import User


@pytest.fixture
@pytest.mark.django_db(transaction=True)
def prefixed_user(local_authenticator):
    user = User.objects.create(username='dab:foo')
    user.set_password("pass")
    user.save()
    return user


def test_prefixed_user_can_login_with_original_username(prefixed_user):
    url = get_relative_url("rest_framework:login")
    me_url = get_relative_url("user-me")
    client = APIClient()

    data = {"username": "foo", "password": "pass"}
    resp = client.post(url, data=data, follow=True)
    resp = client.get(me_url)

    assert resp.status_code == 200
    assert resp.data["username"] == "dab:foo"


def test_prefixed_user_can_login_with_prefixed_username(prefixed_user):
    url = get_relative_url("rest_framework:login")
    me_url = get_relative_url("user-me")
    client = APIClient()

    data = {"username": "dab:foo", "password": "pass"}
    resp = client.post(url, data=data, follow=True)
    resp = client.get(me_url)

    assert resp.status_code == 200
    assert resp.data["username"] == "dab:foo"
