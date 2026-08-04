import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";

import { parseTranscriptState, sessionFileMatchesState } from "../restoration";

const SESSION_ID = "019fc513-7044-7281-979d-6660f0ee8acd";

test("restoration accepts persisted transcript identity", () => {
  assert.deepEqual(
    parseTranscriptState({
      sessionId: SESSION_ID,
      filePath: `/codex/sessions/2026/rollout-${SESSION_ID}.jsonl`,
    }),
    {
      sessionId: SESSION_ID,
      filePath: `/codex/sessions/2026/rollout-${SESSION_ID}.jsonl`,
    },
  );
});

test("restoration rejects malformed webview state", () => {
  for (const state of [
    undefined,
    {},
    { sessionId: "not-an-id", filePath: "/tmp/session.jsonl" },
    { sessionId: SESSION_ID, filePath: "relative/session.jsonl" },
  ]) {
    assert.equal(parseTranscriptState(state), undefined);
  }
});

test("restoration only reads the matching transcript beneath Codex sessions", () => {
  const codexHome = path.resolve("/codex");
  const validPath = path.join(codexHome, "sessions", "2026", `rollout-${SESSION_ID}.jsonl`);
  assert.equal(sessionFileMatchesState(codexHome, { sessionId: SESSION_ID, filePath: validPath }), true);
  assert.equal(
    sessionFileMatchesState(codexHome, {
      sessionId: SESSION_ID,
      filePath: path.join(codexHome, "sessions", "2026", "different.jsonl"),
    }),
    false,
  );
  assert.equal(
    sessionFileMatchesState(codexHome, {
      sessionId: SESSION_ID,
      filePath: path.join(codexHome, "outside", `rollout-${SESSION_ID}.jsonl`),
    }),
    false,
  );
});
