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
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPOSITORY_ROOT / "main_site" / "data" / "publications.json"
HTML_PATH = REPOSITORY_ROOT / "main_site" / "publications.html"
START_MARKER = "        <!-- PUBLICATIONS:START -->"
END_MARKER = "        <!-- PUBLICATIONS:END -->"

REQUIRED_FIELDS = {
    "id",
    "title",
    "authors",
    "year",
    "sort_date",
    "date_basis",
    "venue",
    "url",
    "source_url",
}
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
ARXIV_PATTERN = re.compile(r"^\d{4}\.\d{4,5}$")
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SORT_DATE_PATTERN = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
VENUE_HIGHLIGHT_PATTERN = re.compile(
    r"\((?=[^()]*[A-Za-z])[^()]*(?:19|20)\d{2}\)"
)
DATE_BASES = {
    "crossref_published",
    "arxiv_latest_version",
    "journal_issue",
}
DISTINCTION_KINDS = {"award", "presentation"}


class PublicationDataError(ValueError):
    """Raised when curated publication data violates the page contract."""


def _normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.casefold())


def _parse_sort_date(value: Any, publication_id: str) -> Tuple[int, int, int]:
    if not isinstance(value, str) or not SORT_DATE_PATTERN.fullmatch(value):
        raise PublicationDataError(
            f"{publication_id}: sort_date must be YYYY, YYYY-MM, or YYYY-MM-DD"
        )

    parts = [int(part) for part in value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) >= 2 else 0
    day = parts[2] if len(parts) == 3 else 0
    if len(parts) >= 2 and month == 0:
        raise PublicationDataError(
            f"{publication_id}: sort_date month must be between 01 and 12"
        )
    if len(parts) == 3 and day == 0:
        raise PublicationDataError(
            f"{publication_id}: sort_date day must be a valid calendar day"
        )
    try:
        date(year, month or 1, day or 1)
    except ValueError as exc:
        raise PublicationDataError(
            f"{publication_id}: invalid sort_date {value!r}"
        ) from exc
    return year, month, day


