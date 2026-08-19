import json
import re
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = REPO_ROOT / "main_site" / "econcausal"
HTML_PATH = PAGE_ROOT / "index.html"
CSS_PATH = PAGE_ROOT / "styles.css"
SCRIPT_PATH = PAGE_ROOT / "script.js"
DATA_PATH = PAGE_ROOT / "data" / "paper-data.v1.json"
OG_IMAGE_PATH = PAGE_ROOT / "assets" / "og-card.png"


class _ReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        for name in ("href", "src"):
            if attributes.get(name):
                self.references.append(attributes[name])


class EconCausalPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")
        cls.data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_canonical_metadata_and_public_resources(self):
        expected = (
            "https://econai.kaist.ac.kr/econcausal/",
            "https://arxiv.org/abs/2510.07231",
            "EconCausal: A Context-Aware Economic Reasoning Benchmark",
            "Preprint",
            "Submitted to EMNLP 2026",
        )
        for value in expected:
            self.assertIn(value, self.html)
        self.assertIn('rel="canonical"', self.html)
        self.assertIn('property="og:image"', self.html)
        self.assertIn('type="application/ld+json"', self.html)

    def test_text_light_page_has_both_comparison_modes_and_core_surfaces(self):
        for value in (
            'data-view-mode="explore"',
            'data-view-mode="results"',
            'id="context-lab"',
            'id="model-chart"',
            'id="transfer-chart"',
            'id="sign-chart"',
            'id="calibration-chart"',
            'id="model-detail-dialog"',
        ):
            self.assertIn(value, self.html)
        self.assertRegex(self.html, r'<main\b')
        self.assertRegex(self.html, r'class="[^"]*skip-link')

    def test_no_runtime_framework_or_third_party_cdn(self):
        combined = f"{self.html}\n{self.script}"
        for forbidden in (
            "unpkg.com",
            "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com",
            "react.production",
            "vue.global",
            "d3.min.js",
        ):
            self.assertNotIn(forbidden, combined)

    def test_local_links_and_assets_resolve(self):
        parser = _ReferenceParser()
        parser.feed(self.html)
        parser.close()
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for reference in parser.references:
            parsed = urlparse(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("#", "mailto:")):
                continue
            target = (PAGE_ROOT / parsed.path).resolve()
            if parsed.path.startswith("../"):
                target = (PAGE_ROOT / parsed.path).resolve()
            self.assertTrue(target.exists(), f"missing local reference: {reference}")

    def test_interactions_are_keyboard_and_motion_aware(self):
        for value in (
            "aria-pressed",
            "showModal",
            "focus()",
            "Escape",
            "prefers-reduced-motion",
        ):
            self.assertIn(value, f"{self.html}\n{self.css}\n{self.script}")
        self.assertNotIn("overflow-x: auto", self.css)
        self.assertNotIn("overflow-x:auto", self.css)

    def test_authoritative_dataset_shape_and_headline_numbers(self):
        self.assertEqual(self.data["stats"]["causal_triplets"], 10490)
        self.assertEqual(self.data["stats"]["source_papers"], 2595)
        self.assertEqual([task["instances"] for task in self.data["tasks"]], [1807, 284, 852])
        self.assertEqual(len(self.data["models"]), 18)
        self.assertEqual(len({model["id"] for model in self.data["models"]}), 18)
        self.assertEqual(len(self.data["examples"]), 8)

        group_averages = {row["id"]: row for row in self.data["group_averages"]}
        closed = group_averages["closed_source"]["metrics"]
        opened = group_averages["open_source"]["metrics"]
        self.assertAlmostEqual(closed["task2_overall"]["accuracy"] * 100, 73.9)
        self.assertAlmostEqual(closed["task2_sign_mismatch"]["accuracy"] * 100, 41.3)
        self.assertAlmostEqual(opened["task2_overall"]["accuracy"] * 100, 65.4)
        self.assertAlmostEqual(opened["task2_sign_mismatch"]["accuracy"] * 100, 31.8)

        sign_accuracy = self.data["sign_accuracy"]["mean_across_tasks"]
        self.assertAlmostEqual(sign_accuracy["none"], 13.83)
        self.assertAlmostEqual(sign_accuracy["mixed"], 22.82)

    def test_bespoke_social_card_is_present(self):
        self.assertTrue(OG_IMAGE_PATH.is_file())
        self.assertGreater(OG_IMAGE_PATH.stat().st_size, 100_000)

    def test_page_data_validator_passes(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "validate_econcausal_data.py")],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
