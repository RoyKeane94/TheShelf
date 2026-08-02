"""SQLite pragmas applied once per connection.

Django's sqlite backend has no init_command the way MySQL does, so we set WAL and
friends on the connection_created signal. Litestream replicates the WAL; keep
synchronous at NORMAL so the write cost stays honest.
"""

from django.db.backends.signals import connection_created


def _set_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA foreign_keys=ON;")


def install():
    connection_created.connect(_set_sqlite_pragmas)
