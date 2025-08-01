import importlib
import logging
from typing import Optional, Tuple, Union

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.db.models import Q
from django.utils.translation import gettext as _
from social_core.exceptions import AuthException
from social_core.pipeline.user import get_username

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.social_auth import AuthenticatorStorage, AuthenticatorStrategy
from ansible_base.authentication.utils.user import normalize_and_get_email

logger = logging.getLogger('ansible_base.authentication.utils.authentication')

merge_strategy = "Email fallback"


class FakeBackend:
    def __init__(self):
        self.settings = {}
        fq_function_name = getattr(settings, 'ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION', None)
        if fq_function_name:
            try:
                module_name, _, function_name = fq_function_name.rpartition('.')
                the_function = getattr(importlib.import_module(module_name), function_name)
                self.settings = the_function()
            except Exception as e:
                logger.error(f"FakeBackend: Failed to run {fq_function_name} to get additional settings: {e}")

        self.settings["USER_FIELDS"] = ["username", "email"]

    def setting(self, name, default=None):
        for name in [name, f"SOCIAL_AUTH_{name}"]:
            if name in self.settings:
                return self.settings[name]
        return default


def raise_auth_exception(message: str, backend: Optional[Authenticator] = None):
    raise AuthException(backend, message)


def migrate_from_existing_authenticator(
    uid: str, alt_uid: Optional[str], authenticator: Authenticator, preferred_username: Optional[str] = None
) -> Optional[str]:
    """
    uid: the users uid.
    alt_uid: an optional alternative uid to use for looking up other accounts.
    authenticator: the authenticator that the user is currently authenticating with.
    preferred_username: the username that the authenticator wants to use for the user.

    Returns the username of the django account to user for the authenticated user, or None if no match was found.
    """

    # SAML puts prepends all the UIDs with IdP. Adding this to the search criteria will
    # allow us to find SAML accounts that match the UID.
    uid_filter = [uid, "IdP:" + uid]
    if alt_uid:
        uid_filter.append(alt_uid)

    migrate_users = list(
        AuthenticatorUser.objects.filter(
            uid__in=uid_filter,
            provider__auto_migrate_users_to=authenticator.pk,
        ).order_by("provider__order")
    )

    if len(migrate_users) == 0:
        return

    try:
        main_user = AuthenticatorUser.objects.get(uid=uid, provider=authenticator).user
    except AuthenticatorUser.DoesNotExist:
        main_user = migrate_users[0].user

    for migrate_user in migrate_users:
        provider = migrate_user.provider
        from_authenticator = get_authenticator_class(provider.type)(database_instance=provider)
        old_user = from_authenticator.move_authenticator_user_to(main_user, migrate_user)
        if old_user and not old_user.authenticator_users.exists():
            old_user.delete()
        elif old_user:
            logger.warning(f"{old_user.username} is still managed by other authenticators and cannot be deleted.")

    # Now that we've potentially cleaned up any old user accounts, lets see if we can
    # give the user their preferred_username as their username

    if preferred_username:
        if main_user.username != preferred_username and not get_user_model().objects.filter(username=preferred_username).exists():
            main_user.username = preferred_username
            main_user.save()

    return main_user.username


def get_local_username(user_details: dict) -> str:
    """
    Converts the username provided by the backend to one that doesn't conflict with users
    from other auth backends.
    """
    username = get_username(strategy=AuthenticatorStrategy(AuthenticatorStorage()), details=user_details, backend=FakeBackend())
    return username['username']


def check_system_username(uid: str, authenticator: Optional[Authenticator]) -> None:
    """
    Determine if a username is identical with SYSTEM_USERNAME
    Raise AuthException if system user attempts to login via an external authentication source
    """
    if uid.casefold() == settings.SYSTEM_USERNAME.casefold():
        logger.warning(f'{settings.SYSTEM_USERNAME} cannot log in from an authenticator!')
        raise_auth_exception(_('System user is not allowed to log in from external authentication sources.'), backend=authenticator)


def determine_username_from_uid_social(**kwargs) -> dict:
    # If you are troubleshooting login issues and getting to here ....
    # Make sure that your backend properly implements get_user_details per the base backend
    # See https://github.com/python-social-auth/social-core/blob/master/social_core/backends/base.py#L173
    # The return should be in the format:
    #
    # {
    #     'username': <username if any>,
    #     'email': <user email if any>,
    #     'fullname': <user full name if any>,
    #     'first_name': <user first name if any>,
    #     'last_name': <user last name if any>
    # }
    # If this data structure does not return the username, this method will fail
    authenticator = kwargs.get('backend')
    if not authenticator:
        raise_auth_exception(_('Unable to get backend from kwargs'))
    if authenticator.setting('USERNAME_IS_FULL_EMAIL', False):
        selected_username = kwargs.get('details', {}).get('email', None)
    else:
        selected_username = kwargs.get('details', {}).get('username', None)
    if not selected_username:
        raise_auth_exception(
            _('Unable to get associated username from details, expected entry "username". Full user details: %(details)s')
            % {'details': kwargs.get("details", None)},
            backend=authenticator,
        )

    alt_uid = authenticator.get_alternative_uid(**kwargs)
    email = kwargs.get('details', {}).get('email', None)

    if migrated_username := migrate_from_existing_authenticator(
        uid=kwargs.get("uid"), alt_uid=alt_uid, authenticator=authenticator.database_instance, preferred_username=selected_username
    ):
        username = migrated_username
    else:
        username = determine_username_from_uid(selected_username, email, authenticator.database_instance)

    return {"username": username}


