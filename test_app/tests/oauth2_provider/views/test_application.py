import pytest
from django.contrib.auth.hashers import check_password
from django.urls import reverse

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application, OAuth2RefreshToken


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 200),
        pytest.param("user_api_client", 200, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ("unauthenticated_api_client", 401),
    ],
)
@pytest.mark.django_db
def test_oauth2_provider_application_list(request, client_fixture, expected_status, oauth2_application):
    """
    Test that we can view the list of OAuth2 applications iff we are authenticated.
    """
    client = request.getfixturevalue(client_fixture)
    url = reverse("application-list")
    response = client.get(url)
    assert response.status_code == expected_status
    if expected_status == 200:
        assert len(response.data['results']) == OAuth2Application.objects.count()
        assert response.data['results'][0]['name'] == oauth2_application[0].name


@pytest.mark.parametrize(
    "view, path",
    [
        ("application-list", lambda data: data['results'][0]),
        ("application-detail", lambda data: data),
    ],
)
def test_oauth2_provider_application_related(admin_api_client, oauth2_application, organization, view, path):
    """
    Test that the related fields are correct.

    Organization should only be shown if the application is associated with an organization.
    Associating an application with an organization should not affect other related fields.
    """
    oauth2_application = oauth2_application[0]
    if view == "application-list":
        url = reverse(view)
    else:
        url = reverse(view, args=[oauth2_application.pk])

    oauth2_application.organization = None
    oauth2_application.save()
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert path(response.data)['related']['access_tokens'] == reverse("application-access_tokens-list", args=[oauth2_application.pk])
    assert 'organization' not in path(response.data)['related']

    oauth2_application.organization = organization
    oauth2_application.save()
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert path(response.data)['related']['access_tokens'] == reverse("application-access_tokens-list", args=[oauth2_application.pk])
    assert path(response.data)['related']['organization'] == reverse("organization-detail", args=[organization.pk])


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 200),
        pytest.param("user_api_client", 200, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ("unauthenticated_api_client", 401),
    ],
)
@pytest.mark.django_db
def test_oauth2_provider_application_detail(request, client_fixture, expected_status, oauth2_application):
    """
    Test that we can view the detail of an OAuth2 application iff we are authenticated.
    """
    oauth2_application = oauth2_application[0]
    client = request.getfixturevalue(client_fixture)
    url = reverse("application-detail", args=[oauth2_application.pk])
    response = client.get(url)
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.data['name'] == oauth2_application.name


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 201),
        pytest.param("user_api_client", 201, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ("unauthenticated_api_client", 401),
    ],
)
def test_oauth2_provider_application_create(request, client_fixture, expected_status, randname, organization):
    """
    As an admin, I should be able to create an OAuth2 application.
    """
    client = request.getfixturevalue(client_fixture)
    url = reverse("application-list")
    name = randname("Test Application")
    response = client.post(
        url,
        data={
            'name': name,
            'description': 'Test Description',
            'organization': organization.pk,
            'redirect_uris': 'https://example.com/callback',
            'authorization_grant_type': 'authorization-code',
            'client_type': 'confidential',
        },
    )
    assert response.status_code == expected_status, response.data
    if expected_status == 201:
        assert response.data['name'] == name
        assert OAuth2Application.objects.get(pk=response.data['id']).organization == organization

        created_app = OAuth2Application.objects.get(client_id=response.data['client_id'])
        assert created_app.name == name
        assert not created_app.skip_authorization
        assert created_app.redirect_uris == 'https://example.com/callback'
        assert created_app.client_type == 'confidential'
        assert created_app.authorization_grant_type == 'authorization-code'
        assert created_app.organization == organization


def test_oauth2_provider_application_validator(admin_api_client):
    """
    If we don't get enough information in the request, we should 400
    """
    url = reverse("application-list")
    response = admin_api_client.post(
        url,
        data={
            'name': 'test app',
            'authorization_grant_type': 'authorization-code',
            'client_type': 'confidential',
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 200),
        pytest.param("user_api_client", 200, marks=pytest.mark.xfail(reason="https://github.com/ansible/django-ansible-base/issues/424")),
        ("unauthenticated_api_client", 401),
    ],
)
@pytest.mark.django_db
def test_oauth2_provider_application_update(request, client_fixture, expected_status, oauth2_application):
    """
    Test that we can update oauth2 applications iff we are authenticated.
    """
    oauth2_application = oauth2_application[0]
    client = request.getfixturevalue(client_fixture)
    url = reverse("application-detail", args=[oauth2_application.pk])
    response = client.patch(
        url,
        data={
            'name': 'Updated Name',
            'description': 'Updated Description',
            'redirect_uris': 'http://example.com/updated',
            'client_type': 'public',
        },
    )
    assert response.status_code == expected_status, response.data
    if expected_status == 200:
        assert response.data['name'] == 'Updated Name'
        assert response.data['description'] == 'Updated Description'
        assert response.data['redirect_uris'] == 'http://example.com/updated'
        assert response.data['client_type'] == 'public'
        oauth2_application.refresh_from_db()
        assert oauth2_application.name == 'Updated Name'
        assert oauth2_application.description == 'Updated Description'
        assert oauth2_application.redirect_uris == 'http://example.com/updated'
        assert oauth2_application.client_type == 'public'


