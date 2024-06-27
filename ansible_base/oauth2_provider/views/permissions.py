import oauth2_provider.models as oauth2_models
from django.conf import settings
from oauth2_provider.contrib.rest_framework import TokenHasReadWriteScope
from rest_framework.permissions import SAFE_METHODS, BasePermission


class OAuth2TokenPermission(BasePermission):
    # An app token is a token that has an application attached to it
    # A personal access token (PAT) is a token with no application attached to it
    # With that in mind:
    # - An app token can be read, changed, or deleted if:
    #   - I am the superuser
    #   - I am the admin of the organization of the application of the token
    #   - I am the user of the token
    # - An app token can be created if:
    #   - I have read access to the application (currently this means: I am the superuser)
    # - A PAT can be read, changed, or deleted if:
    #   - I am the superuser
    #   - I am the user of the token
    # - A PAT can be created if:
    #   - I am a user

    def has_permission(self, request, view):
        # Handle PAT and app token creation separately
        if request.method == 'POST':
            if request.data.get('application'):
                # TODO: Change this once ansible/django-ansible-base#424 is fixed
                return request.user.is_superuser
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and getattr(request.user, 'is_platform_auditor', False):
            return True
        if request.user.is_superuser:
            return True
        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            if obj.application and obj.application.organization.access_qs(request.user, "change").exists():
                return True
        return request.user == obj.user


class OAuth2ScopePermission(BasePermission):
    """
    A DRF Permission class to be used by apps that functions in the following way:

    - If an OAuth 2 token is used to authenticate, then its scope must contain the required scope
      (i.e. read cannot use "unsafe" methods)
    - Otherwise, fall back.
    """

    def has_permission(self, request, view):
        if request.auth and isinstance(request.auth, oauth2_models.AbstractAccessToken):
            scopes = request.auth.scope.split()
            if 'write' in scopes and 'read' not in scopes:
                request.auth.scope += ' read'  # write implies read
            token_permission = TokenHasReadWriteScope()
            return token_permission.has_permission(request, view)
        return True
