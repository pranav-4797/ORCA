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
  /**
   * Verdict-card metric tiles built from the backend's structured ocean_state.
   * The answer body is free-form AI prose in the user's own language, so the
   * HUD must not depend on regex-scraping English labels out of it.
   */
  hudMetrics?: { label: string; value: string }[];
  /** Auto-routing explainability (which agents were selected and why). */
  autoRouting?: {
    intent: string;
    agents: string[];
    routing_mode: string;
    reason: string;
  };
  /** Fleet Convergence Forecast — crowding-adjusted recommendation */
  fleetConvergence?: {
    status: string;
    window_hours: number;
    recommendation_changed: boolean;
    change_reason: string;
    candidates: Array<{
      zone_id: string;
      center_lat: number;
      center_lon: number;
      distance_km: number;
      bearing_deg: number;
      base_suitability: number;
      fleet_count: number;
      crowding_ratio: number;
      crowding_penalty: number;
      adjusted_suitability: number;
      crowding_label?: string;
      is_recommended?: boolean;
    }>;
    raw_best_zone?: any;
    final_zone?: any;
  };
  /** Satellite–Model Wind Divergence Flag — forecast vs satellite wind comparison */
  windDivergence?: {
    status: string; // MATCH | MODERATE_DIVERGENCE | HIGH_DIVERGENCE | UNAVAILABLE | STALE
    forecast_wind_kn: number;
    satellite_wind_kn?: number | null;
    diff_kn?: number | null;
    warning: string;
    satellite_status: string; // REAL | SIMULATED | UNAVAILABLE
    is_simulated: boolean;
  };
}
