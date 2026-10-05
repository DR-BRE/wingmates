# Playful Reskin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Wingmates screen a bright, chunky, friendly look in light and dark themes, with no change to behaviour or to any Python.

**Architecture:** `public/static/style.css` is rewritten in place on a token layer: light tokens on `:root`, dark tokens under `prefers-color-scheme:dark`, and the dark tokens repeated on `.mapwrap` because the map is dark in both themes. Every existing class name and element id is kept, so the scripts keep working. Icons come from one inline SVG sprite in `web/index.html`. A new offline test file pins the contract between pages, scripts and stylesheet.

**Tech Stack:** Vanilla CSS, HTML and JS (no build step), Flask static serving, Python `unittest`, Nunito from Google Fonts.

**Spec:** `docs/superpowers/specs/2026-10-04-playful-reskin-design.md` — read it before starting.

## Global Constraints

- No Python changes outside `tests/`. No change to `public/static/globe.js`.
- No new dependencies and no build step. The only new third-party request is Google Fonts (Nunito, weights 600, 700, 800, 900).
- Keep every existing class name and element id. Scripts find elements by them.
- No Duolingo assets: no owl, no logo, no proprietary font. Primary colour is sky blue; green is the success colour.
- Theme follows `prefers-color-scheme` only. No manual toggle.
- The globe and flat map stay dark in both themes. Colours drawn by the scripts (`#5fd0dd`, `#f08a6b`, `#4fb6c2`, `#e0574d` and friends in `app.js`, `history.js`, `social.js`, `globe.js`) are not changed.
- Text on any fill or tint meets 4.5:1. If the contrast test fails, change the token value. Never weaken or delete a pair in the test.
- Monospace is used only for callsigns and registrations.
- Copy is friendly and plain. No exclamation marks. Error text stays specific.
- No mascot, no layout restructuring, no gamification.
- Run tests with `.venv/bin/python -m unittest discover -s tests -t .`
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (use your own model name if you are a different model).

## Review Focus

Each line has a test or a named check in the task that owns it.

1. **Google Fonts is blocked or offline.** Expected: text falls back to a system rounded or sans face and nothing overlaps. Test in Task 2 (`--sans` has system fallbacks); browser check in Task 5.
2. **Light theme, with a toast or popup over the dark map.** Expected: it is a dark card with light text, readable against the map. Test in Task 2 (`.mapwrap` carries the dark tokens).
3. **A tinted row: your own leaderboard row, an open mate, an emergency card, a flight being edited.** Expected: every line of text in it is still readable. Test in Task 2 (tint pairs in the contrast test).
4. **A script rewrites a button's text** (`h-add`, `add-btn`, `btn-nearby`, `btn-refresh` are all reset with `textContent`). An icon inside one would vanish after the first click. Expected: icons live only in buttons no script rewrites. Test in Task 3.
5. **A 20-character username, a long name, or long flight notes at 375px wide.** Expected: text is cut with an ellipsis and the page never scrolls sideways. Browser check in Task 5.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tests/test_frontend.py` | Offline contract tests for pages, scripts, stylesheet | Create |
| `public/static/style.css` | All styling | Rewrite |
| `web/index.html` | Main page: head, icon sprite, tab icons, copy | Modify |
| `web/login.html`, `web/welcome.html` | Gate pages: head only | Modify |
| `public/static/history.js` | Totals icons, copy | Modify |
| `public/static/social.js` | Rank badge class, copy | Modify |
| `public/static/app.js` | Not changed unless Task 5 finds a problem | — |

---

### Task 1: Branch, contract test file, page heads

**Files:**
- Create: `tests/test_frontend.py`
- Modify: `web/index.html:1-9`, `web/login.html:1-8`, `web/welcome.html:1-8`

**Interfaces:**
- Produces: module-level names in `tests/test_frontend.py` that later tasks extend: `ROOT`, `CSS`, `PAGES` (dict of filename to text), `SCRIPTS` (dict of filename to text).

- [ ] **Step 1: Create the branch and commit the spec and plan**

The work starts from the current branch (`free-hosting`).

```bash
git switch -c playful-reskin
git add docs/superpowers/specs/2026-10-04-playful-reskin-design.md docs/superpowers/plans/2026-10-04-playful-reskin.md
git commit -m "Add the playful reskin spec and plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_frontend.py`:

```python
"""Front-end contract tests: static checks on pages, scripts and stylesheet. Offline."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "public/static/style.css").read_text()
PAGES = {name: (ROOT / "web" / name).read_text()
         for name in ("index.html", "login.html", "welcome.html")}
SCRIPTS = {name: (ROOT / "public/static" / name).read_text()
           for name in ("app.js", "history.js", "social.js")}

# Ids that app.js creates itself (the account menu and the dev-user form).
MADE_BY_SCRIPT = {"acct-out", "acct-del", "del-form", "del-confirm",
                  "dev-form", "dev-user"}


class TestPageHeads(unittest.TestCase):

    def test_every_page_loads_nunito_and_declares_both_schemes(self):
        for name, html in PAGES.items():
            with self.subTest(page=name):
                self.assertIn("fonts.googleapis.com/css2?family=Nunito", html)
                self.assertIn('<meta name="color-scheme" content="light dark">', html)
                self.assertLess(html.index("fonts.googleapis.com/css2"),
                                html.index("/static/style.css"),
                                "the font must load before the stylesheet")


class TestScriptsFindTheirElements(unittest.TestCase):

    def test_every_id_a_script_looks_up_is_on_the_page(self):
        on_page = set(re.findall(r'id="([^"]+)"', PAGES["index.html"]))
        for name, js in SCRIPTS.items():
            wanted = set(re.findall(r"\$\('([^']+)'\)", js))
            with self.subTest(script=name):
                self.assertEqual(wanted - on_page - MADE_BY_SCRIPT, set())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to see the head test fail**

Run: `.venv/bin/python -m unittest tests.test_frontend -v`
Expected: `test_every_page_loads_nunito_and_declares_both_schemes` FAILS (no font link yet). `test_every_id_a_script_looks_up_is_on_the_page` PASSES; it is a guard for the later tasks.

- [ ] **Step 4: Add the font and colour-scheme lines to all three pages**

In each of `web/index.html`, `web/login.html` and `web/welcome.html`, put these four lines directly after the `<meta name="viewport" ...>` line:

```html
<meta name="color-scheme" content="light dark">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800;900&display=swap">
```

In `index.html` the Leaflet stylesheet link stays where it is, before `/static/style.css`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add tests/test_frontend.py web/index.html web/login.html web/welcome.html
git commit -m "Load Nunito and declare both colour schemes on every page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Rewrite the stylesheet

**Files:**
- Modify: `public/static/style.css` (replace the whole file)
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `CSS`, `SCRIPTS` from Task 1.
- Produces: CSS classes later tasks use in markup: `.ico` (an inline SVG icon), `.rank.medal.m1`, `.rank.medal.m2`, `.rank.medal.m3` (rank badges). Token names: `--bg --panel --panel-2 --line --lip --ink --muted --faint --accent --accent-lip --accent-dim --accent-line --accent-ink --on-accent --green-ink --green-tint --green-line --gold --on-gold --gold-ink --gold-tint --coral --coral-ink --coral-tint --amber --amber-tint --amber-line --red --red-fill --red-lip --on-red --red-tint --red-line --shadow --mono --sans`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_frontend.py`, above the `if __name__` line:

