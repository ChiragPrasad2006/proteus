# Proteus Frontend

Vite + React + TypeScript + Tailwind v4.

## Dev

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api → 127.0.0.1:8000)
npm run build      # production build → dist/
npm run lint       # oxlint
npm run build:art  # regenerate rasterised artwork from art-src/proteus-engraving.svg
```

---

## Frontend Studio — Cobalt & Engraving Design System

Proteus uses a single saturated **cobalt world** with off-white type and fine-line
black-ink engraving. The reference feel: confident, editorial, mythic, calm.
No glassmorphism, no emoji, no stock icons. Generous whitespace, huge type, few elements per screen.

### Colour Tokens

| Token | Value | Usage |
|---|---|---|
| `--cobalt` | `#2641E6` | Primary background, full-bleed |
| `--cobalt-deep` | `#1B33D6` | Panels, hover, section alternation |
| `--ink` | `#070B2E` | Near-black navy, text on paper |
| `--paper` | `#F3EFE6` | Primary text on cobalt, light cards |
| `--paper-muted` | `rgba(243,239,230,0.82)` | Secondary text on cobalt-deep |
| `--paper-label` | `rgba(243,239,230,0.90)` | Small labels on cobalt |
| `--foam` | `#C9F0E3` | Live / success / streaming / focus ring |
| `--ember` | `#FF5B2E` | Borders, dots on dark surfaces |
| `--ember-ink` | `#B8320C` | Text/stamps on paper (WCAG AA ≥ 4.5:1) |
| `--hairline` | `rgba(243,239,230,0.28)` | Borders everywhere |

**Rule:** cobalt + paper + ink do 95% of the work. Foam and ember are rare, small, and meaningful.
Radius: `2px` on cards/inputs; `9999px` on pills only.

### Typography

| Role | Font | Settings |
|---|---|---|
| Display / Headlines | **Newsreader** (variable, opsz on, 300–500) | Tight tracking `-0.03em`, line-height `0.95`, up to `~11vw` on hero |
| UI / Body | **Instrument Sans** 400/500/600 | — |
| Labels / Metadata / Code | **JetBrains Mono** 400/500 | Uppercase, 11–12 px, tracking `0.08em` |

Loaded via Google Fonts (`display=swap`) with full fallback stacks.
**Fonts are the only allowed external request**; everything else works offline on localhost.

### Artwork — `proteus-engraving.svg`

The master SVG (`art-src/proteus-engraving.svg`, 14 MB, ~21 000 paths) is a black-ink
engraving on white: Proteus rising from waves, holding a flame, lion's head, serpent, and tree.

**Never inline or load it raw.** `npm run build:art` rasterises it via `@resvg/resvg-js` + `sharp`:

| Output | Size | Usage |
|---|---|---|
| `public/art/proteus-full@2x.webp` | 2400 px | Hero `srcset 2x` |
| `public/art/proteus-full.webp` | 1200 px | Hero `srcset 1x` |
| `public/art/proteus-full-800.webp` | 800 px | Hero mobile |
| `public/art/proteus-{flame,lion,serpent,tree,waves,face}.webp` | ~1000 px each | Section crops |
| `public/art/proteus-alpha.png` | 1200 px | Luminance-as-alpha; ink areas = opaque, paper = transparent |

**Blending:**
- White-background WebP on cobalt → `mix-blend-mode: multiply`. White becomes cobalt, ink stays black.
- `proteus-alpha.png` with `filter: invert(1)` → lines render in paper colour on dark (`bg-ink`) sections.

### Motion

- Hero headline: staggered line reveal (`translateY 24 px + opacity`, 700 ms, `cubic-bezier(0.16,1,0.3,1)`)
- Hero engraving: slow breathing scale `1.00 → 1.03` (14 s loop) + scroll parallax
- Section reveals: `IntersectionObserver`, engraving crops drift 20–40 px
- Tier hover: crop scales `1.03`, numeral underline wipes in
- **`prefers-reduced-motion`**: disables parallax, breathing, marquee, and all transitions

### Landing Page Sections (`/`)

1. **Nav** — sticky, transparent over cobalt, hairline bottom on scroll; lowercase serif wordmark; mono links; pill CTA
2. **Hero** — full-viewport cobalt, Newsreader headline, staggered reveal, engraving right/centre bleeding off bottom, install line with copy button
3. **Marquee strip** — hairline-bordered, mono, slow scroll
4. **Four Tiers of Becoming** — alternating cobalt/cobalt-deep, engraving crop + roman numeral + serif title + 2–3 line description
5. **Live Style-Profile Demo** — paper card on cobalt-deep, stylometry fingerprint, streaming mock data
6. **Safety Gate** — paper email mockup with rotating `PENDING REVIEW` ember stamp; Approve toggles to foam Sent
7. **Privacy Band** — `bg-ink`, inverted alpha engraving at low opacity, `100% local. Zero telemetry.`
8. **Footer** — oversized wordmark, GitHub/License links, mono tagline

### App Workspace (`/workspace`)

- `bg-cobalt-deep`; hairline borders everywhere, no shadows
- Left rail (260 px): wordmark, `+ New session`, `Ctrl+K` search, grouped session history (Today / Previous 7 Days / Earlier), inline Rename + Delete, Account Switcher, Add account, Style Profile
- Centre: chat; agent messages in Newsreader, user messages in Instrument Sans; foam streaming caret; face crop as Proteus monogram; `NEEDS_CLARIFICATION` inline cards
- Right (30 rem, desktop): Paper Letter Draft Card — editable To/Cc/Bcc/Subject/Body, audience tag, `Suggest a tweak` → `POST /api/draft/tweak`, Save Draft, `Approve & Send Now` → `POST /api/email/approve-and-learn`
- Top bar: real `Qwen3:8B` health indicator (foam=online, ember=offline), Auto-Send toggle with ember warning band
- `PENDING_REVIEW`: dashed ember border + banner; `SENT`: foam border + band
- Empty states: small engraving crops as illustrations
