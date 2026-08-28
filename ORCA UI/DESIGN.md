---
name: Maritime Precision
colors:
  surface: '#f6fafd'
  surface-dim: '#d6dbdd'
  surface-bright: '#f6fafd'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f0f4f7'
  surface-container: '#eaeef1'
  surface-container-high: '#e5e9ec'
  surface-container-highest: '#dfe3e6'
  on-surface: '#171c1f'
  on-surface-variant: '#3e494a'
  inverse-surface: '#2c3134'
  inverse-on-surface: '#edf1f4'
  outline: '#6e797a'
  outline-variant: '#bdc9ca'
  surface-tint: '#006972'
  primary: '#00626a'
  on-primary: '#ffffff'
  primary-container: '#0e7c86'
  on-primary-container: '#ddfbff'
  inverse-primary: '#7cd4df'
  secondary: '#516072'
  on-secondary: '#ffffff'
  secondary-container: '#d1e1f7'
  on-secondary-container: '#556477'
  tertiary: '#4a5a68'
  on-tertiary: '#ffffff'
  tertiary-container: '#627281'
  on-tertiary-container: '#eff6ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#98f0fb'
  primary-fixed-dim: '#7cd4df'
  on-primary-fixed: '#001f23'
  on-primary-fixed-variant: '#004f56'
  secondary-fixed: '#d4e4fa'
  secondary-fixed-dim: '#b8c8de'
  on-secondary-fixed: '#0d1d2d'
  on-secondary-fixed-variant: '#39485a'
  tertiary-fixed: '#d4e4f6'
  tertiary-fixed-dim: '#b8c8d9'
  on-tertiary-fixed: '#0d1d2a'
  on-tertiary-fixed-variant: '#394856'
  background: '#f6fafd'
  on-background: '#171c1f'
  surface-variant: '#dfe3e6'
typography:
  display-data:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.08em
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  data-mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
  container-max: 1440px
---

## Brand & Style
The design system is engineered for high-stakes maritime logistics and vessel monitoring. The brand personality is institutional, authoritative, and stoic. It rejects the "hype-cycles" of modern consumer tech (AI-glow, neon gradients, or glassmorphism) in favor of a utilitarian aesthetic that bridges the gap between a modern ship’s electronic chart display (ECDIS) and high-end data journalism.

The visual style is **Corporate / Modern** with a focus on **Precision Minimalism**. It prioritizes readability and information density over decorative flair. The emotional response should be one of "calm in the storm"—providing operators with clear, actionable data that feels as reliable as a physical instrument.

## Colors
The palette is rooted in a "Maritime Cool" spectrum. The background utilizes a near-white grey to reduce eye strain during long shifts, while white surfaces provide clear containment for data modules.

- **Primary (Teal):** Reserved for interactive elements, primary actions, and navigational markers. It provides a distinct contrast against the navy text without the aggression of a standard blue.
- **Text Hierarchy:** Use Deep Navy (#0B1B2B) for high-contrast legibility in headlines and values. Use Slate Grey (#5B6B7A) for metadata and labels.
- **Status Colors:** These follow international maritime safety standards. They are muted enough to not overwhelm the UI but saturated enough to remain legible against both the teal accent and the navy text.

## Typography
The typography system uses a dual-font approach to differentiate between UI controls and technical data.

- **Inter:** The primary typeface for all interface elements. It is chosen for its geometric clarity and exceptional legibility at small sizes.
- **JetBrains Mono:** Dedicated exclusively to coordinates (Lat/Long), timestamps, vessel IDs (MMSI), and sensor readings. The monospaced nature ensures that numbers align perfectly in tables and dashboard grids, mimicking hardware instrument panels.
- **Visual Weight:** Use `display-data` for critical metrics like speed (knots) or ETA. Use `label-caps` for section headers and field descriptors to create a clear structural hierarchy.

## Layout & Spacing
The design system employs a strict **8px linear grid**. All spacing, padding, and margins must be increments of 8.

- **Grid Model:** Use a 12-column fluid grid for desktop with 16px gutters. For data-heavy views, columns may be split into sidebars (3 columns) and main content areas (9 columns).
- **Responsive Behavior:** 
  - **Desktop (1024px+):** Full 12-column visibility with 32px outer margins.
  - **Tablet (768px - 1023px):** 8-column grid, 24px margins. Sidebars collapse into drawers.
  - **Mobile (<768px):** 4-column fluid layout with 16px margins. 
- **Information Density:** Maintain generous whitespace between functional groups, but high density within data cards to allow for maximum information at a glance.

## Elevation & Depth
This system intentionally avoids depth through shadows. Instead, it utilizes **Flat Structural Tiers** and **Low-Contrast Outlines**.

- **Level 0 (Base):** #EDF1F4 (Cool Grey). This is the "ocean" background.
- **Level 1 (Card/Surface):** #FFFFFF (White) with a 1px #D1D5DB border. Used for the primary content containers.
- **Level 2 (In-Card Elements):** Use subtle grey fills (#F8FAFB) for input fields or nested sections within a card to create separation without adding shadows.
- **Focus States:** For interactive elements in focus, use a 2px solid Teal (#0E7C86) ring with a 2px white offset. 
- **Z-Index Strategy:** Only use elevation for global navigation bars or temporary modals, which should use a high-contrast 1px border rather than a shadow.

## Shapes
The shape language is controlled and systematic. It avoids hyper-rounded "bubble" aesthetics, opting for subtle radii that feel modern but structured.

- **Cards:** Fixed at 8px to provide a soft container for data without feeling informal.
- **Buttons:** Reduced to 6px for a more precise, "tool-like" appearance.
- **Form Inputs:** 4px radius to maximize internal space for text alignment.
- **Icons:** All icons must use a consistent 1.5px stroke weight with square caps and joins to match the rigid grid of the typography.

## Components
- **Buttons:** 
  - *Primary:* Solid Teal (#0E7C86) with White text. 
  - *Secondary:* Ghost style with Teal border and Teal text. 
  - *Text:* Use `label-caps` for button labels to emphasize their functional role.
- **Data Cards:** Must always include a 1px #D1D5DB border. Headers within cards should use a light grey background fill (#F8FAFB) to separate the label from the data.
- **Input Fields:** Use 1px #D1D5DB borders. Inactive fields should have a very light grey fill. Focus state changes border to Teal.
- **Status Chips:** Small, rounded (pill-shaped) badges using the Status Colors palette. Use low-opacity fills (10-15%) of the status color with high-contrast text for maximum readability.
- **Lists:** Use 1px horizontal dividers between items. Avoid alternating row colors (zebra striping) to maintain a clean, journalistic look; rely on whitespace and thin lines instead.
- **Additional Elements:** 
  - *Instrument Readouts:* Large numeric values in Inter Bold with the unit (e.g., "KTS") in small JetBrains Mono to the right.
  - *Vessel Markers:* Simple geometric shapes (triangles/circles) in Teal for active vessels and Navy for others.