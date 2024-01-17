import os

from split_settings.tools import include

DEBUG = True

# noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "test_app/tests/sqllite_dbs/db.sqlite3",
        "TEST": {
            "NAME": "test_app/tests/sqllite_dbs/db_test.sqlite3",
        },
    }
}

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
    },
}
for logger in LOGGING["loggers"]:  # noqa: F405
    LOGGING["loggers"][logger]["level"] = "ERROR"  # noqa: F405

SECRET_KEY = "asdf1234"

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
    'test_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'crum.CurrentRequestUserMiddleware',
]

ROOT_URLCONF = 'test_app.urls'

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

ANSIBLE_BASE_TEAM_MODEL = 'test_app.Team'
ANSIBLE_BASE_ORGANIZATION_MODEL = 'test_app.Organization'

STATIC_URL = '/static/'

AUTH_USER_MODEL = 'auth.User'

ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ['ansible_base.authentication.authenticator_plugins']

from ansible_base.lib import dynamic_config  # noqa: E402

settings_file = os.path.join(os.path.dirname(dynamic_config.__file__), 'dynamic_settings.py')
include(settings_file)
