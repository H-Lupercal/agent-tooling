import assert from "node:assert/strict";
import { test } from "node:test";

import type { ParsedSession } from "../model";
import { renderTranscriptHtml } from "../render";

test("transcript HTML escapes content and uses a nonce-only CSP", () => {
  const session: ParsedSession = {
    filePath: "/tmp/session.jsonl",
    sessionId: "019fc513-7044-7281-979d-6660f0ee8acd",
    cwd: "/work/<private>&\"project\"",
    title: "Unsafe <script>alert(1)</script>",
    createdAt: "2026-08-02T10:00:00Z",
    updatedAtMs: 1,
    skippedRecords: 2,
    messages: [
      { role: "user", text: "Run <script>steal()</script> & report" },
      { role: "assistant", text: "Use `safe` > unsafe" },
    ],
  };

  const html = renderTranscriptHtml(session, "fixed-nonce");

  assert.match(
    html,
    /default-src &#39;none&#39;; style-src &#39;nonce-fixed-nonce&#39;; script-src &#39;nonce-fixed-nonce&#39;/u,
  );
  assert.doesNotMatch(html, /<script>steal\(\)<\/script>/u);
  assert.match(html, /&lt;script&gt;steal\(\)&lt;\/script&gt; &amp; report/u);
  assert.match(html, /\/work\/&lt;private&gt;&amp;&quot;project&quot;/u);
  assert.match(html, /2 unsupported or malformed records were skipped/u);
  assert.equal((html.match(/id="resume"/gu) ?? []).length, 1);
  assert.equal((html.match(/<section class="message/gu) ?? []).length, 2);
});

test("transcript HTML does not invent warnings for a clean session", () => {
  const session: ParsedSession = {
    filePath: "/tmp/session.jsonl",
    sessionId: "019fc513-7044-7281-979d-6660f0ee8acd",
    title: "Clean",
    updatedAtMs: 1,
    skippedRecords: 0,
    messages: [],
  };

  const html = renderTranscriptHtml(session, "nonce");

  assert.doesNotMatch(html, /records were skipped/u);
  assert.match(html, /No user or assistant messages were found/u);
});
