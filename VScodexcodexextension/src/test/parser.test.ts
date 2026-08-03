import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { parseSessionFile } from "../parser";

test("parser extracts metadata and primary event messages without duplicates", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const filePath = path.join(root, "session.jsonl");
  const records = [
    {
      timestamp: "2026-08-02T10:00:00Z",
      type: "session_meta",
      payload: {
        id: "019fc513-7044-7281-979d-6660f0ee8acd",
        cwd: "/work/project",
        timestamp: "2026-08-02T10:00:00Z",
      },
    },
    {
      timestamp: "2026-08-02T10:00:01Z",
      type: "response_item",
      payload: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: "Explain this project" }],
      },
    },
    {
      timestamp: "2026-08-02T10:00:01Z",
      type: "event_msg",
      payload: { type: "user_message", message: "Explain this project" },
    },
    {
      timestamp: "2026-08-02T10:00:02Z",
      type: "response_item",
      payload: {
        type: "message",
        role: "assistant",
        content: [{ type: "output_text", text: "Here is the overview." }],
      },
    },
    {
      timestamp: "2026-08-02T10:00:02Z",
      type: "event_msg",
      payload: { type: "agent_message", message: "Here is the overview." },
    },
    { type: "response_item", payload: { type: "reasoning", encrypted_content: "hidden" } },
    { type: "response_item", payload: { type: "custom_tool_call", input: "hidden" } },
  ];
  await writeFile(
    filePath,
    `${records.map((record) => JSON.stringify(record)).join("\n")}\n{not-json}\n`,
    "utf8",
  );

  const parsed = await parseSessionFile(filePath);

  assert.equal(parsed.sessionId, "019fc513-7044-7281-979d-6660f0ee8acd");
  assert.equal(parsed.cwd, "/work/project");
  assert.equal(parsed.createdAt, "2026-08-02T10:00:00Z");
  assert.equal(parsed.title, "Explain this project");
  assert.deepEqual(
    parsed.messages.map(({ role, text }) => ({ role, text })),
    [
      { role: "user", text: "Explain this project" },
      { role: "assistant", text: "Here is the overview." },
    ],
  );
  assert.equal(parsed.skippedRecords, 1);
});

test("parser falls back to response-item messages for older sessions", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const filePath = path.join(root, "rollout-019fc513-7044-7281-979d-6660f0ee8acd.jsonl");
  await writeFile(
    filePath,
    [
      JSON.stringify({
        type: "response_item",
        timestamp: "2025-01-01T00:00:00Z",
        payload: { type: "message", role: "user", content: "Older question" },
      }),
      JSON.stringify({
        type: "response_item",
        timestamp: "2025-01-01T00:00:01Z",
        payload: { type: "message", role: "assistant", content: "Older answer" },
      }),
    ].join("\n"),
    "utf8",
  );

  const parsed = await parseSessionFile(filePath);

  assert.equal(parsed.sessionId, "019fc513-7044-7281-979d-6660f0ee8acd");
  assert.deepEqual(parsed.messages.map((message) => message.text), ["Older question", "Older answer"]);
});

test("parser truncates and normalizes long titles", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const filePath = path.join(root, "session.jsonl");
  const longMessage = `  ${"word ".repeat(25)}  `;
  await writeFile(
    filePath,
    JSON.stringify({
      type: "event_msg",
      payload: { type: "user_message", message: longMessage },
    }),
    "utf8",
  );

  const parsed = await parseSessionFile(filePath);

  assert.equal(parsed.title.length, 80);
  assert.match(parsed.title, /…$/u);
});

test("parser prefers Codex's generated thread title", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const sessionId = "019fc513-7044-7281-979d-6660f0ee8acd";
  const filePath = path.join(root, `rollout-${sessionId}.jsonl`);
  await writeFile(
    filePath,
    JSON.stringify({
      type: "event_msg",
      payload: { type: "user_message", message: "A long and awkward first prompt" },
    }),
    "utf8",
  );

  const parsed = await parseSessionFile(
    filePath,
    new Map([[sessionId, "Generated Codex title"]]),
  );

  assert.equal(parsed.title, "Generated Codex title");
});

test("parser keeps the parent identity when nested session metadata follows", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const parentId = "019fc513-7044-7281-979d-6660f0ee8acd";
  const childId = "119fc513-7044-7281-979d-6660f0ee8acd";
  const filePath = path.join(root, `rollout-${parentId}.jsonl`);
  const records = [
    {
      type: "session_meta",
      payload: {
        id: parentId,
        cwd: "/work/parent",
        timestamp: "2026-08-01T10:00:00Z",
        source: "vscode",
      },
    },
    {
      type: "session_meta",
      payload: {
        id: childId,
        cwd: "/work/child",
        timestamp: "2026-08-02T10:00:00Z",
        source: { subagent: {} },
      },
    },
  ];
  await writeFile(
    filePath,
    records.map((record) => JSON.stringify(record)).join("\n"),
    "utf8",
  );

  const parsed = await parseSessionFile(
    filePath,
    new Map([
      [parentId, "Parent title"],
      [childId, "Child title"],
    ]),
  );

  assert.equal(parsed.sessionId, parentId);
  assert.equal(parsed.cwd, "/work/parent");
  assert.equal(parsed.createdAt, "2026-08-01T10:00:00Z");
  assert.equal(parsed.title, "Parent title");
});

test("parser uses the latest user prompt time as the updated time", async (context) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codex-history-parser-"));
  context.after(async () => rm(root, { force: true, recursive: true }));
  const filePath = path.join(root, "session.jsonl");
  const records = [
    {
      timestamp: "2026-08-01T10:00:00Z",
      type: "event_msg",
      payload: { type: "user_message", message: "First prompt" },
    },
    {
      timestamp: "2026-08-03T12:34:56Z",
      type: "event_msg",
      payload: { type: "user_message", message: "Latest prompt" },
    },
    {
      timestamp: "2026-08-03T13:00:00Z",
      type: "event_msg",
      payload: { type: "agent_message", message: "Later assistant response" },
    },
  ];
  await writeFile(
    filePath,
    records.map((record) => JSON.stringify(record)).join("\n"),
    "utf8",
  );

  const parsed = await parseSessionFile(filePath);

  assert.equal(parsed.updatedAtMs, Date.parse("2026-08-03T12:34:56Z"));
});
