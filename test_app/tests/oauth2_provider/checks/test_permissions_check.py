import copy
from typing import Type
from unittest import mock

import pytest
from django.core.checks import Debug, Error, Warning
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.urls import path
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from ansible_base.authentication.authenticator_plugins.saml import SAMLMetadataView
from ansible_base.authentication.views.authenticator import AuthenticatorViewSet
from ansible_base.authentication.views.ui_auth import UIAuth
from ansible_base.lib.utils.views.urls import get_api_view_functions
from ansible_base.oauth2_provider.checks.permisssions_check import oauth2_permission_scope_check, view_in_app_configs
from test_app import views

urlpatterns = [
    # APIView without OAuth2ScopePermission (needs patch)
    path('api/users/', views.UserViewSet.as_view({"get": "list"}), name='user-view'),
    # APIView with OAuth2ScopePermission (happy path)
    path('api/teams/', views.TeamViewSet.as_view({"get": "list"}), name='team-list'),
    # APIView with binary Operands (Needs patch)
    path('api/authenticators/', AuthenticatorViewSet.as_view({"get": "list"}), name="authenticator-list"),
    # APIView with inverted OAuth2ScopePermission (need patch)
    path('api/organizations/', views.OrganizationViewSet.as_view({"get": "list"}), name="organization-list"),
    # Ignored view (ignored in settings.py)
    path('/docs/', SpectacularSwaggerView.as_view()),
    # Fully permissive APIView (via empty permission classes)
    path('/ui-auth/', UIAuth.as_view()),
    # Non-ApiView view
    path('/non-api-view/', SAMLMetadataView.as_view()),
]


@pytest.fixture
def missing_permissions_view_class():
    PatchedUserViewSet = copy.deepcopy(views.UserViewSet)
    PatchedUserViewSet.permission_classes = [~AllowAny]
    with mock.patch("test_app.views.UserViewSet", PatchedUserViewSet):
        yield PatchedUserViewSet


@pytest.fixture
def inverted_permissions_view_class():
    from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

    PatchedOrganizationViewSet = copy.deepcopy(views.OrganizationViewSet)
    PatchedOrganizationViewSet.permission_classes = [~OAuth2ScopePermission]
    with mock.patch("test_app.views.OrganizationViewSet", PatchedOrganizationViewSet):
        yield PatchedOrganizationViewSet


@pytest.fixture
def nested_permissions_view_class():
    from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

    PatchedAuthenticatorViewSet = copy.deepcopy(AuthenticatorViewSet)
    PatchedAuthenticatorViewSet.permission_classes = [OAuth2ScopePermission & AllowAny]
    with mock.patch("ansible_base.authentication.views.authenticator.AuthenticatorViewSet", PatchedAuthenticatorViewSet):
        yield PatchedAuthenticatorViewSet


@mock.patch("test_app.urls.urlpatterns", urlpatterns)
class TestOAuth2PermissionsCheck:
    def test_get_api_view_functions(self):
        expected_results = set([views.UserViewSet, views.TeamViewSet, views.OrganizationViewSet, AuthenticatorViewSet, SpectacularSwaggerView])
        result = set(get_api_view_functions(urlpatterns))
        # Confirm mock works
        assert views.TestAppViewSet not in result

        # Roundabout way of asserting that the result equals the expected results,
        # but tracebacks will show missing results
        assert expected_results.intersection(result).difference(expected_results) == set(), "Missing results from get_api_view_functions"

    # Test the check by calling the check
    def test_check_function(
        self, inverted_permissions_view_class: Type[APIView], nested_permissions_view_class: Type[APIView], missing_permissions_view_class: Type[APIView]
    ):
        expected_messages = [
            Debug(
                "Found OAuth2ScopePermission permission_class",
                id="ansible_base.oauth2_provider.D02",
                obj=nested_permissions_view_class,
            ),
            Debug(
                "Found OAuth2ScopePermission permission_class",
                id="ansible_base.oauth2_provider.D02",
                obj=views.TeamViewSet,
            ),
            Warning(
                "~ (not) operand used on OAuth2ScopePermission, probably a bad idea.",
                id="ansible_base.oauth2_provider.W001",
                obj=inverted_permissions_view_class,
            ),
            Error(
                "View class has no valid usage of OAuth2ScopePermission",
                id="ansible_base.oauth2_provider.E002",
                obj=missing_permissions_view_class,
            ),
            Debug(
                "View class in the ignore list. Ignoring.",
                id="ansible_base.oauth2_provider.D03",
                obj=SpectacularSwaggerView,
            ),
            Debug(
                "View object is fully permissive, OAuth2ScopePermission is not required",
                obj=UIAuth,
                id="ansible_base.oauth2_provider.D04",
            ),
        ]
        # Call check function
        messages = oauth2_permission_scope_check(None)
        # Verify messages
        for message in expected_messages:
            assert message in messages, "Missing message in check results"

    # Test the check by running the management command
    # I Cannot figure out how to mock the check to assert it is called, so this should suffice.
    @pytest.mark.parametrize(
        "call_command_args",
        (
            ["--deploy", "--tag", "oauth2_permissions"],
            ["--deploy", "--tag", "oauth2_permissions", "test_app"],
        ),
    )
    # Need to mock the helper function, since patch cannot find the registered check function itself
    @mock.patch("ansible_base.oauth2_provider.checks.permisssions_check.view_in_app_configs", spec=view_in_app_configs)
    def test_call_check(self, mocked_helper_function: mock.Mock, call_command_args):
        try:
            call_command("check", *call_command_args)
        except SystemCheckError:
            # Should fail with this error with the patched urlconf
            pass
        finally:
            # Assert that view_in_app_config helper called, which would mean the check was most likely called
            mocked_helper_function.assert_called()
