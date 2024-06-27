# Data validation

django-ansible-base provides some basic validation tools. These reside in `ansible_base.lib.utils.validation`.
The following items are available from the validation library:

`ansible_base.lib.utils.validation.VALID_STRING` this is a common string which says say:
```
Must be a valid string
```

`ansible_base.lib.utils.validation.validate_url` this is similar to the validate_url in django but has a parameter for `allow_plain_hostname: bool = False` which means you can have a url like `https://something:443/testing`.

`ansible_base.lib.utils.validation.validate_url_list` this is a convince method which takes an array of urls and validates each of them using its own validate_url method.


# Validation callback for role assignment

Apps that utilize django-ansible-base may wish to add extra validation when assigning roles to actors (users or teams).

For this, django-ansible-base will call out to `validate_role_assignment` method that defined on the object that being assigned.

The signature of this callback is

`validate_role_assignment(self, actor, role_definition)`

This method is reponsible for raising the appropriate exception if necessary, for example,

```python
from rest_framework.exceptions import ValidationError
class MyDjangoModel:
    def validate_role_assignment(self, actor, role_definition):
        raise ValidationError({'detail': 'Role assignment not allowed.'})
```

Note, if you want the exception to result in a HTTP 400 or 403 response, you can raise django rest framework exceptions instead of django exceptions.
