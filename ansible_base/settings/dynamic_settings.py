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
    ANSIBLE_BASE_FEATURES  # noqa: F821
except NameError:
    ANSIBLE_BASE_FEATURES = {}

try:
    INSTALLED_APPS  # noqa: F821
except NameError:
    INSTALLED_APPS = []


if ANSIBLE_BASE_FEATURES.get('SWAGGER', False):  # noqa: F821
    if 'drf_spectacular' not in INSTALLED_APPS:  # noqa: F821
        INSTALLED_APPS.append('drf_spectacular')  # noqa: F821


if ANSIBLE_BASE_FEATURES.get('FILTERING', False):  # noqa: F821
    REST_FRAMEWORK.update(  # noqa: F821
        {
            'DEFAULT_FILTER_BACKENDS': (
                'ansible_base.filters.rest_framework.type_filter_backend.TypeFilterBackend',
                'ansible_base.filters.rest_framework.field_lookup_backend.FieldLookupBackend',
                'rest_framework.filters.SearchFilter',
                'ansible_base.filters.rest_framework.order_backend.OrderByBackend',
            )
        }
    )


if 'ansible_base.authentication' in INSTALLED_APPS:
    try:
        AUTHENTICATION_BACKENDS  # noqa: F821
    except NameError:
        AUTHENTICATION_BACKENDS = ["ansible_base.authentication.backend.AnsibleBaseAuth"]

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

    try:
        REST_FRAMEWORK  # noqa: F821
    except NameError:
        REST_FRAMEWORK = {}

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
