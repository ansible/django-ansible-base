from base64 import b64encode
from typing import Any

from django.conf import settings
from django.db import models
from social_django.models import AbstractUserSocialAuth

from ansible_base.authentication.models import Authenticator


def b64_encode_binary_data_in_dict(obj: Any) -> Any:
    if isinstance(obj, list):
        for index in range(0, len(obj)):
            obj[index] = b64_encode_binary_data_in_dict(obj[index])
    elif isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = b64_encode_binary_data_in_dict(key)
    elif isinstance(obj, bytes):
        return b64encode(obj)
    return obj


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

    def save(self, *args, **kwargs):
        # Some authenticators can put binary field in the extra data so we need to be sure to strip that out.
        self.extra_data = b64_encode_binary_data_in_dict(self.extra_data)

        super().save(*args, **kwargs)
