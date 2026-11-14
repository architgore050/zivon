# Instrumentation map — adding a row and keeping map-lint green

Sources: `docs/specs/observability/instrumentation-map.csv`, `logging-api.md` §2/§8,
`testing/observability/test_events.py`, `logging_manager/events.py`. Verified 2026-11-14 at
`main` @ `57147bb`.

The map is the per-event source of truth. An event name without a row is delivered anyway but
flagged (`log.event_unknown`), and CI's map-lint fails. A row without a real emitter is dead
documentation. The row and the code land in the same PR.

## 1. The column contract

One header, fixed order, RFC-4180 via the stdlib `csv` module:

```
component,event,severity,correlation_ids,required_fields,latency_ms,error_class,privacy_class,emitter,notes
```

| Column | Rule | Examples |
|---|---|---|
| `component` | closed enum from `logging_manager.events.COMPONENTS` (or a map-declared exception) | `factory`, `voice`, `frontend`, `llm_node` |
| `event` | `<component>.<subject>.<action>`, lower snake case, globally unique | `factory.stage.ok` |
| `severity` | `DEBUG|INFO|WARNING|ERROR|CRITICAL`; declared once, never overridden at the call site | `INFO` |
| `correlation_ids` | `+`-joined ids the event actually carries; `no` or blank when none (the map uses both) | `run_id+stage+request_id`, `session_id+turn_id`, `no` |
| `required_fields` | `;`-separated payload keys a dashboard/query depends on; `no` or blank when none (the map uses both) | `blocks;attempts` |
| `latency_ms` | `no` for non-timing; `yes` or the metric field name for a duration event (the current map uses metric names, e.g. `stage_ms`) | `stage_ms`, `call_ms`, `no` |
| `error_class` | blank for non-failure; a closed `ErrorClass` for failure-shaped rows | `gate_fail` |
| `privacy_class` | `L1` system/diagnostic, `L2` usage/telemetry, `L3` security/audit, `CR` credit | `L1` |
| `emitter` | the file/symbol that actually calls `log_event` | `factory/stages.py::run_pipeline` |
| `notes` | enums, sampling, why; never learner content | `sampled 1/10` |

Privacy classes drive retention (`spec.md` §6): L1/L2 7 d hot / 90 d cold; L3 30 d / 365 d;
credit counters 7 d / 365 d. Choose the class by what the event is for, not by how sensitive
the code feels.

## 2. Add a row — exact steps

1. **Pick the component and name.** The component must already be in the enum. The name must be
   unique; grep the map before naming.
2. **Add one line** to `docs/specs/observability/instrumentation-map.csv` using the column
   contract above. Keep the header untouched. Quote a field only when it contains a comma.
3. **Emit it** from the emitter named in the row. Use `bind_context` for correlation and
   `log_event` for delivery. Include every `required_fields` key.
4. **Update `testing/observability/test_events.py`:**
   - add the name to `EMITTED_BY_THIS_BRANCH` when the same PR emits it;
   - add it to `RESERVED_ROWS` when it is declared for another owner and not emitted yet;
   - update the row-count assertion in
     `MapParsingTests.test_map_parses_rfc4180_with_consistent_columns` (currently `73`;
     verify with `wc -l` minus the header).
5. **Run** the map tests and verify one real JSON line:

   ```bash
   python -m unittest discover -s testing/observability -t .
   ZIVON_RUNS_DIR=/tmp/zivon-log-demo python - <<'PY'
   from logging_manager import bind_context, log_event
   bind_context(run_id="demo-run")
   log_event("factory.catalogue.written", {"topics_count": 7, "locales_count": 3},
             stage="11-link", latency_ms=12)
   PY
   cat /tmp/zivon-log-demo/logs/*-factory.jsonl | tail -1
   ```

6. **Update the owning doc** if the surface changed. A new event only needs the map row; a new
   component, enum value, or endpoint also needs `logging-api.md`. A dashboard query changes
   in the dashboard PR, not the emitter PR.

## 3. What map-lint actually checks

From `testing/observability/test_events.py`:

| Test | What it pins |
|---|---|
| `test_map_parses_rfc4180_with_consistent_columns` | the CSV parses, exact header order, row count |
| `test_map_rows_have_valid_severities_and_privacy_classes` | severity and privacy enums |
| `test_every_emitted_name_resolves_to_a_row` | every name in `EMITTED_BY_THIS_BRANCH` has a row |
| `test_emitted_severity_matches_the_map_declaration` | `severity_for(name)` equals the row |
| `test_module_own_events_carry_the_log_component` | `log.*` rows resolve to `log` |
| `test_emitting_a_declared_event_uses_the_map_component` | the map component wins over module inference |

