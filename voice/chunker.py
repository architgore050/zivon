"""Sentence-boundary streaming chunker — spec.md §2 stage 5, ADR-0019.

The one-stream law requires handing speakable text to Timbre while the brain
is still generating; this module decides WHERE a partial stream becomes
speech. Deterministic rules in priority order (ADR-0019):

1. Strong boundaries: ``।`` (danda), ``.``, ``!``, ``?``, ``…``, newline.
2. Clause fallback: pending > 140 chars → flush at the last ``,`` ``;`` ``:``
   ``—`` boundary ≥ 40 chars in.
3. Flush deadline: pending sat > 250 ms without a flushable boundary → flush
   at a whitespace word edge ≥ 40 chars in (prosody loss buys latency; rule
   5 makes it apply from the first token, so the first spoken segment is at
   most ~250 ms behind the first boundary).
4. No-split guarantees: never split inside a number/decimal/unit token,
   inside a Timbre tag ``<…>``, inside a ``REF:`` line, inside a URL/domain,
   inside an open code fence; markup is stripped (``**``, ``#``, ``$…$``,
   code fences) before flushing — a ``REF:`` line or a stripped-empty chunk
   is dropped silently (never speak markup garbage). Known trade-off: a
   dotted abbreviation at sentence end ("… e.g. next") may pause early —
   accepted: it never corrupts numbers, units, tags, or URLs.
5. First-chunk fast path: rule 3 applies from the first token.
6. Segments carry monotonic ids; ``kind: speech|summary|filler`` (ADR-0018).

Boundary rules are repo law for the voice loop: changes go through
``testing/voice/test_chunker.py`` fixtures (incl. Devanagari + mixed-script)
before tuning (ADR-0019 consequences).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["Chunk", "SegmentIds", "SentenceChunker"]

_MAX_SENT_CHARS = 140
_MIN_FLUSH_CHARS = 40
_FLUSH_DEADLINE_S = 0.250

_STRONG = "।!?\u2026"  # danda, !, ?, … ('.' handled with guards; '\n' too)
_CLAUSE = ",;:\u2014"  # , ; : — (em dash)

_FENCE_MARKER = "```"
# markup strip per ADR-0019 rule 4 (visible text only, never markup garbage)
_EMPHASIS = re.compile(r"\*\*|__|(?<!\w)\*|\*(?!\w)|(?<!\w)_|_(?!\w)")
_HASH = re.compile(r"(?<![\w#])#{1,6}(?=[\s\w])")  # '#1', '# heading'; not urls
_MATH = re.compile(r"\$([^$]*)\$")
_BACKTICK = re.compile(r"`+")


@dataclass(frozen=True)
class Chunk:
    """One speakable segment: ``segment_id`` is monotonic per turn."""

    text: str
    segment_id: int
    kind: str  # speech | summary | filler


class SegmentIds:
    """Monotonic per-turn segment id allocator (ws-contract.md §3: from 1)."""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def take(self) -> int:
        segment_id = self._next
        self._next += 1
        return segment_id


class SentenceChunker:
    """Streaming chunker for one turn's speech stream.

    Feed brain content deltas; collect the emitted chunks. The instance
    keeps only the pending text between boundaries — never the whole answer
    (memory bound; ADR-0008 posture for text too).
    """

    def __init__(
        self,
        segment_ids: SegmentIds,
        *,
        max_sent_chars: int = _MAX_SENT_CHARS,
        min_flush_chars: int = _MIN_FLUSH_CHARS,
        flush_deadline_s: float = _FLUSH_DEADLINE_S,
        clock: Callable[[], float] = time.monotonic,
        kind: str = "speech",
    ) -> None:
        self._ids = segment_ids
        self._max = max_sent_chars
        self._min = min_flush_chars
        self._deadline = flush_deadline_s
        self._clock = clock
        self._kind = kind
        self._pending = ""
        self._held = ""
        self._pending_since: float | None = None
        self._in_ref_line = False
        self._in_fence = False
        self.dropped_empty = 0
        self.dropped_ref = 0
        self.chunks_emitted = 0
        self.deadline_flushes = 0

    def feed(self, delta: str) -> list[Chunk]:
        """Feed one content delta; return chunks ready for Timbre."""
        if not delta:
            return []
        if self._in_fence:
            self._held += delta  # fence content: held, never spoken
        else:
            if not self._pending:
                self._pending_since = self._clock()
            self._pending += delta
        self._resolve_fences()
        self._track_ref_line()
        return self._drain()

    def flush(self) -> list[Chunk]:
        """End of stream: emit whatever speakable text remains."""
        chunks: list[Chunk] = []
        if self._pending.strip():
            chunk = self._emit(self._pending)
            if chunk is not None:
                chunks.append(chunk)
        self._pending = ""
        self._held = ""  # fence content is never spoken
        self._pending_since = None
        self._in_ref_line = False
        self._in_fence = False
        return chunks

    # --- internals -----------------------------------------------------------

    def _resolve_fences(self) -> None:
        """Drop ``` fences (spoken code is garbage); hold open ones.

        Prose BEFORE an open fence stays flushable; the fence content itself
        collects in ``_held`` until its closing marker arrives, then is
        dropped silently (ADR-0019 rule 4: never speak markup garbage).
        """
        while True:
            if self._in_fence:
                _pre, marker, rest = self._held.partition(_FENCE_MARKER)
                if not marker:
                    return  # still open — keep holding
                self._held = ""
                self._in_fence = False
                if rest and not self._pending:
                    self._pending_since = self._clock()
                self._pending += rest
                continue  # rest may open another fence
            start = self._pending.find(_FENCE_MARKER)
            if start == -1:
                return
            end = self._pending.find(_FENCE_MARKER, start + len(_FENCE_MARKER))
            if end == -1:
                self._held = self._pending[start + len(_FENCE_MARKER) :]
                self._pending = self._pending[:start]
                self._in_fence = True
                continue
            self._pending = (
                self._pending[:start] + self._pending[end + len(_FENCE_MARKER) :]
            )

    def _track_ref_line(self) -> None:
        # No-split guarantee: hold clause/deadline flushes inside a REF: line
        # (only a newline ends it; the brain parser normally strips REF upstream
        # — this guards against mid-content misuse).
        if not self._in_ref_line and self._pending.lstrip()[:4].upper() == "REF:":
            self._in_ref_line = True
        elif self._in_ref_line and "\n" in self._pending:
            self._in_ref_line = False

    def _drain(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        while True:
            # _resolve_fences guarantees: pending never contains a fence
            # marker (open ones are held separately), so all rules scan safe.
            cut = self._strong_cut()
            if cut is not None:
                chunk = self._emit(self._pending[: cut[0]])
                self._pending = self._pending[cut[1] :].lstrip(" \t")
                if chunk is not None:
                    chunks.append(chunk)
                self._pending_since = self._clock()
                self._track_ref_line()
                continue
            if self._in_ref_line or self._in_fence:
                break
            if len(self._pending) > self._max:
                cut = self._clause_cut()
                if cut is not None:
                    chunk = self._emit(self._pending[: cut[0]])
                    self._pending = self._pending[cut[1] :].lstrip(" \t")
                    if chunk is not None:
                        chunks.append(chunk)
                    self._pending_since = self._clock()
                    continue
            now = self._clock()
            if (
                self._pending_since is not None
                and now - self._pending_since > self._deadline
                and len(self._pending) >= self._min
            ):
                cut = self._whitespace_cut()
                if cut is not None:
                    chunk = self._emit(self._pending[: cut[0]])
                    self._pending = self._pending[cut[1] :].lstrip(" \t")
                    if chunk is not None:
                        chunks.append(chunk)
                    self._pending_since = self._clock()
                    self.deadline_flushes += 1
                    continue
            break
        return chunks

    def _strong_cut(self) -> tuple[int, int] | None:
        """First valid strong boundary: (emit_end, resume_at)."""
        pending = self._pending
        i = 0
        while i < len(pending):
            char = pending[i]
            if char == "<":
                close = pending.find(">", i + 1)
                if close == -1:
                    return None  # inside an open Timbre tag — never split
                i = close + 1
                continue
            if char == "\n":
                return (i, i + 1)  # newline never spoken
            if char in _STRONG:
                return (i + 1, i + 1)
            if char == "." and self._dot_is_boundary(pending, i):
                return (i + 1, i + 1)
            i += 1
        return None

    @staticmethod
    def _dot_is_boundary(pending: str, i: int) -> bool:
        """A '.' splits sentences, never numbers, decimals, or domains."""
        before = pending[i - 1] if i > 0 else ""
        after = pending[i + 1] if i + 1 < len(pending) else ""
        if before.isdigit() and after.isdigit():
            return False  # 3.06 — decimal inside a number token
        return not (before.isalnum() and after.isalnum())  # zivon.ai / e.g.

    def _clause_cut(self) -> tuple[int, int] | None:
        """Last clause boundary ≥ min chars in, outside numbers/tags/urls."""
        pending = self._pending
        best: int | None = None
        i = 0
        while i < len(pending):
            char = pending[i]
            if char == "<":
                close = pending.find(">", i + 1)
                if close == -1:
                    break  # open tag: cannot flush past it
                i = close + 1
                continue
            if char in _CLAUSE and i + 1 >= self._min:
                before = pending[i - 1] if i > 0 else ""
                after = pending[i + 1] if i + 1 < len(pending) else ""
                splits_number = char in ",." and before.isdigit() and after.isdigit()
                if not splits_number:
                    best = i
            i += 1
        if best is None:
            return None
        return (best + 1, best + 1)

    def _whitespace_cut(self) -> tuple[int, int] | None:
        """Last word edge ≥ min chars in (flush-deadline path, rule 3)."""
        pending = self._pending
        tag_open = pending.rfind("<")
        tag_close = pending.rfind(">")
        limit = len(pending)
        if tag_open > tag_close:
            limit = tag_open  # never flush inside an open Timbre tag
        best: int | None = None
        for i, char in enumerate(pending[:limit]):
            if char in " \t" and i + 1 >= self._min:
                best = i
        if best is None:
            return None
        return (best, best + 1)

    def _emit(self, raw: str) -> Chunk | None:
        text = _strip_markup(raw).strip()
        if not text:
            self.dropped_empty += 1
            return None
        if text[:4].upper() == "REF:":
            # REF lines are harness data, never speech (spec.md §7) — the
            # brain parser strips the leading one; this drops stragglers.
            self.dropped_ref += 1
            return None
        self.chunks_emitted += 1
        return Chunk(text=text, segment_id=self._ids.take(), kind=self._kind)


def _strip_markup(text: str) -> str:
    """Remove markdown/LaTeX syntax, keep the visible words (ADR-0019 rule 4)."""
    text = _MATH.sub(r"\1", text)  # $…$ → keep the inner expression
    text = _HASH.sub(" ", text)  # '#1', '## heading' — not URL fragments
    text = _EMPHASIS.sub("", text)  # **bold**, _it_
    text = _BACKTICK.sub("", text)
    return re.sub(r" {2,}", " ", text)  # collapse the gaps markers leave
