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
    path('up', simple_view),
]


@override_settings(ROOT_URLCONF=__name__)
class _ProfileRequestMiddlewareTest(TestCase):
    def test_profile_request_middleware_headers(self):
        """
        Test that the _ProfileRequestMiddleware adds sensible headers.
        """
        middleware = _ProfileRequestMiddleware(simple_view)
        response = middleware(self.client.get('/test/').wsgi_request)

        # Test X-API-Total-Time
        self.assertIn('X-API-Total-Time', response)
        self.assertTrue(response['X-API-Total-Time'].endswith('s'))
        try:
            float(response['X-API-Total-Time'][:-1])
        except ValueError:
            self.fail("X-API-Total-Time value is not a valid float")

    def test_profile_request_middleware_cprofile(self):
        """
        Test that the _ProfileRequestMiddleware adds the X-API-Profile-File
        header and creates a profile file when ANSIBLE_BASE_PROFILING_ENABLED is True.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(ANSIBLE_BASE_PROFILING_ENABLED=True, ANSIBLE_BASE_PROFILING_CPROFILE_DIR=tmpdir):
                middleware = _ProfileRequestMiddleware(simple_view)
                response = middleware(self.client.get('/test/').wsgi_request)
                self.assertIn('X-API-Profile-File', response)
                profile_file = response['X-API-Profile-File']
                self.assertTrue(profile_file.endswith('.prof'))
                self.assertTrue(os.path.exists(profile_file))


@override_settings(
    ROOT_URLCONF=__name__,
    ANSIBLE_BASE_PROFILING_SQL_ENABLED=True,
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

    def test_sql_profiling_adds_headers(self):
        response = self.client.get('/test-db/')
        self.assertIn('X-API-Query-Count', response)
        self.assertGreaterEqual(int(response['X-API-Query-Count']), 1)
        self.assertIn('X-API-Query-Time', response)
        self.assertTrue(response['X-API-Query-Time'].endswith('s'))


@override_settings(
    ROOT_URLCONF=__name__,
    ANSIBLE_BASE_PROFILING_SQL_ENABLED=True,
    MIDDLEWARE=[
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'ansible_base.lib.middleware.profiling.profile_request._SQLProfilingMiddleware',
    ],
)
class _SQLProfilingMiddlewareMissingContextTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    @patch('ansible_base.lib.middleware.profiling.profile_request.logger')
    def test_logs_warning_if_context_middleware_is_missing(self, mock_logger):
        self.client.get('/test-db/')
        mock_logger.warning.assert_called_with(
            "SQL profiling is enabled, but the trace context is not set. "
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
    ANSIBLE_BASE_PROFILING_ENABLED=True,
    ANSIBLE_BASE_PROFILING_SQL_ENABLED=True,
)
class ObservabilityMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)

    def test_observability_middleware_all_headers(self):
        """
        When both profiling flags are True, all profiling headers should be present.
        """
        request_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(ANSIBLE_BASE_PROFILING_CPROFILE_DIR=tmpdir):
                response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id)

                # 1. From _TraceContextMiddleware: Check response header
                self.assertIn('X-Request-ID', response)
                self.assertEqual(response['X-Request-ID'], request_id)

                # 2. From _ProfileRequestMiddleware: Check profiling headers and filename
                self.assertIn('X-API-Total-Time', response)
                self.assertIn('X-API-Profile-File', response)
                self.assertIn(request_id, response['X-API-Profile-File'])
                self.assertTrue(os.path.exists(response['X-API-Profile-File']))

                # 3. From _SQLProfilingMiddleware: Check SQL headers
                self.assertIn('X-API-Query-Count', response)
                self.assertIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_PROFILING_ENABLED=False, ANSIBLE_BASE_PROFILING_SQL_ENABLED=False)
    def test_observability_middleware_disabled(self):
        """
        When both profiling flags are False, no profiling headers should be present,
        but trace context (X-Request-ID) and timing (X-API-Total-Time) should still work.
        """
        request_id = str(uuid.uuid4())
        response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id)

        self.assertIn('X-Request-ID', response)
        self.assertEqual(response['X-Request-ID'], request_id)

        # Timing is always present
        self.assertIn('X-API-Total-Time', response)

        # Profiling-specific headers should be absent
        self.assertNotIn('X-API-Profile-File', response)
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)

    def test_observability_middleware_excludes_paths(self):
        """
        When profiling flags are True but the request path matches an excluded
        prefix, profiling headers should not be present but timing should.
        """
        request_id = str(uuid.uuid4())
        response = self.client.get('/up', HTTP_X_REQUEST_ID=request_id)

        # Trace context and timing should still work
        self.assertIn('X-Request-ID', response)
        self.assertEqual(response['X-Request-ID'], request_id)
        self.assertIn('X-API-Total-Time', response)

        # Profiling headers should be absent (path is excluded)
        self.assertNotIn('X-API-Profile-File', response)
        self.assertNotIn('X-API-Query-Count', response)
        self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_PROFILING_ENABLED=True, ANSIBLE_BASE_PROFILING_SQL_ENABLED=False)
    def test_observability_middleware_cprofile_only(self):
        """
        When only ANSIBLE_BASE_PROFILING_ENABLED is True, cProfile headers should
        be present but SQL headers should not.
        """
        request_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(ANSIBLE_BASE_PROFILING_CPROFILE_DIR=tmpdir):
                response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id)

                self.assertIn('X-Request-ID', response)
                self.assertIn('X-API-Total-Time', response)
                self.assertIn('X-API-Profile-File', response)

                self.assertNotIn('X-API-Query-Count', response)
                self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_PROFILING_ENABLED=False, ANSIBLE_BASE_PROFILING_SQL_ENABLED=False)
    def test_header_enables_cprofile_without_setting(self):
        """
        When ANSIBLE_BASE_PROFILING_ENABLED is False but the X-Enable-Profiling
        header is sent, cProfile should be enabled for that request only.
        SQL profiling should remain off.
        """
        request_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(ANSIBLE_BASE_PROFILING_CPROFILE_DIR=tmpdir):
                response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id, HTTP_X_ENABLE_PROFILING='true')

                self.assertIn('X-Request-ID', response)
                self.assertIn('X-API-Total-Time', response)
                self.assertIn('X-API-Profile-File', response)
                self.assertTrue(os.path.exists(response['X-API-Profile-File']))

                self.assertNotIn('X-API-Query-Count', response)
                self.assertNotIn('X-API-Query-Time', response)

    @override_settings(ANSIBLE_BASE_PROFILING_ENABLED=False, ANSIBLE_BASE_PROFILING_SQL_ENABLED=True)
    def test_observability_middleware_sql_only(self):
        """
        When only ANSIBLE_BASE_PROFILING_SQL_ENABLED is True, SQL headers should be present
        but cProfile headers should not.
        """
        request_id = str(uuid.uuid4())
        response = self.client.get('/test-db/', HTTP_X_REQUEST_ID=request_id)

        self.assertIn('X-Request-ID', response)
        self.assertIn('X-API-Total-Time', response)
        self.assertIn('X-API-Query-Count', response)
        self.assertIn('X-API-Query-Time', response)

        self.assertNotIn('X-API-Profile-File', response)


class DABProfilerFallbackTest(TestCase):
    @patch('ansible_base.lib.middleware.profiling.profile_request.os.makedirs', side_effect=OSError("Permission denied"))
    def test_falls_back_to_tmpdir_on_permission_error(self, _mock_makedirs):
        """
        When the configured directory is not writable, DABProfiler should
        fall back to the system temp directory instead of crashing.
        """
        from ansible_base.lib.middleware.profiling.profile_request import DABProfiler

        profiler = DABProfiler(output_dir='/some/configured/path')
        profiler.start()
        profile_id = uuid.uuid4()
        elapsed, cprofile_filename = profiler.stop(profile_id=profile_id)

        self.assertIsNotNone(elapsed)
        self.assertIsNotNone(cprofile_filename)
        self.assertTrue(cprofile_filename.startswith(tempfile.gettempdir()))
        self.assertTrue(os.path.exists(cprofile_filename))
        os.remove(cprofile_filename)


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
