# Request Profiling and Observability

The `ObservabilityMiddleware` provides a simple way to gain performance and debugging insights into your Django application. It acts as a single entry point for several underlying middleware components, ensuring they are always used in the correct order.

## `ObservabilityMiddleware`

This single middleware bundles tracing, request profiling, and SQL query analysis. To use it, add it to the top of your `MIDDLEWARE` list in your Django settings.

```python
# settings.py
MIDDLEWARE = [
    'ansible_base.lib.middleware.observability.ObservabilityMiddleware',
    ...
]
```

The middleware always adds the following header to the response:

*   `X-Request-ID`: A unique identifier for the request. If the incoming request includes an `X-Request-ID` header, that value will be used; otherwise, a new UUID will be generated.

### Request Timing

When the `ANSIBLE_BASE_PROFILE_TIMING` setting is enabled, the middleware adds:

*   `X-API-Time`: The total time taken to process the request, in seconds.

```python
# settings.py
ANSIBLE_BASE_PROFILE_TIMING = True
```

> **Note:** Request timing has minimal overhead and is generally safe for production use.

### Node Identification

When the `ANSIBLE_BASE_PROFILE_NODE` setting is enabled, the middleware adds:

*   `X-API-Node`: The cluster host ID of the node that served the request.

```python
# settings.py
ANSIBLE_BASE_PROFILE_NODE = True
```

> **Note:** Some security-conscious deployments may not want to expose internal node identifiers. This setting allows you to control that behavior.

### cProfile Support

When the `ANSIBLE_BASE_CPROFILE_REQUESTS` setting is enabled, the middleware will also perform a cProfile analysis for each request. The resulting `.prof` file is saved to a directory on the node that served the request, and its path is returned in the `X-API-CProfile-File` response header. The filename will include the request's `X-Request-ID`.

When cProfile is enabled, `X-API-Node` is automatically included in the response (needed to identify which node contains the profile file).

To enable cProfile support, set the following in your Django settings:

```python
# settings.py
ANSIBLE_BASE_CPROFILE_REQUESTS = True

# Optional: Specify where to write cProfile files (defaults to system temp directory)
ANSIBLE_BASE_CPROFILE_DIR = '/var/log/myapp/profile'
```

> **Note:** Enabling cProfile has significant performance implications and is intended for temporary, live debugging sessions, not for permanent use in production environments.
>
> **Note:** When setting `ANSIBLE_BASE_CPROFILE_DIR`, ensure the directory exists and the application has write permissions. The directory will be created automatically if it doesn't exist.

### SQL Profiling Support

When the `ANSIBLE_BASE_SQL_PROFILING` setting is enabled, the middleware provides insights into the database queries executed during a request. It adds the following headers to the response:

*   `X-API-Query-Count`: The total number of database queries executed during the request.
*   `X-API-Query-Time`: The total time spent on database queries, in seconds.

It also injects contextual information as a comment into each SQL query, which is invaluable for debugging and tracing. For example:
`/* trace_id=b71696ed-c483-408d-9740-2e7935b4f2d9, route=api/v2/users/{pk}/, origin=request */ SELECT ...`

To enable SQL profiling, set the following in your Django settings:

```python
# settings.py
ANSIBLE_BASE_SQL_PROFILING = True
```

> **Note:** This feature is most effective when used in combination with your database's slow query logging capabilities. For high-traffic environments, consider configuring your database to log only a percentage of queries to manage logging overhead.

## `DABProfiler`

For profiling non-HTTP contexts, such as background tasks or gRPC services, the `DABProfiler` class can be used directly.

The profiler's cProfile functionality is controlled by the `ANSIBLE_BASE_CPROFILE_REQUESTS` setting.

- When the setting is `True`, `profiler.stop()` returns a tuple of `(elapsed_time, cprofile_filename)`.
- When the setting is `False`, `profiler.stop()` returns `(elapsed_time, None)`.

### Example Usage

```python
from ansible_base.lib.middleware.profiling.profile_request import DABProfiler

def my_background_task():
    profiler = DABProfiler()
    profiler.start()

    # Your code here

    elapsed, cprofile_filename = profiler.stop()

    if cprofile_filename:
        print(f"cProfile data saved to: {cprofile_filename}")

    print(f"Task took {elapsed:.3f}s to complete.")
```

## `trace_context` for Background Tasks

For adding observability to non-HTTP contexts without the overhead of the `DABProfiler`, the `trace_context` context manager is the ideal tool. It ensures that background tasks can be traced with a unique request ID, just like the `ObservabilityMiddleware` does for web requests.

This is particularly useful for background tasks, such as those initiated by the controller's dispatcher, where you want to correlate all log messages for a specific operation.

### Example Usage

Here's how you might use the `trace_context` manager in the controller's dispatcher to ensure that all work related to a specific job has a consistent trace ID.

```python
# In a hypothetical controller dispatcher task
from ansible_base.lib.logging.context import trace_context

def run_job(job_id, parent_trace_id=None):
    """
    A background task that runs a job.
    """
    # Use the parent_trace_id if it exists; otherwise, a new one will be generated.
    # The origin is a string that identifies the source of the trace.
    with trace_context(origin='controller_dispatcher', trace_id=parent_trace_id):
        # All logging within this block will now have the same trace_id.
        # logger.info(f"Starting job {job_id}")
        # ... do work ...
        # logger.info(f"Finished job {job_id}")
        pass
```

## Visualizing Profile Data

The `.prof` files generated by the cProfile support can be analyzed with a variety of tools.

### SnakeViz

[SnakeViz](https://jiffyclub.github.io/snakeviz/) is a browser-based graphical viewer for the output of Python profilers.

You can install it with pip:
```bash
pip install snakeviz
```

To visualize a profile file, run:
```bash
snakeviz /path/to/your/profile.prof
```

### pstats

The standard library `pstats` module can also be used to read and manipulate profile data.

```python
import pstats

p = pstats.Stats('/path/to/your/profile.prof')
p.sort_stats('cumulative').print_stats(10)
```

