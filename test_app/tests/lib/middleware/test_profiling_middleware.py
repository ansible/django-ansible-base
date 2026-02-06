import os
import tempfile
import uuid
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path

from ansible_base.lib.middleware.profiling.profile_request import (
    SQLQueryMetrics,
    _ProfileRequestMiddleware,
)
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
class _ProfileRequestMiddlewareTest(TestCase):
    @override_settings(CLUSTER_HOST_ID='test-node')
    def test_profile_request_middleware_headers(self):
        """
        Test that the _ProfileRequestMiddleware adds sensible headers.
        """
        middleware = _ProfileRequestMiddleware(simple_view)
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
        Test that the _ProfileRequestMiddleware adds the X-API-CProfile-File
        header and creates a profile file when enabled.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('tempfile.gettempdir', return_value=tmpdir):
                middleware = _ProfileRequestMiddleware(simple_view)
                response = middleware(self.client.get('/test/').wsgi_request)
                self.assertIn('X-API-CProfile-File', response)
                profile_file = response['X-API-CProfile-File']
                self.assertTrue(profile_file.endswith('.prof'))
                self.assertTrue(os.path.exists(profile_file))

    @override_settings(ANSIBLE_BASE_CPROFILE_REQUESTS=False)
    def test_profile_request_middleware_cprofile_disabled(self):
        """
        Test that the _ProfileRequestMiddleware does not add the
        X-API-CProfile-File header when disabled.
        """
        middleware = _ProfileRequestMiddleware(simple_view)
        response = middleware(self.client.get('/test/').wsgi_request)
        self.assertNotIn('X-API-CProfile-File', response)


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.request_context._TraceContextMiddleware',
        'ansible_base.lib.middleware.profiling.profile_request._SQLProfilingMiddleware',
    ],
)
class _SQLProfilingMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=False)
    def test_sql_profiling_disabled_by_default(self):
        response = self.client.get('/test-db/')
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_SQL_PROFILING=True)
    def test_sql_profiling_enabled_with_new_setting(self):
        response = self.client.get('/test-db/')
        self.assertIn('X-API-Query-Count', response)
        self.assertGreaterEqual(int(response['X-API-Query-Count']), 1)
        self.assertIn('X-API-Query-Time', response)
        self.assertTrue(response['X-API-Query-Time'].endswith('s'))


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.profiling.profile_request._SQLProfilingMiddleware',
    ],
    ANSIBLE_BASE_SQL_PROFILING=True,
)
class _SQLProfilingMiddlewareMissingContextTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    @patch('ansible_base.lib.middleware.profiling.profile_request.logger')
    def test_logs_warning_if_context_middleware_is_missing(self, mock_logger):
        self.client.get('/test-db/')
        mock_logger.warning.assert_called_with(
            "ANSIBLE_BASE_SQL_PROFILING is enabled, but the trace context is not set. "
            "Please use the ObservabilityMiddleware instead of including profiling middleware individually."
        )


class SQLQueryMetricsTest(TestCase):
    def test_sql_comment_injection(self):
        from django.test.client import RequestFactory

        from ansible_base.lib.logging.context import origin_var, trace_id_var

        # 1. Manually set the context, saving the tokens to reset it later.
        trace_id_token = trace_id_var.set("test-trace-id")
        origin_token = origin_var.set("test-origin")

        # 2. Create a mock request and manually set the resolver_match
        factory = RequestFactory()
        request = factory.get('/test-db/')
        request.resolver_match = type('ResolverMatch', (), {'route': 'test/route'})

        try:
            # 3. Instantiate our metrics class and call it directly.
            metrics = SQLQueryMetrics(request)
            original_sql = "SELECT 1"
            modified_sql = ""

            def mock_execute(sql, params, many, context):
                nonlocal modified_sql
                modified_sql = sql
                return None

            metrics(mock_execute, original_sql, [], False, {})

            # 4. Assert that the SQL passed to our mock was correctly modified.
            self.assertIn("/*", modified_sql)
            self.assertIn("trace_id='test-trace-id'", modified_sql)
            self.assertIn("route='test/route'", modified_sql)
            self.assertIn("origin='test-origin'", modified_sql)
            self.assertIn("*/", modified_sql)
            self.assertIn(original_sql, modified_sql)
        finally:
            # 5. Reset the context variables to their previous state.
            trace_id_var.reset(trace_id_token)
            origin_var.reset(origin_token)


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.observability.ObservabilityMiddleware',
    ],
    ANSIBLE_BASE_SQL_PROFILING=True,
    ANSIBLE_BASE_CPROFILE_REQUESTS=True,
    CLUSTER_HOST_ID='test-node-obs',
)
class ObservabilityMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    def test_observability_middleware_all_headers(self):
        """
        An integration test to ensure the facade middleware adds all expected
        headers and uses the request ID consistently.
        """
        request_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('tempfile.gettempdir', return_value=tmpdir):
                response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id)

                # 1. From _TraceContextMiddleware: Check response header
                self.assertIn('X-Request-ID', response)
                self.assertEqual(response['X-Request-ID'], request_id)

                # 2. From _ProfileRequestMiddleware: Check profiling headers and filename
                self.assertIn('X-API-Time', response)
                self.assertIn('X-API-Node', response)
                self.assertEqual(response['X-API-Node'], 'test-node-obs')
                self.assertIn('X-API-CProfile-File', response)
                self.assertIn(request_id, response['X-API-CProfile-File'])
                self.assertTrue(os.path.exists(response['X-API-CProfile-File']))

                # 3. From _SQLProfilingMiddleware: Check SQL headers
                self.assertIn('X-API-Query-Count', response)
                self.assertIn('X-API-Query-Time', response)


class SQLCommentSanitizationTest(TestCase):
    def test_sanitization_escapes_disallowed_chars(self):
        from ansible_base.lib.middleware.profiling.profile_request import _sanitize_for_sql_comment

        malicious_string = "*/; DROP TABLE users; --"
        sanitized = _sanitize_for_sql_comment(malicious_string)
        self.assertEqual(sanitized, "%%2A/%%3B%%20DROP%%20TABLE%%20users%%3B%%20--")

    def test_sanitization_allows_safe_chars(self):
        from ansible_base.lib.middleware.profiling.profile_request import _sanitize_for_sql_comment

        safe_string = "a-b_c.d/e123"
        sanitized = _sanitize_for_sql_comment(safe_string)
        self.assertEqual(sanitized, "a-b_c.d/e123")

    def test_sanitization_truncates_long_strings(self):
        from ansible_base.lib.middleware.profiling.profile_request import SQL_COMMENT_MAX_LENGTH, _sanitize_for_sql_comment

        long_string = "a" * (SQL_COMMENT_MAX_LENGTH + 100)
        sanitized = _sanitize_for_sql_comment(long_string)
        self.assertEqual(len(sanitized), SQL_COMMENT_MAX_LENGTH)
