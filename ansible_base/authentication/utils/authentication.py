import logging
from typing import Optional, Tuple

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext as _
from social_core.exceptions import AuthException
from social_core.pipeline.user import get_username

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.social_auth import AuthenticatorStorage, AuthenticatorStrategy

logger = logging.getLogger('ansible_base.authentication.utils.authentication')


class FakeBackend:
    def setting(self, *args, **kwargs):
        return ["username", "email"]


def get_local_username(user_details: dict) -> str:
    """
    Converts the username provided by the backend to one that doesn't conflict with users
    from other auth backends.
    """
    username = get_username(strategy=AuthenticatorStrategy(AuthenticatorStorage()), details=user_details, backend=FakeBackend())

    return username['username']


def determine_username_from_uid_social(**kwargs: dict) -> dict:
    uid = kwargs.get('details', {}).get('username', None)
    if not uid:
        raise AuthException(_('Unable to get associated username from: %(details)s') % {'details': kwargs.get("details", None)})

    authenticator = kwargs.get('backend')
    if not authenticator:
        raise AuthException(_('Unable to get backend from kwargs'))

    return {"username": determine_username_from_uid(uid, authenticator)}


def determine_username_from_uid(uid: str = None, authenticator: Authenticator = None) -> str:
    """
    Determine what the username for the User object will be from the given uid and authenticator
    This will take uid like "bella" and search for an AuthenticatorUser and return:
        bella - if there is no bella user in AuthenticatorUser
        bella<hash> - if there is already a bella user in AuthenticatorUser but its not from the given authenticator
        <User.username> - If there is already a user associated with bella for this authenticator (could be bella or bella<hash> or even something else)
    """
    # If we have an AuthenticatorUser with the exact uid and provider than we have a match
    exact_match = AuthenticatorUser.objects.filter(uid=uid, provider=authenticator)
    if exact_match.count() == 1:
        new_username = exact_match[0].user.username
        logger.info(f"Authenticator {authenticator.name} already authenticated {uid} as {new_username}")
        return new_username

    # We didn't get an exact match. If any other provider is using this uid our id will be uid<hash>
    if AuthenticatorUser.objects.filter(uid=uid).count() != 0:
        # Some other provider is providing this username so we need to create our own username
        new_username = get_local_username({'username': uid})
        logger.info(
            f'Authenticator {authenticator.name} wants to authenticate {uid} but that'
            f'username is already in use by another authenticator,'
            f' the user from this authenticator will be {new_username}'
        )
        return new_username

    # We didn't have an exact match but no other provider is servicing this uid so lets return that for usage
    logger.info(f"Authenticator {authenticator.name} is is able to authenticate user {uid} as {uid}")
    return uid


def get_or_create_authenticator_user(
    username: str, authenticator: Authenticator, user_details: dict = dict, extra_data: dict = dict
) -> Tuple[Optional[AbstractUser], Optional[AuthenticatorUser], Optional[bool]]:
    """
    Create the user object in the database along with it's associated AuthenticatorUser class.
    In some cases, the user may already be created in the database.
    This assumes that the given user_name has already been resolved using the determine_username_from_uid but will do a quick double check

    This should be called any non-social auth plugins.

    Inputs
    username: The username we are going to be created
    user_details: Any details about the user from the source (first name, last name, email, etc)
    authenticator: The authenticator authenticating the user
    extra_data: Any additional information about the user provided by the source.
                For example, LDAP might return sn, location, phone_number, etc
    """

    created = None
    try:
        # First see if we have an auth user and if so update it
        auth_user = AuthenticatorUser.objects.get(uid=username, provider=authenticator)
        auth_user.extra_data = extra_data
        auth_user.save()
        created = False
    except AuthenticatorUser.DoesNotExist:
        # Ensure that this username is not already tired to another authenticator
        auth_user = AuthenticatorUser.objects.filter(uid=username).first()
        if auth_user is not None:
            logger.error(
                f'Authenticator {authenticator.name} attempted to create an AuthenticatorUser for {username}'
                f' but that id is already tied to authenticator {auth_user.provider.name}'
            )
            return None, None, None

    # ensure the authenticator isn't trying to pass along a cheeky is_superuser in user_details
    details = {k: user_details.get(k, "") for k in ["first_name", "last_name", "email"]}
    # Create or get our user object
    local_user, user_created = get_user_model().objects.get_or_create(username=username, defaults=details)
    if user_created:
        logger.info(f"Authenticator {authenticator.name} created User {username}")

    if created is None:
        # Create or get the user object. The get shouldn't happen but just incase something snuck in on us
        auth_user, created = AuthenticatorUser.objects.get_or_create(
            user=local_user,
            uid=username,
            provider=authenticator,
            defaults={'extra_data': extra_data},
        )
        if created:
            extra = ''
            if not user_created:
                extra = ' attaching to existing user'
            logger.debug(f"Authenticator {authenticator.name} created AuthenticatorUser for {username}{extra}")

    return local_user, auth_user, created
