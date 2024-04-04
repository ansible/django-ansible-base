#!/bin/bash

set -e
set -x

sed -i '/^\[crb\]$/,/^enabled=0$/ s/enabled=0/enabled=1/' /etc/yum.repos.d/centos.repo
dnf -y install \
    python3.11 python3.11-pip python3.11-devel gcc openldap-devel \
    xmlsec1 xmlsec1-openssl xmlsec1-devel libtool-ltdl-devel libpq-devel libpq postgresql
if [[ ! -d /venv ]]; then
    python3.11 -m venv /venv
fi

PIP=/venv/bin/pip
PYTHON=/venv/bin/python3

$PIP install -r requirements/requirements_all.txt
$PIP install -r requirements/requirements_dev.txt

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
