from rest_framework.pagination import CursorPagination


class ServiceCursorPagination(CursorPagination):
    page_size = 50
    ordering = 'id'
    page_size_query_param = 'page_size'
    max_page_size = 1000
