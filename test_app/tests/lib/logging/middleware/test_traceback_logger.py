from unittest import TestCase, mock

from django.http import HttpRequest

from ansible_base.lib.middleware.logging.log_request import LogTracebackMiddleware


class TestLogTracebackMiddleware(TestCase):
    def test_log_traceback_middleware(self):
        get_response = mock.MagicMock()
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test"

        middleware = LogTracebackMiddleware(get_response)
        response = middleware(request)

        # ensure get_response has been returned
        self.assertEqual(get_response.return_value, response)

        # mock handling signal while there is a request in transactions stored
        middleware.transactions = {"foobarid": request}
        middleware.handle_signal()
