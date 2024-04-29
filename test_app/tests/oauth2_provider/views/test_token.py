import base64

import pytest
from django.urls import reverse
from django.utils.http import urlencode


@pytest.mark.django_db
def test_oauth2_personal_access_token_creation(oauth2_application, user, unauthenticated_api_client):
    app = oauth2_application[0]
    app.authorization_grant_type = 'password'
    app.save()

    secret = oauth2_application[1]
    url = reverse('token')
    data = {
        "grant_type": "password",
        "username": "user",
        "password": "password",
        "scope": "read",
    }
    resp = unauthenticated_api_client.post(
        url,
        data=urlencode(data),
        content_type='application/x-www-form-urlencoded',
        headers={'Authorization': 'Basic ' + base64.b64encode(f"{app.client_id}:{secret}".encode()).decode()},
    )

    assert resp.status_code == 200, resp.content
    resp_json = resp.json()
    assert 'access_token' in resp_json
    assert len(resp_json['access_token']) > 0
    assert 'scope' in resp_json
    assert resp_json['scope'] == 'read'
    assert 'refresh_token' in resp_json


#
# @pytest.mark.django_db
# @pytest.mark.parametrize('allow_oauth, status', [(True, 201), (False, 403)])
# def test_token_creation_disabled_for_external_accounts(oauth_application, post, alice, allow_oauth, status):
#     UserEnterpriseAuth(user=alice, provider='radius').save()
#     url = drf_reverse('api:oauth_authorization_root_view') + 'token/'
#
#     with override_settings(RADIUS_SERVER='example.org', ALLOW_OAUTH2_FOR_EXTERNAL_USERS=allow_oauth):
#         resp = post(
#             url,
#             data='grant_type=password&username=alice&password=alice&scope=read',
#             content_type='application/x-www-form-urlencoded',
#             HTTP_AUTHORIZATION='Basic ' + smart_str(base64.b64encode(smart_bytes(':'.join([oauth_application.client_id, oauth_application.client_secret])))),
#             status=status,
#         )
#         if allow_oauth:
#             assert AccessToken.objects.count() == 1
#         else:
#             assert 'OAuth2 Tokens cannot be created by users associated with an external authentication provider' in smart_str(resp.content)  # noqa
#             assert AccessToken.objects.count() == 0
#
# @pytest.mark.django_db
# def test_existing_token_enabled_for_external_accounts(oauth_application, get, post, admin):
#     UserEnterpriseAuth(user=admin, provider='radius').save()
#     url = drf_reverse('api:oauth_authorization_root_view') + 'token/'
#     with override_settings(RADIUS_SERVER='example.org', ALLOW_OAUTH2_FOR_EXTERNAL_USERS=True):
#         resp = post(
#             url,
#             data='grant_type=password&username=admin&password=admin&scope=read',
#             content_type='application/x-www-form-urlencoded',
#             HTTP_AUTHORIZATION='Basic ' + smart_str(base64.b64encode(smart_bytes(':'.join([oauth_application.client_id, oauth_application.client_secret])))),
#             status=201,
#         )
#         token = json.loads(resp.content)['access_token']
#         assert AccessToken.objects.count() == 1
#
#         with immediate_on_commit():
#             resp = get(drf_reverse('api:user_me_list', kwargs={'version': 'v2'}), HTTP_AUTHORIZATION='Bearer ' + token, status=200)
#             assert json.loads(resp.content)['results'][0]['username'] == 'admin'
#
#     with override_settings(RADIUS_SERVER='example.org', ALLOW_OAUTH2_FOR_EXTERNAL_USER=False):
#         with immediate_on_commit():
#             resp = get(drf_reverse('api:user_me_list', kwargs={'version': 'v2'}), HTTP_AUTHORIZATION='Bearer ' + token, status=200)
#             assert json.loads(resp.content)['results'][0]['username'] == 'admin'
#
# @pytest.mark.django_db
# def test_pat_creation_no_default_scope(oauth_application, post, admin):
#     # tests that the default scope is overriden
#     url = reverse('api:o_auth2_token_list')
#     response = post(
#         url,
#         {
#             'description': 'test token',
#             'scope': 'read',
#             'application': oauth_application.pk,
#         },
#         admin,
#     )
#     assert response.data['scope'] == 'read'
#
# @pytest.mark.django_db
# def test_pat_creation_no_scope(oauth_application, post, admin):
#     url = reverse('api:o_auth2_token_list')
#     response = post(
#         url,
#         {
#             'description': 'test token',
#             'application': oauth_application.pk,
#         },
#         admin,
#     )
#     assert response.data['scope'] == 'write'
#


@pytest.mark.django_db
def test_oauth2_provider_list_user_tokens(unauthenticated_api_client, admin_user, random_user):
    for user in (admin_user, random_user):
        unauthenticated_api_client.login(username=user.username, password=user.password)
        url = reverse('api:o_auth2_token_list', kwargs={'pk': user.pk})
        response = unauthenticated_api_client.post(url, data={'scope': 'read'})
        assert response.status_code == 201
        assert response.json()['count'] == 1
