#!/bin/bash

set -e
set -x

PIP=/venv/bin/pip
PYTHON=/venv/bin/python3
DYNACONF=/venv/bin/dynaconf

$PIP install uwsgi

echo "settings.DATABASE ..."
$PYTHON manage.py shell -c 'from django.conf import settings; print(settings.DATABASES)'

echo "DAB overridden settings ..."
$DYNACONF -i test_app.settings.DYNACONF list -k ANSIBLE_BASE_OVERRIDDEN_SETTINGS --json

echo "Read the custom settings file data just as a test"
$DYNACONF -i test_app.settings.DYNACONF inspect -k JUST_A_TEST

$PYTHON manage.py migrate
DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid $PYTHON manage.py createsuperuser --noinput || true
$PYTHON manage.py authenticators --initialize
$PYTHON manage.py create_demo_data

# $PYTHON manage.py runserver 0.0.0.0:8000
cd /src
PYTHONPATH=. /venv/bin/uwsgi --ini test_app/uwsgi.ini
