# Voca Rebrand — Color Palette & Logo

## Context

The Voca UI currently uses the default shadcn **neutral** token set — every color in `frontend/app/globals.css` is a pure gray, so buttons, links, nav, chips and chat bubbles all render monochrome. The rebrand applies the user's 5-color palette and logo (recolor decision applied: **brand purple tile #6A54D4 with the original cream wave stroke**), keeping all existing component code untouched where possible because the app styles through shadcn CSS-variable tokens.

### Decisions (user, via Inbox)

1. **Primary/interactive color**: purple-blue `#6A54D4`
2. **Dark mode**: keep it, dark surfaces re-skinned on navy `#09162F`
3. **Logo in-app**: recolored to a brand purple (`#6A54D4`) tile, cream stroke — used in sidebar, auth card, favicon
4. **Boldness**: subtle touches — light-blue surfaces, green for success/progress, one purple→pink gradient moment on the auth page (no gradients on buttons/everywhere)

### Palette (with computed OKLCH)

| Role | Hex | Token target |
|---|---|---|
| Purple-blue primary | `#6A54D4` | `oklch(0.539 0.188 286.1)` |
| Navy ink / dark base | `#09162F` | `oklch(0.205 0.053 262.1)` |
| Pink accent | `#C280B6` | `oklch(0.685 0.108 333.4)` |
| Light blue soft surface | `#D9E3F7` | `oklch(0.914 0.029 264.4)` |
| Light green success | `#9ED981` | `oklch(0.824 0.132 135.9)` |
| Logo stroke cream | `#FDF9F0` | `oklch(0.983 0.013 86.8)` |

## Approach

Brand the token layer, swap the two icon brand marks for the real logo, and fold the three hardcoded Tailwind-green/blue spots into brand tokens. Components keep their classes (`bg-primary`, `text-muted-foreground`, …) so the recolor is almost entirely a `globals.css` token swap; the user chat bubble recolors for free because `components/ui/bubble.tsx` derives its shades from `--primary` via relative-color syntax.

## Files to modify

- `frontend/app/globals.css` — token palette (light + dark) + brand extension tokens
- `frontend/public/logo.svg` (new) — source logo, purple tile + cream stroke
- `frontend/app/icon.svg` (new) + `frontend/app/favicon.ico` (regenerated) — favicon
- `frontend/components/sidebar.tsx` — replace `Languages` brand tile (2 spots) with the logo
- `frontend/app/auth/page.tsx` — replace icon tile with logo + subtle gradient wash
- `frontend/app/history/page.tsx`, `frontend/app/recap/[sessionId]/page.tsx`, `frontend/app/onboarding/page.tsx` — tokenize hardcoded green/blue
- `frontend/app/layout.tsx` — `viewport.themeColor` (navy/purple) metadata

## Reuse

- Existing token plumbing: `@theme inline` block in `globals.css` maps `--color-*` → theme utilities; add new `--color-brand-*` entries there to get `bg-brand-*`/`from-brand-*` utilities.
- `bubble.tsx` primary-derived tinting (tinted/default/hover variants) — no edits needed.
- `sharp` (already in `frontend/node_modules`) — one-off Node script to rasterize `icon.svg` → `favicon.ico` (48/32/16).
- shadcn `Empty`/`Message`/`Avatar` etc. already token-based — untouched.

## Steps

- [x] 1. **Add logo assets**
  - `frontend/public/logo.svg`: same geometry as the supplied SVG (viewBox 0 0 400 400, rx=90, same `g` transform/path), `fill` = `#6A54D4`, stroke stays `#FDF9F0`, stroke-width 32
  - `frontend/app/icon.svg`: same mark
  - One-off `node` + `sharp` script (run from `frontend/`, not committed) to write `app/favicon.ico` at 48/32/16 from `icon.svg`
