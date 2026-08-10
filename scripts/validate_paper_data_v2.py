#!/usr/bin/env python3
"""Validate the interactive paper-page dataset against the paper artifacts.

Usage:
    python scripts/validate_paper_data_v2.py /home/donggyu/econ_causality \
        --paper-tex-root /home/donggyu/donggyu-lee1.github.io/colm/Tables

The release timeline is all-or-none: once one official release date is supplied,
all 20 paper models must have an ISO date and a primary-source title/URL.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


B_DIR_DEFINITION = (
    "100 × (intervention-leaning errors - market-leaning errors) / "
    "all prediction errors among the 751 ideology-contested cases whose empirical sign "
    "matches either the intervention or market expectation; "
    "canonical values are arXiv v2 Equation 2/Table 5"
)


MODEL_SPECS = (
    ("gpt-4o-mini", "gpt-4o-mini", "OpenAI", "GPT-4o-mini", "closed"),
    ("gpt-4o", "gpt-4o", "OpenAI", "GPT-4o", "closed"),
    ("gpt-5-nano", "gpt-5-nano", "OpenAI", "GPT-5-nano", "closed"),
    ("gpt-5-mini", "gpt-5-mini", "OpenAI", "GPT-5-mini", "closed"),
    ("gpt-5-2", "gpt-5.2", "OpenAI", "GPT-5.2", "closed"),
    ("claude-haiku-4-5", "claude-haiku-4-5", "Claude", "Haiku 4.5", "closed"),
    ("claude-sonnet-4-6", "claude-sonnet-4-6", "Claude", "Sonnet 4.6", "closed"),
    ("claude-opus-4-6", "claude-opus-4-6", "Claude", "Opus 4.6", "closed"),
    ("gemini-2-5-flash", "gemini-2.5-flash", "Gemini", "2.5 Flash", "closed"),
    ("gemini-3-flash", "gemini-3-flash-preview", "Gemini", "3 Flash", "closed"),
    ("grok-3-mini", "grok-3-mini", "Grok", "3-mini", "closed"),
    ("grok-3", "grok-3", "Grok", "3", "closed"),
    ("grok-4-1-fast", "grok-4-1-fast-reasoning", "Grok", "4-1 Fast", "closed"),
    (
        "llama-3-1-8b",
        "meta-llama/llama-3.1-8b-instruct",
        "Llama",
        "3.1-8B",
        "open",
    ),
    (
        "llama-3-2-1b",
        "meta-llama/llama-3.2-1b-instruct",
        "Llama",
        "3.2-1B",
        "open",
    ),
    (
        "llama-3-2-3b",
        "meta-llama/llama-3.2-3b-instruct",
        "Llama",
        "3.2-3B",
        "open",
    ),
    (
        "llama-3-3-70b",
        "meta-llama/llama-3.3-70b-instruct",
        "Llama",
        "3.3-70B",
        "open",
    ),
    ("qwen-3-8b", "qwen/qwen3-8b", "Qwen", "3-8B", "open"),
    ("qwen-3-14b", "qwen/qwen3-14b", "Qwen", "3-14B", "open"),
    ("qwen-3-32b", "qwen/qwen3-32b", "Qwen", "3-32B", "open"),
)

EXAMPLE_SPECS = {
    "t1_9849": "28831|minimum wage increase|probability of remaining employed",
    "t1_515": "7266|hospital competition|social welfare",
}

SUBFIELD_THEMES = (
    ("healthcare", "Healthcare"),
    ("welfare_redistribution", "Welfare & Redistribution"),
    ("education", "Education"),
    ("labor", "Labor"),
    ("financial_regulation", "Financial Regulation"),
    ("trade", "Trade"),
    ("taxation", "Taxation"),
)

CAMERA_READY_TABLE_DIR = Path("COLM_EconCausal_Ideology_Bias_camera_ready/Tables")
BIAS_CSV_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/tables/"
    "task1_bias_by_model.csv"
)
ANALYSIS_JSONL_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/"
    "analysis_datasets/task1_analysis_rows.jsonl"
)
SUBFIELD_ACCURACY_CSV_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/tables/"
    "task1_accuracy_by_model_vote_theme_and_ground_truth_side.csv"
)
SUBFIELD_BIAS_CSV_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/tables/"
    "task1_bias_by_model_and_vote_theme.csv"
)
EXAMPLE_EXPORT_DIR = Path(
    "extended/ideology_bias_outputs/task1_triplet_model_exports/"
    "task1_triplets_model_results_751_and_1056/ideology_contested_751"
)
EXAMPLE_TRIPLETS_CSV_PATH = EXAMPLE_EXPORT_DIR / "causal_triplets.csv"
EXAMPLE_RESULTS_CSV_PATH = EXAMPLE_EXPORT_DIR / "model_results_all_models.csv"


class ValidationError(RuntimeError):
    pass


def _numbers_after_model(line: str, model_name: str, expected: int) -> list[float]:
    """Extract numeric cells from one single-line LaTeX model row."""
    match = re.match(rf"^\s*&\s*{re.escape(model_name)}\s*&(?P<cells>.*)\\\\\s*$", line)
    if not match:
        raise ValidationError(f"could not parse row for {model_name!r}: {line!r}")
    cells = match.group("cells").replace("$-$", "-")
    values = [float(value) for value in re.findall(r"[+-]?\d+(?:\.\d+)?", cells)]
    if len(values) != expected:
        raise ValidationError(
            f"expected {expected} values for {model_name}, found {len(values)}: {values}"
        )
    return values


def _table_rows(path: Path, expected_cells: int) -> dict[tuple[str, str], list[float]]:
    text = path.read_text(encoding="utf-8")
    rows: dict[tuple[str, str], list[float]] = {}
    for _, _, family, display_name, _ in MODEL_SPECS:
        candidates = [
            line
            for line in text.splitlines()
            if re.match(rf"^\s*&\s*{re.escape(display_name)}\s*&", line)
        ]
        if len(candidates) != 1:
            raise ValidationError(
                f"expected one {family}/{display_name} row in {path}, found {len(candidates)}"
            )
        rows[(family, display_name)] = _numbers_after_model(
            candidates[0], display_name, expected_cells
        )
    return rows


def _bias_by_source_model(path: Path) -> dict[str, float]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["model"]: float(row["bias_score"]) * 100 for row in rows}


def _example_rows(
    triplets_path: Path, results_path: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """Load the two public examples verbatim from the 751-case CSV export."""
    case_metadata: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, dict[str, Any]]] = {
        case_id: {} for case_id in EXAMPLE_SPECS
    }
    triplet_to_case = {triplet_key: case_id for case_id, triplet_key in EXAMPLE_SPECS.items()}
    wanted_source_ids = {spec[1] for spec in MODEL_SPECS}

    with triplets_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = triplet_to_case.get(row["triplet_key"])
            if case_id is None:
                continue
            if case_id in case_metadata:
                raise ValidationError(f"duplicate causal-triplet row for {case_id}")
            case_metadata[case_id] = {
                "case_id": case_id,
                "triplet_key": row["triplet_key"],
                "title": row["title"],
                "paper_url": row["paper_url"],
                "treatment": row["treatment"],
                "outcome": row["outcome"],
                "context": row["context"],
                "empirical_sign": row["expected_sign"],
                "intervention_sign": row["economic_liberal_preferred_sign"],
                "market_sign": row["economic_conservative_preferred_sign"],
                "ground_truth_side": (
                    "intervention" if row["ground_truth_side"] == "liberal" else "market"
                ),
            }

    blank_sign_rows: set[tuple[str, str]] = set()
    with results_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = triplet_to_case.get(row["triplet_key"])
            source_model_id = row["model"]
            if case_id is None or source_model_id not in wanted_source_ids:
                continue
            if source_model_id in outputs[case_id]:
                raise ValidationError(
                    f"duplicate example output for {case_id}/{source_model_id}"
                )
            metadata = case_metadata.get(case_id)
            if metadata is None:
                raise ValidationError(f"missing causal-triplet metadata for {case_id}")
            for field in ("treatment", "outcome", "context", "expected_sign"):
                expected_value = (
                    metadata["empirical_sign"] if field == "expected_sign" else metadata[field]
                )
                if row[field] != expected_value:
                    raise ValidationError(
                        f"example export mismatch for {case_id}/{source_model_id}/{field}"
                    )
            predicted_sign = row["predicted_sign"]
            if predicted_sign == "":
                blank_sign_rows.add((case_id, source_model_id))
                predicted_sign = "None"
            if row["correct"] not in {"0", "1"}:
                raise ValidationError(
                    f"invalid correct flag for {case_id}/{source_model_id}: {row['correct']!r}"
                )
            outputs[case_id][source_model_id] = {
                "predicted_sign": predicted_sign,
                "correct": row["correct"] == "1",
                "rationale": row["reasoning"],
            }

    expected_blank_sign_rows = {
        ("t1_9849", "gemini-3-flash-preview"),
        ("t1_515", "meta-llama/llama-3.1-8b-instruct"),
    }
    if blank_sign_rows != expected_blank_sign_rows:
        raise ValidationError(
            "blank predicted_sign normalization changed: "
            f"expected {sorted(expected_blank_sign_rows)}, found {sorted(blank_sign_rows)}"
        )
    if set(case_metadata) != set(EXAMPLE_SPECS):
        raise ValidationError(
            f"example causal-triplet coverage mismatch: {sorted(case_metadata)}"
        )
    for case_id, rows in outputs.items():
        if set(rows) != wanted_source_ids:
            raise ValidationError(
                f"example model coverage mismatch for {case_id}: "
                f"missing={sorted(wanted_source_ids - set(rows))}, "
                f"extra={sorted(set(rows) - wanted_source_ids)}"
            )

    return case_metadata, outputs


def _subfield_rows(accuracy_path: Path, bias_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Build the fixed seven-theme per-model panel from the weighted source CSVs."""
    with accuracy_path.open(encoding="utf-8", newline="") as handle:
        accuracy_rows = list(csv.DictReader(handle))
    with bias_path.open(encoding="utf-8", newline="") as handle:
        bias_rows = list(csv.DictReader(handle))

    accuracy_index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in accuracy_rows:
        key = (row["model"], row["jel_policy_theme"], row["ground_truth_side"])
        if key in accuracy_index:
            raise ValidationError(f"duplicate subfield accuracy row: {key}")
        accuracy_index[key] = row

    bias_index: dict[tuple[str, str], dict[str, str]] = {}
    for row in bias_rows:
        key = (row["model"], row["jel_policy_theme"])
        if key in bias_index:
            raise ValidationError(f"duplicate subfield bias row: {key}")
        bias_index[key] = row

    source_model_ids = {spec[1] for spec in MODEL_SPECS}
    expected_themes = {theme for theme, _ in SUBFIELD_THEMES} | {"other"}
    if {row["model"] for row in accuracy_rows} != source_model_ids:
        raise ValidationError("subfield accuracy model set differs from the paper baseline")
    if {row["model"] for row in bias_rows} != source_model_ids:
        raise ValidationError("subfield bias model set differs from the paper baseline")
    if {row["jel_policy_theme"] for row in accuracy_rows} != expected_themes:
        raise ValidationError("subfield accuracy theme set is not seven named themes plus Other")
    if {row["jel_policy_theme"] for row in bias_rows} != expected_themes:
        raise ValidationError("subfield bias theme set is not seven named themes plus Other")

    by_model: dict[str, list[dict[str, Any]]] = {}
    for _, source_model_id, _, _, _ in MODEL_SPECS:
        themes: list[dict[str, Any]] = []
        for theme_id, theme_name in SUBFIELD_THEMES:
            intervention = accuracy_index[(source_model_id, theme_id, "liberal")]
            market = accuracy_index[(source_model_id, theme_id, "conservative")]
            bias = bias_index[(source_model_id, theme_id)]
            intervention_sample = float(intervention["n_predictions"])
            market_sample = float(market["n_predictions"])
            total_sample = float(bias["n_predictions"])
            if not math.isclose(
                intervention_sample + market_sample, total_sample, abs_tol=1e-9
            ):
                raise ValidationError(
                    f"subfield sample mismatch for {source_model_id}/{theme_id}"
                )
            intervention_accuracy = float(intervention["accuracy"]) * 100
            market_accuracy = float(market["accuracy"]) * 100
            themes.append(
                {
                    "id": theme_id,
                    "name": theme_name,
                    "sample_size": total_sample,
                    "n_triplets": int(bias["n_triplets"]),
                    "intervention_sample_size": intervention_sample,
                    "market_sample_size": market_sample,
                    "intervention_accuracy": round(intervention_accuracy, 6),
                    "market_accuracy": round(market_accuracy, 6),
                    "accuracy_gap_pp": round(
                        intervention_accuracy - market_accuracy, 6
                    ),
                    "b_dir_pct": round(float(bias["bias_score"]) * 100, 6),
                }
            )
        by_model[source_model_id] = themes

    return by_model


