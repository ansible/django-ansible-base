# Logging

django-ansible-base uses Python's logging library to emit messages as needed. If you would like to control the messages coming out of django-ansible-base you can add a logger for `ansible_base` like:

```
        'ansible_base': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
```

## Logging request IDs

django-ansible-base provides machinery (middleware and logging filters) to inject the request id into the logging format string.
The request id should come through as a header in the request, `X-Request-Id` (case-insensitive).

To enable logging of request ids, make the following changes to your application's `settings.py`:

1. Add `'ansible_base.lib.middleware.logging.LogRequestMiddleware'` to `MIDDLEWARE`. This is a middleware that simply
   adds the current request object to the thread-local state, so that the logging filter (in the following steps) can
   make use of it.

2. Configure `LOGGING`

   a. Add the logging filter to `LOGGING['filters']`

   b. Enable the filter in `LOGGING['handlers']`

   c. Make use of the `request_id` parameter in `LOGGING['formatters']`

```python
LOGGING = {
    # ...
    'filters': {
        'request_id_filter': {  # (a)
            '()': 'ansible_base.lib.logging.filters.RequestIdFilter',
        },
    },
    # ...
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)-8s [%(request_id)s]  %(name)s %(message)s'},  # (b)
    },
    # ...
    'handlers': {
        'console': {
            '()': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'simple',
            'filters': ['request_id_filter'],  # (c)
        },
    },
```

After that, the request ID should automatically show up in logs, when the header is passed in.
