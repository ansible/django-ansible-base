# ViewWithHeaders

django-ansible-base provides a view `ansible_base.lib.utils.views.ViewWithHeaders` that is of type `rest_framework.views.APIView`. This view will look for the setting `ANSIBLE_BASE_EXTRA_HEADERS` which is a dict of key/value pairs (both strings). The view will inject headers in the format of `key: value` into the response.

The view can be subclassed by any view created to inject default headers.
