import inspect
import logging
import re
from collections import OrderedDict
from typing import Any

import ldap
from django.utils.translation import gettext_lazy as _
from django_auth_ldap import config
from django_auth_ldap.backend import LDAPBackend
from django_auth_ldap.backend import LDAPSettings as BaseLDAPSettings
from rest_framework.serializers import ValidationError

from ansible_base.authentication.common import check_user_attribute_map, get_or_create_authenticator_user, update_user_claims
from ansible_base.authenticator_plugins.base import AbstractAuthenticatorPlugin, Authenticator
from ansible_base.utils.encryption import ENCRYPTED_STRING
from ansible_base.utils.validation import VALID_STRING, validate_url_list

logger = logging.getLogger('ansible_base.authenticator_plugins.ldap')


user_search_string = '%(user)s'


class LDAPSettings(BaseLDAPSettings):
    # We add group type params to our list of valid settings
    defaults = dict(list(BaseLDAPSettings.defaults.items()) + list({'GROUP_TYPE_PARAMS': {}}.items()))

    def __init__(self, prefix: str = 'AUTH_LDAP_', defaults: dict = {}):
        # This init method double checks the passed defaults while initializing a settings objects
        super(LDAPSettings, self).__init__(prefix, defaults)

        self.errors = {}
        # We track these separate because there may be cases where we have errors but it would still yield a valid configuration
        self.configuration_valid = False

        # Check BindDN
        self.validate_ldap_dn(defaults.get('BIND_DN', None), error_entry_label='BIND_DN', with_user=False, required=False)

        if 'BIND_PASSWORD' in defaults and type(defaults['BIND_PASSWORD']) is not str:
            self.set_error('BIND_PASSWORD', VALID_STRING, True)

        # Ensure all options specified in CONNECTION_OPTIONS are valid options
        # Connection options need to be set as {"integer": "value"} but our configuration has {"friendly_name": "value"} so we need to convert them
        self.validate_connection_options(defaults.get('CONNECTION_OPTIONS', None))

        # Ensure GROUP_TYPE is a valid option and that GROUP_TYPE_PARAMS matches it
        self.validate_group_type(defaults.get('GROUP_TYPE', None), defaults.get('GROUP_TYPE_PARAMS', None))

        # Validate USER_SEARCH is a valid search (list of 3, with valid information)
        # Ensure GROUP_SEARCH is valid (list of 3, with valid information)
        for field, search_must_have_user in [('GROUP_SEARCH', False), ('USER_SEARCH', True)]:
            self.validate_ldap_search_field(field, defaults.get(field, None), search_must_have_user)

        # Ensure SERVER_URI is valid
        if 'SERVER_URI' in defaults:
            valid_schemes = ['ldap', 'ldaps']
            try:
                validate_url_list(defaults['SERVER_URI'], schemes=valid_schemes, allow_plain_hostname=True)
            except ValidationError as e:
                self.set_error(
                    'SERVER_URI',
                    f"SERVER_URI must contain only valid urls with schemes {', '.join(valid_schemes)}, the following are invalid: {e.args[0]}",
                    True,
                )
            # SERVER_URI needs to be a comma delineated string
            setattr(self, 'SERVER_URI', ', '.join(defaults['SERVER_URI']))
        else:
            self.set_error('SERVER_URI', 'Must be a list of valid LDAP URLs', True)

        # Make sure START_TLS is a valid boolean
        if 'START_TLS' in defaults and type(defaults['START_TLS']) is not bool:
            self.set_error('START_TLS', 'Must be a boolean value', True)

        # Make sure USER_DN_TEMPLATE is a valid template
        self.validate_ldap_dn(defaults.get('USER_DN_TEMPLATE', None), error_entry_label='USER_DN_TEMPLATE', with_user=True, required=True)

        if 'USER_ATTR_MAP' in defaults:
            for key, value in check_user_attribute_map(defaults['USER_ATTR_MAP']).items():
                self.set_error(key, value, True)
        else:
            self.configuration_valid = False

        # Make sure no other parameters are set unless they are valid LDAP settings
        for option in defaults.keys():
            if option not in LDAPSettings.defaults:
                self.set_error(option, 'Is not a valid setting for an LDAP authenticator', False)

    def set_error(self, option_name: str, message: str, fail_configuration: bool) -> None:
        logger.debug(f"{option_name} {message}")
        self.errors[option_name] = message
        if fail_configuration:
            self.configuration_valid = False

    def validate_connection_options(self, connection_options: Any) -> None:
        if not connection_options:
            return

        if type(connection_options) is not dict:
            self.set_error('CONNECTION_OPTIONS', 'Must be a dict of options', True)
            return

        valid_options = dict([(v, k) for k, v in ldap.OPT_NAMES_DICT.items()])
        internal_data = {}
        for key in connection_options:
            if key not in valid_options:
                self.set_error(f'CONNECTION_OPTIONS.{key}', 'Not a valid connection option', True)
            else:
                internal_data[valid_options[key]] = connection_options[key]

        # If a DB-backed setting is specified that wipes out the
        # OPT_NETWORK_TIMEOUT, fall back to a sane default
        if ldap.OPT_NETWORK_TIMEOUT not in internal_data:
            internal_data[ldap.OPT_NETWORK_TIMEOUT] = 30

        # when specifying `.set_option()` calls for TLS in python-ldap, the
        # *order* in which you invoke them *matters*, particularly in Python3,
        # where dictionary insertion order is persisted
        #
        # specifically, it is *critical* that `ldap.OPT_X_TLS_NEWCTX` be set *last*
        # this manual sorting puts `OPT_X_TLS_NEWCTX` *after* other TLS-related
        # options
        #
        # see: https://github.com/python-ldap/python-ldap/issues/55
        newctx_option = internal_data.pop(ldap.OPT_X_TLS_NEWCTX, None)
        internal_data = OrderedDict(internal_data)
        if newctx_option is not None:
            internal_data[ldap.OPT_X_TLS_NEWCTX] = newctx_option

        setattr(self, 'CONNECTION_OPTIONS', internal_data)

    def validate_group_type(self, group_type_class_name: Any, group_type_params: Any) -> None:
        if not group_type_class_name:
            self.set_error('GROUP_TYPE', 'Must be present', True)
            return

        if type(group_type_class_name) is not str:
            self.set_error('GROUP_TYPE', 'Must be string', True)
            return

        group_type_class = getattr(config, group_type_class_name, None)
        if not group_type_class:
            self.set_error('GROUP_TYPE', 'Specified group type is invalid', True)
            return

        if not isinstance(group_type_params, dict):
            self.set_error('GROUP_TYPE_PARAMS', "Must be a dict object", True)
            return

        class_args = inspect.getfullargspec(group_type_class.__init__).args[1:]
        invalid_keys = set(group_type_params) - set(class_args)
        missing_keys = set(class_args) - set(group_type_params)
        if invalid_keys:
            invalid_keys = sorted(list(invalid_keys))
            for key in invalid_keys:
                self.set_error(f'GROUP_TYPE_PARAMS.{key}', "Invalid option for specified GROUP_TYPE", True)

        if missing_keys:
            missing_keys = sorted(list(missing_keys))
            for key in missing_keys:
                self.set_error(f'GROUP_TYPE_PARAMS.{key}', "Missing required field for GROUP_TYPE", True)

        if not missing_keys and not invalid_keys:
            # Group type needs to be an object instead of a String so instantiate it
            setattr(self, 'GROUP_TYPE', group_type_class(**group_type_params))

    def validate_ldap_search_field(self, search_field: str, data: Any, search_must_have_user: bool) -> None:
        LIST_MESSAGE = 'Must be an array of 3 items: search DN, search scope and a filter'

        if not data:
            setattr(self, search_field, None)
            return

        if type(data) is not list:
            self.set_error(search_field, LIST_MESSAGE, True)
            return

        if len(data) != 3:
            self.set_error(search_field, LIST_MESSAGE, True)
            return

        config_good = True
        if not self.validate_ldap_dn(data[0], error_entry_label=f'{search_field}.0', with_user=False, required=True):
            config_good = False

        if type(data[1]) is not str or not data[1].startswith('SCOPE_') or not getattr(ldap, data[1], None):
            self.set_error(f'{search_field}.1', 'Must be a string representing an LDAP scope object', False)
            config_good = False

        if not self.validate_ldap_filter(data[2], f'{search_field}.2', with_user=search_must_have_user):
            config_good = False

        # If any of the above steps failed then make configuration_valid false
        self.configuration_valid = config_good or self.configuration_valid

        if config_good:
            try:
                # Search fields should be LDAPSearch objects, so we need to convert them from [] to these objects
                search_object = config.LDAPSearch(data[0], getattr(ldap, data[1]), data[2])
                setattr(self, search_field, search_object)
            except Exception as e:
                self.set_error(search_field, f'Failed to instantiate LDAPSearch object: {e}', True)

    def validate_ldap_filter(self, value: Any, error_entry_label: str, with_user: bool = False) -> bool:
        # True = valid filter
        # False = invalid filter
        if type(value) is not str:
            self.set_error(error_entry_label, VALID_STRING, False)
            return False

        value = value.strip()

        dn_value = value
        if with_user:
            if user_search_string not in value:
                self.set_error(error_entry_label, _('DN must include "{}" placeholder for username: {}').format(user_search_string, value), False)
                return False
            dn_value = value.replace(user_search_string, 'USER')

        if re.match(r'^\([A-Za-z0-9-]+?=[^()]+?\)$', dn_value):
            return True
        elif re.match(r'^\([&|!]\(.*?\)\)$', dn_value):
            for sub_filter in dn_value[3:-2].split(')('):
                # We only need to check with_user at the top of the recursion stack
                sub_filter_valid = self.validate_ldap_filter(f'({sub_filter})', error_entry_label, with_user=False)
                if not sub_filter_valid:
                    return False
            return True
        self.set_error(error_entry_label, _('Invalid filter: %s') % value, False)
        return False

    def validate_ldap_dn(self, value: Any, error_entry_label: str, with_user: bool = False, required: bool = True) -> bool:
        # True is a valid DN
        # False means the DN is invalid

        if not value and not required:
            return True

        if type(value) is not str:
            self.set_error(error_entry_label, VALID_STRING, True)
            return False

        dn_value = value
        if with_user:
            if user_search_string not in value:
                self.set_error(error_entry_label, _('DN must include "{}" placeholder for username: {}').format(user_search_string, value), True)
                return False

            dn_value = value.replace(user_search_string, 'USER')

        try:
            ldap.dn.str2dn(dn_value.encode('utf-8'))
            return True
        except ldap.DECODING_ERROR:
            self.set_error(error_entry_label, _('Invalid DN: %s') % value, True)
            return False


