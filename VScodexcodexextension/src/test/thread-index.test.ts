import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { loadThreadTitles } from "../thread-index";

test("thread index loads Codex-generated titles and skips malformed entries", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-index-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  await writeFile(
    path.join(root, "session_index.jsonl"),
    [
      JSON.stringify({ id: "session-one", thread_name: "Generated title", updated_at: "2026-08-03" }),
      "{not-json}",
      JSON.stringify({ id: "session-two", thread_name: "  ", updated_at: "2026-08-03" }),
      JSON.stringify({ id: "session-three", updated_at: "2026-08-03" }),
    ].join("\n"),
    "utf8",
  );

  const titles = await loadThreadTitles(root);

  assert.deepEqual([...titles], [["session-one", "Generated title"]]);
});

test("thread index returns no titles when the index does not exist", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-index-"));
  context.after(async () => rm(root, { force: true, recursive: true }));

  assert.deepEqual([...await loadThreadTitles(root)], []);
});
