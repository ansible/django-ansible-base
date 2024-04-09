#
# If you are adding a new dynamic setting:
#     Please be sure to modify pyproject.toml with your new settings in tool.setuptools.dynamic
#     Add a new requirements/requirements_<section>.in /even if its an empty file/
#

# The org and team abstract models cause errors if not set, even if not used
try:
    ANSIBLE_BASE_TEAM_MODEL
except NameError:
    ANSIBLE_BASE_TEAM_MODEL = 'auth.Group'

try:
    ANSIBLE_BASE_ORGANIZATION_MODEL
except NameError:
    ANSIBLE_BASE_ORGANIZATION_MODEL = 'auth.Group'

try:
    INSTALLED_APPS  # noqa: F821
except NameError:
    INSTALLED_APPS = []

try:
    REST_FRAMEWORK  # noqa: F821
except NameError:
    REST_FRAMEWORK = {}


# This is needed for the rest_filters app, but someone may use the filter class
# without enabling the ansible_base.rest_filters app explicitly
# we also apply this to views from other apps so we should always define it
try:
    ANSIBLE_BASE_REST_FILTERS_RESERVED_NAMES
except NameError:
    ANSIBLE_BASE_REST_FILTERS_RESERVED_NAMES = (
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


if 'ansible_base.api_documentation' in INSTALLED_APPS:
    if 'drf_spectacular' not in INSTALLED_APPS:
        INSTALLED_APPS.append('drf_spectacular')

    try:
        SPECTACULAR_SETTINGS  # noqa: F821
    except NameError:
        SPECTACULAR_SETTINGS = {}

    for key, value in {
        'TITLE': 'Open API',
        'DESCRIPTION': 'Open API',
        'VERSION': 'v1',
        'SCHEMA_PATH_PREFIX': '/api/v1/',
    }.items():
        if key not in SPECTACULAR_SETTINGS:
            SPECTACULAR_SETTINGS[key] = value

    if 'DEFAULT_SCHEMA_CLASS' not in REST_FRAMEWORK:
        REST_FRAMEWORK['DEFAULT_SCHEMA_CLASS'] = 'drf_spectacular.openapi.AutoSchema'


# General, factual, constant of all filters that ansible_base.rest_filters ships
ANSIBLE_BASE_ALL_REST_FILTERS = (
    'ansible_base.rest_filters.rest_framework.type_filter_backend.TypeFilterBackend',
    'ansible_base.rest_filters.rest_framework.field_lookup_backend.FieldLookupBackend',
    'rest_framework.filters.SearchFilter',
    'ansible_base.rest_filters.rest_framework.order_backend.OrderByBackend',
)


if 'ansible_base.rest_filters' in INSTALLED_APPS:
    REST_FRAMEWORK.update({'DEFAULT_FILTER_BACKENDS': ANSIBLE_BASE_ALL_REST_FILTERS})
else:
    # Explanation - these are the filters for views provided by DAB like /authenticators/
    # we want them to be enabled by default _even if_ the rest_filters app is not used
    # so that clients have consistency, but if an app wants to turn them off, they can.
    # these will be combined with the actual DRF defaults in our base view
    ANSIBLE_BASE_CUSTOM_VIEW_FILTERS = ANSIBLE_BASE_ALL_REST_FILTERS


if 'ansible_base.authentication' in INSTALLED_APPS:
    if 'social_django' not in INSTALLED_APPS:
        INSTALLED_APPS.append('social_django')

    try:
        AUTHENTICATION_BACKENDS  # noqa: F821
    except NameError:
        AUTHENTICATION_BACKENDS = []
    if "ansible_base.authentication.backend.AnsibleBaseAuth" not in AUTHENTICATION_BACKENDS:
        AUTHENTICATION_BACKENDS.append("ansible_base.authentication.backend.AnsibleBaseAuth")

    middleware_class = 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware'
    try:
        MIDDLEWARE  # noqa: F821
        if middleware_class not in MIDDLEWARE:  # noqa: F821
            try:
                index = MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware')  # noqa: F821
                MIDDLEWARE.insert(index, middleware_class)  # noqa: F821
            except ValueError:
                MIDDLEWARE.append(middleware_class)  # noqa: F821
    except NameError:
        MIDDLEWARE = [middleware_class]

    drf_authentication_class = 'ansible_base.authentication.session.SessionAuthentication'
    if 'DEFAULT_AUTHENTICATION_CLASSES' not in REST_FRAMEWORK:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = []  # noqa: F821
    if drf_authentication_class not in REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, drf_authentication_class)  # noqa: F821

    try:
        ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES  # noqa: F821
    except NameError:
        ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ["ansible_base.authentication.authenticator_plugins"]

    SOCIAL_AUTH_PIPELINE = (
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
    SOCIAL_AUTH_STORAGE = "ansible_base.authentication.social_auth.AuthenticatorStorage"
    SOCIAL_AUTH_STRATEGY = "ansible_base.authentication.social_auth.AuthenticatorStrategy"
    SOCIAL_AUTH_LOGIN_REDIRECT_URL = "/"


if 'ansible_base.rest_pagination' in INSTALLED_APPS:
    REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] = 'ansible_base.rest_pagination.DefaultPaginator'


