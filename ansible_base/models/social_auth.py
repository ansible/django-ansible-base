from django.contrib.auth import get_user_model
from django.db import models
from social_django.models import AbstractUserSocialAuth

from ansible_base.models import Authenticator

USER_MODEL = get_user_model()


class AuthenticatorUser(AbstractUserSocialAuth):
    """
    This appends extra information on the local user model that includes extra data returned by
    the authenticators and links the user to the authenticator that they used to login.
    """

    provider = models.ForeignKey(Authenticator, to_field='slug', on_delete=models.PROTECT, related_name="authenticator_user")
    user = models.ForeignKey(USER_MODEL, related_name="authenticator_user", on_delete=models.CASCADE)
    # TODO: set self.authenticated based on the provider that is passed to this method.
    # the provider should be the name of the Authenticator model instance
    claims = models.JSONField(default=dict, null=False)
    last_login_map_results = models.JSONField(default=list, null=False)
    # This field tracks if a user passed or failed an allow map
    access_allowed = models.BooleanField(default=None, null=True)

    @classmethod
    def create_social_auth(cls, user, uid, slug):
        provider = Authenticator.objects.get(slug=slug)
        return super().create_social_auth(user, uid, provider)

    class Meta:
        """Meta data"""

        app_label = "ansible_base"
        unique_together = ("provider", "uid")
