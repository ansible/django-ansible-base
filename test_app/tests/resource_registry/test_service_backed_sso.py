from unittest import mock

import jwt
import pytest
from social_django.models import UserSocialAuth
from social_django.storage import BaseDjangoStorage
from social_django.strategy import DjangoStrategy

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.utils.auth_code import get_user_auth_code
from ansible_base.resource_registry.utils.service_backed_sso_pipeline import redirect_to_resource_server


def _validate_auth_code(auth_code, user):
    cfg = get_resource_server_config()

    data = jwt.decode(
        auth_code,
        cfg["SECRET_KEY"],
        algorithms=cfg["JWT_ALGORITHM"],
        required=["iss", "exp"],
    )

    assert data["username"] == user.username
    assert data["sub"] == str(user.resource.ansible_id)

    return data


@pytest.fixture
def patched_load_strategy():
    def _get_strat():
        return DjangoStrategy(storage=BaseDjangoStorage())

    with mock.patch("ansible_base.resource_registry.utils.sso_provider.load_strategy", _get_strat) as get_strat:
        yield get_strat


@pytest.fixture
def authenticator_user(user, github_authenticator):
    AuthenticatorUser.objects.create(provider=github_authenticator, user=user, uid="my_uid")

    return user, user.authenticator_users.first()


@pytest.fixture
def social_user(user, patched_load_strategy):
    UserSocialAuth.objects.create(provider="github", user=user, uid="my_uid")

    return user, user.social_auth.first()


@pytest.mark.django_db
def test_user_auth_code_generation_social_auth(social_user):
    user, social = social_user
    auth_code = get_user_auth_code(user)
    data = _validate_auth_code(auth_code, user)
    assert data["sso_uid"] is None
    assert data["sso_backend"] is None

    auth_code = get_user_auth_code(user, social_user=social)
    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_user_auth_code_generation_dab(authenticator_user):
    user, social = authenticator_user
    auth_code = get_user_auth_code(user)
    data = _validate_auth_code(auth_code, user)
    assert data["sso_uid"] is None
    assert data["sso_backend"] is None

    auth_code = get_user_auth_code(user, social_user=social)
    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider.slug
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_auth_code_pipeline(social_user):
    user, social = social_user

    resp = redirect_to_resource_server(user=user, social=social)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_auth_code_pipeline_dab(authenticator_user):
    user, social = authenticator_user

    resp = redirect_to_resource_server(user=user, social=social)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider.slug
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_auth_code_pipeline_no_social(user):
    resp = redirect_to_resource_server(user=user)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] is None
    assert data["sso_backend"] is None
    assert data["sso_server"] is None


@pytest.mark.django_db
def test_auth_code_pipeline_not_authed():
    assert redirect_to_resource_server(user=None, social=None) is None
