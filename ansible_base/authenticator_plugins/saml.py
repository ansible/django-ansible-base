import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.serializers import ValidationError
from social_core.backends.saml import SAMLAuth

from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.serializers.fields import PrivateKey, PublicCert, URLField
from ansible_base.utils.encryption import ENCRYPTED_STRING
from ansible_base.utils.validation import validate_cert_with_key

logger = logging.getLogger('ansible_base.authenticator_plugins.saml')

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

    SP_ENTITY_ID = serializers.CharField(
        allow_null=False,
        max_length=512,
        default="aap_gateway",
        help_text=_(
            "The application-defined unique identifier used as the audience of the SAML service provider (SP) configuration. This is usually the URL for the"
            " service."
        ),
    )
    SP_PUBLIC_CERT = PublicCert(allow_null=False, help_text=_("Create a keypair to use as a service provider (SP) and include the certificate content here."))
    SP_PRIVATE_KEY = PrivateKey(allow_null=False, help_text=_("Create a keypair to use as a service provider (SP) and include the private key content here."))
    ORG_INFO = serializers.JSONField(
        allow_null=False,
        default={"en-US": {"url": "", "name": "", "displayname": ""}},
        help_text=_("Provide the URL, display name, and the name of your app. Refer to the documentation for example syntax."),
    )
    TECHNICAL_CONTACT = serializers.JSONField(
        allow_null=False,
        default={'givenName': "", 'emailAddress': ""},
        help_text=_("Provide the name and email address of the technical contact for your service provider. Refer to the documentation for example syntax."),
    )
    SUPPORT_CONTACT = serializers.JSONField(
        allow_null=False,
        default={'givenName': "", 'emailAddress': ""},
        help_text=_("Provide the name and email address of the support contact for your service provider. Refer to the documentation for example syntax."),
    )
    SP_EXTRA = serializers.JSONField(
        default={"requestedAuthnContext": False},
        help_text=_("A dict of key value pairs to be passed to the underlying python-saml Service Provider configuration setting."),
    )
    SECURITY_CONFIG = serializers.JSONField(
        default={},
        help_text=_(
            "A dict of key value pairs that are passed to the underlying python-saml security setting https://github.com/onelogin/python-saml#settings"
        ),
    )
    EXTRA_DATA = serializers.ListField(
        default=[],
        help_text=_("A list of tuples that maps IDP attributes to extra_attributes. Each attribute will be a list of values, even if only 1 value."),
    )
    IDP_URL = URLField(
        allow_null=False,
        help_text=_("The URL to redirect the user to for login initiation."),
    )
    IDP_X509_CERT = PublicCert(
        allow_null=False,
        help_text=_("The public cert used for secrets coming from the IdP."),
    )
    IDP_ENTITY_ID = serializers.CharField(
        allow_null=False,
        help_text=_("The entity ID returned in the assertion."),
    )
    IDP_GROUPS = serializers.CharField(
        help_text=_("The field in the assertion which represents the users groups."),
    )
    IDP_ATTR_EMAIL = serializers.CharField(
        allow_null=False,
        help_text=_("The field in the assertion which represents the users email."),
    )
    IDP_ATTR_USERNAME = serializers.CharField(
        help_text=_("The field in the assertion which represents the users username."),
    )
    IDP_ATTR_LAST_NAME = serializers.CharField(
        allow_null=False,
        help_text=_("The field in the assertion which represents the users last name."),
    )
    IDP_ATTR_FIRST_NAME = serializers.CharField(
        allow_null=False,
        help_text=_("The field in the assertion which represents the users first name."),
    )
    IDP_ATTR_USER_PERMANENT_ID = serializers.CharField(
        help_text=_("The field in the assertion which represents the users permanent id (overrides IDP_ATTR_USERNAME)"),
    )

    def validate(self, attrs):
        # attrs is only the data in the configuration field
        errors = {}
        # pull the cert_info out of the existing object (if we have one)
        cert_info = {
            "SP_PRIVATE_KEY": getattr(self.instance, 'configuration', {}).get('SP_PRIVATE_KEY', None),
            "SP_PUBLIC_CERT": getattr(self.instance, 'configuration', {}).get('SP_PUBLIC_CERT', None),
        }

        # Now get the cert_info out of the passed in attrs (if there is any)
        for cert_type in cert_info.keys():
            item = attrs.get(cert_type, None)
            if item and item == ENCRYPTED_STRING and not self.instance:
                # Catch a case where we got input but it was ENCRYPTED and we don't have an object yet
                errors[cert_type] = f"Can not be {ENCRYPTED_STRING} on creation"
            elif item and item != ENCRYPTED_STRING:
                # We got an input form the attrs so let that override whatever was in the object
                cert_info[cert_type] = item
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
        # TODO: Check to make sure either ID or Perminant ID is set
        if not idp_data['attr_user_permanent_id'] and not idp_data['attr_username']:
            errors['IDP_ATTR_USERNAME'] = "Either IDP_ATTR_USERNAME or IDP_ATTR_USER_PERMANENT_ID needs to be set"

        if errors:
            raise serializers.ValidationError(errors)

        response = super().validate(attrs)
        return response

    def to_internal_value(self, data):
        resp = super().to_internal_value(data)
        idp_data = {}
        for field in self.settings_to_enabled_idps_fields:
            if field in resp:
                idp_data[self.settings_to_enabled_idps_fields[field]] = resp[field]
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
