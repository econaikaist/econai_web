#!/usr/bin/env python3
"""Add reproducible detail records to the hosted experiment-results payload.

The public payload keeps two representative Task 1 outputs and the seven named
JEL-theme slices for each main benchmark condition.  This intentionally uses
the same 1,056-case data, classifier labels, and completed result artifacts as
the headline metrics; it never re-runs inference.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_PATH = ROOT / "main_site/ideological-bias-in-llms/data/website-experiment-results.v1.json"
EXAMPLE_IDS = ("t1_9849", "t1_515")
THEMES = (
    ("healthcare", "Healthcare"),
    ("welfare_redistribution", "Welfare & Redistribution"),
    ("education", "Education"),
    ("labor", "Labor"),
    ("financial_regulation", "Financial Regulation"),
    ("trade", "Trade"),
    ("taxation", "Taxation"),
)


def official(date: str, title: str, url: str, note: str | None = None) -> dict[str, str]:
    record = {"date": date, "title": title, "url": url}
    if note:
        record["note"] = note
    return record


RELEASES = {
    "gpt-5-nano-2025-08-07": official("2025-08-07", "Introducing GPT-5 for developers", "https://openai.com/index/introducing-gpt-5-for-developers/"),
    "gpt-5-mini-2025-08-07": official("2025-08-07", "Introducing GPT-5 for developers", "https://openai.com/index/introducing-gpt-5-for-developers/"),
    "gpt-5.4-nano-2026-03-17": official("2026-03-17", "GPT-5.4 nano model", "https://platform.openai.com/docs/models/gpt-5.4-nano"),
    "gpt-5.4-mini-2026-03-17": official("2026-03-17", "GPT-5.4 mini model", "https://platform.openai.com/docs/models/gpt-5.4-mini"),
    "gpt-5.4-2026-03-05": official("2026-03-05", "GPT-5.4 model", "https://platform.openai.com/docs/models/gpt-5.4"),
    "gpt-5.5-2026-04-23": official("2026-04-23", "GPT-5.5 model", "https://platform.openai.com/docs/models/gpt-5.5"),
    "gpt-5.6-luna": official("2026-07-09", "Introducing GPT-5.6", "https://openai.com/index/gpt-5-6/"),
    "gpt-5.6-terra": official("2026-07-09", "Introducing GPT-5.6", "https://openai.com/index/gpt-5-6/"),
    "gpt-5.6-sol": official("2026-07-09", "Introducing GPT-5.6", "https://openai.com/index/gpt-5-6/"),
    "claude-sonnet-4-6": official("2026-02-17", "Introducing Claude Sonnet 4.6", "https://www.anthropic.com/news/claude-sonnet-4-6"),
    "claude-opus-4-6": official("2026-02-05", "Introducing Claude Opus 4.6", "https://www.anthropic.com/news/claude-opus-4-6"),
    "claude-opus-4-7": official("2026-04-16", "Introducing Claude Opus 4.7", "https://www.anthropic.com/news/claude-opus-4-7"),
    "claude-opus-4-8": official("2026-05-28", "Introducing Claude Opus 4.8", "https://www.anthropic.com/news/claude-opus-4-8"),
    "claude-fable-5": official("2026-06-09", "Introducing Claude Fable 5 and Mythos 5", "https://www.anthropic.com/news/claude-fable-5-mythos-5"),
    "claude-sonnet-5": official("2026-06-30", "Introducing Claude Sonnet 5", "https://www.anthropic.com/news/claude-sonnet-5"),
    "claude-opus-5": official("2026-07-23", "Claude Opus 5 model documentation", "https://docs.anthropic.com/en/docs/about-claude/models/overview", "The dated canonical snapshot in the completed run confirms the released model identifier."),
    "gemini-3-flash-preview": official("2025-12-17", "Gemini 3 Flash: frontier intelligence built for speed", "https://blog.google/products-and-platforms/products/gemini/gemini-3-flash/"),
    "gemini-3.1-flash-lite": official("2026-05-07", "Gemini API changelog", "https://ai.google.dev/gemini-api/docs/changelog"),
    "gemini-3.5-flash": official("2026-05-19", "Gemini API changelog", "https://ai.google.dev/gemini-api/docs/changelog"),
    "gemini-3.6-flash": official("2026-07-21", "Gemini API changelog", "https://ai.google.dev/gemini-api/docs/changelog"),
    "x-ai/grok-4.20": official("2026-03-09", "Grok 4.20 Non-Reasoning", "https://docs.x.ai/developers/models/grok-4.20-non-reasoning"),
    "x-ai/grok-4.3": official("2026-04-30", "Grok 4.3", "https://docs.x.ai/developers/models/grok-4.3"),
    "x-ai/grok-4.5": official("2026-07-08", "Grok 4.5", "https://docs.x.ai/developers/models/grok-4.5"),
    "meta-llama/llama-4-scout-17b-16e-instruct": official("2025-04-05", "Introducing Llama 4", "https://ai.meta.com/blog/llama-4-multimodal-intelligence/"),
    "qwen/qwen3.5-0.8b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.5-2b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.5-4b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.5-9b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.5-27b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.5-35b-a3b": official("2026-02-15", "Qwen3.5", "https://qwen.ai/blog?id=qwen3.5"),
    "qwen/qwen3.6-27b": official("2026-04-22", "Qwen3.6 27B", "https://qwen.ai/blog?id=qwen3.6-27b"),
    "qwen/qwen3.6-35b-a3b": official("2026-04-15", "Qwen3.6 35B-A3B", "https://qwen.ai/blog?id=qwen3.6-35b-a3b"),
}


def sign(value: Any) -> str:
    return str(value).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    sources = payload["sources"]
    dataset_path = Path(sources["dataset"]["absolute_path"])
    classifier_path = Path(sources["classifier"]["absolute_path"])
    hosted_path = Path(sources["results"]["absolute_path"])
    dataset = {row["case_id"]: row for row in load_jsonl(dataset_path)}
    classifier = {row["triplet_key"]: row for row in load_jsonl(classifier_path)}
    assert len(dataset) == len(classifier) == 1056

    # The seven public named themes are categorical classifier assignments.  "other"
    # remains excluded just as it is from the site’s camera-ready subfield panel.
    metadata = {}
    for case_id, item in dataset.items():
        label = classifier[item["triplet_key"]]
        empirical, intervention, market = map(sign, (item["sign"], label["lib_vote"], label["con_vote"]))
        side = "intervention" if empirical == intervention else "market" if empirical == market else "neither"
        metadata[case_id] = {"expected": empirical, "side": side, "theme": label.get("jel_policy_theme", "other")}

    hosted_rows: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in load_jsonl(hosted_path):
        hosted_rows[row["condition_key"]][row["case_id"]] = row
    assert len(hosted_rows) == 36 and all(len(rows) == 1056 for rows in hosted_rows.values())

    local_root = Path(sources["local_results_manifest"]["absolute_path"]).parent
    local_by_digest = {sha256(path): path for path in local_root.glob("*/results/*_results.json")}
    assert len(local_by_digest) == 9

    for result in payload["main_benchmark"]["results"]:
        condition_key = result["condition_key"]
        if result["provider"] == "Local GPU":
            local_path = local_by_digest[result["condition_id"]]
            raw = json.loads(local_path.read_text(encoding="utf-8"))["results"]
            rows = {
                row["case_id"]: {
                    "predicted_sign": row.get("predicted_sign", row.get("predicted")),
                    "reasoning": row["reasoning"],
                }
                for row in raw
            }
        else:
            rows = hosted_rows[condition_key]
        assert len(rows) == 1056, condition_key

        examples = []
        for case_id in EXAMPLE_IDS:
            raw = rows[case_id]
            predicted = sign(raw.get("predicted_sign", raw.get("predicted")))
            examples.append({
                "case_id": case_id,
                "predicted_sign": predicted,
                "rationale": raw["reasoning"],
                "correct": predicted == metadata[case_id]["expected"],
            })

        subfields = []
        for theme_id, name in THEMES:
            case_ids = [
                case_id for case_id, item in metadata.items()
                if item["theme"] == theme_id and item["side"] in {"intervention", "market"}
            ]
            intervention_ids = [case_id for case_id in case_ids if metadata[case_id]["side"] == "intervention"]
            market_ids = [case_id for case_id in case_ids if metadata[case_id]["side"] == "market"]
            assert intervention_ids and market_ids, theme_id
            intervention_accuracy = 100 * sum(sign(rows[case_id].get("predicted_sign", rows[case_id].get("predicted"))) == metadata[case_id]["expected"] for case_id in intervention_ids) / len(intervention_ids)
            market_accuracy = 100 * sum(sign(rows[case_id].get("predicted_sign", rows[case_id].get("predicted"))) == metadata[case_id]["expected"] for case_id in market_ids) / len(market_ids)
            subfields.append({
                "id": theme_id,
                "name": name,
                "sample_size": len(case_ids),
                "intervention_accuracy": intervention_accuracy,
                "market_accuracy": market_accuracy,
                "accuracy_gap_pp": intervention_accuracy - market_accuracy,
            })

        release = RELEASES.get(result["model_id"])
        if release is None:
            raise KeyError(f"missing approved release record for {result['model_id']}")
        result["examples"] = examples
        result["subfields"] = subfields
        result["release_date"] = release["date"]
        result["release_date_source"] = {key: value for key, value in release.items() if key != "date"}

    grok_rows = [row for row in payload["main_benchmark"]["results"] if row["condition_key"] == "or_grok420_reasoning_disabled"]
    assert len(grok_rows) == 1
    grok_rows[0]["display_name"] = "Grok 4.2"
    # The four provider-minimum conditions also appear as their respective
    # reasoning-sweep baselines.  Keep those duplicate records byte-for-byte
    # equivalent so either view has identical provenance/detail records.
    main_by_key = {row["condition_key"]: row for row in payload["main_benchmark"]["results"]}
    for sweep in payload["reasoning_effort_sweeps"]["sweeps"]:
        for row in sweep["results"]:
            source = main_by_key.get(row["condition_key"])
            if source is not None:
                for field in ("examples", "subfields", "release_date", "release_date_source"):
                    row[field] = source[field]
    payload["detail_generation"] = {
        "examples": {"case_ids": list(EXAMPLE_IDS), "source": "completed per-case result artifacts"},
        "subfields": {
            "method": "categorical JEL policy-theme assignment on the 878 directionally aligned cases; Other excluded",
            "theme_ids": [theme_id for theme_id, _ in THEMES],
            "dataset_sha256": sha256(dataset_path),
            "classifier_sha256": sha256(classifier_path),
        },
        "release_date_policy": "Approved official public availability mapping; source links are retained per condition.",
    }
    PAYLOAD_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
