# Common Models

django-ansible-base can house common models available to all ansible django apps.

Models include:


`ansible_base.lib.abstract_models.common.CommonModel` This model has built in fields for created/modified tracking. It also has provisions for setting up related and summary fields from the models themselves. Related fields are auto-discovered through foreign keys. Summary fields starts here with just `id`.

`ansible_base.lib.abstract_models.common.NamedCommonModel` Extends CommonModel with a unique name and appends the `name` to the summary fields.


If you are using either of these models as a base class you can use their corresponding default serializers as well:
`ansible_base.lib.serializers.common.CommonModelSerializer` or `ansible_base.lib.serializers.common.NamedCommonModelSerializer`
