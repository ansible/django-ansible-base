import pytest
from django.urls import reverse

from ansible_base.oauth2_provider.models import OAuth2Application


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 200),
        ("user_api_client", 200),
        ("client", 401),
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
        assert response.data['results'][0]['name'] == oauth2_application.name


@pytest.mark.parametrize(
    "client_fixture,expected_status",
    [
        ("admin_api_client", 200),
        ("user_api_client", 200),
        ("client", 401),
    ],
)
@pytest.mark.django_db
def test_oauth2_provider_application_detail(request, client_fixture, expected_status, oauth2_application):
    """
    Test that we can view the detail of an OAuth2 application iff we are authenticated.
    """
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
        ("user_api_client", 201),
        ("client", 401),
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
            'redirect_uris': 'http://example.com/callback',
            'authorization_grant_type': 'authorization-code',
            'client_type': 'confidential',
        },
    )
    assert response.status_code == expected_status, response.data
    if expected_status == 201:
        assert response.data['name'] == name
        assert OAuth2Application.objects.get(pk=response.data['id']).organization == organization
