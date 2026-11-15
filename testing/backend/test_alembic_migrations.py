"""Tests for Alembic migration upgrade/downgrade from empty DB and schema constraints."""

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
from db.uuid7 import uuid7_str


class TestAlembicMigrations(unittest.TestCase):
    def test_linear_history_single_head_and_version_files(self) -> None:
        heads = get_heads()
        self.assertEqual(
            heads, ["0003_full_frontend"], "Alembic history must have exactly one head"
        )
        self.assertEqual(LATEST_REVISION, "0003_full_frontend")

        versions_dir = Path("alembic/versions")
        py_files = sorted(versions_dir.glob("*.py"))
        self.assertEqual(len(py_files), 3)
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
        self.assertEqual(rev2, "0003_full_frontend")
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

        # Step 3: Downgrade to 0002 drops only the 0003 additions
        down2 = downgrade_db(eng, "0002")
        self.assertEqual(down2, "0002")
        tables_0002 = set(eng.list_tables())
        for tbl in ADDENDA_TABLES_0002:
            self.assertIn(tbl, tables_0002)
        for tbl in FULL_FRONTEND_TABLES_0003:
            self.assertNotIn(tbl, tables_0002)
        device_cols = {row["name"] for row in eng.fetchall("PRAGMA table_info(device)")}
        self.assertNotIn("user_id", device_cols)

        # Step 4: Downgrade to 0001, then base, then re-upgrade to head
        down1 = downgrade_db(eng, "0001")
        self.assertEqual(down1, "0001")
        down_base = downgrade_db(eng, "base")
        self.assertIsNone(down_base)
        self.assertEqual(set(eng.list_tables()), {"alembic_version"})

        re_up = upgrade_db(eng, "head")
        self.assertEqual(re_up, "0003_full_frontend")
        self.assertTrue(set(ALL_TABLES).issubset(set(eng.list_tables())))

    def test_cli_only_revision_alias_continues_to_head(self) -> None:
        """A DB left at EX2's Alembic-only 0022 continues to 0003, not an error."""
        eng = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        upgrade_db(eng, "0002")
        eng.execute("DELETE FROM alembic_version")
        eng.execute(
            "INSERT INTO alembic_version (version_num) "
            "VALUES ('0022_translation_memory_c3')"
        )
        self.assertEqual(upgrade_db(eng, "head"), "0003_full_frontend")
        self.assertIn("users", set(eng.list_tables()))

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


if __name__ == "__main__":
    unittest.main()
