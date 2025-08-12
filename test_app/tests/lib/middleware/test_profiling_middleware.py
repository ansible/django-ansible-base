import os
import tempfile
import uuid
from unittest.mock import MagicMock, patch

from django.db import connection
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path

from ansible_base.lib.middleware.profiling.profile_request import ProfileRequestMiddleware, SQLProfilingMiddleware
from ansible_base.lib.utils.settings import get_setting
from test_app.models import Organization, User


# A simple view for testing middleware
def simple_view(request):
    return HttpResponse("OK")


# A view that performs a database query
def db_view(request):
    # Get or create an organization to guarantee at least one query is executed.
    Organization.objects.get_or_create(name=f"test-org-{uuid.uuid4()}")
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
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.request_context.TraceContextMiddleware',
        'ansible_base.lib.middleware.profiling.profile_request.SQLProfilingMiddleware',
    ],
)
class SQLProfilingMiddlewareTest(TestCase):
    def setUp(self):
        # Create a user and log them in. This is necessary to avoid the bug in the
        # test_app models that causes a TypeError when get_system_user is called.
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=False)
    def test_sql_profiling_disabled_by_default(self):
        """
        Test that the SQLProfilingMiddleware does not add headers when disabled.
        """
        response = self.client.get('/test-db/')
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=True)
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


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.profiling.profile_request.SQLProfilingMiddleware',
    ],
    ANSIBLE_BASE_SQL_PROFILING=True,
)
class SQLProfilingMiddlewareMissingContextTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    @patch('ansible_base.lib.middleware.profiling.profile_request.logger')
    def test_logs_warning_if_context_middleware_is_missing(self, mock_logger):
        """
        Test that the SQLProfilingMiddleware logs a warning if the TraceContextMiddleware
        is not present and the context is missing, even when a query is made.
        """
        # We need to use a real view that makes a query
        response = self.client.get('/test-db/')
        self.assertEqual(response.status_code, 200)

        mock_logger.warning.assert_called_with(
            "ANSIBLE_BASE_SQL_PROFILING is enabled, but the trace context is not set. "
            "Please ensure that TraceContextMiddleware is included in your MIDDLEWARE settings before this middleware."
        )


class SQLQueryMetricsTest(TestCase):
    def test_sql_comment_injection(self):
        """
        Test that the SQLQueryMetrics wrapper correctly injects context
        into the SQL query as a comment.
        """
        from ansible_base.lib.logging.context import origin_var, route_var, trace_id_var
        from ansible_base.lib.middleware.profiling.profile_request import SQLQueryMetrics

        # 1. Manually set the context, saving the tokens to reset it later.
        trace_id_token = trace_id_var.set("test-trace-id")
        route_token = route_var.set("test/route")
        origin_token = origin_var.set("test-origin")

        try:
            # 2. Instantiate our metrics class and call it directly.
            metrics = SQLQueryMetrics()
            original_sql = "SELECT 1"

            # 3. We don't need a real execute function, so we'll just use a lambda.
            # The key is that we can inspect the SQL that was passed to it.
            modified_sql = ""

            def mock_execute(sql, params, many, context):
                nonlocal modified_sql
                modified_sql = sql
                return None

            metrics(mock_execute, original_sql, [], False, {})

            # 4. Assert that the SQL passed to our mock was correctly modified.
            self.assertIn("/*", modified_sql)
            self.assertIn("trace_id=test-trace-id", modified_sql)
            self.assertIn("route=test/route", modified_sql)
            self.assertIn("origin=test-origin", modified_sql)
            self.assertIn("*/", modified_sql)
            self.assertIn(original_sql, modified_sql)
        finally:
            # 5. Reset the context variables to their previous state.
            trace_id_var.reset(trace_id_token)
            route_var.reset(route_token)
            origin_var.reset(origin_token)
