import logging

from django.http import HttpResponse, HttpResponseNotFound
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.errors import OneLogin_Saml2_Error
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from rest_framework.serializers import ValidationError
from rest_framework.views import View
from social_core.backends.saml import SAMLAuth, SAMLIdentityProvider

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.social_auth import (
    AuthenticatorConfigTestStrategy,
    AuthenticatorStorage,
    AuthenticatorStrategy,
    SocialAuthMixin,
    SocialAuthValidateCallbackMixin,
)
from ansible_base.lib.serializers.fields import CharField, JSONField, ListField, PrivateKey, PublicCert, URLField
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.validation import validate_cert_with_key

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.saml')

idp_string = 'IdP'


class SAMLConfiguration(BaseAuthenticatorConfiguration):
    settings_to_enabled_idps_fields = {
        'IDP_URL': 'url',
        'IDP_X509_CERT': 'x509cert',
        'IDP_ENTITY_ID': 'entity_id',
        'IDP_ATTR_EMAIL': 'attr_email',
        'IDP_GROUPS': 'attr_groups',
        'IDP_ATTR_USERNAME': 'attr_username',
        'IDP_ATTR_LAST_NAME': 'attr_last_name',
        'IDP_ATTR_FIRST_NAME': 'attr_first_name',
        'IDP_ATTR_USER_PERMANENT_ID': 'attr_user_permanent_id',
    }

    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/saml.html"

    SP_ENTITY_ID = CharField(
        allow_null=False,
        max_length=512,
        default="saml_entity",
        help_text=_(
            "The application-defined unique identifier used as the audience of the SAML service provider (SP) configuration. This is usually the URL for the"
            " service."
        ),
        ui_field_label=_('SAML Service Provider Entity ID'),
    )
    SP_PUBLIC_CERT = PublicCert(
        allow_null=False,
        help_text=_("Create a keypair to use as a service provider (SP) and include the certificate content here."),
        ui_field_label=_('SAML Service Provider Public Certificate'),
    )
    SP_PRIVATE_KEY = PrivateKey(
        allow_null=False,
        help_text=_("Create a keypair to use as a service provider (SP) and include the private key content here."),
        ui_field_label=_('SAML Service Provider Private Key'),
    )
    ORG_INFO = JSONField(
        allow_null=False,
        default={"en-US": {"url": "", "name": "", "displayname": ""}},
        help_text=_("Provide the URL, display name, and the name of your app. Refer to the documentation for example syntax."),
        ui_field_label=_('SAML Service Provider Organization Info'),
    )
    TECHNICAL_CONTACT = JSONField(
        allow_null=False,
        default={'givenName': "", 'emailAddress': ""},
        help_text=_("Provide the name and email address of the technical contact for your service provider. Refer to the documentation for example syntax."),
        ui_field_label=_('SAML Service Provider Technical Contact'),
    )
    SUPPORT_CONTACT = JSONField(
        allow_null=False,
        default={'givenName': "", 'emailAddress': ""},
        help_text=_("Provide the name and email address of the support contact for your service provider. Refer to the documentation for example syntax."),
        ui_field_label=_('SAML Service Provider Support Contact'),
    )
    SP_EXTRA = JSONField(
        default={"requestedAuthnContext": False},
        help_text=_("A dict of key value pairs to be passed to the underlying python-saml Service Provider configuration setting."),
        ui_field_label=_('SAML Service Provider extra configuration data'),
    )
    SECURITY_CONFIG = JSONField(
        default={},
        help_text=_(
            "A dict of key value pairs that are passed to the underlying python-saml security setting https://github.com/onelogin/python-saml#settings."
        ),
        ui_field_label=_('SAML Security Config'),
    )
    EXTRA_DATA = ListField(
        default=[],
        help_text=_("A list of tuples that maps IDP attributes to extra_attributes. Each attribute will be a list of values, even if only 1 value."),
        ui_field_label=_('SAML IDP to extra_data attribute mapping'),
    )
    IDP_URL = URLField(
        allow_null=False,
        help_text=_("The URL to redirect the user to for login initiation."),
        ui_field_label=_('IdP Login URL'),
    )
    IDP_X509_CERT = PublicCert(
        allow_null=False,
        help_text=_("The public certificate used for secrets coming from the IdP."),
        ui_field_label=_('IdP Public Cert'),
    )
    IDP_ENTITY_ID = CharField(
        allow_null=False,
        help_text=_("The entity ID returned in the assertion."),
        ui_field_label=_('Entity ID'),
    )
    IDP_GROUPS = CharField(
        allow_null=True,
        required=False,
        help_text=_("The field in the assertion which represents the user's groups."),
        ui_field_label=_('Groups'),
    )
    IDP_ATTR_EMAIL = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the user's email."),
        ui_field_label=_('User Email'),
    )
    IDP_ATTR_USERNAME = CharField(
        help_text=_("The field in the assertion which represents the user's username."),
        ui_field_label=_('Username'),
    )
    IDP_ATTR_LAST_NAME = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the user's last name."),
        ui_field_label=_('User Last Name'),
    )
    IDP_ATTR_FIRST_NAME = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the user's first name."),
        ui_field_label=_('User First Name'),
    )
    IDP_ATTR_USER_PERMANENT_ID = CharField(
        help_text=_("The field in the assertion which represents the user's permanent id."),
        ui_field_label=_('User Permanent ID'),
    )
    CALLBACK_URL = URLField(
        required=False,
        allow_null=True,
        help_text=_(
            "Register the service as a service provider (SP) with each identity provider (IdP) you have configured. "
            "Provide your SP Entity ID and this ACS URL for your application."
        ),
        ui_field_label=_('SAML Assertion Consumer Service (ACS) URL'),
    )

    def validate(self, attrs):
        # attrs is only the data in the configuration field
        errors = {}
        # pull the cert_info out of the existing object (if we have one)
        cert_info = {
            "SP_PRIVATE_KEY": getattr(self.instance, 'configuration', {}).get('SP_PRIVATE_KEY', None),
            "SP_PUBLIC_CERT": getattr(self.instance, 'configuration', {}).get('SP_PUBLIC_CERT', None),
        }

        # Get public cert if provided
        public_cert = attrs.get('SP_PUBLIC_CERT', None)
        if public_cert is not None:
            cert_info['SP_PUBLIC_CERT'] = public_cert

        # Now get the SP_PRIVATE_KEY out of the passed in attrs (if there is any)
        private_key = attrs.get('SP_PRIVATE_KEY', None)
        if private_key and private_key != ENCRYPTED_STRING:
            # We got an input form the attrs so let that override whatever was in the object
            cert_info['SP_PRIVATE_KEY'] = private_key
        # If we didn't get an input or we got ENCRYPTED_STRING but there is an item, we will just use whatever we got from the item

        # If we made it here the cert_info has one of three things:
        #  * None (error state or not passed in on PUT)
        #  * The existing value from the instance
        #  * A new value

        # Now validate that we can load the cert and key and that they match.
        # Technically, we are also doing this on save even if both values came from the existing instance
        # so there is an inefficiency here but it should be trivial
        try:
            validate_cert_with_key(cert_info['SP_PUBLIC_CERT'], cert_info['SP_PRIVATE_KEY'])
        except ValidationError as e:
            errors['SP_PRIVATE_KEY'] = e

        if errors:
            raise ValidationError(errors)

        saml_auth = SAMLAuth(AuthenticatorConfigTestStrategy(AuthenticatorStorage(), additional_settings=attrs))
        saml_auth.redirect_uri = attrs['CALLBACK_URL']
        idp = SAMLIdentityProvider(idp_string, **attrs['ENABLED_IDPS'][idp_string])
        config = saml_auth.generate_saml_config(idp=idp)
        invalid_security_settings = []
        try:
            settings = OneLogin_Saml2_Settings(settings=config)
            settings._security = {}
            settings._add_default_values()
            valid_security_settings = set(settings._security.keys())
            security_settings = set(attrs.get('SECURITY_CONFIG').keys())
            invalid_security_settings = security_settings.difference(valid_security_settings)
        except Exception as e:
            raise ValidationError(_("Failed to load config: %(e)s") % {"e": e})

        if invalid_security_settings:
            raise ValidationError({'SECURITY_CONFIG': _("Invalid keys:) {', '.join(invalid_security_settings)}")})

        response = super().validate(attrs)
        return response

    def to_internal_value(self, data):
        resp = super().to_internal_value(data)
        idp_data = {}
        for field, idp_field in self.settings_to_enabled_idps_fields.items():
            if field in resp:
                idp_data[idp_field] = resp[field]
                del resp[field]
        resp['ENABLED_IDPS'] = {idp_string: idp_data}
        return resp

    def to_representation(self, configuration):
        if 'ENABLED_IDPS' in configuration:
            for config_setting_name in self.settings_to_enabled_idps_fields:
                enabled_idp_field_name = self.settings_to_enabled_idps_fields[config_setting_name]
                if enabled_idp_field_name in configuration['ENABLED_IDPS'][idp_string]:
                    configuration[config_setting_name] = configuration['ENABLED_IDPS'][idp_string][enabled_idp_field_name]
            del configuration['ENABLED_IDPS']
        return configuration


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, SAMLAuth, AbstractAuthenticatorPlugin):
    configuration_class = SAMLConfiguration
    type = "SAML"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SP_PRIVATE_KEY']

    def generate_saml_config(self, idp=None):
        """
        SP Assertion Consumer Service URL (ACS URL) is where the IdP should send the login response (the URL back to the SP)

        tl; dr;
        This is a "super function" to fix setting the ACS URL

        The SP ACS URL is pulled form the config['sp']['assertionConsumerService']['url']
        This defaults to self.redirect_uri which, I believe, is made from inspecting the request.
        This became an issue when doing SSL offloading.
        Ideally, we want this to come from CALLBACK_URL which we expose as the ACS URL.
        This function overrides the default function setting the redirect_uri to our CALLBACK_URL
        """
        self.redirect_uri = self.strategy.get_setting('CALLBACK_URL', self)
        return super().generate_saml_config(idp=idp)

    def get_login_url(self, authenticator):
        url = get_relative_url('social:begin', kwargs={'backend': authenticator.slug})
        return f'{url}?idp={idp_string}'

    def _create_saml_auth(self, idp):
        """
        Get an instance of OneLogin_Saml2_Auth
        Identical to the implementation in SAMLAuth, with the exception
        of forcing https in the request info when SOCIAL_AUTH_REDIRECT_IS_HTTPS == True
        """
        config = self.generate_saml_config(idp)
        request_info = {
            "https": "on" if self.strategy.request_is_secure() else "off",
            "http_host": self.strategy.request_host(),
            "script_name": self.strategy.request_path(),
            "get_data": self.strategy.request_get(),
            "post_data": self.strategy.request_post(),
        }

        if self.strategy.setting("REDIRECT_IS_HTTPS", False, self):
            request_info["https"] = "on"

        return OneLogin_Saml2_Auth(request_info, config)

    def add_related_fields(self, request, authenticator):
        return {"metadata": get_relative_url('authenticator-metadata', kwargs={'pk': authenticator.id})}

    def extra_data(self, user, backend, response, *args, **kwargs):
        attrs = response["attributes"] if "attributes" in response else {}
        for perm in ["is_superuser", get_setting('ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG')]:
            if perm in attrs:
                kwargs["social"].extra_data[perm] = attrs[perm]

        # Move group spec up a level if present
        if "Group" in attrs:
            response["Group"] = attrs["Group"]
        data = super().extra_data(user, backend, response, *args, **kwargs)

        # Ideally we would always have a DB instance
        # But if something was mocked in a test or somehow a db_instance just wasn't passed in we don't want to error here
        if self.database_instance is None:
            return data

        # The fields we want in extra get embedded into the ENABLED_IDPS field so we need to get them out from there
        idp_data = self.database_instance.configuration.get('ENABLED_IDPS', {}).get(idp_string, {})

        # We are going to auto-include all of the fields like USER_FIRST_NAME, USER_EMAIL, etc.
        for field, attr_name in SAMLConfiguration.settings_to_enabled_idps_fields.items():
            if field in ('IDP_URL', 'IDP_X509_CERT', 'IDP_ENTITY_ID'):
                continue

            field_name = idp_data.get(attr_name, None)
            if field_name in attrs:
                data[field_name] = attrs[field_name]

        return data

    def get_user_groups(self, extra_groups=[]):
        return extra_groups

    def get_alternative_uid(self, **kwargs):
        if uid := kwargs.get("uid", None):
            if ":" in uid:
                return uid.split(":", maxsplit=1)[1]

        return None


class SAMLMetadataView(View):
    def get(self, request, pk=None, format=None):
        authenticator = Authenticator.objects.get(id=pk)
        plugin = get_authenticator_plugin(authenticator.type)
        if plugin.type != 'SAML':
            logger.debug(f"Authenticator {authenticator.id} has a type which does not support metadata {plugin.type}")
            return HttpResponseNotFound()

        strategy = AuthenticatorStrategy(AuthenticatorStorage())
        complete_url = authenticator.configuration.get('CALLBACK_URL')
        saml_backend = strategy.get_backend(slug=authenticator.slug, redirect_uri=complete_url)
        try:
            metadata, errors = saml_backend.generate_metadata_xml()
        except OneLogin_Saml2_Error as e:
            errors = e
        if not errors:
            return HttpResponse(content=metadata, content_type='text/xml')
        else:
            return HttpResponse(content=errors, content_type='text/plain')


urls = [
    # SAML Metadata
    re_path(r'authenticators/(?P<pk>[0-9]+)/metadata/$', SAMLMetadataView.as_view(), name='authenticator-metadata'),
]
