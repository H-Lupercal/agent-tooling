export interface ResumePlan {
  executable: "codex";
  args: ["resume", string];
  cwd: string;
}

const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

export function isValidSessionId(sessionId: string): boolean {
  return SESSION_ID.test(sessionId);
}

export function createResumePlan(sessionId: string, cwd: string): ResumePlan {
  if (!isValidSessionId(sessionId)) {
    throw new Error("Invalid Codex session ID");
  }
  return {
    executable: "codex",
    args: ["resume", sessionId],
    cwd,
  };
}

export function resolveResumeViewColumn(
  transcriptViewColumn: number | undefined,
  activeViewColumn: number,
): number {
  return transcriptViewColumn ?? activeViewColumn;
}
