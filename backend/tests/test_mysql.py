"""MySQL migration checks against the isolated database created by tests."""
import unittest

import tests  # Initialize the isolated database even when discovery omits -t .

from app.db.session import connect, init_schema, one, set_config, get_config


class MySQLTest(unittest.TestCase):
    def test_unicode_longtext_upsert_and_rollback(self):
        conn = connect()
        try:
            init_schema(conn)
            init_schema(conn)  # Re-running initialization must preserve existing tables.
            original = one(conn, "SELECT COUNT(*) n FROM topic")["n"]
            with conn.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                self.assertTrue(cursor.fetchone()[0].startswith("8."))
            text = "中文餐饮🍜 ' % ? " * 6000
            result = conn.execute(
                "INSERT INTO topic(name, keywords, channels) VALUES(%s,%s,%s)",
                (text, "[]", "{}"),
            )
            self.assertEqual(one(conn, "SELECT name FROM topic WHERE id=%s", (result.lastrowid,))["name"], text)
            set_config(conn, "mysql_test", "first")
            set_config(conn, "mysql_test", "updated🍜")
            self.assertEqual(get_config(conn)["mysql_test"], "updated🍜")
            conn.rollback()
            self.assertEqual(one(conn, "SELECT COUNT(*) n FROM topic")["n"], original)
            self.assertNotIn("mysql_test", get_config(conn))
        finally:
            conn.close()