```python
def block(css, start):
    """The text inside the first pair of braces that opens at or after `start`."""
    i = css.index("{", start)
    depth = 0
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1:j]
    raise AssertionError("unbalanced braces")


def tokens(text):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b", text))


def luminance(colour):
    parts = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (text token, background token): every pairing the stylesheet actually uses.
PAIRS = [
    ("--ink", "--panel"), ("--ink", "--bg"), ("--ink", "--accent-dim"),
    ("--muted", "--panel"), ("--muted", "--panel-2"), ("--muted", "--accent-dim"),
    ("--muted", "--coral-tint"), ("--muted", "--red-tint"),
    ("--faint", "--panel"), ("--faint", "--panel-2"),
    ("--on-accent", "--accent"),
    ("--accent-ink", "--panel"), ("--accent-ink", "--accent-dim"),
    ("--green-ink", "--green-tint"),
    ("--on-gold", "--gold"),
    ("--gold-ink", "--panel"), ("--gold-ink", "--accent-dim"), ("--gold-ink", "--coral-tint"),
    ("--coral-ink", "--panel"), ("--coral-ink", "--coral-tint"),
    ("--amber", "--amber-tint"),
    ("--red", "--panel"), ("--red", "--red-tint"),
    ("--on-red", "--red-fill"),
]

# Classes the scripts and pages put on elements; each needs a rule.
CLASSES = ["logrow", "frow", "prow", "brow", "card", "sel", "emerg", "phase",
           "metrics", "ev", "loud", "alarm", "toast", "show", "bad", "pill",
           "hint", "error", "tag", "gdot", "gmark", "gpop", "av", "pn", "un",
           "st", "rank", "ws", "sub", "h2h", "lead", "acct", "menu", "quiet",
           "danger", "editing", "on", "badge", "count", "empty", "medal", "ico"]


class TestStylesheet(unittest.TestCase):

    def setUp(self):
        self.light = tokens(block(CSS, CSS.index(":root")))
        media = block(CSS, CSS.index("@media (prefers-color-scheme:dark)"))
        self.dark_only = tokens(block(media, media.index(":root")))
        self.dark = {**self.light, **self.dark_only}

    def test_text_is_readable_on_every_surface_in_both_themes(self):
        for theme, t in (("light", self.light), ("dark", self.dark)):
            for fg, bg in PAIRS:
                with self.subTest(theme=theme, text=fg, on=bg):
                    self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5)

    def test_dark_theme_redefines_every_colour_token(self):
        self.assertEqual(set(self.dark_only), set(self.light))

    def test_the_map_area_uses_the_dark_tokens_in_both_themes(self):
        on_map = tokens(block(CSS, CSS.index(".mapwrap{")))
        self.assertEqual(on_map, self.dark_only)

    def test_the_font_has_system_fallbacks(self):
        sans = re.search(r"--sans\s*:\s*([^;]+);", CSS).group(1)
        self.assertTrue(sans.startswith('"Nunito"'))
        self.assertIn("ui-rounded", sans)
        self.assertIn("-apple-system", sans)
        self.assertTrue(sans.rstrip().endswith("sans-serif"))

    def test_motion_can_be_turned_off(self):
        self.assertIn("@media (prefers-reduced-motion:reduce)", CSS)

    def test_the_date_field_follows_the_theme(self):
        self.assertNotIn("color-scheme:dark", block(CSS, CSS.index("#h-date")))

    def test_every_class_in_use_has_a_rule(self):
        for cls in CLASSES:
            with self.subTest(cls=cls):
                self.assertRegex(CSS, r"\.%s\b" % re.escape(cls))

    def test_the_old_theme_is_gone(self):
        for old in ("#080c11", "#0e151d", "#17414a", "#15434c", "#4fb6c2"):
            with self.subTest(colour=old):
                self.assertNotIn(old, CSS)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest tests.test_frontend.TestStylesheet -v`
Expected: errors and failures (`ValueError: substring not found` for the dark media query, missing tokens, old colours present).

- [ ] **Step 3: Replace `public/static/style.css` with this file**

