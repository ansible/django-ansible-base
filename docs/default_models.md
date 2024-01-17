# Common Models

django-ansible-base can house common models available to all ansible django apps.

Models include:


`ansible_base.common.models.common.CommonModel` This model has built in fields for created/modified tracking. It also has provisions for setting up related and summary fields from the models themselves. Related fields are auto-discovered through foreign keys. Summary fields starts here with just `id`.

`ansible_base.common.models.common.NamedCommonModel` Extends CommonModel with a unique name and appends the `name` to the summary fields.


If you are using either of these models as a base class you can use their cooresponding default serializers as well:
`ansible_base.common.serializers.common.CommonModelSerializer` or `ansible_base.common.serializers.common.NamedCommonModelSerializer`
