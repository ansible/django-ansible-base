import uuid
import os
import tempfile
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path

from ansible_base.lib.middleware.profiling.profile_request import ProfileRequestMiddleware, SQLProfilingMiddleware
from ansible_base.lib.utils.settings import get_setting
from test_app.models import User

# A simple view for testing middleware
def simple_view(request):
    return HttpResponse("OK")

# A view that performs a database query
def db_view(request):
    # Create a user with a unique username to guarantee a query.
    User.objects.create(username=f"test-{uuid.uuid4()}")
    return HttpResponse("OK")

# Define URL patterns for the test
urlpatterns = [
    path('test/', simple_view),
    path('test-db/', db_view),
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


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=['ansible_base.lib.middleware.profiling.profile_request.SQLProfilingMiddleware']
)
class SQLProfilingMiddlewareTest(TestCase):
    def test_sql_profiling_disabled_by_default(self):
        """
        Test that the SQLProfilingMiddleware does not add headers when disabled.
        """
        response = self.client.get('/test-db/')
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=True, DEBUG=True)
    def test_sql_profiling_enabled_with_new_setting(self):
        """
        Test that the SQLProfilingMiddleware adds headers when ANSIBLE_BASE_SQL_PROFILING is True.
        """
        response = self.client.get('/test-db/')
        self.assertIn('X-API-Query-Count', response)
        self.assertGreaterEqual(int(response['X-API-Query-Count']), 1)
        self.assertIn('X-API-Query-Time', response)
        self.assertTrue(response['X-API-Query-Time'].endswith('s'))
        try:
            float(response['X-API-Query-Time'][:-1])
        except ValueError:
            self.fail("X-API-Query-Time value is not a valid float")

    @override_settings(SQL_DEBUG=True, DEBUG=True)
    def test_sql_profiling_enabled_with_fallback_setting(self):
        """
        Test that the SQLProfilingMiddleware adds headers when SQL_DEBUG is True as a fallback.
        """
        response = self.client.get('/test-db/')
        self.assertIn('X-API-Query-Count', response)
        self.assertGreaterEqual(int(response['X-API-Query-Count']), 1)
        self.assertIn('X-API-Query-Time', response)
        self.assertTrue(response['X-API-Query-Time'].endswith('s'))
        try:
            float(response['X-API-Query-Time'][:-1])
        except ValueError:
            self.fail("X-API-Query-Time value is not a valid float")

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=True, DEBUG=False)
    def test_sql_profiling_logs_warning_if_debug_is_false(self):
        """
        Test that the SQLProfilingMiddleware logs a warning and does not add headers
        if profiling is enabled but DEBUG is False.
        """
        with self.assertLogs('ansible_base.lib.middleware.profiling.profile_request', level='WARNING') as cm:
            response = self.client.get('/test-db/')
            self.assertIn("ANSIBLE_BASE_SQL_PROFILING is enabled, but DEBUG is False", cm.output[0])
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)


