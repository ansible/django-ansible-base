FROM mirror.gcr.io/library/postgres:15

ENV POSTGRES_DB=dab_db
ENV POSTGRES_USER=dab
ENV POSTGRES_PASSWORD=dabing

USER postgres

EXPOSE 5432

HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD ["sh", "-c", "pg_isready -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\""]