import hashlib
import html as html_lib
import importlib.util
import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = REPO_ROOT / "main_site/ideological-bias-in-llms"
HTML_PATH = PAGE_ROOT / "index.html"
CSS_PATH = PAGE_ROOT / "styles.css"
EXPLORER_PATH = PAGE_ROOT / "modules/paper-explorer.v2.js"
DATA_PATH = PAGE_ROOT / "data/paper-data.v2.json"

EXPECTED_MODEL_IDS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5-nano",
    "gpt-5-mini",
    "gpt-5-2",
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "gemini-2-5-flash",
    "gemini-3-flash",
    "grok-3-mini",
    "grok-3",
    "grok-4-1-fast",
    "llama-3-1-8b",
    "llama-3-2-1b",
    "llama-3-2-3b",
    "llama-3-3-70b",
    "qwen-3-8b",
    "qwen-3-14b",
    "qwen-3-32b",
)

EXPECTED_B_DIR = {
    "gpt-4o-mini": 15.5,
    "gpt-4o": 7.8,
    "gpt-5-nano": 9.9,
    "gpt-5-mini": 2.8,
    "gpt-5-2": -2.6,
    "claude-haiku-4-5": 1.4,
    "claude-sonnet-4-6": -8.7,
    "claude-opus-4-6": -8.7,
    "gemini-2-5-flash": 6.5,
    "gemini-3-flash": -6.0,
    "grok-3-mini": 13.5,
    "grok-3": 4.7,
    "grok-4-1-fast": 1.8,
    "llama-3-1-8b": -1.0,
    "llama-3-2-1b": 1.9,
    "llama-3-2-3b": 6.8,
    "llama-3-3-70b": 17.9,
    "qwen-3-8b": 17.7,
    "qwen-3-14b": 8.0,
    "qwen-3-32b": 10.1,
}

EXPECTED_SUBFIELDS = (
    ("healthcare", "Healthcare"),
    ("welfare_redistribution", "Welfare & Redistribution"),
    ("education", "Education"),
    ("labor", "Labor"),
    ("financial_regulation", "Financial Regulation"),
    ("trade", "Trade"),
    ("taxation", "Taxation"),
)

EXPECTED_AGGREGATE_SUBFIELDS = (
    ("Healthcare", 91.0, 70.17241379310345, 49.24137931034483, 20.9),
    (
        "Welfare & redistribution",
        87.0,
        79.49029126213594,
        61.523809523809526,
        18.0,
    ),
    ("Education", 56.0, 75.17964071856287, 64.5945945945946, 10.6),
    ("Labor", 183.0, 70.27675276752767, 60.87855297157623, 9.4),
    (
        "Financial regulation",
        172.0,
        69.52830188679245,
        61.33064516129032,
        8.2,
    ),
    ("Trade", 30.0, 63.68421052631579, 58.7037037037037, 5.0),
    ("Taxation", 73.0, 66.82051282051282, 67.83216783216782, -1.0),
)

EXPECTED_CONTEXTS = {
    "t1_9849": (
        "This paper studies Brazil’s labor market and wage inequality over 1985–2014 "
        "with a focus on 1996–2012, using administrative linked employer–employee data "
        "(RAIS) and household surveys (PNAD, PME). Units include male workers aged 18–54, "
        "firms, and state-year aggregates. The institutional setting is Brazil’s federal "
        "minimum wage, which rose sharply from 1996 to 2012 and applied uniformly across "
        "states but varied in effective bindingness by local wage distributions. Analyses "
        "combine firm-worker decompositions, cross-state panel regressions, and a structural "
        "equilibrium model."
    ),
    "t1_515": (
        "This empirical study analyzes how hospital competition affected Medicare "
        "beneficiaries' AMI (heart attack) care in the United States from 1985–1994. It uses "
        "patient-level data on nonrural elderly Medicare beneficiaries hospitalized for new "
        "AMI events, matched to American Hospital Association hospital characteristics and "
        "state HMO enrollment rates. The institutional setting includes Medicare reimbursement "
        "regimes and rising managed-care penetration; the authors exploit exogenous determinants "
        "of hospital choice (travel distances) and changes in local hospital markets to assess "
        "impacts on treatment intensity, Medicare inpatient spending, and one-year mortality and "
        "cardiac rehospitalizations."
    ),
}

