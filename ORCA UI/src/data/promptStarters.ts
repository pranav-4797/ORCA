export interface PromptStarter {
  id: string;
  category: string;
  title: string;
  description: string;
  icon: string;
  prompt: string;
  agentId: string;
}

export const PROMPT_STARTERS: PromptStarter[] = [
  {
    id: 'starter-safety',
    category: 'Operational Safety',
    title: 'Is it safe to sail tomorrow morning?',
    description: 'Inspect significant wave height, wind gusts, squall advisories, and harbor clearance',
    icon: 'shield',
    prompt: 'Is it safe to sail tomorrow morning from Mumbai Port? Please check current synoptic conditions, swell forecasts, and IMD coastal advisories.',
    agentId: 'orca-nav'
  },
  {
    id: 'starter-fishing',
    category: 'PFZ Advisory',
    title: 'Nearest fishing zone near me',
    description: 'Retrieve satellite thermal fronts (SST) and chlorophyll-a fish aggregation zones',
    icon: 'sparkles',
    prompt: 'What is the nearest Potential Fishing Zone (PFZ) near Porbandar/Veraval sector? Include bearing, distance in nautical miles, depth, and target species forecast.',
    agentId: 'orca-pfz'
  },
  {
    id: 'starter-cyclone',
    category: 'Severe Weather',
    title: 'Any cyclone alerts today?',
    description: 'Check active low-pressure depressions, cyclonic storm tracks, and IMD/JTWC bulletins',
    icon: 'zap',
    prompt: 'Are there any active cyclone alerts, deep depressions, or heavy squall warnings in the Arabian Sea or Bay of Bengal today?',
    agentId: 'orca-weather'
  },
  {
    id: 'starter-tides',
    category: 'Oceanography',
    title: 'Tide times for today',
    description: 'Astronomical high & low tide predictions, dynamic UKC windows, and tidal streams',
    icon: 'compass',
    prompt: 'Provide high tide and low tide timings with height above chart datum for Jawaharlal Nehru Port (JNPT) and Mumbai Harbour today.',
    agentId: 'orca-weather'
  }
];
