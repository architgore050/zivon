"""Keeps sources/catalog.json and docs/content-factory/source-catalog.md in sync.

Every catalog book must be represented in the human-readable research doc:
its title and at least one of its URLs/filenames must appear there.
"""

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


class TestCatalogSync(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(
            (REPO_ROOT / "sources" / "catalog.json").read_text(encoding="utf-8")
        )
        # strip markdown emphasis so table titles match literal JSON titles
        self.doc = (
            (REPO_ROOT / "docs" / "content-factory" / "source-catalog.md")
            .read_text(encoding="utf-8")
            .replace("*", "")
        )

    def test_every_book_documented(self):
        for book in self.catalog["books"]:
            with self.subTest(book=book["id"]):
                title = book["title"]
                base_title = title.split(" (")[0].split(" - ")[0]
                self.assertTrue(
                    title in self.doc or base_title in self.doc,
                    f"book '{title}' ({book['id']}) not found in docs/content-factory/source-catalog.md",
                )
                link = (
                    book.get("prelims_url")
                    or book.get("manual_url")
                    or book.get("manual_filename")
                )
                self.assertTrue(
                    link and link in self.doc,
                    f"book '{book['id']}' link/filename '{link}' not found in docs/content-factory/source-catalog.md",
                )

    def test_catalog_has_classes_6_to_12(self):
        classes = {b["class"] for b in self.catalog["books"]}
        for expected in range(6, 13):
            self.assertIn(expected, classes, f"no catalog book covers class {expected}")

    def test_every_auto_book_has_required_fields(self):
        for book in self.catalog["books"]:
            if book.get("download") != "auto":
                continue
            for key in (
                "prelims_url",
                "chapter_url_template",
                "chapter_numbers",
                "chapters_verified",
                "class_evidence",
            ):
                self.assertIn(key, book, f"{book['id']} missing {key}")
            self.assertIn("{nn}", book["chapter_url_template"])

    def test_manual_books_have_instructions(self):
        for book in self.catalog["books"]:
            if book.get("download") != "manual":
                continue
            self.assertIn("manual_filename", book)
            self.assertIn("manual_url", book)


if __name__ == "__main__":
    unittest.main()
