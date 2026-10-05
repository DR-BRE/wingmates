# Playful Reskin — Design

Date: 2026-10-04. Status: design approved in conversation; written spec awaiting review.

## Purpose

Brett asked for a Duolingo-style UI in Wingmates. Agreed scope is two
sub-projects:

1. **Reskin** (this spec): a bright, chunky, friendly look across the whole
   front end.
2. **Gamification** (separate spec, later): streaks, XP, achievements, leagues.

Success for this piece: every screen reads as one playful system in both light
and dark, nothing that works today stops working, and no Python changes.

## Decisions made with Brett

- Scope: reskin now, gamification as its own follow-up project.
- Theme: light and dark, following the system setting (`prefers-color-scheme`).
  No manual toggle.
- Personality: playful copy and simple icons. No mascot.

## Assumptions (mine, not yet confirmed)

- Primary colour is sky blue, not Duolingo's green, to suit a flight app and
  avoid looking like a clone. Green is the success colour.
- Typeface is Nunito from Google Fonts, the usual free stand-in for Duolingo's
  proprietary face.
- No Duolingo assets: no owl, logo, or proprietary font.

## Approach

Rewrite `public/static/style.css` in place on a new token layer. Keep every
existing class name and element id, because the scripts build rows by class
name and the tests fetch pages by route. Rejected: an override sheet layered on
the old CSS (two styles fighting forever) and Tailwind or a component library
(adds a build step to a no-build app).

## Visual system

### Colour roles

| Role | Used for |
|---|---|
| Primary (sky blue) | Main buttons, active tab, selection, focus |
| Success (green) | Arrived / at gate, confirmations |
| Reward (gold) | Wingspan scores, top-three ranks |
| Mate (coral) | Mate rows, head-to-head, as today |
| Warn (amber) | Signal lost |
| Danger (red) | Emergencies, delete, errors |

Each role has a fill, a darker "lip", a tint background, and an ink (text)
shade. Text on any fill or tint meets WCAG AA (4.5:1). Light buttons use white
text on a deepened blue; dark buttons use dark text on a bright blue.

Light surfaces: white panels on a very light grey page, light-grey 2px borders,
charcoal text. Dark surfaces: deep navy-slate panels, slate borders, near-white
text.

### Type

Nunito 600/700/800/900 for everything. Monospace stays only for callsigns and
registrations. Numbers use tabular figures. Section labels stay uppercase but
become heavy Nunito with light tracking instead of spaced-out mono.

### Shape

- Buttons: 14px radius, 2px border, 4px solid lip below, uppercase 800 label.
  Pressing moves the button down 4px and removes the lip. Variants: primary,
  secondary (`.quiet`), danger. Minimum height 44px for main actions.
- Inputs: 2px border, 12px radius, soft fill, primary border on focus.
- Rows and cards: 2px border, 16px radius, roomier padding. Selected or
  editing: primary border and tint. Emergency: danger border and tint.
- Tabs: three separate chunky buttons, each with an icon; active is
  primary-tinted with a primary border.
- Totals: tiles with a coloured icon each.
- Leaderboard: gold, silver, bronze rank badges for ranks 1 to 3; own row
  primary-tinted.
- Pills become rounded chips. Toast, account menu and globe popup become
  chunky cards with a 2px border.
- Sign-in and username pages: centred card, full-width primary button.

### Globe and map

The globe and flat map stay dark in both themes. Colours drawn by the scripts
(plane, route, dot colours) are unchanged. In light theme the map area gets a
rounded frame and a margin so it reads as a panel. Map tool buttons, the
Globe/Map toggle and callsign tags use fixed dark-surface colours in both
themes, since they sit on the dark map.

### Icons

Seven small inline SVG icons, drawn fresh, stroke-based, `currentColor`:
three tab icons, four totals icons (the plane is shared), and one for import.
Each is decorative (`aria-hidden="true"`); the text label stays. Icons never
go in a button whose text a script rewrites, because the rewrite would remove
them.

### Copy

Friendlier labels, hints and empty states, same meaning. Examples: "No flights
yet. Where to first?", "No mates yet. Find one by username.", "Nothing tracked
yet." Error text stays plain and specific. No exclamation-heavy cheerleading.

### Motion

Button press (transform, 80ms), tab and toast pop (150 to 200ms). All disabled
under `prefers-reduced-motion: reduce`.

### Layout

Unchanged: header, 390px sidebar, map; stacked below 860px. No horizontal
scroll at 375px wide.

## Files

- `public/static/style.css`: rewritten.
- `web/index.html`, `web/login.html`, `web/welcome.html`: font link,
  `color-scheme` meta, icons, copy.
- `public/static/app.js`, `history.js`, `social.js`: copy strings, totals
  icons, rank badge class. No behaviour changes.
- `globe.js` and all Python: untouched.

## Risks

- Google Fonts is a new third-party request. If it fails, the stack falls back
  to the system rounded/sans face and the layout must still hold.
- The date input is forced dark today (`color-scheme:dark`); it must follow the
  theme.
- Light-theme surfaces that overlap the dark map (toast, popups) must stay
  legible against it.

## Testing

- Existing suite stays green: `.venv/bin/python -m unittest discover -s tests -t .`
- Browser check with the `wingmates-dev` server: My flights, Social, Live,
  sign-in and username pages, each in light and dark, at desktop width and at
  375px. No console errors.

## Out of scope

Layout restructuring, a mascot, a manual theme toggle, and all gamification.
