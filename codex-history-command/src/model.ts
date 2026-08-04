export interface SessionSummary {
  filePath: string;
  sessionId: string;
  cwd?: string;
  title: string;
  createdAt?: string;
  updatedAtMs: number;
  skippedRecords: number;
}

export interface TranscriptMessage {
  role: "user" | "assistant";
  text: string;
  timestamp?: string;
}

export interface ParsedSession extends SessionSummary {
  messages: TranscriptMessage[];
}
