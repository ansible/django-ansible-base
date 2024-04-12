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
        'social_core.pipeline.user.get_username',
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
    # Settings for the RBAC system, override as necessary in app
    ANSIBLE_BASE_ROLE_PRECREATE = {
        'object_admin': '{cls._meta.model_name}-admin',
        'org_admin': 'organization-admin',
        'org_children': 'organization-{cls._meta.model_name}-admin',
        'special': '{cls._meta.model_name}-{action}',
    }

    # Permissions a user will get when creating a new item
    ANSIBLE_BASE_CREATOR_DEFAULTS = ['add', 'change', 'delete', 'view']
    # If a role does not already exist that can give those object permissions
    # then the system must create one, this is used for naming the auto-created role
    ANSIBLE_BASE_ROLE_CREATOR_NAME = '{obj._meta.model_name}-creator-permission'

    # Specific feature enablement bits
    # For assignments
    ANSIBLE_BASE_ALLOW_TEAM_PARENTS = True
    ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS = True
    ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN = True
    # For role definitions
    ANSIBLE_BASE_ALLOW_CUSTOM_ROLES = True
    ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES = False
    # Allows managing singleton permissions
    ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = False
    ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES = False
    ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API = True

    # User flags that can grant permission before consulting roles
    ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
    ANSIBLE_BASE_BYPASS_ACTION_FLAGS = {}

    ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS = False
