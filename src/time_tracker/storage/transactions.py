"""Explicit transactions, including rollback-safe nested repository operations."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Use BEGIN IMMEDIATE, or a savepoint inside an existing transaction."""
    nested = connection.in_transaction
    savepoint = f"sp_{uuid4().hex}"
    connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
    try:
        yield connection
        connection.execute(f"RELEASE SAVEPOINT {savepoint}" if nested else "COMMIT")
    except BaseException:
        if connection.in_transaction:
            if nested:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.execute("ROLLBACK")
        raise
