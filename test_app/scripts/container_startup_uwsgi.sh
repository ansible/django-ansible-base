#!/bin/bash

set -e
set -x

PIP=/venv/bin/pip
PYTHON=/venv/bin/python3

$PIP install uwsgi

echo "settings.DATABASE ..."
$PYTHON manage.py shell -c 'from django.conf import settings; print(settings.DATABASES)'

$PYTHON manage.py migrate
DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid $PYTHON manage.py createsuperuser --noinput || true
$PYTHON manage.py authenticators --initialize
$PYTHON manage.py create_demo_data

# $PYTHON manage.py runserver 0.0.0.0:8000
cd /src
PYTHONPATH=. /venv/bin/uwsgi --ini test_app/uwsgi.ini
