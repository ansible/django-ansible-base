#!/bin/bash

set -e
set -x

PIP=/venv/bin/pip
PYTHON=/venv/bin/python3

echo "settings.DATABASE ..."
$PYTHON manage.py shell -c 'from django.conf import settings; print(settings.DATABASES)'

$PYTHON manage.py migrate
set +e
DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid $PYTHON manage.py createsuperuser --noinput
set -e
$PYTHON manage.py authenticators --initialize
$PYTHON manage.py create_demo_data
$PYTHON manage.py runserver 0.0.0.0:8000