class AuthenticatorPlugin(LDAPBackend, AbstractAuthenticatorPlugin):
    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database_instance = database_instance
        if database_instance:
            self.settings = LDAPSettings(defaults=database_instance.configuration)
        self.configuration_encrypted_fields = ['BIND_PASSWORD']
        self.type = 'LDAP'
        self.set_logger(logger)
        self.category = "password"

    def authenticate(self, request, username=None, password=None, **kwargs) -> (object, dict, list):
        if not username or not password:
            return
        users_groups = []

        if not self.database_instance:
            logger.error("AuthenticatorPlugin was missing an authenticator")
            return None

        if not self.database_instance.enabled:
            logger.info(f"LDAP authenticator {self.database_instance.name} is disabled, skipping")
            return None

        # We don't have to check if settings is None because it can never happen, the parent object will always return something

        if not self.settings.configuration_valid:
            logger.error(f"LDAP authenticator {self.database_instance.name} can not be used due to configuration errors.")
            return None

        if self.settings.START_TLS and ldap.OPT_X_TLS_REQUIRE_CERT in self.settings.CONNECTION_OPTIONS:
            # with python-ldap, if you want to set connection-specific TLS
            # parameters, you must also specify OPT_X_TLS_NEWCTX = 0
            # see: https://stackoverflow.com/a/29722445
            # see: https://stackoverflow.com/a/38136255
            self.settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] = 0

        try:
            user_from_ldap = super().authenticate(request, username, password)

            if user_from_ldap is not None and user_from_ldap.ldap_user:
                users_groups = list(user_from_ldap.ldap_user._get_groups().get_group_dns())

                # If we have an LDAP user and that user we found has an user_from_ldap internal object and that object has a bound connection
                # Then we can try and force an unbind to close the sticky connection
                if user_from_ldap.ldap_user._connection_bound:
                    logger.debug(f"Forcing LDAP connection to close for {self.database_instance.name}")
                    try:
                        user_from_ldap.ldap_user._connection.unbind_s()
                        user_from_ldap.ldap_user._connection_bound = False
                    except Exception:
                        logger.exception(
                            f"Got unexpected LDAP exception when forcing LDAP disconnect for user {user_from_ldap.username}, login will still proceed"
                        )

            self.process_login_messages(user_from_ldap, username)

            return update_user_claims(user_from_ldap, self.database_instance, users_groups)
        except Exception:
            logger.exception(f"Encountered an error authenticating to LDAP {self.database_instance.name}")
            return None

    def process_login_messages(self, ldap_user, username: str) -> None:
        if ldap_user is None:
            logger.info(f"User {username} could not be authenticated by LDAP {self.database_instance.name}")

            # If our login failed and we have REQUIRE or DENY group we can't tell that the user is in that but we want inform the admin via a log as a hint
            if self.settings.REQUIRE_GROUP and self.settings.DENY_GROUP:
                logger.info("Hint: is user missing required group or in deny group?")
            elif self.settings.REQUIRE_GROUP:
                logger.info("Hint: is user missing required group?")
            elif self.settings.DENY_GROUP:
                logger.info("Hint: is user in deny group?")
        else:
            logger.info(f"User {username} authenticated by LDAP {self.database_instance.name}")

    def validate_configuration(self, data: dict, instance: object) -> None:
        # If there are any encrypted keys we don't want to use ENCRYPTED_STRING if they were not updated
        for key in self.configuration_encrypted_fields:
            if key in data and data[key] == ENCRYPTED_STRING:
                data[key] = instance.configuration.get(key, None)

        settings = LDAPSettings(defaults=data)

        if settings.errors:
            raise ValidationError({"configuration": settings.errors})

        # Raise some warnings if specific fields were used
        # TODO: Figure out how to display these warnings on a successful save
        for field in ['USER_FLAGS_BY_GROUP', 'DENY_GROUP', 'REQUIRE_GROUP']:
            if field in data:
                self.warnings[field] = "It would be better to use the authenticator field instead of setting this field in the LDAP adapter"

    def update_settings(self, database_authenticator: Authenticator) -> None:
        self.settings = LDAPSettings(defaults=database_authenticator.configuration)

    def get_or_build_user(self, username, ldap_user):
        """
        This gets called by _LDAPUser to create the user in the database.
        """
        authenticator_user, created = get_or_create_authenticator_user(
            user_id=username,
            user_details={
                "username": username,
            },
            authenticator=self.database_instance,
            extra_data=ldap_user.attrs.data,
        )

        return authenticator_user.user, created
