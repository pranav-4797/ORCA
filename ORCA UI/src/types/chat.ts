import { Message } from './message';

export interface Chat {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  agentId: string;
  model: string;
  pinned?: boolean;
  project?: string;
  tags?: string[];
  messageCount: number;
  lastMessagePreview?: string;
  isArchived?: boolean;
}

export interface ChatFolder {
  id: string;
  name: string;
  icon?: string;
  color?: string;
}

export type ThemeMode = 'dark' | 'light' | 'system';

export interface AppSettings {
  theme: ThemeMode;
  sidebarCollapsed: boolean;
  agentPanelOpen: boolean;
  soundEnabled: boolean;
  sendOnEnter: boolean;
  streamSpeed: 'fast' | 'normal' | 'cinematic';
  defaultModel: string;
  codeTheme: 'dark' | 'light';
  fontSize: 'small' | 'medium' | 'large';
}
