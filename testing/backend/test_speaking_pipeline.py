"""Explain-back pipeline mechanics: WAV bounds, rubric mapping, vendor seams.

Hermetic: no key, no network. Prisma is a fake transport at the
`SttTransport` seam; the tutor model is a fake `StreamFactory` at the
`voice.brain_client` seam. The real `SttClient`, `BrainClient`, and the
store's prompt shape are exercised — only the vendor sockets are replaced.
"""

from __future__ import annotations

import asyncio
import json
import struct
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from backend.speaking import (
    MOCK_TRANSCRIPT,
    AudioError,
    EvaluationError,
    SpeakingEvaluationError,
    SpeakingPipeline,
    key_ideas,
    parse_evaluation,
    parse_wav,
    pcm_frames,
    stt_credit_points,
    thresholds,
)
from voice.brain_client import RawChunk
from voice.config import VoiceSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK = (
    REPO_ROOT
    / "sources"
    / "assessment"
    / "packs"
    / "class-9-describing-motion-around-us"
    / "speaking.json"
)


def prompt_fixture(language: str = "en") -> dict[str, Any]:
    data = json.loads(PACK.read_text(encoding="utf-8"))
    row = next(
        item
        for item in data["prompts"]
        if item["language"] == language and item["prompt_id"] == "spk-c9-motion-001"
    )
    return {
        "prompt_id": row["prompt_id"],
        "language": row["language"],
        "prompt": row["prompt"],
        "key_ideas": row["key_ideas"],
        "rubric": row["thresholds"],
        "model_answer": row["model_answer"],
        "model_answer_source": row["model_answer_source"],
    }


def wav_bytes(seconds: float = 2.0, *, sample_rate: int = 16000) -> bytes:
    frames = int(sample_rate * seconds)
    data = b"\x00\x01" * frames
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def evaluation_json(prompt: dict[str, Any], *, present: int) -> str:
    ideas = key_ideas(prompt)
    return json.dumps(
        {
            "ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "present": index < present,
                    "evidence": "the student's own words" if index < present else "",
                }
                for index, idea in enumerate(ideas)
            ],
            "feedback": {
                "what_went_well": "A clear start.",
                "next_step": "Name each idea once.",
            },
        }
    )


class FakeTransport:
    """One Prisma socket: records sent frames and returns one transcript."""

    def __init__(self, transcript: str = "Distance is the whole path.") -> None:
        self.transcript = transcript
        self.sent: list[str | bytes] = []
        self.closed = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        await asyncio.sleep(0)
        return json.dumps({"type": "transcript", "text": self.transcript})

    async def close(self) -> None:
        self.closed = True


class WavTests(unittest.TestCase):
    def test_parses_the_canonical_16k_mono_pcm16_shape(self) -> None:
        audio = parse_wav(wav_bytes(seconds=2))
        self.assertEqual(audio.sample_rate, 16000)
        self.assertEqual(audio.duration_ms, 2000)
        self.assertEqual(len(audio.pcm), 64000)

    def test_rejects_compressed_stereo_and_wrong_rate(self) -> None:
        body = bytearray(wav_bytes(seconds=1))
        body[20:22] = struct.pack("<H", 3)  # IEEE float
        with self.assertRaises(AudioError):
            parse_wav(bytes(body))

        stereo = bytearray(wav_bytes(seconds=1))
        stereo[22:24] = struct.pack("<H", 2)
        with self.assertRaises(AudioError):
            parse_wav(bytes(stereo))

        with self.assertRaises(AudioError):
            parse_wav(wav_bytes(seconds=1, sample_rate=48000))

    def test_rejects_short_long_empty_and_malformed(self) -> None:
        for body in (b"", b"not a wav", wav_bytes(seconds=0.2), wav_bytes(seconds=61)):
            with self.subTest(size=len(body)), self.assertRaises(AudioError):
                parse_wav(body)

    def test_rejects_a_body_over_the_cap(self) -> None:
        with self.assertRaises(AudioError) as caught:
            parse_wav(b"RIFF" + b"\x00" * 3_000_001)
        self.assertEqual(caught.exception.code, "E-SPEAKING-AUDIO-SIZE")

    def test_frames_are_the_voice_loop_shape(self) -> None:
        frames = pcm_frames(b"\x00" * 64000, sample_rate=16000, frame_ms=100)
        self.assertEqual(len(frames), 20)
        self.assertTrue(all(len(frame) == 3200 for frame in frames))
        partial = pcm_frames(b"\x00" * 64100, sample_rate=16000, frame_ms=100)
        self.assertEqual(len(partial[-1]), 100)

    def test_credit_points_are_ceil_with_a_floor_of_one(self) -> None:
        self.assertEqual(stt_credit_points(1_000, 30), 1)
        self.assertEqual(stt_credit_points(31_000, 30), 2)
        self.assertEqual(stt_credit_points(0, 30), 1)


