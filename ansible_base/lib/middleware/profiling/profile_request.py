import cProfile
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Optional, Union
from urllib.parse import quote

from django.db import connection
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.logging.context import origin_var, trace_id_var
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger(__name__)


class DABProfiler:
    def __init__(self, *args, **kwargs):
        self.cprofiling = bool(get_setting('ANSIBLE_BASE_CPROFILE_REQUESTS', False))
        self.prof = None
        self.start_time = None
        # If DABProfiler is manually initialized by something that is not django middleware, we can change the output dir
        self.output_dir = kwargs.get("output_dir", None)

    def start(self):
        self.start_time = time.time()
        if self.cprofiling:
            self.prof = cProfile.Profile()
            self.prof.enable()

    def stop(self, profile_id: Optional[Union[str, uuid.UUID]] = None):
        if self.start_time is None:
            logger.debug("Attempting to stop profiling without having started...")
            return None, None

        elapsed = time.time() - self.start_time

        if not profile_id:
            profile_id = uuid.uuid4()

        cprofile_filename = None

        if self.cprofiling and self.prof:
            self.prof.disable()

            # Get output directory from setting or use system temp directory
            output_dir = self.output_dir if self.output_dir else get_setting('ANSIBLE_BASE_CPROFILE_DIR', None)
            if output_dir:
                # Ensure the directory exists
                os.makedirs(output_dir, exist_ok=True)
            else:
                output_dir = tempfile.gettempdir()

            filename = f"cprofile-{profile_id}.prof"
            cprofile_filename = os.path.join(output_dir, filename)
            self.prof.dump_stats(cprofile_filename)

        return elapsed, cprofile_filename


class ProfilingSettings:
    def __init__(self, request):
        # Check if any profiling features are enabled
        self.timing_enabled = get_setting('ANSIBLE_BASE_PROFILE_TIMING', False)
        self.node_enabled = get_setting('ANSIBLE_BASE_PROFILE_NODE', False)
        self.cprofile_enabled = get_setting('ANSIBLE_BASE_CPROFILE_REQUESTS', False)
        # Get expected header to enable profiling for the request in the format of HTTP_HEADER_NAME
        enable_profiling_header: str = get_setting('ANSIBLE_BASE_ENABLE_PROFILE_HEADER', '')
        # Skip entirely if the application sets a profiling request header, and that request header is not present
        # Note that we want to always profile the request if profiling is enabled, but the profile header is not defined in settings
        self.profiling_header_unset = enable_profiling_header and not self.get_request_header_value(request, enable_profiling_header)
        # Skip entirely if no profiling is enabled (safe default for production)
        self.profiling_disabled = not (self.timing_enabled or self.node_enabled or self.cprofile_enabled) or self.profiling_header_unset

    # override point in case user passes in some object other than a Django HttpRequest-like object
    def get_request_header_value(self, request, header):
        return request.META.get(header)


