# AnsibleBaseView

django-ansible-base provides a view called `ansible_base.lib.utils.views.AnsibleBaseView` which is indirectly parent class for all views in django-ansible-base.

This view itself is subclassed from `rest_framework.views.APIView` and is intended to be subclassed from individual services like:

```
from rest_framework.viewsets import ModelViewSet
from ansible_base.lib.utils.views import AnsibleBaseView

class MyServiceBaseApiView(AnsibleBaseView):
    pass

class MyServiceModelViewSet(ModelViewSet, MyServiceBaseApiView):
    pass
```

## Changing the parent view

All views in django-ansible-base actually inherit from a class called `ansible_base.lib.utils.views.AnsibleBaseDjanoAppApiView` which inherits, by default from `AnsibleBaseView`.

However, if you already have an existing parent view with additional features you can override the view that `AnsibleBaseDjangoAppApiView` inherits from by setting the django setting `ANSIBLE_BASE_CUSTOM_VIEW_PARENT`.

For example, lets say you had a class like `my_app.views.DefaultAPIView` like:
```
from rest_framework.views import APIView

class DefaultAPIView(APIView):
    ...
    all my good stuff
    ...
```

And lets say all of your django views already inherit from this view. To make the django views in django-ansible-base inherit from this view simply add this to your settings:
```
ANSIBLE_BASE_CUSTOM_VIEW_PARENT = 'my_app.views.DefaultAPIView'
```

This will force `AnsibleBaseDjangoAppApiView` to inherit from `my_app.views.DefaultAPIView` instead of `ansible_base.lib.utils.views.AnsibleBaseView`.

If you want the goodness from `AnsibleBaseView` alongside your custom you, you can also make your custom view inherit from `ansible_base.lib.utils.views.AnsibleBaseView` like:
```
from ansible_base.lib.utils.views import AnsibleBaseView
from rest_framework.views import APIView

class DefaultAPIView(AnsibleBaseView):
    ...
    all my good stuff
    ...
```
