import pytest
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url
from test_app.models import User


@pytest.mark.django_db(transaction=True)
def test_prefixed_username_login(local_authenticator):
    user = User.objects.create(username='dab:foo')
    user.set_password("pass")
    user.save()

    url = get_relative_url("rest_framework:login")
    me_url = get_relative_url("user-me")

    # Check that the user can login with their unprefixed username
    client = APIClient()
    data = {"username": "foo", "password": "pass"}
    resp = client.post(url, data=data, follow=True)
    resp = client.get(me_url)

    assert resp.status_code == 200
    assert resp.data["username"] == "dab:foo"

    # Check that the user can login with their prefixed username
    client = APIClient()
    assert client.get(me_url).status_code == 401

    data = {"username": "dab:foo", "password": "pass"}
    resp = client.post(url, data=data, follow=True)
    resp = client.get(me_url)

    assert resp.status_code == 200
    assert resp.data["username"] == "dab:foo"