class RubricTests(unittest.TestCase):
    def test_three_of_four_is_pass_and_counts_are_exact(self) -> None:
        prompt = prompt_fixture()
        result = parse_evaluation(
            evaluation_json(prompt, present=3), prompt=prompt, model="test"
        )
        self.assertEqual(result.ideas_present, 3)
        self.assertEqual(result.ideas_total, 4)
        self.assertEqual(result.band, "pass")
        self.assertAlmostEqual(result.ratio, 0.75)
        self.assertEqual(result.score, 75.0)
        self.assertEqual(result.band_label, "Clear explanation")

    def test_bands_come_from_the_authored_thresholds(self) -> None:
        prompt = prompt_fixture()
        prompt["rubric"] = {
            "max_duration_s": 45,
            "pass_ratio": 0.5,
            "strong_ratio": 0.9,
        }
        self.assertEqual(
            parse_evaluation(
                evaluation_json(prompt, present=2), prompt=prompt, model="test"
            ).band,
            "pass",
        )
        self.assertEqual(
            parse_evaluation(
                evaluation_json(prompt, present=4), prompt=prompt, model="test"
            ).band,
            "strong",
        )
        self.assertEqual(
            parse_evaluation(
                evaluation_json(prompt, present=1), prompt=prompt, model="test"
            ).band,
            "needs_practice",
        )

    def test_missing_ids_are_absent_and_unknown_ids_are_dropped(self) -> None:
        prompt = prompt_fixture()
        payload = json.loads(evaluation_json(prompt, present=4))
        payload["ideas"] = payload["ideas"][:2]
        payload["ideas"].append(
            {"idea_id": "invented-idea", "present": True, "evidence": "x"}
        )
        result = parse_evaluation(json.dumps(payload), prompt=prompt, model="test")
        self.assertEqual(result.ideas_present, 2)
        self.assertEqual(result.ideas_total, 4)
        self.assertEqual(result.ideas[2]["present"], False)
        self.assertNotIn("invented-idea", [row["idea_id"] for row in result.ideas])

    def test_non_boolean_present_is_not_coerced(self) -> None:
        prompt = prompt_fixture()
        payload = json.loads(evaluation_json(prompt, present=4))
        payload["ideas"][0]["present"] = "true"
        result = parse_evaluation(json.dumps(payload), prompt=prompt, model="test")
        self.assertFalse(result.ideas[0]["present"])

    def test_code_fenced_json_and_short_evidence_are_accepted(self) -> None:
        prompt = prompt_fixture()
        raw = "```json\n" + evaluation_json(prompt, present=2) + "\n```"
        result = parse_evaluation(raw, prompt=prompt, model="test")
        self.assertEqual(result.ideas_present, 2)
        self.assertEqual(result.ideas[0]["evidence"], "the student's own words")

    def test_malformed_output_is_a_typed_failure(self) -> None:
        prompt = prompt_fixture()
        for raw in ("", "no json here", "{broken", '{"ideas": []}'):
            with self.subTest(raw=raw[:12]), self.assertRaises(EvaluationError):
                parse_evaluation(raw, prompt=prompt, model="test")

    def test_empty_feedback_gets_a_deterministic_fallback(self) -> None:
        prompt = prompt_fixture()
        payload = json.loads(evaluation_json(prompt, present=0))
        payload.pop("feedback")
        result = parse_evaluation(json.dumps(payload), prompt=prompt, model="test")
        self.assertIn("record once more", result.next_step)
        self.assertTrue(result.what_went_well)

    def test_bad_thresholds_fall_back_to_defaults(self) -> None:
        self.assertEqual(
            thresholds({"rubric": {"pass_ratio": "x", "max_duration_s": None}}),
            {"max_duration_s": 45.0, "pass_ratio": 0.6, "strong_ratio": 0.85},
        )

    def test_stored_payloads_stay_bounded(self) -> None:
        prompt = prompt_fixture()
        result = parse_evaluation(
            evaluation_json(prompt, present=4), prompt=prompt, model="test"
        )
        self.assertLessEqual(len(json.dumps(result.rubric_scores())), 2000)
        self.assertLessEqual(len(json.dumps(result.feedback())), 2000)

    def test_a_many_idea_prompt_drops_evidence_before_the_store_cap(self) -> None:
        prompt = prompt_fixture()
        prompt["key_ideas"] = [
            {"idea_id": f"idea-{index:02d}", "text": "A long authored key idea. " * 4}
            for index in range(20)
        ]
        payload = {
            "ideas": [
                {
                    "idea_id": f"idea-{index:02d}",
                    "present": True,
                    "evidence": "verbatim student words " * 8,
                }
                for index in range(20)
            ],
            "feedback": {"what_went_well": "ok", "next_step": "ok"},
        }
        result = parse_evaluation(json.dumps(payload), prompt=prompt, model="test")
        stored = result.rubric_scores()
        self.assertLessEqual(len(json.dumps(stored, ensure_ascii=False)), 2000)
        self.assertEqual(len(stored["ideas"]), 20)
        self.assertTrue(all(row["present"] for row in stored["ideas"]))
        self.assertTrue(all(row["evidence"] == "" for row in stored["ideas"]))


