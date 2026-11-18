# Design brief

One page. This sets the direction for the visual overhaul; the approval hero in
`site/` is the first thing built from it.

## What the references do well

Reviewed 18 November 2026.

**formula1.com** - charcoal surfaces, one wide geometric display face used in
capitals, a single hot accent, full-bleed photography under a gradient, dense
results tables with thin dividers and team colour as a small dot, pill-shaped
filters, a countdown strip. It feels official because it is consistent and
dense, not because it is decorated.

**landonorris.com** - one enormous focal object per screen, type set far larger
than expected, two type voices played against each other (a heavy grotesk and a
high-contrast serif), a single acid accent, faint contour lines as texture,
very small precise interface elements pinned to the corners, and scroll-driven
scene changes. It feels premium because of scale contrast and restraint.

## What we take, and what we do not

We take the principles: one focal object, big confident type, a strict grid,
one accent, team colour as the organising device for data, small precise
labels, purposeful motion. We do not take either site's logo, typeface,
photography, colour pairing, textures or page layouts.

## Our identity: the timing screen

The idea is the pit-wall timing screen, where **purple means fastest**. That
convention belongs to the sport's data, not to any brand, and it gives every
colour a meaning.

| Role | Value | Use |
|---|---|---|
| Carbon (background) | `#0a0b0d` | page |
| Surface / raised | `#121418` / `#1a1d23` | panels, components |
| Hairline | `#2a2e37` | dividers, grids |
| Paper (text) | `#f4f1ea` | headings, values |
| Secondary / muted text | `#b8b4aa` / `#7c7a73` | labels, notes |
| Purple sector (accent) | `#a26bff` | fastest, focus, interactive, speed ramp |
| Throttle / brake | `#35d07f` / `#ff4d5a` | pedal inputs only |
| Team colours | from the data | anything that identifies a driver or team |

No team uses purple, so the accent never collides with a car.

**Focal object:** the circuit itself, drawn from real geometry, large enough to
bleed off the grid. Where the references use a photograph or a portrait, we use
the track.

**Type:** Archivo (variable width and weight). Expanded and heavy for display,
normal width for text, condensed capitals for small labels - three voices from
one family. JetBrains Mono for every number, so times and speeds line up like a
timing screen.

**Texture:** our own data, not borrowed patterns - sector ticks, a faint
measurement grid behind the circuit, telemetry traces as section dividers.

**Grid:** 12 columns, 1320 px maximum, 24 px gutters; 4 columns below 900 px;
8 px spacing unit. Corners are 4 px (precise, technical), never pill-shaped
except on toggles.

**Motion:** motion shows data, never decorates. The circuit draws itself once on
load, the car laps in real time, gauges follow the telemetry. 200 ms ease-out
for interface changes. Nothing autoplays under `prefers-reduced-motion`.

**Charts:** one y-axis per chart; team colour for identity with a dashed line for
the second driver of a team; one-hue ramps for magnitude (the purple ramp for
speed); labels in text colours; hover detail on every mark.

## What stays honest

Track width and kerbs are not in any data source, so they are drawn to a
stylised width and labelled as such. Car telemetry is sampled about four times
a second, and every graphic that implies finer precision says so.