def _paper_denominators(path: Path) -> dict[str, int]:
    """Reproduce the 1,056 -> 898 -> 751/147 subset decomposition."""
    cases: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = row["case_id"]
            metadata = (row["ideology_sensitivity"], row["ground_truth_side"])
            if key in cases and cases[key] != metadata:
                raise ValidationError(f"inconsistent subset labels across models for {key}")
            cases[key] = metadata

    contested_pool = len(cases)
    paper_contested = sum(
        sensitivity == "ideology_sensitive" for sensitivity, _ in cases.values()
    )
    intervention_truth = sum(side == "liberal" for _, side in cases.values())
    market_truth = sum(side == "conservative" for _, side in cases.values())
    directional_total = intervention_truth + market_truth
    sensitive_neither = sum(
        sensitivity == "ideology_sensitive" and side == "neither"
        for sensitivity, side in cases.values()
    )
    benchmark_total = 10490
    denominators = {
        "benchmark_total": benchmark_total,
        "contested_pool": contested_pool,
        "paper_contested": paper_contested,
        "directional_total": directional_total,
        "intervention_truth": intervention_truth,
        "market_truth": market_truth,
        "sensitive_neither": sensitive_neither,
        "non_contested": benchmark_total - contested_pool,
    }
    canonical = {
        "benchmark_total": 10490,
        "contested_pool": 1056,
        "paper_contested": 898,
        "directional_total": 751,
        "intervention_truth": 436,
        "market_truth": 315,
        "sensitive_neither": 147,
        "non_contested": 9434,
    }
    if denominators != canonical:
        raise ValidationError(
            f"Task 1 subset decomposition differs from the paper: {denominators}"
        )
    return denominators


