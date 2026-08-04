import { createReadStream } from "node:fs";
import path from "node:path";
import readline from "node:readline";

type JsonObject = Record<string, unknown>;

export async function loadThreadTitles(codexHome: string): Promise<ReadonlyMap<string, string>> {
  const titles = new Map<string, string>();
  const lines = readline.createInterface({
    input: createReadStream(path.join(codexHome, "session_index.jsonl"), { encoding: "utf8" }),
    crlfDelay: Number.POSITIVE_INFINITY,
  });

  try {
    for await (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      let record: unknown;
      try {
        record = JSON.parse(line) as unknown;
      } catch {
        continue;
      }
      if (!isObject(record)) {
        continue;
      }
      const id = stringValue(record.id);
      const title = stringValue(record.thread_name);
      if (id && title) {
        titles.set(id, title);
      }
    }
  } catch {
    return new Map();
  }

  return titles;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  return value.trim() || undefined;
}
