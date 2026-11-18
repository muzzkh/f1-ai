# Design brief

One page. This is the direction the website and dashboard are built to.

## The idea: a race programme

The site should feel like something printed for race day, not a software
dashboard: paper pages, heavy slanted headlines, hard printed shadows, and
dark timing panels dropped into the page like TV graphics in a magazine.
Colour comes from the sport itself rather than from a brand palette.

An earlier direction (near-black pages with a single purple accent, thin
grey rules, rounded pills and glow) was dropped: it was monochrome, and it
looked like every other dark dashboard.

## Where the colour comes from

| Source | Colour | Used for |
|---|---|---|
| The teams | from the data | Each race page wears its winner's colours across the whole hero; the lap duel splits between the two drivers' colours; team colour marks every driver everywhere |
| Kerbs | racing red `#e3262e` and white | The brand colour, section numbers, the stripe under the header, panel tops |
| Flags and pit boards | yellow `#ffd23c` on black | Headline numbers, active tabs, start line and sector marks |
| Chequered flag | black and white | Footer, plain page headers |
| Timing screens | purple `#a26bff`, green | Purple means fastest (sector done, speed ramp); green for throttle and "go" |
| Tyres | red, yellow, white, green, blue | Compounds, always in their real colours |
| Paper and asphalt | `#f1ede2` and `#16161a` | Pages and timing panels |

No team uses our red-white-yellow combination as a block, and we never use a
team's colour for anything except that team.

## Type

**Archivo**, expanded, black weight, italic, capitals for headlines: wide and
leaning forward. **Barlow Condensed** for labels and every number: the
condensed italic numerals read like pit boards and timing boards. Body text
is Archivo at normal width.

## Shapes and texture

- **The slant.** Tabs, tags, bars and markers lean 11 degrees, the way racing
  numbers and liveries do. Nothing is a rounded pill.
- **Hard shadows.** Panels and cards sit on an offset block of solid colour,
  like a two-colour print, instead of soft glows.
- **Kerb stripe** under the header and the hero; **chequered flag** at the foot
  of every page; **livery stripes** across heroes.
- **Race numbers.** Sections are numbered in red; the round number sits
  oversized and outlined behind the hero.

## Layout

12 columns, 1320 px maximum, 24 px gutters; one column on phones, where the
circuit moves up to sit straight under the winner. The focal object of every
page is the circuit itself, drawn from real geometry on a dark panel.

## Charts

One y-axis per chart; team colour for identity with a dashed line for the
second driver of a team; one-hue ramps for magnitude; labels in text colours;
hover detail on every mark. Charts with many team-coloured lines always sit
on dark panels, where every team colour stays readable.

## Motion

Motion shows data, never decorates: the circuit draws itself once, the car
laps in real time, gauges follow the telemetry. Nothing autoplays under
`prefers-reduced-motion`.

## What we do not borrow

The references (formula1.com, landonorris.com) set the bar for craft: scale,
confidence, strict grids, colour discipline. We do not use either site's
logo, typeface, photography, textures or layouts.

## What stays honest

Track width, kerbs and the scenery in generated video are stylised and
labelled as such. Car telemetry is sampled about four times a second, and
every graphic that implies finer precision says so.
