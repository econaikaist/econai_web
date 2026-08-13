#!/usr/bin/env python3
"""Integrate the four exact-model addendum and rebuild 51-model subfields.

No inference is performed.  The script verifies the completed 1,056-case
prediction bundles, computes headline metrics and the camera-ready top-tied
vote-weighted JEL slices, then updates only the website extension payload and
the separate all-model subfield artifact.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SITE_ROOT = Path(__file__).resolve().parents[1]
ECON_ROOT = Path("/home/donggyu/econ_causality")
PAGE = SITE_ROOT / "main_site/ideological-bias-in-llms"
PAYLOAD_PATH = PAGE / "data/website-experiment-results.v1.json"
PAPER_SUBFIELDS_PATH = PAGE / "data/camera-ready-subfields-878.v1.json"
ALL_SUBFIELDS_PATH = PAGE / "data/all-model-subfields-878.v1.json"
DATASET_PATH = ECON_ROOT / "data/task1_ideology_subset_1056.jsonl"
CLASSIFIER_PATH = ECON_ROOT / "extended/classification_results/ideology_triplet_subset_current.jsonl"
OLD_HOSTED_PATH = ECON_ROOT / "colm_web_standard_parallel_20260805T121530Z/runs/full_20260806T094208Z/results.jsonl"
LOCAL_ROOT = ECON_ROOT / "econ_eval/evaluation_results_final/local4bit_1056_20260803"
NEW_RUN = ECON_ROOT / "web_four_model_eval_20260812T145553Z"
NEW_PRIMARY = NEW_RUN / "results.jsonl"
NEW_OPUS = NEW_RUN / "opus45_corrected/results.jsonl"
SELECTED_BUNDLE = NEW_RUN / "website_selected_results.jsonl"
STABLE_ALL_SUBFIELDS_PATH = NEW_RUN / "all-model-subfields-878.v1.json"
EXAMPLE_IDS = ("t1_9849", "t1_515")
EXCLUDED_VISIBLE = {
    "oa_gpt5_nano_minimal", "oa_gpt5_mini_minimal", "an_sonnet46_disabled_low",
    "an_opus46_disabled_low", "gg_gemini3_minimal",
}
THEMES = (
    ("healthcare", "Healthcare"),
    ("welfare_redistribution", "Welfare & Redistribution"),
    ("education", "Education"),
    ("labor", "Labor"),
    ("financial_regulation", "Financial Regulation"),
    ("trade", "Trade"),
    ("taxation", "Taxation"),
)
NEW_SPECS = (
    {
        "condition_key": "openai_gpt5_minimal", "provider": "OpenAI", "family": "GPT",
        "display_name": "GPT-5", "model_id": "gpt-5-2025-08-07",
        "canonical_model_id": "gpt-5-2025-08-07", "setting": {"reasoning_effort": "minimal"},
        "release_date": "2025-08-07", "release_date_source": {
            "title": "Introducing GPT-5 for developers",
            "url": "https://openai.com/index/introducing-gpt-5-for-developers/",
        },
    },
    {
        "condition_key": "openai_gpt51_none", "provider": "OpenAI", "family": "GPT",
        "display_name": "GPT-5.1", "model_id": "gpt-5.1-2025-11-13",
        "canonical_model_id": "gpt-5.1-2025-11-13", "setting": {"reasoning_effort": "none"},
        "release_date": "2025-11-13", "release_date_source": {
            "title": "Introducing GPT-5.1 for developers",
            "url": "https://openai.com/index/gpt-5-1-for-developers/",
        },
    },
    {
        "condition_key": "anthropic_sonnet45_disabled", "provider": "Anthropic", "family": "Claude",
        "display_name": "Claude Sonnet 4.5", "model_id": "claude-sonnet-4-5-20250929",
        "canonical_model_id": "claude-sonnet-4-5-20250929", "setting": {"thinking": "disabled"},
        "release_date": "2025-09-29", "release_date_source": {
            "title": "Introducing Claude Sonnet 4.5",
            "url": "https://www.anthropic.com/news/claude-sonnet-4-5",
        },
    },
    {
        "condition_key": "anthropic_opus45_disabled_low", "provider": "Anthropic", "family": "Claude",
        "display_name": "Claude Opus 4.5", "model_id": "claude-opus-4-5-20251101",
        "canonical_model_id": "claude-opus-4-5-20251101",
        "setting": {"thinking": "disabled", "effort": "low"},
        "release_date": "2025-11-24", "release_date_source": {
            "title": "Introducing Claude Opus 4.5",
            "url": "https://www.anthropic.com/news/claude-opus-4-5",
        },
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_sign(value: Any) -> str:
    return str(value).strip().lower()


def split_jel_codes(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                raw_value = parsed
    raw_items = raw_value if isinstance(raw_value, (list, tuple, set)) else [raw_value]
    tokens: list[str] = []
    for item in raw_items:
        for piece in str(item).replace(";", ",").split(","):
            cleaned = piece.strip().upper()
            if cleaned and cleaned != "NAN" and cleaned not in tokens:
                tokens.append(cleaned)
    return tokens


def theme_weights(raw_jel_codes: Any) -> dict[str, float]:
    prefixes = {
        "taxation": ("H2",), "healthcare": ("I1",), "education": ("I2",),
        "welfare_redistribution": ("H5", "I3"), "labor": ("J",),
        "financial_regulation": ("G",), "trade": ("F1",),
    }
    counts = {theme: sum(any(code.startswith(prefix) for prefix in theme_prefixes)
                         for code in split_jel_codes(raw_jel_codes))
              for theme, theme_prefixes in prefixes.items()}
    positive = {theme: count for theme, count in counts.items() if count > 0}
    if not positive:
        return {"other": 1.0}
    maximum = max(positive.values())
    tied = [theme for theme in prefixes if positive.get(theme) == maximum]
    return {theme: 1.0 / len(tied) for theme in tied}


def metadata() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    dataset = read_jsonl(DATASET_PATH)
    classifier = {row["triplet_key"]: row for row in read_jsonl(CLASSIFIER_PATH)}
    if len(dataset) != 1056 or len(classifier) != 1056:
        raise RuntimeError("dataset/classifier count drift")
    by_case: dict[str, dict[str, Any]] = {}
    raw_by_case: dict[str, dict[str, Any]] = {}
    counts = defaultdict(int)
    for row in dataset:
        ann = classifier[row["triplet_key"]]
        empirical = normalize_sign(row["sign"])
        intervention = normalize_sign(ann["lib_vote"])
        market = normalize_sign(ann["con_vote"])
        side = "intervention" if empirical == intervention else "market" if empirical == market else "neither"
        counts[side] += 1
        by_case[row["case_id"]] = {
            "expected": empirical, "intervention": intervention, "market": market,
            "side": side, "theme_weights": theme_weights(ann.get("jel_codes")),
        }
        raw_by_case[row["case_id"]] = row
    if dict(counts) != {"intervention": 507, "market": 371, "neither": 178}:
        raise RuntimeError(f"side count drift: {dict(counts)}")
    return by_case, raw_by_case


def prediction(row: dict[str, Any]) -> str:
    output = row.get("output_data") or {}
    return normalize_sign(row.get("predicted_sign", row.get("predicted", output.get("predicted_sign"))))


def rationale(row: dict[str, Any]) -> str:
    output = row.get("output_data") or {}
    return str(row.get("reasoning", output.get("reasoning", "")))


def compute(rows: list[dict[str, Any]], meta: dict[str, dict[str, Any]]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    by_case = {str(row["case_id"]): row for row in rows}
    if len(rows) != 1056 or set(by_case) != set(meta):
        raise RuntimeError(f"prediction coverage drift: rows={len(rows)}, unique={len(by_case)}")
    correct_all = correct_int = correct_mkt = int_errors = mkt_errors = directional_errors = 0
    cells = {theme_id: {"iw": 0.0, "mw": 0.0, "ic": 0.0, "mc": 0.0}
             for theme_id, _ in THEMES}
    for case_id, item in meta.items():
        pred = prediction(by_case[case_id])
        correct = pred == item["expected"]
        correct_all += int(correct)
        correct_int += int(correct and item["side"] == "intervention")
        correct_mkt += int(correct and item["side"] == "market")
        if item["side"] in {"intervention", "market"} and not correct:
            directional_errors += 1
            int_errors += int(pred == item["intervention"])
            mkt_errors += int(pred == item["market"])
        if item["side"] not in {"intervention", "market"}:
            continue
        for theme_id, weight in item["theme_weights"].items():
            if theme_id not in cells:
                continue
            prefix = "i" if item["side"] == "intervention" else "m"
            cells[theme_id][prefix + "w"] += weight
            cells[theme_id][prefix + "c"] += weight * int(correct)
    metrics = {
        "contested_accuracy_pct": 100 * correct_all / 1056,
        "intervention_accuracy_pct": 100 * correct_int / 507,
        "market_accuracy_pct": 100 * correct_mkt / 371,
    }
    metrics["accuracy_gap_pp"] = metrics["intervention_accuracy_pct"] - metrics["market_accuracy_pct"]
    metrics["error_direction_bias_pct"] = (100 * (int_errors - mkt_errors) / directional_errors
                                              if directional_errors else 0.0)
    subfields = []
    for theme_id, theme_name in THEMES:
        cell = cells[theme_id]
        ia = 100 * cell["ic"] / cell["iw"]
        ma = 100 * cell["mc"] / cell["mw"]
        subfields.append({
            "id": theme_id, "name": theme_name,
            "sample_size": cell["iw"] + cell["mw"],
            "intervention_sample_size": cell["iw"], "market_sample_size": cell["mw"],
            "intervention_accuracy": ia, "market_accuracy": ma,
            "accuracy_gap_pp": ia - ma,
        })
    return metrics, subfields


def selected_new_rows() -> dict[str, list[dict[str, Any]]]:
    wanted = {spec["condition_key"] for spec in NEW_SPECS}
    expected_models = {
        spec["condition_key"]: spec["canonical_model_id"] for spec in NEW_SPECS
    }
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in (NEW_PRIMARY, NEW_OPUS):
        for row in read_jsonl(path):
            key = row.get("condition_id")
            if key in wanted and row.get("status") == "completed":
                rows[key].append(row)
    if set(rows) != wanted or any(len(value) != 1056 for value in rows.values()):
        raise RuntimeError("four-model addendum is not complete")
    for key, condition_rows in rows.items():
        if len({row["case_id"] for row in condition_rows}) != 1056:
            raise RuntimeError(f"four-model addendum has duplicate cases: {key}")
        if {row.get("returned_model") for row in condition_rows} != {expected_models[key]}:
            raise RuntimeError(f"returned-model drift in four-model addendum: {key}")
        if any(row.get("http_status") != 200 or row.get("error") for row in condition_rows):
            raise RuntimeError(f"non-success response in four-model addendum: {key}")
    selected = [row for key in sorted(rows) for row in sorted(rows[key], key=lambda item: item["case_id"])]
    SELECTED_BUNDLE.write_text("".join(canonical(row) + "\n" for row in selected), encoding="utf-8")
    return rows


def extension_rows(payload: dict[str, Any], new_rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    hosted: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(OLD_HOSTED_PATH):
        hosted[row["condition_key"]].append(row)
    local_by_sha = {sha256(path): json.loads(path.read_text(encoding="utf-8"))["results"]
                    for path in LOCAL_ROOT.glob("*/results/*_results.json")}
    output: dict[str, list[dict[str, Any]]] = {}
    for record in payload["main_benchmark"]["results"]:
        key = record["condition_key"]
        output[key] = (local_by_sha[record["condition_id"]]
                       if record["provider"] == "Local GPU" else hosted[key])
    output.update(new_rows)
    return output


def main() -> None:
    meta, raw_items = metadata()
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    new_rows = selected_new_rows()
    new_records = []
    for spec in NEW_SPECS:
        rows = new_rows[spec["condition_key"]]
        metrics, subfields = compute(rows, meta)
        examples = []
        by_case = {row["case_id"]: row for row in rows}
        for case_id in EXAMPLE_IDS:
            row = by_case[case_id]
            examples.append({
                "case_id": case_id, "predicted_sign": row["predicted_sign"],
                "rationale": row["reasoning"],
                "correct": prediction(row) == meta[case_id]["expected"],
            })
        record = {**spec, "condition_id": spec["condition_key"],
                  "metrics": metrics, "examples": examples, "subfields": subfields,
                  "result_bundle_sha256": sha256(SELECTED_BUNDLE)}
        new_records.append(record)
    existing = [
        row for row in payload["main_benchmark"]["results"]
        if row["condition_key"] not in {spec["condition_key"] for spec in NEW_SPECS}
    ]
    by_key = {row["condition_key"]: row for row in new_records}
    ordered = []
    for row in existing:
        if row["condition_key"] == "oa_gpt54_nano_none":
            ordered.extend([by_key["openai_gpt5_minimal"], by_key["openai_gpt51_none"]])
        if row["condition_key"] == "an_sonnet46_disabled_low":
            ordered.extend([
                by_key["anthropic_sonnet45_disabled"],
                by_key["anthropic_opus45_disabled_low"],
            ])
        ordered.append(row)
    payload["main_benchmark"]["results"] = ordered
    payload["main_benchmark"]["condition_count"] = 36

    all_extension = extension_rows(payload, new_rows)
    extension_subfields: dict[str, list[dict[str, Any]]] = {}
    for record in payload["main_benchmark"]["results"]:
        _, subfields = compute(all_extension[record["condition_key"]], meta)
        record["subfields"] = subfields
        extension_subfields[record["condition_key"]] = subfields
    main_by_key = {
        record["condition_key"]: record for record in payload["main_benchmark"]["results"]
    }
    for sweep in payload["reasoning_effort_sweeps"]["sweeps"]:
        sweep["results"] = [
            main_by_key.get(record["condition_key"], record)
            for record in sweep["results"]
        ]

    paper_artifact = json.loads(PAPER_SUBFIELDS_PATH.read_text(encoding="utf-8"))
    paper_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in paper_artifact["rows"]:
        paper_by_model[row["public_model_id"]].append({
            "id": row["subfield_id"], "name": row["subfield_name"],
            "sample_size": row["sample_size"],
            "intervention_sample_size": row["intervention_sample_size"],
            "market_sample_size": row["market_sample_size"],
            "intervention_accuracy": row["intervention_accuracy"],
            "market_accuracy": row["market_accuracy"],
            "accuracy_gap_pp": row["accuracy_gap_pp"],
        })
    visible_extension = {
        record["condition_key"]: record["subfields"]
        for record in payload["main_benchmark"]["results"]
        if record["condition_key"] not in EXCLUDED_VISIBLE
    }
    if len(paper_by_model) != 20 or len(visible_extension) != 31:
        raise RuntimeError("51-model visible set drift")
    all_models = {**{f"paper:{key}": value for key, value in paper_by_model.items()},
                  **{f"new:{key}": value for key, value in visible_extension.items()}}
    aggregate = []
    for theme_id, theme_name in THEMES:
        values = []
        for model_id, rows in all_models.items():
            matches = [row for row in rows if row["id"] == theme_id]
            if len(matches) != 1:
                raise RuntimeError(f"missing theme {theme_id} for {model_id}")
            values.append(matches[0])
        ia = sum(float(row["intervention_accuracy"]) for row in values) / len(values)
        ma = sum(float(row["market_accuracy"]) for row in values) / len(values)
        aggregate.append({
            "id": theme_id, "name": theme_name, "model_count": len(values),
            "sample_size": values[0]["sample_size"],
            "intervention_accuracy": ia, "market_accuracy": ma,
            "accuracy_gap_pp": ia - ma,
        })
    aggregate.sort(key=lambda row: row["accuracy_gap_pp"], reverse=True)
    all_artifact = {
        "schema_version": "all-model-subfields-878.v1",
        "method": "equal-weight mean across 51 visible models; every model uses top-tied vote-weighted JEL themes on the current 878 directional cases",
        "denominators": payload["evaluation"]["denominators"],
        "model_count": 51, "theme_count": 7,
        "model_ids": sorted(all_models), "aggregate": aggregate,
        "per_model": all_models,
        "sources": {
            "paper_subfields": {
                "path": "data/camera-ready-subfields-878.v1.json",
                "sha256": sha256(PAPER_SUBFIELDS_PATH),
            },
            "old_hosted": {"path": str(OLD_HOSTED_PATH), "sha256": sha256(OLD_HOSTED_PATH)},
            "new_selected": {"path": str(SELECTED_BUNDLE), "sha256": sha256(SELECTED_BUNDLE), "rows": 4224},
            "dataset": {"path": str(DATASET_PATH), "sha256": sha256(DATASET_PATH)},
            "classifier": {"path": str(CLASSIFIER_PATH), "sha256": sha256(CLASSIFIER_PATH)},
        },
    }
    serialized_subfields = json.dumps(all_artifact, ensure_ascii=False, indent=2) + "\n"
    STABLE_ALL_SUBFIELDS_PATH.write_text(serialized_subfields, encoding="utf-8")
    ALL_SUBFIELDS_PATH.write_text(serialized_subfields, encoding="utf-8")
    payload["sources"]["four_model_addendum"] = {
        "absolute_path": str(SELECTED_BUNDLE), "sha256": sha256(SELECTED_BUNDLE),
        "row_count": 4224,
    }
    payload["sources"]["all_model_subfields"] = {
        "absolute_path": str(STABLE_ALL_SUBFIELDS_PATH), "sha256": sha256(ALL_SUBFIELDS_PATH),
        "model_count": 51, "row_count": 357,
    }
    payload["coverage"].update({
        "completed_full_run_condition_count": 49,
        "completed_result_row_count": 51744,
        "main_and_sweeps_unique_condition_count": 49,
        "main_benchmark_condition_count": 36,
        "visible_main_model_count": 51,
    })
    payload["all_model_subfields"] = {
        "source": "data/all-model-subfields-878.v1.json", "model_count": 51,
        "method": all_artifact["method"], "aggregate": aggregate,
    }
    payload["generated_at_utc"] = "2026-08-12T00:00:00Z"
    PAYLOAD_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS new_bundle_rows=4224 sha256={sha256(SELECTED_BUNDLE)}")
    print(f"PASS visible_models=51 aggregate_sha256={sha256(ALL_SUBFIELDS_PATH)}")


if __name__ == "__main__":
    main()
