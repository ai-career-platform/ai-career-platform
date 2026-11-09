import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from crawler.storage import staging


class StagingDatabaseTests(unittest.TestCase):
    def test_only_explicit_staging_database_and_role(self):
        good = 'postgresql://crawler_staging@db/ai_career_crawler_training'
        staging.validate_staging_dsn(good)
        for bad in (good.replace('@db/', '@example.com/'), good.replace('crawler_staging', 'postgres'),
                    good.replace('ai_career_crawler_training', 'ai_career_poc'), good + '?host=other'):
            with self.assertRaises(ValueError):
                staging.validate_staging_dsn(bad)

    def test_mode_is_explicit_and_unknown_mode_rejected(self):
        with patch.dict('os.environ', {'CRAWLER_DB_MODE': 'staging', 'CRAWLER_STAGING_DATABASE_URL': 'test-only'}):
            self.assertEqual(staging.database_url(), 'test-only')
        with patch.dict('os.environ', {'CRAWLER_DB_MODE': 'production'}):
            with self.assertRaises(ValueError):
                staging.database_url()

    def test_privileged_staging_role_is_rejected_and_closed(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            'ai_career_crawler_training', 'crawler_staging', False, True, False, False)
        driver = SimpleNamespace(connect=MagicMock(return_value=connection))
        with patch.dict('sys.modules', {'psycopg': driver}), patch('socket.gethostbyname', return_value='127.0.0.1'):
            with self.assertRaises(ValueError):
                staging.connect_staging_db('postgresql://crawler_staging@db/ai_career_crawler_training')
        connection.close.assert_called_once()

    def test_staging_connection_pins_resolved_hostaddr(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            'ai_career_crawler_training', 'crawler_staging', False, False, False, False)
        driver = SimpleNamespace(connect=MagicMock(return_value=connection))
        dsn = 'postgresql://crawler_staging@db/ai_career_crawler_training'
        with patch.dict('sys.modules', {'psycopg': driver}), patch('socket.gethostbyname', return_value='127.0.0.1'):
            self.assertIs(staging.connect_staging_db(dsn), connection)
        driver.connect.assert_called_once_with(dsn, hostaddr='127.0.0.1', connect_timeout=5)
