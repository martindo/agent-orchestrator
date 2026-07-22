# Audit Task List

Source: full-codebase audit, 2026-07-22 (six parallel subsystem audits). Check items off as completed.

**Verdict:** This is a substantially real platform — the orchestration loop makes real LLM calls, all 11 connectors make real API calls, MCP uses the real SDK, Studio is wired end-to-end. But the "Phase 34 Complete / All Features Implemented / 1451 tests passing / zero known issues" claim is false in specific, load-bearing ways: **no auth anywhere, a PostgreSQL backend that doesn't exist, governance running on a constant, an audit trail that isn't tamper-evident, and latent bugs hidden behind swallowed exceptions.**

> **✅ Test baseline (measured 2026-07-22):** the suite now *runs* (install PyPI via `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e ".[dev,llm,mcp]"` — plain install hit a corporate-CA SSL error). **The "1451 passing / zero known issues" claim was false.** As shipped, the `tests/` suite was **1342 passing, 14 failing, +1 flaky** — and it couldn't even be collected without the optional `llm`/`mcp` extras (a `cannot import name 'AnthropicProvider'` collection error breaks *all* tests when those SDKs are absent). The 14 failures were **stale tests**: connector providers had grown operations (Slack gained `list_channels`/`upload_file`/`send_notification`; repository providers gained *write* ops `create_pull_request`/`create_issue`/`add_review_comment`; ticketing gained `transition_ticket`/`get_sprint_issues`) and the MCP manager now raises the more-specific `MCPConfigurationError` — none of the assertions were updated because **there is no CI** (Tier 5.1) running them. After the fixes below the suite is **1357 passing, 0 failing**, deterministic across repeat runs. Studio's separate suite was not run here.

Effort tags: **S** = under a day, **M** = 1–3 days, **L** = a week+.

---

## Tier 1 — Correctness quick wins (latent bugs; small diffs)

- [x] **1.1 (S)** `_artifact_store` dead on every startup (`state_dir` used before assignment → swallowed `UnboundLocalError`). ✅ 2026-07-22 — moved the `state_dir` definition + `mkdir` above the artifact-store init; artifact persistence now initializes. Runtime-verified: full suite green.
- [x] **1.2 (S)** Silent mock LLM fallback → now raises. ✅ 2026-07-22 — `LLMAdapter.call` raises `ConfigurationError` when no provider is registered instead of returning a fabricated `confidence:0.5` success. Two tests *did* rely on the old fake behavior (`test_returns_mock_for_unregistered_provider`, `test_work_processing_records_metrics`) — updated them (see test-suite work below). Runtime-verified.
- [~] **1.3 (S)** Broad exception-swallowing hides init failures. Partial 2026-07-22 — the artifact-store swallow now logs at `error` (was `debug`). **Still to do:** the SLA-monitor / gap / MCP init swallows.
- [x] **1.4 (S)** Stale "Phase 5 placeholder" comments. ✅ 2026-07-22 — corrected `agent_executor.py` module + `_default_llm_call` docstrings to state the engine injects a real adapter and the stub is a TEST-ONLY fallback.
- [ ] **1.5 (S)** Dead stub endpoints — `GET /config/history` always returns `[]` (`api/routes.py:1169`) despite `persistence/config_history.py` implementing it; `api/benchmark_routes.py:418,435` return `[]` unconditionally. Wire them to the real stores or 501 honestly.

## Tier 2 — Security floor (nothing is enforced today)

