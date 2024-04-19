# @pytest.mark.django_db
# def test_oauth_application_update(oauth_application, organization, patch, admin, alice):
#     patch(
#         reverse('api:o_auth2_application_detail', kwargs={'pk': oauth_application.pk}),
#         {
#             'name': 'Test app with immutable grant type and user',
#             'organization': organization.pk,
#             'redirect_uris': 'http://localhost/api/',
#             'authorization_grant_type': 'password',
#             'skip_authorization': True,
#         },
#         admin,
#         expect=200,
#     )
#     updated_app = Application.objects.get(client_id=oauth_application.client_id)
#     assert updated_app.name == 'Test app with immutable grant type and user'
#     assert updated_app.redirect_uris == 'http://localhost/api/'
#     assert updated_app.skip_authorization is True
#     assert updated_app.authorization_grant_type == 'password'
#     assert updated_app.organization == organization
#
#
# @pytest.mark.django_db
# def test_oauth_application_encryption(admin, organization, post):
#     response = post(
#         reverse('api:o_auth2_application_list'),
#         {
#             'name': 'test app',
#             'organization': organization.pk,
#             'client_type': 'confidential',
#             'authorization_grant_type': 'password',
#         },
#         admin,
#         expect=201,
#     )
#     pk = response.data.get('id')
#     secret = response.data.get('client_secret')
#     with connection.cursor() as cursor:
#         encrypted = cursor.execute('SELECT client_secret FROM main_oauth2application WHERE id={}'.format(pk)).fetchone()[0]
#         assert encrypted.startswith('$encrypted$')
#         assert decrypt_value(get_encryption_key('value', pk=None), encrypted) == secret
#
# @pytest.mark.django_db
# def test_oauth_token_create(oauth_application, get, post, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     assert 'modified' in response.data and response.data['modified'] is not None
#     assert 'updated' not in response.data
#     token = AccessToken.objects.get(token=response.data['token'])
#     refresh_token = RefreshToken.objects.get(token=response.data['refresh_token'])
#     assert token.application == oauth_application
#     assert refresh_token.application == oauth_application
#     assert token.user == admin
#     assert refresh_token.user == admin
#     assert refresh_token.access_token == token
#     assert token.scope == 'read'
#     response = get(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), admin, expect=200)
#     assert response.data['count'] == 1
#     response = get(reverse('api:o_auth2_application_detail', kwargs={'pk': oauth_application.pk}), admin, expect=200)
#     assert response.data['summary_fields']['tokens']['count'] == 1
#     assert response.data['summary_fields']['tokens']['results'][0] == {'id': token.pk, 'scope': token.scope, 'token': '************'}
#
#     response = post(reverse('api:o_auth2_token_list'), {'scope': 'read', 'application': oauth_application.pk}, admin, expect=201)
#     assert response.data['refresh_token']
#     response = post(
#         reverse('api:user_authorized_token_list', kwargs={'pk': admin.pk}), {'scope': 'read', 'application': oauth_application.pk}, admin, expect=201
#     )
#     assert response.data['refresh_token']
#     response = post(reverse('api:application_o_auth2_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     assert response.data['refresh_token']
#
#
# @pytest.mark.django_db
# def test_oauth_token_update(oauth_application, post, patch, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     token = AccessToken.objects.get(token=response.data['token'])
#     patch(reverse('api:o_auth2_token_detail', kwargs={'pk': token.pk}), {'scope': 'write'}, admin, expect=200)
#     token = AccessToken.objects.get(token=token.token)
#     assert token.scope == 'write'
#
#
# @pytest.mark.django_db
# def test_oauth_token_delete(oauth_application, post, delete, get, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     token = AccessToken.objects.get(token=response.data['token'])
#     delete(reverse('api:o_auth2_token_detail', kwargs={'pk': token.pk}), admin, expect=204)
#     assert AccessToken.objects.count() == 0
#     assert RefreshToken.objects.count() == 1
#     response = get(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), admin, expect=200)
#     assert response.data['count'] == 0
#     response = get(reverse('api:o_auth2_application_detail', kwargs={'pk': oauth_application.pk}), admin, expect=200)
#     assert response.data['summary_fields']['tokens']['count'] == 0
#
#
# @pytest.mark.django_db
# def test_oauth_application_delete(oauth_application, post, delete, admin):
#     post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     delete(reverse('api:o_auth2_application_detail', kwargs={'pk': oauth_application.pk}), admin, expect=204)
#     assert Application.objects.filter(client_id=oauth_application.client_id).count() == 0
#     assert RefreshToken.objects.filter(application=oauth_application).count() == 0
#     assert AccessToken.objects.filter(application=oauth_application).count() == 0
#
# @pytest.mark.django_db
# def test_refresh_accesstoken(oauth_application, post, get, delete, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     assert AccessToken.objects.count() == 1
#     assert RefreshToken.objects.count() == 1
#     token = AccessToken.objects.get(token=response.data['token'])
#     refresh_token = RefreshToken.objects.get(token=response.data['refresh_token'])
#
#     refresh_url = drf_reverse('api:oauth_authorization_root_view') + 'token/'
#     response = post(
#         refresh_url,
#         data='grant_type=refresh_token&refresh_token=' + refresh_token.token,
#         content_type='application/x-www-form-urlencoded',
#         HTTP_AUTHORIZATION='Basic ' + smart_str(base64.b64encode(smart_bytes(':'.join([oauth_application.client_id, oauth_application.client_secret])))),
#     )
#     assert RefreshToken.objects.filter(token=refresh_token).exists()
#     original_refresh_token = RefreshToken.objects.get(token=refresh_token)
#     assert token not in AccessToken.objects.all()
#     assert AccessToken.objects.count() == 1
#     # the same RefreshToken remains but is marked revoked
#     assert RefreshToken.objects.count() == 2
#     new_token = json.loads(response._container[0])['access_token']
#     new_refresh_token = json.loads(response._container[0])['refresh_token']
#     assert AccessToken.objects.filter(token=new_token).count() == 1
#     # checks that RefreshTokens are rotated (new RefreshToken issued)
#     assert RefreshToken.objects.filter(token=new_refresh_token).count() == 1
#     assert original_refresh_token.revoked  # is not None
#
#
# @pytest.mark.django_db
# def test_refresh_token_expiration_is_respected(oauth_application, post, get, delete, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     assert AccessToken.objects.count() == 1
#     assert RefreshToken.objects.count() == 1
#     refresh_token = RefreshToken.objects.get(token=response.data['refresh_token'])
#     refresh_url = drf_reverse('api:oauth_authorization_root_view') + 'token/'
#     short_lived = {'ACCESS_TOKEN_EXPIRE_SECONDS': 1, 'AUTHORIZATION_CODE_EXPIRE_SECONDS': 1, 'REFRESH_TOKEN_EXPIRE_SECONDS': 1}
#     time.sleep(1)
#     with override_settings(OAUTH2_PROVIDER=short_lived):
#         response = post(
#             refresh_url,
#             data='grant_type=refresh_token&refresh_token=' + refresh_token.token,
#             content_type='application/x-www-form-urlencoded',
#             HTTP_AUTHORIZATION='Basic ' + smart_str(base64.b64encode(smart_bytes(':'.join([oauth_application.client_id, oauth_application.client_secret])))),
#         )
#     assert response.status_code == 403
#     assert b'The refresh token has expired.' in response.content
#     assert RefreshToken.objects.filter(token=refresh_token).exists()
#     assert AccessToken.objects.count() == 1
#     assert RefreshToken.objects.count() == 1
#
#
# @pytest.mark.django_db
# def test_revoke_access_then_refreshtoken(oauth_application, post, get, delete, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     token = AccessToken.objects.get(token=response.data['token'])
#     refresh_token = RefreshToken.objects.get(token=response.data['refresh_token'])
#     assert AccessToken.objects.count() == 1
#     assert RefreshToken.objects.count() == 1
#
#     token.revoke()
#     assert AccessToken.objects.count() == 0
#     assert RefreshToken.objects.count() == 1
#     assert not refresh_token.revoked
#
#     refresh_token.revoke()
#     assert AccessToken.objects.count() == 0
#     assert RefreshToken.objects.count() == 1
#
#
# @pytest.mark.django_db
# def test_revoke_refreshtoken(oauth_application, post, get, delete, admin):
#     response = post(reverse('api:o_auth2_application_token_list', kwargs={'pk': oauth_application.pk}), {'scope': 'read'}, admin, expect=201)
#     refresh_token = RefreshToken.objects.get(token=response.data['refresh_token'])
#     assert AccessToken.objects.count() == 1
#     assert RefreshToken.objects.count() == 1
#
#     refresh_token.revoke()
#     assert AccessToken.objects.count() == 0
#     # the same RefreshToken is recycled
#     new_refresh_token = RefreshToken.objects.all().first()
#     assert refresh_token == new_refresh_token
#     assert new_refresh_token.revoked
