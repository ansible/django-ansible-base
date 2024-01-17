import logging

from django.http import HttpResponse, HttpResponseNotFound
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from onelogin.saml2.errors import OneLogin_Saml2_Error
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from rest_framework.reverse import reverse
from rest_framework.serializers import ValidationError
from rest_framework.views import View
from social_core.backends.saml import SAMLAuth, SAMLIdentityProvider

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_plugin
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.social_auth import AuthenticatorConfigTestStrategy, AuthenticatorStorage, AuthenticatorStrategy, SocialAuthMixin
from ansible_base.common.serializers.fields import CharField, JSONField, ListField, PrivateKey, PublicCert, URLField
from ansible_base.common.utils.encryption import ENCRYPTED_STRING
from ansible_base.common.utils.validation import validate_cert_with_key

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
        default="aap",
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
            "A dict of key value pairs that are passed to the underlying python-saml security setting https://github.com/onelogin/python-saml#settings"
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
        help_text=_("The public cert used for secrets coming from the IdP."),
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
        help_text=_("The field in the assertion which represents the users groups."),
        ui_field_label=_('Groups'),
    )
    IDP_ATTR_EMAIL = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the users email."),
        ui_field_label=_('User Email'),
    )
    IDP_ATTR_USERNAME = CharField(
        allow_null=True,
        required=False,
        help_text=_("The field in the assertion which represents the users username."),
        ui_field_label=_('Username'),
    )
    IDP_ATTR_LAST_NAME = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the users last name."),
        ui_field_label=_('User Last Name'),
    )
    IDP_ATTR_FIRST_NAME = CharField(
        allow_null=True,
        help_text=_("The field in the assertion which represents the users first name."),
        ui_field_label=_('User First Name'),
    )
    IDP_ATTR_USER_PERMANENT_ID = CharField(
        allow_null=True,
        required=False,
        help_text=_("The field in the assertion which represents the users permanent id (overrides IDP_ATTR_USERNAME)"),
        ui_field_label=_('User Permanent ID'),
    )
    CALLBACK_URL = URLField(
        required=False,
        allow_null=True,
        help_text=_(
            '''Register the service as a service provider (SP) with each identity provider (IdP) you have configured.'''
            '''Provide your SP Entity ID and this ACS URL for your application.'''
        ),
        ui_field_label=_('SAML Assertion Consumer Service (ACS) URL'),
    )

    def validate(self, attrs):
        # attrs is only the data in the configuration field
        errors = {}
        # pull the cert_info out of the existing object (if we have one)
        cert_info = {
            "SP_PRIVATE_KEY": getattr(self.instance, 'configuration', {}).get('SP_PRIVATE_KEY', None),
            "SP_PUBLIC_CERT": getattr(self.instance, 'configuration', {}).get('SP_PUBLIC_CERT', attrs.get('SP_PUBLIC_CERT', None)),
        }

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

        idp_data = attrs.get('ENABLED_IDPS', {}).get(idp_string, {})
        if not idp_data.get('attr_user_permanent_id', None) and not idp_data.get('attr_username'):
            errors['IDP_ATTR_USERNAME'] = "Either IDP_ATTR_USERNAME or IDP_ATTR_USER_PERMANENT_ID needs to be set"

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
            raise ValidationError(f"Failed to load config: {e}")

        if invalid_security_settings:
            raise ValidationError({'SECURITY_CONFIG': f"Invalid keys: {', '.join(invalid_security_settings)}"})

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


class AuthenticatorPlugin(SocialAuthMixin, SAMLAuth, AbstractAuthenticatorPlugin):
    configuration_class = SAMLConfiguration
    type = "SAML"
    logger = logger
    category = "sso"
    configuration_encrypted_fields = ['SP_PRIVATE_KEY']

    def get_login_url(self, authenticator):
        url = reverse('social:begin', kwargs={'backend': authenticator.slug})
        return f'{url}?idp={idp_string}'

    def add_related_fields(self, request, authenticator):
        return {"metadata": reverse('authenticator-metadata', kwargs={'pk': authenticator.id})}

    def validate(self, serializer, data):
        # if we have an instance already and we didn't get a configuration parameter we are just updating other fields and can return
        if serializer.instance and 'configuration' not in data:
            return data

        configuration = data['configuration']
        if not configuration.get('CALLBACK_URL', None):
            if not serializer.instance:
                slug = generate_authenticator_slug(data['type'], data['name'])
            else:
                slug = serializer.instance.slug

            configuration['CALLBACK_URL'] = reverse('social:complete', request=serializer.context['request'], kwargs={'backend': slug})

        return data


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
