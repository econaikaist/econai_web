#!/usr/bin/env python3
"""Validate the public EconCausal paper-page data payload.

The submitted PDF is the authority for reported metrics.  Released benchmark
JSONL files are used only to validate task counts and the curated examples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


PDF_SHA256 = "ab4d93b8187b15329b5599d04ff5c1189d5d2d10efd076877fb7e748b834f9ed"
TASK2_SHA256 = "d0ce22483255a45c438e01f0e8d9b5e8baf015228728b399f732414814df86d6"
TRIPLETS_SHA256 = "dc360df8654bac95b5dffebf692f3bac465303552f8686f3e476b3ca597720de"

METRIC_KEYS = (
    "task1_econ",
    "task1_finance",
    "task2_overall",
    "task2_sign_mismatch",
    "task3",
)

# Table 2 values, ordered as accuracy/F1 for each key in METRIC_KEYS.
MODEL_ROWS: dict[str, tuple[str, str, tuple[float, ...]]] = {
    "gemini-3-flash": ("Gemini 3 Flash", "closed_source", (0.884, 0.548, 0.868, 0.613, 0.824, 0.587, 0.634, 0.511, 0.624, 0.452)),
    "gemini-2-5-pro": ("Gemini 2.5 Pro", "closed_source", (0.829, 0.482, 0.808, 0.503, 0.747, 0.521, 0.535, 0.443, 0.552, 0.408)),
    "gemini-2-5-flash": ("Gemini 2.5 Flash", "closed_source", (0.810, 0.432, 0.800, 0.521, 0.725, 0.498, 0.426, 0.342, 0.386, 0.295)),
    "gpt-5-2": ("GPT-5.2", "closed_source", (0.771, 0.440, 0.782, 0.518, 0.782, 0.571, 0.485, 0.414, 0.572, 0.426)),
    "gpt-5-mini": ("GPT-5 mini", "closed_source", (0.753, 0.442, 0.750, 0.456, 0.750, 0.517, 0.416, 0.338, 0.534, 0.382)),
    "gpt-5-nano": ("GPT-5 nano", "closed_source", (0.736, 0.422, 0.720, 0.435, 0.729, 0.477, 0.366, 0.284, 0.447, 0.326)),
    "gpt-4o": ("GPT-4o", "closed_source", (0.665, 0.411, 0.704, 0.443, 0.658, 0.469, 0.346, 0.303, 0.357, 0.290)),
    "gpt-4o-mini": ("GPT-4o mini", "closed_source", (0.679, 0.364, 0.634, 0.339, 0.690, 0.467, 0.168, 0.150, 0.338, 0.250)),
    "grok-4-1-fast": ("Grok-4.1 Fast", "closed_source", (0.834, 0.476, 0.813, 0.521, 0.775, 0.525, 0.465, 0.363, 0.541, 0.405)),
    "grok-3": ("Grok-3", "closed_source", (0.802, 0.424, 0.767, 0.461, 0.739, 0.501, 0.346, 0.267, 0.531, 0.394)),
    "grok-3-mini": ("Grok-3 mini", "closed_source", (0.828, 0.485, 0.798, 0.490, 0.711, 0.490, 0.356, 0.298, 0.547, 0.411)),
    "llama-3-3-70b": ("Llama 3.3 70B", "open_source", (0.761, 0.418, 0.718, 0.436, 0.747, 0.490, 0.327, 0.245, 0.525, 0.352)),
    "llama-3-1-8b": ("Llama 3.1 8B", "open_source", (0.565, 0.290, 0.509, 0.295, 0.676, 0.353, 0.297, 0.141, 0.473, 0.242)),
    "llama-3-2-3b": ("Llama 3.2 3B", "open_source", (0.582, 0.230, 0.585, 0.252, 0.609, 0.244, 0.257, 0.114, 0.445, 0.212)),
    "llama-3-2-1b": ("Llama 3.2 1B", "open_source", (0.620, 0.191, 0.599, 0.187, 0.486, 0.132, 0.386, 0.112, 0.511, 0.171)),
    "qwen3-32b": ("Qwen3 32B", "open_source", (0.692, 0.380, 0.654, 0.402, 0.725, 0.463, 0.307, 0.230, 0.412, 0.302)),
    "qwen3-14b": ("Qwen3 14B", "open_source", (0.626, 0.348, 0.600, 0.372, 0.630, 0.423, 0.317, 0.247, 0.392, 0.298)),
    "qwen3-8b": ("Qwen3 8B", "open_source", (0.773, 0.419, 0.714, 0.413, 0.704, 0.474, 0.337, 0.265, 0.343, 0.262)),
}

GROUP_ROWS = {
    "closed_source": (11, (0.781, 0.448, 0.768, 0.482, 0.739, 0.511, 0.413, 0.338, 0.493, 0.367)),
    "open_source": (7, (0.660, 0.325, 0.626, 0.337, 0.654, 0.368, 0.318, 0.194, 0.443, 0.262)),
}

EXAMPLE_IDS = (
    "task2-10852-14804",
    "task2-21808-15831",
    "task2-18259-21811",
    "task2-27013-5692",
    "task2-9273-20787",
    "task2-14606-18674",
    "task2-7269-21433",
    "task2-20387-18463",
)

VENUE_NAMES = {
    "american_economic_review": "American Economic Review",
    "quarterly_journal_of_economics": "Quarterly Journal of Economics",
    "journal_of_political_economy": "Journal of Political Economy",
    "review_of_economic_studies": "Review of Economic Studies",
    "econometrica": "Econometrica",
    "journal_of_finance": "Journal of Finance",
    "journal_of_financial_economics": "Journal of Financial Economics",
    "review_of_financial_studies": "Review of Financial Studies",
}

SIGN_NAMES = {"+": "positive", "-": "negative", "none": "none", "mixed": "mixed"}
DISALLOWED_PUBLIC_KEYS = {
    "answer",
    "evidence",
    "model_response",
    "prompt",
    "question",
    "rationale",
    "reasoning",
}


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def flatten_metrics(row: dict[str, Any]) -> tuple[float, ...]:
    metrics = row.get("metrics")
    require(isinstance(metrics, dict), f"missing metrics for {row.get('id')}")
    require(tuple(metrics) == METRIC_KEYS, f"metric order/keys changed for {row.get('id')}")
    values: list[float] = []
    for key in METRIC_KEYS:
        cell = metrics[key]
        require(set(cell) == {"accuracy", "macro_f1"}, f"bad metric cell for {row.get('id')}/{key}")
        for metric in ("accuracy", "macro_f1"):
            value = cell[metric]
            require(isinstance(value, (int, float)) and 0 <= value <= 1, f"out-of-range {row.get('id')}/{key}/{metric}")
            values.append(float(value))
    return tuple(values)


def reject_disallowed_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(key.lower() not in DISALLOWED_PUBLIC_KEYS, f"disallowed public key at {path}.{key}")
            reject_disallowed_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_disallowed_keys(child, f"{path}[{index}]")


def validate_core(data: dict[str, Any]) -> None:
    required = {
        "meta", "stats", "tasks", "models", "group_averages", "transfer",
        "sign_accuracy", "calibration", "examples", "provenance",
    }
    require(set(data) == required, f"top-level keys must be {sorted(required)}")
    require(data["meta"]["schema_version"] == "econcausal.paper-data.v1", "schema version changed")
    require(
        data["meta"]["authors_display"]
        == "Donggyu Lee, Hyeok Yun, Meeyoung Cha, Sungwon Park, Sangyoon Park, Jihee Kim",
        "public author metadata changed",
    )
    require(data["meta"]["paper_status"] == "preprint_submitted_emnlp_2026", "paper status changed")

    stats = data["stats"]
    expected_stats = {
        "causal_triplets": 10490,
        "source_papers": 2595,
        "evaluated_models": 18,
        "benchmark_tasks": 3,
        "benchmark_instances": 2943,
    }
    for key, expected in expected_stats.items():
        require(stats.get(key) == expected, f"stats.{key} must be {expected}")
    require(stats["headline"] == {
        "top_task1_econ_accuracy_pct": 88.4,
        "closed_task2_overall_accuracy_pct": 73.9,
        "closed_task2_sign_mismatch_accuracy_pct": 41.3,
        "context_shift_drop_pp": 32.6,
        "closed_task3_accuracy_pct": 49.3,
        "open_task3_accuracy_pct": 44.3,
        "mean_none_accuracy_pct": 13.83,
    }, "headline metrics changed")
    require(sum(row["count"] for row in stats["sign_distribution"].values()) == 2943, "sign counts must sum to 2,943")

    tasks = {row["id"]: row for row in data["tasks"]}
    require(set(tasks) == {"task1", "task2", "task3"}, "task IDs changed")
    require(tasks["task1"]["instances"] == 1807, "Task 1 count changed")
    require([row["instances"] for row in tasks["task1"]["subsets"]] == [947, 860], "Task 1 split changed")
    require(tasks["task2"]["instances"] == 284 and tasks["task2"]["sign_mismatch_instances"] == 101, "Task 2 counts changed")
    require(tasks["task3"]["instances"] == 852 and tasks["task3"]["variants_per_task2_instance"] == 3, "Task 3 counts changed")

    models = data["models"]
    require(len(models) == 18, "exactly 18 model rows are required")
    require(len({row["id"] for row in models}) == 18, "model IDs must be unique")
    require({row["id"] for row in models} == set(MODEL_ROWS), "model ID set changed")
    for row in models:
        name, access, expected = MODEL_ROWS[row["id"]]
        require((row["name"], row["access"]) == (name, access), f"model metadata changed for {row['id']}")
        require(flatten_metrics(row) == expected, f"Table 2 values changed for {row['id']}")
    require(sum(row["access"] == "closed_source" for row in models) == 11, "closed-source count changed")
    require(sum(row["access"] == "open_source" for row in models) == 7, "open-source count changed")

    groups = {row["id"]: row for row in data["group_averages"]}
    require(set(groups) == set(GROUP_ROWS), "group-average IDs changed")
    for group_id, (count, expected) in GROUP_ROWS.items():
        require(groups[group_id]["model_count"] == count, f"group count changed for {group_id}")
        require(flatten_metrics(groups[group_id]) == expected, f"group values changed for {group_id}")

    transfer = data["transfer"]
    require((transfer["sign_mismatch_instances"], transfer["sign_mismatch_share_pct"]) == (101, 35.6), "mismatch headline changed")
    require([(row["overall_accuracy_pct"], row["sign_mismatch_accuracy_pct"], row["drop_pp"]) for row in transfer["groups"]] == [(73.9, 41.3, 32.6), (65.4, 31.8, 33.6)], "transfer group values changed")
    require([(row["correct_pct"], row["source_sign_error_pct"], row["other_error_pct"]) for row in transfer["prediction_distribution"]] == [(52.70, 27.28, 20.02), (37.62, 49.23, 13.15)], "Table 3 values changed")
    require(transfer["prediction_distribution_delta_pp"] == {"correct": -15.08, "source_sign_error": 21.95, "other_error": -6.87}, "Table 3 deltas changed")

    sign_rows = data["sign_accuracy"]["rows"]
    expected_sign_rows = [
        (81.58, 65.43, 9.89, 10.23, 73.47),
        (81.49, 63.48, 10.18, 21.52, 71.42),
        (81.38, 71.04, 16.90, 24.60, 70.60),
        (54.84, 44.62, 18.36, 34.92, 47.38),
    ]
    observed_sign_rows = [tuple(row[key] for key in ("positive", "negative", "none", "mixed", "overall")) for row in sign_rows]
    require(observed_sign_rows == expected_sign_rows, "Table 9 sign accuracies changed")
    for key in ("positive", "negative", "none", "mixed"):
        computed = round(sum(row[key] for row in sign_rows) / 4, 2)
        require(math.isclose(computed, data["sign_accuracy"]["mean_across_tasks"][key], abs_tol=1e-9), f"sign mean mismatch for {key}")

    calibration = data["calibration"]
    require(calibration["model_id"] == "gpt-4o", "calibration model changed")
    require(calibration["abstention_unknown_pct"] == {"economics": 6.8, "finance": 9.4}, "abstention values changed")
    require(calibration["ece_by_category"] == {
        "economics": {"positive": 0.094, "negative": 0.237, "mixed": 0.743, "none": 0.616},
        "finance": {"positive": 0.111, "negative": 0.264, "mixed": 0.580, "none": 0.839},
    }, "Figure 3 ECE values changed")

    examples = data["examples"]
    require(tuple(row["id"] for row in examples) == EXAMPLE_IDS, "example IDs/order changed")
    require(len({row["source"]["paper_id"] for row in examples}) == 8, "source paper IDs must be unique")
    require(len({row["target"]["paper_id"] for row in examples}) == 8, "target paper IDs must be unique")
    require(sum(row["domain"] == "finance" for row in examples) == 2, "exactly two finance examples are required")
    signs = {"positive", "negative", "none", "mixed"}
    require(signs <= {side["sign"] for row in examples for side in (row["source"], row["target"])}, "examples must cover all sign labels")
    for index, row in enumerate(examples, 1):
        require(row["selection"]["slot"] == index, f"selection slot mismatch for {row['id']}")
        require(0.8 <= row["similarity"] <= 1, f"similarity out of range for {row['id']}")
        require(row["source"]["paper_id"] != row["target"]["paper_id"], f"same-paper example for {row['id']}")
        require(row["source"]["sign"] != row["target"]["sign"], f"non-shift example for {row['id']}")
        require(row["transition"] == f"{row['source']['sign']}_to_{row['target']['sign']}", f"transition mismatch for {row['id']}")
        for side_name in ("source", "target"):
            side = row[side_name]
            require(set(side) == {"paper_id", "title", "year", "journal", "url", "treatment", "outcome", "sign", "context"}, f"example schema changed for {row['id']}/{side_name}")
            require(side["url"].startswith("https://www.nber.org/papers/"), f"unexpected URL for {row['id']}/{side_name}")
            require(bool(side["context"].strip()), f"empty context for {row['id']}/{side_name}")
    reject_disallowed_keys(examples, "$.examples")

    provenance = data["provenance"]
    require(provenance["numerical_authority"]["sha256"] == PDF_SHA256, "paper hash provenance changed")
    require(provenance["public_benchmark"]["task2_sha256"] == TASK2_SHA256, "Task 2 hash provenance changed")
    require(provenance["public_benchmark"]["causal_triplets_sha256"] == TRIPLETS_SHA256, "triplet hash provenance changed")
    require(tuple(provenance["example_selection"]["selected_ids"]) == EXAMPLE_IDS, "selection provenance changed")


def normalized_sign(value: str) -> str:
    key = value.strip().lower()
    require(key in SIGN_NAMES, f"unknown benchmark sign {value!r}")
    return SIGN_NAMES[key]


def display_venue(value: str) -> str:
    return VENUE_NAMES.get(value, value)


def validate_benchmark_sources(data: dict[str, Any], benchmark_root: Path) -> None:
    task2_path = benchmark_root / "data/tasks/task2.jsonl"
    triplets_path = benchmark_root / "data/causal_triplets/causal_triplets.jsonl"
    require(task2_path.is_file(), f"missing source: {task2_path}")
    require(triplets_path.is_file(), f"missing source: {triplets_path}")
    require(sha256(task2_path) == TASK2_SHA256, "released Task 2 file hash changed")
    require(sha256(triplets_path) == TRIPLETS_SHA256, "released causal-triplets file hash changed")

    task2_rows = read_jsonl(task2_path)
    triplet_rows = read_jsonl(triplets_path)
    require(len(task2_rows) == 284, "released Task 2 must contain 284 rows")
    require(len(triplet_rows) == 10490, "released causal-triplets file must contain 10,490 rows")
    mismatch_count = sum(
        json.loads(row["example_details"])[0]["sign"].lower() != row["sign"].lower()
        for row in task2_rows
    )
    require(mismatch_count == 101, "first/highest-similarity mismatch count must be 101")

    for example in data["examples"]:
        target = example["target"]
        source = example["source"]
        candidates = [
            row for row in task2_rows
            if str(row["paper_id"]) == target["paper_id"]
            and row["treatment"] == target["treatment"]
            and row["outcome"] == target["outcome"]
            and normalized_sign(row["sign"]) == target["sign"]
            and row["context"] == target["context"]
        ]
        require(len(candidates) == 1, f"expected one public Task 2 target for {example['id']}, found {len(candidates)}")
        row = candidates[0]
        require(display_venue(row["published_venue"]) == target["journal"], f"target journal mismatch for {example['id']}")
        require(int(row["publication_year"]) == target["year"] and row["title"] == target["title"] and row["paper_url"] == target["url"], f"target metadata mismatch for {example['id']}")
        reference = json.loads(row["example_details"])[0]
        require(str(reference["paper_id"]) == source["paper_id"], f"source ID mismatch for {example['id']}")
        require(reference["treatment"] == source["treatment"] and reference["outcome"] == source["outcome"], f"source relation mismatch for {example['id']}")
        require(normalized_sign(reference["sign"]) == source["sign"], f"source sign mismatch for {example['id']}")
        require(math.isclose(float(reference["avg_similarity"]), example["similarity"], abs_tol=1e-12), f"similarity mismatch for {example['id']}")

        source_candidates = [
            triplet for triplet in triplet_rows
            if str(triplet["paper_id"]) == source["paper_id"]
            and triplet["treatment"] == source["treatment"]
            and triplet["outcome"] == source["outcome"]
            and normalized_sign(triplet["sign"]) == source["sign"]
        ]
        require(len(source_candidates) == 1, f"expected one public source triplet for {example['id']}, found {len(source_candidates)}")
        source_row = source_candidates[0]
        require(source_row["context"] == source["context"], f"source context mismatch for {example['id']}")
        require(display_venue(source_row["published_venue"]) == source["journal"], f"source journal mismatch for {example['id']}")
        require(int(source_row["publication_year"]) == source["year"] and source_row["title"] == source["title"] and source_row["paper_url"] == source["url"], f"source metadata mismatch for {example['id']}")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=repo_root / "main_site/econcausal/data/paper-data.v1.json")
    parser.add_argument("--benchmark-root", type=Path, default=repo_root.parent / "econcausal-benchmark")
    parser.add_argument("--paper", type=Path, help="optional submitted PDF path; validates its SHA-256")
    parser.add_argument("--require-sources", action="store_true", help="fail when the benchmark checkout is unavailable")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        require(args.data.is_file(), f"missing data payload: {args.data}")
        data = json.loads(args.data.read_text(encoding="utf-8"))
        require(isinstance(data, dict), "payload root must be an object")
        validate_core(data)

        sources_checked = False
        if args.benchmark_root.is_dir():
            validate_benchmark_sources(data, args.benchmark_root)
            sources_checked = True
        elif args.require_sources:
            raise ValidationError(f"benchmark root not found: {args.benchmark_root}")

        paper_checked = False
        if args.paper is not None:
            require(args.paper.is_file(), f"paper not found: {args.paper}")
            require(sha256(args.paper) == PDF_SHA256, "submitted PDF hash changed")
            paper_checked = True

        print(
            "OK: EconCausal data validated "
            f"(3 tasks, 18 models, 2 group rows, 8 examples; "
            f"benchmark_sources={'yes' if sources_checked else 'skipped'}, "
            f"paper_hash={'yes' if paper_checked else 'skipped'})"
        )
        return 0
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
