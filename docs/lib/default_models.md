# Common Models

django-ansible-base can house common models available to all ansible django apps.

Models include:


`ansible_base.lib.abstract_models.common.CommonModel` This model has built in fields for created/modified tracking. It also has provisions for setting up related and summary fields from the models themselves. Related fields are auto-discovered through foreign keys. Summary fields starts here with just `id`.

`ansible_base.lib.abstract_models.common.NamedCommonModel` Extends CommonModel with a unique name and appends the `name` to the summary fields.


If you are using either of these models as a base class you can use their corresponding default serializers as well:
`ansible_base.lib.serializers.common.CommonModelSerializer` or `ansible_base.lib.serializers.common.NamedCommonModelSerializer`

## Managing Related Links

The common serializers expect certain things from your models in order to reduce code
needed to populate standard patterns in the returned API data. In particular:

 - "url" - the URL of the object itself
 - "related" - links to related objects
 - "summary_fields" - details of related objects

Doing this without lots of redundancy requires standardization of _view names_.

### Model URLs

Say that you have a model with a multi-word name like MyModel.
 - If you registered a custom model name, then add `router_basename` to the model
 - An instance method `get_absolute_url` can be used, but this is deprecated
 - Serializers default to assuming a view name like "mymodel-detail" exists

To clarify, you can make a model like

```python
class MyModel(models.Model):
    router_basename = 'my_model'  # not standard
```

Would correspond to routers

```python
router.register(r'my_models', views.MyModelViewSet, basename='my_model')
```

These information sources are used to populate "url" in the common serializer.

### ForeignKeys

If your model has a ForeignKey to another model, then the same logic used for
the "url" field is use to put an entry in "related". The key in the related
dictionary is the field name.

### Many-to-Many and One-to-Many/reverse ForeignKey

These relations are automatically handled by the Association Router.
See its documentation in routers.md.