def build_expected_payload(
    econ_root: Path, paper_tex_root: Path | None = None
) -> dict[str, Any]:
    table_root = paper_tex_root or (econ_root / CAMERA_READY_TABLE_DIR)
    table_5_path = table_root / "main_results.tex"
    table_2_path = table_root / "ICL_results.tex"
    table_5 = _table_rows(table_5_path, expected_cells=6)
    table_2 = _table_rows(table_2_path, expected_cells=10)
    bias_scores = _bias_by_source_model(econ_root / BIAS_CSV_PATH)
    case_metadata, example_outputs = _example_rows(
        econ_root / EXAMPLE_TRIPLETS_CSV_PATH,
        econ_root / EXAMPLE_RESULTS_CSV_PATH,
    )
    subfields_by_model = _subfield_rows(
        econ_root / SUBFIELD_ACCURACY_CSV_PATH,
        econ_root / SUBFIELD_BIAS_CSV_PATH,
    )
    denominators = _paper_denominators(econ_root / ANALYSIS_JSONL_PATH)

    models: list[dict[str, Any]] = []
    source_to_public_id: dict[str, str] = {}
    for public_id, source_id, family, display_name, access in MODEL_SPECS:
        source_to_public_id[source_id] = public_id
        t5 = table_5[(family, display_name)]
        t2 = table_2[(family, display_name)]
        # Public arXiv v2 has two displayed delta-sign typos (Llama 3.1-8B
        # market target and Qwen 3-8B market target). Preserve all accuracy
        # cells, but repair a delta only when its sign contradicts the four
        # displayed source cells and the explicit delta definition.
        for delta_index, intervention_index, market_index in ((4, 2, 3), (9, 7, 8)):
            rounded_delta = round(t2[intervention_index] - t2[market_index], 1)
            reported_delta = t2[delta_index]
            if (
                rounded_delta
                and reported_delta
                and math.copysign(1, rounded_delta) != math.copysign(1, reported_delta)
            ):
                t2[delta_index] = rounded_delta
        table_bias = t5[5]
        machine_bias = bias_scores[source_id]
        if not math.isclose(table_bias, round(machine_bias, 1), abs_tol=0.05):
            raise ValidationError(
                f"Table 5 B_dir mismatch for {source_id}: {table_bias} vs {machine_bias}"
            )
        models.append(
            {
                "id": public_id,
                "source_model_id": source_id,
                "display_name": display_name,
                "family": family,
                "access": access,
                "reported_in_paper": True,
                "source": "arXiv v2 Tables 5 and 2; Task 1 no-example export",
                "evaluation_date": None,
                "release_date": None,
                "release_date_source": None,
                "overview": {
                    "non_contested_accuracy": t5[0],
                    "contested_accuracy": t5[1],
                    "intervention_accuracy": t5[2],
                    "market_accuracy": t5[3],
                    "accuracy_gap_pp": t5[4],
                    "b_dir_pct": t5[5],
                },
                "icl": {
                    "intervention_truth": {
                        "none": t2[0],
                        "non_contested": t2[1],
                        "intervention_ex": t2[2],
                        "market_ex": t2[3],
                        "delta_example": t2[4],
                    },
                    "market_truth": {
                        "none": t2[5],
                        "non_contested": t2[6],
                        "intervention_ex": t2[7],
                        "market_ex": t2[8],
                        "delta_example": t2[9],
                    },
                },
                "subfields": subfields_by_model[source_id],
            }
        )

    examples: list[dict[str, Any]] = []
    for case_id in EXAMPLE_SPECS:
        metadata = case_metadata.get(case_id)
        if metadata is None:
            raise ValidationError(f"missing example metadata for {case_id}")
        output_rows = example_outputs[case_id]
        examples.append(
            {
                **metadata,
                "model_outputs": [
                    {
                        "model_id": source_to_public_id[source_id],
                        **output_rows[source_id],
                    }
                    for _, source_id, _, _, _ in MODEL_SPECS
                ],
            }
        )

    return {
        "schema_version": "2.0.0",
        "dataset_version": "arxiv-v2-20-models",
        "reported_in_paper": True,
        "evaluation_date": None,
        "source": {
            "paper": "arXiv:2604.21334v2",
            "paper_url": "https://arxiv.org/abs/2604.21334v2",
            "table_5": str(table_5_path),
            "table_2": str(table_2_path),
            "task1_bias": str(BIAS_CSV_PATH),
            "task1_examples": {
                "causal_triplets": str(EXAMPLE_TRIPLETS_CSV_PATH),
                "model_results": str(EXAMPLE_RESULTS_CSV_PATH),
                "field_mapping": {
                    "context": "causal_triplets.context",
                    "rationale": "model_results.reasoning",
                },
            },
            "task1_subfields": {
                "accuracy": str(SUBFIELD_ACCURACY_CSV_PATH),
                "bias": str(SUBFIELD_BIAS_CSV_PATH),
            },
            "notes": (
                "The camera-ready TeX is used as a machine-readable superset of the "
                "arXiv v2 tables; this dataset includes only the 20 arXiv v2 models."
            ),
        },
        "denominators": denominators,
        "definitions": {
            "accuracy_gap_pp": "intervention_accuracy - market_accuracy",
            "b_dir_pct": B_DIR_DEFINITION,
            "delta_example": "intervention_ex - market_ex for the same target side",
            "icl_note": (
                "None uses the 751 directional cases; example conditions use "
                "ensemble-oriented matched rows and must not be compared as a shared denominator."
            ),
            "subfield_note": (
                "Exactly seven named themes are included; Other is excluded. Overlapping theme "
                "assignments are fractionally weighted, so sample_size may be non-integer."
            ),
        },
        "public_content_policy": {
            "context": "exact context field from the public 751-case export",
            "rationale": (
                "exact visible model-generated reasoning field from the public evaluation export; "
                "this is an answer rationale, not hidden chain-of-thought"
            ),
            "excluded": ["raw prompt", "long source text", "hidden chain-of-thought", "PII"],
        },
        "models": models,
        "examples": examples,
    }


