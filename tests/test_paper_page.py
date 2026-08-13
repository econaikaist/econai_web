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
EXTENSION_DATA_PATH = PAGE_ROOT / "data/website-experiment-results.v1.json"

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
    "gpt-4o-mini": 6.3,
    "gpt-4o": 6.0,
    "gpt-5-nano": 7.4,
    "gpt-5-mini": 3.7,
    "gpt-5-2": 0.8,
    "claude-haiku-4-5": 6.2,
    "claude-sonnet-4-6": -5.9,
    "claude-opus-4-6": -10.2,
    "gemini-2-5-flash": 10.7,
    "gemini-3-flash": -7.3,
    "grok-3-mini": 14.5,
    "grok-3": 1.6,
    "grok-4-1-fast": -3.9,
    "llama-3-1-8b": -3.9,
    "llama-3-2-1b": 0.8,
    "llama-3-2-3b": 5.2,
    "llama-3-3-70b": 12.5,
    "qwen-3-8b": 16.9,
    "qwen-3-14b": 9.6,
    "qwen-3-32b": 10.0,
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
    (
        "Healthcare",
        101.0,
        71.64113233717924,
        55.06155950752394,
        16.579572829655305,
    ),
    (
        "Welfare & Redistribution",
        92.0,
        77.57296466973885,
        63.10629514963882,
        14.466669520100034,
    ),
    (
        "Education",
        60.0,
        72.74401473296501,
        65.81196581196583,
        6.932048920999179,
    ),
    (
        "Labor",
        218.0,
        68.70121089188028,
        62.14941672871679,
        6.551794163163493,
    ),
    (
        "Financial Regulation",
        220.0,
        69.33210784313725,
        65.58485463150777,
        3.7472532116294843,
    ),
    (
        "Taxation",
        77.0,
        72.08538587848932,
        72.95696802210817,
        -0.871582143618852,
    ),
    (
        "Trade",
        38.0,
        65.406162464986,
        66.66666666666666,
        -1.2605042016806607,
    ),
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
    "all prediction errors among the 878 ideology-contested cases whose empirical sign "
    "matches either the intervention or market expectation; "
    "canonical values are from the COLM 2026 camera-ready Equation 1/Table 5"
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
        cls.extension_data = json.loads(EXTENSION_DATA_PATH.read_text(encoding="utf-8"))

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
        for character in ("×", "−", "→", "≠", "’"):
            self.assertIn(character, "\n".join((self.html, self.explorer, self.data_text)))

    def test_camera_ready_has_exactly_the_twenty_paper_models(self):
        models = self.data["models"]
        self.assertEqual(self.data["schema_version"], "2.1.0")
        self.assertEqual(self.data["dataset_version"], "colm-camera-ready-20-models")
        self.assertEqual(self.data["source"]["paper"], "COLM 2026 camera-ready")
        self.assertEqual(
            self.data["source"]["paper_url"], "https://arxiv.org/abs/2604.21334v2"
        )
        self.assertEqual(tuple(model["id"] for model in models), EXPECTED_MODEL_IDS)
        self.assertEqual(len({model["source_model_id"] for model in models}), 20)
        self.assertTrue(self.data["reported_in_paper"])
        self.assertIn("evaluation_date", self.data)

        for model in models:
            self.assertIs(model["reported_in_paper"], True)
            self.assertEqual(model["source"], "COLM 2026 camera-ready Tables 5 and 2; Task 1 no-example export")
            self.assertIn("evaluation_date", model)
            self.assertRegex(model["release_date"], r"^\d{4}-\d{2}-\d{2}$")
            release_source = model["release_date_source"]
            self.assertTrue(release_source["title"].strip())
            self.assertTrue(release_source["url"].startswith("https://"))

        serialized_ids = "\n".join(model["id"] for model in models).lower()
        self.assertNotIn("opus-4-8", serialized_ids)
        self.assertNotIn("opus 4.8", serialized_ids)

    def test_new_evaluations_cover_all_completed_hosted_and_local_conditions_once(self):
        extension = self.extension_data
        self.assertEqual(extension["schema_version"], "website-experiment-results.v1")
        self.assertEqual(
            extension["evaluation"]["denominators"],
            {
                "contested": 1056,
                "directional": 878,
                "intervention_truth": 507,
                "market_truth": 371,
                "neither_truth": 178,
            },
        )

        main = extension["main_benchmark"]
        self.assertEqual(main["condition_count"], 36)
        self.assertEqual(len(main["results"]), 36)
        self.assertEqual(
            sum(row["provider"] == "Local GPU" for row in main["results"]),
            9,
        )
        self.assertEqual(
            {row["model_id"] for row in main["excluded_models"]},
            {"gemini-2.5-flash", "gemini-3.1-pro-preview"},
        )

        sweeps = extension["reasoning_effort_sweeps"]["sweeps"]
        self.assertEqual([sweep["condition_count"] for sweep in sweeps], [5, 5, 4, 3])
        self.assertEqual([len(sweep["results"]) for sweep in sweeps], [5, 5, 4, 3])
        self.assertEqual(extension["coverage"]["completed_full_run_condition_count"], 49)
        self.assertEqual(extension["coverage"]["completed_result_row_count"], 51744)
        self.assertIs(
            extension["coverage"]["main_and_sweeps_cover_all_completed_conditions"],
            True,
        )

        main_keys = {row["condition_key"] for row in main["results"]}
        sweep_keys = {
            row["condition_key"]
            for sweep in sweeps
            for row in sweep["results"]
        }
        self.assertEqual(len(main_keys), 36)
        self.assertEqual(len(sweep_keys), 17)
        self.assertEqual(len(main_keys | sweep_keys), 49)

    def test_new_results_are_integrated_and_effort_has_verified_progressive_fallbacks(self):
        effort_section = re.search(
            r'<section id="reasoning-effort".*?</section>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(effort_section)
        self.assertEqual(effort_section.group(0).count('data-condition-key="'), 17)
        self.assertEqual(effort_section.group(0).count('class="effort-model-row"'), 4)
        self.assertEqual(effort_section.group(0).count('class="effort-card"'), 0)
        self.assertNotIn('id="post-paper-extension"', self.html)
        self.assertNotIn('id="post-paper-result-body"', self.html)
        self.assertNotIn('id="model-benchmark-controls"', self.html)
        self.assertNotIn('result-source-chip', self.html)
        self.assertNotIn('effort-selection-detail', self.html)
        self.assertIn("normalizeBenchmarkRows(data, extensionData)", self.explorer)
        self.assertIn("exactly 51 unique models", self.explorer)
        self.assertIn("MAIN_EXCLUDED_CONDITIONS", self.explorer)
        self.assertIn("renderReasoningExplorer(extensionData)", self.explorer)

        effort_series = self.explorer.split("const EFFORT_SERIES =", 1)[1].split(
            "function effortMetricValue", 1
        )[0]
        self.assertEqual(
            set(re.findall(r"^\s{4}(overall|gap):", effort_series, flags=re.MULTILINE)),
            {"overall", "gap"},
        )
        self.assertNotRegex(effort_series, r"^\s{4}(?:bias|intervention|market):")
        self.assertIn("Object.entries(EFFORT_SERIES).forEach", self.explorer)
        self.assertIn("grid.dataset.metric = 'overall,gap'", self.explorer)
        self.assertIn('class="effort-setting-hit"', self.explorer)
        self.assertIn("grid.dataset.pointCount", self.explorer)
        self.assertNotIn("data-effort-metric-button", self.explorer)
        self.assertNotIn("effort-metric-selector", self.explorer)

    def test_bundled_pdf_is_the_final_camera_ready_file(self):
        paper_bytes = (PAGE_ROOT / "assets/paper.pdf").read_bytes()
        self.assertEqual(
            hashlib.sha256(paper_bytes).hexdigest(),
            "cf2dd5490757f23bf30b936307775a50a524da163a977eb86ad98a5e63542c0b",
        )

    def test_social_card_uses_the_camera_ready_headline(self):
        social_svg = (PAGE_ROOT / "assets/og-card.svg").read_text(encoding="utf-8")
        self.assertIn(">17 / 20</text>", social_svg)
        self.assertNotIn(">18 / 20</text>", social_svg)
        social_png = (PAGE_ROOT / "assets/og-card.png").read_bytes()
        self.assertEqual(social_png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(social_png[16:20], "big"), 1200)
        self.assertEqual(int.from_bytes(social_png[20:24], "big"), 630)

    def test_table_5_b_dir_values_and_denominators_are_canonical(self):
        self.assertEqual(self.data["definitions"]["b_dir_pct"], B_DIR_DEFINITION)
        self.assertEqual(self.validator_b_dir_definition, B_DIR_DEFINITION)
        self.assertEqual(
            self.data["denominators"],
            {
                "benchmark_total": 10490,
                "contested_pool": 1056,
                "directional_total": 878,
                "intervention_truth": 507,
                "market_truth": 371,
                "sensitive_neither": 178,
                "non_contested": 9434,
            },
        )
        observed = {
            model["id"]: model["overview"]["b_dir_pct"] for model in self.data["models"]
        }
        self.assertEqual(observed, EXPECTED_B_DIR)
        self.assertNotIn("first.bias - second.bias", self.explorer)
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

    def test_overview_uses_direct_sign_terms_and_three_accessible_equations(self):
        overview_renderer = self.explorer.split("function renderOverview(model)", 1)[1].split(
            "function renderExamples", 1
        )[0]
        self.assertIn("metricCard('Same-sign accuracy'", overview_renderer)
        self.assertIn("metricCard('Different-sign accuracy'", overview_renderer)
        for asset in (self.html, self.explorer):
            self.assertNotRegex(asset, r"(?i)\bviews?\s+(?:agree|differ)\b")

        definition_grid = re.search(
            r'<div class="metric-definition-grid">(?P<body>.*?)</div>',
            overview_renderer,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(definition_grid)
        definition_body = definition_grid.group("body")
        self.assertEqual(definition_body.count("<section>"), 4)
        self.assertRegex(
            definition_body,
            r"<strong>(?:Same-sign accuracy|Same predicted sign)</strong>",
        )
        self.assertRegex(
            definition_body,
            r"<strong>(?:Different-sign accuracy|Different predicted signs)</strong>",
        )
        self.assertIn("<strong>Accuracy gap</strong>", definition_body)

        accessible_equations = (
            "Intervention-oriented sign equals market-oriented sign",
            "Intervention-oriented sign does not equal market-oriented sign",
            "Intervention-truth accuracy minus market-truth accuracy",
            "One hundred times intervention-leaning errors minus market-leaning errors, divided by all prediction errors",
        )
        self.assertEqual(definition_body.count('aria-label="'), 5)
        for label in accessible_equations:
            self.assertIn(f'aria-label="{label}"', definition_body)
        for equation in (
            "Sign<sub>intervention</sub> = Sign<sub>market</sub>",
            "Sign<sub>intervention</sub> ≠ Sign<sub>market</sub>",
            "Acc<sub>intervention</sub> − Acc<sub>market</sub>",
            "100 × (Errors<sub>intervention</sub> − Errors<sub>market</sub>) / "
            "Errors<sub>total</sub>",
        ):
            self.assertIn(equation, definition_body)
        self.assertNotIn("Expectation<sub>", definition_body)

        definition_hint = re.search(
            r'<p class="definition-hint">(?P<body>.*?)</p>',
            overview_renderer,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(definition_hint)
        hint_text = normalized_markup_text(definition_hint.group("body")).lower()
        self.assertIn("accuracies", hint_text)
        self.assertRegex(hint_text, r"\bgroup(?:ed|s)?\b")
        direct_sign_hint = hint_text.replace("-", " ")
        self.assertRegex(direct_sign_hint, r"\bsame(?: causal)? signs?\b")
        self.assertRegex(direct_sign_hint, r"\bdifferent(?: causal)? signs?\b")

        self.assertNotIn("view-definition-grid", self.explorer)
        self.assertNotIn("truth-definition", self.explorer)
        self.assertNotIn(".view-definition-grid", self.css)
        self.assertNotIn(".truth-definition", self.css)

    def test_accuracy_gap_and_b_dir_use_signed_tones_without_tinted_cards(self):
        quick_detail_renderer = self.explorer.split(
            "function showQuickDetail", 1
        )[1].split("function activateTab", 1)[0]
        overview_renderer = self.explorer.split(
            "function renderOverview(model)", 1
        )[1].split("function renderExamples", 1)[0]

        self.assertIn(
            '<div class="${signedTone(overview.accuracy_gap_pp)}"><dt>Accuracy gap</dt>',
            quick_detail_renderer,
        )
        self.assertIn("signedTone(overview.b_dir_pct)", quick_detail_renderer)

        self.assertRegex(
            overview_renderer,
            r"metricCard\('Accuracy gap',.*?signedTone\(overview\.accuracy_gap_pp\),\s*"
            r"gapDirection\(overview\.accuracy_gap_pp\)\)",
        )
        self.assertIn("signedTone(overview.b_dir_pct)", overview_renderer)

        positive_gap_rule = extract_braced_block(self.css, ".positive-gap {")
        negative_gap_rule = extract_braced_block(self.css, ".negative-gap {")
        self.assertRegex(positive_gap_rule, r"color:\s*var\(--intervention\)")
        self.assertRegex(negative_gap_rule, r"color:\s*var\(--market\)")
        for asset in (self.html, self.css, self.explorer):
            self.assertNotIn("is-gap-neutral", asset)

        metric_card_rule = extract_braced_block(self.css, ".metric-card {")
        self.assertRegex(metric_card_rule, r"background:\s*#f8fafc")
        for selector in (
            r"\.metric-card\.is-intervention",
            r"\.metric-card\.is-market",
            r"\.metric-card\.intervention-metric",
            r"\.metric-card\.market-metric",
        ):
            for rule in re.findall(rf"{selector}[^{{]*\{{[^}}]*\}}", self.css):
                self.assertNotRegex(rule, r"\bbackground(?:-color)?:")

        model_row_tags = re.findall(r'<div class="model-score-row[^"]*"', self.html)
        self.assertEqual(len(model_row_tags), 20)
        self.assertEqual(len(set(model_row_tags)), 1)

    def test_model_score_bars_have_no_repeating_grid_background(self):
        score_bars_rule = extract_braced_block(self.css, ".model-score-bars {")
        self.assertNotRegex(
            score_bars_rule,
            r"(?:repeating-)?(?:linear|radial)-gradient",
        )
        background_image = re.search(r"background-image:\s*([^;]+)", score_bars_rule)
        if background_image:
            self.assertEqual(background_image.group(1).strip(), "none")

    def test_interactive_assets_use_matching_cache_busters(self):
        asset_version = "20260813c"
        self.assertIn(f'href="styles.css?v={asset_version}"', self.html)
        self.assertIn(f'src="script.js?v={asset_version}"', self.html)
        entrypoint = (PAGE_ROOT / "script.js").read_text(encoding="utf-8")
        self.assertIn(
            f"import('./modules/paper-explorer.v2.js?v={asset_version}')",
            entrypoint,
        )

    def test_selected_release_chart_replaces_other_drafts_and_uses_left_right_colors(self):
        drafts_html = (PAGE_ROOT / "release-chart-drafts.html").read_text(encoding="utf-8")
        drafts_js = (PAGE_ROOT / "release-chart-drafts.js").read_text(encoding="utf-8")
        self.assertIn('id="draft-5"', drafts_html)
        for removed_id in ('draft-1', 'draft-2', 'draft-3', 'draft-4'):
            self.assertNotIn(f'id="{removed_id}"', drafts_html)
        for removed_renderer in ('renderSmallMultiples', 'renderSignalLanes', 'renderConstellation', 'renderEraCards'):
            self.assertNotIn(removed_renderer, drafts_js)
        self.assertIn("document.body.dataset.draftCount = '1'", drafts_js)
        self.assertIn("--intervention: #2563eb", self.css)
        self.assertIn("--intervention-soft: #dbeafe", self.css)
        self.assertIn("--market: #dc2626", self.css)
        self.assertIn("--market-soft: #fee2e2", self.css)
        self.assertIn('data-release-family="${escapeHtml(family)}"', self.explorer)

    def test_signs_and_direction_labels_are_explicit_and_semantically_distinct(self):
        expected_direction_text = (
            "Intervention-oriented",
            "Market-oriented",
            "Balanced",
            "Intervention-truth advantage",
            "Market-truth advantage",
            "No accuracy advantage",
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
            "Exactly seven named themes are shown; Other is excluded. Per-model and aggregate "
            "subfield metrics use the corrected 878 directional cases and top-tied vote-weighted "
            "JEL assignments, so sample_size may be non-integer.",
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
                "context": "exact context field retained from the public 751-case example "
                "export; the displayed example case IDs remain in the corrected 878 "
                "directional subset",
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

    def test_examples_stack_full_width_reference_before_selected_model(self):
        examples_renderer = self.explorer.split(
            "function renderExamples(model)", 1
        )[1].split("function renderModelSubfields", 1)[0]
        reference_position = examples_renderer.index(
            '<section class="example-reference-block">'
        )
        model_position = examples_renderer.index(
            '<section class="example-model-block">'
        )
        self.assertLess(reference_position, model_position)

        intro = re.search(
            r'<p class="(?P<class>[^"]+)">(?P<body>[^<]+)</p>',
            examples_renderer,
        )
        self.assertIsNotNone(intro)
        self.assertNotIn("icl", intro.group("class").lower())
        intro_text = normalized_markup_text(intro.group("body")).lower()
        self.assertIn("reference", intro_text)
        self.assertIn("selected model", intro_text)
        self.assertNotIn("side by side", intro_text)
        self.assertNotIn("side-by-side", intro_text)

        example_block_rules = re.findall(r"\.example-blocks\s*\{[^}]*\}", self.css)
        self.assertTrue(example_block_rules)
        for rule in example_block_rules:
            columns = re.search(r"grid-template-columns:\s*([^;]+)", rule)
            if columns:
                self.assertRegex(
                    columns.group(1).strip(),
                    r"^(?:minmax\(0,\s*)?1fr\)?$",
                )
        self.assertRegex(
            extract_braced_block(self.css, ".example-blocks {"),
            r"grid-template-columns:\s*(?:minmax\(0,\s*)?1fr\)?",
        )

    def test_model_subfield_dialog_renders_seven_named_rows_plus_overview_total(self):
        renderer = self.explorer.split(
            "function renderModelSubfields(model)", 1
        )[1].split("function openModel", 1)[0]

        for model in self.data["models"]:
            visible_names = [row["name"] for row in model["subfields"]] + ["Total"]
            self.assertEqual(len(visible_names), 8)
            self.assertEqual(tuple(visible_names[:7]), tuple(name for _, name in EXPECTED_SUBFIELDS))
            self.assertEqual(visible_names[-1], "Total")

        rows_definition = re.search(
            r"const rows = \[(?P<body>.*?)\n\s*\];",
            renderer,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(rows_definition)
        self.assertIn("...subfields.map", rows_definition.group("body"))
        self.assertIn("name: 'Total'", rows_definition.group("body"))
        self.assertLess(
            rows_definition.group("body").index("...subfields.map"),
            rows_definition.group("body").index("name: 'Total'"),
        )
        self.assertIn("${rows.map((subfield)", renderer)
        for field in (
            "intervention_accuracy",
            "market_accuracy",
            "accuracy_gap_pp",
        ):
            self.assertRegex(renderer, rf"overview\.{field}\b")
        self.assertNotRegex(renderer, r">\s*n\s*=")
        self.assertNotIn("n_triplets", renderer)
        self.assertNotRegex(renderer, r"\.(?:reduce|sum)\s*\(")
        self.assertIn("signedTone(subfield.accuracy_gap_pp)", renderer)
        self.assertIn('class="model-subfield-note"', renderer)
        self.assertIn("corrected 878 directional cases", renderer)
        self.assertIn("Tied JEL-theme assignments", renderer)

    def test_exact_section_order_headings_caption_and_benchmark_copy(self):
        markers = (
            'class="hero section-shell"',
            'id="motivation"',
            'id="benchmark"',
            'id="findings"',
            'aria-labelledby="subfields-heading"',
            'id="reasoning-effort"',
            'aria-labelledby="internship-heading"',
            'id="citation"',
        )
        positions = [self.html.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertNotRegex(self.html, r'<section[^>]+id="(?:icl|examples)"')

        page_text = normalized_markup_text(self.html)
        exact_copy = (
            "Left-Advantage Score Left-truth accuracy minus right-truth accuracy.",
            "Figure 1. Accuracy asymmetry across model generations. Lines connect releases only "
            "within the same model family; hover, focus, or click any model for exact results.",
            "Do LLMs exhibit systematic ideological bias when reasoning about economic causal effects?",
            "LLMs are increasingly deployed in economic reporting, policy evaluation, and corporate "
            "decision support, where predicting causal directions correctly is essential. Yet a single "
            "intervention can trigger competing mechanisms whose relative magnitudes are debated along "
            "ideological lines.",
            "From published evidence to directional questions.",
            "EconCausal is a dataset of causal relationships extracted from economics and finance "
            "journals. Each record includes a treatment, an outcome, the study context, and the "
            "empirical effect sign. Among 10,490 records, intervention-oriented and market-oriented "
            "perspectives predict different signs for 1,056. The directional analysis uses the 878 "
            "cases whose empirical sign aligns with one of the two perspectives: 507 intervention-"
            "truth and 371 market-truth cases. The remaining 178 contested cases align with neither "
            "perspective.",
            "10,490 Economic causal relationships",
            "1,056 Perspectives predict different signs",
            "878 Empirical sign matches one perspective",
            "Intervention-oriented (pro-government, left) Expects active government action to correct market "
            "failures, reduce inequality, or expand social insurance. Intervention-truth means the "
            "empirical sign matches that ideology-conditioned expectation.",
            "Market-oriented (pro-market, right) Expects market allocation and individual incentives to "
            "dominate, with limited government intervention. Market-truth means the empirical sign "
            "matches that ideology-conditioned expectation.",
            "All-model results",
            "Most models are more accurate on intervention-truth cases.",
            "Accuracy (%) on the corrected 878-item directional set: 507 intervention-truth and 371 "
            "market-truth cases. Gap = intervention-truth minus market-truth accuracy.",
            "Average accuracy gap by economic subfield",
            "How reasoning effort changes the result",
            "I am looking for research internship opportunities.",
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

    def test_release_chart_covers_the_same_51_unique_rows_as_the_main_benchmark(self):
        self.assertNotIn('id="bias-map"', self.html)
        self.assertNotIn("renderBiasMap", self.explorer)
        self.assertNotIn("biasMap", self.explorer)
        self.assertIn('id="release-chart"', self.html)
        self.assertIn("renderReleaseChart", self.explorer)
        renderer = self.explorer.split("function renderReleaseChart", 1)[1].split(
            "function renderAggregateSubfieldDetail", 1
        )[0]
        self.assertIn("release-point-button", renderer)
        self.assertIn("data-result-key", renderer)
        self.assertIn("releaseChart.dataset.modelCount = String(mainModelRows.length)", renderer)
        self.assertIn("mainModelRows", renderer)
        self.assertIn("releaseMarkerElement", renderer)
        self.assertIn("`${point.actualX},${point.actualY}`", renderer)
        self.assertIn("releaseChart.dataset.coordinateSystem = 'exact-data-coordinates'", renderer)
        self.assertIn("releaseChart.dataset.familyLineOrder = 'release-date-ascending'", renderer)
        self.assertNotIn("layoutReleasePoints", self.explorer)
        self.assertNotIn("displayX", renderer)
        self.assertNotIn("displayY", renderer)

    def test_main_model_sequence_uses_capability_groups(self):
        self.assertIn("const MAIN_MODEL_GROUPS", self.explorer)
        expected_groups = (
            "openai-compact", "openai-flagship", "claude-general", "claude-premium", "gemini",
            "grok", "llama", "qwen-compact", "qwen-large",
        )
        for group in expected_groups:
            self.assertIn(f"key: '{group}'", self.explorer)
        for removed_group in (
            "claude", "claude-opus", "gemini-flash", "grok-fast",
            "grok-flagship", "llama-compact", "llama-large",
        ):
            self.assertNotIn(f"key: '{removed_group}'", self.explorer)

        groups_block = self.explorer.split("const MAIN_MODEL_GROUPS =", 1)[1].split(
            "const FAMILY_STYLES", 1
        )[0]
        self.assertEqual(groups_block.count("key: '"), 9)
        self.assertEqual(groups_block.count("family: 'OpenAI'"), 2)
        self.assertEqual(groups_block.count("family: 'Claude'"), 2)
        self.assertEqual(groups_block.count("family: 'Qwen'"), 2)
        for family in ("Gemini", "Grok", "Llama"):
            self.assertEqual(groups_block.count(f"family: '{family}'"), 1)

        claude_general = groups_block.split("key: 'claude-general'", 1)[1].split("},", 1)[0]
        claude_premium = groups_block.split("key: 'claude-premium'", 1)[1].split("},", 1)[0]
        self.assertLess(claude_general.index("paper:claude-haiku-4-5"), claude_general.index("new:anthropic_sonnet45_disabled"))
        self.assertLess(claude_general.index("new:anthropic_sonnet45_disabled"), claude_general.index("paper:claude-sonnet-4-6"))
        self.assertLess(claude_general.index("paper:claude-sonnet-4-6"), claude_general.index("new:an_sonnet5_disabled_low"))
        for older, newer in zip(
            (
                "new:anthropic_opus45_disabled_low", "paper:claude-opus-4-6",
                "new:an_opus47_disabled_low", "new:an_opus48_disabled_low",
                "new:an_opus5_disabled_low",
            ),
            (
                "paper:claude-opus-4-6", "new:an_opus47_disabled_low",
                "new:an_opus48_disabled_low", "new:an_opus5_disabled_low",
                "new:an_fable5_adaptive_low",
            ),
        ):
            self.assertLess(claude_premium.index(older), claude_premium.index(newer))
        self.assertIn("benchmarkChart.dataset.order = 'capability-groups'", self.explorer)
        self.assertIn("OpenAI and Claude are split by capability tier", self.explorer)
        self.assertIn("new:oa_gpt56_terra_none", self.explorer)
        self.assertIn("new:an_sonnet5_disabled_low", self.explorer)
        self.assertIn("new:gg_gemini36_minimal", self.explorer)
        self.assertIn("new:or_grok420_reasoning_disabled", self.explorer)
        self.assertIn("new:or_grok43_none", self.explorer)
        paper_grok = next(model for model in self.data["models"] if model["id"] == "grok-4-1-fast")
        updated_grok = next(row for row in self.extension_data["main_benchmark"]["results"] if row["condition_key"] == "or_grok420_reasoning_disabled")
        self.assertEqual(paper_grok["display_name"], "4.1")
        self.assertEqual(updated_grok["display_name"], "Grok 4.2")

    def test_progressive_html_keeps_twenty_main_rows_and_paper_resources(self):
        self.assertEqual(self.html.count('class="model-score-row'), 20)
        for value in (
            'href="assets/paper.pdf"',
            'href="https://arxiv.org/abs/2604.21334"',
            'content="https://econai.kaist.ac.kr/ideological-bias-in-llms/assets/og-card.png"',
            'data-copy-target="bibtex"',
            'type="module" src="script.js?v=20260813c"',
        ):
            self.assertIn(value, self.html)

    def test_all_51_main_rows_are_interactive_and_new_rows_have_provenance_dialogs(self):
        enhancer = self.explorer.split("function enhanceMainResults()", 1)[1].split(
            "function initializeUnifiedBenchmark", 1
        )[0]
        self.assertIn(".model-score-row[data-result-key]", enhancer)
        self.assertIn("mainRowsByResultKey.get(row.dataset.resultKey)", enhancer)
        self.assertIn("button.className = 'model-open-button'", enhancer)
        self.assertIn("button.dataset.conditionKey = result.conditionKey", enhancer)
        self.assertIn("openBenchmarkRow(result, button)", enhancer)
        self.assertNotIn(".model-score-row[data-paper-model-id]", enhancer)

        updated_dialog = self.explorer.split("function renderUpdatedOverview(row)", 1)[1].split(
            "function configureDialogTabs", 1
        )[0]
        for label, field in (
            ("Intervention-truth", "row.intervention"),
            ("Market-truth", "row.market"),
            ("Accuracy gap", "row.gap"),
        ):
            self.assertIn(label, updated_dialog)
            self.assertIn(field, updated_dialog)
        self.assertNotIn("Overall accuracy", updated_dialog)
        self.assertNotIn("row.overall", updated_dialog)
        for label, field in (
            ("Provider", "row.provider"),
            ("Setting", "row.setting"),
        ):
            self.assertIn(label, updated_dialog)
            self.assertIn(field, updated_dialog)
        self.assertNotIn("Requested model", updated_dialog)
        self.assertNotIn("Canonical model", updated_dialog)
        self.assertNotIn("row.modelId", updated_dialog)
        self.assertNotIn("row.canonicalModelId", updated_dialog)

        updated_opener = self.explorer.split("function openUpdatedResult(row, trigger)", 1)[1].split(
            "function openBenchmarkRow", 1
        )[0]
        self.assertIn("Official release: ${formatDate(row.releaseDate)}", updated_opener)
        self.assertNotIn("experimentSettingLabel(row.setting)", updated_opener)

        self.assertIn("function formatSampleSize(value)", self.explorer)
        self.assertIn("Math.round(number)", self.explorer)
        self.assertIn("formatSampleSize(subfield.sample_size)", self.explorer)

        row_normalizer = self.explorer.split("function normalizeBenchmarkRows", 1)[1].split(
            "function benchmarkRowMarkup", 1
        )[0]
        for source_field in (
            "result.provider", "result.model_id", "result.canonical_model_id",
            "result.setting", "result.condition_key", "result.condition_id",
        ):
            self.assertIn(source_field, row_normalizer)
        self.assertNotIn("configureDialogTabs(false)", self.explorer)
        self.assertNotIn("tab.hidden = !fullPaperDetail && tab.dataset.modelTab !== 'overview'", self.explorer)
        self.assertIn("if (row.paperModelId) openModel", self.explorer)
        self.assertIn("else openUpdatedResult(row, trigger)", self.explorer)

    def test_updated_model_dialogs_keep_the_full_three_tab_contract(self):
        updated_dialog = self.explorer.split("function openUpdatedResult", 1)[1].split(
            "function renderReleaseChart", 1
        )[0]
        self.assertNotIn("tab.hidden", updated_dialog)
        for row in self.extension_data["main_benchmark"]["results"]:
            self.assertEqual(
                [example["case_id"] for example in row["examples"]],
                ["t1_9849", "t1_515"],
            )
            self.assertEqual(len(row["subfields"]), 7)

    def test_reasoning_effort_renders_two_series_together_for_17_settings(self):
        renderer = self.explorer.split("function renderReasoningExplorer", 1)[1].split(
            "export async function initPaperExplorer", 1
        )[0]
        self.assertIn("const overallDomain", renderer)
        self.assertIn("const signedDomain", renderer)
        self.assertIn("Object.entries(EFFORT_SERIES).forEach", renderer)
        self.assertIn("data-effort-series=", renderer)
        self.assertIn("data-metric=", renderer)
        self.assertIn('class="effort-setting-hit"', renderer)
        self.assertIn("grid.dataset.metric = 'overall,gap'", renderer)
        self.assertIn("grid.dataset.chartCount = String(sweeps.length)", renderer)
        self.assertIn("grid.dataset.pointCount", renderer)
        self.assertIn("Overall ${escapeHtml(effortMetricValue(row, 'overall'))}", renderer)
        self.assertIn("Gap ${escapeHtml(effortMetricValue(row, 'gap'))}", renderer)
        self.assertNotIn("B<sub>dir</sub>", renderer)
        self.assertNotIn("bias", renderer.lower())
        self.assertNotIn("data-effort-metric-button", renderer)
        self.assertNotIn("selectedMetric", renderer)

        sweeps = self.extension_data["reasoning_effort_sweeps"]["sweeps"]
        self.assertEqual(sum(len(sweep["results"]) for sweep in sweeps), 17)
        self.assertEqual(len(sweeps), 4)


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

    def test_dialog_has_exactly_three_accessible_tabs_and_no_icl_ui(self):
        tab_tags = re.findall(
            r'<button\b(?=[^>]*data-model-tab="[^"]+")[^>]*>.*?</button>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertEqual(len(tab_tags), 3)
        expected_tabs = (
            ("overview", "Overview"),
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
        self.assertGreater(min_width, 0)
        self.assertGreaterEqual(min_height, 44)
        self.assertIn("@media (max-width: 340px)", self.css)
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            self.assertIn(f"'{key}'", self.explorer)

        self.assertNotRegex(self.html, r'(?i)\bICL\b')
        for token in (
            "model-panel-icl",
            'data-model-tab="icl"',
            "function renderIcl",
            "function iclTargetCard",
            "exampleDirection",
            "model.icl",
        ):
            self.assertNotIn(token, self.html)
            self.assertNotIn(token, self.explorer)
        self.assertNotRegex(self.css, r"(?i)\.icl[-_]")
        self.assertNotIn(".formula-card", self.css)

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
        for name in ("Taxation", "Trade"):
            row = re.search(
                rf'<button\b[^>]*data-subfield-name="{name}".*?</button>',
                section,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(row)
            self.assertIn('class="negative-value"', row.group(0))
        self.assertRegex(
            section,
            r'id="subfield-detail"[^>]*aria-live="polite"[^>]*aria-atomic="true"[^>]*hidden',
        )

        for listener in ("click", "keydown"):
            self.assertIn(f"row.addEventListener('{listener}'", self.explorer)
        initializer = self.explorer.split("function initializeAggregateSubfields", 1)[1].split(
            "initializeUnifiedBenchmark();", 1
        )[0]
        for listener in ("mouseenter", "mouseleave", "focus", "blur"):
            self.assertNotIn(f"row.addEventListener('{listener}'", initializer)
        self.assertIn("event.key !== 'Escape'", self.explorer)
        self.assertIn("candidate.setAttribute('aria-expanded'", self.explorer)
        self.assertIn("renderAggregateSubfieldDetail", self.explorer)

    def test_aggregate_subfield_axis_and_detail_stay_compact_on_mobile(self):
        self.assertIn(
            '<span class="axis-wide">Market-truth advantage</span>'
            '<span class="axis-compact">Market</span>',
            self.html,
        )
        self.assertIn(
            '<span class="axis-wide">Intervention-truth advantage</span>'
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
            "Intervention-truth",
            "Market-truth",
            "Accuracy gap",
        ):
            self.assertIn(f"<dt>{label}</dt>", selected_detail.group("body"))

    def test_core_controls_keep_at_least_44px_touch_targets(self):
        model_open_rule = extract_braced_block(self.css, ".model-open-button {")
        generation_cell_rule = extract_braced_block(self.css, ".generation-model-cell {")
        release_point_rules = re.findall(r"\.release-point-button\s*\{[^}]*\}", self.css)
        subfield_rules = re.findall(r"\.subfield-row\s*\{[^}]*\}", self.css)
        for property_name in ("min-width", "min-height"):
            self.assertRegex(model_open_rule, rf"{property_name}:\s*44px")
        self.assertRegex(generation_cell_rule, r"min-height:\s*(?:4[4-9]|[5-9]\d)px")
        self.assertTrue(release_point_rules)
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
            ".effort-setting-hit",
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
