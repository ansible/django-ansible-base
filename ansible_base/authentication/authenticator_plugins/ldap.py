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
from django_auth_ldap.config import LDAPGroupType
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, Authenticator, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.claims import get_or_create_authenticator_user, update_user_claims
from ansible_base.common.serializers.fields import BooleanField, CharField, ChoiceField, DictField, ListField, URLListField, UserAttrMap
from ansible_base.common.utils.validation import VALID_STRING

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.ldap')


user_search_string = '%(user)s'


def validate_ldap_dn(value: str, with_user: bool = False, required: bool = True) -> bool:
    if not value and not required:
        return

    dn_value = value
    if with_user:
        if user_search_string not in value:
            raise ValidationError(_('DN must include "{}" placeholder for username: {}').format(user_search_string, value))

        dn_value = value.replace(user_search_string, 'USER')

    try:
        ldap.dn.str2dn(dn_value.encode('utf-8'))
    except ldap.DECODING_ERROR:
        raise ValidationError(_('Invalid DN: %s') % value)


class DNField(CharField):
    def __init__(self, **kwargs):
        self.with_user = kwargs.pop('with_user', False)
        super().__init__(**kwargs)

        def validator(value):
            validate_ldap_dn(value, with_user=self.with_user, required=self.required)

        self.validators.append(validator)


