# Authenticator Plugins

django-ansible-base provides a plugable authentication system (see authentication.md for high level details) that are backed by individual plugin files. The plugin files are meant to provide access to specific authentication methods like SAML, ldap, OIDC, tacacs, etc. 

This document outlines how to create authenticator plugins.

## Creating an authenticator plugin

### The File
Authenticator plugins in django-ansible-base should be individual files in the ansible_base/authenticator_plugins folder. That being said, you can configure django-ansible-base to look in additional directories for the authenticator_plugins (see authentication.md). The file should be a logical name for the backend service you are communicating with; for example, saml.py houses the code for connecting to SAML. 

### The AuthenticatorPlugin Class
The primary class you need to implement in your file is called `AuthenticatorPlugin`. When django-ansible-base attempts to instantiate an authenticator from an authenticator_plugin it will be loading this class. This class must be a superclass of `AbstractAuthenticatorPlugin` but can also subclass additional classes if required. For example, the SAML authenticator class subclasses `SAMLAuth` and `SocialAuthMixin` in addition to `AbstractAuthenticatorPlugin`.

The abstract class can be found in ansible_base.authentication.authenticator_plugins.base in here you can see several fields and methods that can be set or overridden as part of the authenticator class.

#### Customizable Fields
`configuration_class`: This must be a class of type `BaseAuthenticatorConfiguration` (see section The Configuration Class) for more details about this class.
`configuration_encrypted_fields`: An array of fields from the configuration_class that are to be stored encrypted in the database. Putting the name of the field in here will automatically perform the encryption/decryption of the field through the serializer.
`type`: The specific type name for this authenticator_plugin, i.e. SAML. This should be unique across the authenticator_plugins.
`logger`: The plugin will default to a logger of `ansible_base.authentication.models.abstract_authenticator` but you can set logger to be more specific for your plugin. i.e. `ansible_base.authentication.authenticator_plugins.saml`. Note: this takes the logger class, not a string of the logger name.
`category`: Currently there are two supported categories: `password` and `sso`. This field indicates to the UI if the username/password fields should be displayed on the login form or if there should be an SSO icon for any authenticator of this type. Additional categories may be added in the future but are out of scope for this document.


#### Customizable Methods
`def get_login_url(self, authenticator)`: If providing an SSO provider you can manage the login_url associated with the authenticator. Note: The default method in the Abstract class has an appropriate return value for most social auth login types. 
`add_related_fields`: This function will return additional related fields to add to the serializer for authenticators of this plugin type. For example, SAML authentication provides a metadata related field to expose the SAML SP metadata.
`validate`: This function is called by the Authenticator serializer so if you need to validate multiple fields from your `configuration_class` against one another you can implement validate here.
`authenticate`: If you need to actually do something to authenticate the user you can implement this method. For example the LDAP authenticator_plugin implements this field to pass the username/password back to the LDAP server and process the response. 

Methods other than those described above should not be overridden in normal circumstances.


### The Configuration Class
The Configuration Class tells the plugin system what attributes are needed for this authentication_plugin to work with its backend and will vary based on backend implementation. This is a Serializer field and as such has several fields related to serialization. The configuration class for your authenticator_plugin must be a superclass of `ansible_base.authentication.authenticator_plugins.base.BaseAUthenticatorConfiguration`

#### Documentation URL
Your configuration class should first override the documentation_url property. This is a URL to point a user towards the documentation for the library you are implementing. This can be used to reference the general architecture of the backend and how the configuration classes' fields are used by any supporting libraries. 

#### Serializer Fields
Your configuration class can then specify 0 or more configuration fields. These fields are serializer fields but should come from `ansible_base.lib.serializers.fields`. There we subclass serializer fields to add the ui_field_label and any additional fields we might require in the future.

Here is an example of a serializer field from the SAML authenticator:
```
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
```
The fields can take any valid entry for a Serializer field. Note the `required` field is currently ignored and derived from the `allow_null` parameter.  Please be sure to add `help_text` to each field in the serializer.

Additionally, you should include a field called `ui_field_label` as this will tell the UI what the human friendly field name should be. If you do not specify a `ui_field_label` the default value of `Undefined` will be added. 

Side note: The base class will automatically add `ADDITIONAL_UNVERIFIED_ARGS` this allows for users to add additional parameters to the authenticator that your authenticator_plugin configuration class did not explicitly expose. The settings from the serializer will be updated with the settings from this field and then used by the backend. Technically you could supply the same value in this dict that would override a validated field from the serializer. 

#### Serializer Methods
In addition to defining Fields you can add any additional serializer methods to this class. For example:

`to_internal_value/to_representation`: These methods are common Serializer methods and can be overridden if you want to interpolate data. For example, the SAML authenticator uses these methods to combine individual configuration fields into a single field in the DB and extracts the single filed form the DB and turns them into the individual fields for the Serializer to present.
`validate`: Note, this passes all of the configuration parameters as a single field from the authenticator serializer. So you have access to any field that is specified by your class but not other fields from the authenticator. So, for example, if you need the `name` field for the authenticator to do some validation you would want to implement the `validate` method on the AuthenticatorPlugin class and perform inter-field validation there.  

### Additional Views
If your provider requires additional URLs you can specify in the file a `urls = []` note, this is not in either class, just a top level variable. Any paths in here will be applied /per authenticator/. This can be coupled with the AuthenticatorPlugin's `add_related_fields` method. See the SAML adapter for an example of this.

If you need to add global URLs like those needed for social-core you can either do it in the django-ansible-base URLs to specify how an app would do that in the authentication.md file. This may be a better general approach since django-ansible-base provides many functions so an app including django-ansible-base may not need URLs for an authenticator it does not use.


## Additional Python Requirements
Currently the only way to specify additional python requirements which may be needed for your plugin is to modify the `requirements/requirements.in`` file. If your plugin requires additional python requirements please create a section like:
```
# LDAP Authenticator Plugins
django-auth-ldap
python-ldap
```

## Social Auth

Social Auth backends can be turned into authenticators by subclassing `SocialAuthMixin` and `AbstractAuthenticatorPlugin`
as shown in the example bellow (note that the `SocialAuthMixin` MUST come before KeycloakOauth2 so that the backend's name
gets set correctly):

```python
import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from social_core.backends.keycloak import KeycloakOAuth2

from ansible_base.authentication.utils.authenticator_lib import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.keycloak')


class KeycloakConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/keycloak.html"

    ACCESS_TOKEN_URL = URLField(
        help_text=_("Location where this app can fetch the user's token from."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/token",
        allow_null=False,
    )
    AUTHORIZATION_URL = URLField(
        help_text=_("Location to redirect the user to during the login flow."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/auth",
        allow_null=False,
    )
    KEY = serializers.CharField(help_text=_("Keycloak Client ID."), allow_null=False)
    PUBLIC_KEY = serializers.CharField(help_text=_("RS256 public key provided by your Keycloak ream."), allow_null=False)
    SECRET = serializers.CharField(help_text=_("Keycloak Client secret."), allow_null=True)


class AuthenticatorPlugin(SocialAuthMixin, KeycloakOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = KeycloakConfiguration
    type = "keycloak"
    logger = logger

    def get_user_groups(self):
        return []
```

In addition to the base classes, each social authenticator must:
- Define a `configuration_class` that subclasses `BaseAuthenticatorConfiguration`. This is a modified DRF serializer
  object is defined in in the same way.
- Define a plugin type.
- Define `get_user_groups()` (optional): authenticators can add extra logic here to return a list of groups based on
  the attributes returned by their IDP.
