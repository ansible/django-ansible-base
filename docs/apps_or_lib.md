# django-ansible-base Features
django-ansible-base provides features as combination of django applications and python libraries.

All top level folders in ansible_base are django applications for features except for the lib folder.

## Determining if a new feature should be an app or a lib

To determine if a feature should be a library or a django-application please consider the following criteria.

If any of the following are true, you should create your new feature as a django app:
1) Does the feature require models
2) Does the feature require urls
3) Does the feature provide management commands
4) Does the feature require settings

If all of these are false, your feature should be a library under the `libs` folder.

## Initializing a new application

### Selecting a name

Please try to choose a concise descriptive name that is not an overloaded term.

For example, we chose `rest_filters` instead of using a generic term like `filters`.

### Initializing an application

To have django initialize your application run the following commands:

```
cd ansible_base
python ../manage.py startapp <app name>
```

This will automatically create a folder and files for you with the name of your application in ansible_base.

You can leave the `__init__.py` and the `migrations` folder alone.

If you are adding models and want them to show up in the test_app default admin pages you can add them to `admin.py`, otherwise, this file should be deleted.

In the `apps.py` file be sure to change the `name` of the application to be prefixed with `ansible_base.`. For example, if your called your app `testing` the generated line would be:

```
name = 'testing'
```

But we need to change it to:
```
name = 'ansible_base.testing'
```

Additionally, add a label field that looks like `dab_<app name>`. So if your app name was `authentication` you class would default to:
```
class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.authentication'
```

And we want to add a label like:
```
class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.authentication'
    label = 'dab_authentication'
```

Additionally, if you want the admin pages to render a different section title for your models you can add a `verbose_name` like:
```
class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.authentication'
    label = 'dab_authentication'
    verbose_name = 'Pluggable Authentication'
```


If you plan to have models you can either add them to `models.py` or, if you have multiple you can remove `models.py` and create a `models` folder (be sure to add an `__init__.py` into the models folder). If you don't plan to have models `models.py` can be deleted.

You can remove `tests.py` as we don't put tests in ansible_base. Additionally, you should create a folder matching your application name in `test_app/tests` and put all of your test files in there.

If you have views you can add them to `views.py` or, like models, remove `views.py` and create a `views` folder. If you don't plan to have views `views.py` can be deleted.

Finally, if your application will add endpoints to the API be sure to add `urls.py`. You can define three different types of urls in this file:
 * `api_version_urls`: These are intended to be on an endpoint like /api/<some name>/v1/. Most URLs should be added here.
 * `api_urls`: These are intended to be on an endpoint like /api/<some name>. An example of this its swaggers docs endpoint or social-auths social.
 * `root_urls`: These are intended to be mounted on /. An example of this is OAuths /o endpoint.

These will all be loaded through the dynamic url loader.

In your urls.py be sure to include lines like:
```
from ansible_base.<app_name>.apps import <app class>
app_name = <app class>.label
```

