# PostgreSQL Diagnostic Reporting

This document describes the `database_resource_report` management command, a tool for analyzing PostgreSQL database table sizes and query activity.

**Note:** This command is only compatible with PostgreSQL.

## How to Run the Command

To make the command available in your project, ensure that the `ansible_base.resource_registry` application is included in your `INSTALLED_APPS` setting in your project's `settings.py`.

```python
# settings.py
INSTALLED_APPS = [
    ...
    'ansible_base.resource_registry',
    ...
]
```

Once the app is installed, you can run the command using your project's `manage.py` script. The exact invocation may vary depending on the consuming application.

**AWX Development Environment:**
```bash
# Run from within the tools_awx_1 container
awx-manage database_resource_report
```

**AAP Gateway Environment:**
```bash
# Run from within the aap-gateway container
aap-gateway-manage database_resource_report
```

The command accepts no arguments and will run all available reports sequentially.

---

## Understanding the Report Output

The report is divided into several sections, providing a comprehensive overview of the database from different perspectives. Each section also includes the literal SQL query that was run to generate the data.

### 1. Table Sizes and Row Counts

This section provides a raw, physical overview of the database tables.

- **What it shows:** A list of all tables in the `public` schema, their total size on disk (including indexes and TOAST data), and the estimated number of rows.
- **How it's sorted:** By the number of rows, in descending order.
- **Usefulness:** Helps you quickly identify the largest tables in your database, which are often the most important ones to monitor for bloat and performance.

### 2. Model Object Counts

This section provides an application-level view of the data, based on Django's models.

- **What it shows:** A list of all registered Django models in the application and the total number of objects (rows) for each.
- **How it's sorted:** Alphabetically by the model's label (`app_name.ModelName`).
- **Usefulness:** Helps you understand data distribution from the perspective of the application's logic. It can also highlight tables that are not managed by a Django model.

### 3. PostgreSQL Activity Report (`pg_stat_activity`)

This section provides a **real-time snapshot** of all current connections and their activity. It is only available for PostgreSQL databases. It is broken down into several sorted views to help diagnose immediate issues.

#### Top 10 Longest Running Active Queries
- **What it shows:** Queries that are currently in the `active` state, sorted by how long they have been running.
- **Usefulness:** This is the most critical report for diagnosing live performance problems. It immediately shows you which queries are currently consuming resources and may be stuck or running inefficiently.

#### Top 10 Oldest "Idle in Transaction" Connections
- **What it shows:** Connections that have an open transaction (`BEGIN` has been issued) but are not currently running a query.
- **Usefulness:** These connections can be dangerous. They can hold locks for long periods, blocking other queries, and prevent database cleanup processes (`VACUUM`) from working, which leads to table bloat. This report helps you find and investigate them.

#### Top 10 Connections by Wait Time
- **What it shows:** Connections that are currently waiting for a specific event (e.g., waiting for a lock, for disk I/O, or for the client to send data).
- **Usefulness:** This report directly identifies bottlenecks. If many queries are waiting on the same type of event, it points to a specific area of contention.

#### Top 10 Oldest Open Connections
- **What it shows:** All connections sorted by the time they were first established.
- **Usefulness:** A general health check that can help you spot problems with connection pooling (applications not closing connections properly) or find very old, forgotten sessions.

### 4. PostgreSQL Statement Statistics (`pg_stat_statements`)

This section provides **historical performance data** about all queries that have been run against the database. It is only available for PostgreSQL and requires the `pg_stat_statements` extension to be enabled.

#### Enabling `pg_stat_statements`
If the extension is not enabled, the report will provide instructions on how to do so. You must be a database superuser. The order of operations is important.

1.  **Configure the server:** Add or modify the `shared_preload_libraries` line in your `postgresql.conf` file. This tells PostgreSQL to load the extension into memory on the next startup.
    ```ini
    shared_preload_libraries = 'pg_stat_statements'
    ```
2.  **Restart the PostgreSQL server:** This is required to apply the configuration change and load the library.
3.  **Create the extension:** Connect to your database and run `CREATE EXTENSION pg_stat_statements;`. This command initializes the views and functions for the extension, which can only be done after the library has been loaded.

#### The Reports
- **Top 10 Most Frequent Queries:** Shows which queries are executed most often. Optimizing these can have a large impact on overall performance.
- **Top 10 Slowest Queries (by mean execution time):** Shows the queries that take the longest on average to complete.
- **Top 10 Queries by Total Execution Time (CPU):** This is often the most important report. It shows which queries have consumed the most total database time (i.e., `frequency * average_time`). These are the best candidates for optimization.
- **Top 10 Queries by I/O Read & Buffer Cache Usage:** These reports show which queries are the most demanding on disk and memory resources, respectively. They can help identify queries that would benefit from new indexes or memory tuning.
