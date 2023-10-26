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