```css
/* Wingmates, playful theme. Light is the default; dark follows the system.
   Every colour is a token. The dark set appears twice: under the dark media
   query, and on .mapwrap, because the map is dark in both themes. */
:root{
  color-scheme:light dark;
  --bg:#f4f7fa; --panel:#ffffff; --panel-2:#f7f7f7; --line:#e0e4e8; --lip:#cfd5db;
  --ink:#3c3c3c; --muted:#666666; --faint:#707070;
  --accent:#0b76b8; --accent-lip:#085a8d; --accent-dim:#ddf4ff; --accent-line:#84d0f5;
  --accent-ink:#0b6aa5; --on-accent:#ffffff;
  --green-ink:#2a7600; --green-tint:#e3f8d3; --green-line:#a5e07a;
  --gold:#ffc800; --on-gold:#5c4300; --gold-ink:#7a5900; --gold-tint:#fff4cc;
  --coral:#f08a6b; --coral-ink:#b8451f; --coral-tint:#ffe9e1;
  --amber:#8a5a00; --amber-tint:#fff0d6; --amber-line:#f2cf8a;
  --red:#c02a24; --red-fill:#d8362f; --red-lip:#a82520; --on-red:#ffffff;
  --red-tint:#ffe3e1; --red-line:#f5a9a5;
  --shadow:0 8px 24px rgba(0,0,0,.12);
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:"Nunito",ui-rounded,"SF Pro Rounded",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0c171c; --panel:#131f24; --panel-2:#1c2b33; --line:#37464f; --lip:#2a3840;
    --ink:#f1f7fb; --muted:#a3b3bd; --faint:#8496a1;
    --accent:#49c0f8; --accent-lip:#1899d6; --accent-dim:#17384a; --accent-line:#2b6f93;
    --accent-ink:#49c0f8; --on-accent:#0b2230;
    --green-ink:#79d634; --green-tint:#1d3a17; --green-line:#3c6b2a;
    --gold:#ffc800; --on-gold:#3d2c00; --gold-ink:#ffd43b; --gold-tint:#3a3113;
    --coral:#f08a6b; --coral-ink:#ff9d80; --coral-tint:#3d251e;
    --amber:#ffb84d; --amber-tint:#3a2c14; --amber-line:#6b5120;
    --red:#ff6b63; --red-fill:#ff6b63; --red-lip:#d8443c; --on-red:#2b0704;
    --red-tint:#3d1c1b; --red-line:#7a3430;
    --shadow:0 8px 24px rgba(0,0,0,.45);
  }
}
.mapwrap{
  color-scheme:dark;
  --bg:#0c171c; --panel:#131f24; --panel-2:#1c2b33; --line:#37464f; --lip:#2a3840;
  --ink:#f1f7fb; --muted:#a3b3bd; --faint:#8496a1;
  --accent:#49c0f8; --accent-lip:#1899d6; --accent-dim:#17384a; --accent-line:#2b6f93;
  --accent-ink:#49c0f8; --on-accent:#0b2230;
  --green-ink:#79d634; --green-tint:#1d3a17; --green-line:#3c6b2a;
  --gold:#ffc800; --on-gold:#3d2c00; --gold-ink:#ffd43b; --gold-tint:#3a3113;
  --coral:#f08a6b; --coral-ink:#ff9d80; --coral-tint:#3d251e;
  --amber:#ffb84d; --amber-tint:#3a2c14; --amber-line:#6b5120;
  --red:#ff6b63; --red-fill:#ff6b63; --red-lip:#d8443c; --on-red:#2b0704;
  --red-tint:#3d1c1b; --red-line:#7a3430;
  --shadow:0 8px 24px rgba(0,0,0,.45);
  color:var(--ink);
}

/* ---------------------------------------------------------------- base */
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;font-weight:600;line-height:1.45;-webkit-font-smoothing:antialiased;
  overflow:hidden}
.ico{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:2.2;
  stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px}

/* -------------------------------------------------------------- header */
.bar{display:flex;align-items:center;gap:16px;padding:0 16px;height:60px;
  background:var(--panel);border-bottom:2px solid var(--line);flex-wrap:wrap}
.brand{font-weight:900;font-size:19px;letter-spacing:.02em;color:var(--ink)}
.brand .glyph{color:var(--accent-ink);margin-right:6px}
.brand .dim{color:var(--accent-ink)}
.status{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.who{display:flex;gap:10px;align-items:center;font-size:14px;font-weight:800;
  color:var(--muted)}
body.no-live .who{margin-left:auto}
.who input{width:150px;font-size:13px;padding:6px 10px;min-height:36px}
body.no-live .live-only{display:none}
.link + .link{margin-left:12px}
.pill{font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  padding:4px 12px;border-radius:999px;background:var(--accent-dim);color:var(--accent-ink);
  border:2px solid var(--accent-line);white-space:nowrap}
.pill.quiet{background:var(--panel-2);color:var(--muted);border-color:var(--line)}
.pill.bad{background:var(--red-tint);color:var(--red);border-color:var(--red-line)}

/* ------------------------------------------------------------- sidebar */
main{display:flex;height:calc(100vh - 60px);background:var(--bg)}
.side{width:390px;flex:none;background:var(--panel);border-right:2px solid var(--line);
  overflow-y:auto;padding:16px}
.side section{margin-top:26px}
.side h2,label{font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted)}
.side h2{margin:0 0 10px;display:flex;align-items:center;gap:8px}
label{display:block;margin-bottom:8px}
.count{background:var(--panel-2);border:2px solid var(--line);border-radius:999px;
  padding:0 8px;color:var(--muted);font-size:11px;letter-spacing:0}

/* ------------------------------------------------------------ controls */
.row{display:flex;gap:8px;align-items:flex-start}
input{flex:1;min-width:0;min-height:44px;background:var(--panel-2);
  border:2px solid var(--line);color:var(--ink);border-radius:12px;padding:8px 12px;
  font-family:var(--sans);font-weight:700;font-size:15px}
input:focus{outline:none;border-color:var(--accent);background:var(--panel)}
input::placeholder{color:var(--faint);font-weight:600}
button,.gatebtn{min-height:44px;margin:0 0 4px;padding:8px 16px;background:var(--accent);
  color:var(--on-accent);border:2px solid transparent;border-radius:14px;
  box-shadow:0 4px 0 var(--accent-lip);font-family:var(--sans);font-weight:800;
  font-size:13px;letter-spacing:.05em;text-transform:uppercase;cursor:pointer;
  white-space:nowrap;transition:transform .08s,box-shadow .08s,filter .08s}
button:hover,.gatebtn:hover{filter:brightness(1.07)}
button:active,.gatebtn:active{transform:translateY(4px);box-shadow:0 0 0 transparent}
button:focus-visible,.gatebtn:focus-visible,a:focus-visible,summary:focus-visible{
  outline:3px solid var(--accent-line);outline-offset:2px}
button:disabled{opacity:.5;cursor:not-allowed;transform:none;
  box-shadow:0 4px 0 var(--accent-lip)}
button.quiet,#h-import,#h-cancel{background:var(--panel);color:var(--muted);
  border-color:var(--line);box-shadow:0 4px 0 var(--lip)}
button.quiet:hover{color:var(--ink)}
button.danger{background:var(--red-fill);color:var(--on-red);
  box-shadow:0 4px 0 var(--red-lip)}
.hint{color:var(--muted);font-size:13px;margin:8px 0 0;line-height:1.45}
.hint.error{color:var(--red);font-weight:700}
.empty{color:var(--muted);font-size:14px;margin:0}

.tabs{display:flex;gap:8px;margin-bottom:20px}
.tabs button{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;
  padding:8px 6px;background:var(--panel);color:var(--muted);border-color:var(--line);
  box-shadow:0 4px 0 var(--lip)}
.tabs button.on{background:var(--accent-dim);color:var(--accent-ink);
  border-color:var(--accent-line);box-shadow:0 4px 0 var(--accent-line);
  animation:pop .15s ease-out}
@keyframes pop{from{transform:scale(.96)}to{transform:scale(1)}}
.badge{display:inline-block;min-width:18px;padding:0 5px;border-radius:999px;
  background:var(--red-fill);color:var(--on-red);font-size:11px;line-height:18px;
  letter-spacing:0}
.badge[hidden]{display:none}

#hist-form .row + .row,#hist-form details .row{margin-top:8px}
#h-date{flex:1.5}
.more{margin-top:10px}
.more summary{cursor:pointer;color:var(--accent-ink);font-size:13px;font-weight:800;
  user-select:none}
.actions{align-items:center;flex-wrap:wrap;margin-top:14px!important}
.link{color:var(--accent-ink);font-size:13px;font-weight:800;margin-left:auto;
  text-decoration:none}
.link:hover{text-decoration:underline}
#hist-form.editing #h-label{color:var(--accent-ink)}

/* ------------------------------------------------------ rows and cards */
.log,.cards{display:flex;flex-direction:column;gap:8px}
.logrow,.card{background:var(--panel);border:2px solid var(--line);border-radius:16px;
  padding:12px 14px;transition:border-color .12s,background-color .12s}
.logrow{display:flex;gap:10px;align-items:baseline;font-size:14px;font-weight:700;
  font-variant-numeric:tabular-nums}
.logrow .c{font-weight:800}
.logrow .m{margin-left:auto;color:var(--muted)}
.frow{cursor:pointer;flex-wrap:wrap;row-gap:2px}
.frow:hover,.card:hover,.brow:hover{border-color:var(--lip)}
.frow .d{color:var(--muted)}
.frow .sub,.brow .sub{flex-basis:100%;color:var(--muted);font-size:12.5px;font-weight:600;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.frow.editing{border-color:var(--accent-line);background:var(--accent-dim)}
/* Icon-only buttons: no fill, no lip. */
.frow .ed,.frow .x,.card .x,.gpop .gpop-x{min-height:0;margin:0;padding:0 4px;
  background:none;border:none;box-shadow:none;color:var(--faint);font-size:16px;
  line-height:1;letter-spacing:0;text-transform:none}
.frow .ed:active,.frow .x:active,.card .x:active,.gpop .gpop-x:active{transform:none}
.frow .ed:hover{color:var(--accent-ink)}
.frow .x:hover,.card .x:hover{color:var(--red)}

.card{cursor:pointer}
.card.sel{border-color:var(--accent-line);background:var(--accent-dim)}
.card.emerg{border-color:var(--red-line);background:var(--red-tint)}
.card .top{display:flex;align-items:baseline;gap:8px}
.card .cs{font-family:var(--mono);font-weight:700;font-size:16px}
.card .reg{font-family:var(--mono);font-size:12px;color:var(--muted)}
.card .x{margin-left:auto}
.phase{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 10px;border-radius:999px;margin-top:8px;
  background:var(--panel-2);color:var(--muted);border:2px solid var(--line)}
.phase.airborne{background:var(--accent-dim);color:var(--accent-ink);
  border-color:var(--accent-line)}
.phase.arrived,.phase.at_gate{background:var(--green-tint);color:var(--green-ink);
  border-color:var(--green-line)}
.phase.signal_lost{background:var(--amber-tint);color:var(--amber);
  border-color:var(--amber-line)}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0 0;
  font-variant-numeric:tabular-nums}
.metrics div{min-width:0}
.metrics dt{font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:var(--muted)}
.metrics dd{margin:2px 0 0;font-size:15px;font-weight:800}

.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:0}
.stats div{background:var(--panel);border:2px solid var(--line);border-radius:16px;
  padding:12px 14px;min-width:0}
.stats dt{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:800;
  letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
.stats dd{margin:4px 0 0;font-size:22px;font-weight:900;font-variant-numeric:tabular-nums}
.stats dd small{font-size:12px;font-weight:700;color:var(--muted);margin-left:3px}
.stats div:nth-child(1) .ico{color:var(--accent-ink)}
.stats div:nth-child(2) .ico{color:var(--gold-ink)}
.stats div:nth-child(3) .ico{color:var(--green-ink)}
.stats div:nth-child(4) .ico{color:var(--coral-ink)}

.feed{display:flex;flex-direction:column;gap:6px;max-height:320px;overflow-y:auto}
.ev{display:flex;gap:10px;padding:10px 12px;background:var(--panel);
  border:2px solid var(--line);border-radius:14px}
.ev.loud{border-color:var(--accent-line);background:var(--accent-dim)}
.ev.alarm{border-color:var(--red-line);background:var(--red-tint)}
.ev .t{font-size:12px;font-weight:700;color:var(--muted);flex:none;padding-top:1px;
  font-variant-numeric:tabular-nums}
.ev .b{min-width:0}
.ev .h{font-size:14px;font-weight:800}
.ev .d{font-size:13px;color:var(--muted)}
.ev .f{font-family:var(--mono);font-size:11px;color:var(--accent-ink)}

/* -------------------------------------------------------------- social */
.prow{align-items:center;gap:10px}
.av{width:32px;height:32px;border-radius:50%;flex:none;object-fit:cover;
  display:inline-flex;align-items:center;justify-content:center;
  background:var(--accent-dim);color:var(--accent-ink);font-size:13px;font-weight:900}
.prow .pn{display:flex;flex-direction:column;min-width:0;line-height:1.3;margin-right:auto}
.prow .pn b{font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prow .un{font-size:12px;font-weight:600;color:var(--muted);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.prow .st{font-size:12px;color:var(--muted)}
.prow button{min-height:36px;padding:4px 12px}
.brow{flex-wrap:wrap;row-gap:2px;cursor:pointer}
.brow.me{cursor:default;border-color:var(--accent-line);background:var(--accent-dim)}
.brow.open{border-color:var(--coral);background:var(--coral-tint)}
.brow .rank{width:26px;height:26px;flex:none;border-radius:50%;display:inline-flex;
  align-items:center;justify-content:center;font-size:12px;font-weight:900;
  color:var(--muted)}
.rank.medal.m1{background:var(--gold);color:var(--on-gold)}
.rank.medal.m2{background:#c9d3da;color:#2f3b43}
.rank.medal.m3{background:#e3a876;color:#4a2a0c}
.brow .ws{font-size:16px;font-weight:900;color:var(--gold-ink);
  font-variant-numeric:tabular-nums}
.brow .ws small{font-size:11px;font-weight:700;color:var(--muted);margin-left:3px}
.brow .sub{padding-left:36px}
table.h2h{width:100%;border-collapse:collapse;font-size:14px;font-weight:700;
  margin-bottom:14px;font-variant-numeric:tabular-nums}
table.h2h th{font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:var(--muted);text-align:center;padding:8px 6px}
table.h2h td{width:38%;padding:8px 6px;color:var(--muted)}
table.h2h td:first-child{text-align:right}
table.h2h td.lead{font-weight:900}
table.h2h td:first-child.lead{color:var(--accent-ink)}
table.h2h td:last-child.lead{color:var(--coral-ink)}

/* ------------------------------------------- map (dark in both themes) */
.mapwrap{flex:1;position:relative;min-width:0;margin:12px;border-radius:20px;
  overflow:hidden;background:#06090d}
#map{position:absolute;inset:0;background:#0a1016}
.leaflet-container{background:#0a1016;font-family:var(--sans)}
.maptools{position:absolute;top:12px;right:12px;z-index:500;display:flex;gap:8px;
  flex-wrap:wrap;justify-content:flex-end;max-width:calc(100% - 24px)}
.maptools button{min-height:38px;padding:4px 12px;background:var(--panel);color:var(--ink);
  border-color:var(--line);box-shadow:0 4px 0 var(--lip)}
.reg{display:flex;gap:8px}
.maptools .reg input{width:170px;min-height:38px;font-size:13px;padding:4px 10px;
  background:var(--panel)}
.viewtoggle{display:flex}
.viewtoggle[hidden]{display:none}
.viewtoggle button:first-child{border-radius:14px 0 0 14px}
.viewtoggle button:last-child{border-radius:0 14px 14px 0;border-left:none}
.viewtoggle button.on{background:var(--accent);color:var(--on-accent);
  border-color:transparent;box-shadow:0 4px 0 var(--accent-lip)}

#globe{position:absolute;inset:0;overflow:hidden;
  background:radial-gradient(ellipse at 50% 45%,#0c1622 0%,#06090d 70%)}
#globe canvas{display:block;cursor:grab;touch-action:none}
#globe canvas:active{cursor:grabbing}
.goverlay{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.gmark{position:absolute;left:0;top:0;width:0;height:0;pointer-events:auto;cursor:pointer}
.gmark svg{position:absolute;transform-origin:center;
  filter:drop-shadow(0 0 5px rgba(79,182,194,.55))}
.gmark.tracked svg{left:-15px;top:-15px}
.gmark.near svg{left:-9px;top:-9px;filter:none}
.gmark.near{z-index:1}
.gmark.tracked{z-index:2}
.gmark .tag{position:absolute;left:18px;top:-10px}
.gmark.sel .tag{border-color:var(--accent);color:var(--accent)}
.gdot{position:absolute;left:-3px;top:-3px;width:6px;height:6px;border-radius:50%;
  background:#dff7fa;box-shadow:0 0 6px 2px rgba(95,208,221,.7);pointer-events:auto}
.gdot .tag{position:absolute;left:10px;top:-8px;opacity:.9}
.gdot.mate{background:#fde3da;box-shadow:0 0 6px 2px rgba(240,138,107,.7)}
.gpop{position:absolute;left:0;top:0;z-index:3;pointer-events:auto;background:var(--panel);
  border:2px solid var(--line);border-radius:16px;padding:12px 30px 10px 14px;
  white-space:nowrap;box-shadow:var(--shadow)}
.gpop button{margin-top:8px;min-height:36px;padding:4px 12px}
.gpop .gpop-x{position:absolute;top:6px;right:6px;margin:0;padding:2px 6px}
.gpop .gpop-x:hover{color:var(--ink)}

.plane{transform-origin:center;transition:transform .5s linear}
.tag{font-family:var(--mono);font-size:11px;background:rgba(12,23,28,.9);color:#f1f7fb;
  padding:2px 7px;border-radius:8px;border:2px solid #37464f;white-space:nowrap}
.leaflet-popup-content-wrapper{background:var(--panel);color:var(--ink);border-radius:16px;
  border:2px solid var(--line);box-shadow:var(--shadow)}
.leaflet-popup-tip{background:var(--panel);border:2px solid var(--line)}
.pop{font-size:13px;font-weight:700;line-height:1.7}
.pop b{font-family:var(--mono);font-size:15px;color:var(--accent-ink)}

.toast{position:absolute;bottom:20px;left:50%;transform:translateX(-50%) translateY(20px);
  background:var(--panel);color:var(--ink);border:2px solid var(--accent-line);
  padding:12px 18px;border-radius:16px;font-size:14px;font-weight:700;opacity:0;
  pointer-events:none;box-shadow:var(--shadow);transition:opacity .2s,transform .2s;
  z-index:600;max-width:80%}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.bad{border-color:var(--red-line);color:var(--red)}

/* -------------------------------------------------------- account menu */
.acct{position:relative}
.acct summary{display:flex;align-items:center;gap:8px;cursor:pointer;list-style:none;
  border-radius:999px}
.acct summary::-webkit-details-marker{display:none}
.acct .av{width:30px;height:30px;font-size:12px}
.acct .menu{position:absolute;right:0;top:calc(100% + 12px);z-index:700;width:240px;
  display:flex;flex-direction:column;gap:8px;padding:14px;background:var(--panel);
  border:2px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}
.acct .menu p{margin:0;font-size:13px;color:var(--muted);line-height:1.45}
.acct .menu form{display:flex;flex-direction:column;gap:8px}
.acct .menu form[hidden]{display:none}
.acct .menu input{width:100%;flex:none}

/* ---------------------------------------- sign-in and username pages */
body.gate{display:flex;align-items:center;justify-content:center;overflow:auto;
  padding:16px}
.gatebox{display:block;height:auto;width:min(420px,100%);padding:32px 28px;
  background:var(--panel);border:2px solid var(--line);border-radius:20px}
.gatebox h1{font-size:24px;font-weight:900;margin:20px 0 22px;line-height:1.25}
.gatebox .hint{margin:14px 0 0}
.gatebtn{display:flex;align-items:center;justify-content:center;min-height:48px;
  font-size:14px;text-decoration:none}
.gatebox #out{margin-top:22px}

/* ------------------------------------------------------- small screens */
@media (max-width:860px){
  body{overflow:auto}
  .bar{height:auto;min-height:60px;padding:8px 12px;row-gap:6px}
  main{flex-direction:column;height:auto;overflow:visible}
  .side{width:100%;border-right:none;border-bottom:2px solid var(--line);overflow:visible}
  .mapwrap{height:60vh;flex:none}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{transition:none!important;animation:none!important}
}
```