At runtime, `log_event` emits `log.event_unknown` (WARNING, fields `{offender_event}`) for a
name with no row. That is a diagnostic, not a licence to ship.

The map is loaded from `docs/specs/observability/instrumentation-map.csv` relative to the
package, or from `ZIVON_INSTRUMENTATION_MAP` when set. A bare import outside the repo/image has
no map; validation is disabled then, which is why tests run from the repo root.

## 4. Examples

### Pipeline event (new, with a duration)

```csv
factory,factory.catalogue.written,INFO,run_id,topics_count;locales_count,yes,,L1,factory/link.py,11-link regenerated courses.js; duration is the write time
```

```python
# factory/link.py, at the end of run()
log_event(
    "factory.catalogue.written",
    {"topics_count": len(entries), "locales_count": len(locales)},
    stage="11-link",
    latency_ms=int(elapsed * 1000),
)
```

### Pipeline failure (gate-shaped)

```csv
factory,factory.catalogue.smoke_failed,ERROR,run_id,broken_links,no,infra_error,L1,factory/link.py,11-link href/locale smoke gate; feeds factory.run.failed
```

```python
log_event(
    "factory.catalogue.smoke_failed",
    {"broken_links": len(broken)},
    stage="11-link",
    error_class=ErrorClass.INFRA_ERROR,
)
```

`infra_error` is defensible because a broken published link is a publish-integrity failure, not
a model-quality verdict. If the condition is a review gate, use `gate_fail` instead. The point
is that the row and the code agree on one closed class.

### Backend/HTTP event (request-scoped)

```csv
voice,voice.ws.connected,WARNING,request_id,session_count,no,infra_error,L2,voice/ws_api.py,WS accepted but no voice session bound within the grace window
```

```python
log_event(
    "voice.ws.connected",
    {"session_count": active_sessions},
    error_class=ErrorClass.INFRA_ERROR,
)
```

`request_id` is bound by the HTTP/WS edge. Do not also pass `session_id` unless the row says
so and the event is genuinely per-session.

### Frontend event (reuse before adding)

Existing rows (`EVT-F01..F12`) cover page/section views, sim open/interact, check answers, mic
press, turn done, errors, language-bar use, session end, publish view, heartbeat. Only add a row
when none of those expresses the interaction:

```csv
frontend,frontend.worksheet_open,INFO,client_session_id,topic;worksheet_id,no,,L2,frontend shell (zivon.js; F-2 contract),EVT-F13 (new id requires the frontend spec change); no free text
```

```js
// frontend/assets/zivon.js — first add the EVENT_CATALOG entry (below), then
// record through the existing queue, never a raw fetch
// "EVT-worksheet_open": { evt_id: "EVT-F13", event: "frontend.worksheet_open", privacy_class: "L2" }
window.ZivonEvents.emit("EVT-worksheet_open", { topic: topic, worksheet_id: id });
```

An id that is not in `EVENT_CATALOG` falls back to `EVT-F08` with the raw name as `event`, so
the catalogue entry is part of the change, not an afterthought.

A new `EVT-Fxx` id is a frontend-spec change (`docs/specs/observability/spec.md` §8), not just a
JS string. The browser must keep working when the beacon is dropped.

## 5. Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Row added, count assertion not bumped | CI red in `testing/observability` | Update `len(rows) == 73` in the same PR |
| Name added to `EMITTED_BY_THIS_BRANCH` with no row | `test_every_emitted_name_resolves_to_a_row` fails | Add the row or move the name to `RESERVED_ROWS` |
| Row declares `latency_ms=no` but code passes `latency_ms` | Field appears while the row says it should not; review finding | Mark the row `yes`/metric name, or drop the argument |
| Failure row has blank `error_class` | Dashboard cannot group it; review finding | Pick the closed class |
| `severity=ERROR` passed at the call site for an `INFO` row | Overrides the declared severity and defeats the map | Change the row (spec change if it affects consumers) |
| `required_fields` uses commas | CSV row splits into extra columns | Use `;` |
| Emitter names a file that never emits | Dead row; the next agent trusts it | Point at the real symbol or mark `RESERVED_ROWS` |
| Frontend event added without an `EVT-Fxx` contract | Ingest rejects it; catalogue drifts | Add the spec row and the ingest allow-list entry first |

## 6. Verification checklist

```text
[ ] Name is unique and follows <component>.<subject>.<action>
[ ] Component is in the closed enum
[ ] Severity, privacy class, correlation ids, required fields are declared
[ ] latency_ms / error_class match the event's shape
[ ] Emitter exists and calls log_event with the declared fields
[ ] testing/observability/test_events.py updated (name + row count)
[ ] JSON line observed in a sink (stdout or runs/logs)
[ ] PR names the event and its consumer, or says "audit only"
```
