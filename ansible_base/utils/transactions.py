from django.db import connection


def create_transaction(transaction_id):
    cursor = connection.cursor()
    cursor.execute(
        "PREPARE TRANSACTION %s;",
        [
            str(transaction_id),
        ],
    )
    cursor.close()


def commit_transaction(transaction_id):
    cursor = connection.cursor()
    cursor.execute(
        "COMMIT PREPARED %s;",
        [
            str(transaction_id),
        ],
    )
    cursor.close()


def rollback_transaction(transaction_id):
    cursor = connection.cursor()
    cursor.execute(
        "ROLLBACK PREPARED %s;",
        [
            str(transaction_id),
        ],
    )
    cursor.close()
