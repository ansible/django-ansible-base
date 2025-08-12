import json
from uuid import UUID, uuid4

from django.http import JsonResponse
from django.test import TestCase, override_settings
from django.urls import path

from ansible_base.lib.logging.context import trace_id_var


# A simple view for testing middleware
def context_view(request):
    return JsonResponse({"trace_id": trace_id_var.get()})


# Define URL patterns for the test
urlpatterns = [
    path('context/', context_view),
]


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        'ansible_base.lib.middleware.request_context._TraceContextMiddleware',
    ],
)
class TraceContextMiddlewareTest(TestCase):
    def test_uses_x_request_id_header(self):
        """
        Test that the middleware uses the X-Request-ID from the request header
        if it is provided.
        """
        self.assertIsNone(trace_id_var.get())
        request_id = str(uuid4())

        response = self.client.get('/context/', HTTP_X_REQUEST_ID=request_id)
        self.assertEqual(response.status_code, 200)

        # The trace_id in the view should match the header
        trace_id = json.loads(response.content).get("trace_id")
        self.assertEqual(trace_id, request_id)

        # After the request, the context should be reset
        self.assertIsNone(trace_id_var.get())

    def test_generates_id_if_header_is_missing(self):
        """
        Test that the middleware generates a new UUID if the X-Request-ID
        header is not provided.
        """
        self.assertIsNone(trace_id_var.get())

        response = self.client.get('/context/')
        self.assertEqual(response.status_code, 200)

        # The trace_id should be a valid UUID
        trace_id = json.loads(response.content).get("trace_id")
        self.assertIsNotNone(trace_id)
        try:
            UUID(trace_id, version=4)
        except ValueError:
            self.fail("trace_id is not a valid UUID4")

        # After the request, the context should be reset
        self.assertIsNone(trace_id_var.get())

    def test_context_does_not_bleed_between_requests(self):
        """
        Test that the trace_id from one request does not bleed into the next.
        """
        # First request has an X-Request-ID
        request_id = str(uuid4())
        self.client.get('/context/', HTTP_X_REQUEST_ID=request_id)

        # Second request does not have the header
        response = self.client.get('/context/')
        self.assertEqual(response.status_code, 200)

        # The trace_id of the second request should be a new, generated UUID,
        # not the one from the first request's header.
        trace_id_2 = json.loads(response.content).get("trace_id")
        self.assertIsNotNone(trace_id_2)
        self.assertNotEqual(trace_id_2, request_id)
        try:
            UUID(trace_id_2, version=4)
        except ValueError:
            self.fail("trace_id_2 is not a valid UUID4")

    def test_discards_invalid_uuid_in_header(self):
        """
        Test that the middleware discards an invalid UUID in the X-Request-ID
        header and generates a new, valid one.
        """
        malicious_id = "not-a-uuid' --"
        response = self.client.get('/context/', HTTP_X_REQUEST_ID=malicious_id)
        self.assertEqual(response.status_code, 200)

        # The trace_id in the response should be a new, valid UUID, not the malicious one.
        new_trace_id = response.headers.get("X-Request-ID")
        self.assertIsNotNone(new_trace_id)
        self.assertNotEqual(new_trace_id, malicious_id)
        try:
            UUID(new_trace_id, version=4)
        except ValueError:
            self.fail("The new trace_id is not a valid UUID4")
