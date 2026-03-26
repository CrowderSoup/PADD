from pathlib import Path

from django.test import SimpleTestCase


class StaticAssetTests(SimpleTestCase):
    def test_hidden_attribute_rule_is_present_in_lcars_styles(self):
        css_path = Path(__file__).resolve().parents[1] / "static" / "css" / "lcars.css"
        css = css_path.read_text()

        self.assertIn("[hidden]", css)
        self.assertIn("display: none !important;", css)