- [ ] **Step 4: Run the stylesheet tests**

Run: `.venv/bin/python -m unittest tests.test_frontend -v`
Expected: all PASS. If a contrast pair fails, adjust that token's value in every place it is defined (it may be in `:root`, the dark block and `.mapwrap`) and rerun. Do not edit `PAIRS`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 6: Look at it once in the browser**

Start the dev server with the preview tool, configuration name `wingmates-dev` (from `.claude/launch.json`, port 8817). Never start it with Bash. Open the page, take one screenshot in light and one in dark (`resize_window` with `colorScheme`). You are checking only that the page is not broken: sidebar on the left, map on the right, buttons have a lip. Detailed checks come in Task 5. Read the console and confirm no errors.

- [ ] **Step 7: Commit**

```bash
git add public/static/style.css tests/test_frontend.py
git commit -m "Rewrite the stylesheet as a light and dark playful theme

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Icons and rank badges

**Files:**
- Modify: `web/index.html` (sprite after `<body>`; the three tab buttons; the Import CSV button)
- Modify: `public/static/history.js` (the `$('h-stats').innerHTML` template in `renderHistory`)
- Modify: `public/static/social.js` (the `row.innerHTML` template in the `everyone.forEach` loop)
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `.ico` and `.rank.medal.m1/.m2/.m3` from Task 2; `PAGES`, `SCRIPTS` from Task 1.
- Produces: sprite symbol ids `i-plane`, `i-mates`, `i-radar`, `i-route`, `i-pin`, `i-globe`, `i-upload`. Use one with `<svg class="ico" aria-hidden="true"><use href="#i-plane"/></svg>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_frontend.py`, above the `if __name__` line:

```python
# Buttons whose text a script replaces with textContent; an icon inside
# one of these would disappear after the first click.
REWRITTEN_BUTTONS = ("h-add", "h-cancel", "add-btn", "btn-nearby", "btn-refresh")


