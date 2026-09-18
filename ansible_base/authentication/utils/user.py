import logging
from typing import Any, Optional

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import validate_email as django_validate_email

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.models import is_system_user

logger = logging.getLogger('ansible_base.authentication.utils.user')


def _is_valid_email(email: str) -> bool:
    """Check if email is valid using Django's built-in email validator."""
    try:
        django_validate_email(email)
        return True
    except ValidationError:
        return False


# This helper centralizes the logic for handling and cleaning the email input.
def normalize_and_get_email(email: Any) -> Optional[str]:
    """Handles list or string email input, validates type, normalizes, and validates format.

    Returns the normalized email if valid, or None if the input is empty, not a string,
    or not a valid email address. Logs a warning when an invalid email is rejected.
    """
    if not email:  # Covers None, empty string, or empty list
        return None

    raw_email = None
    if isinstance(email, list):
        first_email = email[0]
        if not isinstance(first_email, str) or not first_email.strip():
            return None
        raw_email = first_email.strip().lower()
    elif isinstance(email, str):
        raw_email = email.strip().lower()
    else:
        # For any other type (int, dict, etc.), treat as empty
        return None

    if raw_email and not _is_valid_email(raw_email):
        logger.warning(
            "Rejecting invalid email address '%s' from authenticator. "
            "User will be created with an empty email. "
            "Check your authenticator's email attribute mapping.",
            raw_email,
        )
        return None

    return raw_email


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
