# ADR-0028: LLM-as-Judge Model Selection, Calibration Anchor Strategy, and Cost Budget

- **Status**: accepted (Wave S1 — `SP4-EVALS`)
- **Date / deciders**: 2026-11-09 / Founder + `SP4-EVALS`
- **Driving NFRs / requirements**:
  - `AGENTS.md` Non-Negotiable: *"All model calls go through `llm_manager/`... NO other module may hand-roll HTTP calls to an inference server."*
  - `NEED-JUDGE-CALIBRATION`: LLM judges (`EV-CUR-001`, `EV-SYN-001`, `EV-SYN-002`, `EV-VIS-001`, `EV-REV-001`, `EV-REV-002`) must achieve `100%` recall on planted `fatal` defects and `0%` false-fatal rate on clean golden pages (`skills/prompting-and-agent-design/SKILL.md` `[S2][S7]`).
  - `NFR-COST-BUDGET`: CI PR checks must cost `0` model calls and require `0` API keys; scheduled in-cluster full eval runs (`k8s/52-eval-cronjob.yaml`) must stay bounded in call count (`<= 30` calls/run), wall-clock time (`<= 3600s`), and thinking tokens (`<= 35,000` completion tokens/call), and must **never** spend Gnani voice programme credits (`5,000` credit pool reserved for Prisma/Timbre/Evon runtime voice demo per `AGENTS.md` line 202).

---

## Context

The `evals/` framework evaluates both:
1. **Generated topic artifacts** (Curator claims, Synthesizer lessons/blocks, Visual Builder JS/CSS/HTML), and
2. **The factory's own reviewer stages** (`03-check` in `EV-REV-001` and `09-review-facts`/`09-review-design` in `EV-REV-002`) against a seeded-defect corpus (`19` samples total: `5` deterministic security defects + `14` model-evaluated samples).

We must decide:
- Which model acts as the LLM judge in `evals/judges/`,
- How judge calls route through the cluster (`llm_manager`),
- How to mitigate self-preference bias when the judge model and generator model are the same weight family, and
- How to bound compute/token cost so evals never starve factory runs or burn Gnani runtime credits.

---

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Option 1: Use Proprietary Frontier API Directly from `evals/` (e.g., direct Anthropic/OpenAI SDK calls)** | Strong out-of-the-box reasoning; cross-family from Qwen/Evon. | Violates `AGENTS.md` (`llm_manager` law + single-model node guard); fails in offline cluster pods (gotcha 15: pods only reach `llm-manager`); introduces second paid API key. | Paid per-token API + extra Secret management. | Fails `AGENTS.md` `llm_manager` law and cluster network isolation (gotcha 15). |
| **Option 2: Use Gnani Evon API Credits for Build-Time Evals** | Tests Evon on grading rubrics. | Burns the scarce 5,000 Gnani programme credit pool needed for the runtime voice loop and judge demo traffic (`AGENTS.md` line 202, `TIMELINE.md` Guiding Rule 4). | High credit risk (`~500k+` tokens per full eval run). | Fails `NFR-COST-BUDGET` and `TIMELINE.md` Guiding Rule 4. |
| **Option 3: Route All Judge Calls Through `llm_manager/` Using `ZIVON_MODEL` by Default, with Optional `ZIVON_EVAL_JUDGE_MODEL` Override + Deterministic-First Funnel + Quote-Grounded Rubrics (Selected)** | Obeys `llm_manager/` law 100%; works in-cluster through `http://llm-manager.zivon.svc.cluster.local:80/v1`; deterministic-first funnel cuts PR cost to `0` calls; quote-grounding + arithmetic recomputation + seeded-defect calibration (`EV-REV-001/002`) eliminate self-preference vibes; supports pointing `ZIVON_EVAL_JUDGE_MODEL` at a distinct model when run outside the single-model node or via a secondary node upstream. | When running in-cluster through the single-model `llm-manager` node (`k8s/16`), generator and judge share `ZIVON_MODEL` unless a judge-specific `LLMConfig` upstream is configured. | `0` calls on PRs (`eval-smoke`); `26` calls per 6-hour CronJob run (`~150k–400k` tokens on OpenRouter / ₹0 on local Strata server). | Fails none. |

---

## Decision

We adopt **Option 3**:

1. **Mandatory `llm_manager` Routing**:
   - Every LLM judge in `evals/judges/` calls `llm_manager.LLMManager` + `llm_manager.validation.run_validation_rounds`. No module in `evals/` may import `requests`, `httpx`, or `openai` directly (enforced by a static isolation unit test mirroring `test_llm_manager_service.py::test_service_module_never_imports_factory`).