- [x] 2. **Re-map tokens in `globals.css`**
  - Light (`:root`):
    - `--primary: oklch(0.539 0.188 286.1)`; `--primary-foreground: oklch(0.983 0.013 86.8)` (logo cream, ~5.3:1 on primary)
    - Cool-tinted neutrals: `--background` near-white cool, `--foreground` = navy ink `oklch(0.25 0.045 262)`
    - `--muted` / `--secondary` / `--border` / `--input` in the light-blue family (steps around `#D9E3F7`, tuned for large surfaces — lighter than the raw hex)
    - `--accent` = light purple wash (tinted from primary, for nav/hover states), `--accent-foreground` navy ink
    - `--ring: var(--primary)`
    - Sidebar tokens: `--sidebar` very light blue wash; `--sidebar-primary` purple; `--sidebar-accent` matching accent family
    - `--chart-1..5`: purple, pink, navy, green, light blue
  - Dark (`.dark`):
    - `--background: oklch(0.205 0.053 262.1)` (#09162F); card/popover one step lighter navy; `--muted`/`--secondary`/`--accent` further navy steps; `--foreground` soft cool white (`#E7ECF5` family)
    - Keep the existing `--border`/`--input` white-alpha pattern; `--ring` lighter purple
    - Keep `--primary` purple (white text still 5.5:1); `--sidebar-primary` a lighter purple step for dark
    - `--destructive`: leave as-is (both modes)
  - Brand extras (in `:root` and `.dark`, registered in `@theme inline` as `--color-brand-*`):
    - `--brand-navy: oklch(0.205 0.053 262.1)`, `--brand-pink: oklch(0.685 0.108 333.4)`, `--brand-green: oklch(0.824 0.132 135.9)`, `--brand-blue: oklch(0.914 0.029 264.4)`
    - `--success` = darker green step for light-mode text (`oklch(0.55 0.19 142)`-ish, tune visually)
- [x] 3. **Swap brand marks**
  - `components/sidebar.tsx` (lines 63/69): both `Languages` tiles → `<img src="/logo.svg" alt="Voca" />` inside the existing trigger/`div` wrappers (rounded shape matches logo tile; keep the collapsed-state language trigger behavior)
  - `app/auth/page.tsx` (line 47-49): `Languages` tile → logo mark
- [x] 4. **Subtle decorative touches**
  - Auth card: very subtle diagonal brand wash (`bg-linear-to-br from-primary/5 to-brand-pink/10`) behind the card content; logo mark stays purple
  - Leave chat empty state, buttons, and headers token-based (no extra gradients)
- [x] 5. **Tokenize hardcoded colors**
  - `app/history/page.tsx:106-107`: completed chip → green/success family (`bg-brand-green/25 text-success dark:…`); active chip → light-blue/primary family
  - `app/recap/[sessionId]/page.tsx:126,131-132`: `text-green-500` → `text-success`; wins list `bg-green-50 border-green-100 …` → `bg-brand-green/10 border-brand-green/30` (+ dark equivalents); bullet → `text-success`
  - `app/onboarding/page.tsx:245`: success circle `bg-green-100 text-green-600` → `bg-brand-green/25 text-success`
- [x] 6. **Metadata**: add `themeColor` (navy in dark, purple accent light) via `viewport` export in `app/layout.tsx`
- [x] 7. **Visual pass + gates** (see Verification)

## Verification

- `cd frontend && npm run typecheck && npm run lint` — must pass (project frontend gate)
- Backend untouched → run `uv run task test` only as a sanity check that nothing else regressed
- Manual: `uv run task frontend`, then click through **/auth, / (chat, incl. user bubble + sending a message), /history, /library, /profile, /onboarding, /recap** in both light and dark (theme toggle) — check: purple primary on buttons/links/active nav, light-blue surfaces, navy dark mode, success-green chips, logo in sidebar (expanded + collapsed) and auth card
- Favicon: hard-refresh a tab (or new private window) to see the purple-tile icon; confirm `app/favicon.ico` regenerated