class LDAPConnectionOptions(DictField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def validator(value):
            valid_options = dict([(v, k) for k, v in ldap.OPT_NAMES_DICT.items()])
            errors = {}
            for key in value.keys():
                if key not in valid_options:
                    errors[key] = 'Not a valid connection option'
            if errors:
                raise ValidationError(errors)

        self.validators.append(validator)


class LDAPSearchField(ListField):
    def __init__(self, **kwargs):
        self.search_must_have_user = kwargs.pop('search_must_have_user', False)
        super().__init__(**kwargs)

        def validator(value):
            errors = {}

            if len(value) != 3:
                raise ValidationError(_('Must be an array of 3 items: search DN, search scope and a filter'))

            try:
                validate_ldap_dn(value[0], with_user=False, required=True)
            except ValidationError as e:
                errors[0] = e.args[0]

            if type(value[1]) is not str or not value[1].startswith('SCOPE_') or not getattr(ldap, value[1], None):
                errors[1] = _('Must be a string representing an LDAP scope object')

            try:
                validate_ldap_filter(value[2], with_user=self.search_must_have_user)
            except ValidationError as e:
                errors[2] = e.args[0]

            if errors:
                raise ValidationError(errors)

            # We made it all the way here, make sure we can instantiate an LDAPSearch object
            try:
                # Search fields should be LDAPSearch objects, so we need to convert them from [] to these objects
                config.LDAPSearch(value[0], getattr(ldap, value[1]), value[2])
            except Exception as e:
                raise ValidationError(f'Failed to instantiate LDAPSearch object: {e}')

        self.validators.append(validator)


def validate_ldap_filter(value: Any, with_user: bool = False) -> bool:
    if type(value) is not str:
        raise ValidationError(VALID_STRING)

    value = value.strip()

    dn_value = value
    if with_user:
        if user_search_string not in value:
            raise ValidationError(_('DN must include "{}" placeholder for username: {}').format(user_search_string, value))
        dn_value = value.replace(user_search_string, 'USER')

    if re.match(r'^\([A-Za-z0-9-]+?=[^()]+?\)$', dn_value):
        return
    elif re.match(r'^\([&|!]\(.*?\)\)$', dn_value):
        for sub_filter in dn_value[3:-2].split(')('):
            # We only need to check with_user at the top of the recursion stack
            validate_ldap_filter(f'({sub_filter})', with_user=False)
        return
    raise ValidationError(_('Invalid filter: %s') % value)


def get_all_sub_classes(cls):
    # This function can get the names of all subclasses... maybe we want to move this into utils
    # We use it to find all of the parent classes for LDAPGroup
    sub_classes = []
    for sub_cls in cls.__subclasses__():
        sub_classes.append(sub_cls.__name__)
        sub_classes.extend(get_all_sub_classes(sub_cls))
    return sub_classes


class LDAPConfiguration(BaseAuthenticatorConfiguration):
    # We add group type params to our list of valid settings
    defaults = dict(list(BaseLDAPSettings.defaults.items()) + list({'GROUP_TYPE_PARAMS': {}}.items()))

    documentation_url = "https://django-auth-ldap.readthedocs.io/en/latest/"

    SERVER_URI = URLListField(
        help_text=_('A list of URIs to connect to LDAP server, such as "ldap://ldap.example.com:389" ' '(non-SSL) or "ldaps://ldap.example.com:636" (SSL).'),
        allow_null=False,
        required=True,
        schemes=['ldap', 'ldaps'],
        ui_field_label=_('LDAP Server URI'),
    )

    BIND_DN = DNField(
        help_text=_(
            'DN (Distinguished Name) of user to bind for all search queries. This'
            ' is the system user account we will use to login to query LDAP for other'
            ' user information. Refer to the documentation for example syntax.'
        ),
        allow_null=False,
        required=False,
        with_user=False,
        ui_field_label=_('LDAP Bind DN'),
    )
    BIND_PASSWORD = CharField(
        help_text=_("The password used for BIND_DN."),
        allow_null=False,
        required=False,
        ui_field_label=_('LDAP Bind Password'),
    )

    CONNECTION_OPTIONS = LDAPConnectionOptions(
        help_text=_(
            'Additional options to set for the LDAP connection.  LDAP '
            'referrals are disabled by default (to prevent certain LDAP '
            'queries from hanging with AD). Option names should be strings '
            '(e.g. "OPT_REFERRALS"). Refer to '
            'https://www.python-ldap.org/doc/html/ldap.html#options for '
            'possible options and values that can be set.'
        ),
        default={},
        allow_null=False,
        required=False,
        ui_field_label=_('LDAP Connection Options'),
    )

    GROUP_TYPE = ChoiceField(
        help_text=_(
            'The group type may need to be changed based on the type of the '
            'LDAP server.  Values are listed at: '
            'https://django-auth-ldap.readthedocs.io/en/stable/groups.html#types-of-groups'
        ),
        allow_null=False,
        required=True,
        choices=get_all_sub_classes(LDAPGroupType),
        ui_field_label=_('LDAP Group Type'),
    )
    GROUP_TYPE_PARAMS = DictField(
        help_text=_('Key value parameters to send the chosen group type init method.'),
        allow_null=False,
        required=True,
        ui_field_label=_('LDAP Group Type Parameters'),
    )
    GROUP_SEARCH = LDAPSearchField(
        help_text=_(
            'Users are mapped to organizations based on their membership in LDAP'
            ' groups. This setting defines the LDAP search query to find groups. '
            'Unlike the user search, group search does not support LDAPSearchUnion.'
        ),
        allow_null=True,
        required=False,
        search_must_have_user=False,
        ui_field_label=_('LDAP Group Search'),
    )
    START_TLS = BooleanField(
        help_text=_("Whether to enable TLS when the LDAP connection is not using SSL."),
        allow_null=False,
        required=False,
        default=False,
        ui_field_label=_('LDAP Start TLS'),
    )
    USER_DN_TEMPLATE = DNField(
        help_text=_(
            'Alternative to user search, if user DNs are all of the same '
            'format. This approach is more efficient for user lookups than '
            'searching if it is usable in your organizational environment. If '
            'this setting has a value it will be used instead of '
            'AUTH_LDAP_USER_SEARCH.'
        ),
        allow_null=False,
        required=True,
        with_user=True,
        ui_field_label=_('LDAP User DN Template'),
    )
    USER_ATTR_MAP = UserAttrMap(
        help_text=_(
            'Mapping of LDAP user schema to API user attributes. The default'
            ' setting is valid for ActiveDirectory but users with other LDAP'
            ' configurations may need to change the values. Refer to the'
            ' documentation for additional details.'
        ),
        allow_null=False,
        required=True,
        ui_field_label=_('LDAP User Attribute Map'),
    )
    USER_SEARCH = LDAPSearchField(
        help_text=_(
            'LDAP search query to find users.  Any user that matches the given '
            'pattern will be able to login to the service.  The user should also be '
            'mapped into an organization (as defined in the '
            'AUTH_LDAP_ORGANIZATION_MAP setting).  If multiple search queries '
            'need to be supported use of "LDAPUnion" is possible. See '
            'the documentation for details.'
        ),
        allow_null=False,
        required=False,
        search_must_have_user=True,
        ui_field_label=_('LDAP User Search'),
    )

    def validate(self, attrs):
        # Check interdependent fields
        errors = {}

        group_type_class = getattr(config, attrs['GROUP_TYPE'], None)
        if group_type_class:
            group_type_params = attrs['GROUP_TYPE_PARAMS']
            logger.error(f"Validating group type params for {attrs['GROUP_TYPE']}")
            class_args = inspect.getfullargspec(group_type_class.__init__).args[1:]
            invalid_keys = set(group_type_params) - set(class_args)
            missing_keys = set(class_args) - set(group_type_params)
            if invalid_keys:
                invalid_keys = sorted(list(invalid_keys))
                for key in invalid_keys:
                    errors[f'GROUP_TYPE_PARAMS.{key}'] = "Invalid option for specified GROUP_TYPE"

            if missing_keys:
                missing_keys = sorted(list(missing_keys))
                for key in missing_keys:
                    errors[f'GROUP_TYPE_PARAMS.{key}'] = "Missing required field for GROUP_TYPE"

        if errors:
            raise ValidationError(errors)

        # Raise some warnings if specific fields were used
        # TODO: Figure out how to display these warnings on a successful save
        # for field in ['USER_FLAGS_BY_GROUP', 'DENY_GROUP', 'REQUIRE_GROUP']:
        #    if field in data:
        #        self.warnings[field] = "It would be better to use the authenticator field instead of setting this field in the LDAP adapter"

        return super().validate(attrs)


class LDAPSettings(BaseLDAPSettings):
    def __init__(self, prefix: str = 'AUTH_LDAP_', defaults: dict = {}):
        # This init method double checks the passed defaults while initializing a settings objects
        super(LDAPSettings, self).__init__(prefix, defaults)

        # SERVER_URI needs to be a string, not an array
        setattr(self, 'SERVER_URI', ','.join(defaults['SERVER_URI']))

        # Connection options need to be set as {"integer": "value"} but our configuration has {"friendly_name": "value"} so we need to convert them
        connection_options = defaults.get('CONNECTION_OPTIONS', {})
        valid_options = dict([(v, k) for k, v in ldap.OPT_NAMES_DICT.items()])
        internal_data = {}
        for key in connection_options:
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

        # Group type needs to be an object instead of a String so instantiate it
        group_type_class = getattr(config, defaults['GROUP_TYPE'], None)
        setattr(self, 'GROUP_TYPE', group_type_class(**defaults['GROUP_TYPE_PARAMS']))


class AuthenticatorPlugin(LDAPBackend, AbstractAuthenticatorPlugin):
    configuration_class = LDAPConfiguration
    type = 'LDAP'
    category = "password"

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database_instance = database_instance
        if database_instance:
            self.settings = LDAPSettings(defaults=database_instance.configuration)
        self.configuration_encrypted_fields = ['BIND_PASSWORD']
        self.set_logger(logger)

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

        if self.settings.START_TLS and ldap.OPT_X_TLS_REQUIRE_CERT in self.settings.CONNECTION_OPTIONS:
            # with python-ldap, if you want to set connection-specific TLS
            # parameters, you must also specify OPT_X_TLS_NEWCTX = 0
            # see: https://stackoverflow.com/a/29722445
            # see: https://stackoverflow.com/a/38136255
            self.settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] = 0

        # Ensure USER_SEARCH and GROUP_SEARCH are converted into a search object
        for field, search_must_have_user in [('GROUP_SEARCH', False), ('USER_SEARCH', True)]:
            data = getattr(self.settings, field, None)
            if data is None:
                setattr(self.settings, field, None)
            else:
                try:
                    # Search fields should be LDAPSearch objects, so we need to convert them from [] to these objects
                    search_object = config.LDAPSearch(data[0], getattr(ldap, data[1]), data[2])
                    setattr(self.settings, field, search_object)
                except Exception as e:
                    logger.error(f'Failed to instantiate LDAPSearch object: {e}')
                    return None

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