def _handle_no_merge_strategy(uid: str, authenticator: Authenticator) -> str:
    """Handles the merge strategy where users are unique for each authenticator."""
    if AuthenticatorUser.objects.filter(Q(uid=uid) | Q(user__username=uid)).exists():
        # Some other provider is providing this username so we need to create our own username
        new_username = get_local_username({'username': uid})
        logger.warning(f"User {uid} is already associated with an existing user, creating a new user with username {new_username}")
        return new_username
    else:
        # We didn't have an exact match but no other provider is servicing this uid so lets return that for usage
        logger.info(f"Authenticator {authenticator.name} is able to authenticate user {uid} as {uid}")
        return uid


def _handle_email_fallback_strategy(uid: str, email: Union[str, list[str], None], authenticator: Authenticator) -> str:
    """Handles the merge strategy where AAP users are matched by email."""
    ###
    # AUTHENTICATION STRATEGY OVERVIEW
    # For more detailed information, see the following proposal
    # https://handbook.eng.ansible.com/proposals/0082-Handling-Sign-In-Via-Multiple-Authenticators#how
    #
    # The logic below maps to the proposal flowchart, indicated by comments starting with "PROPOSAL FLOW"
    ###
    user_model = get_user_model()
    normalized_email = normalize_and_get_email(email)

    # PROPOSAL FLOW: Authenticator No Email provided
    # If local authenticator, no need to use email fallback strategy
    if not normalized_email or authenticator.type == "ansible_base.authentication.authenticator_plugins.local":
        return _handle_no_merge_strategy(uid, authenticator)  # Logic is identical to the no-merge strategy

    # PROPOSAL FLOW: Authenticator provides email
    existing_user_match = user_model.objects.filter(email__iexact=normalized_email)
    user_count = existing_user_match.count()

    # PROPOSAL FLOW: Are there multiple AAP users with this Email? Yes
    if user_count > 1:
        logger.warning(f"Found more than 1 user matching {uid}/{email}, unable to determine which user to merge with!")
        raise AuthException(f"Found more than 1 user matching {uid}/{email}, unable to determine which user to merge with!")
    # PROPOSAL FLOW: Are there multiple AAP users with this Email? No only 1
    elif user_count == 1:
        return existing_user_match.first().username
    # PROPOSAL FLOW: Does an AAP User with this email exist? No
    else:
        new_username = get_local_username({'username': uid})
        logger.warning(f"User {uid} is already associated with an existing user, creating a new user with username {new_username}")
        return new_username


# def _handle_email_username_fallback_strategy(uid: str, email: Union[str, list[str], None], authenticator: Authenticator) -> str:
#     """Handles the unused 'Email and Username fallback' strategy."""
#     # This code is not used anywhere, but is kept here for reference, in case we later want to enable it.
#     normalized_email = normalize_and_get_email(email)

#     # Note: The original code uses .get(), which will raise an exception if zero or multiple
#     # objects are found, and then tries to call .count() on the result, which will fail.
#     # The logic is preserved here as-is.
#     if not normalized_email:
#         existing_user_match = Authenticator.objects.get(user__username=uid)
#     else:
#         existing_user_match = Authenticator.objects.get(user__email=normalized_email)

#     if existing_user_match.count() == 1:
#         existing_user = existing_user_match[0].user
#         new_username = existing_user.username
#         logger.info(f"Authenticator {authenticator.name} matched {uid}/{email} from provider {existing_user_match[0].provider.name}, combining users")
#         return new_username
#     elif existing_user_match.count() > 1:
#         raise AuthException(f"Found more than 1 user matching {uid}/{email}, unable to determine which user to merge with!")
#     else:
#         # Some other provider is providing this username so we need to create our own username
#         new_username = get_local_username({'username': uid})
#         logger.warning(
#             f"User {uid} is already associated with an existing user, creating a new user with username {new_username}"
#         )
#         return new_username


