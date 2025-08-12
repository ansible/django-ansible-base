import uuid

from ansible_base.lib.logging.context import origin_var, route_var, trace_id_var


class TraceContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set the context for the request and store the tokens
        origin_token = origin_var.set('request')
        trace_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        trace_id_token = trace_id_var.set(trace_id)

        route_token = None
        if request.resolver_match:
            route_token = route_var.set(request.resolver_match.route)

        try:
            response = self.get_response(request)
        finally:
            # Reset the context variables to their previous state
            origin_var.reset(origin_token)
            trace_id_var.reset(trace_id_token)
            if route_token:
                route_var.reset(route_token)

        return response
