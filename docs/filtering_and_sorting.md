# Filtering and Sorting

django-ansible-base has a built in mechanism for filtering and sorting query sets based on django-rest-framework Filters. 

To enable filtering on your rest endpoints edit your settings file and modify `REST_FRAMEWORK` with the following entry:
```
REST_FRAMEWORK = {
    ...
    'DEFAULT_FILTER_BACKENDS': (
        'ansible_base.filters.rest_framework.type_filter_backend.TypeFilterBackend',
        'ansible_base.filters.rest_framework.field_lookup_backend.FieldLookupBackend',
        'rest_framework.filters.SearchFilter',
        'ansible_base.filters.rest_framework.order_backend.OrderByBackend',
    ),
    ...
}
```

## Preventing Field Searching

### prevent_search function

Sensitive fields like passwords should be excluded from being searched. To do there is there a function called `prevent_search` which can wrap your model fields like:

```
from ansible_base.common.utils.models import prevent_search

class Authenticator(UniqueNamedCommonModel):
   ...
   configuration = prevent_search(JSONField(default=dict, help_text="The required configuration for this source"))
   ...
```

If you add fields to prevent searching on its your responsibility to add unit/functional tests to ensure that data is not exposed. Here is an example of a test:
```
@pytest.mark.parametrize(
    'model, query',
    [
        (Authenticator, 'configuration__icontains'),
    ],
)
def test_filter_sensitive_fields_and_relations(model, query):
    field_lookup = FieldLookupBackend()
    with pytest.raises(PermissionDenied) as excinfo:
        field, new_lookup = field_lookup.get_field_from_lookup(model, query)
    assert 'not allowed' in str(excinfo.value)
```

### PASSWORD_FIELDS

Another option available is `PASSWORD_FIELDS` which can explicitly protect password fields on your models like:

```
class MyModel(CommonModel):

    PASSWORD_FIELDS = ['inputs']
```

In this example, the `inputs` field of MyModel would be excluded from being searched.

