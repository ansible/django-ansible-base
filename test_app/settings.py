import os
import sys

from split_settings.tools import include

DEBUG = True

if "pytest" in sys.modules:
    # https://github.com/agronholm/typeguard/issues/260
    # Enable runtime type checking only for running tests
    # must be done here because python hooks will not reliably call the
    # typguard plugin setup before other plugins which setup Django, which loads settings.
    # Lower in this settings file, the dynamic config imports ansible_base
    from typeguard import install_import_hook

    install_import_hook(packages=["ansible_base"])

ALLOWED_HOSTS = ["*"]

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)-8s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {
            '()': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'ansible_base': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
        '': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}
for logger in LOGGING["loggers"]:  # noqa: F405
    # We want to ensure that all loggers are at DEBUG because we have tests which validate log messages
    LOGGING["loggers"][logger]["level"] = "DEBUG"  # noqa: F405

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'social_django',
    'ansible_base.api_documentation',
    'ansible_base.authentication',
    'ansible_base.rest_filters',
    'ansible_base.jwt_consumer',
    'ansible_base.resource_registry',
    'ansible_base.rest_pagination',
    'ansible_base.rbac',
    'ansible_base.oauth2_provider',
    'test_app',
    'django_extensions',
    'debug_toolbar',
    'ansible_base.activitystream',
]

MIDDLEWARE = [
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'crum.CurrentRequestUserMiddleware',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['test_app.authentication.logged_basic_auth.LoggedBasicAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", 55432),
        "USER": os.getenv("DB_USER", "dab"),
        "PASSWORD": os.getenv("DB_PASSWORD", "dabing"),
        "NAME": os.getenv("DB_NAME", "dab_db"),
    }
}

AUTH_USER_MODEL = 'test_app.User'

ROOT_URLCONF = 'test_app.urls'

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, 'test_app', 'templates')],
        "APP_DIRS": True,
        "OPTIONS": {
            'context_processors': [
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.request',
            ]
        },
    },
]

INTERNAL_IPS = [
    "127.0.0.1",
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

DEMO_DATA_COUNTS = {'organization': 150, 'user': 379, 'team': 43}

ANSIBLE_BASE_TEAM_MODEL = 'test_app.Team'
ANSIBLE_BASE_ORGANIZATION_MODEL = 'test_app.Organization'

STATIC_URL = '/static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SECRET_KEY = "asdf1234"

ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ['ansible_base.authentication.authenticator_plugins']

from ansible_base.lib import dynamic_config  # noqa: E402

settings_file = os.path.join(os.path.dirname(dynamic_config.__file__), 'dynamic_settings.py')
include(settings_file)

ANSIBLE_BASE_RESOURCE_CONFIG_MODULE = "test_app.resource_api"

SYSTEM_USERNAME = '_system'

ANSIBLE_BASE_ROLE_PRECREATE = {}  # tested in individual tests
ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = True
ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES = True

ANSIBLE_BASE_USER_VIEWSET = 'test_app.views.UserViewSet'

LOGIN_URL = "/login/login"