class PipelineTests(unittest.TestCase):
    def settings(self, **overrides: Any) -> VoiceSettings:
        base = VoiceSettings(
            stt_url="wss://stt.test/realtime",
            gnani_stt_api_key="test-stt-key",
            gemini_api_key="test-gemini-key",
        )
        return replace(base, **overrides)

    def test_transcribe_streams_frames_commits_and_returns_the_final(self) -> None:
        transport = FakeTransport("Distance is the whole path.")

        def connect(settings: VoiceSettings):
            async def _connect():
                return transport

            return _connect

        pipeline = SpeakingPipeline(self.settings(), stt_connect_factory=connect)
        result = asyncio.run(
            pipeline.transcribe(wav_bytes(seconds=1)[44:], language="en")
        )
        self.assertEqual(result.text, "Distance is the whole path.")
        self.assertFalse(result.mock)
        binary = [item for item in transport.sent if isinstance(item, bytes)]
        self.assertEqual(len(binary), 10)  # 1 s at 100 ms frames
        self.assertEqual(transport.sent[-1], '{"type": "commit"}')
        self.assertTrue(transport.closed)

    def test_evaluate_collects_content_and_applies_the_rubric(self) -> None:
        prompt = prompt_fixture()
        payload = evaluation_json(prompt, present=3)

        async def stream_factory(messages: list[Any]):
            del messages
            for start in range(0, len(payload), 17):
                yield RawChunk(content=payload[start : start + 17])

        pipeline = SpeakingPipeline(
            self.settings(), brain_stream_factory=stream_factory
        )
        result = asyncio.run(pipeline.evaluate(prompt, "Distance is the path."))
        self.assertEqual(result.ideas_present, 3)
        self.assertEqual(result.band, "pass")
        self.assertEqual(result.model, "gemma-4-26b-a4b-it")

    def test_evaluate_maps_a_bad_model_output_to_a_typed_failure(self) -> None:
        prompt = prompt_fixture()

        async def stream_factory(messages: list[Any]):
            del messages
            yield RawChunk(content="I think the answer is good.")

        pipeline = SpeakingPipeline(
            self.settings(), brain_stream_factory=stream_factory
        )
        with self.assertRaises(SpeakingEvaluationError):
            asyncio.run(pipeline.evaluate(prompt, "Distance is the path."))

    def test_mock_mode_is_labelled_and_never_production(self) -> None:
        mock = SpeakingPipeline(self.settings(), env="dev", mock=True)
        self.assertTrue(mock.mock)
        self.assertTrue(mock.available)
        transcript = asyncio.run(mock.transcribe(b"\x00\x01" * 16000, language="en"))
        self.assertTrue(transcript.mock)
        self.assertEqual(transcript.text, MOCK_TRANSCRIPT)
        evaluation = asyncio.run(mock.evaluate(prompt_fixture(), "anything"))
        self.assertTrue(evaluation.mock)
        self.assertEqual(evaluation.ideas_present, evaluation.ideas_total)

        prod = SpeakingPipeline(self.settings(), env="prod", mock=True)
        self.assertFalse(prod.mock)

    def test_unconfigured_live_pipeline_is_unavailable(self) -> None:
        pipeline = SpeakingPipeline(
            VoiceSettings(stt_url="", gnani_stt_api_key="", gemini_api_key="")
        )
        self.assertFalse(pipeline.available)


__all__ = ["PipelineTests", "RubricTests", "WavTests"]
