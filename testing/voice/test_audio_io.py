"""Unit tests for voice.audio_io — the ADR-0020 binary frame codec."""

from __future__ import annotations

import unittest

from voice.audio_io import (
    FLAG_FINAL,
    PCM_FRAME_BYTES,
    AudioFrameError,
    DownlinkHeader,
    UplinkStream,
    pack_downlink,
    pack_uplink,
    unpack_downlink,
    unpack_uplink,
)


class HeaderCodecTest(unittest.TestCase):
    def test_uplink_round_trip(self) -> None:
        payload = b"\x00\x01" * 1600  # 3,200 bytes of PCM16
        frame = pack_uplink(segment_id=1, seq=7, payload=payload)
        header, got = unpack_uplink(frame)
        self.assertEqual(header.segment_id, 1)
        self.assertEqual(header.seq, 7)
        self.assertFalse(header.final)
        self.assertEqual(got, payload)
        self.assertEqual(len(frame), 8 + PCM_FRAME_BYTES)

    def test_downlink_round_trip_with_final_flag(self) -> None:
        payload = b"\xf0" * 60  # a 20 ms Opus frame (format pinned at OQ-03)
        frame = pack_downlink(segment_id=3, seq=0, payload=payload, final=True)
        header, got = unpack_downlink(frame)
        self.assertIsInstance(header, DownlinkHeader)
        self.assertEqual(header.segment_id, 3)
        self.assertEqual(header.final, True)
        self.assertEqual(got, payload)

    def test_bad_magic_rejected(self) -> None:
        frame = b"\x00" + pack_uplink(1, 0, b"x" * 3200)[1:]
        with self.assertRaises(AudioFrameError):
            unpack_uplink(frame)

    def test_bad_version_rejected(self) -> None:
        frame = pack_uplink(1, 0, b"x" * 3200)
        broken = bytes([frame[0], 2]) + frame[2:]
        with self.assertRaises(AudioFrameError):
            unpack_uplink(broken)

    def test_oversized_and_odd_payloads_rejected(self) -> None:
        with self.assertRaises(AudioFrameError):
            unpack_uplink(pack_uplink(1, 0, b"x" * 9001))
        with self.assertRaises(AudioFrameError):
            unpack_uplink(pack_uplink(1, 0, b"xyz"))  # odd byte count

    def test_out_of_range_ids_rejected_on_pack(self) -> None:
        with self.assertRaises(AudioFrameError):
            pack_uplink(1 << 16, 0, b"x" * 3200)
        with self.assertRaises(AudioFrameError):
            pack_downlink(1, -1, b"x")

    def test_final_flag_bit(self) -> None:
        self.assertEqual(FLAG_FINAL, 0x01)


class UplinkStreamTest(unittest.TestCase):
    def test_accepts_valid_stream_and_counts_seconds(self) -> None:
        stream = UplinkStream()
        payload = b"\x00\x00" * 1600
        for seq in range(3):
            got = stream.accept(pack_uplink(1, seq, payload))
            self.assertIsNotNone(got)
        self.assertEqual(stream.frames, 3)
        self.assertAlmostEqual(stream.audio_seconds, 0.3, places=6)

    def test_stale_seq_dropped_with_counter(self) -> None:
        stream = UplinkStream()
        payload = b"\x00\x00" * 1600
        self.assertIsNotNone(stream.accept(pack_uplink(1, 5, payload)))
        self.assertIsNone(stream.accept(pack_uplink(1, 4, payload)))  # reorder
        self.assertIsNone(stream.accept(pack_uplink(1, 5, payload)))  # dup
        self.assertEqual(stream.dropped_stale, 2)
        self.assertEqual(stream.frames, 1)

    def test_invalid_frame_dropped_with_counter(self) -> None:
        stream = UplinkStream()
        self.assertIsNone(stream.accept(b"\x00\x01\x00\x01\x00\x00\x00\x00garbage"))
        self.assertEqual(stream.dropped_invalid, 1)


if __name__ == "__main__":
    unittest.main()
