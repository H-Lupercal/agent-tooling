# Claude SessionStart Transcript Compatibility Fix

## Summary

The Claude Code integration cannot generate its state store. When Claude Code
fires the `SessionStart` hook, its payload always includes a `transcript_path`
pointing at the Claude session `.jsonl`. `resolve_run_context()` unconditionally
parses that path as a **Codex rollout** via `read_session_meta()`, which requires
the first JSONL line to contain an `event["payload"]` object. Claude Code
transcripts use a different schema — the first line is
`{"type":"last-prompt","leafUuid":...,"sessionId":...}` with no `payload` key —
so `read_session_meta()` raises `ValueError("... payload must be an object")`,
which `resolve_run_context()` rewraps as
`StateError("invalid run context transcript: ...")`.

`session_start.main()` catches that and emits
`{"conductor":{"ready":false,"error":"StateError"}}` without ever constructing
the `Store`, so `~/.claude/conductor/state/conductor.db` is **never created**.
Every downstream Claude command (`conductor status`, `report`, `recovery`) then
fails with "conductor store does not exist," and `doctor --provider claude`
reports the store as "not created yet."

The fix: do not parse the transcript as a Codex rollout for the Claude provider.
Claude's run id and thread id already come from explicit payload fields
(`session_id`), so the rollout metadata is unnecessary for Claude. Codex behavior
is unchanged.

## Constraints & Assumptions

- **Scope is `resolve_run_context()` in `src/conductor/identity.py` only.** No
  change to `read_session_meta()`, the accounting/usage transcript path
  (`accounting.py` → `claude_transcript_usage`/`latest_usage`), the Claude
  `resolve_caller` override, or any provider contract.
- **Codex behavior must be byte-for-byte preserved**, including the existing
  strict raise on an unreadable/corrupt Codex rollout transcript. This strict
  raise is what surfaces genuine Codex problems (e.g. the sandbox WAL-open case);
  it must remain for Codex.
- **Verified fact — Claude does not need transcript-derived identity.**
  `session_start.handle()` (`src/conductor/hooks/session_start.py:26-50`) resolves
  `resolved_run_id = run_id or provider.session_run_id(payload) or caller.run_id`
  (Claude's `session_run_id` returns `session_id`) and `thread_id = caller.thread_id
  or resolved_run_id`, then passes both as explicit `"run_id"` and `"thread_id"`
  keys into `resolve_run_context()`. So for Claude, `explicit_run` and
  `explicit_thread` are always set and the `meta` fallbacks
  (`identity.py:116-121`) are never taken. This was confirmed empirically: the
  same Claude `SessionStart` payload succeeds and generates the DB when
  `transcript_path` is absent, and fails only when it is present.
- **`read_session_meta` callers audited.** It is called at `identity.py:53` and
  `identity.py:64` (inside the base `resolve_caller`, which Claude overrides in
  `providers/claude.py:61`, so it is Codex-only in practice), at `identity.py:110`
  (the bug site, inside `resolve_run_context`), and at `rollout.py:182` (inside
  `find_rollout`, Codex rollout discovery). Only the `identity.py:110` call runs
  in the Claude `SessionStart` path.
- **Provider enum.** `conductor.schemas.Provider` has members `CODEX` (value
  `"codex"`) and `CLAUDE` (value `"claude"`). `resolve_run_context()` already
  computes a `provider: Provider` local at `identity.py:101-105`.

### Open questions

None. The mechanism, blast radius, and Claude's independence from rollout
metadata are all confirmed by reproduction (see Test Plan).

## Affected Files

- **Modify:** `src/conductor/identity.py` — gate the transcript-metadata read in
  `resolve_run_context()` to the Codex provider only.
- **Modify (add test):** `tests/test_session_start.py` — add a regression test
  that a Claude `SessionStart` payload carrying a non-rollout `transcript_path`
  still resolves and persists a leased run.
- No other files change.

## Public Interfaces

No public signature changes. `resolve_run_context(payload: dict) -> RunContext`
keeps its signature; only its internal transcript-handling branch changes.

## Implementation Plan

1. In `src/conductor/identity.py`, `resolve_run_context()`, replace the
   transcript-read branch (current lines 106-112):

   ```python
   transcript = payload.get("transcript_path") or payload.get("agent_transcript_path")
   meta: SessionMeta | None = None
   if transcript:
       try:
           meta = read_session_meta(Path(transcript))
       except (OSError, ValueError, json.JSONDecodeError) as exc:
           raise StateError(f"invalid run context transcript: {exc}") from exc
   ```

   with a provider-gated version that only parses the transcript for Codex:

   ```python
   transcript = payload.get("transcript_path") or payload.get("agent_transcript_path")
   meta: SessionMeta | None = None
   if transcript and provider is Provider.CODEX:
       try:
           meta = read_session_meta(Path(transcript))
       except (OSError, ValueError, json.JSONDecodeError) as exc:
           raise StateError(f"invalid run context transcript: {exc}") from exc
   ```

   The only change is adding `and provider is Provider.CODEX` to the `if`
   condition. `provider` is already bound at `identity.py:101-105`. Do not remove
   the `meta`-based fallbacks at `identity.py:116-121`; they remain correct for
   Codex and are simply never triggered for Claude (which always supplies explicit
   ids).

2. Leave `read_session_meta` (`src/conductor/rollout.py`) and all other callers
   untouched.

Steps 1 and the test in the Test Plan are independent and may be authored in
parallel, but the test must be run against the modified code.

## Error Handling

- **Codex, transcript present and valid:** unchanged — `meta` is parsed and used.
- **Codex, transcript present and unreadable/corrupt/non-rollout:** unchanged —
  still raises `StateError("invalid run context transcript: ...")`. This preserves
  detection of real Codex store/transcript problems.
- **Claude, transcript present (normal case):** transcript is **not** read;
  `meta` stays `None`; `run_id`/`thread_id` come from the explicit payload fields;
  run context resolves and the caller (`session_start.handle`) proceeds to create
  the `Store` and the run. DB is generated.
- **Claude, transcript absent:** unchanged from today (already worked) — `meta`
  is `None`, explicit ids used.
- **Any provider, no transcript key at all:** unchanged — branch skipped.

## Test Plan

Framework: pytest (existing `tests/`). Boundary: no live services; uses a
temp `CODEX_CONDUCTOR_HOME`, the bundled Claude config, and a temp transcript
file. Mirror the existing style of
`tests/test_session_start.py::test_session_start_persists_one_strict_leased_context`
and the Claude-config helper `CLAUDE_CONFIG` used in
`tests/test_provider_claude.py`.

Add to `tests/test_session_start.py`:

```python
def test_claude_session_start_ignores_non_rollout_transcript(tmp_path: Path) -> None:
    from conductor.hooks.session_start import handle

    # First line matches a real Claude Code transcript: no `payload` object,
    # which read_session_meta() rejects as a Codex rollout.
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        '{"type":"last-prompt","leafUuid":"abc","sessionId":"claude-run-1"}\n',
        encoding="utf-8",
    )
    home = tmp_path / "home"
    config = write_config(tmp_path / "conductor.claude.toml", CLAUDE_CONFIG_TEXT)
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(config),
        CODEX_CONDUCTOR_SESSIONS_ROOT=str(tmp_path / "sessions"),
    )
    try:
        store = Store(tmp_path / "state.db")
        context = handle(
            {
                "provider": "claude",
                "session_id": "claude-run-1",
                "transcript_path": str(transcript),
                "model": "claude-opus-4-8",
                "source": "startup",
            },
            provider_name="claude",
            store=store,
        )
    finally:
        restore_env(old)

    assert context.run_id == "claude-run-1"
    assert context.provider.value == "claude"
    assert store.run_context("claude-run-1") == context
