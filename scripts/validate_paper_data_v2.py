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
from collections import defaultdict
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


B_DIR_DEFINITION = (
    "100 × (intervention-leaning errors - market-leaning errors) / "
    "all prediction errors among the 878 ideology-contested cases whose empirical sign "
    "matches either the intervention or market expectation; "
    "canonical values are from the COLM 2026 camera-ready Equation 1/Table 5"
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

CAMERA_READY_TABLE_DIR = Path(
    "COLM_camera_ready_FINAL_SOURCE_CLEAN_20260809_112253/Tables"
)
BIAS_CSV_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/tables/"
    "task1_bias_by_model.csv"
)
ANALYSIS_JSONL_PATH = Path(
    "extended/ideology_bias_outputs_task1_ideology_subset_1056/"
    "analysis_datasets/task1_analysis_rows.jsonl"
)
CANONICAL_1056_PATH = Path("data/task1_ideology_subset_1056.jsonl")
CURRENT_CLASSIFIER_PATH = Path(
    "extended/classification_results/ideology_triplet_subset_current.jsonl"
)
CAMERA_READY_SUBFIELD_PATH = Path(
    "COLM_EconCausal_Ideology_Bias_camera_ready_CLEAN_20260809_112253/"
    "revision_tools/subfield_metrics_878_vote_weighted.csv"
)
PUBLIC_SUBFIELD_DATA_PATH = Path(
    "main_site/ideological-bias-in-llms/data/"
    "camera-ready-subfields-878.v1.json"
)
EXAMPLE_EXPORT_DIR = Path(
    "extended/ideology_bias_outputs/task1_triplet_model_exports/"
    "task1_triplets_model_results_751_and_1056/ideology_contested_751"
)
EXAMPLE_TRIPLETS_CSV_PATH = EXAMPLE_EXPORT_DIR / "causal_triplets.csv"
EXAMPLE_RESULTS_CSV_PATH = EXAMPLE_EXPORT_DIR / "model_results_all_models.csv"


class ValidationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _camera_ready_subfield_rows(
    artifact_path: Path,
    econ_root: Path,
    aggregate_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Validate and load the corrected 878-item, vote-weighted 20 x 7 panel."""
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "camera-ready-subfields-878.v1":
        raise ValidationError("camera-ready per-model subfield schema changed")
    if (
        payload.get("model_count"),
        payload.get("subfield_count"),
        payload.get("row_count"),
    ) != (20, 7, 140):
        raise ValidationError("camera-ready per-model subfield counts must be 20/7/140")
    if payload.get("denominators") != {
        "contested": 1056,
        "directional": 878,
        "intervention_truth": 507,
        "market_truth": 371,
        "neither_truth": 178,
    }:
        raise ValidationError("camera-ready per-model subfield denominators changed")

    source = payload.get("source") or {}
    fixed_sources = {
        "dataset": CANONICAL_1056_PATH,
        "classifier": CURRENT_CLASSIFIER_PATH,
        "aggregate": CAMERA_READY_SUBFIELD_PATH,
    }
    for source_name, expected_path in fixed_sources.items():
        record = source.get(source_name) or {}
        if record.get("path") != str(expected_path):
            raise ValidationError(f"subfield source path changed for {source_name}")
        resolved = econ_root / expected_path
        if not resolved.is_file() or record.get("sha256") != _sha256(resolved):
            raise ValidationError(f"subfield source hash drift for {source_name}")

    prediction_sources = source.get("predictions") or []
    expected_source_models = {spec[1] for spec in MODEL_SPECS}
    if len(prediction_sources) != 20 or {
        row.get("source_model_id") for row in prediction_sources
    } != expected_source_models:
        raise ValidationError("subfield prediction provenance must cover the 20 paper models")
    for record in prediction_sources:
        source_model_id = record["source_model_id"]
        if record.get("row_count") != 10490:
            raise ValidationError(f"subfield prediction row count changed for {source_model_id}")
        path = econ_root / str(record.get("path", ""))
        if not path.is_file() or record.get("sha256") != _sha256(path):
            raise ValidationError(f"subfield prediction hash drift for {source_model_id}")

    rows = payload.get("rows") or []
    expected_theme_ids = [theme_id for theme_id, _ in SUBFIELD_THEMES]
    expected_keys = {
        (source_model_id, theme_id)
        for _, source_model_id, _, _, _ in MODEL_SPECS
        for theme_id in expected_theme_ids
    }
    row_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("source_model_id"), row.get("subfield_id"))
        if key in row_index:
            raise ValidationError(f"duplicate camera-ready subfield row: {key}")
        row_index[key] = row
    if set(row_index) != expected_keys:
        raise ValidationError("camera-ready per-model subfield model/theme coverage changed")

    aggregate = {row["id"]: row for row in _aggregate_subfields(aggregate_path)}
    by_model: dict[str, list[dict[str, Any]]] = {}
    for _, source_model_id, _, _, _ in MODEL_SPECS:
        themes = []
        for theme_id, theme_name in SUBFIELD_THEMES:
            row = row_index[(source_model_id, theme_id)]
            intervention_sample = float(row["intervention_sample_size"])
            market_sample = float(row["market_sample_size"])
            intervention_correct = float(row["intervention_correct_weight"])
            market_correct = float(row["market_correct_weight"])
            error_weight = float(row["error_weight"])
            intervention_errors = float(row["intervention_leaning_error_weight"])
            market_errors = float(row["market_leaning_error_weight"])
            neither_errors = float(row["neither_leaning_error_weight"])
            expected_intervention_accuracy = 100 * intervention_correct / intervention_sample
            expected_market_accuracy = 100 * market_correct / market_sample
            expected_gap = expected_intervention_accuracy - expected_market_accuracy
            expected_error_weight = (
                intervention_sample + market_sample - intervention_correct - market_correct
            )
            expected_b_dir = (
                100 * (intervention_errors - market_errors) / error_weight
                if error_weight
                else 0.0
            )
            numeric_checks = {
                "sample_size": intervention_sample + market_sample,
                "intervention_accuracy": expected_intervention_accuracy,
                "market_accuracy": expected_market_accuracy,
                "accuracy_gap_pp": expected_gap,
                "error_weight": expected_error_weight,
                "b_dir_pct": expected_b_dir,
            }
            for field, expected_value in numeric_checks.items():
                if not math.isclose(float(row[field]), expected_value, abs_tol=1e-9):
                    raise ValidationError(
                        f"subfield formula mismatch for {source_model_id}/{theme_id}/{field}"
                    )
            if not math.isclose(
                intervention_errors + market_errors + neither_errors,
                error_weight,
                abs_tol=1e-9,
            ):
                raise ValidationError(
                    f"subfield error-orientation decomposition failed for {source_model_id}/{theme_id}"
                )
            if int(row["n_intervention_triplets"]) + int(row["n_market_triplets"]) != int(
                row["n_triplets"]
            ):
                raise ValidationError(
                    f"subfield triplet decomposition failed for {source_model_id}/{theme_id}"
                )
            themes.append(
                {
                    "id": theme_id,
                    "name": theme_name,
                    "sample_size": float(row["sample_size"]),
                    "n_triplets": int(row["n_triplets"]),
                    "intervention_sample_size": intervention_sample,
                    "market_sample_size": market_sample,
                    "intervention_accuracy": round(float(row["intervention_accuracy"]), 6),
                    "market_accuracy": round(float(row["market_accuracy"]), 6),
                    "accuracy_gap_pp": round(float(row["accuracy_gap_pp"]), 6),
                    "b_dir_pct": round(float(row["b_dir_pct"]), 6),
                }
            )
        by_model[source_model_id] = themes

    for theme_id, _ in SUBFIELD_THEMES:
        selected = [row_index[(source_model_id, theme_id)] for source_model_id in expected_source_models]
        pooled_intervention = sum(float(row["intervention_accuracy"]) for row in selected) / 20
        pooled_market = sum(float(row["market_accuracy"]) for row in selected) / 20
        expected = aggregate[theme_id]
        pooled_checks = (
            (pooled_intervention, float(expected["intervention_accuracy"])),
            (pooled_market, float(expected["market_accuracy"])),
            (int(selected[0]["n_intervention_triplets"]), int(expected["n_intervention"])),
            (int(selected[0]["n_market_triplets"]), int(expected["n_market"])),
        )
        if not all(math.isclose(actual, wanted, abs_tol=1e-9) for actual, wanted in pooled_checks):
            raise ValidationError(f"pooled camera-ready subfield reproduction failed for {theme_id}")

    source_record = {
        "camera_ready_per_model": str(PUBLIC_SUBFIELD_DATA_PATH),
        "camera_ready_per_model_sha256": _sha256(artifact_path),
        "method": "top-tied vote-weighted JEL themes on the corrected 878 directional cases",
    }
    return by_model, source_record


def _normalize_sign(value: object) -> str:
    return str(value).strip().lower()


def _paper_denominators(dataset_path: Path, classifier_path: Path) -> dict[str, int]:
    """Reproduce the camera-ready 1,056 -> 878/178 decomposition."""
    dataset = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    classifier = [
        json.loads(line)
        for line in classifier_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_key = {row["triplet_key"]: row for row in classifier}
    if len(dataset) != 1056 or len(by_key) != 1056:
        raise ValidationError(
            f"expected 1,056 dataset/classifier rows, found {len(dataset)}/{len(by_key)}"
        )

    sides: list[str] = []
    for row in dataset:
        annotation = by_key.get(row["triplet_key"])
        if annotation is None:
            raise ValidationError(f"missing classifier row for {row['triplet_key']}")
        empirical = _normalize_sign(row["sign"])
        intervention = _normalize_sign(annotation["lib_vote"])
        market = _normalize_sign(annotation["con_vote"])
        if intervention == market:
            raise ValidationError(f"non-contested classifier votes for {row['triplet_key']}")
        sides.append(
            "intervention"
            if empirical == intervention
            else "market"
            if empirical == market
            else "neither"
        )

    contested_pool = len(sides)
    intervention_truth = sides.count("intervention")
    market_truth = sides.count("market")
    directional_total = intervention_truth + market_truth
    sensitive_neither = sides.count("neither")
    benchmark_total = 10490
    denominators = {
        "benchmark_total": benchmark_total,
        "contested_pool": contested_pool,
        "directional_total": directional_total,
        "intervention_truth": intervention_truth,
        "market_truth": market_truth,
        "sensitive_neither": sensitive_neither,
        "non_contested": benchmark_total - contested_pool,
    }
    canonical = {
        "benchmark_total": 10490,
        "contested_pool": 1056,
        "directional_total": 878,
        "intervention_truth": 507,
        "market_truth": 371,
        "sensitive_neither": 178,
        "non_contested": 9434,
    }
    if denominators != canonical:
        raise ValidationError(
            f"Task 1 subset decomposition differs from the paper: {denominators}"
        )
    return denominators


def _aggregate_subfields(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        if row["subfield"] == "other":
            continue
        output.append(
            {
                "id": row["subfield"],
                "name": row["display"],
                "n_intervention": int(row["n_intervention"]),
                "n_market": int(row["n_market"]),
                "n_total": int(row["n_total"]),
                "intervention_accuracy": float(row["intervention_accuracy"]),
                "market_accuracy": float(row["market_accuracy"]),
                "accuracy_gap_pp": float(row["delta_acc"]),
            }
        )
    expected_order = [
        "healthcare",
        "welfare_redistribution",
        "labor",
        "financial_regulation",
        "education",
        "taxation",
        "trade",
    ]
    output.sort(key=lambda row: expected_order.index(row["id"]))
    if [row["id"] for row in output] != expected_order:
        raise ValidationError("camera-ready aggregate subfield coverage/order changed")
    return output


def build_expected_payload(
    econ_root: Path, paper_tex_root: Path | None = None
) -> dict[str, Any]:
    table_root = paper_tex_root or (econ_root / CAMERA_READY_TABLE_DIR)
    table_5_path = table_root / "main_results.tex"
    table_2_path = table_root / "ICL_results.tex"
    table_5 = _table_rows(table_5_path, expected_cells=6)
    table_2 = _table_rows(table_2_path, expected_cells=10)
    case_metadata, example_outputs = _example_rows(
        econ_root / EXAMPLE_TRIPLETS_CSV_PATH,
        econ_root / EXAMPLE_RESULTS_CSV_PATH,
    )
    denominators = _paper_denominators(
        econ_root / CANONICAL_1056_PATH,
        econ_root / CURRENT_CLASSIFIER_PATH,
    )
    aggregate_subfields = _aggregate_subfields(econ_root / CAMERA_READY_SUBFIELD_PATH)
    site_root = Path(__file__).resolve().parents[1]
    subfields_by_model, subfield_source = _camera_ready_subfield_rows(
        site_root / PUBLIC_SUBFIELD_DATA_PATH,
        econ_root,
        econ_root / CAMERA_READY_SUBFIELD_PATH,
    )

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
        models.append(
            {
                "id": public_id,
                "source_model_id": source_id,
                "display_name": "4.1" if public_id == "grok-4-1-fast" else display_name,
                "family": family,
                "access": access,
                "reported_in_paper": True,
                "source": "COLM 2026 camera-ready Tables 5 and 2; Task 1 no-example export",
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
        "schema_version": "2.1.0",
        "dataset_version": "colm-camera-ready-20-models",
        "reported_in_paper": True,
        "evaluation_date": None,
        "source": {
            "paper": "COLM 2026 camera-ready",
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
                **subfield_source,
            },
            "notes": (
                "This baseline contains the 20 camera-ready paper models; newer "
                "evaluation rows are stored separately and merged only in the website view. "
                "Overview, ICL None baselines, and per-model "
                "subfield metrics use the corrected 1,056/878 camera-ready definitions. "
                "Matched ICL conditions, examples, and release metadata retain their "
                "documented source artifacts."
            ),
        },
        "denominators": denominators,
        "aggregate_subfields": aggregate_subfields,
        "definitions": {
            "accuracy_gap_pp": "intervention_accuracy - market_accuracy",
            "b_dir_pct": B_DIR_DEFINITION,
            "delta_example": "intervention_ex - market_ex for the same target side",
            "icl_note": (
                "None uses the corrected 878 directional cases (507 intervention-truth and "
                "371 market-truth); example conditions preserve the original matched experiment "
                "and must not be compared as a shared denominator."
            ),
            "subfield_note": (
                "Exactly seven named themes are shown; Other is excluded. Per-model and "
                "aggregate subfield metrics use the corrected 878 directional cases and "
                "top-tied vote-weighted JEL assignments, so sample_size may be non-integer."
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

    _assert_equal(payload.get("schema_version"), "2.1.0", "schema_version", errors)
    _assert_equal(
        payload.get("dataset_version"),
        "colm-camera-ready-20-models",
        "dataset_version",
        errors,
    )
    _assert_equal(payload.get("reported_in_paper"), True, "reported_in_paper", errors)
    _assert_equal(payload.get("denominators"), expected["denominators"], "denominators", errors)
    _assert_equal(
        payload.get("aggregate_subfields"),
        expected["aggregate_subfields"],
        "aggregate_subfields",
        errors,
    )
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
    _assert_equal(
        (payload.get("definitions") or {}).get("subfield_note"),
        expected["definitions"]["subfield_note"],
        "definitions.subfield_note",
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
        errors.append("models: newer Opus 4.8 must not be present in the immutable paper baseline")

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


def validate_extension(payload: dict[str, Any]) -> list[str]:
    """Recompute the 36 hosted and nine local website-evaluation conditions."""
    errors: list[str] = []
    if payload.get("schema_version") != "website-experiment-results.v1":
        return ["extension.schema_version: unexpected value"]

    expected_denominators = {
        "contested": 1056,
        "directional": 878,
        "intervention_truth": 507,
        "market_truth": 371,
        "neither_truth": 178,
    }
    if (payload.get("evaluation") or {}).get("denominators") != expected_denominators:
        errors.append("extension.evaluation.denominators: expected 1056/878/507/371/178")

    sources = payload.get("sources") or {}
    for name in (
        "results",
        "four_model_addendum",
        "all_model_subfields",
        "full_manifest",
        "condition_contracts",
        "dataset",
        "classifier",
        "local_results_manifest",
        "local_metrics_878",
    ):
        source = sources.get(name) or {}
        path_text = source.get("absolute_path")
        if not path_text:
            errors.append(f"extension.sources.{name}: missing absolute_path")
            continue
        path = Path(path_text)
        if not path.is_file():
            errors.append(f"extension.sources.{name}: missing source file {path}")
            continue
        if source.get("sha256") != _sha256(path):
            errors.append(f"extension.sources.{name}: SHA256 drift")
    if errors:
        return errors

    dataset_rows = [
        json.loads(line)
        for line in Path(sources["dataset"]["absolute_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    classifier_rows = [
        json.loads(line)
        for line in Path(sources["classifier"]["absolute_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    classifier_by_key = {row["triplet_key"]: row for row in classifier_rows}
    item_meta: dict[str, dict[str, str]] = {}
    for row in dataset_rows:
        annotation = classifier_by_key[row["triplet_key"]]
        empirical = _normalize_sign(row["sign"])
        intervention = _normalize_sign(annotation["lib_vote"])
        market = _normalize_sign(annotation["con_vote"])
        side = (
            "intervention"
            if empirical == intervention
            else "market"
            if empirical == market
            else "neither"
        )
        item_meta[row["case_id"]] = {
            "expected": empirical,
            "intervention": intervention,
            "market": market,
            "side": side,
        }

    rows_by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_name in ("results", "four_model_addendum"):
        with Path(sources[source_name]["absolute_path"]).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    key = row.get("condition_key") or row.get("condition_id")
                    rows_by_condition[key].append(row)
    if sum(map(len, rows_by_condition.values())) != 42240:
        errors.append("extension results: expected exactly 42,240 hosted rows")

    main = (payload.get("main_benchmark") or {}).get("results") or []
    sweep_wrapper = payload.get("reasoning_effort_sweeps") or {}
    sweeps = sweep_wrapper.get("sweeps") or []
    sweep_rows = [row for sweep in sweeps for row in sweep.get("results", [])]
    if len(main) != 36 or (payload.get("main_benchmark") or {}).get("condition_count") != 36:
        errors.append("extension main benchmark: expected exactly 36 conditions")
    main_by_key = {row.get("condition_key"): row for row in main if isinstance(row, dict)}
    for condition_key, row in main_by_key.items():
        examples = row.get("examples") or []
        subfields = row.get("subfields") or []
        if len(examples) != 2 or {example.get("case_id") for example in examples} != {
            "t1_9849",
            "t1_515",
        }:
            errors.append(
                f"extension {condition_key}: updated dialog needs exactly the two public examples"
            )
        if len(subfields) != 7 or [field.get("id") for field in subfields] != [
            theme_id for theme_id, _ in SUBFIELD_THEMES
        ]:
            errors.append(
                f"extension {condition_key}: updated dialog needs seven ordered subfields"
            )
    for condition_key, display_name in {
        "or_grok420_reasoning_disabled": "Grok 4.2",
        "or_grok43_none": "Grok 4.3",
    }.items():
        row = main_by_key.get(condition_key)
        if not row or row.get("display_name") != display_name:
            errors.append(
                f"extension {condition_key}: expected display_name {display_name!r}"
            )
    claude_keys = [
        row.get("condition_key")
        for row in main
        if isinstance(row, dict) and row.get("family") == "Claude"
    ]
    if claude_keys and claude_keys[-1] != "an_fable5_adaptive_low":
        errors.append("extension Claude rows: Fable 5 must be the final Claude entry")
    if [sweep.get("condition_count") for sweep in sweeps] != [5, 5, 4, 3]:
        errors.append("extension effort sweeps: expected condition counts 5/5/4/3")
    if sweep_wrapper.get("condition_count") != 17 or len(sweep_rows) != 17:
        errors.append("extension effort sweeps: expected exactly 17 condition rows")
    excluded = (payload.get("main_benchmark") or {}).get("excluded_models") or []
    excluded_ids = [row.get("model_id") if isinstance(row, dict) else row for row in excluded]
    if excluded_ids != ["gemini-2.5-flash", "gemini-3.1-pro-preview"]:
        errors.append("extension excluded models: expected Gemini 2.5 Flash and 3.1 Pro")

    public_rows: dict[str, dict[str, Any]] = {}
    for row in [*main, *sweep_rows]:
        key = row.get("condition_key")
        if key in public_rows and public_rows[key] != row:
            errors.append(f"extension condition {key}: conflicting duplicate rows")
        public_rows[key] = row
    hosted_public_rows = {
        key: row for key, row in public_rows.items() if row.get("provider") != "Local GPU"
    }
    local_public_rows = {
        key: row for key, row in public_rows.items() if row.get("provider") == "Local GPU"
    }
    if len(public_rows) != 49 or set(hosted_public_rows) != set(rows_by_condition):
        errors.append("extension coverage: hosted main/sweep union must equal all 40 completed conditions")
    if len(local_public_rows) != 9:
        errors.append("extension coverage: expected nine completed local conditions")

    def pct(numerator: int, denominator: int) -> float:
        return 100.0 * numerator / denominator

    def validate_condition_rows(
        condition_key: str,
        public_row: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        if len(rows) != 1056:
            errors.append(f"extension {condition_key}: expected 1,056 rows, found {len(rows)}")
            return
        correct_all = correct_intervention = correct_market = 0
        intervention_errors = market_errors = directional_errors = 0
        seen_cases: set[str] = set()
        for row in rows:
            case_id = row["case_id"]
            if case_id in seen_cases or case_id not in item_meta:
                errors.append(f"extension {condition_key}: duplicate/unknown case {case_id}")
                continue
            seen_cases.add(case_id)
            meta = item_meta[case_id]
            prediction = _normalize_sign(row.get("predicted_sign", row.get("predicted")))
            is_correct = prediction == meta["expected"]
            correct_all += int(is_correct)
            if meta["side"] == "intervention":
                correct_intervention += int(is_correct)
            elif meta["side"] == "market":
                correct_market += int(is_correct)
            if meta["side"] in {"intervention", "market"} and not is_correct:
                directional_errors += 1
                intervention_errors += int(prediction == meta["intervention"])
                market_errors += int(prediction == meta["market"])
        observed = {
            "contested_accuracy_pct": pct(correct_all, 1056),
            "intervention_accuracy_pct": pct(correct_intervention, 507),
            "market_accuracy_pct": pct(correct_market, 371),
        }
        observed["accuracy_gap_pp"] = (
            observed["intervention_accuracy_pct"] - observed["market_accuracy_pct"]
        )
        observed["error_direction_bias_pct"] = (
            pct(intervention_errors - market_errors, directional_errors)
            if directional_errors
            else 0.0
        )
        metrics = public_row.get("metrics") or {}
        for metric, expected_value in observed.items():
            actual_value = metrics.get(metric)
            if not isinstance(actual_value, (int, float)) or not math.isclose(
                float(actual_value), expected_value, abs_tol=1e-9
            ):
                errors.append(
                    f"extension {condition_key}.{metric}: expected {expected_value}, "
                    f"found {actual_value!r}"
                )

    for condition_key, public_row in hosted_public_rows.items():
        validate_condition_rows(condition_key, public_row, rows_by_condition.get(condition_key, []))

    local_root = Path(sources["local_results_manifest"]["absolute_path"]).parent
    local_files = sorted(local_root.glob("*/results/*_results.json"))
    digest_lines = "".join(f"{_sha256(path)}  {path}\n" for path in local_files)
    digest = hashlib.sha256(digest_lines.encode("utf-8")).hexdigest()
    if len(local_files) != 9:
        errors.append(f"extension local results: expected nine result files, found {len(local_files)}")
    if digest != sources["local_results_manifest"].get("result_file_digest"):
        errors.append("extension local results: aggregate result-file digest drift")
    local_files_by_sha = {_sha256(path): path for path in local_files}
    for condition_key, public_row in local_public_rows.items():
        result_path = local_files_by_sha.get(public_row.get("condition_id"))
        if not result_path:
            errors.append(f"extension {condition_key}: local result SHA is missing")
            continue
        local_payload = json.loads(result_path.read_text(encoding="utf-8"))
        validate_condition_rows(condition_key, public_row, local_payload.get("results") or [])

    coverage = payload.get("coverage") or {}
    if coverage.get("completed_full_run_condition_count") != 49:
        errors.append("extension coverage: expected 49 completed conditions")
    if coverage.get("completed_result_row_count") != 51744:
        errors.append("extension coverage: expected 51,744 completed rows")
    if coverage.get("main_and_sweeps_unique_condition_count") != 49:
        errors.append("extension coverage: expected 49 unique public conditions")
    all_subfields = json.loads(
        Path(sources["all_model_subfields"]["absolute_path"]).read_text(encoding="utf-8")
    )
    if (
        all_subfields.get("schema_version") != "all-model-subfields-878.v1"
        or all_subfields.get("model_count") != 51
        or len(all_subfields.get("model_ids") or []) != 51
        or len(all_subfields.get("per_model") or {}) != 51
        or len(all_subfields.get("aggregate") or []) != 7
    ):
        errors.append("extension all-model subfields: expected 51 models and seven themes")
    if (payload.get("all_model_subfields") or {}).get("aggregate") != all_subfields.get("aggregate"):
        errors.append("extension all-model subfields: embedded aggregate differs from artifact")
    return errors


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
        "--extension-data",
        type=Path,
        default=repo_root
        / "main_site/ideological-bias-in-llms/data/website-experiment-results.v1.json",
        help="Hosted and local website-evaluation results payload",
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
        extension = json.loads(args.extension_data.read_text(encoding="utf-8"))
        errors.extend(validate_extension(extension))
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

    print("PASS: schema_version=2.1.0")
    print("PASS: exactly 20 camera-ready paper models remain immutable in the paper payload")
    print("PASS: Table 5 overview and B_dir values match the canonical sources")
    print(
        "PASS: B_dir denominator is all prediction errors among the 878 directionally "
        "aligned ideology-contested cases"
    )
    print("PASS: Table 2 ICL cells and recomputed delta_example values match")
    print("PASS: corrected aggregate subfields match the camera-ready 878 source")
    print("PASS: all 140 per-model subfield rows use the corrected 878 vote-weighted source")
    print("PASS: per-model subfield B_dir formulas and pooled camera-ready reproduction match")
    print("PASS: both public examples exactly match the full CSV context/rationale fields")
    print("PASS: 36 new all-model rows and four effort sweeps match 49 completed evaluations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
