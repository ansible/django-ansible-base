import logging

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param

from ansible_base.lib.utils.settings import get_setting

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGE_SIZE = 200

logger = logging.getLogger('ansible_base.rest_pagination.default_paginator')


class DefaultPaginator(PageNumberPagination):
    page_size_query_param = 'page_size'

    def __init__(self, *args, **kwargs):
        # Since this class is loaded during settings load we have to get these settings on init instead of as class variables
        self.page_size = get_setting('DEFAULT_PAGE_SIZE', DEFAULT_PAGE_SIZE)
        self.max_page_size = get_setting('MAX_PAGE_SIZE', DEFAULT_MAX_PAGE_SIZE)

    # The default PageNumberPagination wants to deliver an absolute URL instead of a relative one so we override these functions to default to relative URLs
    def get_next_link(self):
        if not self.page.has_next():
            return None
        url = self.request.get_full_path()
        url = url.encode('utf-8')
        page_number = self.page.next_page_number()
        return replace_query_param(url, self.page_query_param, page_number)

    def get_previous_link(self):
        if not self.page.has_previous():
            return None
        url = self.request.get_full_path()
        url = url.encode('utf-8')
        page_number = self.page.previous_page_number()
        if page_number == 1:
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, page_number)

    # We need something to capture the count_disabled parameter from the request
    def paginate_queryset(self, queryset, request, view=None):
        self.count_disabled = 'count_disabled' in request.query_params
        # AWX had optimizations for larger models in here we are starting without
        # https://github.com/ansible/awx/commit/c0d9600b66a8b271e4da9b74d0706c6d40ee62bf#diff-d87f638f22a7a23098410cc35ff29b4d811332b31122a04e8cb4f4d00143aa62R57
        return super().paginate_queryset(queryset, request, view)

    # If the count_disabled was set, do not return the count otherwise take the normal action
    def get_paginated_response(self, data):
        if self.count_disabled:
            return Response({'results': data})

        return super().get_paginated_response(data)
