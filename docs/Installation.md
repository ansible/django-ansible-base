# Installation

Currently we install django-ansible-base via a pip install from the git repository.

If you want the devel version you can simply install from the repo:
```
pip install git+https://github.com/ansible/django-ansible-base.git[all]
```

This will install django-ansible-base as well as all its optional dependencies.
These can be found in `requirements/requirements_all.in`

If there are features you are not going to use you can tell pip to only install required packages for the features you will use.
As of this writing there are three django application features:
  * api_documentation
  * authentication
  * rest_filters
  * resource_registry

So if you only wanted api_docs and filtering you could install the library like:
```
pip install git+https://github.com/ansible/django-ansible-base.git[api_documentation,rest_filters]
```

## Pinning versions

If you are using django-ansible-base from another project you will likely want to install a specific version from one of the github releases.
There is a small caveat when doing this.

If you install from the tag like:
```
pip install git+https://github.com/ansible/django-ansible-base@2024.01.27#egg=django-ansible-base[all]
```
It will be a fixed version of django-ansible-base but it will not have a locked __version__ attribute and will appear like a devel version with the current data:
```
python -c "import ansible_base; print(ansible_base.__version__)"
2024.01.31-83d3eb1
```

However, if you install form a tar.gz in a release like:
```
pip install https://github.com/ansible/django-ansible-base/releases/download/2024.01.27/django-ansible-base-2024.1.27.tar.gz[all]
```

Than the version will be locked:
```
python -c "import ansible_base; print(ansible_base.__version__)"
2024.01.26
```


# Configuration

## INSTALLED_APPS
For any django app features you will need to add them to your `INSTALLED_APPS` like:
```
INSTALLED_APPS = [
    'ansible_base.rest_filters',
]
```

The final component of the import path (what is listed in INSTALLED_APPS) is not the
same as the app label which is what is sometimes referenced programmatically
using `from django.apps import apps`.

The pip optional dependencies as the same as the app label without "dab_".
See the following table for a mapping.

| App path                       | Django app label      | Pip optional dependency |
|--------------------------------|-----------------------|-------------------------|
| ansible_base.authentication    | dab_authentication    | authentication          |
| ansible_base.api_documentation | dab_api_documentation | api_documentation       |
| ansible_base.rest_filters      | dab_rest_filters      | rest_filters            |
| ansible_base.resource_registry | dab_resource_registry | resource_registry       |

## settings.py

Please read the various sections of this documentation for what settings django-ansible-base requires to function.

As a convenience, we can let django-ansible-base automatically add the settings it needs to function:
```
from ansible_base.lib import dynamic_config
dab_settings = os.path.join(os.path.dirname(dynamic_config.__file__), 'dynamic_settings.py')
include(dab_settings)
```

## urls.py

Please read the various sections of this documentation for what urls django-ansible-base will need for your application to function.

As a convenience, we can let django-ansible-base automatically add the urls it needs to function:
```
from ansible_base.lib.dynamic_config.dynamic_urls import api_version_urls, root_urls, api_urls

urlpatterns = [
    path('api/<your api name>/<your api version>/', include(api_version_urls)),
    path('api/<your api name>/', include(api_urls)),
    path('', include(root_urls)),
]
```

This will not set up views for the user model, which is expected to be done by your application.
However, serializers will link your own user detail view when applicable, assuming the view name "user-detail" exists.
See the test_app/ folder if you need an example setup.
