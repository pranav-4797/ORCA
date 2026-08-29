export type UserCategoryKey =
  | 'fisherman'
  | 'trawler'
  | 'coastal_guard'
  | 'port_operator'
  | 'marine_scientist';

export type VesselClassKey =
  | 'small_fishing_boat'
  | 'mechanized_trawler'
  | 'coastal_cargo';

export interface UserCategoryConfig {
  key: UserCategoryKey;
  name: string;
  shortName: string;
  tagline: string;
  icon: string;
  vesselClass: VesselClassKey;
  vesselLabel: string;
  description: string;
  focusBadges: string[];
  systemContextPrompt: string;
}

export interface UserCategoryProfile {
  category: UserCategoryKey;
  roleName: string;
  vesselClass: VesselClassKey;
  badgeEmoji: string;
  tagline: string;
  updatedAt: number;
}

export const USER_CATEGORIES: UserCategoryConfig[] = [
  {
    key: 'fisherman',
    name: 'Traditional Coastal Fisherman',
    shortName: 'Fisherman',
    tagline: 'Artisanal & Nearshore Craft Operations',
    icon: '🎣',
    vesselClass: 'small_fishing_boat',
    vesselLabel: 'Small Fishing Boat (< 2.5m wave floor)',
    description: 'Calibrated for small craft safety floors (waves < 2.5m, wind gusts < 45 km/h), live INCOIS PFZ thermal lines, landing centers, and tide charts.',
    focusBadges: ['INCOIS PFZ Advisories', 'Small Craft Safety Floor', 'Tide Gauges', 'Local Weather Alerts'],
    systemContextPrompt: 'User is a Traditional Coastal Fisherman operating a small fishing boat. Prioritize nearest INCOIS PFZ coordinates, landing centre bearing & distance, wave height safety (<2.5m), and local vernacular clarity.',
  },
  {
    key: 'trawler',
    name: 'Mechanized Trawler Fisher',
    shortName: 'Trawler Operator',
    tagline: 'Deep-Sea Commercial Fishing & Longlining',
    icon: '⛴️',
    vesselClass: 'mechanized_trawler',
    vesselLabel: 'Mechanized Trawler (Higher seaworthiness)',
    description: 'Offshore thermal fronts, fleet convergence crowding forecasts, multi-day fuel & weather route optimization, and bathymetry.',
    focusBadges: ['Fleet Crowding Forecast', 'Offshore PFZ', 'Bathymetry Clearance', 'Long-Range Routing'],
    systemContextPrompt: 'User operates a Mechanized Trawler for multi-day deep-sea fishing. Highlight fleet convergence crowding ratio, offshore PFZ coordinates, bathymetric depths, and fuel-optimal routing.',
  },
  {
    key: 'coastal_guard',
    name: 'Coast Guard & Maritime Police',
    shortName: 'Coast Guard',
    tagline: 'Border Patrol, Search & Rescue (SAR) & Coastal Enforcement',
    icon: '🛡️',
    vesselClass: 'coastal_cargo',
    vesselLabel: 'Patrol & Enforcement Vessel',
    description: 'High-priority monitoring for IMBL/Sir Creek border intrusions, Search and Rescue (SAR) drift tracking, distress broadcasts, and security geofences.',
    focusBadges: ['IMBL / Border Geofence', 'SAR Search & Rescue', 'Drift Forecasting', 'Security Bulletins'],
    systemContextPrompt: 'User is an Indian Coast Guard / Maritime Security Officer. Prioritize territorial border geofences (IMBL, Sir Creek, restricted zones), SAR drift predictions, distress tracking, and maritime patrol safety.',
  },
  {
    key: 'port_operator',
    name: 'Port & Commercial Vessel Operator',
    shortName: 'Port Authority / Fleet',
    tagline: 'Harbor Traffic, Navigational Channels & Cargo Logistics',
    icon: '🚢',
    vesselClass: 'coastal_cargo',
    vesselLabel: 'Commercial Cargo & Coastal Vessel',
    description: 'Navigational channel clearances, port approaches, gale & cyclone storm-surge alerts, and commercial weather routing.',
    focusBadges: ['Navigational Channels', 'Gale & Surge Alerts', 'Draft & Bathymetry', 'Port Approaches'],
    systemContextPrompt: 'User is a Port Authority or Commercial Vessel Master. Emphasize navigational channel clearances, gale/cyclone surge warnings, wind divergence, and safe deep-draft passage.',
  },
  {
    key: 'marine_scientist',
    name: 'Marine Researcher & Oceanographer',
    shortName: 'Ocean Researcher',
    tagline: 'Oceanographic Dynamics & Satellite Telemetry Analysis',
    icon: '🔬',
    vesselClass: 'small_fishing_boat',
    vesselLabel: 'Scientific Research Platform',
    description: 'Detailed multi-month SST & chlorophyll trend correlation, satellite wind divergence analysis, NOAA/ERDDAP data provenance, and harmonic tide constituents.',
    focusBadges: ['SST & Chlorophyll Trends', 'Satellite Wind Divergence', 'Harmonic Tides', 'ERDDAP Provenance'],
    systemContextPrompt: 'User is a Marine Scientist and Oceanographer. Provide quantitative scientific data, SST-chlorophyll Pearson correlation (r), satellite wind divergence telemetry, and multi-source provenance tiers.',
  },
];
