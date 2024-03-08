import logging

from django.core.paginator import Paginator as DjangoPaginator
from rest_framework import pagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from ansible_base.lib.utils.settings import get_setting

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGE_SIZE = 200

logger = logging.getLogger('ansible_base.rest_pagination.default_paginator')


class DisabledPaginator(DjangoPaginator):
    _NUM_PAGES = 1
    _COUNT = 200

    @property
    def num_pages(self):
        return self._NUM_PAGES

    @property
    def count(self):
        return self._COUNT


class DefaultPaginator(pagination.PageNumberPagination):
    page_size_query_param = 'page_size'
    count_disabled = False

    def get_next_link(self):
        if not self.page.has_next():
            return None
        url = self.request and self.request.get_full_path() or ''
        url = url.encode('utf-8')
        page_number = self.page.next_page_number()
        return replace_query_param(self.cap_page_size(url), self.page_query_param, page_number)

    def get_previous_link(self):
        if not self.page.has_previous():
            return None
        url = self.request and self.request.get_full_path() or ''
        url = url.encode('utf-8')
        page_number = self.page.previous_page_number()
        return replace_query_param(self.cap_page_size(url), self.page_query_param, page_number)

    def get_page_size(self, request):
        logger.warning(f'page size is {self._get_appropriate_page_size(super().get_page_size(request))}')
        return self._get_appropriate_page_size(super().get_page_size(request))

    def cap_page_size(self, url):
        '''
        If the user gave us > max_page_size we want to trim it down
        '''
        wanted_query_size = self.request.query_params.get(self.page_size_query_param, 0)
        new_query_size = self._get_appropriate_page_size(wanted_query_size)
        if new_query_size != wanted_query_size:
            url = replace_query_param(url, self.page_size_query_param, new_query_size)
        return url

    def get_html_context(self):
        context = super().get_html_context()
        context['page_links'] = [pl._replace(url=self.cap_page_size(pl.url)) for pl in context['page_links']]

        return context

    def paginate_queryset(self, queryset, request, **kwargs):
        self.count_disabled = 'count_disabled' in request.query_params
        try:
            if self.count_disabled:
                self.django_paginator_class = DisabledPaginator
            return super().paginate_queryset(queryset, request, **kwargs)
        finally:
            self.django_paginator_class = DjangoPaginator

    def get_paginated_response(self, data):
        if self.count_disabled:
            return Response({'results': data})
        return super().get_paginated_response(data)

    def _get_appropriate_page_size(self, page_size):
        '''
        Look at the request page size and change it as needed
        '''

        # Convert page size to an int incase its not
        try:
            page_size = int(page_size)
        except (ValueError, TypeError):
            # ValueError if we get a string like 'a'
            # TypeError if we get None or something else that can't be converted
            page_size = 0

        # if we didn't get a page size or was <1 return the default page size
        if page_size is None or page_size < 1:
            return get_setting('DEFAULT_PAGE_SIZE', DEFAULT_PAGE_SIZE)

        max_page_size = get_setting('MAX_PAGE_SIZE', DEFAULT_MAX_PAGE_SIZE)
        # If we got > the max defined page size trim it down
        if page_size > max_page_size:
            return max_page_size

        return page_size
