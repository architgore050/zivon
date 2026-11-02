"""Unit tests for hard lints (factory/lint.py) and text ops (factory/textops.py)."""

import sys
import unittest
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.lint import lint_css, lint_html, lint_js
from factory.textops import chunk_text, normalize_title, titles_equivalent


class TestJsLints(unittest.TestCase):
    def test_clean_js_passes(self):
        code = "var x = 1; console.log(x);"
        self.assertEqual(lint_js("a.js", code), [])

    def test_eval_caught(self):
        self.assertIn("eval", lint_js("a.js", "eval('1+1')")[0])

    def test_new_function_caught(self):
        self.assertTrue(lint_js("a.js", "var f = new Function('return 1');"))

    def test_fetch_caught(self):
        self.assertTrue(lint_js("a.js", "fetch('/api')"))

    def test_url_string_caught(self):
        self.assertTrue(lint_js("a.js", 'var u = "https://evil.example/x";'))

    def test_dynamic_import_caught(self):
        self.assertTrue(lint_js("a.js", "import('./x.js')"))

    def test_document_write_caught(self):
        self.assertTrue(lint_js("a.js", "document.write('<b>')"))


class TestCssLints(unittest.TestCase):
    def test_clean_css_passes(self):
        self.assertEqual(lint_css("a.css", ".a { color: red; }"), [])

    def test_import_caught(self):
        self.assertTrue(lint_css("a.css", "@import url('x.css');"))

    def test_external_url_caught(self):
        self.assertTrue(
            lint_css("a.css", ".a { background: url(https://x.example/i.png); }")
        )


class TestHtmlLints(unittest.TestCase):
    def test_clean_html_passes(self):
        html = '<html><body><p>hi</p><svg xmlns="http://www.w3.org/2000/svg"></svg></body></html>'
        self.assertEqual(lint_html("a.html", html), [])

    def test_script_tag_caught(self):
        self.assertTrue(lint_html("a.html", "<html><script>1</script></html>"))

    def test_external_src_caught(self):
        self.assertTrue(lint_html("a.html", '<img src="https://x.example/i.png">'))

    def test_xmlns_not_flagged(self):
        html = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>'
        self.assertEqual(lint_html("a.html", html), [])


class TestTextOps(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_title("Motion!"), "motion")
        self.assertEqual(
            normalize_title("  Force &  Laws of Motion "), "forcelawsofmotion"
        )

    def test_equivalence(self):
        self.assertTrue(titles_equivalent("Motion", "Motion"))
        self.assertTrue(titles_equivalent("MOTION", "Motion"))
        self.assertTrue(titles_equivalent("motion", "Chapter 7 Motion"))
        self.assertFalse(titles_equivalent("Motion", "Sound"))
        self.assertFalse(titles_equivalent("", "Motion"))

    def test_chunking_overlap(self):
        text = "abcdefghij" * 30
        chunks = chunk_text(text, chunk_chars=100, overlap=20)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        # continuity: each chunk (except the first) shares `overlap` chars with the end of the previous
        for prev, nxt in pairwise(chunks):
            self.assertEqual(prev[-20:], nxt[:20])
        # full coverage: the first chunk starts the text, the last chunk ends it
        self.assertEqual(chunks[0][:80], text[:80])
        self.assertTrue(text.endswith(chunks[-1]))

    def test_chunking_rejects_bad_params(self):
        with self.assertRaises(ValueError):
            chunk_text("abc", chunk_chars=10, overlap=10)

    def test_chunking_empty(self):
        self.assertEqual(chunk_text("   ", 10, 2), [])


if __name__ == "__main__":
    unittest.main()
