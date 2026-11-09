"""Explicit container-only DB opt-in; never creates a database or schema."""
import os
from urllib.parse import urlsplit, unquote
from crawler.storage.postgres import connect_local_training_db, UnsafeDatabaseTarget


def using_staging():
    mode = os.environ.get('CRAWLER_DB_MODE', 'local')
    if mode not in ('local', 'staging'):
        raise UnsafeDatabaseTarget('Unsupported crawler database mode')
    return mode == 'staging'


def database_url():
    key = 'CRAWLER_STAGING_DATABASE_URL' if using_staging() else 'CRAWLER_LOCAL_DATABASE_URL'
    return os.environ.get(key, '')


def validate_staging_dsn(dsn):
    try:
        parts = urlsplit(dsn)
        valid = (parts.scheme in ('postgres', 'postgresql') and parts.hostname == 'db'
                 and parts.port in (None, 5432) and not parts.query and not parts.fragment
                 and parts.path == '/ai_career_crawler_training'
                 and unquote(parts.username or '') == 'crawler_staging')
    except ValueError:
        valid = False
    if not valid:
        raise UnsafeDatabaseTarget('Use the dedicated crawler_staging role and training DB on db:5432')


def connect_staging_db(dsn):
    validate_staging_dsn(dsn)
    import psycopg
    # Explicit hostaddr prevents PGHOSTADDR from overriding the selected host.
    import socket
    connection = psycopg.connect(dsn, hostaddr=socket.gethostbyname('db'), connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database(), current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = current_user')
            if cursor.fetchone() != ('ai_career_crawler_training', 'crawler_staging', False, False, False, False):
                raise UnsafeDatabaseTarget('Unexpected database identity or superuser role')
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def connect_configured_database():
    dsn = database_url()
    return connect_staging_db(dsn) if using_staging() else connect_local_training_db(dsn)
