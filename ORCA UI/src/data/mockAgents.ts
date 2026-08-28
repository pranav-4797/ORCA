import { Agent } from '../types/agent';

export const MOCK_AGENTS: Agent[] = [
  {
    id: 'orca-nav',
    name: 'ORCA Navigation Assistant',
    shortName: 'ORCA',
    role: 'Maritime Domain Awareness & ECDIS Co-Pilot',
    description: 'Expert navigational advisor analyzing bathymetric charts, dynamic under-keel clearance (UKC), tidal windows, and IMO route adherence.',
    icon: 'compass',
    avatarBg: 'rgba(14, 124, 134, 0.14)',
    avatarColor: '#0e7c86',
    status: 'online',
    capabilities: ['TSS Compliance', 'Bathymetry & UKC', 'Chokepoint Routing', 'AIS Telemetry Ingestion'],
    systemPrompt: 'You are ORCA, an authoritative Maritime Intelligence Assistant engineered for ship navigation officers, fleet controllers, and maritime safety operators.',
    defaultModel: 'ORCA-Nav-v3',
    temperature: 0.1,
    maxTokens: 4096,
    tags: ['Navigation', 'ECDIS', 'Passage Planning', 'UKC'],
    suggestedPrompts: [
      'Is it safe to sail tomorrow morning from Mumbai Port?',
      'Check under-keel clearance (UKC) in Phillip Channel for 16.2m draft vessel',
      'Compare Malacca Strait vs Sunda Strait route with bunker consumption models',
      'Assess piracy risk & MARSEC status in Gulf of Aden corridor'
    ]
  },
  {
    id: 'orca-weather',
    name: 'Meteorological & Cyclone Intel',
    shortName: 'Sea Weather',
    role: 'INCOIS / IMD Synoptic Forecast Specialist',
    description: 'Monitors tropical cyclogenesis, significant wave height (SWH), wind gust vectors, ocean current drifts, and squall lines.',
    icon: 'zap',
    avatarBg: 'rgba(217, 119, 6, 0.14)',
    avatarColor: '#D97706',
    status: 'online',
    capabilities: ['Cyclone Tracking', 'Wave Swell Models', 'Tidal Harmonics', 'Beaufort Scale Alerts'],
    systemPrompt: 'You are the ORCA Meteorological & Oceanographic Specialist providing accurate weather routing, sea-state forecasts, and severe storm warnings.',
    defaultModel: 'INCOIS-Ocean-v2',
    temperature: 0.2,
    maxTokens: 4096,
    tags: ['Weather', 'Cyclones', 'Sea State', 'Tides'],
    suggestedPrompts: [
      'Any active cyclone alerts or depressions in Bay of Bengal today?',
      'What are the high tide and low tide timings for Jawaharlal Nehru Port today?',
      'Provide 48-hour sea state forecast for Gujarat coastal corridor',
      'Calculate leeway drift vector for a 12m vessel lost power off Goa'
    ]
  },
  {
    id: 'orca-pfz',
    name: 'Potential Fishing Zone (PFZ)',
    shortName: 'PFZ Advisory',
    role: 'Bio-Oceanographic & Coastal Advisory',
    description: 'Synthesizes Sea Surface Temperature (SST) satellite thermal gradients and Chlorophyll-a frontal zones to identify lucrative fishing grounds.',
    icon: 'sparkles',
    avatarBg: 'rgba(31, 138, 92, 0.14)',
    avatarColor: '#1F8A5C',
    status: 'online',
    capabilities: ['SST Fronts', 'Chlorophyll Maps', 'Fish Aggregation', 'EEZ Boundary Safety'],
    systemPrompt: 'You are the ORCA Potential Fishing Zone (PFZ) advisory system, providing fishermen and commercial trawlers with optimized catch locations.',
    defaultModel: 'PFZ-Sentinel-v4',
    temperature: 0.2,
    maxTokens: 4096,
    tags: ['Fishing', 'SST', 'Chlorophyll', 'Coastal'],
    suggestedPrompts: [
      'Nearest high-yield fishing zone near Porbandar coast',
      'Current Sea Surface Temperature (SST) gradient along Konkan coast',
      'Verify if fishing coordinates are strictly within Indian EEZ limits',
      'Provide multi-day tuna aggregation forecast for Lakshadweep waters'
    ]
  },
  {
    id: 'orca-sar',
    name: 'SAR & Maritime Security',
    shortName: 'Coast Guard & SAR',
    role: 'Search & Rescue and Vessel Safety Coordination',
    description: 'Coordinates IAMSAR search patterns, distress beacon telemetry (EPIRB), vessel collision risk assessments, and border zone alerts.',
    icon: 'shield',
    avatarBg: 'rgba(220, 38, 38, 0.14)',
    avatarColor: '#DC2626',
    status: 'online',
    capabilities: ['IAMSAR Patterns', 'EPIRB Telemetry', 'Collision Avoidance (COLREG)', 'Maritime Safety'],
    systemPrompt: 'You are the ORCA Maritime Search & Rescue (SAR) and Safety Officer, coordinating distress responses, drift calculations, and safety protocols.',
    defaultModel: 'SAR-Coord-v2',
    temperature: 0.1,
    maxTokens: 4096,
    tags: ['SAR', 'Safety', 'Distress', 'IAMSAR'],
    suggestedPrompts: [
      'Generate Expanding Square Search pattern for MOB incident at 18°50\'N, 72°45\'E',
      'Assess COLREG crossing situation with container ship bearing 045° at 16 knots',
      'Decode EPIRB hex telemetry broadcast and pinpoint Doppler location',
      'Check security notice and nav-warnings for western naval command sector'
    ]
  }
];

export const AVAILABLE_MODELS = [
  { id: 'orca-nav-v3', name: 'ORCA Nav Engine v3', provider: 'Maritime AI', badge: 'ECDIS & Route' },
  { id: 'incois-ocean-v2', name: 'INCOIS Ocean v2', provider: 'Govt. Telemetry', badge: 'Weather & Swell' },
  { id: 'pfz-sentinel-v4', name: 'PFZ Sentinel v4', provider: 'Satellite Bio', badge: 'Fishing Zones' },
  { id: 'sar-coord-v2', name: 'SAR Coord Engine', provider: 'Coast Guard', badge: 'Search & Rescue' }
];
