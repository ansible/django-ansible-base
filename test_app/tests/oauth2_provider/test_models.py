import pytest

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken


@pytest.mark.django_db
def test_oauth2_revoke_access_then_refresh_token(oauth2_admin_access_token):
    token = oauth2_admin_access_token
    refresh_token = oauth2_admin_access_token.refresh_token
    assert OAuth2AccessToken.objects.count() == 1
    assert OAuth2RefreshToken.objects.count() == 1

    token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1
    assert not refresh_token.revoked

    refresh_token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1


@pytest.mark.django_db
def test_oauth2_revoke_refresh_token(oauth2_admin_access_token):
    refresh_token = oauth2_admin_access_token.refresh_token
    assert OAuth2AccessToken.objects.count() == 1
    assert OAuth2RefreshToken.objects.count() == 1

    refresh_token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    # the same OAuth2RefreshToken is recycled
    new_refresh_token = OAuth2RefreshToken.objects.all().first()
    assert refresh_token == new_refresh_token
    assert new_refresh_token.revoked