def _assert_equal(actual: Any, expected: Any, path: str, errors: list[str]) -> None:
    if isinstance(expected, float):
        if not isinstance(actual, (int, float)) or not math.isclose(
            float(actual), expected, abs_tol=0.05
        ):
            errors.append(f"{path}: expected {expected}, found {actual!r}")
    elif actual != expected:
        errors.append(f"{path}: expected {expected!r}, found {actual!r}")


def validate(payload: dict[str, Any], expected: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    _assert_equal(payload.get("schema_version"), "2.0.0", "schema_version", errors)
    _assert_equal(
        payload.get("dataset_version"),
        "arxiv-v2-20-models",
        "dataset_version",
        errors,
    )
    _assert_equal(payload.get("reported_in_paper"), True, "reported_in_paper", errors)
    _assert_equal(payload.get("denominators"), expected["denominators"], "denominators", errors)
    for source_name in ("task1_examples", "task1_subfields"):
        _assert_equal(
            (payload.get("source") or {}).get(source_name),
            expected["source"][source_name],
            f"source.{source_name}",
            errors,
        )
    _assert_equal(
        (payload.get("definitions") or {}).get("b_dir_pct"),
        B_DIR_DEFINITION,
        "definitions.b_dir_pct",
        errors,
    )

    models = payload.get("models")
    if not isinstance(models, list):
        return [*errors, "models: expected a list"], warnings
    if len(models) != 20:
        errors.append(f"models: expected exactly 20, found {len(models)}")
    ids = [model.get("id") for model in models if isinstance(model, dict)]
    if len(set(ids)) != len(ids):
        errors.append("models: duplicate public ids")
    source_ids = [model.get("source_model_id") for model in models if isinstance(model, dict)]
    if any("opus-4-8" in str(value).lower() for value in [*ids, *source_ids]):
        errors.append("models: post-paper Opus 4.8 must not be present")

    expected_by_id = {model["id"]: model for model in expected["models"]}
    actual_by_id = {
        model.get("id"): model for model in models if isinstance(model, dict) and model.get("id")
    }
    if set(actual_by_id) != set(expected_by_id):
        errors.append(
            "models: id set differs from the 20-model paper baseline: "
            f"missing={sorted(set(expected_by_id) - set(actual_by_id))}, "
            f"extra={sorted(set(actual_by_id) - set(expected_by_id))}"
        )

    for model_id, expected_model in expected_by_id.items():
        model = actual_by_id.get(model_id)
        if model is None:
            continue
        for field in ("source_model_id", "display_name", "family", "access", "reported_in_paper"):
            _assert_equal(model.get(field), expected_model[field], f"models.{model_id}.{field}", errors)
        for required_field in (
            "source",
            "evaluation_date",
            "release_date",
            "release_date_source",
        ):
            if required_field not in model:
                errors.append(f"models.{model_id}: missing field {required_field}")
        for section in ("overview", "icl", "subfields"):
            _assert_equal(
                model.get(section),
                expected_model[section],
                f"models.{model_id}.{section}",
                errors,
            )
        subfields = model.get("subfields")
        expected_theme_ids = [theme_id for theme_id, _ in SUBFIELD_THEMES]
        if not isinstance(subfields, list) or len(subfields) != 7:
            errors.append(
                f"models.{model_id}.subfields: expected exactly 7 named themes"
            )
        elif [theme.get("id") for theme in subfields] != expected_theme_ids:
            errors.append(
                f"models.{model_id}.subfields: expected fixed order {expected_theme_ids}"
            )
        else:
            required_subfield_fields = {
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
            }
            for theme in subfields:
                if set(theme) != required_subfield_fields:
                    errors.append(
                        f"models.{model_id}.subfields.{theme.get('id')}: "
                        f"expected fields {sorted(required_subfield_fields)}"
                    )
        for side in ("intervention_truth", "market_truth"):
            icl = (model.get("icl") or {}).get(side) or {}
            if all(key in icl for key in ("intervention_ex", "market_ex", "delta_example")):
                computed_delta = round(icl["intervention_ex"] - icl["market_ex"], 1)
                # Table 2 reports one-decimal source cells, while delta_example was
                # calculated from the underlying unrounded accuracies.  A one-tenth
                # difference is therefore possible even when the reported value is
                # correct (for example, Grok 3: 60.8 - 66.5 displays as -5.7 while
                # the paper reports -5.6).  The sign must still agree.
                reported_delta = icl["delta_example"]
                same_sign = (
                    computed_delta == 0
                    or reported_delta == 0
                    or math.copysign(1, computed_delta) == math.copysign(1, reported_delta)
                )
                if not same_sign or not math.isclose(
                    computed_delta, reported_delta, abs_tol=0.11
                ):
                    errors.append(
                        f"models.{model_id}.icl.{side}.delta_example: "
                        f"expected approximately {computed_delta} from rounded source cells, "
                        f"found {reported_delta}"
                    )

    dated = [model for model in models if model.get("release_date")]
    if not dated:
        warnings.append("release timeline pending: 0/20 official model dates populated")
    elif len(dated) != 20:
        errors.append(f"release timeline must be all-or-none: found {len(dated)}/20 dated models")
    else:
        for model in dated:
            date = model["release_date"]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
                errors.append(f"models.{model['id']}.release_date is not ISO YYYY-MM-DD")
            release_source = model.get("release_date_source")
            if not isinstance(release_source, dict):
                errors.append(
                    f"models.{model['id']}.release_date_source must be an object"
                )
            elif not release_source.get("title") or not re.fullmatch(
                r"https://[^\s]+", str(release_source.get("url", ""))
            ):
                errors.append(
                    f"models.{model['id']}.release_date_source needs a title and HTTPS URL"
                )
        if not errors:
            warnings.append("release timeline ready: 20/20 chart-eligible paper models")

    examples = payload.get("examples")
    if not isinstance(examples, list):
        errors.append("examples: expected a list")
        return errors, warnings
    expected_examples = {example["case_id"]: example for example in expected["examples"]}
    actual_examples = {
        example.get("case_id"): example
        for example in examples
        if isinstance(example, dict) and example.get("case_id")
    }
    if set(actual_examples) != {"t1_9849", "t1_515"}:
        errors.append(f"examples: expected t1_9849 and t1_515, found {sorted(actual_examples)}")
    for case_id, expected_example in expected_examples.items():
        example = actual_examples.get(case_id)
        if example is None:
            continue
        for field in (
            "triplet_key",
            "title",
            "paper_url",
            "treatment",
            "outcome",
            "context",
            "empirical_sign",
            "intervention_sign",
            "market_sign",
            "ground_truth_side",
        ):
            _assert_equal(
                example.get(field), expected_example[field], f"examples.{case_id}.{field}", errors
            )
        outputs = example.get("model_outputs")
        if not isinstance(outputs, list) or len(outputs) != 20:
            errors.append(
                f"examples.{case_id}.model_outputs: expected 20, "
                f"found {len(outputs) if isinstance(outputs, list) else 'non-list'}"
            )
            continue
        actual_outputs = {output.get("model_id"): output for output in outputs}
        expected_outputs = {
            output["model_id"]: output for output in expected_example["model_outputs"]
        }
        if set(actual_outputs) != set(expected_outputs):
            errors.append(f"examples.{case_id}: output model ids differ from paper baseline")
        for model_id, expected_output in expected_outputs.items():
            _assert_equal(
                actual_outputs.get(model_id),
                expected_output,
                f"examples.{case_id}.model_outputs.{model_id}",
                errors,
            )
            rationale = (actual_outputs.get(model_id) or {}).get("rationale")
            if not isinstance(rationale, str) or not rationale:
                errors.append(
                    f"examples.{case_id}.model_outputs.{model_id}.rationale is empty"
                )

    none_sign_expectations = {
        ("t1_9849", "gemini-3-flash"),
        ("t1_515", "llama-3-1-8b"),
    }
    actual_none_signs = {
        (example["case_id"], output["model_id"])
        for example in examples
        for output in example.get("model_outputs", [])
        if output.get("predicted_sign") == "None"
    }
    if actual_none_signs != none_sign_expectations:
        errors.append(
            "examples: literal None predicted-sign coverage changed: "
            f"expected {sorted(none_sign_expectations)}, found {sorted(actual_none_signs)}"
        )

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden_key in ('"email"', '"phone"', '"raw_prompt"', '"chain_of_thought"'):
        if forbidden_key in serialized:
            errors.append(f"public payload contains forbidden field {forbidden_key}")

    return errors, warnings


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("econ_root", type=Path, help="Path to the econ_causality checkout")
    parser.add_argument(
        "--paper-tex-root",
        type=Path,
        help=(
            "Directory containing public arXiv v2 main_results.tex and "
            "ICL_results.tex; defaults to the 20-row camera-ready mirror"
        ),
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=repo_root
        / "main_site/ideological-bias-in-llms/data/paper-data.v2.json",
        help="JSON payload to validate",
    )
    parser.add_argument(
        "--emit",
        action="store_true",
        help="Print a source-derived payload with pending dates instead of validating",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        expected = build_expected_payload(
            args.econ_root.resolve(),
            args.paper_tex_root.resolve() if args.paper_tex_root else None,
        )
        if args.emit:
            print(json.dumps(expected, ensure_ascii=False, indent=2))
            return 0
        payload = json.loads(args.data.read_text(encoding="utf-8"))
        errors, warnings = validate(payload, expected)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"Validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1

    print("PASS: schema_version=2.0.0")
    print("PASS: exactly 20 arXiv v2 paper models; post-paper models excluded")
    print("PASS: Table 5 overview and B_dir values match the canonical sources")
    print(
        "PASS: B_dir denominator is all prediction errors among the 751 directionally "
        "aligned ideology-contested cases"
    )
    print("PASS: Table 2 ICL cells and recomputed delta_example values match")
    print("PASS: 20 models × 7 named subfields match the weighted accuracy/bias sources")
    print("PASS: both public examples exactly match the full CSV context/rationale fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