class TestIcons(unittest.TestCase):

    def test_every_icon_used_is_in_the_sprite(self):
        index = PAGES["index.html"]
        defined = set(re.findall(r'<symbol id="(i-[\w-]+)"', index))
        self.assertEqual(defined, {"i-plane", "i-mates", "i-radar", "i-route",
                                   "i-pin", "i-globe", "i-upload"})
        used = set(re.findall(r'href="#(i-[\w-]+)"', index))
        for js in SCRIPTS.values():
            used |= set(re.findall(r'href="#(i-[\w-]+)"', js))
        self.assertEqual(used, defined)

    def test_icons_are_hidden_from_screen_readers(self):
        for name, text in {**PAGES, **SCRIPTS}.items():
            for tag in re.findall(r'<svg class="ico"[^>]*>', text):
                with self.subTest(file=name, tag=tag):
                    self.assertIn('aria-hidden="true"', tag)

    def test_no_icon_sits_in_a_button_a_script_rewrites(self):
        index = PAGES["index.html"]
        for button_id in REWRITTEN_BUTTONS:
            body = re.search(r'<button[^>]*id="%s"[^>]*>(.*?)</button>' % button_id,
                             index, re.S).group(1)
            with self.subTest(button=button_id):
                self.assertNotIn("<svg", body)

    def test_the_top_three_ranks_get_a_medal(self):
        self.assertIn("' medal m' + (i + 1)", SCRIPTS["social.js"])
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest tests.test_frontend.TestIcons -v`
Expected: `test_every_icon_used_is_in_the_sprite` and `test_the_top_three_ranks_get_a_medal` FAIL. The other two pass already and guard later edits.

- [ ] **Step 3: Add the sprite to `web/index.html`**

Directly after the `<body>` line:

```html
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="i-plane" viewBox="0 0 24 24"><path d="M21 3 3 10.5l7 2.5 2.5 7L21 3z"/><path d="M10 13 21 3"/></symbol>
  <symbol id="i-mates" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-4 3-6 6.5-6s6 2 6.5 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M18 14c2 .5 3.5 2 4 5"/></symbol>
  <symbol id="i-radar" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 12 18.5 5.5"/></symbol>
  <symbol id="i-route" viewBox="0 0 24 24"><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="6" r="2.5"/><path d="M7 16.5C10 8 14 14 17 7.5"/></symbol>
  <symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.5"/></symbol>
  <symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3 3 15 0 18c-3-3-3-15 0-18z"/></symbol>
  <symbol id="i-upload" viewBox="0 0 24 24"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></symbol>
