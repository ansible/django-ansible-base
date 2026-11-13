import datetime
import textwrap

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, utils
from django.utils import timezone


class Command(BaseCommand):
    help = 'Generates a report on database table sizes and query activity for PostgreSQL.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            self.stdout.write(self.style.ERROR("This command is only supported for PostgreSQL databases."))
            return

        self.stdout.write(self.style.SUCCESS('Database Diagnostic Report'))
        self.stdout.write(self.style.NOTICE(f"Report generated at: {timezone.now().isoformat()}"))

        self.print_table_sizes()
        self.print_model_report()
        self.print_pg_stat_activity()
        self.print_pg_stat_statements()

    def print_table_sizes(self):
        self.stdout.write("\n" + self.style.SUCCESS('Table Sizes and Row Counts'))
        self.stdout.write(self.style.NOTICE("Based on database schema inspection."))

        query = textwrap.dedent("""
            SELECT table_name, pg_size_pretty(pg_total_relation_size(quote_ident(table_name))),
                   (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text::bigint
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name NOT LIKE 'pg_%%' ORDER BY 3 DESC;
        """).strip()

        self.stdout.write(self.style.SQL_KEYWORD(f"Running query:\n{query}"))

        with connection.cursor() as cursor:
            cursor.execute(query)
            self.stdout.write(f"{'Table Name':<50} {'Size':<20} {'Rows':<10}")
            self.stdout.write(f"{'--'*50} {'--'*20} {'--'*10}")
            for row in cursor:
                self.stdout.write(f"{row[0]:<50} {row[1]:<20} {row[2]:<10}")

    def print_model_report(self):
        self.stdout.write("\n" + self.style.SUCCESS('Model Object Counts'))
        self.stdout.write(self.style.NOTICE("Based on the Django model layer."))
        all_models = apps.get_models()
        self.stdout.write(f"\n{'Model (app.model)':<50} {'Total Objects':<15}")
        self.stdout.write(f"{'--'*50} {'--'*15}")
        for model in sorted(all_models, key=lambda m: m._meta.label):
            if model._meta.proxy:
                continue
            try:
                self.stdout.write(f"{model._meta.label:<50} {model.objects.count():<15}")
            except Exception:
                self.stdout.write(f"{model._meta.label:<50} {'Error counting':<15}")

    def print_pg_stat_activity(self):
        self.stdout.write("\n" + self.style.SUCCESS('PostgreSQL Activity Report (pg_stat_activity)'))

        def run_and_print_report(title, query, age_logic):
            self.stdout.write("\n" + self.style.NOTICE(title))
            self.stdout.write(self.style.SQL_KEYWORD(f"Running query:\n{textwrap.dedent(query).strip()}"))
            header = f"{'PID':<10} {'User':<15} {'Client':<20} {'State':<15} {'Wait Event':<25} {age_logic['header']:<25} {'Query Snippet'}"
            header_underline = f"{'--'*10} {'--'*15} {'--'*20} {'--'*15} {'--'*25} {'--'*25} {'--'*80}"
            with connection.cursor() as cursor:
                try:
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    if not rows:
                        self.stdout.write("No matching activity found.")
                        return
                    self.stdout.write(header)
                    self.stdout.write(header_underline)
                    for row in rows:
                        pid, user, client, state, wait_type, wait_event, query_start, state_change, backend_start, query_text = row
                        now = timezone.now()
                        age = "N/A"
                        ts = row[age_logic['timestamp_index']]
                        if ts:
                            age = now - ts
                        age_str = str(age).split('.')[0] if isinstance(age, datetime.timedelta) else "N/A"
                        wait_full = f"{wait_type or ''}:{wait_event or ''}".strip(':')
                        self.stdout.write(
                            f"{pid:<10} {user or '':<15} {str(client) or '':<20} {state or '':<15} {wait_full:<25} {age_str:<25} {query_text or ''}"
                        )
                except utils.DatabaseError as e:
                    self.stdout.write(self.style.ERROR(f"Could not query pg_stat_activity for '{title}': {e}"))

        base_query = (
            "SELECT pid, usename, client_addr, state, wait_event_type, wait_event, "
            "query_start, state_change, backend_start, left(query, 100) as query_snippet "
            "FROM pg_stat_activity WHERE state IS NOT NULL"
        )
        reports = [
            (
                'Top 10 Longest Running Active Queries',
                f"{base_query} AND state = 'active' ORDER BY query_start ASC LIMIT 10",
                {'header': 'Duration', 'timestamp_index': 6},
            ),
            (
                'Top 10 Oldest "Idle in Transaction" Connections',
                f"{base_query} AND state = 'idle in transaction' ORDER BY state_change ASC LIMIT 10",
                {'header': 'Idle Time', 'timestamp_index': 7},
            ),
            (
                'Top 10 Connections by Wait Time',
                f"{base_query} AND wait_event IS NOT NULL ORDER BY state_change ASC LIMIT 10",
                {'header': 'Wait Time', 'timestamp_index': 7},
            ),
            ('Top 10 Oldest Open Connections', f"{base_query} ORDER BY backend_start ASC LIMIT 10", {'header': 'Connection Age', 'timestamp_index': 8}),
        ]
        for title, query, age_logic in reports:
            run_and_print_report(title, query, age_logic)

    def print_pg_stat_statements(self):
        self.stdout.write("\n" + self.style.SUCCESS('PostgreSQL Statement Statistics (pg_stat_statements)'))
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';")
                if cursor.fetchone() is None:
                    self.stdout.write(self.style.ERROR("The 'pg_stat_statements' extension is not enabled."))
                    self.stdout.write(
                        "To enable it, add 'pg_stat_statements' to 'shared_preload_libraries' in your postgresql.conf, restart the database, and then run 'CREATE EXTENSION pg_stat_statements;'"
                    )
                    return
                cursor.execute("SELECT count(*) FROM pg_stat_statements;")
                if cursor.fetchone()[0] == 0:
                    self.stdout.write(self.style.WARNING("The 'pg_stat_statements' view is empty."))
                    return
                self.print_statement_report(cursor, "Top 10 Most Frequent Queries", "calls DESC", "Calls", "calls")
                self.print_statement_report(
                    cursor, "Top 10 Slowest Queries (by mean execution time)", "mean_exec_time DESC", "Mean Time (ms)", "mean_exec_time"
                )
                self.print_statement_report(
                    cursor, "Top 10 Queries by Total Execution Time (CPU)", "total_exec_time DESC", "Total Time (ms)", "total_exec_time"
                )
                self.print_statement_report(
                    cursor,
                    "Top 10 Queries by I/O Read",
                    "(shared_blks_read + local_blks_read + temp_blks_read) DESC",
                    "Blocks Read",
                    "(shared_blks_read + local_blks_read + temp_blks_read)",
                )
                self.print_statement_report(
                    cursor,
                    "Top 10 Queries by Buffer Cache Usage (Memory)",
                    "(shared_blks_hit + shared_blks_read) DESC",
                    "Shared Blocks Hit+Read",
                    "(shared_blks_hit + shared_blks_read)",
                )
            except utils.DatabaseError as e:
                self.stdout.write(self.style.ERROR(f"Could not query pg_stat_statements: {e}"))

    def print_statement_report(self, cursor, title, order_by, metric_name, metric_col):
        self.stdout.write("\n" + self.style.NOTICE(title))
        query = f"SELECT {metric_col}, query FROM pg_stat_statements ORDER BY {order_by} LIMIT 10;"
        self.stdout.write(self.style.SQL_KEYWORD(f"Running query:\n{query}"))
        try:
            cursor.execute(query)
            self.stdout.write(f"{metric_name:<25} {'Query Snippet'}")
            self.stdout.write(f"{'--'*25} {'--'*100}")
            for row in cursor:
                metric, query_text = row
                query_snippet = textwrap.shorten(' '.join(query_text.split()), width=100, placeholder="...")
                metric_str = f"{metric:,.2f}" if isinstance(metric, float) else f"{metric:,}"
                self.stdout.write(f"{metric_str:<25} {query_snippet}")
        except utils.DatabaseError as e:
            self.stdout.write(self.style.ERROR(f"Could not generate report '{title}': {e}"))