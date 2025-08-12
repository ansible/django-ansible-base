import uuid

from ansible_base.lib.logging.context import origin_var, trace_id_var


class _TraceContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set the context for the request and store the tokens
        origin_token = origin_var.set('request')

        # Get the request ID from the header
        header_trace_id = request.headers.get('x-request-id')
        trace_id = None

        if header_trace_id:
            try:
                # Validate that the provided header is a valid UUID
                uuid.UUID(header_trace_id)
                trace_id = header_trace_id
            except ValueError:
                # If it's not a valid UUID, discard it and we'll generate a new one
                pass

        # If no valid trace_id was found, generate a new one
        if not trace_id:
            trace_id = str(uuid.uuid4())

        trace_id_token = trace_id_var.set(trace_id)

        try:
            response = self.get_response(request)
            response['X-Request-ID'] = trace_id
        finally:
            # Reset the context variables to their previous state
            origin_var.reset(origin_token)
            trace_id_var.reset(trace_id_token)

        return response
