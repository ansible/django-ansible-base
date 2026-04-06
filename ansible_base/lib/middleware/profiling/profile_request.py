import cProfile
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Optional, Union
from urllib.parse import quote

from django.conf import settings
from django.db import connection
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.logging.context import origin_var, trace_id_var

logger = logging.getLogger(__name__)


class DABProfiler:
    def __init__(self, *args, **kwargs):
        self.prof = None
        self.start_time = None
        # If DABProfiler is manually initialized by something that is not django middleware, we can change the output dir
        self.output_dir = kwargs.get("output_dir", None)

    def start(self):
        self.start_time = time.time()
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

        if self.prof:
            self.prof.disable()

            # Get output directory: explicit override > dynamic setting > system temp
            output_dir = self.output_dir if self.output_dir else getattr(settings, 'PROFILING_CPROFILE_DIR', None)
            if not output_dir:
                output_dir = tempfile.gettempdir()

            try:
                os.makedirs(output_dir, exist_ok=True)
                filename = f"cprofile-{profile_id}.prof"
                cprofile_filename = os.path.join(output_dir, filename)
                self.prof.dump_stats(cprofile_filename)
            except OSError:
                logger.warning(f"Failed to write cProfile output to {output_dir}, falling back to {tempfile.gettempdir()}")
                output_dir = tempfile.gettempdir()
                filename = f"cprofile-{profile_id}.prof"
                cprofile_filename = os.path.join(output_dir, filename)
                self.prof.dump_stats(cprofile_filename)

        return elapsed, cprofile_filename


class _ProfileRequestMiddleware(threading.local):
    def __init__(self, get_response=None):
        self.get_response = get_response
        self.profiler = DABProfiler()

    def __call__(self, request):
        self.profiler.start()
        request_id = trace_id_var.get()

        response = self.get_response(request)

        if getattr(self.profiler, 'start_time', None) is None:
            return response

        elapsed, cprofile_filename = self.profiler.stop(profile_id=request_id)

        if elapsed is not None:
            response['X-API-Time'] = f'{elapsed:.3f}s'

        if 'X-API-Node' not in response:
            response['X-API-Node'] = getattr(settings, 'CLUSTER_HOST_ID', _('Unknown'))

        if cprofile_filename:
            response['X-API-CProfile-File'] = cprofile_filename
            if 'X-API-Node' not in response:
                response['X-API-Node'] = getattr(settings, 'CLUSTER_HOST_ID', _('Unknown'))

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
        # Check if the trace context is available. If not, log a warning.
        if trace_id_var.get() is None:
            logger.warning(
                "SQL profiling is enabled, but the trace context is not set. "
                "Please use the ObservabilityMiddleware instead of including profiling middleware individually."
            )

        metrics = SQLQueryMetrics(request)
        with connection.execute_wrapper(metrics):
            response = self.get_response(request)

        response['X-API-Query-Count'] = metrics.query_count
        response['X-API-Query-Time'] = f'{metrics.query_time:.3f}s'
        return response
