import pytest
from django.contrib.auth import get_user_model

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils.authentication import determine_username_from_uid_social, get_or_create_authenticator_user
from ansible_base.lib.utils.response import get_relative_url
from test_app.models import ThingSomeoneOwns, ThingSomeoneShares

User = get_user_model()


def authenticator_user_factory(uid, username, authenticator, things=[]):
    user, _ = User.objects.get_or_create(username=username)
    auth_user = AuthenticatorUser.objects.create(uid=uid, user=user, provider=authenticator)

    for thing in things:
        ThingSomeoneOwns.objects.create(owner=user, thing=thing)

    return auth_user


def get_social_pipeline_kwargs(uid, username, authenticator, **kwargs):
    return {
        "uid": uid,
        "details": {"username": username},
        "backend": get_authenticator_class(authenticator.type)(database_instance=authenticator),
        **kwargs,
    }


@pytest.mark.django_db
def test_migrate_single_user(oidc_authenticator, keycloak_authenticator):
    oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
    oidc_authenticator.save()

    oidc_user = authenticator_user_factory("a9a3b88a-7c1a-4fd8-b735-f20c338debcc", "oidc_user", oidc_authenticator).user

    kwargs = get_social_pipeline_kwargs(
        uid="oidc_user", username="oidc_user", authenticator=keycloak_authenticator, response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"}
    )
    username = determine_username_from_uid_social(**kwargs)

    oidc_user.refresh_from_db()

    assert username["username"] == "oidc_user"
    assert not AuthenticatorUser.objects.filter(provider=oidc_authenticator, user=oidc_user).exists()


@pytest.mark.django_db
def test_migrate_single_user_existing(oidc_authenticator, keycloak_authenticator):
    oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
    oidc_authenticator.save()

    shared_thing = ThingSomeoneShares.objects.create(thing="shared")
    share_user = User.objects.create(username="sharing_is_caring")
    share_user.things_i_share.add(shared_thing)

    oidc_user = authenticator_user_factory(
        "a9a3b88a-7c1a-4fd8-b735-f20c338debcc",
        "oidc_user",
        oidc_authenticator,
        things=[
            "thing1",
            "conflict_thing",
        ],
    ).user

    oidc_user.things_i_share.add(shared_thing)

    kc_user = authenticator_user_factory(
        "kc_user",
        "kc_user",
        keycloak_authenticator,
        things=[
            "thing2",
            "conflict_thing",
        ],
    ).user

    kwargs = get_social_pipeline_kwargs(
        uid="kc_user", username="kc_user", authenticator=keycloak_authenticator, response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"}
    )
    username = determine_username_from_uid_social(**kwargs)

    kc_user.refresh_from_db()

    assert username["username"] == "kc_user"
    assert not AuthenticatorUser.objects.filter(provider=oidc_authenticator, user=kc_user).exists()
    assert not User.objects.filter(username="oidc_user").exists()

    assert set(kc_user.things_i_own.values_list("thing", flat=True)) == set(["thing1", "thing2", "conflict_thing"])
    assert kc_user.things_i_share.filter(thing="shared").exists()
    assert share_user.things_i_share.filter(thing="shared").exists()


@pytest.mark.django_db
def test_migrate_single_user_existing_preferred_username(oidc_authenticator, keycloak_authenticator):
    oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
    oidc_authenticator.save()

    authenticator_user_factory("a9a3b88a-7c1a-4fd8-b735-f20c338debcc", "i_want_this_username", oidc_authenticator).user
    kc_user = authenticator_user_factory("kc_user", "i_dont_want_this_username", keycloak_authenticator).user

    kwargs = get_social_pipeline_kwargs(
        uid="kc_user",
        username="i_want_this_username",
        authenticator=keycloak_authenticator,
        response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"},
    )
    username = determine_username_from_uid_social(**kwargs)

    kc_user.refresh_from_db()

    assert username["username"] == "i_want_this_username"
    assert not AuthenticatorUser.objects.filter(provider=oidc_authenticator, user=kc_user).exists()
    assert User.objects.filter(username="i_want_this_username").exists()
    assert not User.objects.filter(username="i_dont_want_this_username").exists()


