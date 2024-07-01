from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


class OAuth2TokenPermission(BasePermission):
    """
    An app token is a token that has an application attached to it
    A personal access token (PAT) is a token with no application attached to it
    With that in mind:
    - An app token can be read, changed, or deleted if:
      - I am the superuser
      - I am the admin of the organization of the application of the token
      - I am the user of the token
    - An app token can be created if:
      - I have read access to the application (currently this means: I am the superuser)
    - A PAT can be read, changed, or deleted if:
      - I am the superuser
      - I am the user of the token
    - A PAT can be created if:
      - I am a user
    """

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
