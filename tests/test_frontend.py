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
