from pathlib import Path

from django.test import SimpleTestCase


class StaticAssetTests(SimpleTestCase):
    def test_hidden_attribute_rule_is_present_in_lcars_styles(self):
        css_path = Path(__file__).resolve().parents[1] / "static" / "css" / "lcars.css"
        css = css_path.read_text()

        self.assertIn("[hidden]", css)
        self.assertIn("display: none !important;", css)

    def test_base_template_preserves_htmx_error_swap_and_csrf_behavior(self):
        app_dir = Path(__file__).resolve().parents[1]
        template = (app_dir / "templates" / "base.html").read_text()

        self.assertIn('"noSwap":[204,304,"4xx","5xx"]', template)
        self.assertIn('data-csrf-token="{{ csrf_token }}"', template)
        self.assertIn("hx-headers:inherited", template)

    def test_direct_fetch_scripts_read_the_dedicated_csrf_attribute(self):
        js_dir = Path(__file__).resolve().parents[1] / "static" / "js"

        for filename in ("mark-read.js", "new-post.js", "photo-edit-page.js"):
            with self.subTest(filename=filename):
                javascript = (js_dir / filename).read_text()
                self.assertIn("document.body.dataset.csrfToken", javascript)
                self.assertNotIn("getAttribute('hx-headers')", javascript)
