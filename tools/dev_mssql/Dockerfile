FROM mcr.microsoft.com/mssql/server:2025-latest

ENV ACCEPT_EULA=Y
ENV MSSQL_SA_PASSWORD=DabingPass!1234

USER root

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY entrypoint.sh setup.sql /usr/src/app/
RUN chmod +x /usr/src/app/entrypoint.sh

USER mssql
EXPOSE 1433

HEALTHCHECK --interval=3s --timeout=2s --start-period=2s --retries=5 \
  CMD /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" -C || exit 1

ENTRYPOINT ["./entrypoint.sh"]
