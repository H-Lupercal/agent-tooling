import assert from "node:assert/strict";
import { test } from "node:test";

import { isSessionInWorkspace, sortSessionSummaries } from "../history";
import type { SessionSummary } from "../model";

function summary(sessionId: string, cwd: string | undefined, updatedAtMs: number): SessionSummary {
  return {
    filePath: `/${sessionId}.jsonl`,
    sessionId,
    ...(cwd ? { cwd } : {}),
    title: sessionId,
    updatedAtMs,
    skippedRecords: 0,
  };
}

test("workspace history accepts exact and nested working directories", () => {
  assert.equal(isSessionInWorkspace(summary("exact", "/work/project", 1), ["/work/project"]), true);
  assert.equal(
    isSessionInWorkspace(summary("nested", "/work/project/packages/tool", 1), ["/work/project"]),
    true,
  );
});

test("workspace history rejects siblings that only share a path prefix", () => {
  assert.equal(
    isSessionInWorkspace(summary("sibling", "/work/project-old", 1), ["/work/project"]),
    false,
  );
  assert.equal(isSessionInWorkspace(summary("missing", undefined, 1), ["/work/project"]), false);
});

test("workspace history supports multiple roots", () => {
  assert.equal(
    isSessionInWorkspace(summary("second", "/other/repository", 1), ["/work/project", "/other"]),
    true,
  );
});

test("workspace history sorts current sessions first and each group newest first", () => {
  const sessions = [
    summary("outside-new", "/elsewhere", 40),
    summary("inside-old", "/work/project", 10),
    summary("outside-old", "/elsewhere", 20),
    summary("inside-new", "/work/project/subdir", 30),
  ];

  assert.deepEqual(
    sortSessionSummaries(sessions, ["/work/project"]).map(({ sessionId }) => sessionId),
    ["inside-new", "inside-old", "outside-new", "outside-old"],
  );
});