if 'ansible_base.rbac' in INSTALLED_APPS:
    # The settings-based specification of managed roles from DAB RBAC vendored ones
    ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {}

    # Permissions a user will get when creating a new item
    ANSIBLE_BASE_CREATOR_DEFAULTS = ['add', 'change', 'delete', 'view']
    # Permissions API will check for related items, think PATCH/PUT
    # This is a precedence order, so first action related model has will be used
    ANSIBLE_BASE_CHECK_RELATED_PERMISSIONS = ['use', 'change', 'view']
    # If a role does not already exist that can give those object permissions
    # then the system must create one, this is used for naming the auto-created role
    ANSIBLE_BASE_ROLE_CREATOR_NAME = '{obj._meta.model_name}-creator-permission'

    # Specific feature enablement bits
    # For assignments
    ANSIBLE_BASE_ALLOW_TEAM_PARENTS = True
    ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS = True
    ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER = False
    ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN = True
    # For role definitions
    ANSIBLE_BASE_ALLOW_CUSTOM_ROLES = True
    ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES = False
    # Allows managing singleton permissions
    ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = False
    ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES = False
    ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API = True

    # Pass ignore_conflicts=True for bulk_create calls for role evaluations
    # this should be fine to resolve cross-process conflicts as long as
    # directionality is the same - adding or removing permissions
    # A value of False would result in more errors but be more conservative
    ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS = True

    # User flags that can grant permission before consulting roles
    ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
    ANSIBLE_BASE_BYPASS_ACTION_FLAGS = {}

    ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS = False

    try:
        MANAGE_ORGANIZATION_AUTH
    except NameError:
        MANAGE_ORGANIZATION_AUTH = True

    try:
        ORG_ADMINS_CAN_SEE_ALL_USERS
    except NameError:
        ORG_ADMINS_CAN_SEE_ALL_USERS = True


if 'ansible_base.oauth2_provider' in INSTALLED_APPS:  # noqa: F821
    if 'oauth2_provider' not in INSTALLED_APPS:  # noqa: F821
        INSTALLED_APPS.append('oauth2_provider')  # noqa: F821

    try:
        OAUTH2_PROVIDER  # noqa: F821
    except NameError:
        OAUTH2_PROVIDER = {}

    if 'ACCESS_TOKEN_EXPIRE_SECONDS' not in OAUTH2_PROVIDER:
        OAUTH2_PROVIDER['ACCESS_TOKEN_EXPIRE_SECONDS'] = 31536000000
    if 'AUTHORIZATION_CODE_EXPIRE_SECONDS' not in OAUTH2_PROVIDER:
        OAUTH2_PROVIDER['AUTHORIZATION_CODE_EXPIRE_SECONDS'] = 600
    if 'REFRESH_TOKEN_EXPIRE_SECONDS' not in OAUTH2_PROVIDER:
        OAUTH2_PROVIDER['REFRESH_TOKEN_EXPIRE_SECONDS'] = 2628000

    OAUTH2_PROVIDER['APPLICATION_MODEL'] = 'dab_oauth2_provider.OAuth2Application'
    OAUTH2_PROVIDER['ACCESS_TOKEN_MODEL'] = 'dab_oauth2_provider.OAuth2AccessToken'

    oauth2_authentication_class = 'ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication'
    if 'DEFAULT_AUTHENTICATION_CLASSES' not in REST_FRAMEWORK:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = []  # noqa: F821
    if oauth2_authentication_class not in REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, oauth2_authentication_class)  # noqa: F821

    # These have to be defined for the migration to function
    OAUTH2_PROVIDER_APPLICATION_MODEL = 'dab_oauth2_provider.OAuth2Application'
    OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = 'dab_oauth2_provider.OAuth2AccessToken'
    OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "dab_oauth2_provider.OAuth2RefreshToken"
    OAUTH2_PROVIDER_ID_TOKEN_MODEL = "dab_oauth2_provider.OAuth2IDToken"

    ALLOW_OAUTH2_FOR_EXTERNAL_USERS = False