</svg>
```

- [ ] **Step 4: Put icons in the tabs and the Import button**

In `web/index.html`, replace the three tab buttons with:

```html
      <button role="tab" id="tab-history" class="on"><svg class="ico" aria-hidden="true"><use href="#i-plane"/></svg>My flights</button>
      <button role="tab" id="tab-social"><svg class="ico" aria-hidden="true"><use href="#i-mates"/></svg>Social<span class="badge" id="social-badge" hidden></span></button>
      <button role="tab" id="tab-live" class="live-only"><svg class="ico" aria-hidden="true"><use href="#i-radar"/></svg>Live</button>
```

and the Import button with:

```html
          <button type="button" id="h-import"><svg class="ico" aria-hidden="true"><use href="#i-upload"/></svg> Import CSV</button>
```

- [ ] **Step 5: Put icons in the totals tiles**

In `public/static/history.js`, in `renderHistory`, replace the `$('h-stats').innerHTML = ...` statement with the one below. Write the four `<svg>` tags out in full, as shown; the test finds icon ids by the literal text `href="#i-…"`, so do not build them with a helper function.

```js
  $('h-stats').innerHTML = `
    <div><dt><svg class="ico" aria-hidden="true"><use href="#i-plane"/></svg>Flights</dt><dd>${fmt(s.flights)}</dd></div>
    <div><dt><svg class="ico" aria-hidden="true"><use href="#i-route"/></svg>Distance</dt><dd>${fmt(s.distance_mi)}<small>mi</small></dd></div>
    <div><dt><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>Airports</dt><dd>${fmt(s.airports)}</dd></div>
    <div><dt><svg class="ico" aria-hidden="true"><use href="#i-globe"/></svg>Countries</dt><dd>${fmt(s.countries)}</dd></div>`;