- [x] **2.1 (M)** **Enforce authentication (configurable, secure default per mode).** ✅ 2026-07-22 — added `middleware/api_auth.py`: an `AuthMiddleware` wired into `create_app` that, when enabled, requires `Authorization: Bearer <jwt>` on all routes except an allowlist (login/register/verify, health, docs). Enablement resolves from `AGENT_ORCH_AUTH_ENABLED` → else the deployment mode (`enterprise` → on, `lite`/`standard` → off), so a single-user LITE profile isn't forced into auth but an ENTERPRISE deployment is secured by default. `/auth/me` now returns the real verified principal (or an explicit anonymous session), not a hardcoded `anonymous`. Covered by 18 tests. **Still open:** Studio API (`studio/app.py`) and the WebSocket handshake are not yet gated (tracked in 6.x).
- [x] **2.2 (S)** Hardcoded JWT secret → env-driven + fail-closed. ✅ 2026-07-22 — `shared_auth.get_secret()` reads `AGENT_ORCH_JWT_SECRET`; `is_secret_secure()` reports the dev default as insecure; enabling auth on the default secret raises `ConfigurationError` (refuses to start on a forgeable secret).
- [x] **2.3 (S)** Plaintext default credentials → hashed + gated. ✅ 2026-07-22 — passwords are stored as salted PBKDF2-HMAC-SHA256 (stdlib, no plaintext); the `admin`/`developer` convenience accounts are seeded only when auth is disabled (local dev) or `AGENT_ORCH_SEED_DEFAULT_USERS=true`, so a secured deployment ships no working default login. (User store is still in-memory — persistence tracked separately.)
- [ ] **2.4 (S)** Studio stores LLM API keys in **plaintext** at `workspace_dir/studio-settings.yaml` (`studio/routes/settings_routes.py:127-143`); the runtime's key handling is safer (env-stripped on save) — align Studio.
- [~] **2.5 (M)** ~15 endpoints accept raw `body: dict` with no Pydantic schema. Partial 2026-07-22 — the 4 auth endpoints now use request models (`LoginRequest`/`RegisterRequest`/`VerifyRequest`). **Still to do:** the remaining ~11 raw-`dict` endpoints.

## Tier 3 — Make the core promises actually true

- [ ] **3.1 (M)** **Confidence-based governance is inert with real LLMs.** Providers return no `confidence` field, so `output_parser.extract_confidence` returns the 0.5 default and `aggregate_confidence` is *always* 0.5 → a fixed `ALLOW_WITH_WARNING`. ABORT/QUEUE_FOR_REVIEW can essentially never fire on real output. **Fix:** instruct agents (in the user-prompt builder) to return structured output with a `confidence` field and parse it — or drop the confidence-gating pretense. (`core/output_parser.py:39-103`, `agent_executor._build_user_prompt`.)
- [ ] **3.2 (M)** **Audit trail is not tamper-evident** despite the claim — `governance/audit_logger.verify_chain` (`:238-267`) never recomputes content hashes (only checks link pointers); the event `data` payload is unhashed (`:146-154`); the hash is truncated to 64 bits (`hexdigest()[:16]`); rotation resets `_last_hash=""` severing the chain. **Fix:** hash the full record incl. payload, recompute+verify in `verify_chain`, use the full digest, chain across rotations.
- [ ] **3.3 (S)** `decision_ledger` hash omits mutable fields (`tool_calls`, `warnings`, `review_notes`, `duration_seconds`, `metadata`) — they're outside the SHA-256 chain and silently editable. Include them (or document what's intentionally excluded).
- [ ] **3.4 (M)** **Operational state lost on restart** — `WorkQueue` is recreated empty (`engine.py:266`) and never repopulated from the persisted `work_item_store`; `PipelineManager._entries` is in-memory only. Queued/in-flight work is orphaned (the record persists, nothing re-enqueues). Rebuild the queue + pipeline positions from `get_incomplete()` on start.
- [ ] **3.5 (S)** Review queue runs **in-memory** in the engine — constructed as `ReviewQueue()` with no path (`engine.py:300`), contradicting the Phase-32 "JSONL persistence" claim; pending human reviews are lost on restart. Pass a persistence path.
- [ ] **3.6 (S)** Dead gap-detector sub-checks — `retry_count`, `critic_rejection_count`, `gate_failure_count` are never incremented, so `_check_retry_rate`/`_check_critic_rejection` (`gap_detector.py:384-423`) can never fire. Wire the counters or remove the dead checks.
- [ ] **3.7 (M)** Catalog/skill-map never learn from real executions — `SkillMap.record_execution` is called only from `api/skillmap_routes.py`, never by the engine after real agent runs; `SKILL_UPDATED` is defined but never emitted. Wire `record_execution` into the completion path so skill metrics reflect reality. `TeamRegistry` is also passive (never consulted during routing).