def test_oauth2_provider_application_client_secret_encrypted(admin_api_client, organization):
    """
    The client_secret should be encrypted in the database.
    We only show it to the user once, on creation. All other requests should show the encrypted value.
    """
    url = reverse("application-list")

    # POST
    response = admin_api_client.post(
        url,
        data={
            'name': 'Test Application',
            'description': 'Test Description',
            'organization': organization.pk,
            'redirect_uris': 'https://example.com/callback',
            'authorization_grant_type': 'authorization-code',
            'client_type': 'confidential',
        },
    )
    assert response.status_code == 201, response.data
    application = OAuth2Application.objects.get(pk=response.data['id'])

    # If we ever switch to using *our* encryption, this is a good test.
    # But until a release with jazzband/django-oauth-toolkit#1311 hits pypi,
    # we have no way to disable their built-in hashing (which conflicts with our
    # own encryption).
    # with connection.cursor() as cursor:
    #     cursor.execute("SELECT client_secret FROM dab_oauth2_provider_oauth2application WHERE id = %s", [application.pk])
    #     encrypted = cursor.fetchone()[0]
    # assert encrypted.startswith(ENCRYPTED_STRING), encrypted
    # assert ansible_encryption.decrypt_string(encrypted) == response.data['client_secret'], response.data
    # assert response.data['client_secret'] == application.client_secret

    # For now we just make sure it shows the real client secret on POST
    # and never on any other method.
    assert 'client_secret' in response.data
    assert check_password(response.data['client_secret'], application.client_secret)

    # GET
    response = admin_api_client.get(reverse("application-detail", args=[application.pk]))
    assert response.status_code == 200
    assert response.data['client_secret'] == ENCRYPTED_STRING, response.data

    # PATCH
    response = admin_api_client.patch(
        reverse("application-detail", args=[application.pk]),
        data={'name': 'Updated Name'},
    )
    assert response.status_code == 200
    assert response.data['client_secret'] == ENCRYPTED_STRING, response.data

    # PUT
    response = admin_api_client.put(
        reverse("application-detail", args=[application.pk]),
        data={
            'name': 'Updated Name',
            'description': 'Updated Description',
            'organization': organization.pk,
            'redirect_uris': 'http://example.com/updated',
            'client_type': 'public',
            'authorization_grant_type': 'password',
        },
    )
    assert response.status_code == 200
    assert 'client_secret' not in response.data

    # DELETE
    response = admin_api_client.delete(reverse("application-detail", args=[application.pk]))
    assert response.status_code == 204
    assert response.data is None, response.data


@pytest.mark.django_db
def test_oauth2_application_delete(oauth2_application, admin_api_client):
    """
    Test that we can delete an OAuth2 application.
    """
    oauth2_application = oauth2_application[0]
    url = reverse("application-detail", args=[oauth2_application.pk])
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert OAuth2Application.objects.filter(client_id=oauth2_application.client_id).count() == 0
    assert OAuth2RefreshToken.objects.filter(application=oauth2_application).count() == 0
    assert OAuth2AccessToken.objects.filter(application=oauth2_application).count() == 0


@pytest.mark.django_db
def test_oauth2_application_prevent_search_client_secret(oauth2_application, admin_api_client):
    url = reverse("application-list")
    query_params = {
        'client_secret__isnull': False,
    }
    response = admin_api_client.get(url, data=query_params)
    assert response.status_code == 403
    assert 'Filtering on client_secret is not allowed' in response.data['detail']

    # Also ensure we don't leak the client_secret in activity stream
    creation_entry = oauth2_application[0].activity_stream_entries.first()
    assert creation_entry.changes['added_fields']['client_secret'] == ENCRYPTED_STRING
