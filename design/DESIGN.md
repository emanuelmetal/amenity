# Torre 3 portal: design system

This is the visual reference for Claude Code. Use it together with `design/theme.css` (Tailwind v4 tokens).

The look is modelled on the public demo of the **Eyris** React admin template (themenate). It was measured from the live demo on 2026-11-14.

**Licensing rule:** reuse the *visual language* only (colours, type, spacing, layout patterns). Build our own components, for example with plain Tailwind or shadcn/ui primitives.

- Don't copy Eyris's JS/CSS bundle, illustrations, logo or name. It's a paid template.
- If we ever want its actual components, buy a licence.

## 1. Principles

- Calm, neutral, data-first. White surfaces on a near-white app background, thin grey borders, almost no shadows.
- One accent colour: blue `#286cf0`. Use it for the active nav item, primary buttons, focus rings and the first chart series.
- Green and red are reserved for meaning: up/down deltas, verified/unverified, and so on.
- Numbers are the heroes: values are 20px semibold `gray-900`, and labels are 14px `gray-500`.
- The UI is in Spanish (es-AR).
  - Money: `Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS'})` → `$ 125.318,00`. Drop the decimals in KPI tiles.
  - Dates: `14 nov 2026`.

## 2. Tokens (summary — the source of truth is `theme.css`)

| Token | Value | Use |
|---|---|---|
| Font | **Geist** (300–700) | Everything. Use tabular figures (`font-variant-numeric: tabular-nums`) in tables and KPIs |
| `gray-50` | `#fafafa` | App background |
| `gray-100` | `#f5f5f5` | KPI tray, active nav item, input addons |
| `gray-200` | `#e5e5e5` | Card borders, dividers, table row lines |
| `gray-300` | `#d5d7da` | Input borders |
| `gray-500` | `#717680` | Body text, labels, table cells |
| `gray-700` | `#404040` | Nav item text |
| `gray-900` | `#171717` | Headings, KPI values, emphasised cells |
| `primary` | `#286cf0` | The only accent colour (deep `#1f56c0` for hover) |
| `success` / `-subtle` | `#00a85b` / `#05eb7624` | Positive delta, "Verificado" |
| `error` / `-subtle` | `#eb4137` / `#eb41371a` | Negative delta, "Sin comprobante" |
| `warning` / `-subtle` | `#f59e0b` / `#ffd40045` | "Sin verificar", "En revisión" |
| Chart series | `#286cf0`, `#8c62ff`, `#05aed3`, `#00c27f`, `#f59e0b` | In this order. Red only for negatives |
| Radius | 8px (`rounded-lg`) for cards, inputs, buttons. 6px (`rounded-md`) for tags and the segmented control | |
| Spacing | 4px base. Card padding 16px, grid gap 16px, page padding 24px × 32px | |

**Type scale**

| Role | Size | Weight | Colour |
|---|---|---|---|
| Page title | 20px | 600 | gray-900 |
| Card title | 18px | 600 | gray-900 |
| KPI value | 20px | 600 | gray-900 |
| Body and labels | 14px / 21px | 400 | gray-500 |
| Table header | 12px | 600, uppercase, letter-spacing 0.05em | gray-500 |
| Tag / delta | 12px | 600 | |

## 3. Layout shell

- **App background** `gray-50`. The whole content area sits in **one white panel**: `bg-white rounded-lg shadow` with 8px of outer margin (`p-2` on the wrapper), so the app reads as a floating sheet.
- **Sidebar** (≈ 260px, sits on the grey background, not inside the panel):
  - Logo at the top, then small uppercase section labels (12px, gray-500).
  - Nav items: 14px, gray-700, icon + label, height 36px.
  - **Active item:** `bg-gray-100`, `text-primary`, font 600, a 1px inset ring in gray-200 and a tiny shadow. Sub-items hang from a thin vertical line that turns primary on the active item.
  - The user block sits at the bottom.
