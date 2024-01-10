import os

from split_settings.tools import include

# noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "ansible_base/tests/db.sqlite3",
        "TEST": {
            "NAME": "ansible_base/tests/db_test.sqlite3",
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
    'ansible_base',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    # must come before django.contrib.auth.middleware.AuthenticationMiddleware
    'ansible_base.utils.middleware.AuthenticatorBackendMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'crum.CurrentRequestUserMiddleware',
]

ROOT_URLCONF = 'ansible_base.tests.urls'

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

AUTHENTICATION_BACKENDS = [
    "ansible_base.authentication.backend.AnsibleBaseAuth",
]

ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ['ansible_base.authenticator_plugins']

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

from ansible_base import settings  # noqa: E402

settings_file = os.path.join(os.path.dirname(settings.__file__), 'dynamic_settings.py')
include(settings_file)
