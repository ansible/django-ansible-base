# test_app

This is a simple testing application for django-ansible-base and being able to run manage commands against django-ansible-base.
The manage.py at the root of django-ansible-base is configured to work with test_app.
Therefore we can run any manage.py command directly from the root folder.


# Setting up an environment

If you are attempting to start test_app for the first time in a fresh environment you will first need a python virtual environment configured to run test_app. Create and activate a python 3 virtual environment using any method you like and then run the following command from the root of your django-ansible-base checkout:

```
pip install -r requirements/requirements_all.txt
```

# Initialize the test app

## Initialize the database
test_app uses a sqllite database as its backend but we first need to initialize that database. From the root of your django-ansible-base checkout run the command:

```
python manage.py migrate
```

This will apply a handful of migrations to a sql lite database. The files behind the sqllite database are stored in `test_app/tests/sqllite_dbs`. If you ever want to reset your database or are having issues with the database you can remove these files and test_app will create a fresh database.

## Create an admin user
Once our database is initialized we need to create an admin user for ourselves. To do this run the command:

```
python manage.py createsuperuser
```

Follow the prompts to create the user:

NOTE: you must name the user admin but you can use any email or password you'd like.

```
$ python manage.py createsuperuser
Username (leave blank to use 'local_user'): admin
Email address: admin@nowhere.com
Password: 
Password (again): 
Superuser created successfully.
```


## Create a local authenticator
test_app uses django-ansible-base authentication in order to be able to authenticate so we first need to initialize a local authenticator. To do this run the command:

```
python manage.py authenticators --initialize
```

## Starting the server

Now that we have performed the initialization steps we are ready to run the test_app server. To do this, run the command:

```
python manage.py runserver
```

This should yield the results:
```
Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
January 17, 2024 - 07:58:24
Django version 4.2.6, using settings 'test_app.settings'
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.


```


You should now be able to point your browser to the URL specified in the output. However, we do not run a web ui in this application so hitting the root url will yield a django debug page.

If you want to hit the django-ansible-base API you can go to the endpoint `/app/v1` or if you would like to manage and create objects in the default django admin site you can go to `/admin`.

## Logging into the server

Most pages served from django-ansible-base are protected and require login. To log in go to the /admin page and use the username/password created in the `Create admin user` section to authenticate. Once authenticated you can go back to `/api/v1/<end point>/` and you will have a session as the admin user to use the API.


# Creating migrations for a django-ansible-base application

If you add or modify an application in django-ansible-base and want to create migrations for it can run the following command:

```
python manage.py makemigrations <app name>
```

For example, if you needed to make migrations for the test_app itself you could run:

```
python manage.py makemigrations test_app
```
