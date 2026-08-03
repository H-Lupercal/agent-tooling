import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";

import type { ParsedSession, SessionSummary, TranscriptMessage } from "./model";

type JsonObject = Record<string, unknown>;

const SESSION_ID_IN_NAME = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/iu;

export async function parseSessionFile(
  filePath: string,
  threadTitles: ReadonlyMap<string, string> = new Map(),
): Promise<ParsedSession> {
  const primaryMessages: TranscriptMessage[] = [];
  const fallbackMessages: TranscriptMessage[] = [];
  let sessionId: string | undefined;
  let cwd: string | undefined;
  let createdAt: string | undefined;
  let skippedRecords = 0;

  const lines = readline.createInterface({
    input: createReadStream(filePath, { encoding: "utf8" }),
    crlfDelay: Number.POSITIVE_INFINITY,
  });

  for await (const line of lines) {
    if (!line.trim()) {
      continue;
    }
    let record: unknown;
    try {
      record = JSON.parse(line) as unknown;
    } catch {
      skippedRecords += 1;
      continue;
    }
    if (!isObject(record) || typeof record.type !== "string") {
      skippedRecords += 1;
      continue;
    }

    const payload = isObject(record.payload) ? record.payload : undefined;
    const timestamp = stringValue(record.timestamp);
    if (record.type === "session_meta" && payload) {
      sessionId ??= stringValue(payload.id) ?? stringValue(payload.session_id);
      cwd ??= stringValue(payload.cwd);
      createdAt ??= stringValue(payload.timestamp) ?? timestamp;
      continue;
    }
    if (record.type === "event_msg" && payload) {
      const eventMessage = extractEventMessage(payload, timestamp);
      if (eventMessage) {
        primaryMessages.push(eventMessage);
      }
      continue;
    }
    if (record.type === "response_item" && payload) {
      const responseMessage = extractResponseMessage(payload, timestamp);
      if (responseMessage) {
        fallbackMessages.push(responseMessage);
      }
      continue;
    }
    if (record.type !== "world_state" && record.type !== "turn_context") {
      skippedRecords += 1;
    }
  }

  const details = await stat(filePath);
  const messages = primaryMessages.length > 0 ? primaryMessages : fallbackMessages;
  const firstUserMessage = messages.find((message) => message.role === "user")?.text;
  const fileNameId = path.basename(filePath).match(SESSION_ID_IN_NAME)?.[0];
  const resolvedId = fileNameId ?? sessionId ?? path.basename(filePath, path.extname(filePath));

  return {
    filePath,
    sessionId: resolvedId,
    ...(cwd ? { cwd } : {}),
    title: threadTitles.get(resolvedId) ?? createTitle(firstUserMessage),
    ...(createdAt ? { createdAt } : {}),
    updatedAtMs: latestUserPromptAtMs(messages) ?? details.mtimeMs,
    skippedRecords,
    messages,
  };
}

export async function loadSessionSummaries(
  filePaths: readonly string[],
  concurrency = 8,
  threadTitles: ReadonlyMap<string, string> = new Map(),
): Promise<SessionSummary[]> {
  const results: Array<SessionSummary | undefined> = Array.from(
    { length: filePaths.length },
    () => undefined,
  );
  let nextIndex = 0;
  const workerCount = Math.max(1, Math.min(concurrency, filePaths.length));

  async function worker(): Promise<void> {
    while (nextIndex < filePaths.length) {
      const index = nextIndex;
      nextIndex += 1;
      const filePath = filePaths[index];
      if (!filePath) {
        continue;
      }
      try {
        const parsed = await parseSessionFile(filePath, threadTitles);
        results[index] = {
          filePath: parsed.filePath,
          sessionId: parsed.sessionId,
          ...(parsed.cwd ? { cwd: parsed.cwd } : {}),
          title: parsed.title,
          ...(parsed.createdAt ? { createdAt: parsed.createdAt } : {}),
          updatedAtMs: parsed.updatedAtMs,
          skippedRecords: parsed.skippedRecords,
        };
      } catch {
        results[index] = undefined;
      }
    }
  }

  await Promise.all(Array.from({ length: workerCount }, worker));
  return results.filter((summary): summary is SessionSummary => summary !== undefined);
}

function extractEventMessage(payload: JsonObject, timestamp: string | undefined): TranscriptMessage | undefined {
  const eventType = stringValue(payload.type);
  const role = eventType === "user_message" ? "user" : eventType === "agent_message" ? "assistant" : undefined;
  const text = extractText(payload.message);
  if (!role || !text) {
    return undefined;
  }
  return { role, text, ...(timestamp ? { timestamp } : {}) };
}

function extractResponseMessage(
  payload: JsonObject,
  timestamp: string | undefined,
): TranscriptMessage | undefined {
  if (payload.type !== "message" || (payload.role !== "user" && payload.role !== "assistant")) {
    return undefined;
  }
  const text = extractText(payload.content);
  if (!text) {
    return undefined;
  }
  return { role: payload.role, text, ...(timestamp ? { timestamp } : {}) };
}

function extractText(value: unknown): string | undefined {
  if (typeof value === "string") {
    return value.trim() || undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }
  const parts = value.flatMap((part) => {
    if (!isObject(part) || typeof part.text !== "string") {
      return [];
    }
    return [part.text];
  });
  const text = parts.join("\n").trim();
  return text || undefined;
}

function createTitle(message: string | undefined): string {
  if (!message) {
    return "Untitled conversation";
  }
  const normalized = message.replace(/\s+/gu, " ").trim();
  return normalized.length <= 80 ? normalized : `${normalized.slice(0, 79)}…`;
}

function latestUserPromptAtMs(messages: readonly TranscriptMessage[]): number | undefined {
  let latest: number | undefined;
  for (const message of messages) {
    if (message.role !== "user" || !message.timestamp) {
      continue;
    }
    const timestamp = Date.parse(message.timestamp);
    if (Number.isFinite(timestamp) && (latest === undefined || timestamp > latest)) {
      latest = timestamp;
    }
  }
  return latest;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