```

Notes for the implementer:
- Reuse the Claude config text. `tests/test_provider_claude.py` defines a
  `CLAUDE_CONFIG` path fixture at module scope (built from an inline TOML string).
  Either import/replicate that inline Claude TOML as `CLAUDE_CONFIG_TEXT` for
  `write_config`, or load the bundled asset
  `src/conductor/assets/config/conductor.claude.toml`. The config must declare the
  Claude tiers so `load_config()` resolves `claude` models; do not reuse
  `DEFAULT_CONFIG` (that is the Codex ladder).
- The test must **fail before** the one-line change (raising
  `StateError: invalid run context transcript: invalid session metadata: payload
  must be an object`) and **pass after**.

Also run the existing suites to confirm no regression, in particular:
`tests/test_session_start.py`, `tests/test_identity.py`,
`tests/test_provider_claude.py`, `tests/test_rollout.py`.

## Acceptance Criteria

- [ ] `resolve_run_context()` reads the transcript via `read_session_meta()` only
      when `provider is Provider.CODEX`; the sole code change is the added
      `and provider is Provider.CODEX` guard on the existing `if transcript:`
      branch.
- [ ] New test `test_claude_session_start_ignores_non_rollout_transcript` fails on
      the pre-fix code and passes on the post-fix code.
- [ ] All existing tests pass (`make test` or the project's pytest invocation),
      with no changes required to any Codex-path test.
- [ ] Manual end-to-end check: with the fix in place, running the Claude
      `SessionStart` handler against a real Claude transcript generates the store:

      ```bash
      # isolated home so ~/.claude is untouched
      TMP=$(mktemp -d); export CODEX_CONDUCTOR_HOME="$TMP/claude-conductor"
      python -c "
      from conductor.hooks.session_start import handle
      handle({'provider':'claude','session_id':'s1',
              'transcript_path':'<a real .claude/projects/**/*.jsonl>',
              'model':'claude-opus-4-8','source':'startup'},
             provider_name='claude')
      "
      test -f "$CODEX_CONDUCTOR_HOME/state/conductor.db" && echo STORE_CREATED
      ```

      must print `STORE_CREATED`.
- [ ] Codex regression guard: a Codex `SessionStart` payload with a **corrupt**
      `transcript_path` (first line not a valid rollout) still raises
      `StateError("invalid run context transcript: ...")` — behavior unchanged.
