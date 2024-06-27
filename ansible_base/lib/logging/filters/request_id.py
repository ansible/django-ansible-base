import logging
import uuid

from ansible_base.lib.logging import thread_local
from ansible_base.lib.utils.collection import first_matching


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        # Always a default so we can use it in the logging formatter.
        record.request_id = ""

        request = getattr(thread_local, "request", None)

        if request is None:
            # request never got added to the thread local, so we can't add the request id to the log.
            # But we still want to log the message.
            return True

        headers = request.META.keys()
        request_id_header = first_matching(lambda x: x.lower().replace('-', '_') == "http_x_request_id", headers, default=None)
        if request_id_header is None:
            # We have a request, but no request id header. Still want to log the message.
            return True
        request_id = request.META.get(request_id_header)
        try:
            uuid.UUID(request_id)
        except ValueError:
            # Invalid request id, still want to log the message, but not with the invalid request id.
            pass
        else:
            record.request_id = request_id
        return True