- **Top bar** inside the panel: collapse button and search on the left; notifications and settings on the right as 32px ghost icon buttons.
- **Page header:** title (20px/600) with a subtitle line (14px gray-500, e.g. today's date) underneath. Filters on the right: a switch and a select styled as a white `rounded-lg` button with a border and a chevron.
- **Content:** `space-y-4`, with grids such as `grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4`.

## 4. Components

**Card:** `bg-white rounded-lg border border-gray-200`.
- Body `p-4`. Header: title (18px/600) on the left, actions on the right.
- No shadow (the `card-shadow` variant is rare: `0 2px 4px #00000026`).

**KPI tile** (signature pattern, use it for the expenses dashboard):
```
<div class="rounded-lg border border-gray-200 bg-gray-100 p-1">          <!-- tray -->
  <div class="rounded-lg bg-white p-4 border-b border-gray-200">          <!-- inner card -->
    <div class="size-10 rounded-lg border border-gray-200 grid place-items-center">icon</div>
    <div class="mt-4 text-sm text-gray-500">Gasto del mes</div>
    <div class="text-xl font-semibold text-gray-900">$ 2.450.000</div>
  </div>
  <div class="flex justify-between px-3 py-2 text-xs">
    <span class="font-semibold text-success">↑ 5,8%</span>
    <span class="text-gray-500">vs mes anterior</span>
  </div>
</div>
```

**Delta chip:** `inline-flex items-center gap-0.5 rounded-md px-2 py-0.5 text-xs font-semibold`.
- Green: `bg-success-subtle text-success`.
- Red: `bg-error-subtle text-error`.
- Plain-text variant without a background is used in the KPI footer.

**Status tag** (table cells): white pill, `border border-gray-200 rounded-md px-2 py-0.5 text-xs font-semibold text-gray-900`, with a 6px coloured dot before the text. Map the portal's statuses:

| Status | Dot colour |
|---|---|
| Verificado | success |
| Sin verificar | warning |
| Sin comprobante | error |
| Vinculado automáticamente | info |

**Table:**
- No outer border when it sits inside a card.
- Header row on a `gray-50` background: 12px/600, uppercase, letter-spacing 0.05em, gray-500, padding 8px.
- Cells: 14px gray-500, row padding `py-4 px-6`, 1px gray-200 dividers between rows.
- First column: 14px/500 gray-900, with an optional 32px icon box (`rounded-lg border`).
- Money columns are right-aligned and tabular.
- Numeric emphasis colours (green/red) only where a value has meaning.

**Buttons** (height 36px, `rounded-lg`, 14px/500, `active:translate-y-px` press feedback):
- Primary: `bg-primary text-white hover:bg-primary-deep`.
- Default: `bg-white border border-gray-300 text-gray-700 hover:bg-gray-50`.
- Ghost icon: 32px, `rounded-md`, text gray-900/70, `hover:bg-gray-100`.

**Inputs and selects:**
- `rounded-lg border border-gray-300 px-3 py-1.5`, placeholder gray-400.
- Focus: `border-primary ring-1 ring-primary`.
- Invalid: `border-error bg-error-subtle`.
- Dropdown menu: `rounded-lg border border-gray-300 bg-white`, with a large soft shadow (`0 48px 64px -16px #00000040`).

**Segmented control** (period switcher):
- Container `bg-gray-100 rounded-md p-1`.
- Items 14px/600, gray-500.
- Active item: white with a small shadow, gray-900.

**Switch:** 40×20px, track gray-200, primary when on, white 16px knob.

**Dialog:** white `rounded-lg p-4` with a large shadow. Overlay is black at 60% with a 12px backdrop blur.

**Avatar / icon box:** 32/40/48px, `rounded-md` or circle, gray-100 background, 1px gray-200 border.

## 5. Charts (ECharts or Recharts)

- **Line charts:** 2px lines, no area fill (or a very faint fill of the series colour), no markers until hover.
- **Bar charts:** 8px radius on the top corners only. Stacked segments use the same colour family (blue + cyan).
- **Donut:** thick ring (~25% of the radius), 2px white gaps between segments. The legend goes in a table below, with a colour dot, the label, and right-aligned values.
- **Grid:** horizontal dashed lines in gray-200, no vertical grid. Axis labels 12px gray-500, values abbreviated (`$4,5 M`).
- **Tooltip:** white `rounded-lg border-gray-200` with a soft shadow, 12px text.

## 6. Portal-specific mapping

| Portal screen | Pattern to use |
|---|---|
| Inicio | Row of 4 KPI tiles (gasto del mes, variación, % con comprobante, gastos sin comprobante), then "Gasto por rubro" (stacked bars by month) + "Top proveedores" (donut + legend table) |
| Gastos | Card with the page header filters (period select, rubro select, search input) and a table with status tags. Clicking a row opens a right side panel (dialog variant, `max-w-xl`) with the ticket image |
| Reglamento | Two columns: article index in the sidebar style on the left, readable text on the right (`prose` 16px, gray-700, max-width 70ch), "Ver original" default button |
| Comentarios | Cards with an avatar placeholder ("V" in gray-100), "Vecino/a anónimo/a", relative time in gray-400, and a "Reportar" ghost button |

## 7. Dark mode

The template supports dark mode (background `gray-950`, cards `gray-800/900`, text `gray-400`). Leave it out of the MVP. The tokens already allow it via the `.dark` class.
