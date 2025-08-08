
import os
import tempfile
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path

from ansible_base.lib.middleware.profiling.profile_request import ProfileRequestMiddleware

# A simple view for testing middleware
def simple_view(request):
    return HttpResponse("OK")

# Define URL patterns for the test
urlpatterns = [
    path('test/', simple_view),
]

@override_settings(ROOT_URLCONF=__name__)
class ProfileRequestMiddlewareTest(TestCase):
    @override_settings(CLUSTER_HOST_ID='test-node')
    def test_profile_request_middleware_headers(self):
        """
        Test that the ProfileRequestMiddleware adds sensible headers.
        """
        middleware = ProfileRequestMiddleware(simple_view)
        response = middleware(self.client.get('/test/').wsgi_request)
        
        # Test X-API-Time
        self.assertIn('X-API-Time', response)
        self.assertTrue(response['X-API-Time'].endswith('s'))
        try:
            float(response['X-API-Time'][:-1])
        except ValueError:
            self.fail("X-API-Time value is not a valid float")

        # Test X-API-Node
        self.assertIn('X-API-Node', response)
        self.assertEqual(response['X-API-Node'], 'test-node')

    @override_settings(ANSIBLE_BASE_CPROFILE_REQUESTS=True)
    def test_profile_request_middleware_cprofile_enabled(self):
        """
        Test that the ProfileRequestMiddleware adds the X-API-CProfile-File
        header and creates a profile file when enabled.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('tempfile.gettempdir', return_value=tmpdir):
                middleware = ProfileRequestMiddleware(simple_view)
                response = middleware(self.client.get('/test/').wsgi_request)
                self.assertIn('X-API-CProfile-File', response)
                profile_file = response['X-API-CProfile-File']
                self.assertTrue(profile_file.endswith('.prof'))
                self.assertTrue(os.path.exists(profile_file))

    def test_profile_request_middleware_cprofile_disabled(self):
        """
        Test that the ProfileRequestMiddleware does not add the
        X-API-CProfile-File header when disabled.
        """
        middleware = ProfileRequestMiddleware(simple_view)
        response = middleware(self.client.get('/test/').wsgi_request)
        self.assertNotIn('X-API-CProfile-File', response)


