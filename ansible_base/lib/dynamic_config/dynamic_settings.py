#
# If you are adding a new dynamic setting:
#     Please be sure to modify pyproject.toml with your new settings in tool.setuptools.dynamic
#     Add a new requirements/requirements_<section>.in /even if its an empty file/
#

from ansible_base.lib.dynamic_config import default_settings as _dab_default_settings


try:
    INSTALLED_APPS  # noqa: F821
except NameError:
    INSTALLED_APPS = []

try:
    REST_FRAMEWORK  # noqa: F821
except NameError:
    REST_FRAMEWORK = {}


for key, value in vars(_dab_default_settings.general).items():
    if key in locals():
        continue
    locals()[key] = value


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

    middleware_classes = [
        'ansible_base.authentication.middleware.SocialExceptionHandlerMiddleware',
        'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware',
    ]
    for mw in middleware_classes:
        try:
            MIDDLEWARE  # noqa: F821
            if mw not in MIDDLEWARE:  # noqa: F821
                try:
                    index = MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware')  # noqa: F821
                    MIDDLEWARE.insert(index, mw)  # noqa: F821
                except ValueError:
                    MIDDLEWARE.append(mw)  # noqa: F821
        except NameError:
            MIDDLEWARE = [mw]

    drf_authentication_class = 'ansible_base.authentication.session.SessionAuthentication'
    if 'DEFAULT_AUTHENTICATION_CLASSES' not in REST_FRAMEWORK:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = []  # noqa: F821
    if drf_authentication_class not in REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, drf_authentication_class)  # noqa: F821

    for key, value in vars(_dab_default_settings.authentication).items():
        if key in locals():
            continue
        locals()[key] = value


if 'ansible_base.rest_pagination' in INSTALLED_APPS:
    REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] = 'ansible_base.rest_pagination.DefaultPaginator'


if 'ansible_base.jwt_consumer' in INSTALLED_APPS:
    if 'ansible_base.rbac' not in INSTALLED_APPS:
        INSTALLED_APPS.append('ansible_base.rbac')
    ANSIBLE_BASE_JWT_MANAGED_ROLES = ["Platform Auditor", "Organization Admin", "Organization Member", "Team Admin", "Team Member"]

if 'ansible_base.rbac' in INSTALLED_APPS:
    for key, value in vars(_dab_default_settings.rbac).items():
        if key in locals():
            continue
        locals()[key] = value


if 'ansible_base.oauth2_provider' in INSTALLED_APPS:  # noqa: F821
    if 'oauth2_provider' not in INSTALLED_APPS:  # noqa: F821
        INSTALLED_APPS.append('oauth2_provider')  # noqa: F821

    # Process dictionary settings here
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
    if 'PKCE_REQUIRED' not in OAUTH2_PROVIDER:
        # For compat with awx, we don't require PKCE, but the new version
        # of DOT that we are using requires it by default.
        OAUTH2_PROVIDER['PKCE_REQUIRED'] = False

    OAUTH2_PROVIDER['APPLICATION_MODEL'] = 'dab_oauth2_provider.OAuth2Application'
    OAUTH2_PROVIDER['ACCESS_TOKEN_MODEL'] = 'dab_oauth2_provider.OAuth2AccessToken'

    oauth2_authentication_class = 'ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication'
    if 'DEFAULT_AUTHENTICATION_CLASSES' not in REST_FRAMEWORK:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = []  # noqa: F821
    if oauth2_authentication_class not in REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, oauth2_authentication_class)  # noqa: F821

    # Process non dictionary settings
    for key, value in vars(_dab_default_settings.oauth2_provider).items():
        if key in locals():
            continue
        locals()[key] = value

del _dab_default_settings
