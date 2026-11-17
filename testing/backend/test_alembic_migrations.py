"""Tests for Alembic migration upgrade/downgrade from empty DB and schema constraints.

W5.5 PL1 additions (`docs/specs/personalized-learning/data-and-api.md` §2.7):
`0004→head` and `head→0004→head` cases, the `personalized_mastery` CHECK-change
assertion, and the fresh-vs-upgraded schema agreement (the drift gate is the
idempotent second `upgrade head` plus the schema round-trip).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from db import (
    LATEST_REVISION,
    DatabaseEngine,
    downgrade_db,
    get_current_revision,
    get_heads,
    upgrade_db,
)
from db.schema import (
    ADDENDA_TABLES_0002,
    ALL_TABLES,
    CORE_TABLES_0001,
    FULL_FRONTEND_TABLES_0003,
)
from db.schema_assessment import PRACTICE_TEST_TABLES_0004
from db.schema_personalized import PERSONALIZED_TABLES_0005
from db.uuid7 import uuid7_str


def _insert_user(eng: DatabaseEngine, email: str) -> str:
    user_id = uuid7_str()
    eng.execute(
        "INSERT INTO users (user_id, email, board, language, role) "
        "VALUES (?, ?, 'CBSE', 'en-IN', 'student')",
        (user_id, email),
    )
    return user_id


def _table_sql(eng: DatabaseEngine, table: str) -> str:
    row = eng.fetchone(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    )
    assert row is not None, f"table {table} missing"
    return str(row["sql"])


class TestAlembicMigrations(unittest.TestCase):
    def test_linear_history_single_head_and_version_files(self) -> None:
        heads = get_heads()
        self.assertEqual(
            heads,
            ["0005_personalized_learning"],
            "Alembic history must have exactly one head",
        )
        self.assertEqual(LATEST_REVISION, "0005_personalized_learning")

        versions_dir = Path("alembic/versions")
        py_files = sorted(versions_dir.glob("*.py"))
        self.assertEqual(len(py_files), 5)
        for path in py_files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            fn_names = {
                node.name for node in tree.body if isinstance(node, ast.FunctionDef)
            }
            self.assertIn("upgrade", fn_names)
            self.assertIn("downgrade", fn_names)

    def test_upgrade_from_empty_db_and_reversible_downgrade(self) -> None:
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        self.assertIsNone(get_current_revision(eng))

        # Step 1: Upgrade to 0001 -> 20 core tables created
        rev1 = upgrade_db(eng, "0001")
        self.assertEqual(rev1, "0001")
        tables_0001 = set(eng.list_tables())
        for tbl in CORE_TABLES_0001:
            self.assertIn(tbl, tables_0001)
        for tbl in ADDENDA_TABLES_0002:
            self.assertNotIn(tbl, tables_0001)
        for tbl in FULL_FRONTEND_TABLES_0003:
            self.assertNotIn(tbl, tables_0001)

        # Step 2: Upgrade to head -> all tables + seeds present
        rev2 = upgrade_db(eng, "head")
        self.assertEqual(rev2, "0005_personalized_learning")
        tables_head = set(eng.list_tables())
        for tbl in ALL_TABLES:
            self.assertIn(tbl, tables_head)
        device_cols = {row["name"] for row in eng.fetchall("PRAGMA table_info(device)")}
        self.assertIn("user_id", device_cols)

        # Verify guard_profile singleton seed and locale_fallback seed
        gp = eng.fetchone("SELECT * FROM guard_profile WHERE id = 1")
        assert gp is not None
        self.assertEqual(gp["mode"], "normal")
        self.assertEqual(float(gp["global_tranche"]), 1000.0)
        self.assertEqual(float(gp["per_user_cap"]), 30.0)

        locales = eng.fetchall("SELECT locale FROM locale_fallback")
        self.assertEqual(len(locales), 11)

        # Step 3: Downgrade to 0004 drops only the 0005 additions
        down4 = downgrade_db(eng, "0004_practice_speaking_tests")
        self.assertEqual(down4, "0004_practice_speaking_tests")
        tables_0004 = set(eng.list_tables())
        for tbl in PRACTICE_TEST_TABLES_0004:
            self.assertIn(tbl, tables_0004)
        for tbl in PERSONALIZED_TABLES_0005:
            self.assertNotIn(tbl, tables_0004)

        # Step 4: Downgrade to 0003 drops only the 0004 additions
        down3 = downgrade_db(eng, "0003_full_frontend")
        self.assertEqual(down3, "0003_full_frontend")
        tables_0003 = set(eng.list_tables())
        for tbl in FULL_FRONTEND_TABLES_0003:
            self.assertIn(tbl, tables_0003)
        for tbl in PRACTICE_TEST_TABLES_0004:
            self.assertNotIn(tbl, tables_0003)

        # Step 5: Downgrade to 0002 drops only the 0003 additions
        down2 = downgrade_db(eng, "0002")
        self.assertEqual(down2, "0002")
        tables_0002 = set(eng.list_tables())
        for tbl in ADDENDA_TABLES_0002:
            self.assertIn(tbl, tables_0002)
        for tbl in FULL_FRONTEND_TABLES_0003:
            self.assertNotIn(tbl, tables_0002)
        device_cols = {row["name"] for row in eng.fetchall("PRAGMA table_info(device)")}
        self.assertNotIn("user_id", device_cols)

        # Step 6: Downgrade to 0001, then base, then re-upgrade to head
        down1 = downgrade_db(eng, "0001")
        self.assertEqual(down1, "0001")
        down_base = downgrade_db(eng, "base")
        self.assertIsNone(down_base)
        self.assertEqual(set(eng.list_tables()), {"alembic_version"})

        re_up = upgrade_db(eng, "head")
        self.assertEqual(re_up, "0005_personalized_learning")
        self.assertTrue(set(ALL_TABLES).issubset(set(eng.list_tables())))

    def test_upgrade_from_0003_to_head_is_additive_only(self) -> None:
        """A database already serving the frontend keeps every 0003 row and table."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        self.assertEqual(upgrade_db(eng, "0003_full_frontend"), "0003_full_frontend")
        user_id = _insert_user(eng, "kept@example.com")
        self.assertEqual(upgrade_db(eng, "head"), "0005_personalized_learning")
        kept = eng.fetchone("SELECT email FROM users WHERE user_id = ?", (user_id,))
        assert kept is not None
        self.assertEqual(kept["email"], "kept@example.com")
        self.assertIn("question_bank", set(eng.list_tables()))

    def test_upgrade_from_0004_to_head_adds_personalized_learning(self) -> None:
        """0004→head: PL tables appear and the mastery progress kind becomes valid.

        A database created by the CURRENT 0003 DDL already carries the widened
        CHECK (that is the drift agreement), so the test first narrows the
        `kind` vocabulary the way a REAL pre-0005 database looks (the exact
        rebuild 0005's down migration performs), then asserts the upgrade path
        widens it. The inserted `personalized_mastery` row after the upgrade IS
        the assertion that the CHECK actually changed (data-and-api.md §2.7).
        """
        from db.schema_personalized import _rebuild_progress_event_sqlite

        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        self.assertEqual(
            upgrade_db(eng, "0004_practice_speaking_tests"),
            "0004_practice_speaking_tests",
        )
        user_id = _insert_user(eng, "pl1@example.com")
        eng.execute(
            "INSERT INTO progress_event (event_id, user_id, kind, chapter_id) "
            "VALUES (?, ?, 'lesson_complete', 'class-10-light')",
            (uuid7_str(), user_id),
        )
        # Make this database look like a real pre-0005 0004 database (old CHECK).
        for stmt in _rebuild_progress_event_sqlite(
            "('lesson_block_view', 'lesson_complete', 'practice_answer', "
            "'test_submit', 'speaking_attempt', 'bookmark_add', 'bookmark_remove')"
        ):
            eng.execute(stmt)
        # The new kind must NOT be valid on the old vocabulary.
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "INSERT INTO progress_event (event_id, user_id, kind) "
                "VALUES (?, ?, 'personalized_mastery')",
                (uuid7_str(), user_id),
            )
        self.assertEqual(upgrade_db(eng, "head"), "0005_personalized_learning")
        tables_head = set(eng.list_tables())
        for tbl in PERSONALIZED_TABLES_0005:
            self.assertIn(tbl, tables_head)
        # Pre-existing evidence survives the rebuild; the new kind is accepted.
        kept_rows = eng.fetchall(
            "SELECT kind FROM progress_event WHERE user_id = ?", (user_id,)
        )
        self.assertEqual([r["kind"] for r in kept_rows], ["lesson_complete"])
        eng.execute(
            "INSERT INTO progress_event (event_id, user_id, kind, chapter_id, concept_id, payload) "
            "VALUES (?, ?, 'personalized_mastery', 'class-10-light', 'conc-1', '{\"status\": \"mastered\"}')",
            (uuid7_str(), user_id),
        )
        # The personalized rate-limit families are valid too (abuse.py §4.1).
        eng.execute(
            "INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, count, expires_at) "
            "VALUES ('k', 'personalized_turn', 'w', 1, 'e')"
        )
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, count, expires_at) "
                "VALUES ('k2', 'not_a_family', 'w', 1, 'e')"
            )

    def test_downgrade_head_to_0004_reverts_checks_and_tables(self) -> None:
        """head→0004→head: CHECK vocabularies revert and restore; tables return."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        user_id = _insert_user(eng, "down@example.com")
        eng.execute(
            "INSERT INTO progress_event (event_id, user_id, kind) "
            "VALUES (?, ?, 'personalized_mastery')",
            (uuid7_str(), user_id),
        )
        self.assertEqual(
            downgrade_db(eng, "0004_practice_speaking_tests"),
            "0004_practice_speaking_tests",
        )
        for tbl in PERSONALIZED_TABLES_0005:
            self.assertNotIn(tbl, set(eng.list_tables()))
        # The 0005-owned mastery events are explicitly deleted by the downgrade;
        # the pre-0005 kinds are preserved.
        kinds = [r["kind"] for r in eng.fetchall("SELECT kind FROM progress_event")]
        self.assertEqual(kinds, [])
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "INSERT INTO progress_event (event_id, user_id, kind) "
                "VALUES (?, ?, 'personalized_mastery')",
                (uuid7_str(), user_id),
            )
        self.assertEqual(upgrade_db(eng, "head"), "0005_personalized_learning")
        eng.execute(
            "INSERT INTO progress_event (event_id, user_id, kind) "
            "VALUES (?, ?, 'personalized_mastery')",
            (uuid7_str(), user_id),
        )

    def test_second_upgrade_head_is_idempotent_and_schemas_agree(self) -> None:
        """Drift gate: a fresh head DB and a 0004→head DB agree on the schema.

        `db/schema.py`'s progress_event/abuse_bucket CHECKs are updated in the
        same PR as 0005, so upgrading an old database and creating a new one
        must land on the same shape and vocabulary (data-and-api.md §2.7). The
        comparison is semantic — column sets plus which kinds/families are
        accepted and rejected — because the SQLite rebuild path emits its own
        CREATE text.
        """
        fresh = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        self.assertEqual(upgrade_db(fresh, "head"), "0005_personalized_learning")
        self.assertEqual(upgrade_db(fresh, "head"), "0005_personalized_learning")

        upgraded = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        upgrade_db(upgraded, "0004_practice_speaking_tests")
        self.assertEqual(upgrade_db(upgraded, "head"), "0005_personalized_learning")

        for eng in (fresh, upgraded):
            user_id = _insert_user(eng, f"drift-{id(eng)}@example.com")
            for table in ("progress_event", "abuse_bucket"):
                fresh_cols = [
                    r["name"] for r in fresh.fetchall(f"PRAGMA table_info({table})")
                ]
                up_cols = [
                    r["name"] for r in upgraded.fetchall(f"PRAGMA table_info({table})")
                ]
                self.assertEqual(fresh_cols, up_cols, table)
            # Same accepted vocabulary on both databases.
            eng.execute(
                "INSERT INTO progress_event (event_id, user_id, kind) "
                "VALUES (?, ?, 'personalized_mastery')",
                (uuid7_str(), user_id),
            )
            eng.execute(
                "INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, "
                "count, expires_at) VALUES ('k', 'personalized_turn', 'w', 1, 'e')"
            )
            with self.assertRaises(Exception):  # noqa: B017
                eng.execute(
                    "INSERT INTO progress_event (event_id, user_id, kind) "
                    "VALUES (?, ?, 'not_a_kind')",
                    (uuid7_str(), user_id),
                )
            with self.assertRaises(Exception):  # noqa: B017
                eng.execute(
                    "INSERT INTO abuse_bucket (bucket_key, endpoint_family, "
                    "window_start, count, expires_at) "
                    "VALUES ('k2', 'not_a_family', 'w', 1, 'e')"
                )

    def test_cli_only_revision_alias_continues_to_head(self) -> None:
        """A DB left at EX2's Alembic-only 0022 continues to head, not an error."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        upgrade_db(eng, "0002")
        eng.execute("DELETE FROM alembic_version")
        eng.execute(
            "INSERT INTO alembic_version (version_num) "
            "VALUES ('0022_translation_memory_c3')"
        )
        self.assertEqual(upgrade_db(eng, "head"), "0005_personalized_learning")
        self.assertIn("users", set(eng.list_tables()))

    def test_cli_only_revision_alias_downgrades_from_the_alias(self) -> None:
        """The alias applies to downgrade too: 0022 behaves as 0002, not ValueError."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        upgrade_db(eng, "0002")
        eng.execute("DELETE FROM alembic_version")
        eng.execute(
            "INSERT INTO alembic_version (version_num) "
            "VALUES ('0022_translation_memory_c3')"
        )
        self.assertEqual(downgrade_db(eng, "0002"), "0002")
        self.assertEqual(downgrade_db(eng, "base"), None)
        self.assertEqual(set(eng.list_tables()), {"alembic_version"})

    def test_schema_enforced_privacy_and_singleton_constraints(self) -> None:
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        dev_id = "11111111-1111-4111-8111-111111111111"
        eng.upsert_device(dev_id)
        sid = uuid7_str()
        eng.execute(
            """
            INSERT INTO session (session_id, device_pseudo_id, lang, mode, flags)
            VALUES (?, ?, 'en-IN', 'guide', '{}')
            """,
            (sid, dev_id),
        )

        # T11 schema constraint: voice_turn.audio_retained CHECK (audio_retained = false / 0)
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                """
                INSERT INTO voice_turn (
                    turn_id, session_id, turn_seq, modality, tutor_text, audio_retained
                ) VALUES (?, ?, 1, 'voice', 'hello', 1)
                """,
                (uuid7_str(), sid),
            )

        # Singleton constraint: guard_profile id CHECK (id = 1)
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute("INSERT INTO guard_profile (id, mode) VALUES (2, 'normal')")

    def test_personalized_schema_constraints_hold(self) -> None:
        """The PL1 CHECKs the spec pins: prefs length, turn cap, stage list, partial id."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        user_id = _insert_user(eng, "constraints@example.com")
        session_id = uuid7_str()
        eng.execute(
            """
            INSERT INTO personalized_session (
                session_id, user_id, title, class_level, chapter_id
            ) VALUES (?, ?, 'T', 10, 'class-10-light')
            """,
            (session_id, user_id),
        )
        # personal_instructions CHECK (length <= 500)
        eng.execute(
            "INSERT INTO user_preferences (user_id, personal_instructions) VALUES (?, ?)",
            (user_id, "x" * 500),
        )
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "INSERT INTO user_preferences (user_id, personal_instructions) VALUES (?, ?)",
                (uuid7_str(), "x" * 501),
            )
        # turn_count CHECK (0..60)
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "UPDATE personalized_session SET turn_count = 61 WHERE session_id = ?",
                (session_id,),
            )
        # stage vocabulary
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "UPDATE personalized_session SET stage = 'invented' WHERE session_id = ?",
                (session_id,),
            )
        # partial unique: two NULL client ids are fine; a duplicate non-NULL is not
        eng.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind) "
            "VALUES (?, ?, 0, 'tutor', 'text')",
            (uuid7_str(), session_id),
        )
        eng.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind) "
            "VALUES (?, ?, 1, 'tutor', 'text')",
            (uuid7_str(), session_id),
        )
        with self.assertRaises(Exception):  # noqa: B017
            eng.execute(
                "INSERT INTO personalized_message (message_id, session_id, turn_index, "
                "client_turn_id, role, kind) VALUES (?, ?, 2, 'dup-1', 'tutor', 'text')",
                (uuid7_str(), session_id),
            )
            eng.execute(
                "INSERT INTO personalized_message (message_id, session_id, turn_index, "
                "client_turn_id, role, kind) VALUES (?, ?, 3, 'dup-1', 'tutor', 'text')",
                (uuid7_str(), session_id),
            )

    def test_account_cascade_and_quota_rows_survive_no_user_leak(self) -> None:
        """FK shape: deleting a user removes prefs/sessions/usage; quota rows too."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        user_id = _insert_user(eng, "cascade@example.com")
        eng.execute(
            "INSERT INTO user_preferences (user_id, personal_instructions) VALUES (?, 'hi')",
            (user_id,),
        )
        session_id = uuid7_str()
        eng.execute(
            """
            INSERT INTO personalized_session (
                session_id, user_id, title, class_level, chapter_id
            ) VALUES (?, ?, 'T', 9, 'class-9-motion')
            """,
            (session_id, user_id),
        )
        eng.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind) "
            "VALUES (?, ?, 0, 'student', 'text')",
            (uuid7_str(), session_id),
        )
        eng.execute(
            "INSERT INTO personalized_usage (usage_id, user_id, session_id) VALUES (?, ?, ?)",
            (uuid7_str(), user_id, session_id),
        )
        eng.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.assertIsNone(
            eng.fetchone(
                "SELECT 1 AS x FROM user_preferences WHERE user_id = ?", (user_id,)
            )
        )
        self.assertIsNone(
            eng.fetchone(
                "SELECT 1 AS x FROM personalized_session WHERE user_id = ?", (user_id,)
            )
        )
        message_count = eng.fetchone("SELECT COUNT(*) AS c FROM personalized_message")
        usage_count = eng.fetchone("SELECT COUNT(*) AS c FROM personalized_usage")
        assert message_count is not None and usage_count is not None
        self.assertEqual(int(message_count["c"]), 0)
        self.assertEqual(int(usage_count["c"]), 0)


if __name__ == "__main__":
    unittest.main()
