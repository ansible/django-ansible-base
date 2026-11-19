"Vendor detection helpers for database-agnostic code."


def is_mssql(db_connection) -> bool:
    "Return True if db_connection (a Django connection wrapper) is SQL Server."
    return db_connection.vendor == "microsoft"
