# Installation

Currently we install django-ansible-base via a pip install from the repository:
```
pip install git+https://github.com/ansible/django-ansible-base.git
```

This will install django-ansible-base as well as all its dependencies.
Dependencies can be found in `requirements/requirements.in`

Once the library is installed you will need to add it to your installed apps in settings.py:
```
INSTALLED_APPS = [
    ...
    'ansible_base',
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
