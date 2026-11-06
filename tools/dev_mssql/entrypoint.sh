#!/bin/bash

# Start SQL Server in the background
/opt/mssql/bin/sqlservr &
SQLSERVR_PID=$!

# As PID 1, forward container termination signals to SQL Server
trap 'kill "$SQLSERVR_PID" 2>/dev/null' TERM INT

# Wait quietly for local availability to run the initialization script
until /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" -C &>/dev/null; do
    # stop waiting if the server died before becoming ready
    if ! kill -0 "$SQLSERVR_PID" 2>/dev/null; then
        echo "SQL Server exited before becoming ready" >&2
        exit 1
    fi
    sleep 1
done

# Run setup script
echo "SQL Server ready. Running setup.sql..."
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -i setup.sql -C

# Wait on the server process itself; the trap above turns a container stop
# into a clean SQL Server shutdown instead of leaving it orphaned. A trapped
# signal interrupts wait before sqlservr exits, so keep waiting until it is
# actually gone — otherwise PID 1 exits and the container kills SQL Server
# mid-shutdown.
wait "$SQLSERVR_PID"
while kill -0 "$SQLSERVR_PID" 2>/dev/null; do
    wait "$SQLSERVR_PID" 2>/dev/null || true
done
