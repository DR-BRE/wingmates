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

    def test_the_focus_ring_stands_out_from_every_surface(self):
        ring = re.search(r"focus-visible[^{]*\{\s*outline:3px solid var\((--[\w-]+)\)", CSS).group(1)
        for theme, t in (("light", self.light), ("dark", self.dark)):
            for surface in ("--panel", "--bg", "--accent-dim"):
                with self.subTest(theme=theme, on=surface):
                    self.assertGreaterEqual(contrast(t[ring], t[surface]), 3)

    def test_a_long_name_shrinks_before_the_wingspan_wraps(self):
        rule = block(CSS, CSS.index(".brow .pn{"))
        self.assertRegex(rule, r"flex:\s*1 1 0")

    def test_the_old_theme_is_gone(self):
        for old in ("#080c11", "#0e151d", "#17414a", "#15434c", "#4fb6c2"):
            with self.subTest(colour=old):
                self.assertNotIn(old, CSS)


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


if __name__ == "__main__":
    unittest.main()
