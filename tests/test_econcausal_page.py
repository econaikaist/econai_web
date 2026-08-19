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
HERO_FIGURE_PATH = PAGE_ROOT / "assets" / "figure-1-overview.png"


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

    def test_text_light_page_has_grouped_benchmark_and_no_removed_surfaces(self):
        combined = f"{self.html}\n{self.script}"
        for value in (
            'id="family-chart"',
            'id="family-prev"',
            'id="family-next"',
            'id="family-status"',
            'id="model-detail-dialog"',
            "data-family-panel",
            "data-accuracy-bar",
        ):
            self.assertIn(value, combined)
        for removed in (
            'id="context-lab"',
            'id="calibration-chart"',
            'data-view-mode="explore"',
            'data-view-mode="results"',
            "Context Lab",
            "Context lab",
        ):
            self.assertNotIn(removed, combined)
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
            "showModal",
            "focus()",
            "Escape",
            ":focus-visible",
            "prefers-reduced-motion",
        ):
            self.assertIn(value, f"{self.html}\n{self.css}\n{self.script}")
        self.assertNotRegex(
            self.css,
            r"(?:html|body)[^{]*\{[^}]*overflow-x\s*:\s*auto",
        )

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

    def test_grouped_benchmark_contract_has_five_families_and_72_accuracy_bars(self):
        task_order = (
            "task1_econ",
            "task1_finance",
            "task2_overall",
            "task3",
        )
        families = {model["family"] for model in self.data["models"]}
        self.assertEqual(families, {"Gemini", "OpenAI", "Grok", "Llama", "Qwen"})
        self.assertEqual(len(families), 5)
        self.assertEqual(len(self.data["models"]) * len(task_order), 72)
        for model in self.data["models"]:
            self.assertEqual(
                tuple(key for key in task_order if key in model["metrics"]),
                task_order,
                model["id"],
            )
            for task_id in task_order:
                accuracy = model["metrics"][task_id]["accuracy"]
                self.assertGreaterEqual(accuracy, 0, f"{model['id']}/{task_id}")
                self.assertLessEqual(accuracy, 1, f"{model['id']}/{task_id}")

    def test_construction_pipeline_and_paper_figure_are_present(self):
        for value in (
            'id="construction"',
            "Consensus extraction",
            "Context refinement",
            "Conservative filter",
            "27.3%",
            "2,943 evaluations",
            'id="figure-dialog"',
        ):
            self.assertIn(value, self.html)
        self.assertTrue(HERO_FIGURE_PATH.is_file())
        self.assertGreater(HERO_FIGURE_PATH.stat().st_size, 100_000)

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
