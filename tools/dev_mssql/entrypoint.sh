#!/bin/bash

# Start SQL Server in the background
/opt/mssql/bin/sqlservr &

# Wait quietly for local availability to run the initialization script
until /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" -C &>/dev/null; do
    sleep 1
done

# Run setup script
echo "SQL Server ready. Running setup.sql..."
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -i setup.sql -C

# Keep container alive and let Dockerfile HEALTHCHECK take over
wait
