#!/usr/bin/env python3
"""Render and validate the EconAI Lab publication page.

The website is fully static. Edit ``main_site/data/publications.json`` and then
commit both the data file and the generated ``main_site/publications.html``.

Usage:
    python scripts/render_publications.py
    python scripts/render_publications.py --check

The first command validates the curated data and refreshes the generated HTML
block. ``--check`` performs the same validation without writing and exits with
a non-zero status when the committed HTML is stale.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPOSITORY_ROOT / "main_site" / "data" / "publications.json"
HTML_PATH = REPOSITORY_ROOT / "main_site" / "publications.html"
START_MARKER = "        <!-- PUBLICATIONS:START -->"
END_MARKER = "        <!-- PUBLICATIONS:END -->"

CATEGORY_CONFIG: Sequence[Tuple[str, str, str, Tuple[str, ...]]] = (
    (
        "published-accepted",
        "Published & Accepted",
        "Peer-reviewed publications and papers accepted for publication.",
        ("published", "accepted"),
    ),
    (
        "preprints",
        "Preprints",
        "Public manuscripts that have not yet been listed with a final venue.",
        ("preprint",),
    ),
    (
        "extended-abstracts",
        "Extended Abstracts",
        "Peer-reviewed extended abstracts, kept separate from full papers.",
        ("extended_abstract",),
    ),
)

STATUS_LABELS = {
    "published": "Published",
    "accepted": "Accepted",
    "preprint": "Preprint",
    "extended_abstract": "Extended Abstract",
}
STATUS_CATEGORY = {
    status: category_index
    for category_index, (_, _, _, statuses) in enumerate(CATEGORY_CONFIG)
    for status in statuses
}
REQUIRED_FIELDS = {"id", "title", "authors", "year", "venue", "status", "url", "source_url"}
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
ARXIV_PATTERN = re.compile(r"^\d{4}\.\d{4,5}$")
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PublicationDataError(ValueError):
    """Raised when curated publication data violates the page contract."""


def _normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.casefold())


def _sort_key(publication: Dict[str, Any]) -> Tuple[int, int, str, str]:
    return (
        STATUS_CATEGORY[publication["status"]],
        -publication["year"],
        publication["title"].casefold(),
        publication["id"],
    )


def _require_non_empty_string(value: Any, field: str, publication_id: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PublicationDataError(f"{publication_id}: {field} must be a non-empty string")


def load_and_validate_data() -> Dict[str, Any]:
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PublicationDataError(f"missing data file: {DATA_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise PublicationDataError(f"invalid JSON in {DATA_PATH}: {exc}") from exc

    if data.get("schema_version") != 1:
        raise PublicationDataError("schema_version must be 1")

    try:
        date.fromisoformat(data["last_verified"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationDataError("last_verified must be an ISO date (YYYY-MM-DD)") from exc

    lab_authors = data.get("lab_authors")
    if not isinstance(lab_authors, list) or not lab_authors:
        raise PublicationDataError("lab_authors must be a non-empty list")
    if any(not isinstance(author, str) or not author.strip() for author in lab_authors):
        raise PublicationDataError("every lab_authors entry must be a non-empty string")
    if len(lab_authors) != len(set(lab_authors)):
        raise PublicationDataError("lab_authors contains duplicates")

    publications = data.get("publications")
    if not isinstance(publications, list):
        raise PublicationDataError("publications must be a list")
    expected_count = data.get("expected_count")
    if not isinstance(expected_count, int) or expected_count < 1:
        raise PublicationDataError("expected_count must be a positive integer")
    if len(publications) != expected_count:
        raise PublicationDataError(
            f"expected {expected_count} publications, found {len(publications)}"
        )

    ids: set[str] = set()
    dois: set[str] = set()
    arxiv_ids: set[str] = set()
    titles: set[str] = set()

    for index, publication in enumerate(publications):
        if not isinstance(publication, dict):
            raise PublicationDataError(f"publication at index {index} must be an object")
        missing = REQUIRED_FIELDS - publication.keys()
        if missing:
            raise PublicationDataError(
                f"publication at index {index} is missing: {', '.join(sorted(missing))}"
            )

        publication_id = publication["id"]
        _require_non_empty_string(publication_id, "id", f"entry {index}")
        if not ID_PATTERN.fullmatch(publication_id):
            raise PublicationDataError(f"{publication_id}: id must be a lowercase slug")
        if publication_id in ids:
            raise PublicationDataError(f"duplicate id: {publication_id}")
        ids.add(publication_id)

        for field in ("title", "venue", "url", "source_url"):
            _require_non_empty_string(publication[field], field, publication_id)
        for field in ("url", "source_url"):
            if not publication[field].startswith("https://"):
                raise PublicationDataError(f"{publication_id}: {field} must use HTTPS")

        if publication["status"] not in STATUS_LABELS:
            raise PublicationDataError(
                f"{publication_id}: unsupported status {publication['status']!r}"
            )
        if not isinstance(publication["year"], int) or not 1900 <= publication["year"] <= 2100:
            raise PublicationDataError(f"{publication_id}: year must be a four-digit integer")

        authors = publication["authors"]
        if not isinstance(authors, list) or not authors:
            raise PublicationDataError(f"{publication_id}: authors must be a non-empty list")
        if any(not isinstance(author, str) or not author.strip() for author in authors):
            raise PublicationDataError(f"{publication_id}: every author must be a non-empty string")
        if len(authors) != len(set(authors)):
            raise PublicationDataError(f"{publication_id}: duplicate author in authors list")
        if "Jihee Kim" not in authors:
            raise PublicationDataError(f"{publication_id}: curated scope requires Jihee Kim")
        if "Seongeon Lee" in authors:
            raise PublicationDataError(
                f"{publication_id}: use the source-verified spelling 'Seungeon Lee'"
            )

        normalised_title = _normalise_title(publication["title"])
        if normalised_title in titles:
            raise PublicationDataError(f"duplicate normalised title: {publication['title']}")
        titles.add(normalised_title)

        doi = publication.get("doi")
        arxiv_id = publication.get("arxiv")
        if doi is not None:
            _require_non_empty_string(doi, "doi", publication_id)
            doi = doi.casefold()
            if not DOI_PATTERN.fullmatch(doi):
                raise PublicationDataError(f"{publication_id}: malformed DOI {doi!r}")
            if doi in dois:
                raise PublicationDataError(f"duplicate DOI: {doi}")
            if publication["url"].casefold() != f"https://doi.org/{doi}":
                raise PublicationDataError(f"{publication_id}: URL must resolve through its DOI")
            dois.add(doi)
        if arxiv_id is not None:
            _require_non_empty_string(arxiv_id, "arxiv", publication_id)
            if not ARXIV_PATTERN.fullmatch(arxiv_id):
                raise PublicationDataError(f"{publication_id}: malformed arXiv id {arxiv_id!r}")
            if arxiv_id in arxiv_ids:
                raise PublicationDataError(f"duplicate arXiv id: {arxiv_id}")
            if publication["url"] != f"https://arxiv.org/abs/{arxiv_id}":
                raise PublicationDataError(f"{publication_id}: URL must use the stable arXiv abstract URL")
            arxiv_ids.add(arxiv_id)
        if doi is None and arxiv_id is None and publication_id != "jo-2019-time-series-momentum":
            raise PublicationDataError(f"{publication_id}: expected a DOI or arXiv identifier")

    if publications != sorted(publications, key=_sort_key):
        raise PublicationDataError(
            "publications must be ordered by category, descending year, then title"
        )

    tracking = next(
        (item for item in publications if item["id"] == "lee-2025-tracking-north-korea"),
        None,
    )
    if tracking is None:
        raise PublicationDataError("missing curated Tracking Economic Disparities record")
    if "WoonChul Jung" in tracking["authors"]:
        raise PublicationDataError(
            "lee-2025-tracking-north-korea must omit WoonChul Jung from displayed authors"
        )
    if "WoonChul Jung" not in tracking.get("curation_note", ""):
        raise PublicationDataError(
            "lee-2025-tracking-north-korea must document its intentional author omission"
        )

    counts = _category_counts(publications)
    expected_counts = data.get("expected_category_counts")
    if not isinstance(expected_counts, dict) or set(expected_counts) != set(counts):
        raise PublicationDataError(
            "expected_category_counts must contain each rendered category"
        )
    if any(not isinstance(count, int) or count < 0 for count in expected_counts.values()):
        raise PublicationDataError(
            "expected_category_counts values must be non-negative integers"
        )
    if sum(expected_counts.values()) != expected_count:
        raise PublicationDataError(
            "expected_category_counts must sum to expected_count"
        )
    if counts != expected_counts:
        raise PublicationDataError(
            f"unexpected category counts: expected {expected_counts}, found {counts}"
        )

    return data


def _category_counts(publications: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    status_counts = Counter(publication["status"] for publication in publications)
    return {
        slug: sum(status_counts[status] for status in statuses)
        for slug, _, _, statuses in CATEGORY_CONFIG
    }


def _render_authors(authors: Sequence[str], lab_authors: set[str]) -> str:
    rendered_authors: List[str] = []
    for author in authors:
        escaped_author = html.escape(author)
        if author in lab_authors:
            rendered_authors.append(
                f'<strong class="publication-lab-author">{escaped_author}</strong>'
            )
        else:
            rendered_authors.append(escaped_author)
    return ", ".join(rendered_authors)


def _render_publication(publication: Dict[str, Any], lab_authors: set[str]) -> List[str]:
    title = html.escape(publication["title"])
    url = html.escape(publication["url"], quote=True)
    venue = html.escape(publication["venue"])
    status = publication["status"]
    link_label = (
        "DOI"
        if publication.get("doi")
        else "arXiv"
        if publication.get("arxiv")
        else "PDF"
        if publication["url"].casefold().endswith(".pdf")
        else "Article"
    )
    authors = _render_authors(publication["authors"], lab_authors)
    return [
        '                                <li class="publication-item">',
        (
            f'                                    <a class="publication-title" href="{url}" '
            f'target="_blank" rel="noopener noreferrer">{title}</a>'
        ),
        f'                                    <p class="publication-authors">{authors}</p>',
        '                                    <div class="publication-meta">',
        f'                                        <span class="publication-venue">{venue}</span>',
        (
            f'                                        <span class="publication-status '
            f'publication-status-{html.escape(status)}">{STATUS_LABELS[status]}</span>'
        ),
        (
            f'                                        <a class="publication-link" href="{url}" '
            f'target="_blank" rel="noopener noreferrer" '
            f'aria-label="Open {title}">{link_label}<span aria-hidden="true">&#8599;</span></a>'
        ),
        "                                    </div>",
        "                                </li>",
    ]


def _render_category(
    slug: str,
    heading: str,
    description: str,
    statuses: Tuple[str, ...],
    publications: Sequence[Dict[str, Any]],
    lab_authors: set[str],
) -> List[str]:
    category_publications = [item for item in publications if item["status"] in statuses]
    lines = [
        f'                <section class="publication-category" aria-labelledby="{slug}-title">',
        '                    <div class="publication-category-header">',
        "                        <div>",
        f'                            <h2 class="publication-category-title" id="{slug}-title">{html.escape(heading)}</h2>',
        f'                            <p class="publication-category-description">{html.escape(description)}</p>',
        "                        </div>",
        f'                        <span class="publication-count">{len(category_publications)}</span>',
        "                    </div>",
    ]

    years = sorted({publication["year"] for publication in category_publications}, reverse=True)
    for year in years:
        lines.extend(
            [
                f'                    <section class="publication-year-block" aria-labelledby="{slug}-{year}">',
                f'                        <h3 class="publication-year" id="{slug}-{year}">{year}</h3>',
                '                        <ol class="publication-list">',
            ]
        )
        for publication in category_publications:
            if publication["year"] == year:
                lines.extend(_render_publication(publication, lab_authors))
        lines.extend(
            [
                "                        </ol>",
                "                    </section>",
            ]
        )
    lines.append("                </section>")
    return lines


def render_publications(data: Dict[str, Any]) -> str:
    publications = data["publications"]
    lab_authors = set(data["lab_authors"])
    counts = _category_counts(publications)
    verified_date = date.fromisoformat(data["last_verified"])
    verified = f"{verified_date.strftime('%B')} {verified_date.day}, {verified_date.year}"
    lines = [
        START_MARKER,
        '        <section class="section-band publications-section">',
        '            <div class="container publications-container">',
        '                <div class="publication-summary" aria-label="Publication summary">',
        '                    <div class="publication-summary-item">',
        f'                        <strong>{len(publications)}</strong>',
        "                        <span>Curated records</span>",
        "                    </div>",
        '                    <div class="publication-summary-item">',
        f'                        <strong>{counts["published-accepted"]}</strong>',
        "                        <span>Published &amp; accepted</span>",
        "                    </div>",
        '                    <div class="publication-summary-item">',
        f'                        <strong>{counts["preprints"]}</strong>',
        "                        <span>Preprints</span>",
        "                    </div>",
        "                </div>",
        (
            '                <p class="publication-curation-note">'
            'EconAI Lab members are highlighted. Records are curated from publisher and arXiv metadata; '
            f'last verified {html.escape(verified)}.</p>'
        ),
    ]
    for category in CATEGORY_CONFIG:
        lines.extend(_render_category(*category, publications, lab_authors))
    lines.extend(
        [
            "            </div>",
            "        </section>",
            END_MARKER,
        ]
    )
    return "\n".join(lines)


def update_html(generated_block: str, check: bool) -> bool:
    try:
        current_html = HTML_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PublicationDataError(f"missing HTML file: {HTML_PATH}") from exc

    if current_html.count(START_MARKER) != 1 or current_html.count(END_MARKER) != 1:
        raise PublicationDataError(
            f"{HTML_PATH} must contain exactly one PUBLICATIONS marker pair"
        )
    marker_start = current_html.index(START_MARKER)
    marker_end = current_html.index(END_MARKER, marker_start) + len(END_MARKER)
    expected_html = current_html[:marker_start] + generated_block + current_html[marker_end:]

    if current_html == expected_html:
        return False
    if check:
        raise PublicationDataError(
            "generated publication HTML is stale; run: python scripts/render_publications.py"
        )
    HTML_PATH.write_text(expected_html, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate main_site/data/publications.json and render its static HTML block "
            "into main_site/publications.html."
        ),
        epilog=(
            "Run without options after editing publications.json. Use --check in CI or "
            "before a commit to verify that the generated page is current."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate data and fail if publications.html is not freshly rendered",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        data = load_and_validate_data()
        changed = update_html(render_publications(data), check=args.check)
    except PublicationDataError as exc:
        print(f"publication validation failed: {exc}", file=sys.stderr)
        return 1

    counts = _category_counts(data["publications"])
    state = "current" if args.check or not changed else "updated"
    print(
        f"Publication HTML {state}: {len(data['publications'])} records "
        f"({counts['published-accepted']} published/accepted, "
        f"{counts['preprints']} preprints, "
        f"{counts['extended-abstracts']} extended abstracts)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