def _sort_key(publication: Dict[str, Any]) -> Tuple[int, int, int, str, str]:
    year, month, day = _parse_sort_date(publication["sort_date"], publication["id"])
    return (
        -year,
        -month,
        -day,
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

    if data.get("schema_version") != 4:
        raise PublicationDataError("schema_version must be 4")
    if "expected_category_counts" in data:
        raise PublicationDataError("category counts are not used by the chronological list")
    _require_non_empty_string(data.get("date_policy"), "date_policy", "dataset")
    _require_non_empty_string(data.get("link_policy"), "link_policy", "dataset")

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

        for field in ("paper_url", "pdf_url", "venue_url"):
            value = publication.get(field)
            if value is None:
                continue
            _require_non_empty_string(value, field, publication_id)
            if not value.startswith("https://"):
                raise PublicationDataError(f"{publication_id}: {field} must use HTTPS")
        if "pdf_url" in publication and not publication["pdf_url"].casefold().endswith(".pdf"):
            raise PublicationDataError(f"{publication_id}: pdf_url must point to a PDF")

        venue_url = publication.get("venue_url")
        venue_link_label = publication.get("venue_link_label")
        if (venue_url is None) != (venue_link_label is None):
            raise PublicationDataError(
                f"{publication_id}: venue_url and venue_link_label must be provided together"
            )
        if venue_link_label is not None:
            _require_non_empty_string(
                venue_link_label, "venue_link_label", publication_id
            )

        distinction = publication.get("distinction")
        if distinction is not None:
            if not isinstance(distinction, dict):
                raise PublicationDataError(
                    f"{publication_id}: distinction must be an object"
                )
            expected_distinction_fields = {"label", "kind", "source_url"}
            if set(distinction) != expected_distinction_fields:
                raise PublicationDataError(
                    f"{publication_id}: distinction must contain exactly label, kind, and source_url"
                )
            for field in expected_distinction_fields:
                _require_non_empty_string(
                    distinction[field], f"distinction.{field}", publication_id
                )
            if distinction["kind"] not in DISTINCTION_KINDS:
                raise PublicationDataError(
                    f"{publication_id}: unsupported distinction kind {distinction['kind']!r}"
                )
            if not distinction["source_url"].startswith("https://"):
                raise PublicationDataError(
                    f"{publication_id}: distinction.source_url must use HTTPS"
                )

        if "status" in publication:
            raise PublicationDataError(
                f"{publication_id}: status classifications are not used"
            )
        if not isinstance(publication["year"], int) or not 1900 <= publication["year"] <= 2100:
            raise PublicationDataError(f"{publication_id}: year must be a four-digit integer")
        sort_year, _, _ = _parse_sort_date(publication["sort_date"], publication_id)
        if publication["year"] != sort_year:
            raise PublicationDataError(
                f"{publication_id}: year must match the year in sort_date"
            )
        if publication["date_basis"] not in DATE_BASES:
            raise PublicationDataError(
                f"{publication_id}: unsupported date_basis {publication['date_basis']!r}"
            )

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
            if publication["date_basis"] != "crossref_published":
                raise PublicationDataError(
                    f"{publication_id}: DOI records must use crossref_published"
                )
            if "paper_url" not in publication:
                raise PublicationDataError(
                    f"{publication_id}: DOI records must include an official paper_url"
                )
            dois.add(doi)
        if arxiv_id is not None:
            _require_non_empty_string(arxiv_id, "arxiv", publication_id)
            if not ARXIV_PATTERN.fullmatch(arxiv_id):
                raise PublicationDataError(f"{publication_id}: malformed arXiv id {arxiv_id!r}")
            if arxiv_id in arxiv_ids:
                raise PublicationDataError(f"duplicate arXiv id: {arxiv_id}")
            if publication["url"] != f"https://arxiv.org/abs/{arxiv_id}":
                raise PublicationDataError(f"{publication_id}: URL must use the stable arXiv abstract URL")
            if publication["date_basis"] != "arxiv_latest_version":
                raise PublicationDataError(
                    f"{publication_id}: arXiv-only records must use arxiv_latest_version"
                )
            arxiv_ids.add(arxiv_id)
        if doi is None and arxiv_id is None and publication_id != "jo-2019-time-series-momentum":
            raise PublicationDataError(f"{publication_id}: expected a DOI or arXiv identifier")
        if publication_id == "jo-2019-time-series-momentum" and publication["date_basis"] != "journal_issue":
            raise PublicationDataError(
                "jo-2019-time-series-momentum must use its official journal_issue date"
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

    return data


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


def _render_venue(venue: str) -> str:
    rendered: List[str] = []
    start = 0
    for match in VENUE_HIGHLIGHT_PATTERN.finditer(venue):
        rendered.append(html.escape(venue[start : match.start()]))
        rendered.append(
            '<strong class="publication-venue-highlight">'
            f"{html.escape(match.group(0))}</strong>"
        )
        start = match.end()
    rendered.append(html.escape(venue[start:]))
    return "".join(rendered)


def _publication_destination(publication: Dict[str, Any]) -> str:
    if publication.get("paper_url"):
        return publication["paper_url"]
    if publication.get("arxiv"):
        return publication["url"]
    return publication["url"]


def _render_distinction(distinction: Dict[str, str]) -> str:
    label = html.escape(distinction["label"])
    kind = html.escape(distinction["kind"], quote=True)
    return (
        f'                                <span class="publication-distinction '
        f'publication-distinction--{kind}">{label}</span>'
    )


def _render_publication(publication: Dict[str, Any], lab_authors: set[str]) -> List[str]:
    title = html.escape(publication["title"])
    publication_destination = _publication_destination(publication)
    primary_url = html.escape(publication_destination, quote=True)
    venue = _render_venue(publication["venue"])
    authors = _render_authors(publication["authors"], lab_authors)
    lines = [
        '                        <li class="publication-item">',
        (
            f'                            <a class="publication-title" href="{primary_url}" '
            f'target="_blank" rel="noopener noreferrer">{title}</a>'
        ),
        f'                            <p class="publication-authors">{authors}</p>',
    ]

    metadata: List[str] = []
    if publication["venue"] != "arXiv":
        metadata.append(f'                                <span class="publication-venue">{venue}</span>')

    distinction = publication.get("distinction")
    if distinction is not None:
        metadata.append(_render_distinction(distinction))

    if metadata:
        lines.append('                            <div class="publication-meta">')
        lines.extend(metadata)
        lines.append("                            </div>")
    lines.append("                        </li>")
    return lines


def _render_year(
    year: int,
    publications: Sequence[Dict[str, Any]],
    lab_authors: set[str],
) -> List[str]:
    lines = [
        f'                <section class="publication-year-block" aria-labelledby="publications-{year}">',
        f'                    <h2 class="publication-year" id="publications-{year}">{year}</h2>',
        '                    <ol class="publication-list">',
    ]
    for publication in publications:
        if publication["year"] == year:
            lines.extend(_render_publication(publication, lab_authors))
    lines.extend(
        [
            "                    </ol>",
            "                </section>",
        ]
    )
    return lines


def render_publications(data: Dict[str, Any]) -> str:
    publications = sorted(data["publications"], key=_sort_key)
    lab_authors = set(data["lab_authors"])
    lines = [
        START_MARKER,
        '        <section class="section-band publications-section">',
        '            <div class="container publications-container">',
    ]
    for year in sorted({publication["year"] for publication in publications}, reverse=True):
        lines.extend(_render_year(year, publications, lab_authors))
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

    state = "current" if args.check or not changed else "updated"
    print(
        f"Publication HTML {state}: {len(data['publications'])} records in publication/version-date order."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