```

- [ ] **Step 6: Give the top three ranks a medal**

In `public/static/social.js`, in the `everyone.forEach((p, i) => {` loop, change the first line of the `row.innerHTML` template from

```js
    row.innerHTML = `<span class="rank">${i + 1}</span>${person(p)}
```

to

```js
    row.innerHTML = `<span class="rank${i < 3 ? ' medal m' + (i + 1) : ''}">${i + 1}</span>${person(p)}
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 8: Check in the browser**

With `wingmates-dev` running, reload. Confirm with `read_page` and one screenshot: each tab shows an icon and its label; the four totals tiles each show a coloured icon; clicking "Add flight" with empty fields does not remove any icon. Open the Social tab: your own row shows a gold "1" badge. No console errors.

- [ ] **Step 9: Commit**

```bash
git add web/index.html public/static/history.js public/static/social.js tests/test_frontend.py
git commit -m "Add tab and totals icons and medal badges for the top three

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Friendlier copy

**Files:**
- Modify: `web/index.html` (label, hints, empty states)
- Modify: `public/static/history.js` (`exitEdit` label reset; the two success hints in the submit handler)
- Modify: `public/static/social.js` (accept message)
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `PAGES`, `SCRIPTS` from Task 1.
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_frontend.py`, above the `if __name__` line:

```python
class TestCopy(unittest.TestCase):

    def test_empty_states_invite_the_next_step(self):
        index = PAGES["index.html"]
        for line in ("No flights yet. Where to first?",
                     "No mates yet. Find one by username and see who has flown further.",
                     "All quiet. Alerts show up here when a flight changes state."):
            with self.subTest(line=line):
                self.assertIn(line, index)

    def test_the_form_label_is_the_same_before_and_after_an_edit(self):
        on_page = re.search(r'id="h-label">([^<]+)<', PAGES["index.html"]).group(1)
        reset_to = re.findall(r"\$\('h-label'\)\.textContent = '([^']+)'",
                              SCRIPTS["history.js"])
        self.assertIn(on_page, reset_to)
        self.assertEqual(on_page, "Log a flight")

    def test_copy_has_no_exclamation_marks(self):
        visible = re.sub(r"<script.*?</script>|<[^>]+>", " ",
                         PAGES["index.html"], flags=re.S)
        self.assertNotIn("!", visible)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest tests.test_frontend.TestCopy -v`
Expected: the first two FAIL; the third passes and is a guard.

- [ ] **Step 3: Change the copy in `web/index.html`**

Make exactly these replacements (old text, then new text):

| Old | New |
|---|---|
| `<label for="h-from" id="h-label">Add a flight</label>` | `<label for="h-from" id="h-label">Log a flight</label>` |
| `Airport codes and a date are all you need.` | `Two airport codes and a date, that's it.` |
| `No flights yet. Add your first one above.` | `No flights yet. Where to first?` |
| `No mates yet. Find one by username above.` | `No mates yet. Find one by username and see who has flown further.` |
| `Nothing tracked yet. Use “Nearby” on the` | `Nothing tracked yet. Tap “Nearby” on the` |
| `map to find a live callsign, then track it.` | `map to spot a live callsign, then track it.` |
| `Alerts appear here as flights change state.` | `All quiet. Alerts show up here when a flight changes state.` |

The `h-hint` paragraph keeps its second sentence ("For a CSV, dates are YYYY-MM-DD.").

- [ ] **Step 4: Change the copy in the scripts**

In `public/static/history.js`:

- In `exitEdit`, change `$('h-label').textContent = 'Add a flight';` to `$('h-label').textContent = 'Log a flight';`
- In the form submit handler, change

```js
      hint(`Added ${f.from.iata} → ${f.to.iata}, ${fmt(f.distance_mi, ' mi')}.`);
```

to

```js
      hint(`Logged ${f.from.iata} → ${f.to.iata}, ${fmt(f.distance_mi, ' mi')}. Nice one.`);
```

In `public/static/social.js`, change `` `You and @${p.username} are mates.` `` to `` `You and @${p.username} are mates now.` ``

Leave every error message as it is.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add web/index.html public/static/history.js public/static/social.js tests/test_frontend.py
git commit -m "Make labels, hints and empty states friendlier

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Check every screen in the browser and fix what is off

No new files. This task is where the look is judged by eye; the CSS in Task 2 was written without a browser, so expect to adjust spacing and sizes. Any fix must keep every test in `tests/test_frontend.py` passing and must use tokens, never a new hard-coded colour outside the map rules.

**Files:**
- Modify (only if a check fails): `public/static/style.css`

**Interfaces:**
- Consumes: everything from Tasks 1 to 4.

- [ ] **Step 1: Start the app and add data**

Start `wingmates-dev` with the preview tool. In the page:

1. Add three flights: `ATL` to `LHR`, `LHR` to `NRT`, `NRT` to `SFO`, any dates. Under "More details" on one of them, enter notes of at least 80 characters.
2. In the header's "dev: switch user" box, type `a_very_long_username1` (20 characters) and press Enter. Add one flight as that user. In Social, find your first user by username and send a request.
3. Switch back to the first user, open Social, accept the request, then click the mate's row to open the head-to-head.

- [ ] **Step 2: Check light theme at desktop width**

`resize_window` with `preset: "desktop"` and `colorScheme: "light"`. For each of the My flights and Social tabs take a screenshot and confirm:

- Sidebar is white, the map is a dark rounded panel with a margin around it.
- Buttons have a visible lip and move down when pressed.
- Totals tiles, flight rows and leaderboard rows have 2px borders and rounded corners; nothing is clipped or overlapping.
- Leaderboard: medals on ranks 1 and 2, your own row tinted blue, the open mate's row tinted coral, wingspan numbers in gold.
- The long notes line ends in an ellipsis. The 20-character username ends in an ellipsis or fits; the row does not wrap badly.
- Click a flight row so the map shows it; a toast or popup over the map is a dark card with light text.
- Click the edit pencil on a flight: the row is tinted and the form label reads "Edit flight"; Cancel returns it to "Log a flight".

- [ ] **Step 3: Check dark theme at desktop width**

`resize_window` with `colorScheme: "dark"`. Repeat the Step 2 screenshots. Also confirm the date field's calendar icon is visible (it follows the theme).

- [ ] **Step 4: Check at phone width, both themes**

`resize_window` with `preset: "mobile"`, then reload. For light and for dark, on each tab, run in `javascript_tool`:

```js
document.documentElement.scrollWidth <= window.innerWidth
```

Expected: `true` every time. Take one screenshot per theme. The sidebar is stacked above the map and the three tabs fit on one line. Finish with `resize_window` `preset: "desktop"`.

- [ ] **Step 5: Check the Live tab**

The Live tab is hidden when live tracking is off. Stop `wingmates-dev` and start the `wingmates` configuration. If the Live tab appears, open it and check the form, the three empty states and the map tool buttons (Nearby, Clear, Poll now, the registration box) in light and dark. If it does not appear, or the feed is unreachable, say so plainly in your report rather than claiming it was checked.

- [ ] **Step 6: Check the gate pages**

Open `http://localhost:8817/login` and `http://localhost:8817/welcome` directly in light and dark. If a route redirects or returns 404 in this mode, open the file's markup by starting the `wingmates-google` configuration instead; if that needs credentials you do not have, report that the gate pages were checked by reading the CSS only. Expected: a centred card with a 2px border, the brand, a heading, and a full-width primary button on the sign-in page.

- [ ] **Step 7: Check with the font blocked**

In `javascript_tool`, run:

```js
document.querySelectorAll('link[href*="fonts.googleapis"]').forEach(l => l.remove());
getComputedStyle(document.body).fontFamily
```

Take a screenshot. Expected: text is in a system rounded or sans face, and no row, tab or button overflows.

- [ ] **Step 8: Read the console**

`read_console_messages` with `onlyErrors: true`. Expected: none caused by this work.

- [ ] **Step 9: Fix, retest, commit**

Fix anything the checks found in `public/static/style.css`, repeating the check that failed. Then:

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add public/static/style.css
git commit -m "Tune spacing and sizes after checking every screen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If nothing needed fixing, skip the commit and say so.

- [ ] **Step 10: Report**

Tell Brett: what was checked, what was changed in this task, anything that could not be checked (Live tab, gate pages) and why, and attach the light and dark desktop screenshots of My flights and Social. Do not merge or push; that is Brett's call.

---

## After this plan

Gamification (streaks, XP, achievements, leagues) is a separate project. It needs its own brainstorm, spec and plan, and should start only after this branch is reviewed.
