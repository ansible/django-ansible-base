#!/usr/bin/env bash

#
# Copyright 2024 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

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
    python manage.py migrate --check; migrate_needed=$?
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
    python3 manage.py migrate
    DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid python3 manage.py createsuperuser --noinput
    python3 manage.py authenticators --initialize
    python3 manage.py create_demo_data
fi

python3 manage.py runserver
