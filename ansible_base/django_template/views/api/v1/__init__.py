import logging
import re
from collections import OrderedDict

from django.urls import get_resolver
from django.urls.exceptions import NoReverseMatch
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.schemas.generators import EndpointEnumerator

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView

logger = logging.getLogger('aap.templated_app.views')


ignore_endpoints = ['docs', 'login', 'logout']
api_endpoint_re = re.compile('^/api/[^/]*/v1/(?P<endpoint>[^/]+)')


def get_all_endpoints():
    url_patterns = get_resolver().url_patterns
    endpoints = []

    for pattern in url_patterns:
        if hasattr(pattern, 'url_patterns'):
            endpoints.extend(get_all_endpoints_from_pattern(pattern))
        else:
            endpoints.append(pattern.name)

    return endpoints


def get_all_endpoints_from_pattern(pattern):
    endpoints = []
    for subpattern in pattern.url_patterns:
        if hasattr(subpattern, 'url_patterns'):
            endpoints.extend(get_all_endpoints_from_pattern(subpattern))
        else:
            endpoints.append(subpattern.name)
    return endpoints


class V1RootView(AnsibleBaseView):
    permission_classes = (AllowAny,)
    name = _('v1')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        # Get all of the endpoints we want to know about from the URLs in Django
        data = {}
        for endpoint_name in get_all_endpoints():
            try:
                relative_url = get_relative_url(endpoint_name)
            except NoReverseMatch:
                continue

            matches = api_endpoint_re.match(relative_url)
            if matches is None:
                logger.debug(f"Endpoint {relative_url} was not a v1 endpoint, skipping")
                continue

            data[matches.group('endpoint')] = relative_url
        
        sorted_data = OrderedDict()
        for sorted_endpoint in sorted(data.keys()):
            if sorted_endpoint in ignore_endpoints:
                continue

            sorted_data[sorted_endpoint] = data[sorted_endpoint]

        return Response(sorted_data)
