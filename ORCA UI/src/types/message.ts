export type MessageRole = 'user' | 'assistant' | 'system';

export interface Attachment {
  id: string;
  name: string;
  size: number;
  type: string; // 'image/png' | 'application/pdf' | 'text/plain' | etc.
  url?: string;
  previewUrl?: string;
}

export interface MessageReaction {
  type: 'like' | 'dislike' | null;
  feedbackText?: string;
}

export interface Message {
  id: string;
  chatId: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  agentId?: string;
  modelUsed?: string;
  attachments?: Attachment[];
  reactions?: MessageReaction;
  isStreaming?: boolean;
  isEdited?: boolean;
  editHistory?: { content: string; timestamp: number }[];
  activitySteps?: import('./agent').AgentActivityStep[];
  tokens?: {
    promptTokens?: number;
    completionTokens?: number;
    totalTokens?: number;
  };
  /** Structured safety verdict from backend (authoritative). Takes priority over text parsing. */
  status?: 'SAFE' | 'CAUTION' | 'UNSAFE' | 'CRITICAL' | 'INFO';
  /** Auto-routing explainability (which agents were selected and why). */
  autoRouting?: {
    intent: string;
    agents: string[];
    routing_mode: string;
    reason: string;
  };
}
