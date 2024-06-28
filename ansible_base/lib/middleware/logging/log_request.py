import logging

from ansible_base.lib.logging import thread_local

logger = logging.getLogger(__name__)


class LogRequestMiddleware:
    """
    Inject the request into the thread local so that it can be accessed by the logging filter.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self.process_request(request)
        response = self.get_response(request)
        self.process_response(request, response)
        return response

    def process_request(self, request):
        thread_local.request = request
        return None

    def process_response(self, request, response):
        thread_local.request = None
        return response
