# Frontend Design System: Control Room

An operations ledger meets a flight-strip board. Calm, editorial, and precise. The interface stays quiet and restrained until user action is required, at which point priority tasks become unmistakable.

---

## 1. Design Dials & Aesthetic Principles

- **Design Variance:** `7` (Distinctive, characterful, non-generic)
- **Motion Intensity:** `5` (Functional FLIP transitions, orchestrated entry, 0ms under reduced motion)
- **Visual Density:** `6` (Information-dense tables and queues, generous decision cards)
- **Anti-Slop Directives:**
  - Zero generic purple-to-blue gradients.
  - No default system fonts, Inter, Roboto, or Arial as primary typeface.
  - No decorative-only animations; animate exclusively `transform` and `opacity`.
  - No pure `#000000` or `#FFFFFF`.
  - Hairline 1px borders define structure; subtle box-shadows reserved strictly for overlays.

---

## 2. Design Tokens

All styles are driven strictly by CSS custom properties in `tokens.css`.

### 2.1 Theme Palettes

| Token | Dark (Default) | Light (Ledger Paper) | Description |
| :--- | :--- | :--- | :--- |
| `--bg` | `#0E1013` (Graphite) | `#EFEDE6` (Warm paper) | Root background |
| `--surface` | `#15181C` | `#F7F5EF` | Primary card & panel container |
| `--surface-2`| `#1B1F24` | `#E8E5DC` | Elevated elements & table headers |
| `--line` | `#262B31` | `#D6D2C6` | 1px hairline boundary |
| `--fg` | `#E8E6DF` (Warm bone)| `#14161A` (Charcoal) | High-contrast readable text |
| `--muted` | `#8B9097` | `#5F646B` | Secondary captions, metadata, labels |
| `--accent` | `#7C9CFF` (Cobalt) | `#2B4BFF` (Deep blue) | Focus rings, key actions |

### 2.2 Semantic States

Semantic colors are never used decoratively and are always accompanied by textual or icon indicators:

| State | Hex | Background Tint | Usage |
| :--- | :--- | :--- | :--- |
| **OK / Active** | `#2F9E6B` | `rgba(47, 158, 107, 0.12)` | COMPLETED runs, active status, success toast |
| **Warning / Needs You**| `#D9902F` | `rgba(217, 144, 47, 0.12)` | BLOCKED_USER, review required |
| **Critical / Halted** | `#D8453A` | `rgba(216, 69, 58, 0.14)` | HALTED cycle, kill switch engaged |

### 2.3 Geometry & Radii

- **Scale:**
  - `--r-xs: 2px` (Inputs, status pills, code chips)
  - `--r-sm: 4px` (Buttons, queue action targets)
  - `--r-md: 6px` (Panels, modals, card containers)
  - `--r-none: 0px` (Table rows, outer grid boundaries)
- **Borders:** `1px solid var(--line)`

---

## 3. Typography & Hierarchy

Self-hosted SIL OFL typefaces served locally from `harness/web/fonts/` with `font-display: swap`:

1. **Instrument Serif** (`instrument-serif-400.woff2`):
   - Display & Hero Numerals: `clamp(3rem, 7vw, 6.5rem)`, line-height `1.0`.
2. **Geist Sans** (`geist-400.woff2`, `geist-600.woff2`):
   - Section Titles: `1.25rem` (600 weight).
   - Component Headings: `1.0rem` (600 weight).
   - Body Text: `0.9375rem` (400 weight, line-height `1.5`).
   - Form Inputs: `16px` (prevents browser viewport shifts).
3. **Geist Mono** (`geist-mono-400.woff2`):
   - Numerical Data, Timestamps, IDs, Status Pills: `0.8125rem` with `font-variant-numeric: tabular-nums`.

---

## 4. Layout Architecture: Three-View System

The dashboard organizes operational workflows into three distinct views via client-side routing (`#today`, `#pipeline`, `#library`), accessible via segmented tabs and hotkeys `1`, `2`, `3`.

- **Max Width:** `1440px` centered.
- **Base Grid:** `4px` rhythm, `12-column` asymmetric layout on desktop.
- **Breakpoints:** Single column collapse below `900px`; dedicated mobile layout at `390px` with fixed bottom segmented control and $\ge 44\text{px}$ touch targets.
- **Top Bar (Sticky 56px):**
  - State dot with human-readable operational sentence (e.g. `Idle. Next run in 3h 12m.`).
  - View switcher segmented control (`1 Today`, `2 Pipeline`, `3 Library`).
  - Schedule menu dropdown (Cycle, Jobs, People phase toggles).
  - Quick action: `Run cycle now`.
  - Hold-to-confirm Kill Switch (600ms hold gesture).
  - Utility menu `?` (Theme toggle, shortcuts cheatsheet, command palette `⌘K`).
