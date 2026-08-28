import { Chat } from '../types/chat';
import { Message } from '../types/message';

export const INITIAL_CHATS: Chat[] = [
  {
    id: 'chat-sail-safety',
    title: 'Sailing Safety Advisory - Mumbai Coast',
    createdAt: Date.now() - 1000 * 60 * 60 * 2,
    updatedAt: Date.now() - 1000 * 60 * 15,
    agentId: 'orca-nav',
    model: 'ORCA-Nav-v3',
    pinned: true,
    project: 'Western Sector',
    tags: ['Safety', 'Swell', 'Mumbai'],
    messageCount: 2,
    lastMessagePreview: 'ALL CLEAR: Significant Wave Height (SWH) forecast at 1.1m with 12 knots WNW breeze...'
  },
  {
    id: 'chat-pfz-veraval',
    title: 'PFZ Advisory - Gujarat Sector',
    createdAt: Date.now() - 1000 * 60 * 60 * 24,
    updatedAt: Date.now() - 1000 * 60 * 60 * 4,
    agentId: 'orca-pfz',
    model: 'PFZ-Sentinel-v4',
    pinned: true,
    project: 'Fisheries Ops',
    tags: ['PFZ', 'SST', 'Veraval'],
    messageCount: 2,
    lastMessagePreview: 'High chlorophyll concentration at 20°48\'N, 69°42\'E, distance 22.4 NM bearing 215°...'
  },
  {
    id: 'chat-cyclone-track',
    title: 'Arabian Sea Cyclogenesis Assessment',
    createdAt: Date.now() - 1000 * 60 * 60 * 48,
    updatedAt: Date.now() - 1000 * 60 * 60 * 18,
    agentId: 'orca-weather',
    model: 'INCOIS-Ocean-v2',
    pinned: false,
    project: 'Synoptic Weather',
    tags: ['Cyclone', 'IMD', 'Synoptic'],
    messageCount: 2,
    lastMessagePreview: 'No active cyclonic circulation. Low-pressure trough situated 450 NM southwest of Lakshadweep...'
  }
];

