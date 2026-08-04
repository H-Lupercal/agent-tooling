import path from "node:path";

import { isValidSessionId } from "./resume";

export interface TranscriptState {
  sessionId: string;
  filePath: string;
}

export function parseTranscriptState(value: unknown): TranscriptState | undefined {
  if (typeof value !== "object" || value === null || !("sessionId" in value) || !("filePath" in value)) {
    return undefined;
  }
  const { sessionId, filePath } = value;
  if (
    typeof sessionId !== "string" ||
    !isValidSessionId(sessionId) ||
    typeof filePath !== "string" ||
    !path.isAbsolute(filePath)
  ) {
    return undefined;
  }
  return { sessionId, filePath };
}

export function sessionFileMatchesState(codexHome: string, state: TranscriptState): boolean {
  const sessionsRoot = path.resolve(codexHome, "sessions");
  const filePath = path.resolve(state.filePath);
  const relative = path.relative(sessionsRoot, filePath);
  const isWithinSessions =
    relative !== "" &&
    !path.isAbsolute(relative) &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`);
  return (
    isWithinSessions &&
    path.extname(filePath).toLowerCase() === ".jsonl" &&
    path.basename(filePath).toLowerCase().includes(state.sessionId.toLowerCase())
  );
}