@pytest.mark.django_db
def test_migrate_multiple_user_new(oidc_authenticator, keycloak_authenticator, saml_authenticator):
    oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
    saml_authenticator.auto_migrate_users_to = keycloak_authenticator

    # give oidc priority
    oidc_authenticator.order = 1000
    oidc_authenticator.save()
    saml_authenticator.save()

    shared_thing = ThingSomeoneShares.objects.create(thing="shared")
    share_user = User.objects.create(username="sharing_is_caring")
    share_user.things_i_share.add(shared_thing)

    oidc_user = authenticator_user_factory(
        "a9a3b88a-7c1a-4fd8-b735-f20c338debcc",
        "oidc_user",
        oidc_authenticator,
        things=[
            "thing1",
            "conflict_thing",
        ],
    ).user

    oidc_user.things_i_share.add(shared_thing)

    saml_user = authenticator_user_factory(
        "IdP:my_user_id",
        "saml_user",
        saml_authenticator,
        things=[
            "thing2",
            "conflict_thing",
        ],
    ).user

    saml_user.things_i_share.add(shared_thing)

    kwargs = get_social_pipeline_kwargs(
        uid="my_user_id", username="kc_user", authenticator=keycloak_authenticator, response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"}
    )
    username = determine_username_from_uid_social(**kwargs)

    saml_user.refresh_from_db()

    assert username["username"] == "kc_user"
    assert saml_user.username == "kc_user"
    assert not AuthenticatorUser.objects.filter(provider=oidc_authenticator, user=saml_user).exists()
    assert not AuthenticatorUser.objects.filter(provider=saml_authenticator, user=saml_user).exists()
    assert not User.objects.filter(username="oidc_user").exists()
    assert not User.objects.filter(username="saml_user").exists()

    assert set(saml_user.things_i_own.values_list("thing", flat=True)) == set(["thing1", "thing2", "conflict_thing"])
    assert saml_user.things_i_share.filter(thing="shared").exists()
    assert share_user.things_i_share.filter(thing="shared").exists()


@pytest.mark.django_db
def test_migrate_multiple_user_existing(oidc_authenticator, keycloak_authenticator, saml_authenticator):
    oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
    saml_authenticator.auto_migrate_users_to = keycloak_authenticator

    # give oidc priority
    oidc_authenticator.order = 1000
    oidc_authenticator.save()
    saml_authenticator.save()

    shared_thing = ThingSomeoneShares.objects.create(thing="shared")
    share_user = User.objects.create(username="sharing_is_caring")
    share_user.things_i_share.add(shared_thing)

    oidc_user = authenticator_user_factory(
        "a9a3b88a-7c1a-4fd8-b735-f20c338debcc",
        "oidc_user",
        oidc_authenticator,
        things=[
            "thing1",
            "conflict_thing",
        ],
    ).user

    oidc_user.things_i_share.add(shared_thing)

    saml_user = authenticator_user_factory(
        "IdP:my_user_id",
        "saml_user",
        saml_authenticator,
        things=[
            "thing2",
            "conflict_thing",
        ],
    ).user

    saml_user.things_i_share.add(shared_thing)

    kc_user = authenticator_user_factory(
        "my_user_id",
        "kc_user",
        keycloak_authenticator,
        things=[
            "thing3",
            "conflict_thing",
        ],
    ).user

    kwargs = get_social_pipeline_kwargs(
        uid="my_user_id", username="kc_user", authenticator=keycloak_authenticator, response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"}
    )
    username = determine_username_from_uid_social(**kwargs)

    kc_user.refresh_from_db()

    assert username["username"] == "kc_user"
    assert not AuthenticatorUser.objects.filter(provider=oidc_authenticator, user=kc_user).exists()
    assert not AuthenticatorUser.objects.filter(provider=saml_authenticator, user=kc_user).exists()
    assert not User.objects.filter(username="oidc_user").exists()
    assert not User.objects.filter(username="saml_user").exists()

    assert set(kc_user.things_i_own.values_list("thing", flat=True)) == set(["thing1", "thing2", "thing3", "conflict_thing"])
    assert kc_user.things_i_share.filter(thing="shared").exists()
    assert share_user.things_i_share.filter(thing="shared").exists()


@pytest.mark.django_db
def test_alt_uid_saml(saml_authenticator):
    kwargs = get_social_pipeline_kwargs(
        uid="IdP:my_user_id",
        username="kc_user",
        authenticator=saml_authenticator,
    )

    auth_plugin = get_authenticator_class(saml_authenticator.type)(database_instance=saml_authenticator)

    assert auth_plugin.get_alternative_uid(**kwargs) == "my_user_id"


