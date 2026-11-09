"""T71 integration regression; load the mock SQL in a disposable DB first.

D1_TEST_ONLY=YES and PGDATABASE containing test/ci/local/tmp/dev are required.
Uses psql on PATH and normal PGHOST/PGPORT/PGUSER settings, never a fixed server.
"""
import os
import re
import subprocess
import time
import unittest
import uuid


class ConsentConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = os.environ.get("PGDATABASE", "")
        if (os.environ.get("D1_TEST_ONLY") != "YES"
                or not re.search(r"test|ci|local|tmp|dev", name, re.I)
                or re.search(r"stag|prod|live", name, re.I)):
            raise unittest.SkipTest("disposable test DB and D1_TEST_ONLY=YES required")

    def sql(self, sql, app="t71-observer"):
        env = dict(os.environ, PGAPPNAME=app)
        return subprocess.check_output(
            ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
            env=env, text=True, encoding="utf-8", stderr=subprocess.PIPE,
        ).strip()

    def race(self, first, second):
        uid = str(uuid.uuid4())
        self.sql(f"INSERT INTO behavior_mock.users VALUES ('{uid}'); "
                 f"SELECT behavior_mock.record_consent('{uid}', 'behavior_tracking', true)")
        collect = (f"SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event("
                   f"'{uid}', 'page.view', now(), '{{}}')")
        withdraw = (f"SET ROLE t71_consent; SELECT behavior_mock.record_consent("
                    f"'{uid}', 'behavior_tracking', false)")
        commands = {"collect": collect, "withdraw": withdraw}
        app = f"t71-race-{uuid.uuid4().hex}"
        process = subprocess.Popen(
            ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c",
             f"BEGIN; {commands[first]}; SELECT pg_sleep(2); COMMIT;"],
            env=dict(os.environ, PGAPPNAME=app), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            deadline = time.monotonic() + 10
            while self.sql(f"SELECT count(*) FROM pg_stat_activity WHERE "
                          f"application_name='{app}' AND wait_event='PgSleep'") != "1":
                if process.poll() is not None or time.monotonic() > deadline:
                    self.fail("first transaction did not reach synchronization point")
                time.sleep(0.02)
            result = self.sql(commands[second])
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(self.sql("SELECT count(*) FROM behavior_mock.behavior_events "
                                     f"WHERE user_id='{uid}'"), "0")
            if second == "collect":
                self.assertEqual(result, "blocked_no_consent")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            self.sql(f"DELETE FROM behavior_mock.users WHERE user_id='{uid}'")

    def test_collect_in_flight_then_withdraw(self):
        self.race("collect", "withdraw")

    def test_withdraw_in_flight_then_collect(self):
        self.race("withdraw", "collect")


if __name__ == "__main__":
    unittest.main()
