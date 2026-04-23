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

from ansible_base.lib.logging.context import origin_var, trace_id_var

logger = logging.getLogger(__name__)


class DABProfiler:
    """cProfile wrapper that writes .prof files to a configurable directory.

    Output directory resolution: explicit override > ANSIBLE_BASE_PROFILING_CPROFILE_DIR setting > system temp.
    Falls back to the system temp directory on write errors.
    """

    def __init__(self, *args, **kwargs):
        self.prof = None
        self.start_time = None
        self.output_dir = kwargs.get("output_dir", None)

    def start(self) -> None:
        self.start_time = time.time()
        try:
            self.prof = cProfile.Profile()
            self.prof.enable()
        except ValueError:
            # Another profiler is already active on this thread (common in
            # gRPC thread pools). Skip cProfile but still capture timing.
            self.prof = None

    def stop(self, profile_id: Optional[Union[str, uuid.UUID]] = None) -> tuple[Optional[float], Optional[str]]:
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
            output_dir = self.output_dir if self.output_dir else getattr(settings, 'ANSIBLE_BASE_PROFILING_CPROFILE_DIR', None)
            if not output_dir:
                output_dir = tempfile.gettempdir()

            try:
                os.makedirs(output_dir, exist_ok=True)
                # profile_id is the X-Request-ID (a UUID), used to correlate .prof files with requests
                filename = f"cprofile-{profile_id}.prof"
                cprofile_filename = os.path.join(output_dir, filename)
                self.prof.dump_stats(cprofile_filename)
            except OSError:
                logger.warning(f"Failed to write cProfile output to {output_dir}, falling back to {tempfile.gettempdir()}")
                try:
                    output_dir = tempfile.gettempdir()
                    filename = f"cprofile-{profile_id}.prof"
                    cprofile_filename = os.path.join(output_dir, filename)
                    self.prof.dump_stats(cprofile_filename)
                except OSError:
                    logger.warning(f"Failed to write cProfile output to fallback {output_dir}, discarding profile data")
                    cprofile_filename = None

        self.start_time = None
        self.prof = None
        return elapsed, cprofile_filename


class _ProfileRequestMiddleware(threading.local):
    """Adds timing and optional cProfile headers to HTTP responses.

    The timing header (X-API-Total-Time) is always set. cProfile output is
    only produced when the ANSIBLE_BASE_PROFILING_ENABLED setting is True.

    Response headers:
        X-API-Total-Time: Wall-clock request duration (e.g. "0.045s"). Always set.
        X-API-Profile-File: Filesystem path to the .prof file on the server (cProfile only).
    """

    def __init__(self, get_response=None):
        self.get_response = get_response
        self.profiler = DABProfiler()

    def __call__(self, request):
        cprofile_enabled = (getattr(settings, 'ANSIBLE_BASE_PROFILING_ENABLED', False) or request.headers.get('X-Enable-Profiling')) and not getattr(
            request, '_profiling_excluded', False
        )
        request_id = trace_id_var.get()

        if cprofile_enabled:
            self.profiler.start()

        start_time = time.time()

        try:
            response = self.get_response(request)
        except Exception:
            if cprofile_enabled:
                _, path = self.profiler.stop(profile_id=request_id)
                if path:
                    logger.info("Request raised an exception; cProfile data saved to: %s", path)
            raise

        response['X-API-Total-Time'] = f'{time.time() - start_time:.3f}s'

        if cprofile_enabled:
            _, cprofile_filename = self.profiler.stop(profile_id=request_id)
            if cprofile_filename:
                response['X-API-Profile-File'] = cprofile_filename

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
    quoted_value = quote(str(value), safe='/-._~')
    # Extra paranoia: ensure no comment-closing sequences (defense-in-depth)
    quoted_value = quoted_value.replace('*/', '').replace('/*', '')
    # Escape the '%' character for the database driver
    sanitized_value = quoted_value.replace('%', '%%')
    # Truncate to the maximum length
    return sanitized_value[:SQL_COMMENT_MAX_LENGTH]


class SQLQueryMetrics:
    """Database execute wrapper that counts queries and injects trace context into SQL comments.

    After the request completes, ``query_count`` and ``query_time`` contain
    the totals for the wrapped scope.
    """

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
    """Adds SQL query metrics headers to HTTP responses.

    Only active when the ANSIBLE_BASE_PROFILING_SQL_ENABLED setting is True.
    Otherwise passes through to the next middleware with no overhead.

    Response headers:
        X-API-Query-Count: Number of SQL queries executed during the request.
        X-API-Query-Time: Total time spent in SQL (e.g. "0.012s").
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'ANSIBLE_BASE_PROFILING_SQL_ENABLED', False) or getattr(request, '_profiling_excluded', False):
            return self.get_response(request)

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