def determine_username_from_uid(uid: str = None, email: Union[str, list[str], None] = None, authenticator: Authenticator = None) -> str:
    """
    Determine what the username for the User object will be from the given uid and authenticator
    This will take uid like "bella" and search for an AuthenticatorUser and return:
        bella - if there is no bella user in AuthenticatorUser
        bella<hash> - if there is already a bella user in AuthenticatorUser but its not from the given authenticator
        <User.username> - If there is already a user associated with bella for this authenticator (could be bella or bella<hash> or even something else)

    NOTE: This should not be called directly. This will either be called from:
             1. The social auth pipeline
             2. The get_or_create_authenticator_user method below
          With one exception of the local authenticator. This is because we can't allow local authenticator to have maps between a uid of timmy and
          a username of timmy<hash>.  This literally does not make sense for the local authenticator because the DB is its own source of truth.
    """
    try:
        check_system_username(uid, authenticator=authenticator)
    except AuthException as e:
        logger.warning(f"AuthException: {e}")
        raise

    # If we have an AuthenticatorUser with the exact uid and provider than we have a match
    if (exact_match := AuthenticatorUser.objects.filter(uid=uid, provider=authenticator)).exists():
        new_username = exact_match.first().user.username
        logger.info(f"Authenticator {authenticator.name} already authenticated {uid} as {new_username}")
        return new_username

    logger.debug(f"Authentication merge strategy is {merge_strategy}")

    # Dispatch to the correct handler based on the merge strategy
    # if merge_strategy == "": # AAP 2.5 Merge Strategy
    #     return _handle_no_merge_strategy(uid, authenticator)
    if merge_strategy == "Email fallback":  # AAP 2.6 Default Merge Strategy
        return _handle_email_fallback_strategy(uid, email, authenticator)
    # elif merge_strategy == "Email and Username fallback": # In the future, we may want to enable this
    #     return _handle_email_username_fallback_strategy(uid, email, authenticator)
    else:
        raise AuthException(f"Got an invalid merge_strategy {merge_strategy}")


def _validate_username_for_new_user(username: str, authenticator: Authenticator):
    """
    Prevents creating a user if the username is already tied to another authenticator.
    Returns True if the username is available, False otherwise.

    Note: This assumes `merge_strategy` is available in the scope, as in the original code.
    """
    if merge_strategy is None:
        if conflicting_user := AuthenticatorUser.objects.filter(user__username=username).first():
            logger.error(
                f'Authenticator {authenticator.name} attempted to create an AuthenticatorUser for {username}'
                f' but that id is already tied to authenticator {conflicting_user.provider.name}'
            )
            return False  # Validation failed
    return True  # Validation passed


def get_or_create_authenticator_user(
    uid: str, email: str, authenticator: Authenticator, user_details: dict = dict, extra_data: dict = dict
) -> Tuple[Optional[AbstractUser], Optional[AuthenticatorUser], Optional[bool]]:
    """
    Create the user object in the database along with it's associated AuthenticatorUser class.
    In some cases, the user may already be created in the database.
    This should be called any non-social auth plugins.

    Inputs
    uid: The unique id that identifies the user (this comes from the source authenticator, e.g. github or ldap).
    user_details: Any details about the user from the source (first name, last name, email, etc)
    authenticator: The authenticator authenticating the user
    extra_data: Any additional information about the user provided by the source.
                For example, LDAP might return sn, location, phone_number, etc
    """
    try:
        check_system_username(uid, authenticator=authenticator)
    except AuthException as e:
        logger.warning(f"AuthException: {e}")
        raise

    # Step 1: Determine the username, running the migration logic FIRST. This is the key fix.
    if migrated_username := migrate_from_existing_authenticator(uid=uid, alt_uid=None, authenticator=authenticator, preferred_username=uid):
        username = migrated_username
    else:
        username = determine_username_from_uid(uid, email, authenticator)

    # Step 2: Now that the username is finalized, try to find the AuthenticatorUser.
    auth_user = None
    created = None
    try:
        auth_user = AuthenticatorUser.objects.get(uid=uid, provider=authenticator)
        auth_user.extra_data = extra_data
        auth_user.email = email
        auth_user.save()
        created = False
    except AuthenticatorUser.DoesNotExist:
        # If the AuthenticatorUser doesn't exist, validate the username before creating a new one.
        if not _validate_username_for_new_user(username, authenticator):
            return None, None, None

    # Step 3: Get or create the main User model instance.
    details = {k: user_details.get(k, "") for k in ["first_name", "last_name", "email"]}
    local_user, user_created = get_user_model().objects.get_or_create(username=username, defaults=details)
    if user_created:
        logger.info(f"Authenticator {authenticator.name} created User {username}")

    # Step 4: If the AuthenticatorUser was not found in Step 2, create it now.
    if created is None:
        auth_user, created = AuthenticatorUser.objects.get_or_create(
            user=local_user,
            email=email,
            uid=uid,
            provider=authenticator,
            defaults={'extra_data': extra_data},
        )
        if created:
            extra = ' attaching to existing user' if not user_created else ''
            logger.debug(f"Authenticator {authenticator.name} created AuthenticatorUser for {username}{extra}")

    # Ensure the returned user object is the one linked to the auth_user.
    final_user = auth_user.user if auth_user else local_user
    return final_user, auth_user, created
