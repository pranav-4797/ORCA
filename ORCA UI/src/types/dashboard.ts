/**
 * Smart Dashboard types — mirror the /dashboard JSON shape exactly so the
 * UI can pass them straight to the renderer.
 *
 * Backend source: ORCA_Backend/agents/dashboard_agent.py + /dashboard
 * endpoint in main.py. The endpoint never invents a figure: a card is
 * omitted (not emitted with a placeholder) when the underlying field is
 * not live.
 */

export type DashboardCardType =
  | 'pfz'
  | 'sst'
  | 'wind'
  | 'current'
  | 'tide'
  | 'hazard';

export interface DashboardCardWhy {
  key: string;
  value: string;
}

export interface DashboardCard {
  type: DashboardCardType;
  /** Primary display value (number or string) — already rounded. */
  value: number | string | null;
  unit?: string;
  bearing_deg?: number;
  bearing_compass?: string;
  center?: [number, number] | null;
  /** PFZ: distance from current point. */
  landmark?: string | null;
  source?: string;
  /** Map action to take when the card is tapped. */
  action: string;
  /** List of fact snippets shown under the card. */
  why: DashboardCardWhy[];
  /** PFZ: headline advisory headline (e.g. "Very good chance (PFZ)"). */
  headline?: string;
  flags?: Array<{ label: string; detail: string }>;
  cap_count?: number;
  /** Tide: timeline of high/low events. */
  timeline?: Array<{ kind: string; time_local: string; height_m?: number | null }>;
  /** Ranking components, exposed for the (optional) dev "why is this first" UI. */
  score?: number;
  score_parts?: { history: number; location: number; time: number; hazard: number };
  /** Pinned to the top because Hazard is unsafe. */
  pinned?: boolean;
}

export interface DashboardReadinessFactor {
  factor: string;
  contribution: number;
  max: number;
  quality: number;
  detail: string;
}

export interface DashboardReadiness {
  score: number | null;
  score_exact: number | null;
  factors: DashboardReadinessFactor[];
  excluded: Array<{ factor: string; reason: string }>;
  available: boolean;
}

export interface DashboardQuickAction {
  id: DashboardCardType;
  label: string;
  icon: string;
  query: string;
}

export interface DashboardLocation {
  name: string;
  lat: number;
  lon: number;
}

export interface DashboardSnapshot {
  location: DashboardLocation;
  language: string;
  time_window: string;
  vessel_class: string;
  cards: DashboardCard[];
  omitted_cards: DashboardCardType[];
  readiness: DashboardReadiness;
  hazard_override: boolean;
  briefing: { briefing: string; why_top_card: string; readiness_note: string } | null;
  quick_actions: DashboardQuickAction[];
  generated_at: string;
  cached: boolean;
  /** Last card tapped (echoed back from /dashboard/card-tap). */
  last_tap?: DashboardCardType;
}

export interface DashboardRequest {
  user_key?: string;
  lat?: number;
  lon?: number;
  location_name?: string;
  language?: string;
  time_window?: string;
  vessel_class?: string;
  skip_briefing?: boolean;
}
