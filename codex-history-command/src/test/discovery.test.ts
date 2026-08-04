import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { discoverSessionFiles } from "../discovery";

test("discovery recursively returns JSONL sessions newest first", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-discovery-"));
  context.after(async () => rm(root, { force: true, recursive: true }));

  const older = path.join(root, "sessions", "2025", "01", "older.jsonl");
  const newer = path.join(root, "sessions", "2026", "02", "newer.jsonl");
  const ignored = path.join(root, "sessions", "2026", "02", "notes.txt");
  await mkdir(path.dirname(older), { recursive: true });
  await mkdir(path.dirname(newer), { recursive: true });
  await writeFile(older, "{}\n", "utf8");
  await writeFile(newer, "{}\n", "utf8");
  await writeFile(ignored, "ignore me\n", "utf8");
  await utimes(older, new Date(1_000), new Date(1_000));
  await utimes(newer, new Date(2_000), new Date(2_000));

  assert.deepEqual(await discoverSessionFiles(root), [newer, older]);
});

test("discovery returns an empty list when the sessions directory is missing", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-discovery-"));
  context.after(async () => rm(root, { force: true, recursive: true }));

  assert.deepEqual(await discoverSessionFiles(root), []);
});