export const INITIAL_MESSAGES: Record<string, Message[]> = {
  'chat-sail-safety': [
    {
      id: 'msg-ss-1',
      chatId: 'chat-sail-safety',
      role: 'user',
      content: 'Is it safe to sail tomorrow morning from Mumbai Port? Please check current synoptic conditions, swell forecasts, and IMD coastal advisories.',
      timestamp: Date.now() - 1000 * 60 * 60 * 2
    },
    {
      id: 'msg-ss-2',
      chatId: 'chat-sail-safety',
      role: 'assistant',
      agentId: 'orca-nav',
      modelUsed: 'ORCA-Nav-v3',
      timestamp: Date.now() - 1000 * 60 * 60 * 2 + 2500,
      activitySteps: [
        { id: 's1', title: 'Ingesting INCOIS wave telemetry & radar scans', description: 'Significant Wave Height & Peak Period analysis', status: 'completed', durationMs: 140, timestamp: Date.now() - 1000 * 60 * 60 * 2 },
        { id: 's2', title: 'Checking IMD coastal weather warning bulletins', description: 'Western Naval Command coastal warning check', status: 'completed', durationMs: 220, timestamp: Date.now() - 1000 * 60 * 60 * 2 + 300 },
        { id: 's3', title: 'Evaluating Mumbai Harbour tidal window & UKC', description: 'Under-keel clearance calculation for Apollo Bunder channel', status: 'completed', durationMs: 190, timestamp: Date.now() - 1000 * 60 * 60 * 2 + 600 }
      ],
      tokens: { promptTokens: 34, completionTokens: 380, totalTokens: 414 },
      content: `### ORCA Navigation & Coastal Safety Assessment

**Sector**: Mumbai Port & Outer Harbour (\`18°55.20'N, 72°50.15'E\`)  
**Assessment Window**: 06:00 IST – 12:00 IST Tomorrow  
**Overall Status**: <span style="color:var(--status-safe);font-weight:700;background:rgba(31,138,92,0.12);padding:2px 8px;border-radius:4px;border:1px solid rgba(31,138,92,0.3);">● SAFE TO SAIL (ALL CLEAR)</span>

---

#### 1. Synoptic Marine Meteorological Conditions

| Parameter | Forecast Value | Navigational Rating |
| :--- | :--- | :--- |
| **Wind Speed & Direction** | \`10 – 13 KTS\` (WNW) | **Favorable** (Beaufort Force 3) |
| **Significant Wave Height (SWH)** | \`0.9m – 1.2m\` | **Safe** (Slight Sea State) |
| **Peak Swell Period ($T_p$)** | \`6.8 sec\` (Southwesterly Swell) | **Normal** |
| **Surface Current Velocity** | \`0.8 KTS\` (Ebb flow towards SW) | **Manageable** |
| **Horizontal Visibility** | \`> 8.0 NM\` (Clear) | **Optimal** |

---

#### 2. Mumbai Harbour Astronomical Tidal Windows

- **High Tide**: \`07:42 IST\` (Height: \`4.12m\` above Chart Datum)
- **Low Tide**: \`13:58 IST\` (Height: \`1.04m\` above Chart Datum)

> [!TIP]
> Departure during the rising flood tide (\`06:00 – 07:30 IST\`) provides optimal draft clearance of $>4.8\\text{m}$ across the Fairway Buoy channel.

#### Navigational Notice:
No squall warnings or navigational hazard notices are currently active for the Mumbai – Alibaug maritime corridor. Standard MARSEC Level 1 precautions apply.`
    }
  ],
  'chat-pfz-veraval': [
    {
      id: 'msg-pfz-1',
      chatId: 'chat-pfz-veraval',
      role: 'user',
      content: 'What is the nearest Potential Fishing Zone (PFZ) near Porbandar/Veraval sector? Include bearing, distance in nautical miles, depth, and target species forecast.',
      timestamp: Date.now() - 1000 * 60 * 60 * 24
    },
    {
      id: 'msg-pfz-2',
      chatId: 'chat-pfz-veraval',
      role: 'assistant',
      agentId: 'orca-pfz',
      modelUsed: 'PFZ-Sentinel-v4',
      timestamp: Date.now() - 1000 * 60 * 60 * 24 + 3000,
      activitySteps: [
        { id: 'p1', title: 'Processing NOAA/INSAT-3D Sea Surface Temperature (SST)', description: 'Thermal front boundary extraction', status: 'completed', durationMs: 210, timestamp: Date.now() - 1000 * 60 * 60 * 24 },
        { id: 'p2', title: 'Overlaying OCM-3 Ocean Color Chlorophyll-a Fronts', description: 'Chlorophyll gradient density >= 0.8 mg/m³', status: 'completed', durationMs: 340, timestamp: Date.now() - 1000 * 60 * 60 * 24 + 400 },
        { id: 'p3', title: 'Verifying Indian Exclusive Economic Zone (EEZ) perimeter', description: 'Ensuring coordinates are within legal national fishing waters', status: 'completed', durationMs: 180, timestamp: Date.now() - 1000 * 60 * 60 * 24 + 900 }
      ],
      tokens: { promptTokens: 38, completionTokens: 420, totalTokens: 458 },
      content: `### ORCA Potential Fishing Zone (PFZ) Advisory

**Base Harbour**: Veraval Fishery Port (\`20°54'N, 70°22'E\`)  
**Advisory Validity**: Today – 48 Hours  
**Satellite Sensor**: INSAT-3DR SST + Oceansat-3 OCM Chlorophyll-a

---

#### Recommended High-Yield Fishing Coordinates

| Zone ID | Target Coordinates | Bearing & Distance | Water Depth | Expected Catch |
| :--- | :--- | :--- | :--- | :--- |
| **PFZ-V1 (Prime)** | \`20°48.12'N, 69°42.30'E\` | **\`218°\`** (SW) • **\`22.4 NM\`** | \`42 – 55m\` | Ribbonfish, Mackerel, Pomfret |
| **PFZ-V2 (Secondary)** | \`20°35.50'N, 69°58.10'E\` | **\`194°\`** (SSW) • **\`28.6 NM\`** | \`60 – 72m\` | Tuna (Yellowfin), Carangids |

---

#### Oceanographic Signature:
- **Sea Surface Temperature (SST)**: \`27.8°C\` (Sharp thermal gradient of $\\Delta T = 0.9^{\\circ}\\text{C}$ along western eddy boundary)
- **Chlorophyll-a Concentration**: \`0.94 mg/m³\` (High phytoplankton density)

> [!IMPORTANT]
> Both target zones are strictly within the Indian Exclusive Economic Zone (EEZ) and are $>14\\text{ NM}$ clear of the International Maritime Boundary Line (IMBL). Return transit recommended before 18:00 IST to avoid evening sea breezes.`
    }
  ],
  'chat-cyclone-track': [
    {
      id: 'msg-cy-1',
      chatId: 'chat-cyclone-track',
      role: 'user',
      content: 'Are there any active cyclone alerts, deep depressions, or heavy squall warnings in the Arabian Sea or Bay of Bengal today?',
      timestamp: Date.now() - 1000 * 60 * 60 * 48
    },
    {
      id: 'msg-cy-2',
      chatId: 'chat-cyclone-track',
      role: 'assistant',
      agentId: 'orca-weather',
      modelUsed: 'INCOIS-Ocean-v2',
      timestamp: Date.now() - 1000 * 60 * 60 * 48 + 2800,
      activitySteps: [
        { id: 'c1', title: 'Ingesting IMD Regional Specialized Meteorological Centre (RSMC) bulletin', description: 'Checking North Indian Ocean tropical cyclogenesis monitors', status: 'completed', durationMs: 230, timestamp: Date.now() - 1000 * 60 * 60 * 48 },
        { id: 'c2', title: 'Running ECMWF & GFS ensemble cyclone track simulation', description: 'Vorticity and vertical wind shear analysis', status: 'completed', durationMs: 310, timestamp: Date.now() - 1000 * 60 * 60 * 48 + 400 }
      ],
      tokens: { promptTokens: 32, completionTokens: 340, totalTokens: 372 },
      content: `### ORCA Synoptic Weather & Cyclonic Threat Bulletin

**Issuing Agency**: ORCA Marine Intelligence (in sync with IMD & INCOIS)  
**Oceanic Basins**: Arabian Sea & Bay of Bengal (North Indian Ocean)  
**Threat Status**: <span style="color:var(--status-safe);font-weight:700;background:rgba(31,138,92,0.12);padding:2px 8px;border-radius:4px;border:1px solid rgba(31,138,92,0.3);">● NORMAL (NO ACTIVE CYCLONES)</span>

---

#### Synoptic Summary:
1. **Arabian Sea**:
   - No active cyclonic storms, deep depressions, or low-pressure areas.
   - General wind speed: \`10 – 15 KTS\`. Sea condition: Slight to Moderate.

2. **Bay of Bengal**:
   - A feeble trough of low pressure extends over Southeast Bay of Bengal with minimal convective organization.
   - Vertical wind shear remains high ($>25\\text{ KTS}$), preventing any near-term cyclogenesis.

> [!NOTE]
> All commercial shipping lanes and coastal fisheries sectors are cleared for normal maritime operations. Next synoptic bulletin scheduled at \`06:00 UTC\`.`
    }
  ]
};
