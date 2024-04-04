#!/bin/bash

set -e
set -x

PIP=/venv/bin/pip
PYTHON=/venv/bin/python3

echo "settings.DATABASE ..."
$PYTHON manage.py shell -c 'from django.conf import settings; print(settings.DATABASES)'

MAX_ATTEMPTS=10
for i in $(seq 1 $MAX_ATTEMPTS); do
    echo "Waiting for database to come up ($i/$MAX_ATTEMPTS)"
    if $PYTHON manage.py shell -c 'import django; django.db.connection.ensure_connection()' > /dev/null 2>&1; then
        break
    elif [ $i -eq $MAX_ATTEMPTS ]; then
        echo "Database never came up"
        exit 1
    fi
    sleep 1
done

$PYTHON manage.py migrate
set +e
DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid $PYTHON manage.py createsuperuser --noinput
set -e
$PYTHON manage.py authenticators --initialize
$PYTHON manage.py create_demo_data
$PYTHON manage.py runserver 0.0.0.0:8000
