# Installation

Currently we install django-ansible-base via a pip install from the repository:
```
pip install git+https://github.com/ansible/django-ansible-base.git[all]
```

This will install django-ansible-base as well as all its optional dependencies.
These can be found in `requirements/requirements_all.in`

If there are features you are not going to use you can tell pip to only install required packages for the features you will use.
As of this writing there are three features:
  * authentication
  * swagger
  * filtering

So if you only wanted api_docs and filtering you could install the library like:
```
pip install git+https://github.com/ansible/django-ansible-base.git[api_docs,filtering]
```

# Configuration
Once the library is installed you will need to add it to your installed apps in settings.py:
```
INSTALLED_APPS = [
    ...
    'ansible_base',
]
```

Some features in django-ansible-base are also applications that need to be added to installed_apps.
For example, if you want to use authentication you would need to add it like:
```
INSTALLED_APPS = [
    ...
    'ansible_base',
    'ansible_base.authentication',
]
```

Next we can turn on various feature of django-ansible base in your settings file:
```
ANSIBLE_BASE_FEATURES = {
    'AUTHENTICATION': True,
    'FILTERING': False
}
```

Finally, we can let django-ansible-base add the settings it needs to function:
```
from ansible_base import settings
settings_file = os.path.join(os.path.dirname(settings.__file__), 'dynamic_settings.py')
include(settings_file)
```

Please read the various sections of this documentation for what django-ansible-base will do to your settings.
