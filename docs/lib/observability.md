# Observability Middleware

The `ObservabilityMiddleware` provides request tracing, timing, cProfile analysis, and SQL query metrics through a single middleware entry point.

## Setup

Add `ansible_base.lib.middleware.observability.ObservabilityMiddleware` to your `MIDDLEWARE` list. It should be placed near the top, before authentication or other request-processing middleware:

```python
MIDDLEWARE = [
    'ansible_base.lib.middleware.observability.ObservabilityMiddleware',
    # ... other middleware
]
```

Every request automatically gets `X-Request-ID` (trace context) and `X-API-Total-Time` (wall-clock timing). cProfile and SQL metrics are individually opt-in:

```python
# settings.py

# Enable cProfile .prof file generation for ALL requests (heavy — use for debugging sessions only)
ANSIBLE_BASE_PROFILING_ENABLED = True

# Enable SQL query metrics and trace context injection (moderate overhead)
ANSIBLE_BASE_PROFILING_SQL_ENABLED = True
```

Alternatively, cProfile can be enabled on a per-request basis by sending the `X-Enable-Profiling` request header (any value). This avoids the need to restart the server or enable profiling globally:

```bash
curl -H "X-Enable-Profiling: true" https://localhost/api/v1/users/
```

## Settings

| Setting | Default | Description |
|---|---|---|
| `ANSIBLE_BASE_PROFILING_ENABLED` | `False` | Enables cProfile output. Writes `.prof` files and adds the `X-API-Profile-File` header. |
| `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | `False` | Enables SQL query metrics. Adds `X-API-Query-Count` / `X-API-Query-Time` headers and injects trace context into SQL comments. |
| `ANSIBLE_BASE_PROFILING_CPROFILE_DIR` | System temp directory (e.g. `/tmp`) | Directory where `.prof` files are written. Falls back to the system temp directory if the configured path is not writable. |
| `ANSIBLE_BASE_PROFILING_EXCLUDE_PATHS` | `['/api/gateway/v1/ping/', '/up', '/v3/discovery:']` | URL path prefixes to skip for cProfile and SQL profiling, even when the flags are enabled. Timing and trace context still apply to excluded paths. |

## Response Headers

| Header | When present | Description |
|---|---|---|
| `X-Request-ID` | Always | Unique request identifier. Echoes the client-provided value or generates a new UUID. |
| `X-API-Total-Time` | Always | Wall-clock request duration (e.g. `0.045s`). |
| `X-API-Profile-File` | `ANSIBLE_BASE_PROFILING_ENABLED` or `X-Enable-Profiling` header | Filesystem path to the `.prof` file **on the server**. The filename includes the request's `X-Request-ID`. |
| `X-API-Query-Count` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Number of SQL queries executed during the request. |
| `X-API-Query-Time` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Total time spent executing SQL queries (e.g. `0.012s`). |

> **Note:** cProfile has significant performance implications and is intended for temporary, live debugging sessions, not for permanent use in production environments.

> **Note:** Some security-conscious deployments may not want to expose internal node identifiers or filesystem paths. Ensure `ANSIBLE_BASE_PROFILING_ENABLED` is disabled before returning to production traffic.

> **Note:** When setting `ANSIBLE_BASE_PROFILING_CPROFILE_DIR`, ensure the application has write permissions to the directory. The directory will be created automatically if it doesn't exist, and the profiler will fall back to the system temp directory on write errors.

## X-Request-ID and Trace Propagation

The `X-Request-ID` header is the canonical request-tracking identifier across the platform. The middleware:

1. Reads the incoming `X-Request-ID` header (if present and a valid UUID).
2. Generates a new UUID if the header is missing or invalid.
3. Stores the ID in a `ContextVar` (`trace_id_var`) accessible throughout the request lifecycle.
4. Returns the ID on the response as `X-Request-ID`.

The existing `RequestIdFilter` reads `X-Request-ID` from the HTTP request headers independently. When the client provides a valid UUID header, both mechanisms use the same value. When no header is sent, the middleware generates a UUID into `trace_id_var`, but `RequestIdFilter` will not have access to it. The trace ID can be propagated to background tasks via the `trace_context` context manager (see below).

### SQL Query Context

When SQL profiling is enabled, SQL queries include trace context as comments (trace ID, route, origin) which appear in `pg_stat_activity` and slow query logs:
```sql
/* trace_id='b71696ed-...', route='api/v2/users/{pk}/', origin='request' */ SELECT ...
```

> **Note:** SQL profiling is most effective when used in combination with your database's slow query logging capabilities. For high-traffic environments, consider configuring your database to log only a percentage of queries to manage logging overhead.

## `DABProfiler`

For profiling non-HTTP contexts (background tasks, gRPC services), use `DABProfiler` directly:

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

`DABProfiler` always produces both timing and cProfile output. The output directory follows the resolution order: explicit `output_dir` kwarg > `ANSIBLE_BASE_PROFILING_CPROFILE_DIR` setting > system temp directory.

## `trace_context` for Background Tasks

For adding observability to non-HTTP contexts without the overhead of the `DABProfiler`, the `trace_context` context manager is the ideal tool. It ensures that background tasks can be traced with a unique request ID, just like the `ObservabilityMiddleware` does for web requests.

This is particularly useful for background tasks, such as those initiated by the controller's dispatcher, where you want to correlate all log messages for a specific operation.

```python
from ansible_base.lib.logging.context import trace_context

def run_job(job_id, parent_trace_id=None):
    # Use the parent_trace_id if it exists; otherwise, a new one will be generated.
    # The origin is a string that identifies the source of the trace.
    with trace_context(origin='controller_dispatcher', trace_id=parent_trace_id):
        # All logging within this block shares the same trace_id.
        pass
```

## Visualizing Profile Data

The `.prof` files generated by the cProfile support can be analyzed with a variety of tools.

### SnakeViz

[SnakeViz](https://jiffyclub.github.io/snakeviz/) is a browser-based graphical viewer for the output of Python profilers.

```bash
pip install snakeviz
snakeviz /path/to/your/profile.prof
```

### pstats

The standard library `pstats` module can also be used to read and manipulate profile data.

```python
import pstats

p = pstats.Stats('/path/to/your/profile.prof')
p.sort_stats('cumulative').print_stats(20)
```