## Tier 4 — Honesty pass (wire it or label it; fix docs)

- [ ] **4.1 (M)** "Semantic search" is keyword matching — `knowledge/embedding.py` `EmbeddingService` is real code but **never instantiated**; `store.semantic_query()` always raises `KnowledgeError`, so runtime retrieval (`store.retrieve()`) is keyword/tag overlap. Either wire the embedding service into `KnowledgeStore` or relabel Phase-33 "semantic query" as keyword.
- [ ] **4.2 (S)** **`eval()`** in `core/workflow_branching.py:43` (reachable via `api/branching_routes.py`) directly contradicts the Phase-32 "no eval/exec of arbitrary expressions" claim; guarded only by a permissive regex + injection-prone string substitution. Replace with the safe evaluator already used by `governor.py`/`quality_gate.py`.
- [ ] **4.3 (S)** Webhook "with retries" is false — `adapters/webhook_adapter.py:84-99` does a single POST and swallows errors; PROGRESS.md:272 claims "httpx-based POST with retries." Implement retry/backoff (+ optional HMAC signing) or fix the doc.
- [ ] **4.4 (L/decision)** **PostgreSQL backend is a facade** — `PersistenceBackend.POSTGRESQL` enum + `db/init/01_schema.sql` + a `postgres:16` compose service exist, but no driver, no `DATABASE_URL` read, no connection code anywhere in `src/`; compose doesn't even wire `DATABASE_URL` into the app. Decide: implement it, or mark not-implemented and remove it from the enum/compose advertising.
- [ ] **4.5 (S)** Cost tracking is fake — providers return real `usage` tokens but nothing prices them; `core/cost_optimizer.py:39-48` uses a flat `cost_per_1k * 10` guess with **invalid/stale model IDs** (`claude-sonnet-4-6`, `claude-opus-4-6`, `o3`). Price real usage; fix the model IDs.
- [ ] **4.6 (S)** Contract validation is dormant — `engine.py:312` builds `ConnectorService` **without** a `contract_validator`, so `_validate_input/output_contract` always early-returns; the whole contracts framework (Phase 19, 59 tests) never runs on the default execute path. Inject the validator, or document it as opt-in.
- [ ] **4.7 (S)** Docs honesty: PROGRESS.md "zero known issues" is false; the Phase-32 "no eval/exec" claim is contradicted (see 4.2); "tamper-evident audit trail" (3.2) and "webhook retries" (4.3) overstate; Studio frontend page count is understated (9, not 8 — docs undercount, unusual). Reconcile.
- [ ] **4.8 (S)** Deprecated upstream endpoints — Slack `files.upload` (`slack.py:498`) and Jira `/rest/api/3/search` (`jira.py:345`) are deprecated by the vendors and will break over time; migrate.

## Tier 5 — Foundation (CI, hygiene, tests)

