from django.conf import settings
from django.db import models
from social_django.models import AbstractUserSocialAuth

from ansible_base.authentication.models import Authenticator


class AuthenticatorUser(AbstractUserSocialAuth):
    """
    This appends extra information on the local user model that includes extra data returned by
    the authenticators and links the user to the authenticator that they used to login.
    """

    provider = models.ForeignKey(Authenticator, to_field='slug', on_delete=models.PROTECT, related_name="authenticator_providers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="authenticator_users", on_delete=models.CASCADE)
    # TODO: set self.authenticated based on the provider that is passed to this method.
    # the provider should be the name of the Authenticator model instance
    claims = models.JSONField(default=dict, null=False, blank=True)
    last_login_map_results = models.JSONField(default=list, null=False, blank=True)
    # This field tracks if a user passed or failed an allow map
    access_allowed = models.BooleanField(default=None, null=True)

    @classmethod
    def create_social_auth(cls, user, uid, slug):
        provider = Authenticator.objects.get(slug=slug)
        return super().create_social_auth(user, uid, provider)

    class Meta:
        """Meta data"""

        unique_together = ("provider", "uid")