- **View 1: Today (`#today`):**
  - Hero Strip: Three Instrument Serif numerals (*To Send*, *Applied*, *Needs You*).
  - Send Queue: High-density compact rows ($\le 64\text{px}$ collapsed). Clicking or pressing `Space` expands the inline drawer with full personalized message (`note_text` $\le 300$ chars) and target profile link. Action buttons: `Copy note`, `I sent it` (`S`), `Skipped` (`K`) with 6-second in-page undo toast.
  - Needs You Blockers: Truncated single-line blocker rows expanding on demand.
- **View 2: Pipeline (`#pipeline`):**
  - Single-line conversion ribbon / funnel bar.
  - Sortable and filterable target jobs table with status filters (*To Apply*, *Applied*, *Needs You*).
- **View 3: Library (`#library`):**
  - Clean collapsed accordions displaying counts: Contacts (33), Email drafts (4), Queued messages (8), Application answers (6, click to reveal), Screening QA (20 keys), Gmail drafts snapshot (12), Open items (10), Run history (15), and System provenance.

---

## 5. Motion Specification

- **Total Page Orchestration:** Staggered `40ms` reveals across hero numerals, queue cards, and panels (total entry `< 700ms`).
- **Hero Numerals:** `600ms` ease-out count-up animation on initialization.
- **Queue Collapse (FLIP):** When an item is marked SENT or SKIPPED, smooth First-Last-Invert-Play collapse (`180ms ease-out`) with hero figure tick-down.
- **Micro-Interactions:** Focus and hover transitions strictly `120ms - 180ms`.
- **Allowed Animated Properties:** Exclusively `transform` and `opacity` (zero layout thrashing).
- **Reduced Motion (`prefers-reduced-motion: reduce`):** All transitions collapse to `0ms` instant state changes.

---

## 6. Keyboard Shortcuts & Accessibility

- **Focus Rings:** `2px solid var(--accent)` with `2px` offset on all interactive elements.
- **Minimum Tap Target:** `44px × 44px` on all actionable targets.
- **Screen Reader Support:** `#aria-announcements` live region (`aria-live="polite"`).

| Key | Context | Action |
| :--- | :--- | :--- |
| `1` | Global | Switch to **Today** view |
| `2` | Global | Switch to **Pipeline** view |
| `3` | Global | Switch to **Library** view |
| `Space` | Focused queue row | Expand / collapse message drawer |
| `S` | Focused queue card | Mark **I sent it** (starts 6s undo delay) |
| `K` | Focused queue card | Mark **Skipped** |
| `J` | Queue cards | Focus next queue item |
| `L` | Queue cards | Focus previous queue item |
| `⌘K` / `Ctrl+K`| Global | Open Command Palette |
| `?` | Global | Toggle Keyboard Shortcuts Modal |
| `T` | Global | Toggle Dark / Light Theme |
| `Esc` | Modals / Palette | Close active overlay |

---

## 7. Performance Budgets & Measured Transfer Sizes

| Asset Group | Budget (Gzip) | Actual Raw | Actual Gzip | % of Budget | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HTML Shell** (`index.html`) | $\le 8\text{ KB}$ (8,192 B) | 16,504 B | **4,195 B** | 51.2% | PASS |
| **CSS Total** (5 files) | $\le 24\text{ KB}$ (24,576 B) | 17,884 B | **5,530 B** | 22.5% | PASS |
| **JS Total** (7 modules) | $\le 45\text{ KB}$ (46,080 B) | 57,745 B | **16,248 B** | 35.3% | PASS |
| **Fonts Total** (4 woff2 files) | $\le 140\text{ KB}$ (143,360 B) | **99,588 B** | (Pre-compressed) | 69.5% | PASS |
| **Images** | `favicon.svg` only | 386 B | 235 B | — | PASS |
| **External Requests** | `0` external calls | 0 | 0 | 0% | PASS |

### Individual Asset Breakdown
- `css/tokens.css`: 1,789 B raw (866 B gzip)
- `css/base.css`: 2,561 B raw (941 B gzip)
- `css/layout.css`: 2,202 B raw (808 B gzip)
- `css/components.css`: 9,930 B raw (2,314 B gzip)
- `css/motion.css`: 1,402 B raw (601 B gzip)
- `js/api.js`: 2,160 B raw (913 B gzip)
- `js/store.js`: 3,040 B raw (1,011 B gzip)
- `js/motion.js`: 3,056 B raw (1,100 B gzip)
- `js/render.js`: 29,245 B raw (7,065 B gzip)
- `js/palette.js`: 6,255 B raw (2,006 B gzip)
- `js/keys.js`: 2,651 B raw (885 B gzip)
- `js/main.js`: 11,338 B raw (3,268 B gzip)
- `fonts/geist-400.woff2`: 33,400 B raw
- `fonts/geist-600.woff2`: 35,292 B raw
- `fonts/geist-mono-400.woff2`: 9,864 B raw
- `fonts/instrument-serif-400.woff2`: 21,032 B raw
