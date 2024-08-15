from copy import copy
from typing import Optional

from ansible_base.lib.cache.fallback_cache import FALLBACK_CACHE, PRIMARY_CACHE, STATUS_CACHE

#
# If you are adding a new dynamic setting:
#     Please be sure to modify pyproject.toml with your new settings in tool.setuptools.dynamic
#     Add a new requirements/requirements_<section>.in /even if its an empty file/
#


def get_dab_settings(
    installed_apps: list[str],
    rest_framework: Optional[dict] = None,
    spectacular_settings: Optional[dict] = None,
    authentication_backends: Optional[list[str]] = None,
    middleware: Optional[list[str]] = None,
    oauth2_provider: Optional[dict] = None,
    caches: Optional[dict] = None,
) -> dict:
    dab_data = {}

    # The org and team abstract models cause errors if not set, even if not used
    dab_data['ANSIBLE_BASE_TEAM_MODEL'] = 'auth.Group'
    dab_data['ANSIBLE_BASE_ORGANIZATION_MODEL'] = 'auth.Group'

    # This is needed for the rest_filters app, but someone may use the filter class
    # without enabling the ansible_base.rest_filters app explicitly
    # we also apply this to views from other apps so we should always define it
    dab_data['ANSIBLE_BASE_REST_FILTERS_RESERVED_NAMES'] = (
        'page',
        'page_size',
        'format',
        'order',
        'order_by',
        'search',
        'type',
        'host_filter',
        'count_disabled',
        'no_truncate',
        'limit',
        'validate',
    )

    if 'ansible_base.api_documentation' in installed_apps:
        if 'drf_spectacular' not in installed_apps:
            dab_data.setdefault('INSTALLED_APPS', copy(installed_apps))
            dab_data['INSTALLED_APPS'].append('drf_spectacular')
            # Shadow local variable so subsequent conditionals works.
            installed_apps = dab_data['INSTALLED_APPS']

        if spectacular_settings is None:
            raise RuntimeError('Must define SPECTACULAR_SETTINGS to form DAB settings with documentation app')

        dab_data['SPECTACULAR_SETTINGS'] = copy(spectacular_settings)

        for key, value in {
            'TITLE': 'Open API',
            'DESCRIPTION': 'Open API',
            'VERSION': 'v1',
            'SCHEMA_PATH_PREFIX': '/api/v1/',
        }.items():
            if key not in spectacular_settings:
                dab_data['SPECTACULAR_SETTINGS'][key] = value

        if 'DEFAULT_SCHEMA_CLASS' not in rest_framework:
            dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))
            dab_data['REST_FRAMEWORK']['DEFAULT_SCHEMA_CLASS'] = 'drf_spectacular.openapi.AutoSchema'

    # General, factual, constant of all filters that ansible_base.rest_filters ships
    dab_data['ANSIBLE_BASE_ALL_REST_FILTERS'] = (
        'ansible_base.rest_filters.rest_framework.type_filter_backend.TypeFilterBackend',
        'ansible_base.rest_filters.rest_framework.field_lookup_backend.FieldLookupBackend',
        'rest_framework.filters.SearchFilter',
        'ansible_base.rest_filters.rest_framework.order_backend.OrderByBackend',
    )

    if 'ansible_base.rest_filters' in installed_apps:
        dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))
        dab_data['REST_FRAMEWORK'].update({'DEFAULT_FILTER_BACKENDS': dab_data['ANSIBLE_BASE_ALL_REST_FILTERS']})
    else:
        # Explanation - these are the filters for views provided by DAB like /authenticators/
        # we want them to be enabled by default _even if_ the rest_filters app is not used
        # so that clients have consistency, but if an app wants to turn them off, they can.
        # these will be combined with the actual DRF defaults in our base view
        dab_data['ANSIBLE_BASE_CUSTOM_VIEW_FILTERS'] = dab_data['ANSIBLE_BASE_ALL_REST_FILTERS']

    if 'ansible_base.authentication' in installed_apps:
        if 'social_django' not in installed_apps:
            dab_data.setdefault('INSTALLED_APPS', copy(installed_apps))
            dab_data['INSTALLED_APPS'].append('social_django')
            # Shadow local variable so subsequent conditionals works.
            installed_apps = dab_data['INSTALLED_APPS']

        if "ansible_base.authentication.backend.AnsibleBaseAuth" not in authentication_backends:
            dab_data.setdefault('AUTHENTICATION_BACKENDS', copy(authentication_backends))
            dab_data['AUTHENTICATION_BACKENDS'].append("ansible_base.authentication.backend.AnsibleBaseAuth")

        middleware_classes = [
            'ansible_base.authentication.middleware.SocialExceptionHandlerMiddleware',
            'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware',
        ]
        if any(cls_name not in middleware for cls_name in middleware_classes):
            if middleware is None:
                local_middleware = []
            else:
                local_middleware = copy(middleware)

            for mw in middleware_classes:
                if mw not in local_middleware:
                    try:
                        index = local_middleware.index('django.contrib.auth.middleware.AuthenticationMiddleware')
                        local_middleware.insert(index, mw)
                    except ValueError:
                        local_middleware.append(mw)

            dab_data['MIDDLEWARE'] = local_middleware

        if rest_framework is None:
            raise RuntimeError('Must define REST_FRAMEWORK setting to use authentication app')

        drf_authentication_class = 'ansible_base.authentication.session.SessionAuthentication'
        dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))
        dab_data['REST_FRAMEWORK'].setdefault('DEFAULT_AUTHENTICATION_CLASSES', [])

        if drf_authentication_class not in dab_data['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES']:
            dab_data['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, drf_authentication_class)

        dab_data['ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES'] = ["ansible_base.authentication.authenticator_plugins"]

        dab_data['SOCIAL_AUTH_PIPELINE'] = (
            'social_core.pipeline.social_auth.social_details',
            'social_core.pipeline.social_auth.social_uid',
            'social_core.pipeline.social_auth.auth_allowed',
            'social_core.pipeline.social_auth.social_user',
            'ansible_base.authentication.utils.authentication.determine_username_from_uid_social',
            'social_core.pipeline.user.create_user',
            'social_core.pipeline.social_auth.associate_user',
            'social_core.pipeline.social_auth.load_extra_data',
            'social_core.pipeline.user.user_details',
            'ansible_base.authentication.social_auth.create_user_claims_pipeline',
        )
        dab_data['SOCIAL_AUTH_STORAGE'] = "ansible_base.authentication.social_auth.AuthenticatorStorage"
        dab_data['SOCIAL_AUTH_STRATEGY'] = "ansible_base.authentication.social_auth.AuthenticatorStrategy"
        dab_data['SOCIAL_AUTH_LOGIN_REDIRECT_URL'] = "/"

        dab_data['ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG'] = "is_system_auditor"

        # URL to send users when social auth login fails
        dab_data['LOGIN_ERROR_URL'] = "/?auth_failed"

    if 'ansible_base.rest_pagination' in installed_apps:
        if rest_framework is None:
            raise RuntimeError('Must define REST_FRAMEWORK setting to use rest_pagination app')

        dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))
        dab_data['REST_FRAMEWORK'].setdefault('DEFAULT_PAGINATION_CLASS', 'ansible_base.rest_pagination.DefaultPaginator')

    if 'ansible_base.jwt_consumer' in installed_apps:
        if 'ansible_base.rbac' not in installed_apps:
            dab_data.setdefault('INSTALLED_APPS', copy(installed_apps))
            dab_data['INSTALLED_APPS'].append('ansible_base.rbac')
            # Shadow local variable so subsequent conditionals works.
            installed_apps = dab_data['INSTALLED_APPS']

    if ('ansible_base.jwt_consumer' in installed_apps) or ('ansible_base.rbac' in installed_apps):
        dab_data['ANSIBLE_BASE_JWT_MANAGED_ROLES'] = ["Platform Auditor", "Organization Admin", "Organization Member", "Team Admin", "Team Member"]

    if 'ansible_base.rbac' in installed_apps:
        # The settings-based specification of managed roles from DAB RBAC vendored ones
        dab_data['ANSIBLE_BASE_MANAGED_ROLE_REGISTRY'] = {}
        # Permissions a user will get when creating a new item
        dab_data['ANSIBLE_BASE_CREATOR_DEFAULTS'] = ['add', 'change', 'delete', 'view']
        # Permissions API will check for related items, think PATCH/PUT
        # This is a precedence order, so first action related model has will be used
        dab_data['ANSIBLE_BASE_CHECK_RELATED_PERMISSIONS'] = ['use', 'change', 'view']
        # If a role does not already exist that can give those object permissions
        # then the system must create one, this is used for naming the auto-created role
        dab_data['ANSIBLE_BASE_ROLE_CREATOR_NAME'] = '{obj._meta.model_name}-creator-permission'
        # Require view permission in roles containing any other permission
        # this requirement does not apply to models that do not have view permission
        dab_data['ANSIBLE_BASE_ROLES_REQUIRE_VIEW'] = True
        # Require change permission to get delete permission
        dab_data['ANSIBLE_BASE_DELETE_REQUIRE_CHANGE'] = True
        # Specific feature enablement bits
        # For assignments
        dab_data['ANSIBLE_BASE_ALLOW_TEAM_PARENTS'] = True
        dab_data['ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS'] = True
        dab_data['ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER'] = False
        dab_data['ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN'] = True
        # For role definitions
        dab_data['ANSIBLE_BASE_ALLOW_CUSTOM_ROLES'] = True
        dab_data['ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES'] = False
        # Allows managing singleton permissions
        dab_data['ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES'] = False
        dab_data['ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES'] = False
        dab_data['ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API'] = True

        # Pass ignore_conflicts=True for bulk_create calls for role evaluations
        # this should be fine to resolve cross-process conflicts as long as
        # directionality is the same - adding or removing permissions
        # A value of False would result in more errors but be more conservative
        dab_data['ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS'] = True

        # User flags that can grant permission before consulting roles
        dab_data['ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS'] = ['is_superuser']
        dab_data['ANSIBLE_BASE_BYPASS_ACTION_FLAGS'] = {}

        # Save RoleEvaluation entries for child permissions on parent models
        # ex: organization roles giving view_inventory permission will save
        # entries mapping that permission to the assignment's organization
        dab_data['ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS'] = False

        # API clients can assign users and teams roles for shared resources
        dab_data['ALLOW_LOCAL_RESOURCE_MANAGEMENT'] = True
        # API clients can assign roles provided by the JWT
        # this should only be left as True for testing purposes
        # TODO: change this default to False
        dab_data['ALLOW_LOCAL_ASSIGNING_JWT_ROLES'] = True
        # API clients can create custom roles that change shared resources
        dab_data['ALLOW_SHARED_RESOURCE_CUSTOM_ROLES'] = False

        dab_data['MANAGE_ORGANIZATION_AUTH'] = True

        dab_data['ORG_ADMINS_CAN_SEE_ALL_USERS'] = True

    if 'ansible_base.resource_registry' in installed_apps:
        # Disable reverse syncing by default
        dab_data['DISABLE_RESOURCE_SERVER_SYNC'] = True

    if 'ansible_base.oauth2_provider' in installed_apps:
        if 'oauth2_provider' not in installed_apps:
            dab_data.setdefault('INSTALLED_APPS', copy(installed_apps))
            dab_data['INSTALLED_APPS'].append('oauth2_provider')
            # Shadow local variable so subsequent conditionals works.
            installed_apps = dab_data['INSTALLED_APPS']

        if oauth2_provider is None:
            raise RuntimeError('Must define OAUTH2_PROVIDER setting to use ansible_base.oauth2_provider app')

        dab_data['OAUTH2_PROVIDER'] = copy(oauth2_provider)

        if 'ACCESS_TOKEN_EXPIRE_SECONDS' not in oauth2_provider:
            dab_data['OAUTH2_PROVIDER']['ACCESS_TOKEN_EXPIRE_SECONDS'] = 31536000000
        if 'AUTHORIZATION_CODE_EXPIRE_SECONDS' not in oauth2_provider:
            dab_data['OAUTH2_PROVIDER']['AUTHORIZATION_CODE_EXPIRE_SECONDS'] = 600
        if 'REFRESH_TOKEN_EXPIRE_SECONDS' not in oauth2_provider:
            dab_data['OAUTH2_PROVIDER']['REFRESH_TOKEN_EXPIRE_SECONDS'] = 2628000
        if 'PKCE_REQUIRED' not in oauth2_provider:
            # For compat with awx, we don't require PKCE, but the new version
            # of DOT that we are using requires it by default.
            dab_data['OAUTH2_PROVIDER']['PKCE_REQUIRED'] = False

        dab_data['OAUTH2_PROVIDER']['OAUTH2_BACKEND_CLASS'] = 'ansible_base.oauth2_provider.authentication.OAuthLibCore'

        dab_data['OAUTH2_PROVIDER']['APPLICATION_MODEL'] = 'dab_oauth2_provider.OAuth2Application'
        dab_data['OAUTH2_PROVIDER']['ACCESS_TOKEN_MODEL'] = 'dab_oauth2_provider.OAuth2AccessToken'

        if rest_framework is None:
            raise RuntimeError('Must define REST_FRAMEWORK setting to use ansible_base.oauth2_provider app')

        dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))

        oauth2_authentication_class = 'ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication'
        if 'DEFAULT_AUTHENTICATION_CLASSES' not in rest_framework:
            dab_data['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES'] = []
        if oauth2_authentication_class not in rest_framework['DEFAULT_AUTHENTICATION_CLASSES']:
            dab_data.setdefault('REST_FRAMEWORK', copy(rest_framework))
            dab_data['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, oauth2_authentication_class)

        # These have to be defined for the migration to function
        dab_data['OAUTH2_PROVIDER_APPLICATION_MODEL'] = 'dab_oauth2_provider.OAuth2Application'
        dab_data['OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL'] = 'dab_oauth2_provider.OAuth2AccessToken'
        dab_data['OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL'] = "dab_oauth2_provider.OAuth2RefreshToken"
        dab_data['OAUTH2_PROVIDER_ID_TOKEN_MODEL'] = "dab_oauth2_provider.OAuth2IDToken"

        dab_data['ALLOW_OAUTH2_FOR_EXTERNAL_USERS'] = False

        if caches is not None:
            dab_data['CACHES'] = copy(caches)
            # Ensure proper configuration for fallback cache
            default_backend = caches.get('default', {}).get('BACKEND', '')
            if default_backend == 'ansible_base.cache.fallback_cache.DABCacheWithFallback':
                # Ensure primary and fallback are defined
                if PRIMARY_CACHE not in caches or FALLBACK_CACHE not in caches:
                    raise RuntimeError(f'Cache definitions with the keys {PRIMARY_CACHE} and {FALLBACK_CACHE} must be defined when DABCacheWithFallback is used.')
                # Add fallback status manager cache
                dab_data['CACHES'][STATUS_CACHE] = {
                    'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
                    'LOCATION': '/var/tmp/fallback_status',
                }

    return dab_data
