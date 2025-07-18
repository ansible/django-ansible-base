from typing import Any, Optional

from django.contrib.auth.models import AbstractUser

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.models import is_system_user


# This helper centralizes the logic for handling and cleaning the email input.
def normalize_and_get_email(email: Any) -> Optional[str]:
    """Handles list or string email input, validates type, and normalizes it."""
    if not email:  # Covers None, empty string, or empty list
        return None

    if isinstance(email, list):
        first_email = email[0]
        if not isinstance(first_email, str) or not first_email.strip():
            return None
        return first_email.strip().lower()

    if isinstance(email, str):
        return email.strip().lower()

    # For any other type (int, dict, etc.), treat as empty
    return None


def can_user_change_password(user: Optional[AbstractUser]) -> bool:
    """
    See if the given user is allowed to change their password.
    True if they are authenticated from the `local` authenticator
    False otherwise.
    The system user can never change their password
    """
    if user is None or is_system_user(user):
        # If we didn't actually get a user we can't say they can change their password
        # Or if we are the system user, we can not change our password ever
        return False

    auth_users = AuthenticatorUser.objects.filter(user=user)
    if auth_users.count() == 0:
        # If the user has no associations we can set a password for them so they can login through the local authenticator
        return True

    for auth_user in auth_users:
        try:
            plugin = get_authenticator_plugin(auth_user.provider.type)
            if plugin.type == 'local':
                return True
        except ImportError:
            pass

    return False
