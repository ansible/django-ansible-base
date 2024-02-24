import os

from test_app.settings import *  # noqa

# noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", 5432),
        "USER": os.getenv("DB_USER", "dab"),
        "PASSWORD": os.getenv("DB_PASSWORD", "dabing"),
        "NAME": os.getenv("DB_NAME", "dab_db"),
    }
}
