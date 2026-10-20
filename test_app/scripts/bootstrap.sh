#!/usr/bin/env bash

set -e

# Detect database backend from environment (default: postgres)
# Part of ANSTRAT-1887: MS SQL Server Database Support - Technology Preview
DB_BACKEND=${DB_BACKEND:-postgres}

# Set appropriate variables based on backend
if [[ "$DB_BACKEND" == "mssql" ]]; then
    CONTAINER_NAME="dab_mssql"
    MAKE_START_TARGET="mssql"
    MAKE_STOP_TARGET="stop-mssql"
    export DJANGO_SETTINGS_MODULE="test_app.mssqlsettings"
    echo "=== Using MS SQL Server backend (ANSTRAT-1887) ==="
else
    CONTAINER_NAME="dab_postgres"
    MAKE_START_TARGET="postgres"
    MAKE_STOP_TARGET="stop-postgres"
    export DJANGO_SETTINGS_MODULE="test_app.settings"
    echo "=== Using PostgreSQL backend (default) ==="
fi

# Always make sure we kill the database when we exit
function cleanup {
    echo "***"
    echo "This will delete all data in the test_app database (container: $CONTAINER_NAME)"
    echo "Press:"
    echo " - Ctrl-C to cancel and leave the database running"
    echo " - Enter to continue shutdown and delete the database"
    echo "***"
    read
    make $MAKE_STOP_TARGET
}

trap cleanup EXIT

docker_running=$(docker ps -aq -f name=$CONTAINER_NAME)
migrate_needed=1

if [[ -z "${docker_running// /}" ]]
then
    echo "Creating new $DB_BACKEND container: $CONTAINER_NAME"
    make $MAKE_START_TARGET
else
    echo "$CONTAINER_NAME container is already running, will use that container"
    set +e
    python manage.py migrate --check; migrate_needed=$?
    set -e
fi

MAX_ATTEMPTS=10

for i in $(seq 1 $MAX_ATTEMPTS); do
    echo "Waiting for database to come up ($i/$MAX_ATTEMPTS)"
    if python3 manage.py shell -c 'import django; django.db.connection.ensure_connection()' > /dev/null 2>&1; then
        break
    elif [[ $i -eq $MAX_ATTEMPTS ]]; then
        echo "Database never came up"
        exit 1
    fi
    sleep 1
done

admin_password='admin'

if [[ "${migrate_needed}" -ne 0 ]]
then
    echo "Migrating database using ${DJANGO_SETTINGS_MODULE}"
    python3 manage.py migrate
    if [[ "${DJANGO_SUPERUSER_PASSWORD}" ]]; then
        admin_password=${DJANGO_SUPERUSER_PASSWORD}
    fi
    DJANGO_SUPERUSER_PASSWORD=$admin_password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid python3 manage.py createsuperuser --noinput
    python3 manage.py authenticators --initialize
    python3 manage.py create_demo_data
fi

python3 manage.py runserver
