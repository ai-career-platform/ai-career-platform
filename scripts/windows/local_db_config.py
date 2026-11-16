"""Local-only DB settings loader for the Windows crawler PC.

Reads ONLY the ``*_LOCAL`` keys (Host_LOCAL, Port_LOCAL, Database_LOCAL, Username_LOCAL,
Password_LOCAL) from the repository-root ``.env``. Every other key in that file (staging SSH,
GCP, Slack webhook, ...) is ignored and never copied into ``os.environ``.

Values are validated to be a loopback host and the training database before use, and the
password is only ever handed to ``psycopg.connect(password=...)`` as a keyword argument, so no
URL is built, no special-character encoding is needed and nothing is printed or logged.
The admin (``postgres``) credentials are meant for one-time bootstrap only; the crawler itself
runs as ``crawler_local`` with a pgpass entry (see bootstrap_local_db.py).
"""
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_KEYS = ('Host_LOCAL', 'Port_LOCAL', 'Database_LOCAL', 'Username_LOCAL', 'Password_LOCAL')
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
TRAINING_DB = 'ai_career_crawler_training'


class UnsafeLocalConfig(ValueError):
    """Raised without ever including a secret value in the message."""


@dataclass(frozen=True)
class LocalAdmin:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    def connect(self, dbname=None, **kwargs):
        import psycopg
        return psycopg.connect(host=self.host, hostaddr='127.0.0.1', port=self.port,
                               dbname=dbname or self.dbname, user=self.user, password=self.password,
                               connect_timeout=5, **kwargs)


def _parse_env(path):
    values = {}
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key not in LOCAL_KEYS:
            continue  # never touch non-local keys
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values[key] = value
    return values


def load_local_admin(env_path=None):
    values = _parse_env(env_path or REPO_ROOT / '.env')
    missing = [k for k in LOCAL_KEYS if not values.get(k)]
    if missing:
        raise UnsafeLocalConfig(f'Missing .env keys: {", ".join(missing)}')
    if values['Host_LOCAL'] not in LOOPBACK:
        raise UnsafeLocalConfig('Host_LOCAL must be a loopback address')
    if values['Database_LOCAL'] != TRAINING_DB:
        raise UnsafeLocalConfig(f'Database_LOCAL must be {TRAINING_DB}')
    try:
        port = int(values['Port_LOCAL'])
    except ValueError:
        raise UnsafeLocalConfig('Port_LOCAL must be an integer') from None
    return LocalAdmin(values['Host_LOCAL'], port, values['Database_LOCAL'], values['Username_LOCAL'],
                      values['Password_LOCAL'])
