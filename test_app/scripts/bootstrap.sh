
rm -rf test_app/tests/sqllite_dbs/*.sqlite3

python manage.py migrate

DJANGO_SUPERUSER_PASSWORD=password DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@stuff.invalid python manage.py createsuperuser --noinput

python manage.py authenticators --initialize

python manage.py create_demo_data

python manage.py runserver
