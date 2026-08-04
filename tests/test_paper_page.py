import hashlib
import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = REPO_ROOT / "main_site/ideological-bias-in-llms"
HTML_PATH = PAGE_ROOT / "index.html"
DATA_PATH = PAGE_ROOT / "data/paper-data.v2.json"
SUBFIELDS_SHA256 = "fbc53a88880b7340d4e635e80488d9776d608df1f126b004a4b04562f787457a"


class PaperPageStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.css = (PAGE_ROOT / "styles.css").read_text(encoding="utf-8")
        cls.data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_public_arxiv_v2_model_baseline(self):
        models = self.data["models"]
        self.assertEqual(self.data["dataset_version"], "arxiv-v2-20-models")
        self.assertEqual(len(models), 20)
        self.assertEqual(len({model["id"] for model in models}), 20)
        self.assertTrue(all(model["reported_in_paper"] is True for model in models))
        self.assertFalse(any("opus-4-8" in model["id"].lower() for model in models))
        for model in models:
            for field in ("source", "evaluation_date", "release_date", "release_date_source"):
                self.assertIn(field, model)

    def test_release_chart_has_twenty_primary_sourced_points(self):
        models = self.data["models"]
        self.assertEqual(sum(bool(model["release_date"]) for model in models), 20)
        for model in models:
            self.assertRegex(model["release_date"], r"^\d{4}-\d{2}-\d{2}$")
            source = model["release_date_source"]
            self.assertTrue(source["title"])
            self.assertTrue(source["url"].startswith("https://"))

    def test_drawer_and_compare_data_are_complete(self):
        models = self.data["models"]
        for model in models:
            self.assertEqual(
                set(model["overview"]),
                {
                    "non_contested_accuracy",
                    "contested_accuracy",
                    "intervention_accuracy",
                    "market_accuracy",
                    "accuracy_gap_pp",
                    "b_dir_pct",
                },
            )
            for side in ("intervention_truth", "market_truth"):
                self.assertEqual(
                    set(model["icl"][side]),
                    {"none", "non_contested", "intervention_ex", "market_ex", "delta_example"},
                )
        self.assertEqual({example["case_id"] for example in self.data["examples"]}, {"t1_9849", "t1_515"})
        for example in self.data["examples"]:
            self.assertEqual(len(example["model_outputs"]), 20)
            self.assertTrue(example["paper_url"].startswith("https://"))

    def test_section_order_and_no_standalone_icl_or_example_section(self):
        markers = [
            'class="hero section-shell"',
            'id="motivation"',
            'id="benchmark"',
            'id="findings"',
            'id="release-bias"',
            'aria-labelledby="subfields-heading"',
            'id="citation"',
        ]
        positions = [self.html.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertNotRegex(self.html, r"<section[^>]+id=\"(?:icl|examples)\"")

    def test_subfields_dom_is_byte_identical_to_baseline(self):
        match = re.search(
            r'        <section class="content-section section-shell" aria-labelledby="subfields-heading">.*?        </section>\n',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()
        self.assertEqual(digest, SUBFIELDS_SHA256)

    def test_progressive_core_and_existing_resources_remain(self):
        self.assertEqual(self.html.count('class="model-score-row'), 20)
        for value in ("10,490", "1,056", "751", "15 / 20", "+20.9", "−1.0"):
            self.assertIn(value, self.html)
        for value in (
            'href="assets/paper.pdf"',
            'href="https://arxiv.org/abs/2604.21334"',
            'content="https://econai.kaist.ac.kr/ideological-bias-in-llms/assets/og-card.png"',
            'data-copy-target="bibtex"',
        ):
            self.assertIn(value, self.html)

    def test_accessible_interaction_scaffolding(self):
        for value in (
            '<dialog id="model-detail-dialog"',
            'role="tablist"',
            'aria-live="polite"',
            'id="compare-tray"',
            'id="release-chart"',
            'type="module" src="script.js"',
        ):
            self.assertIn(value, self.html)

    def test_reduced_motion_keeps_core_controls_available(self):
        reduced_motion = self.css.split("@media (prefers-reduced-motion: reduce)", 1)[1].split(
            "@media print", 1
        )[0]
        self.assertNotIn("display: none", reduced_motion)
        for selector in (
            ".model-detail-dialog",
            ".compare-tray",
            ".model-open-button",
            ".release-point-button",
        ):
            self.assertIn(selector, reduced_motion)
        self.assertIn("transition: none !important", reduced_motion)
        self.assertIn("animation: none !important", reduced_motion)


if __name__ == "__main__":
    unittest.main()
