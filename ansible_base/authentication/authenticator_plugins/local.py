import logging
from urllib.parse import urljoin

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from requests.auth import HTTPBasicAuth

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.authentication import determine_username_from_uid, get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')


# TODO: Change the validator to not allow it to be deleted or a second one added

UserModel = get_user_model()


class LocalConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"

    def validate(self, data):
        if data != {}:
            raise ValidationError(_({"configuration": "Can only be {} for local authenticators"}))
        return data


class AuthenticatorPlugin(ModelBackend, AbstractAuthenticatorPlugin):
    configuration_class = LocalConfiguration
    logger = logger
    type = "local"
    category = "password"

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        if not self.database_instance:
            return None

        if not self.database_instance.enabled:
            logger.info(f"Local authenticator {self.database_instance.name} is disabled, skipping")
            return None

        # Determine the user name for this authenticator, we have to call this so that we can "attach" to a pre-created user
        new_username = determine_username_from_uid(username, self.database_instance)
        # However we can't really accept a different username because we are the local authenticator imagine if:
        #    User "a" is from another authenticator and has an AuthenticatorUser
        #    User "a" tried to login from local authenticator
        #    The above function will return a username of "a<hash>"
        #    We then try to do local authentication with the database from a different username that will not exist in the database, so it would never work
        if new_username != username:
            return None

        user = super().authenticate(request, username, password, **kwargs)
        controller_login_results = None
        if (
            not user
            and request
            and request.path.startswith('/api/gateway/v1/login/')
            and (controller_login_results := self._can_authenticate_from_controller(username, password))
        ):
            logger.warning("User has been validated by controller, updating gateway user.")
            self.update_gateway_user(username, password)
            user = super().authenticate(request, username, password, **kwargs)
        elif not user:
            logger.info(
                "Fallback authentication condition not met: "
                f"username={username}, "
                f"request={'set' if request else 'None'}, "
                f"login_path={'True' if request and request.path.startswith('/api/gateway/v1/login/') else 'False'}, "
                f"controller_login_results={controller_login_results}"
            )

        # This auth class doesn't create any new local users, but we still need to make sure
        # it has an AuthenticatorUser associated with it.
        if user:
            get_or_create_authenticator_user(
                username,
                authenticator=self.database_instance,
                user_details={},
                extra_data={
                    "username": username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            )
        return update_user_claims(user, self.database_instance, [])

    def _can_authenticate_from_controller(self, username, password):
        """
        Check if a user exists in the AuthenticatorUser table with the local authenticator provider.
        If the user is valid, update the gateway users credentials with the controller credentials.
        """
        try:
            UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            logger.warning(f"User '{username}' does not exist in the database.")
            return False

        if controller_user := self._get_controller_user(username, password):
            # Validate controller_user has a ldap_dn field, if it is not None, then the user is a local user
            ldap_dn = controller_user.get("ldap_dn")
            if ldap_dn is None or ldap_dn != "":
                logger.warning(f"User '{username}' is an ldap user and can not be authenticated.")
                return False
            if controller_user.get('password', None) != "$encrypted$":
                logger.warning(f"User '{username}' is an enterprise user and can not be authenticated.")
                return False
            return True
        else:
            return False

    def _get_controller_user(self, username: str, password: str):
        """
        Get the user from the controller by making a request to the controller API /me/ endpoint.
        If the user is not found, return None.
        If the user is found, return the user.
        """

        controller_base_domain = get_setting('gateway_proxy_url')
        if not controller_base_domain:
            logger.warning("Controller authentication failed, unable to get controller base domain")
            return None
        controller_url = urljoin(controller_base_domain, "/api/controller/v2/me/")

        timeout = get_setting('GRPC_SERVER_AUTH_SERVICE_TIMEOUT')
        timeout = self._convert_to_seconds(timeout)

        try:
            response = requests.get(controller_url, auth=HTTPBasicAuth(username, password), timeout=int(timeout))
            response.raise_for_status()
            user_data = response.json()

            # Check if count exists and equals 1
            count = user_data.get("count")
            if count != 1:
                logger.warning(f"Unable to authenticate user '{username}' with controller.")
                return None

            # Check if results exists and is a non-empty list
            results = user_data.get("results")
            if not results or not isinstance(results, list) or len(results) == 0:
                logger.info(f"Unable to authenticate user '{username}' with controller. Invalid or empty results.")
                return None
            if not isinstance(results[0], dict):
                logger.warning(f"Unable to authenticate user '{username}' with controller. user was not a dictionary.")
                return False

            return results[0]
        except requests.exceptions.HTTPError as http_err:
            logger.warning(f"HTTP error occurred: {http_err}")
            return None
        except requests.exceptions.ConnectionError as conn_err:
            logger.warning(f"Connection error occurred: {conn_err}")
            return None
        except requests.exceptions.Timeout as timeout_err:
            logger.warning(f"Timeout error occurred: {timeout_err}")
            return None
        except requests.exceptions.RequestException as err:
            logger.warning(f"An unexpected error occurred: {err}")
            return None
        except ValueError as json_err:
            logger.warning(f"JSON decode error occurred: {json_err}")
            return None
        except Exception as err:
            logger.warning(f"An unexpected error occurred: {err}")
            return None

    def update_gateway_user(self, username, password):
        """
        Update the gateway user with the controller credentials and set is_partially_migrated to False.
        """
        user = UserModel._default_manager.get_by_natural_key(username)
        user.set_password(password)
        user.save(update_fields=['password'])
        logger.info(f"Updated user {username} gateway account")

    def _convert_to_seconds(self, s):
        """
        Converts a time string like '15s', '5m', '1h', '2d', '3w' to seconds.
        """
        default = 10
        try:
            unit = s[-1].lower()
            value = int(s[:-1])

            ret_val = 0
            # Check units
            if unit == '-':
                ret_val = default
            elif unit == 's':
                ret_val = value
            elif unit == 'm':
                ret_val = value * 60
            elif unit == 'h':
                ret_val = value * 3600  # 60 * 60
            elif unit == 'd':
                ret_val = value * 86400  # 60 * 60 * 24
            elif unit == 'w':
                ret_val = value * 604800  # 60 * 60 * 24 * 7
            else:
                ret_val = int(s)
            # If less than or equal to 0, return default
            if ret_val <= 0:
                ret_val = default
            return ret_val
        except Exception:
            logger.warning(f"Invalid duration format: '{s}'")
            return default