2. **Judge Model Configuration (`ZIVON_EVAL_JUDGE_MODEL` & `ZIVON_EVAL_BASE_URL`)**:
   - In `evals/config.py`, the judge's `LLMConfig` resolves:
     - `base_url = os.environ.get("ZIVON_EVAL_BASE_URL") or os.environ["ZIVON_BASE_URL"]`
     - `model = os.environ.get("ZIVON_EVAL_JUDGE_MODEL") or os.environ["ZIVON_MODEL"]`
     - `temperature = 0.0` (deterministic greedy decoding for all judge and calibration calls, overriding the generator's `0.2` default).
   - **In-Cluster Default (`k8s/52-eval-cronjob.yaml`)**: Uses `zivon-factory-config` (`ZIVON_BASE_URL=http://llm-manager.zivon.svc.cluster.local:80/v1`, `ZIVON_MODEL=stealth/crouton-alpha` or local fallback `qwen3.8-flash-next-iq3_xxs`). Because the `llm-manager` service node enforces a single-model guard (`llm_manager/service/app.py` returns HTTP 400 on model mismatch), in-cluster runs use `ZIVON_MODEL` unless a dedicated judge upstream (`ZIVON_EVAL_BASE_URL` + `ZIVON_EVAL_JUDGE_MODEL`) is set.
   - **Cross-Model Audit Mode (Local / Pre-Release)**: Operators can set `ZIVON_EVAL_BASE_URL` and `ZIVON_EVAL_JUDGE_MODEL` to a second model (e.g., evaluating pages generated by local `qwen3.8-flash-next-iq3_xxs` using cloud `stealth/crouton-alpha`, or vice versa) with zero code changes.
3. **Mitigating Self-Preference Bias Without a Second Cluster Node**:
   - Literature (`[S2]`, `[S7]` RUVERBENCH EMNLP 2026 in `skills/prompting-and-agent-design/references/sources-and-evidence.md`) shows that self-preference bias occurs when an LLM judge scores prose on holistic/Likert scales, and drops sharply when the judge is constrained to **verifiable item-level tasks**:
     1. **Quote-Grounded Fatal Rule**: Every `fatal` factual or coverage finding must include a verbatim quote or section/page locator from the source pack; `evals/judges/base.py` verifies that quoted substrings appear in the source pack.
     2. **Explicit Recomputation**: Numerical checks (`EV-SYN-002`, `SD-CHK-002`) require recomputing the formula from problem numerals rather than judging whether the prose "sounds right."
     3. **Seeded-Defect Calibration Gate (`EV-REV-001` & `EV-REV-002`)**: Before trusting any judge model on golden pages, `--suite full` runs the judge against `14` planted defect/clean samples (`SD-CHK-001..008` and `SD-REV-001..006`). If the judge's `fatal` recall drops below `1.00` or its clean-golden specificity drops below `1.00`, the eval run fails loudly as an `UNCAUGHT_SEEDED_DEFECT` calibration failure.
4. **Call-Cost & Token Budget per Suite**:

| Suite | When Run | Deterministic Checkers | LLM Judge Calls | Typical Token Budget | Gnani Voice Credits Used |
|---|---|---|---|---|---|
| `smoke` | Every PR (`.github/workflows/ci.yml`), `apply-k8s.sh` startup | All (`3` golden topics + `5` `SD-SEC` security defects + `mid-laptop` perf) | **`0` calls** | `0` tokens | `0` |
| `calibrate` | On prompt/reviewer edits (`scripts/trigger-evals.sh calibrate`) | Prompt contracts + `5` `SD-SEC` defects | **`20` calls** (`8` for `EV-REV-001` + `12` for `EV-REV-002`) | `~120k` prompt / `~80k` completion | `0` |
| `full` | Every 6h (`k8s/52-eval-cronjob.yaml`) + pre-release | All deterministic + `weak-android` perf | **`26` calls** (`20` calibration + `6` judge calls across published golden topics; reuses cached `run_report` when golden SHA is unchanged) | `~220k` prompt / `~140k` completion | `0` |

---

## Consequences

- **What gets easier**:
  - Zero new K8s Deployments or Services are required for `evals/` — `k8s/52-eval-cronjob.yaml` reuses the existing `zivon-factory` image and `llm-manager` Service (`k8s/16-llm-manager.yaml`).
  - Swapping the cluster's model in `k8s/infra.env` immediately tests whether the new model still passes reviewer calibration (`EV-REV-001`, `EV-REV-002`).
  - Gnani's 5,000 runtime credits remain 100% protected for the voice tutor demo.
- **What gets harder**:
  - Full calibration + judge suites (`26` calls) take `~5–8 minutes` on OpenRouter (`stealth/crouton-alpha`) and `~45–60 minutes` on a single-slot ~20 tok/s local server; therefore `k8s/52-eval-cronjob.yaml` uses `concurrencyPolicy: Forbid` and a 6-hour schedule rather than running every 30 minutes.
- **What we must monitor**:
  - `max_completion_tokens` and `thinking_s` (`first_token_s`) per judge call in `eval_report.json` — any judge call exceeding `35,000` completion tokens or hitting `finish_reason == "length"` flags a prompt-scope regression.

---

## Revisit trigger

- Revisit if a candidate `ZIVON_MODEL` passes `EV-E2E-001` on its own outputs while failing `EV-REV-001` / `EV-REV-002` seeded defects (indicating model weakness on rubric verification), or if human kid-testing (`EV-KID-001`) uncovers factual errors that `EV-SYN-002` and `EV-REV-001` both passed (`false_negative_escape_count >= 1`).

---

## References

- [`docs/specs/evals/spec.md`](../../specs/evals/spec.md) §2 (Eval Card Design) & §5 (CI Wiring)
- [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md) (Reviewers get calibrated rubrics, honest framing, `unverified:` way-out)
- [`skills/prompting-and-agent-design/references/sources-and-evidence.md`](../../../skills/prompting-and-agent-design/references/sources-and-evidence.md) (`[S2]` Anthropic Agent Evals Jan 2026; `[S7]` RUVERBENCH EMNLP 2026)
- [`llm_manager/README.md`](../../../llm_manager/README.md) (Single model-call module & service node contract)
