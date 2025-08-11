import cProfile
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Optional, Union

from django.db import connection
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.utils.settings import get_function_from_setting, get_setting


logger = logging.getLogger(__name__)


class DABProfiler:
    def __init__(self, *args, **kwargs):
        self.cprofiling = bool(get_setting('ANSIBLE_BASE_CPROFILE_REQUESTS', False))
        self.prof = None
        self.start_time = None

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
            temp_dir = tempfile.gettempdir()
            filename = f"cprofile-{profile_id}.prof"
            cprofile_filename = os.path.join(temp_dir, filename)
            self.prof.dump_stats(cprofile_filename)

        return elapsed, cprofile_filename


class ProfileRequestMiddleware(threading.local):
    def __init__(self, get_response=None):
        self.get_response = get_response
        self.profiler = DABProfiler()

    def __call__(self, request):
        # Logic before the view (formerly process_request)
        self.profiler.start()
        request_id = request.headers.get('X-Request-ID')

        # Call the next middleware or the view
        response = self.get_response(request)

        # Logic after the view (formerly process_response)
        if getattr(self.profiler, 'start_time', None) is None:
            return response

        elapsed, cprofile_filename = self.profiler.stop(profile_id=request_id)

        if elapsed is not None:
            response['X-API-Time'] = f'{elapsed:.3f}s'
        if 'X-API-Node' not in response:
            response['X-API-Node'] = get_setting('CLUSTER_HOST_ID', _('Unknown'))

        if cprofile_filename:
            response['X-API-CProfile-File'] = cprofile_filename
            logger.debug(
                f'request: {request}, cprofile_file: {response["X-API-CProfile-File"]}',
                extra=dict(python_objects=dict(request=request, response=response, X_API_CPROFILE_FILE=response["X-API-CProfile-File"])),
            )

        return response


class SQLProfilingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sql_profiling_enabled = get_setting('ANSIBLE_BASE_SQL_PROFILING', get_setting('SQL_DEBUG', False))
        if sql_profiling_enabled:
            if not settings.DEBUG:
                logger.warning("ANSIBLE_BASE_SQL_PROFILING is enabled, but DEBUG is False. No SQL queries will be logged or counted.")
                return self.get_response(request)

            queries_before = len(connection.queries)
            response = self.get_response(request)
            q_times = [float(q['time']) for q in connection.queries[queries_before:]]
            response['X-API-Query-Count'] = len(q_times)
            response['X-API-Query-Time'] = '%0.3fs' % sum(q_times)
        else:
            response = self.get_response(request)

        return response
