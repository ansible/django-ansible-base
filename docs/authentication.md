# Authentication

django-ansible-base has a plugable authentication setup allowing you to add logins via LDAP, SAML, Local and several other methods. This document describes how to setup authentication in your app using django-ansible-base.


## Settings

### AUTHENTICATION_BACKENDS
In your settings.py file we will start by changing the AUTHENTICATION_BACKENDS:
```
AUTHENTICATION_BACKENDS = [
    "ansible_base.authentication.backend.AnsibleBaseAuth",
]
```

If you have other backends in there please consider whether or not you need them. If you do can you make a plugin for django-ansible-base?

### MIDDLEWARE
Next in your MIDDLEWARE, we want to add a django-ansible-base class like:
```
MIDDLEWARE = [
    ...
    # must come before django.contrib.auth.middleware.AuthenticationMiddleware
    'ansible_base.utils.middleware.AuthenticatorBackendMiddleware',
    ...
]
``` 

Note: this must come before django.contrib.auth.middleware.AuthenticationMiddlware in order to have precedence over it. Otherwise a local user will be authenticated even if the user was destined for LDAP/Tacacs+/Radius/etc. 


### ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIX
Next we need to setup the class prefix for the installed authenticator classes, this can be:
```
ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIX = "ansible_base.authenticator_plugins"
```

If you are going to create a different class to hold the plugins you can change this as needed.

### REST_FRAMEWORK

If you are using DRF and want to use django-ansible-base authentication we need to make changes to your REST_FRAMEWORK settings. Configure your DEFAULT_AUTHENTICATION_CLASSES to use the ansible_base class as follows:
```
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # NOTE: Do NOT put the built-in DRF SessionAuthentication here first,
        # or anything that doesn't return a string from its authenticate_header.
        # DRF uses the first thing here to determine if invalid auth should be
        # 401 or 403. The UI expects 401.
        'ansible_base.authentication.session.SessionAuthentication',
        ...
    ],
```


### Social Auth Settings
Finally, if you are using any of the social authentication classes we need to define some social classes:
```
SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'social_core.pipeline.social_auth.social_user',
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.user.create_user',
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'social_core.pipeline.user.user_details',
    'ansible_base.authentication.social_auth.create_user_claims_pipeline',
)
SOCIAL_AUTH_STORAGE = "ansible_base.authentication.social_auth.AuthenticatorStorage"
SOCIAL_AUTH_STRATEGY = "ansible_base.authentication.social_auth.AuthenticatorStrategy"
SOCIAL_AUTH_LOGIN_REDIRECT_URL = "/api/v1/me"
```

If you have additional steps for the social pipeline feel free to add them here.


## URLS

For generic authentication we need to import the urls from `ansible_base` like the following:
```
from ansible_base.urls import urls as base_urls
```

Then we will include the ansible_base endpoints as follows:
```
urlpatterns = [
    ...
    re_path(r'api/v1/', include(base_urls)),
    ...
]
```

Additionally, if you are going to support Social authentication you need to include the social_auth urls as follows:
```
urlpatterns = [
    ...
    path('api/social/', include('social_django.urls', namespace='social')),
    ...
]
```

## Restricting available authenticators

django-ansible-base comes with many types of authenticators which can be found in `ansible_base.authenticator_plugins` some of these include:
  * local (local.py) Akin to local model authentication but can still be enabled/disabled and have authenticator maps applied
  * LDAP (ldap.py) An LDAP adapter
  * Keycloak (keycloak.py) An OIDC social authenticator

If you wanted to remove authenticators from your application there are two ways to do this:
1. Remove the unwanted files from your ansible_base installation.
2. Create a new class directory in your application and only add in the authenticators you care about and then set `ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIX` to be the prefix for your class.


