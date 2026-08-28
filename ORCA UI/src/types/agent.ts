export type AgentStatus = 'online' | 'busy' | 'offline' | 'thinking' | 'idle';

export interface AgentCapability {
  id: string;
  name: string;
  description: string;
  icon?: string;
}

export interface Agent {
  id: string;
  name: string;
  shortName: string;
  role: string;
  description: string;
  icon: string;
  avatarBg: string;
  avatarColor: string;
  status: AgentStatus;
  capabilities: string[];
  systemPrompt: string;
  defaultModel: string;
  temperature: number;
  maxTokens: number;
  tags: string[];
  suggestedPrompts: string[];
}

export type ActivityStepStatus = 'pending' | 'in_progress' | 'completed' | 'error';

export interface AgentActivityStep {
  id: string;
  title: string;
  description?: string;
  status: ActivityStepStatus;
  durationMs?: number;
  timestamp: number;
  icon?: string;
}

export interface AgentExecutionState {
  agentId: string;
  state: 'idle' | 'thinking' | 'searching' | 'executing' | 'completed' | 'error';
  currentAction: string;
  steps: AgentActivityStep[];
  startedAt?: number;
  finishedAt?: number;
}
