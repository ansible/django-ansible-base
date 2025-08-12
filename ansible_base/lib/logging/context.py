import contextvars
import uuid

# Define the context variables that will hold our trace information.
# Providing a default value is important so that they can be accessed
# even when the context has not been explicitly set.
trace_id_var = contextvars.ContextVar('trace_id', default=None)
route_var = contextvars.ContextVar('route', default=None)
origin_var = contextvars.ContextVar('origin', default=None)


class trace_context:
    """
    A context manager and decorator to set the trace context for non-web operations.
    """

    def __init__(self, origin=None, **kwargs):
        self.origin = origin
        self.kwargs = kwargs
        self.tokens = []

    def __enter__(self):
        # Set a new trace ID for this context
        self.tokens.append(trace_id_var.set(str(uuid.uuid4())))

        # Set the origin (e.g., 'dispatcher')
        if self.origin:
            self.tokens.append(origin_var.set(self.origin))

        for key, value in self.kwargs.items():
            var = contextvars.ContextVar(key)
            self.tokens.append(var.set(value))

    def __exit__(self, exc_type, exc_value, traceback):
        # Reset the context variables to their previous state
        for token in self.tokens:
            var = token.var
            var.reset(token)

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return wrapper
