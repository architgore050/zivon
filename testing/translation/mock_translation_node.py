"""Mock OpenAI-compatible translation + reviewer server for testing 10a..10d.

Simulates the `llm-manager` node (`k8s/16-llm-manager.yaml`) serving Evon v3.3
for:
- `10a-translate` / `10c-transrepair`: per-unit JSON translations (`hi`, `hi-Latn`, `ta`)
  preserving all Western Arabic numerals, SI units, equations, and length budgets.
- `10b-transcheck`: calibrated LLM reviewer returning `TRANSLATION_REVIEW_CALL_REPORT`
  (with configurable scripted issues to test repair routing, stall handling, and
  `unverified:` minor downgrade).
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _translate_text_str(text: str, locale: str) -> str:
    """Deterministic test translator that preserves all numbers, equations, and SI units
    while emitting authentic Devanagari (for hi) or Roman Hinglish (for hi-Latn) prose."""
    if locale == "hi":
        out = text
        replacements = [
            ("Motion: describing how things move", "गति (motion): वस्तुएँ कैसे चलती हैं"),
            ("After this lesson you can", "इस पाठ के बाद आप"),
            (
                "explain what motion, distance and displacement mean",
                "गति (motion), दूरी (distance) और विस्थापन (displacement) का अर्थ समझा सकते हैं",
            ),
            (
                "calculate speed, velocity and acceleration using simple formulas",
                "सरल सूत्रों से चाल (speed), वेग (velocity) और त्वरण (acceleration) की गणना कर सकते हैं",
            ),
            (
                "read a distance-time graph and say how fast something moves",
                "दूरी-समय ग्राफ़ पढ़कर बता सकते हैं कि कोई वस्तु कितनी तेज़ चलती है",
            ),
            ("What motion means", "गति (motion) का अर्थ"),
            ("Distance and displacement", "दूरी (distance) और विस्थापन (displacement)"),
            (
                "Speed, velocity and acceleration",
                "चाल (speed), वेग (velocity) और त्वरण (acceleration)",
            ),
            ("Reading motion from graphs", "ग्राफ़ से गति को समझना"),
            (
                "You are in motion when your position changes with time.",
                "जब समय के साथ आपकी स्थिति बदलती है तो आप गति (motion) में होते हैं।",
            ),
            (
                "A bus moving down a road is in motion, and so is a fan blade going around.",
                "सड़क पर चलती बस गति में है और घूमती हुई पंखे की पत्ती भी गति में है।",
            ),
            (
                "To say that something moved, we compare its position now with its position a moment ago.",
                "यह कहने के लिए कि कुछ हिला है, हम उसकी अभी की स्थिति की तुलना कुछ क्षण पहले की स्थिति से करते हैं।",
            ),
            (
                "To describe motion clearly we use a few measured quantities.",
                "गति को स्पष्ट रूप से समझने के लिए हम कुछ मापी गई राशियों का उपयोग करते हैं।",
            ),
            (
                "Each one answers a different question: how far, how fast, and speeding up or slowing down.",
                "प्रत्येक राशि एक अलग प्रश्न का उत्तर देती है: कितनी दूर, कितनी तेज़ और तेज़ होना या धीमा होना।",
            ),
            ("You will meet them one at a time.", "आप उनसे एक-एक करके परिचित होंगे।"),
            (
                "Distance is the total length of the path you travelled.",
                "दूरी (distance) आपके द्वारा तय किए गए पथ की कुल लंबाई है।",
            ),
            (
                "Walk 3 metres forward and then 4 metres back, and your distance is 7 metres.",
                "3 मीटर आगे और फिर 4 मीटर पीछे चलने पर आपकी दूरी 7 मीटर होती है।",
            ),
            (
                "Distance only has a size, so it is called a scalar.",
                "दूरी में केवल परिमाण होता है, इसलिए इसे अदिश राशि (scalar) कहते हैं।",
            ),
            (
                "Displacement is the shortest straight line from your starting point to your ending point, with its direction.",
                "विस्थापन (displacement) आपके प्रारंभिक बिंदु से अंतिम बिंदु तक दिशा सहित सबसे छोटी सीधी रेखा है।",
            ),
            (
                "In the same walk you end up 1 metre behind where you began, so your displacement is 1 metre backwards.",
                "उसी यात्रा में आप प्रारंभिक स्थान से 1 मीटर पीछे पहुँचते हैं, इसलिए आपका विस्थापन 1 मीटर पीछे की ओर है।",
            ),
            (
                "Because it carries a direction, displacement is a vector.",
                "क्योंकि इसमें दिशा होती है, विस्थापन एक सदिश राशि (vector) है।",
            ),
            (
                "Distance and displacement are equal only when the whole path is one straight line with no turning back.",
                "दूरी और विस्थापन केवल तभी बराबर होते हैं जब पूरा पथ बिना मुड़े एक सीधी रेखा हो।",
            ),
            ("The moment you turn, they separate.", "जैसे ही आप मुड़ते हैं, वे अलग हो जाते हैं।"),
            (
                "Speed tells you how much distance is covered in each second.",
                "चाल (speed) बताती है कि प्रत्येक सेकंड में कितनी दूरी तय की गई है।",
            ),
            ("It is distance divided by time.", "यह दूरी बटा समय के बराबर होती है।"),
            (
                "Cover 100 metres in 20 seconds and your average speed is 5 m/s.",
                "20 सेकंड में 100 मीटर तय करने पर आपकी औसत चाल 5 m/s होती है।",
            ),
            (
                "Velocity is speed with a direction attached.",
                "वेग (velocity) दिशा के साथ जुड़ी हुई चाल है।",
            ),
            (
                "A car moving north at 20 m/s and a car moving south at 20 m/s have the same speed but different velocities.",
                "उत्तर की ओर 20 m/s से चलती कार और दक्षिण की ओर 20 m/s से चलती कार की चाल समान है परंतु वेग भिन्न हैं।",
            ),
            (
                "Acceleration is how quickly velocity changes.",
                "त्वरण (acceleration) बताता है कि वेग कितनी तेज़ी से बदलता है।",
            ),
            (
                "If a body at rest reaches a speed of 10 m/s in 5 seconds, its velocity changed by 10 m/s in 5 s, so its acceleration is 2 m/s2.",
                "यदि विराम में स्थित कोई वस्तु 5 सेकंड में 10 m/s की चाल प्राप्त करती है, तो 5 s में उसका वेग 10 m/s बदला और त्वरण 2 m/s2 है।",
            ),
            (
                "A common formula is v = u + a*t, where u is the starting velocity.",
                "एक सामान्य सूत्र v = u + a*t है, जहाँ u प्रारंभिक वेग है।",
            ),
            (
                "A distance-time graph plots distance on the vertical axis and time on the horizontal axis.",
                "दूरी-समय ग्राफ़ ऊर्ध्वाधर अक्ष पर दूरी और क्षैतिज अक्ष पर समय दर्शाता है।",
            ),
            (
                "The slope of the line tells you the speed: a steep slope means fast motion and a flat line means the object is at rest.",
                "रेखा की ढाल आपको चाल बताती है: अधिक ढाल का अर्थ तेज़ गति है और समतल रेखा का अर्थ है कि वस्तु विराम में है।",
            ),
            (
                "For steady motion the graph is a straight line.",
                "एकसमान गति के लिए ग्राफ़ एक सीधी रेखा होता है।",
            ),
            (
                "When the line curves, the speed is changing, which means the motion is accelerated.",
                "जब रेखा मुड़ती है, तो चाल बदल रही होती है, जिसका अर्थ है कि गति त्वरित है।",
            ),
            (
                "Distance is the total length of the path travelled, and it has only a size.",
                "दूरी (distance) तय किए गए पथ की कुल लंबाई है और इसमें केवल परिमाण होता है।",
            ),
            (
                "Displacement is the shortest straight line from the starting point to the ending point, with its direction.",
                "विस्थापन (displacement) प्रारंभिक बिंदु से अंतिम बिंदु तक दिशा सहित सबसे छोटी सीधी रेखा है।",
            ),
            (
                "They are equal only when the path is one straight line with no turning back.",
                "वे केवल तभी बराबर होते हैं जब पथ बिना मुड़े एक सीधी रेखा में हो।",
            ),
            (
                "Speed is distance divided by time, and velocity is speed with a direction.",
                "चाल (speed) दूरी बटा समय है और वेग (velocity) दिशा के साथ चाल है।",
            ),
            (
                "Acceleration is the rate of change of velocity, and its SI unit is m/s2.",
                "त्वरण (acceleration) वेग परिवर्तन की दर है और इसका SI मात्रक m/s2 है।",
            ),
            (
                "A body starts from rest and accelerates steadily. It gains a speed of 10 m/s in 5 s. What is its acceleration?",
                "एक वस्तु विराम से चलना शुरू करती है और एकसमान रूप से त्वरित होती है। यह 5 s में 10 m/s की चाल प्राप्त करती है। इसका त्वरण (acceleration) क्या है?",
            ),
            ("Write what you know", "ज्ञात मान लिखें"),
            (
                "Starting velocity u = 0 because the body starts from rest, final velocity v = 10 m/s, time t = 5 s.",
                "प्रारंभिक वेग u = 0 क्योंकि वस्तु विराम से शुरू होती है, अंतिम वेग v = 10 m/s, समय t = 5 s।",
            ),
            ("Choose the relation", "सही सूत्र चुनें"),
            (
                "Use v = u + a*t, which connects velocity change to acceleration and time.",
                "सूत्र v = u + a*t का उपयोग करें जो वेग परिवर्तन को त्वरण और समय से जोड़ता है।",
            ),
            ("Rearrange for acceleration", "त्वरण के लिए व्यवस्थित करें"),
            ("Put in the numbers", "संख्यात्मक मान रखें"),
            (
                "Which quantity is defined as the rate of change of velocity?",
                "किस भौतिक राशि को वेग (velocity) में परिवर्तन की दर के रूप में परिभाषित किया जाता है?",
            ),
            (
                "Acceleration is the rate of change of velocity with time; its SI unit is m/s2.",
                "त्वरण (acceleration) समय के साथ वेग परिवर्तन की दर है; इसका SI मात्रक m/s2 है।",
            ),
            (
                "The learner can name acceleration as the quantity that measures changing velocity.",
                "विद्यार्थी बदलते वेग को मापने वाली राशि के रूप में त्वरण का नाम बता सकता है।",
            ),
            (
                "A distance-time graph for steady motion is a straight line; its slope is the speed.",
                "एकसमान गति के लिए दूरी-समय ग्राफ़ एक सीधी रेखा होता है; इसकी ढाल चाल (speed) दर्शाती है।",
            ),
            ("steady speed: straight line", "एकसमान चाल: सीधी रेखा"),
            ("Motion with steady acceleration", "एकसमान त्वरण के साथ गति"),
            (
                "A dot starts at rest and speeds up. Increase or decrease the acceleration and watch how the dot covers distance.",
                "एक बिंदु विराम से शुरू होकर तेज़ होता है। त्वरण बढ़ाएँ या घटाएँ और देखें कि बिंदु दूरी कैसे तय करता है।",
            ),
            (
                "Connect the size of acceleration to how quickly the dot crosses the canvas.",
                "त्वरण के परिमाण को इस बात से जोड़ें कि बिंदु कैनवास को कितनी तेज़ी से पार करता है।",
            ),
            ("acceleration m/s2", "त्वरण a (m/s2)"),
            (
                "The dot starts from rest and drifts faster to the right while the acceleration is positive.",
                "बिंदु विराम से शुरू होता है और धनात्मक त्वरण होने पर दाईं ओर तेज़ी से बढ़ता है।",
            ),
            (
                "A cycle covers 100 m in 20 s. What is its average speed in m/s?",
                "एक साइकिल 20 s में 100 m की दूरी तय करती है। m/s में इसकी औसत चाल (speed) क्या है?",
            ),
            (
                "Average speed is total distance divided by total time: 100 / 20.",
                "औसत चाल कुल दूरी बटा कुल समय होती है: 100 / 20।",
            ),
            (
                "The learner can compute average speed from distance and time.",
                "विद्यार्थी दूरी और समय से औसत चाल की गणना कर सकता है।",
            ),
            (
                "Which of these is a vector quantity?",
                "इनमें से कौन-सी एक सदिश राशि (vector) है?",
            ),
            (
                "Displacement carries a direction from start to end, so it is a vector; distance, mass and time have only size.",
                "विस्थापन (displacement) में प्रारंभ से अंत तक दिशा होती है इसलिए यह सदिश है; दूरी, द्रव्यमान और समय में केवल परिमाण होता है।",
            ),
            (
                "The learner can tell scalars and vectors apart for the quantities on this page.",
                "विद्यार्थी इस पृष्ठ की राशियों में अदिश और सदिश की पहचान कर सकता है।",
            ),
            (
                "the shortest straight-line distance from start to end, with its direction",
                "प्रारंभ से अंत तक दिशा सहित सबसे छोटी सीधी रेखा की दूरी",
            ),
            (
                "speed in a particular direction; the rate of change of displacement",
                "एक निश्चित दिशा में चाल; विस्थापन परिवर्तन की दर",
            ),
            (
                "the rate of change of velocity with time",
                "समय के साथ वेग में परिवर्तन की दर",
            ),
            (
                "a quantity that has only a size, such as distance or speed",
                "वह राशि जिसमें केवल परिमाण होता है, जैसे दूरी या चाल",
            ),
            (
                "a quantity that has both size and direction, such as displacement or velocity",
                "वह राशि जिसमें परिमाण और दिशा दोनों होते हैं, जैसे विस्थापन या वेग",
            ),
        ]
        for src, dst in replacements:
            out = out.replace(src, dst)
        if out == text:
            short_map = {
                "Speed": "चाल (Speed)",
                "Acceleration": "त्वरण (Acceleration)",
                "Distance": "दूरी (Distance)",
                "Force": "बल (Force)",
                "Displacement": "विस्थापन (Displacement)",
                "Mass": "द्रव्यमान (Mass)",
                "Time": "समय (Time)",
                "time": "समय",
                "distance": "दूरी",
                "displacement": "विस्थापन (displacement)",
                "velocity": "वेग (velocity)",
                "acceleration": "त्वरण (acceleration)",
                "scalar": "अदिश राशि (scalar)",
                "vector": "सदिश राशि (vector)",
            }
            if text in short_map:
                return short_map[text]
            return f"भौतिकी विवरण: {text}"
        return out

    if locale == "hi-Latn":
        out = text
        replacements = [
            (
                "Motion: describing how things move",
                "Motion: cheezein kaise move karti hain",
            ),
            (
                "You are in motion when your position changes with time.",
                "Jab time ke saath aapki position change hoti hai toh aap motion mein hote hain.",
            ),
            (
                "Distance is the total length of the path travelled, and it has only a size.",
                "Distance tay kiye gaye path ki total length hai aur ismein sirf size hota hai.",
            ),
            (
                "Speed is distance divided by time, and velocity is speed with a direction.",
                "Speed distance divided by time hai, aur velocity direction ke saath speed hai.",
            ),
            (
                "Acceleration is the rate of change of velocity, and its SI unit is m/s2.",
                "Acceleration velocity ke change hone ki rate hai, aur iska SI unit m/s2 hai.",
            ),
            (
                "Which quantity is defined as the rate of change of velocity?",
                "Kaunsi quantity velocity ke rate of change ke roop mein define hoti hai?",
            ),
            (
                "A cycle covers 100 m in 20 s. What is its average speed in m/s?",
                "Ek cycle 20 s mein 100 m cover karti hai. m/s mein iski average speed kya hai?",
            ),
            (
                "Which of these is a vector quantity?",
                "Inmein se kaunsi ek vector quantity hai?",
            ),
            ("acceleration m/s2", "Acceleration a (m/s2)"),
        ]
        for src, dst in replacements:
            out = out.replace(src, dst)
        out = re.sub(r"[\u0900-\u097F]+", " ", out)
        return out

    return text


def translate_payload_deterministically(
    source_payload: dict[str, Any], locale: str, unit_type: str
) -> dict[str, Any]:
    """Produce a schema-valid translated payload for any unit_type."""
    if unit_type == "meta":
        return {
            "title": _translate_text_str(source_payload["title"], locale)[:110],
            "objectives": [
                _translate_text_str(o, locale) for o in source_payload["objectives"]
            ],
            "sections": [
                {
                    "id": s["id"],
                    "title": _translate_text_str(s["title"], locale),
                    "paragraphs": [
                        _translate_text_str(p, locale) for p in s["paragraphs"]
                    ],
                }
                for s in source_payload.get("sections", [])
            ],
            "glossary": [
                {
                    "term": _translate_text_str(g["term"], locale),
                    "definition": _translate_text_str(g["definition"], locale),
                }
                for g in source_payload["glossary"]
            ],
            "sim_strings": {
                bid: {k: _translate_text_str(v, locale)[:32] for k, v in table.items()}
                for bid, table in source_payload.get("sim_strings", {}).items()
            },
        }
    if unit_type == "text":
        return {
            "paragraphs": [
                _translate_text_str(p, locale) for p in source_payload["paragraphs"]
            ]
        }
    if unit_type == "worked_example":
        return {
            "problem": _translate_text_str(source_payload["problem"], locale),
            "steps": [
                {
                    "title": _translate_text_str(s["title"], locale),
                    "detail": _translate_text_str(s["detail"], locale),
                }
                for s in source_payload["steps"]
            ],
            "answer": _translate_text_str(source_payload["answer"], locale),
        }
    if unit_type == "check":
        if "options" in source_payload:
            return {
                "question": _translate_text_str(source_payload["question"], locale),
                "options": [
                    _translate_text_str(o, locale) for o in source_payload["options"]
                ],
                "explanation": _translate_text_str(
                    source_payload["explanation"], locale
                ),
                "expected_understanding": _translate_text_str(
                    source_payload["expected_understanding"], locale
                ),
            }
        return {
            "question": _translate_text_str(source_payload["question"], locale),
            "explanation": _translate_text_str(source_payload["explanation"], locale),
            "expected_understanding": _translate_text_str(
                source_payload["expected_understanding"], locale
            ),
        }
    if unit_type == "reveal":
        return {
            "title": _translate_text_str(source_payload["title"], locale),
            "steps": [
                {
                    "title": _translate_text_str(s["title"], locale),
                    "detail": _translate_text_str(s["detail"], locale),
                }
                for s in source_payload["steps"]
            ],
        }
    if unit_type == "diagram":
        svg_texts = []
        for item in source_payload.get("svg_texts", []):
            max_c = int(item.get("max_chars", 32))
            tr = _translate_text_str(item["source"], locale)
            if len(tr) > max_c:
                tr = tr[:max_c].rstrip()
            svg_texts.append({"id": item["id"], "text": tr})
        return {
            "caption": _translate_text_str(source_payload["caption"], locale),
            "svg_aria_label": _translate_text_str(
                source_payload.get("svg_aria_label", ""), locale
            ),
            "svg_texts": svg_texts,
        }
    if unit_type == "simulation":
        return {
            "title": _translate_text_str(source_payload["title"], locale),
            "description": _translate_text_str(source_payload["description"], locale),
            "learning_goal": _translate_text_str(
                source_payload["learning_goal"], locale
            ),
            "controls": [
                {
                    "id": c["id"],
                    "label": _translate_text_str(c["label"], locale)[:32],
                }
                for c in source_payload.get("controls", [])
            ],
            "default_behaviour": _translate_text_str(
                source_payload["default_behaviour"], locale
            ),
        }
    raise ValueError(f"Unsupported unit_type: {unit_type}")


class MockTranslationState:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.scripted_review_issues: dict[str, list[list[dict[str, Any]]]] = {}
        self.scripted_bad_unit_first_attempt: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append(entry)


def start_translation_mock() -> tuple[ThreadingHTTPServer, str, MockTranslationState]:
    state = MockTranslationState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw)
            messages = body.get("messages", [])
            sys_prompt = messages[0]["content"] if messages else ""
            # Note: on validation retries in llm_manager, messages[1] is the original user prompt
            first_user_prompt = messages[1]["content"] if len(messages) > 1 else ""

            if "10b-transcheck" in sys_prompt or "10-transcheck" in sys_prompt:
                m_loc = re.search(r"Locale:\s*([A-Za-z-]+)", first_user_prompt)
                locale = m_loc.group(1) if m_loc else "hi"
                state.record({"stage": "10b-transcheck", "locale": locale})
                queue = state.scripted_review_issues.get(locale, [])
                issues = queue.pop(0) if queue else []
                resp_payload: dict[str, Any] = {"issues": issues}
            else:
                stage = (
                    "10c-transrepair"
                    if "10c-transrepair" in sys_prompt
                    else "10a-translate"
                )
                req_obj = json.loads(first_user_prompt)
                locale = str(req_obj["target_locale"]["code"])
                unit_id = str(req_obj["topic_context"]["unit_id"])
                unit_type = str(req_obj["topic_context"]["unit_type"])
                source_payload = req_obj["source_payload"]

                state.record(
                    {
                        "stage": stage,
                        "locale": locale,
                        "unit_id": unit_id,
                        "unit_type": unit_type,
                    }
                )
                resp_payload = translate_payload_deterministically(
                    source_payload, locale, unit_type
                )
                key = (locale, unit_id)
                if key in state.scripted_bad_unit_first_attempt:
                    state.scripted_bad_unit_first_attempt.remove(key)
                    if unit_type == "worked_example":
                        resp_payload["answer"] = "२ m/s2"

            content = json.dumps(resp_payload, ensure_ascii=False)
            model = body.get("model", "mock-evon-v3.3")

            if body.get("stream"):
                # Simulate the OpenAI-format SSE streaming that llm_manager's
                # streaming client (openai>=2 / langchain streaming) consumes.
                usage = {
                    "prompt_tokens": 250,
                    "completion_tokens": 120,
                    "total_tokens": 370,
                }

                def sse_chunk(delta: dict[str, Any], finish: str | None) -> str:
                    chunk = {
                        "id": "chatcmpl-mock-trans",
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": finish,
                                "delta": delta,
                            }
                        ],
                    }
                    if "usage" in delta:
                        chunk["usage"] = delta.pop("usage")
                        chunk["choices"] = []
                    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"

                lines = [
                    sse_chunk(
                        {"role": "assistant", "content": content},
                        finish=None,
                    ),
                    sse_chunk({}, finish="stop"),
                ]
                if body.get("stream_options", {}).get("include_usage"):
                    # terminal usage-only chunk (choices must be empty)
                    lines.append(
                        sse_chunk({"usage": usage}, finish=None)
                    )
                lines.append("data: [DONE]\n\n")
                encoded = "".join(lines).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return

            wire = {
                "id": "chatcmpl-mock-trans",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": content,
                            "reasoning_content": "Translated with glossary and invariant checks.",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 250,
                    "completion_tokens": 120,
                    "total_tokens": 370,
                },
            }
            encoded = json.dumps(wire, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host!s}:{port}/v1", state
