"""Tests for opus encoding + ST-04 content-hash naming."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory.narration.audio import (
    OPUS_BITRATE_KBPS,
    asset_rel_path,
    content_hash,
    encode_opus,
    is_opus,
    write_asset,
)
from factory.narration.errors import NarrationError
from factory.narration.timbre import _silence_wav


class TestContentHash(unittest.TestCase):
    def test_deterministic_and_16_hex(self):
        h1 = content_hash("en", "en-IN", "Speed is distance by time.")
        h2 = content_hash("en", "en-IN", "Speed is distance by time.")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)
        int(h1, 16)  # hex

    def test_sensitive_to_text_lang_and_voice(self):
        base = content_hash("en", "en-IN", "same text")
        self.assertNotEqual(base, content_hash("hi", "en-IN", "same text"))
        self.assertNotEqual(base, content_hash("en", "hi-IN", "same text"))
        self.assertNotEqual(base, content_hash("en", "en-IN", "same text!"))

    def test_st04_filename_pattern(self):
        h = content_hash("en", "en-IN", "text")
        path = asset_rel_path("class-9-physics", "b-01", "en", h)
        self.assertRegex(path, r"^audio/class-9-physics/b-01\.en\.[0-9a-f]{16}\.opus$")

    def test_meta_block_uses_b00meta_id(self):
        h = content_hash("en", "", "title")
        path = asset_rel_path("class-9-physics", "b-00-meta", "en", h)
        self.assertIn("b-00-meta.en.", path)


class TestEncodeOpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("ffmpeg not on PATH")

    def test_wav_encodes_to_valid_opus(self):
        opus = encode_opus(_silence_wav(1.5), "audio/wav")
        self.assertTrue(is_opus(opus))
        self.assertGreater(len(opus), 0)
        # 1.5 s of silence at 24 kbps must stay small (the narration rung).
        self.assertLess(len(opus), 24_000 * 2 / 8)  # < full-bitrate 1.5 s

    def test_opus_passthrough_untouched(self):
        once = encode_opus(_silence_wav(1.0), "audio/wav")
        twice = encode_opus(once, "audio/ogg")
        self.assertEqual(once, twice)  # never double-transcode

    def test_empty_input_refused(self):
        with self.assertRaises(NarrationError):
            encode_opus(b"", "audio/wav")

    def test_garbage_input_fails_loudly(self):
        with self.assertRaises(NarrationError) as ctx:
            encode_opus(b"this is not audio at all" * 100, "application/octet-stream")
        self.assertIn("ffmpeg opus encode failed", str(ctx.exception))

    def test_missing_binary_raises_with_guidance(self):
        import os

        saved = os.environ.get("ZIVON_FFMPEG_PATH")
        os.environ["ZIVON_FFMPEG_PATH"] = "/nonexistent/ffmpeg"
        try:
            with self.assertRaises(NarrationError) as ctx:
                encode_opus(_silence_wav(0.5), "audio/wav")
            self.assertIn("ZIVON_FFMPEG_PATH", str(ctx.exception))
        finally:
            if saved is None:
                os.environ.pop("ZIVON_FFMPEG_PATH", None)
            else:
                os.environ["ZIVON_FFMPEG_PATH"] = saved

    def test_encode_is_real_opus_per_ffprobe(self):
        if shutil.which("ffprobe") is None:
            return  # ffprobe optional; the magic-byte checks above already bind
        opus = encode_opus(_silence_wav(1.0), "audio/wav")
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,channels,sample_rate",
                "-of",
                "default=nw=1",
                "pipe:0",
            ],
            input=opus,
            capture_output=True,
            check=False,
        )
        out = proc.stdout.decode()
        self.assertIn("codec_name=opus", out)
        self.assertIn("channels=1", out)
        self.assertIn("sample_rate=48000", out)

    def test_bitrate_constant_is_the_narration_rung(self):
        self.assertEqual(OPUS_BITRATE_KBPS, 24)


class TestWriteAsset(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-audio-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_content_addressed_file(self):
        path = write_asset(self.tmp, "audio/class-9-physics/b-01.en.abc.opus", b"data")
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), b"data")

    def test_existing_asset_never_rewritten(self):
        rel = "audio/class-9-physics/b-01.en.abc.opus"
        write_asset(self.tmp, rel, b"original")
        path = write_asset(self.tmp, rel, b"different")
        self.assertEqual(path.read_bytes(), b"original")  # immutability

    def test_no_tmp_files_left_behind(self):
        write_asset(self.tmp, "audio/x/b-01.en.abc.opus", b"data")
        leftovers = list((self.tmp / "audio" / "x").glob("*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