class _ProfileRequestMiddleware(threading.local):
    def __init__(self, get_response=None):
        self.get_response = get_response
        self.profiler = DABProfiler()

    def __call__(self, request):
        profiling_settings = ProfilingSettings(request)
        if profiling_settings.profiling_disabled:
            return self.get_response(request)

        logger.debug(
            f"ProfileRequestMiddleware ENABLED: timing={profiling_settings.timing_enabled}, "
            + f"node={profiling_settings.node_enabled}, cprofile={profiling_settings.cprofile_enabled}",
            extra=dict(
                python_objects=dict(
                    timing_enabled=profiling_settings.timing_enabled,
                    node_enabled=profiling_settings.node_enabled,
                    cprofile_enabled=profiling_settings.cprofile_enabled,
                )
            ),
        )

        # Logic before the view (formerly process_request)
        self.profiler.start()
        request_id = trace_id_var.get()

        # Call the next middleware or the view
        response = self.get_response(request)

        # Logic after the view (formerly process_response)
        if getattr(self.profiler, 'start_time', None) is None:
            return response

        elapsed, cprofile_filename = self.profiler.stop(profile_id=request_id)

        # Only add timing header if enabled
        if profiling_settings.timing_enabled and elapsed is not None:
            response['X-API-Time'] = f'{elapsed:.3f}s'
            logger.debug(f"Added X-API-Time header: {elapsed:.3f}s")

        # Only add node header if enabled
        if profiling_settings.node_enabled and 'X-API-Node' not in response:
            node_id = get_setting('CLUSTER_HOST_ID', _('Unknown'))
            response['X-API-Node'] = node_id
            logger.debug(f"Added X-API-Node header: {node_id}")

        # Only add cprofile header if cprofile was actually generated
        if cprofile_filename:
            response['X-API-CProfile-File'] = cprofile_filename
            # Also add node header when cprofile is present (needed to fetch the file)
            if 'X-API-Node' not in response:
                response['X-API-Node'] = get_setting('CLUSTER_HOST_ID', _('Unknown'))
            logger.debug(
                f'request: {request}, cprofile_file: {response["X-API-CProfile-File"]}',
                extra=dict(python_objects=dict(request=request, response=response, X_API_CPROFILE_FILE=response["X-API-CProfile-File"])),
            )

        return response


# Define the maximum length for a value in a SQL comment
SQL_COMMENT_MAX_LENGTH = 256


def _sanitize_for_sql_comment(value: str) -> str:
    """
    Sanitizes a string for safe inclusion in a SQL comment.

    - URL-encodes the value to handle special characters.
    - Removes any */ sequences that could close the SQL comment.
    - Escapes the '%' character to prevent conflicts with database placeholders.
    - Truncates the string to a maximum length.

    This provides defense-in-depth against SQL injection even though the input
    is typically from trusted sources (Django URL patterns).
    """
    # URL-encode the value (handles most dangerous characters)
    quoted_value = quote(str(value), safe='')
    # Extra paranoia: ensure no comment-closing sequences (defense-in-depth)
    quoted_value = quoted_value.replace('*/', '').replace('/*', '')
    # Escape the '%' character for the database driver
    sanitized_value = quoted_value.replace('%', '%%')
    # Truncate to the maximum length
    return sanitized_value[:SQL_COMMENT_MAX_LENGTH]


class SQLQueryMetrics:
    def __init__(self, request=None):
        self.request = request
        self.query_count = 0
        self.query_time = 0.0

    def __call__(self, execute, sql, params, many, context):
        # Build the context comment
        context_items = []
        # trace_id is already validated as a UUID, so it is safe
        if trace_id := trace_id_var.get():
            context_items.append(f"trace_id='{trace_id}'")

        # The route is only available after the URL resolver has run
        if self.request and getattr(self.request, 'resolver_match', None):
            if route := self.request.resolver_match.route:
                context_items.append(f"route='{_sanitize_for_sql_comment(route)}'")

        if origin := origin_var.get():
            context_items.append(f"origin='{_sanitize_for_sql_comment(origin)}'")

        if context_items:
            comment = f"/* {', '.join(context_items)} */"
            sql = f"{comment} {sql}"

        start_time = time.time()
        try:
            return execute(sql, params, many, context)
        finally:
            self.query_count += 1
            self.query_time += time.time() - start_time


class _SQLProfilingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not get_setting('ANSIBLE_BASE_SQL_PROFILING', False):
            return self.get_response(request)

        # Check if the trace context is available. If not, log a warning.
        if trace_id_var.get() is None:
            logger.warning(
                "ANSIBLE_BASE_SQL_PROFILING is enabled, but the trace context is not set. "
                "Please use the ObservabilityMiddleware instead of including profiling middleware individually."
            )

        metrics = SQLQueryMetrics(request)
        with connection.execute_wrapper(metrics):
            response = self.get_response(request)

        response['X-API-Query-Count'] = metrics.query_count
        response['X-API-Query-Time'] = f'{metrics.query_time:.3f}s'
        return response
