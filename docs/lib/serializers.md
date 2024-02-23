# Serializers

django-ansible-base can house common serializer fields. These are in `ansible_base.lib.serializers.fields`.

`ansible_base.lib.serializers.fields.URLField` can handle doing URL validation (see validation.md).



# ValidationSerializerMixin

django-ansible-base offers a `ValidationSerializerMixin` for DRF serializers. This is in `ansible_base.lib.serializers.validation`.

Adding this mixin to your serializers will allow for "validation" of a POST/PUT by returning a HTTP 202 response from the `.save()` method if the passed in object passes validation and could be saved.
Validation is indicated to the serializer by passing a GET parameter of `validate=[True|False]`.
* If unspecified validation will be false.
* If multiple validate params are offered any being True turn on the validation login.

*Note*: if you use the DRF filter class from DAB its already configured to ignore the validate parameters. If you are using your own filtering class you will need to ensure that the filter is not used as part of the lookup model. 
