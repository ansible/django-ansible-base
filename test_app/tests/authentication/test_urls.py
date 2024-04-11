import importlib
from unittest import mock

import pytest
from django.urls.resolvers import URLResolver

from ansible_base.authentication import views


@pytest.mark.parametrize(
    'view_set,expect_url',
    (
        (None, False),
        (views.AuthenticatorMapViewSet, True),
    ),
)
def test_authentication_user_in_urls(view_set, expect_url):
    from ansible_base.authentication import urls

    with mock.patch('ansible_base.authentication.views.authenticator_users.get_authenticator_user_view', return_value=view_set):
        importlib.reload(urls)
        url_names = []
        for url in urls.api_version_urls:
            if isinstance(url, URLResolver):
                for url in url.url_patterns:
                    url_names.append(url.name)
            else:
                url_names.append(url.name)

        expected_url_name = 'authenticator-users-list'
        if expect_url:
            assert expected_url_name in url_names
        else:
            assert expected_url_name not in url_names
