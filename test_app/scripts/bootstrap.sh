#!/usr/bin/env bash

set -e

# Always make sure we kill the database when we exit
function cleanup {
    echo "***"
    echo "This will delete all data in the test_app database (container)"
    echo "Press:"
    echo " - Ctrl-C to cancel and leave the database running (container: dab_postgres)"
    echo " - Enter to continue shutdown and delete the database"
    echo "***"
    read
    make stop-postgres
}

trap cleanup EXIT

docker_running=$(docker ps -aq -f name=dab_postgres)
migrate_needed=1

if [[ -z "${docker_running// /}" ]]
then
    echo "creating new postgres container"
    make postgres
else
    echo "dab_postgres container is already running, will use that container"
    migrate_needed=$(echo $(python manage.py migrate --check > /dev/null 2> /dev/null; echo $?))
fi

MAX_ATTEMPTS=10

for i in $(seq 1 $MAX_ATTEMPTS); do
    echo "Waiting for database to come up ($i/$MAX_ATTEMPTS)"
    if python3 manage.py shell -c 'import django; django.db.connection.ensure_connection()' > /dev/null 2>&1; then
        break
    elif [ $i -eq $MAX_ATTEMPTS ]; then
        echo "Database never came up"
        exit 1
    fi
    sleep 1
done

if [ "${migrate_needed}" -ne 0 ]
then
    echo "Migrating database"
    python3 manage.py migrate
    DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid python3 manage.py createsuperuser --noinput
    python3 manage.py authenticators --initialize
    python3 manage.py create_demo_data
fi

python3 manage.py runserver