@pytest.mark.django_db
def test_alt_uid_keycloak(keycloak_authenticator):
    kwargs = get_social_pipeline_kwargs(
        uid="my_user_id", username="kc_user", authenticator=keycloak_authenticator, response={"sub": "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"}
    )
    auth_plugin = get_authenticator_class(keycloak_authenticator.type)(database_instance=keycloak_authenticator)

    assert auth_plugin.get_alternative_uid(**kwargs) == "a9a3b88a-7c1a-4fd8-b735-f20c338debcc"


@pytest.mark.django_db
def test_alt_uid_oidc(oidc_authenticator):
    kwargs = get_social_pipeline_kwargs(
        uid="a9a3b88a-7c1a-4fd8-b735-f20c338debcc",
        username="kc_user",
        authenticator=oidc_authenticator,
        response={"preferred_username": "my_user_id"},
    )

    auth_plugin = get_authenticator_class(oidc_authenticator.type)(database_instance=oidc_authenticator)

    assert auth_plugin.get_alternative_uid(**kwargs) == "my_user_id"


@pytest.mark.django_db
def test_cant_chain_auto_migrate(oidc_authenticator, keycloak_authenticator, saml_authenticator, admin_api_client):
    url = get_relative_url("authenticator-detail", kwargs={'pk': oidc_authenticator.pk})
    resp = admin_api_client.patch(url, {"auto_migrate_users_to": keycloak_authenticator.pk})

    # Test that we can use the API to auto migrate oidc to keycloak
    assert resp.status_code == 200
    assert resp.data["auto_migrate_users_to"] == keycloak_authenticator.pk

    # oidc is set to auto migrate to keycloak. Ensure we can't set saml to auto migrate to oidc
    url = get_relative_url("authenticator-detail", kwargs={'pk': saml_authenticator.pk})
    resp = admin_api_client.patch(url, {"auto_migrate_users_to": oidc_authenticator.pk})

    assert resp.status_code == 400
    assert "auto_migrate_users_to" in resp.data


@pytest.mark.django_db
def test_password_based_authenticators_existing_user(ldap_authenticator, saml_authenticator):
    saml_authenticator.auto_migrate_users_to = ldap_authenticator
    saml_authenticator.save()

    authenticator_user_factory(
        "IdP:my_user_id",
        "oidc_user",
        saml_authenticator,
        things=[
            "thing1",
            "conflict_thing",
        ],
    ).user

    ldap_user = authenticator_user_factory(
        "my_user_id",
        "my_user_id",
        ldap_authenticator,
        things=[
            "thing2",
            "conflict_thing",
        ],
    ).user

    get_or_create_authenticator_user(
        uid="my_user_id",
        authenticator=ldap_authenticator,
        user_details={},
        extra_data={},
    )

    ldap_user.refresh_from_db()

    assert ldap_user.username == "my_user_id"
    assert not AuthenticatorUser.objects.filter(provider=saml_authenticator, user=ldap_user).exists()
    assert AuthenticatorUser.objects.filter(provider=ldap_authenticator, user=ldap_user).exists()
    assert not User.objects.filter(username="oidc_user").exists()

    assert set(ldap_user.things_i_own.values_list("thing", flat=True)) == set(["thing1", "thing2", "conflict_thing"])


@pytest.mark.django_db
def test_password_based_authenticators_new_user(ldap_authenticator, saml_authenticator):
    saml_authenticator.auto_migrate_users_to = ldap_authenticator
    saml_authenticator.save()

    saml_user = authenticator_user_factory(
        "IdP:my_user_id",
        "oidc_user",
        saml_authenticator,
        things=[
            "thing1",
            "conflict_thing",
        ],
    ).user

    user, _, _ = get_or_create_authenticator_user(
        uid="my_user_id",
        authenticator=ldap_authenticator,
        user_details={},
        extra_data={},
    )

    saml_user.refresh_from_db()

    assert saml_user.username == "my_user_id"
    assert saml_user == user
    assert not AuthenticatorUser.objects.filter(provider=saml_authenticator, user=saml_user).exists()
    assert AuthenticatorUser.objects.filter(provider=ldap_authenticator, user=saml_user).exists()
    assert not User.objects.filter(username="oidc_user").exists()

    assert set(saml_user.things_i_own.values_list("thing", flat=True)) == set(["thing1", "conflict_thing"])
