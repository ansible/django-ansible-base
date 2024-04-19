import pytest

from ansible_base.oauth2_provider.models import OAuth2Application


@pytest.fixture
def oauth2_application(randname):
    return OAuth2Application.objects.create(
        name=randname("OAuth2 Application"),
        description="Test OAuth2 Application",
        redirect_uris="http://example.com/callback",
        authorization_grant_type="authorization-code",
        client_type="confidential",
    )