- [ ] **5.1 (S)** **No CI** — `.github/` does not exist. The "1451 passing" was gated by nothing, and in fact 14 tests had rotted to red (now fixed). Add a GitHub Actions workflow: install `.[dev,llm,mcp]`, run `pytest tests` + the studio suite. **Must install the `llm`/`mcp` extras or collection fails outright.** Also pin/lock deps (see 5.x below) — the suite was only run against *latest* PyPI here.
- [x] **5.7 (S)** Stale/flaky tests fixed to restore a real green baseline. ✅ 2026-07-22 — updated the 14 stale connector/MCP descriptor assertions to the current provider surface; made `test_expired_session_evicted` deterministic (it backdates `last_activity` instead of relying on `sleep(0.01)` crossing a strict `elapsed > ttl` on a coarse clock); reworked `test_skips_provider_on_import_error` to fail only the target import instead of globally patching `importlib.import_module` (which broke unittest.mock's own target resolution). Suite: 1357 passing, 0 failing.
- [ ] **5.2 (S)** **`studio/frontend/node_modules/` is committed — 4,613 tracked files** (~91% of the repo's ~5,062 tracked files). `git rm -r --cached` it, add to `.gitignore`. Also untrack `workspace/` runtime files.
- [ ] **5.3 (S)** Cross-project cruft — `_setup_packages.py` adds a sibling `../coderswarm-packages` to `sys.path` (references to "coderswarm-v2" also in `settings_store.py` docstrings) — leftovers from another codebase. Remove.
- [ ] **5.4 (M)** Core-execution unit tests assert the **stub** — `test_core.py:445` runs `AgentExecutor` with no `llm_call_fn` and asserts `confidence == 0.85` (the mock's value). The real `LLMAdapter` execution path (with a mocked provider SDK) is under-tested end-to-end. Add tests that exercise the adapter path.
- [ ] **5.5 (S)** No end-to-end generator→loader test (Studio) — generation tests stop at YAML parseability; add a test that loads Studio-generated YAML through the runtime's `configuration/loader.py` + `ProfileConfig` to prove compatibility.
- [ ] **5.6 (S)** Web-search provider tests don't assert request correctness (no `call_args`/`assert_called` — `test_web_search_providers.py`), so a wrong endpoint/auth would pass. Other categories check sparsely; strengthen.

## Tier 6 — Robustness / follow-ups

- [ ] **6.1 (M)** Studio project state is in-memory/volatile — a single global `current_team` (`studio/routes/team_routes.py`), no project list/multi-project, lost on restart. Persist projects.
- [ ] **6.2 (M)** MCP client session lifecycle is fragile — `mcp/client_manager._create_session:151-177` manually drives anyio context managers across call frames; may throw "cancel scope in different task" against live servers. Restructure to enter/exit within one task (e.g. an `AsyncExitStack` owned by a single task).
- [ ] **6.3 (S)** Connector executor retries generic `FAILURE` by default (`executor.py:28`), so non-idempotent writes (create_ticket, send_message) can be retried on ambiguous failures — narrow `retryable_statuses` for write ops.
- [ ] **6.4 (S)** Provider token-usage is uneven — Google and Ollama providers return no usage, breaking any downstream accounting once 4.5 is fixed.

---

## Progress log

| Date | Item(s) | Notes |
|------|---------|-------|
| 2026-07-22 | 1.1, 1.2, 1.4 (+1.3 partial) | First correctness wave on branch `audit/fixes`. Fixed the artifact-store use-before-assignment (dead on every start), made the silent mock-LLM fallback raise instead of fabricating, corrected stale placeholder comments. |
| 2026-07-22 | Test baseline + 5.7 | Got the suite actually running (`--trusted-host` install with `[dev,llm,mcp]`). Measured real baseline: **1342 pass / 14 fail / 1 flaky** — disproving "1451 passing / zero known issues". Fixed all 14 stale tests + the flaky MCP session test + the 2 tests that depended on the removed mock. **Now 1357 pass / 0 fail, deterministic.** Surfaced a security-relevant signal: repository connectors gained write ops guarded by an old read-only invariant (flagged in 2.1 / test comment). |
| 2026-07-22 | 2.1, 2.2, 2.3, 2.5 (partial) | Security floor. Configurable auth-enforcement middleware (secure default per deployment mode, not forced); JWT secret from env with fail-closed on the dev default; default creds hashed (PBKDF2) and gated out of secured deployments; auth endpoints got request models; `/auth/me` returns the real principal. 18 new tests. **Suite: 1375 pass / 0 fail.** |
