import logging

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission

logger = logging.getLogger('ansible_base.oauth2_provider.views.permissions')


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
        logger.error(f"Checking object permissions for {request.user}")
        if request.method in SAFE_METHODS and getattr(request.user, 'is_system_auditor', False):
            logger.error("Is system auditor and safe method")
            return True
        if request.user.is_superuser:
            logger.error("Is super user")
            return True
        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            logger.error(f"RBAC INSTALLED {obj.application}")
            if obj.application:
                logger.error(obj.application.organization.access_qs(request.user, "change").exists())
            if obj.application and obj.application.organization.access_qs(request.user, "change").exists():
                logger.error("obj check worked")
                return True
        logger.error(f"Defaulting to am I the user {request.user} {obj.user}")
        logger.error(f"settings.INSTALLED_APPS: {settings.INSTALLED_APPS}")
        return request.user == obj.user