EXPECTED_EXAMPLE_OUTPUT_SHA256 = {
    "t1_9849": "fd77df40d64ffcd940d2d17cde0313e0e758504b896e7aa081d69f10b267f022",
    "t1_515": "8ebd153699f67b89c24fe0f4ecc8bac3673fac0438c5cd2068524378c7fc16ad",
}

B_DIR_DEFINITION = (
    "100 × (intervention-leaning errors - market-leaning errors) / "
    "all prediction errors among the 751 ideology-contested cases whose empirical sign "
    "matches either the intervention or market expectation; "
    "canonical values are arXiv v2 Equation 2/Table 5"
)


def normalized_markup_text(markup):
    without_tags = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(html_lib.unescape(without_tags).split())


def tag_attribute(tag, name):
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag)
    if not match:
        raise AssertionError(f"attribute {name!r} is missing from {tag!r}")
    return html_lib.unescape(match.group(1))


def extract_braced_block(source, marker):
    marker_index = source.index(marker)
    open_index = source.index("{", marker_index)
    depth = 0
    for index in range(open_index, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[marker_index : index + 1]
    raise AssertionError(f"unclosed CSS block starting at {marker!r}")


def signed_one(value):
    value = float(value)
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f}"


class PaperPageStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_bytes = HTML_PATH.read_bytes()
        cls.css_bytes = CSS_PATH.read_bytes()
        cls.explorer_bytes = EXPLORER_PATH.read_bytes()
        cls.data_bytes = DATA_PATH.read_bytes()

        cls.html = cls.html_bytes.decode("utf-8", errors="strict")
        cls.css = cls.css_bytes.decode("utf-8", errors="strict")
        cls.explorer = cls.explorer_bytes.decode("utf-8", errors="strict")
        cls.data_text = cls.data_bytes.decode("utf-8", errors="strict")
        cls.data = json.loads(cls.data_text)

        validator_path = REPO_ROOT / "scripts/validate_paper_data_v2.py"
        validator_spec = importlib.util.spec_from_file_location(
            "paper_data_validator", validator_path
        )
        validator_module = importlib.util.module_from_spec(validator_spec)
        validator_spec.loader.exec_module(validator_module)
        cls.validator_b_dir_definition = validator_module.B_DIR_DEFINITION

    def test_all_page_assets_are_strict_utf8_without_replacement_glyphs(self):
        for path, decoded in (
            (HTML_PATH, self.html),
            (CSS_PATH, self.css),
            (EXPLORER_PATH, self.explorer),
            (DATA_PATH, self.data_text),
        ):
            self.assertNotIn("\ufffd", decoded, f"replacement glyph in {path}")
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        for character in ("×", "−", "→", "Δ", "’"):
            self.assertIn(character, "\n".join((self.html, self.explorer, self.data_text)))

    def test_public_arxiv_v2_has_exactly_the_twenty_paper_models(self):
        models = self.data["models"]
        self.assertEqual(self.data["schema_version"], "2.0.0")
        self.assertEqual(self.data["dataset_version"], "arxiv-v2-20-models")
        self.assertEqual(self.data["source"]["paper"], "arXiv:2604.21334v2")
        self.assertEqual(
            self.data["source"]["paper_url"], "https://arxiv.org/abs/2604.21334v2"
        )
        self.assertEqual(tuple(model["id"] for model in models), EXPECTED_MODEL_IDS)
        self.assertEqual(len({model["source_model_id"] for model in models}), 20)
        self.assertTrue(self.data["reported_in_paper"])
        self.assertIn("evaluation_date", self.data)

        for model in models:
            self.assertIs(model["reported_in_paper"], True)
            self.assertEqual(model["source"], "arXiv v2 Tables 5 and 2; Task 1 no-example export")
            self.assertIn("evaluation_date", model)
            self.assertRegex(model["release_date"], r"^\d{4}-\d{2}-\d{2}$")
            release_source = model["release_date_source"]
            self.assertTrue(release_source["title"].strip())
            self.assertTrue(release_source["url"].startswith("https://"))

        serialized_ids = "\n".join(model["id"] for model in models).lower()
        self.assertNotIn("opus-4-8", serialized_ids)
        self.assertNotIn("opus 4.8", serialized_ids)

    def test_table_5_b_dir_values_and_denominators_are_canonical(self):
        self.assertEqual(self.data["definitions"]["b_dir_pct"], B_DIR_DEFINITION)
        self.assertEqual(self.validator_b_dir_definition, B_DIR_DEFINITION)
        self.assertEqual(
            self.data["denominators"],
            {
                "benchmark_total": 10490,
                "contested_pool": 1056,
                "paper_contested": 898,
                "directional_total": 751,
                "intervention_truth": 436,
                "market_truth": 315,
                "sensitive_neither": 147,
                "non_contested": 9434,
            },
        )
        observed = {
            model["id"]: model["overview"]["b_dir_pct"] for model in self.data["models"]
        }
        self.assertEqual(observed, EXPECTED_B_DIR)
        self.assertIn("actualY: yScale(model.overview.b_dir_pct)", self.explorer)
        self.assertNotIn("directionally classifiable mistakes", self.html)
        self.assertNotIn("/ directional errors", self.explorer)

    def test_overview_and_four_condition_icl_payloads_are_complete(self):
        expected_overview_keys = {
            "non_contested_accuracy",
            "contested_accuracy",
            "intervention_accuracy",
            "market_accuracy",
            "accuracy_gap_pp",
            "b_dir_pct",
        }
        expected_icl_keys = {
            "none",
            "non_contested",
            "intervention_ex",
            "market_ex",
            "delta_example",
        }
        for model in self.data["models"]:
            self.assertEqual(set(model["overview"]), expected_overview_keys)
            self.assertEqual(
                set(model["icl"]), {"intervention_truth", "market_truth"}
            )
            for values in model["icl"].values():
                self.assertEqual(set(values), expected_icl_keys)
                expected_delta = round(
                    values["intervention_ex"] - values["market_ex"], 1
                )
                # Table 2 reports every accuracy and delta to one decimal place. A delta
                # computed again from the displayed accuracy cells may therefore differ
                # from the independently rounded paper delta by at most 0.1 pp.
                self.assertLessEqual(
                    abs(values["delta_example"] - expected_delta), 0.1000001
                )
        self.assertEqual(
            self.data["definitions"]["delta_example"],
            "intervention_ex - market_ex for the same target side",
        )

    def test_overview_uses_compact_metrics_and_four_accessible_equations(self):
        overview_renderer = self.explorer.split("function renderOverview(model)", 1)[1].split(
            "function iclTargetCard", 1
        )[0]
        self.assertIn("metricCard('Views agree'", overview_renderer)
        self.assertIn("metricCard('Views differ'", overview_renderer)
        self.assertNotIn("Views agree (non-contested)", overview_renderer)
        self.assertNotIn("Views differ (ideology-contested)", overview_renderer)

        definition_grid = re.search(
            r'<div class="metric-definition-grid">(?P<body>.*?)</div>',
            overview_renderer,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(definition_grid)
        definition_body = definition_grid.group("body")
        self.assertEqual(definition_body.count("<section>"), 4)
        for heading in ("Views agree", "Views differ", "Accuracy gap"):
            self.assertIn(f"<strong>{heading}</strong>", definition_body)
        self.assertIn('<strong aria-label="B dir">', definition_body)

        accessible_equations = (
            "Intervention expectation equals market expectation",
            "Intervention expectation does not equal market expectation",
            "Intervention-aligned truth accuracy minus market-aligned truth accuracy",
            "One hundred times intervention-leaning errors minus market-leaning errors, "
            "divided by all prediction errors",
        )
        self.assertEqual(definition_body.count('aria-label="'), 5)
        for label in accessible_equations:
            self.assertIn(f'aria-label="{label}"', definition_body)
        for equation in (
            "Expectation<sub>intervention</sub> = Expectation<sub>market</sub>",
            "Expectation<sub>intervention</sub> ≠ Expectation<sub>market</sub>",
            "Acc<sub>intervention</sub> − Acc<sub>market</sub>",
            "100 × (Errors<sub>intervention</sub> − Errors<sub>market</sub>) / "
            "Errors<sub>total</sub>",
        ):
            self.assertIn(equation, definition_body)

        self.assertNotIn("view-definition-grid", self.explorer)
        self.assertNotIn("truth-definition", self.explorer)
        self.assertNotIn(".view-definition-grid", self.css)
        self.assertNotIn(".truth-definition", self.css)

    def test_accuracy_gap_is_neutral_while_b_dir_keeps_signed_tone(self):
        quick_detail_renderer = self.explorer.split(
            "function showQuickDetail", 1
        )[1].split("function activateTab", 1)[0]
        overview_renderer = self.explorer.split(
            "function renderOverview(model)", 1
        )[1].split("function iclTargetCard", 1)[0]

        self.assertIn(
            '<div class="is-gap-neutral"><dt>Accuracy gap</dt>',
            quick_detail_renderer,
        )
        self.assertNotIn(
            "signedTone(overview.accuracy_gap_pp)", quick_detail_renderer
        )
        self.assertIn("signedTone(overview.b_dir_pct)", quick_detail_renderer)

        self.assertRegex(
            overview_renderer,
            r"metricCard\('Accuracy gap',.*?'is-gap-neutral',\s*"
            r"gapDirection\(overview\.accuracy_gap_pp\)\)",
        )
        self.assertNotIn("signedTone(overview.accuracy_gap_pp)", overview_renderer)
        self.assertIn("signedTone(overview.b_dir_pct)", overview_renderer)

        negative_gap_rule = extract_braced_block(self.css, ".negative-gap {")
        self.assertRegex(negative_gap_rule, r"color:\s*var\(--ink\)")
        self.assertNotRegex(negative_gap_rule, r"var\(--market\)")
        self.assertIn(".quick-detail-grid .is-gap-neutral dd { color: #fff; }", self.css)
        neutral_metric_rule = extract_braced_block(
            self.css, ".metric-card.is-gap-neutral dd {"
        )
        self.assertRegex(neutral_metric_rule, r"color:\s*var\(--ink\)")

    def test_signs_and_direction_labels_are_explicit_and_semantically_distinct(self):
        expected_direction_text = (
            "Intervention-oriented",
            "Market-oriented",
            "Balanced",
            "Intervention-aligned advantage",
            "Market-aligned advantage",
            "No accuracy advantage",
            "Intervention-Ex advantage",
            "Market-Ex advantage",
            "No example advantage",
        )
        for label in expected_direction_text:
            self.assertIn(f"return '{label}'", self.explorer)
        for sign_label in (
            "'+': 'Positive (+)'",
            "'-': 'Negative (−)'",
            "None: 'No significant effect'",
            "mixed: 'Mixed'",
        ):
            self.assertIn(sign_label, self.explorer)

        self.assertIn('class="metric-direction"', self.explorer)
        self.assertIn("gapDirection(overview.accuracy_gap_pp)", self.explorer)
        self.assertIn("biasDirection(overview.b_dir_pct)", self.explorer)
        self.assertIn("exampleDirection(values.delta_example)", self.explorer)
        self.assertIn("gapDirection(subfield.accuracy_gap_pp)", self.explorer)

    def test_every_model_has_the_same_seven_named_subfields(self):
        expected_ids = tuple(item[0] for item in EXPECTED_SUBFIELDS)
        expected_names = tuple(item[1] for item in EXPECTED_SUBFIELDS)
        all_rows = []
        for model in self.data["models"]:
            rows = model["subfields"]
            all_rows.extend(rows)
            self.assertEqual(tuple(row["id"] for row in rows), expected_ids)
            self.assertEqual(tuple(row["name"] for row in rows), expected_names)
            for row in rows:
                self.assertEqual(
                    set(row),
                    {
                        "id",
                        "name",
                        "sample_size",
                        "n_triplets",
                        "intervention_sample_size",
                        "market_sample_size",
                        "intervention_accuracy",
                        "market_accuracy",
                        "accuracy_gap_pp",
                        "b_dir_pct",
                    },
                )
                self.assertAlmostEqual(
                    row["sample_size"],
                    row["intervention_sample_size"] + row["market_sample_size"],
                    places=6,
                )
                self.assertAlmostEqual(
                    row["accuracy_gap_pp"],
                    row["intervention_accuracy"] - row["market_accuracy"],
                    places=5,
                )
                self.assertGreater(row["n_triplets"], 0)
        self.assertEqual(len(all_rows), 20 * 7)
        self.assertNotIn("other", {row["id"].lower() for row in all_rows})
        self.assertEqual(
            self.data["definitions"]["subfield_note"],
            "Exactly seven named themes are included; Other is excluded. Overlapping theme "
            "assignments are fractionally weighted, so sample_size may be non-integer.",
        )

    def test_examples_are_full_verbatim_public_exports_for_all_models(self):
        examples = {example["case_id"]: example for example in self.data["examples"]}
        self.assertEqual(set(examples), {"t1_9849", "t1_515"})
        self.assertEqual(
            self.data["source"]["task1_examples"]["field_mapping"],
            {
                "context": "causal_triplets.context",
                "rationale": "model_results.reasoning",
            },
        )
        self.assertEqual(
            self.data["public_content_policy"],
            {
                "context": "exact context field from the public 751-case export",
                "rationale": "exact visible model-generated reasoning field from the public "
                "evaluation export; this is an answer rationale, not hidden chain-of-thought",
                "excluded": [
                    "raw prompt",
                    "long source text",
                    "hidden chain-of-thought",
                    "PII",
                ],
            },
        )

        expected_triplets = {
            "t1_9849": "28831|minimum wage increase|probability of remaining employed",
            "t1_515": "7266|hospital competition|social welfare",
        }
        for case_id, example in examples.items():
            self.assertEqual(example["triplet_key"], expected_triplets[case_id])
            self.assertEqual(example["context"], EXPECTED_CONTEXTS[case_id])
            self.assertNotIn("context_summary", example)
            self.assertTrue(example["paper_url"].startswith("https://"))

            outputs = example["model_outputs"]
            self.assertEqual(len(outputs), 20)
            self.assertEqual({output["model_id"] for output in outputs}, set(EXPECTED_MODEL_IDS))
            for output in outputs:
                self.assertEqual(
                    set(output), {"model_id", "predicted_sign", "correct", "rationale"}
                )
                self.assertIn(output["predicted_sign"], {"+", "-", "None", "mixed"})
                self.assertIs(type(output["correct"]), bool)
                self.assertEqual(output["rationale"], output["rationale"].strip())
                self.assertGreaterEqual(len(output["rationale"]), 100)
                self.assertFalse(output["rationale"].endswith(("…", "...")))

            canonical_outputs = "\n".join(
                f'{output["model_id"]}\t{output["predicted_sign"]}\t'
                f'{1 if output["correct"] else 0}\t{output["rationale"]}'
                for output in sorted(outputs, key=lambda item: item["model_id"])
            )
            digest = hashlib.sha256(canonical_outputs.encode("utf-8")).hexdigest()
            self.assertEqual(digest, EXPECTED_EXAMPLE_OUTPUT_SHA256[case_id])

        by_case_and_model = {
            (example["case_id"], output["model_id"]): output
            for example in examples.values()
            for output in example["model_outputs"]
        }
        self.assertEqual(
            by_case_and_model[("t1_9849", "gemini-3-flash")]["predicted_sign"],
            "None",
        )
        self.assertEqual(
            by_case_and_model[("t1_515", "llama-3-1-8b")]["predicted_sign"],
            "None",
        )
        self.assertIn("${escapeHtml(example.context)}", self.explorer)
        self.assertIn("${escapeHtml(output.rationale)}", self.explorer)
        self.assertNotIn("context_summary", self.explorer)
        self.assertNotIn("output.explanation", self.explorer)

    def test_exact_section_order_headings_caption_and_benchmark_copy(self):
        markers = (
            'class="hero section-shell"',
            'id="motivation"',
            'id="benchmark"',
            'id="findings"',
            'id="release-bias"',
            'aria-labelledby="subfields-heading"',
            'id="citation"',
        )
        positions = [self.html.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertNotRegex(self.html, r'<section[^>]+id="(?:icl|examples)"')

        page_text = normalized_markup_text(self.html)
        exact_copy = (
            "Figure 1. The same economic question can imply different causal signs under "
            "intervention-oriented and market-oriented economic perspectives.",
            "Do LLMs exhibit systematic ideological bias when reasoning about economic causal effects?",
            "LLMs are increasingly deployed in economic reporting, policy evaluation, and corporate "
            "decision support, where predicting causal directions correctly is essential. Yet a single "
            "intervention can trigger competing mechanisms whose relative magnitudes are debated along "
            "ideological lines.",
            "From published evidence to directional questions.",
            "EconCausal is a dataset of causal relationships extracted from economics and finance "
            "journals. Each record includes a treatment, an outcome, the study context, and the "
            "empirical effect sign. Among 10,490 records, intervention-oriented and market-oriented "
            "perspectives predict different signs for 1,056. The directional analysis uses the 751 "
            "cases whose empirical sign aligns with one of the two perspectives.",
            "10,490 Economic causal relationships",
            "1,056 Perspectives predict different signs",
            "751 Published evidence matches one perspective",
            "Intervention-oriented (pro-government) Expects active government action to correct market "
            "failures, reduce inequality, or expand social insurance. Intervention-aligned truth means "
            "the published effect matches that expectation.",
            "Market-oriented (pro-market) Expects market allocation and individual incentives to "
            "dominate, with limited government intervention. Market-aligned truth means the published "
            "effect matches that expectation.",
            "Main results across 20 language models",
            "18 of 20 models are more accurate on intervention-aligned truth cases.",
            "Accuracy (%) on the 751 cases where published evidence matches one perspective. Gap = "
            "intervention-aligned truth minus market-aligned truth accuracy; reported gaps use the "
            "paper's unrounded estimates.",
            "Directional bias across model releases",
            "B dir measures the direction of prediction errors. Positive values indicate intervention-"
            "oriented bias; negative values indicate market-oriented bias.",
            "Average accuracy gap by economic subfield",
        )
        for expected in exact_copy:
            self.assertIn(expected, page_text)

        for removed_copy in (
            "01 · Economic causal reasoning",
            "02 · Main findings",
            "03 · Where is it strongest?",
            "One benchmark. Two directional failures.",
            "Directional bias does not disappear in newer releases.",
        ):
            self.assertNotIn(removed_copy, page_text)

    def test_release_section_copy_is_simplified_but_chart_remains_accessible(self):
        release_match = re.search(
            r'<section id="release-bias".*?</section>', self.html, flags=re.DOTALL
        )
        self.assertIsNotNone(release_match)
        release_html = release_match.group(0)
        self.assertIn('aria-label="Directional bias by model release date"', release_html)
        self.assertIn('id="release-family-legend"', release_html)
        self.assertIn('id="release-chart"', release_html)
        self.assertRegex(
            release_html,
            r'aria-label="Interactive plot of release date and error-direction bias for 20 models\.[^"]*"',
        )
        self.assertIn("do not represent a global time trend", release_html)
        self.assertEqual(release_html.count("<p>"), 1)
        for removed in (
            "release-chart-footer",
            "release-data-details",
            "release-data-table",
            "How to read it:",
            "View the 20-point data table",
            "first official public release date with its canonical",
        ):
            self.assertNotIn(removed, release_html)

    def test_progressive_html_keeps_twenty_main_rows_and_paper_resources(self):
        self.assertEqual(self.html.count('class="model-score-row'), 20)
        for value in (
            'href="assets/paper.pdf"',
            'href="https://arxiv.org/abs/2604.21334"',
            'content="https://econai.kaist.ac.kr/ideological-bias-in-llms/assets/og-card.png"',
            'data-copy-target="bibtex"',
            'type="module" src="script.js"',
        ):
            self.assertIn(value, self.html)

    def test_static_bias_ranking_has_twenty_canonical_rows(self):
        button_blocks = re.findall(
            r'<button\b(?=[^>]*class="[^"]*\bbias-ranking-row\b)[^>]*>.*?</button>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertEqual(len(button_blocks), 20)
        models = {model["id"]: model for model in self.data["models"]}
        expected_order = sorted(
            models,
            key=lambda model_id: (
                -models[model_id]["overview"]["b_dir_pct"],
                f'{models[model_id]["family"]} {models[model_id]["display_name"]}',
            ),
        )
        observed_order = [tag_attribute(block, "data-model-id") for block in button_blocks]
        self.assertEqual(observed_order, expected_order)
        self.assertEqual(len(set(observed_order)), 20)

        for rank, (model_id, block) in enumerate(zip(observed_order, button_blocks), 1):
            self.assertEqual(tag_attribute(block, "type"), "button")
            model = models[model_id]
            full_name = f'{model["family"]} {model["display_name"]}'
            score = signed_one(model["overview"]["b_dir_pct"])
            direction = (
                "Intervention-oriented"
                if model["overview"]["b_dir_pct"] > 0
                else "Market-oriented"
                if model["overview"]["b_dir_pct"] < 0
                else "Balanced"
            )
            self.assertIn(f"Rank {rank} of 20, {full_name}", tag_attribute(block, "aria-label"))
            self.assertIn(score, normalized_markup_text(block))
            self.assertIn(direction, normalized_markup_text(block))
            self.assertRegex(block, rf'<span class="bias-rank"[^>]*>{rank}</span>')

    def test_compare_feature_is_completely_removed(self):
        for token in (
            'id="compare-',
            'class="compare-',
            "data-compare-",
            "data-remove-model",
            "Add to compare",
        ):
            self.assertNotIn(token, self.html)

        for token in (
            "compareTray",
            "comparedModelIds",
            "compareToggle",
            "compareSort",
            "compareGrid",
            "maxComparedModels",
            "syncCompareUrl",
            "toggleCompare",
            "setComparedModels",
            "renderCompare",
            "initializeCompareFromUrl",
            "is-compared",
        ):
            self.assertNotIn(token, self.explorer)
        self.assertNotRegex(
            self.explorer,
            r"searchParams\.(?:get|set|delete)\(\s*['\"]compare['\"]",
        )

        for token in (
            ".compare-tray",
            ".compare-controls",
            ".compare-grid",
            ".compare-card",
            ".compare-remove",
            ".compare-metrics",
            ".is-compared",
        ):
            self.assertNotIn(token, self.css)

    def test_dialog_has_four_accessible_tabs_contained_at_320px(self):
        tab_tags = re.findall(
            r'<button\b(?=[^>]*data-model-tab="[^"]+")[^>]*>.*?</button>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertEqual(len(tab_tags), 4)
        expected_tabs = (
            ("overview", "Overview"),
            ("icl", "ICL"),
            ("examples", "Examples"),
            ("subfields", "By subfield"),
        )
        for tag, (name, label) in zip(tab_tags, expected_tabs):
            self.assertEqual(tag_attribute(tag, "id"), f"model-tab-{name}")
            self.assertEqual(tag_attribute(tag, "type"), "button")
            self.assertEqual(tag_attribute(tag, "role"), "tab")
            self.assertEqual(tag_attribute(tag, "aria-controls"), f"model-panel-{name}")
            self.assertEqual(tag_attribute(tag, "data-model-tab"), name)
            self.assertEqual(normalized_markup_text(tag), label)
            panel_pattern = (
                rf'<div id="model-panel-{name}"[^>]*role="tabpanel"'
                rf'[^>]*aria-labelledby="model-tab-{name}"'
            )
            self.assertRegex(self.html, panel_pattern)
        self.assertIn('class="model-tabs" role="tablist"', self.html)

        tabs_rule = extract_braced_block(self.css, ".model-tabs {")
        tab_button_rule = extract_braced_block(self.css, ".model-tabs button {")
        self.assertRegex(tabs_rule, r"overflow-x:\s*auto")
        min_width = int(re.search(r"min-width:\s*(\d+)px", tab_button_rule).group(1))
        min_height = int(re.search(r"min-height:\s*(\d+)px", tab_button_rule).group(1))
        self.assertGreater(min_width * 4, 320)
        self.assertGreaterEqual(min_height, 44)
        self.assertIn("@media (max-width: 340px)", self.css)
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            self.assertIn(f"'{key}'", self.explorer)

    def test_aggregate_subfields_are_accessible_interactive_buttons(self):
        section_match = re.search(
            r'<section class="content-section section-shell" '
            r'aria-labelledby="subfields-heading">.*?</section>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(section_match)
        section = section_match.group(0)
        self.assertIn(
            'class="subfield-panel" role="region" aria-labelledby="subfields-heading"',
            section,
        )
        buttons = re.findall(
            r'<button\b(?=[^>]*class="[^"]*\bsubfield-row\b)[^>]*>', section
        )
        self.assertEqual(len(buttons), 7)
        observed = []
        for button in buttons:
            self.assertEqual(tag_attribute(button, "type"), "button")
            self.assertEqual(tag_attribute(button, "aria-expanded"), "false")
            self.assertEqual(tag_attribute(button, "aria-controls"), "subfield-detail")
            observed.append(
                (
                    tag_attribute(button, "data-subfield-name"),
                    float(tag_attribute(button, "data-sample-size")),
                    float(tag_attribute(button, "data-intervention-accuracy")),
                    float(tag_attribute(button, "data-market-accuracy")),
                    float(tag_attribute(button, "data-gap")),
                )
            )
        self.assertEqual(observed, list(EXPECTED_AGGREGATE_SUBFIELDS))
        self.assertRegex(
            section,
            r'id="subfield-detail"[^>]*aria-live="polite"[^>]*aria-atomic="true"',
        )

        for listener in ("mouseenter", "mouseleave", "focus", "blur", "click", "keydown"):
            self.assertIn(f"row.addEventListener('{listener}'", self.explorer)
        self.assertIn("event.key !== 'Escape'", self.explorer)
        self.assertIn("candidate.setAttribute('aria-expanded'", self.explorer)
        self.assertIn("renderAggregateSubfieldDetail", self.explorer)

    def test_aggregate_subfield_axis_and_detail_stay_compact_on_mobile(self):
        self.assertIn(
            '<span class="axis-wide">Market-aligned advantage</span>'
            '<span class="axis-compact">Market</span>',
            self.html,
        )
        self.assertIn(
            '<span class="axis-wide">Intervention-aligned advantage</span>'
            '<span class="axis-compact">Intervention</span>',
            self.html,
        )
        base_compact_rule = extract_braced_block(self.css, ".axis-compact {")
        self.assertRegex(base_compact_rule, r"display:\s*none")

        mobile = extract_braced_block(self.css, "@media (max-width: 680px)")
        self.assertRegex(
            mobile,
            r"\.subfield-axis\s*\{[^}]*display:\s*grid[^}]*min-height:\s*32px",
        )
        self.assertRegex(mobile, r"\.axis-wide\s*\{[^}]*display:\s*none")
        self.assertRegex(mobile, r"\.axis-compact\s*\{[^}]*display:\s*inline")
        self.assertRegex(
            mobile,
            r"\.subfield-detail dl\s*\{[^}]*grid-template-columns:\s*"
            r"repeat\(2,\s*minmax\(0,\s*1fr\)\)",
        )

        detail_renderer = self.explorer.split(
            "function renderAggregateSubfieldDetail", 1
        )[1].split("function initializeAggregateSubfields", 1)[0]
        selected_detail = re.search(
            r'<dl>(?P<body>.*?)</dl>', detail_renderer, flags=re.DOTALL
        )
        self.assertIsNotNone(selected_detail)
        self.assertEqual(selected_detail.group("body").count("<div"), 4)
        for label in (
            "Directional cases",
            "Intervention-aligned",
            "Market-aligned",
            "Accuracy gap",
        ):
            self.assertIn(f"<dt>{label}</dt>", selected_detail.group("body"))

    def test_core_controls_keep_at_least_44px_touch_targets(self):
        model_open_rule = extract_braced_block(self.css, ".model-open-button {")
        release_point_rule = extract_braced_block(self.css, ".release-point-button {")
        ranking_rules = re.findall(r"\.bias-ranking-row\s*\{[^}]*\}", self.css)
        subfield_rules = re.findall(r"\.subfield-row\s*\{[^}]*\}", self.css)
        for property_name in ("min-width", "min-height"):
            self.assertRegex(model_open_rule, rf"{property_name}:\s*44px")
        for property_name in ("width", "height"):
            self.assertRegex(release_point_rule, rf"{property_name}:\s*44px")
        self.assertTrue(
            any(
                re.search(r"min-height:\s*(?:4[4-9]|[5-9]\d)px", rule)
                for rule in ranking_rules
            )
        )
        self.assertTrue(
            any(
                re.search(r"min-height:\s*(?:4[4-9]|[5-9]\d)px", rule)
                for rule in subfield_rules
            )
        )

    def test_reduced_motion_never_hides_core_interactive_controls(self):
        reduced_motion = extract_braced_block(
            self.css, "@media (prefers-reduced-motion: reduce)"
        )
        self.assertNotRegex(reduced_motion, r"display\s*:\s*none")
        self.assertNotRegex(reduced_motion, r"visibility\s*:\s*hidden")
        for selector in (
            ".model-detail-dialog",
            ".model-open-button",
            ".release-point-button",
            ".bias-ranking-row",
            ".subfield-row",
        ):
            self.assertIn(selector, reduced_motion)
        self.assertRegex(reduced_motion, r"transition:\s*none\s*!important")
        self.assertRegex(reduced_motion, r"animation:\s*none\s*!important")

    def test_dialog_and_release_controls_have_keyboard_and_focus_scaffolding(self):
        for value in (
            '<dialog id="model-detail-dialog"',
            'data-dialog-close aria-label="Close model details"',
            'id="model-quick-detail"',
            'role="tooltip" hidden',
            'aria-live="polite"',
            'id="release-chart"',
        ):
            self.assertIn(value, self.html)
        for value in (
            "button.addEventListener('focus'",
            "button.addEventListener('click'",
            "dialog.addEventListener('close'",
            "lastDialogTrigger.focus()",
            "button.type = 'button'",
            "button.className = `release-point-button",
        ):
            self.assertIn(value, self.explorer)


if __name__ == "__main__":
    unittest.main()
