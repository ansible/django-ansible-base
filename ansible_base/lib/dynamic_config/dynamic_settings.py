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


if 'ansible_base.rest_filters' in INSTALLED_APPS:
    REST_FRAMEWORK.update(
        {
            'DEFAULT_FILTER_BACKENDS': (
                'ansible_base.rest_filters.rest_framework.type_filter_backend.TypeFilterBackend',
                'ansible_base.rest_filters.rest_framework.field_lookup_backend.FieldLookupBackend',
                'rest_framework.filters.SearchFilter',
                'ansible_base.rest_filters.rest_framework.order_backend.OrderByBackend',
            )
        }
    )


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


# Load settings from any .py files in the global conf.d directory specified in
# the environment, defaulting to /etc/ansible_base/gcconf.d/.
import os
from split_settings.tools import optional, include

settings_dir = os.environ.get('ANSIBLE_BASE_SETTINGS_DIR', '/etc/ansible_base/conf.d/')
settings_files = os.path.join(settings_dir, '*.py')

# Load remaining settings from the global settings file specified in the
# environment, defaulting to /etc/ansible_base/gcsettings.py.
settings_file = os.environ.get('ANSIBLE_BASE_SETTINGS_FILE', '/etc/ansible_base/settings.py')

# Attempt to load settings from /etc/ansible_base/settings.py first, followed by
# /etc/ansible_base/conf.d/*.py.
try:
    include(settings_file, optional(settings_files), scope=locals())
except ImportError:
    traceback.print_exc()
    sys.exit(1)
except IOError:
    from django.core.exceptions import ImproperlyConfigured

    included_file = locals().get('__included_file__', '')
    if not included_file or included_file == settings_file:
        # The import doesn't always give permission denied, so try to open the
        # settings file directly.
        try:
            e = None
            open(settings_file)
        except IOError:
            pass
        if e and e.errno == errno.EACCES:
            SECRET_KEY = 'permission-denied'
            LOGGING = {}
        else:
            msg = 'No Configuration found at %s.' % settings_file
            msg += '\nDefine the ANSIBLE_BASE_SETTINGS_FILE environment variable to '
            msg += 'specify an alternate path.'
            raise ImproperlyConfigured(msg)
    else:
        raise
