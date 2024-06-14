import logging
import threading

_ids = {}


class HTTPIdentifiedLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        _ids[threading.current_thread().ident] = request.headers.get('x_request_id', None)

        response = self.get_response(request)

        active_thread_idents = set([t.ident for t in threading.enumerate()])
        cached_idents = set(_ids.keys())
        for ident_to_delete in cached_idents - active_thread_idents:
            del _ids[ident_to_delete]

        return response


class HttpIdentifiedLogger(logging.LoggerAdapter):
    def __init__(self, logger, extra=None):
        self.http_id = None
        super().__init__(logger, extra)

    def process(self, msg, kwargs):
        if self.http_id is None:
            http_id = _ids.get(threading.current_thread().ident, kwargs.get('extra', {}).get('http_id', "None"))
        else:
            http_id = self.http_id

        return f'[{http_id}] {msg}', kwargs

    def set_http_id(self, new_id):
        self.http_id = new_id


def get_logger(name):
    logger = logging.getLogger(name)
    adapter = HttpIdentifiedLogger(logger)
    return adapter
