#!/usr/bin/env python3
"""Build the static EconAI website from the lab's Google Sheet.

The source HTML remains a complete, browsable fallback. During a build this
script copies ``main_site`` to a staging directory, reads the three Sheet tabs,
and replaces only explicitly marked content blocks.

No Google API key is required: the Sheet must be viewable by anyone with the
link, while edit access should remain restricted to lab accounts.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET_ID = "14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM"
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "main_site"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "_site"
CATALOG_NAME = "data/site_catalog.json"
PUBLICATION_DATA_NAME = "data/publications.json"

REQUIRED_COLUMNS = {
    "Publications": {
        "publish",
        "date",
        "title",
        "authors",
        "venue",
        "paper_url",
        "project_url",
        "highlight",
    },
    "Research": {"publish", "title", "summary"},
    "Projects": {"publish", "title", "summary"},
}
MINIMUM_PUBLISHED_ROWS = {"Publications": 20, "Research": 1, "Projects": 1}
TRUTHY = {"1", "true", "yes", "y", "checked", "x"}
DATE_PATTERN = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
VENUE_HIGHLIGHT_PATTERN = re.compile(
    r"\((?=[^()]*[A-Za-z])[^()]*(?:19|20)\d{2}\)"
)
SAFE_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class SheetBuildError(RuntimeError):
    """Raised when Sheet content cannot safely produce a site."""


def _read_csv_text(text: str, tab_name: str) -> List[Dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        fieldnames = [name.strip() for name in (reader.fieldnames or []) if name]
    except csv.Error as exc:
        raise SheetBuildError(f"{tab_name}: invalid CSV: {exc}") from exc

    missing = REQUIRED_COLUMNS[tab_name] - set(fieldnames)
    if missing:
        raise SheetBuildError(
            f"{tab_name}: missing columns: {', '.join(sorted(missing))}"
        )

    rows: List[Dict[str, str]] = []
    for source_row in reader:
        row = {
            (key or "").strip(): (value or "").strip()
            for key, value in source_row.items()
            if key is not None
        }
        if not any(row.values()):
            continue
        if row.get("publish", "").casefold() not in TRUTHY:
            continue
        rows.append(row)

    minimum = MINIMUM_PUBLISHED_ROWS[tab_name]
    if len(rows) < minimum:
        raise SheetBuildError(
            f"{tab_name}: expected at least {minimum} published rows, found {len(rows)}"
        )

    titles: set[str] = set()
    for index, row in enumerate(rows, start=2):
        title = row.get("title", "")
        if not title:
            raise SheetBuildError(f"{tab_name} row {index}: title is required")
        title_key = _normalise_title(title)
        if title_key in titles:
            raise SheetBuildError(f"{tab_name} row {index}: duplicate title {title!r}")
        titles.add(title_key)

        if tab_name == "Publications":
            for field in ("authors", "venue", "paper_url"):
                if not row.get(field):
                    raise SheetBuildError(
                        f"{tab_name} row {index}: {field} is required"
                    )
            _validate_url(row["paper_url"], f"{tab_name} row {index} paper_url")
            if row.get("project_url"):
                _validate_url(
                    row["project_url"], f"{tab_name} row {index} project_url"
                )
            _publication_sort_tuple(row)
        elif not row.get("summary"):
            raise SheetBuildError(f"{tab_name} row {index}: summary is required")

    return rows


def _fetch_tab(sheet_id: str, tab_name: str, timeout: float) -> str:
    query = urllib.parse.urlencode(
        {
            "sheet": tab_name,
            "tqx": "out:csv",
            "t": str(time.time_ns()),
        }
    )
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "EconAI-Site-Builder/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:  # urllib exposes several transport exception types
        raise SheetBuildError(f"{tab_name}: Google Sheet fetch failed: {exc}") from exc

    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SheetBuildError(f"{tab_name}: response is not UTF-8 CSV") from exc


def load_sheet_tabs(
    sheet_id: str,
    csv_dir: Path | None,
    timeout: float,
) -> Dict[str, List[Dict[str, str]]]:
    tabs: Dict[str, List[Dict[str, str]]] = {}
    for tab_name in REQUIRED_COLUMNS:
        if csv_dir is None:
            text = _fetch_tab(sheet_id, tab_name, timeout)
        else:
            csv_path = csv_dir / f"{tab_name}.csv"
            try:
                text = csv_path.read_text(encoding="utf-8-sig")
            except FileNotFoundError as exc:
                raise SheetBuildError(f"missing offline fixture: {csv_path}") from exc
        tabs[tab_name] = _read_csv_text(text, tab_name)
    return tabs


def _normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _validate_url(value: str, label: str) -> None:
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme and not parsed.netloc and value and not value.startswith("//"):
        return
    if parsed.scheme != "https" or not parsed.netloc:
        raise SheetBuildError(f"{label}: use an HTTPS or relative URL")


def _publication_sort_tuple(row: Mapping[str, str]) -> Tuple[int, int, int]:
    raw_date = row.get("date", "")
    if raw_date:
        match = DATE_PATTERN.fullmatch(raw_date)
        if match is None:
            raise SheetBuildError(
                f"Publications: date for {row.get('title', '<untitled>')!r} must be YYYY, YYYY-MM, or YYYY-MM-DD"
            )
        year = int(match.group(1))
        month = int(match.group(2) or 0)
        day = int(match.group(3) or 0)
        if not 1900 <= year <= 2100 or not 0 <= month <= 12 or not 0 <= day <= 31:
            raise SheetBuildError(
                f"Publications: invalid date {raw_date!r} for {row.get('title')!r}"
            )
        if month and day:
            try:
                datetime(year, month, day)
            except ValueError as exc:
                raise SheetBuildError(
                    f"Publications: invalid date {raw_date!r} for {row.get('title')!r}"
                ) from exc
        return year, month, day

    venue_years = [int(year) for year in YEAR_PATTERN.findall(row.get("venue", ""))]
    if len(set(venue_years)) != 1:
        raise SheetBuildError(
            f"Publications: date is blank and venue has no unambiguous year for {row.get('title')!r}"
        )
    return venue_years[0], 0, 0


def _publication_year(row: Mapping[str, str]) -> int:
    return _publication_sort_tuple(row)[0]


def _sort_publications(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            -_publication_sort_tuple(row)[0],
            -_publication_sort_tuple(row)[1],
            -_publication_sort_tuple(row)[2],
            row["title"].casefold(),
        ),
    )


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SheetBuildError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SheetBuildError(f"invalid {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise SheetBuildError(f"{label} must be a JSON object")
    return data


def _load_catalog(source_dir: Path) -> Dict[str, Any]:
    catalog = _load_json(source_dir / CATALOG_NAME, "site catalog")
    if catalog.get("schema_version") != 1:
        raise SheetBuildError("site catalog schema_version must be 1")
    if not isinstance(catalog.get("research"), dict) or not isinstance(
        catalog.get("projects"), dict
    ):
        raise SheetBuildError("site catalog must contain research and projects objects")
    return catalog


def _load_lab_authors(source_dir: Path) -> set[str]:
    data = _load_json(source_dir / PUBLICATION_DATA_NAME, "publication metadata")
    authors = data.get("lab_authors")
    if not isinstance(authors, list) or not all(
        isinstance(author, str) and author.strip() for author in authors
    ):
        raise SheetBuildError("publication metadata lab_authors must be a string list")
    return set(authors)


def _escape(value: str, quote: bool = False) -> str:
    return html.escape(value, quote=quote)


def _render_authors(authors: str, lab_authors: set[str]) -> str:
    rendered: List[str] = []
    for author in (part.strip() for part in authors.split(",")):
        escaped = _escape(author)
        if author in lab_authors:
            rendered.append(f'<strong class="publication-lab-author">{escaped}</strong>')
        else:
            rendered.append(escaped)
    return ", ".join(rendered)


def _render_venue(venue: str) -> str:
    rendered: List[str] = []
    cursor = 0
    for match in VENUE_HIGHLIGHT_PATTERN.finditer(venue):
        rendered.append(_escape(venue[cursor : match.start()]))
        rendered.append(
            '<strong class="publication-venue-highlight">'
            f"{_escape(match.group(0))}</strong>"
        )
        cursor = match.end()
    rendered.append(_escape(venue[cursor:]))
    return "".join(rendered)


def _distinction_kind(label: str) -> str:
    lowered = label.casefold()
    return "presentation" if "oral" in lowered or "presentation" in lowered else "award"


def _render_publication_item(row: Mapping[str, str], lab_authors: set[str]) -> List[str]:
    title = _escape(row["title"])
    paper_url = _escape(row["paper_url"], quote=True)
    lines = [
        '                        <li class="publication-item">',
        f'                            <a class="publication-title" href="{paper_url}" target="_blank" rel="noopener noreferrer">{title}</a>',
        f'                            <p class="publication-authors">{_render_authors(row["authors"], lab_authors)}</p>',
        '                            <div class="publication-meta">',
        f'                                <span class="publication-venue">{_render_venue(row["venue"])}</span>',
    ]
    if row.get("project_url"):
        project_url = _escape(row["project_url"], quote=True)
        label = _escape(f"Project page for {row['title']}", quote=True)
        lines.append(
            f'                                <a class="publication-project-link" href="{project_url}" aria-label="{label}">Project Page</a>'
        )
    if row.get("highlight"):
        kind = _distinction_kind(row["highlight"])
        lines.append(
            f'                                <span class="publication-distinction publication-distinction--{kind}">{_escape(row["highlight"])}</span>'
        )
    lines.extend(
        [
            "                            </div>",
            "                        </li>",
        ]
    )
    return lines


def render_publications_page(
    publications: Sequence[Dict[str, str]], lab_authors: set[str]
) -> str:
    sorted_rows = _sort_publications(publications)
    by_year: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    for row in sorted_rows:
        by_year[_publication_year(row)].append(row)

    lines = [
        '        <section class="section-band publications-section">',
        '            <div class="container publications-container">',
    ]
    for year in sorted(by_year, reverse=True):
        lines.extend(
            [
                f'                <section class="publication-year-block" aria-labelledby="publications-{year}">',
                f'                    <h2 class="publication-year" id="publications-{year}">{year}</h2>',
                '                    <ol class="publication-list">',
            ]
        )
        for row in by_year[year]:
            lines.extend(_render_publication_item(row, lab_authors))
        lines.extend(["                    </ol>", "                </section>"])
    lines.extend(["            </div>", "        </section>"])
    return "\n".join(lines)


def _slugify(value: str) -> str:
    slug = SAFE_SLUG_PATTERN.sub("-", value.casefold()).strip("-")
    return slug or "research-area"


def render_home_research(
    research_rows: Sequence[Dict[str, str]], catalog: Mapping[str, Any]
) -> str:
    lines = ['        <div class="research-focus-grid">']
    for index, row in enumerate(research_rows[:3], start=1):
        details = catalog.get(row["title"], {})
        summary = details.get("home_summary", row["summary"])
        lines.extend(
            [
                '          <article class="focus-card">',
                f'            <span class="focus-number">{index:02d}</span>',
                f'            <h3>{_escape(row["title"])}</h3>',
                f'            <p>{_escape(summary)}</p>',
                "          </article>",
            ]
        )
    lines.append("        </div>")
    return "\n".join(lines)


def _short_authors(authors: str, limit: int = 4) -> str:
    names = [part.strip() for part in authors.split(",") if part.strip()]
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + ", et al."


def render_home_latest(publications: Sequence[Dict[str, str]]) -> str:
    lines = ['          <ol class="publication-list">']
    for row in _sort_publications(publications)[:3]:
        lines.extend(
            [
                "            <li>",
                f'              <a href="{_escape(row["paper_url"], quote=True)}">{_escape(row["title"])}</a>',
                f'              <p class="publication-authors">{_escape(_short_authors(row["authors"]))}</p>',
                f'              <p class="publication-venue">{_escape(row["venue"])}</p>',
                "            </li>",
            ]
        )
    lines.append("          </ol>")
    return "\n".join(lines)


def _publication_lookup(
    publications: Sequence[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    return {_normalise_title(row["title"]): row for row in publications}


def _selected_publication_lines(
    selected: Mapping[str, Any],
    publication_lookup: Mapping[str, Dict[str, str]],
    output_dir: Path,
) -> List[str]:
    publication_title = selected.get("publication_title")
    if not isinstance(publication_title, str) or not publication_title:
        raise SheetBuildError("selected publication is missing publication_title")
    publication = publication_lookup.get(_normalise_title(publication_title))
    if publication is None:
        raise SheetBuildError(
            f"selected publication not found in Publications tab: {publication_title}"
        )

    for field in ("figure_src", "figure_alt", "figure_credit"):
        if not isinstance(selected.get(field), str) or not selected[field]:
            raise SheetBuildError(f"{publication_title}: catalog {field} is required")
    figure_path = output_dir / selected["figure_src"]
    if not figure_path.is_file():
        raise SheetBuildError(f"{publication_title}: missing figure asset {figure_path}")

    display_title = selected.get("display_title", publication["title"])
    paper_url = _escape(publication["paper_url"], quote=True)
    aria_label = _escape(f"Open {display_title}", quote=True)
    return [
        "                  <li>",
        f'                    <a class="selected-figure-link" href="{paper_url}" aria-label="{aria_label}">',
        f'                      <span class="selected-figure-frame"><img src="{_escape(selected["figure_src"], quote=True)}" alt="{_escape(selected["figure_alt"], quote=True)}" loading="lazy" decoding="async"></span>',
        "                    </a>",
        f'                    <a class="selected-title" href="{paper_url}">{_escape(display_title)}</a>',
        f'                    <span>{_escape(publication["venue"])}</span>',
        f'                    <small class="selected-figure-credit">{_escape(selected["figure_credit"])}</small>',
        "                  </li>",
    ]


def render_research_areas(
    research_rows: Sequence[Dict[str, str]],
    catalog: Mapping[str, Any],
    publications: Sequence[Dict[str, str]],
    output_dir: Path,
) -> str:
    lookup = _publication_lookup(publications)
    lines = ['        <div class="research-rows">']
    for index, row in enumerate(research_rows, start=1):
        details = catalog.get(row["title"], {})
        slug = details.get("slug", _slugify(row["title"]))
        lines.extend(
            [
                f'          <article class="research-row" id="{_escape(slug, quote=True)}">',
                f'            <div class="research-index">{index:02d}</div>',
                '            <div class="research-body">',
                f'              <h2>{_escape(row["title"])}</h2>',
            ]
        )
        question = details.get("question")
        if question:
            lines.append(f'              <p class="research-question">{_escape(question)}</p>')
        lines.append(f'              <p class="research-summary">{_escape(row["summary"])}</p>')

        selected_publications = details.get("selected_publications", [])
        if selected_publications:
            if not isinstance(selected_publications, list):
                raise SheetBuildError(f"{row['title']}: selected_publications must be a list")
            lines.extend(
                [
                    '              <div class="selected-publications">',
                    '                <p class="selected-label">Selected Publications</p>',
                    "                <ul>",
                ]
            )
            for selected in selected_publications:
                if not isinstance(selected, dict):
                    raise SheetBuildError(
                        f"{row['title']}: selected publication entries must be objects"
                    )
                lines.extend(_selected_publication_lines(selected, lookup, output_dir))
            lines.extend(["                </ul>", "              </div>"])

        lines.extend(["            </div>", "          </article>"])
    lines.append("        </div>")
    return "\n".join(lines)


def _project_url(
    details: Mapping[str, Any], publication_lookup: Mapping[str, Dict[str, str]]
) -> str:
    explicit_url = details.get("url")
    if explicit_url:
        _validate_url(explicit_url, "project catalog url")
        return explicit_url
    publication_title = details.get("publication_title")
    if publication_title:
        publication = publication_lookup.get(_normalise_title(publication_title))
        if publication is None:
            raise SheetBuildError(
                f"project publication not found in Publications tab: {publication_title}"
            )
        return publication["paper_url"]
    return ""


def _render_project_group(
    status_label: str,
    rows: Sequence[Dict[str, str]],
    catalog: Mapping[str, Any],
    publication_lookup: Mapping[str, Dict[str, str]],
) -> List[str]:
    slug = f"{status_label.casefold()}-projects"
    count_label = "project" if len(rows) == 1 else "projects"
    lines = [
        f'        <section class="project-section" aria-labelledby="{slug}">',
        '          <div class="project-section-header">',
        f'            <h2 id="{slug}">{status_label} Projects</h2>',
        f'            <span class="project-count">{len(rows)} {count_label}</span>',
        "          </div>",
        '          <div class="project-grid">',
    ]
    for row in rows:
        details = catalog.get(row["title"], {})
        status = details.get("status", status_label)
        period = details.get("period", "")
        area = details.get("area", "")
        display_title = details.get("display_title", row["title"])
        url = _project_url(details, publication_lookup)
        status_class = " status-completed" if status.casefold() == "completed" else ""
        title_html = _escape(display_title)
        if url:
            title_html = f'<a href="{_escape(url, quote=True)}">{title_html}</a>'
        lines.extend(
            [
                '            <article class="project-card">',
                '              <div class="project-meta">',
                f'                <span class="status{status_class}">{_escape(status)}</span>',
                f'                <span class="project-period">{_escape(period)}</span>' if period else "",
                "              </div>",
                f"              <h3>{title_html}</h3>",
                f'              <p>{_escape(row["summary"])}</p>',
                f'              <span class="project-area">{_escape(area)}</span>' if area else "",
                "            </article>",
            ]
        )
    lines.extend(["          </div>", "        </section>"])
    return [line for line in lines if line]


def render_projects(
    project_rows: Sequence[Dict[str, str]],
    catalog: Mapping[str, Any],
    publications: Sequence[Dict[str, str]],
) -> str:
    lookup = _publication_lookup(publications)
    grouped: Dict[str, List[Dict[str, str]]] = {"Ongoing": [], "Completed": []}
    for row in project_rows:
        details = catalog.get(row["title"], {})
        status = details.get("status", "Ongoing")
        key = "Completed" if status.casefold() == "completed" else "Ongoing"
        grouped[key].append(row)

    lines: List[str] = []
    for label in ("Ongoing", "Completed"):
        if grouped[label]:
            if lines:
                lines.append("")
            lines.extend(_render_project_group(label, grouped[label], catalog, lookup))
    return "\n".join(lines)


def _replace_block(path: Path, start_marker: str, end_marker: str, block: str) -> None:
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SheetBuildError(f"missing HTML template: {path}") from exc
    if current.count(start_marker) != 1 or current.count(end_marker) != 1:
        raise SheetBuildError(
            f"{path.name}: expected exactly one {start_marker} / {end_marker} pair"
        )
    start = current.index(start_marker)
    end_start = current.index(end_marker, start)
    end = end_start + len(end_marker)
    line_start = current.rfind("\n", 0, start) + 1
    indent = current[line_start:start]
    replacement = f"{start_marker}\n{block}\n{indent}{end_marker}"
    path.write_text(current[:start] + replacement + current[end:], encoding="utf-8")


def _safe_prepare_output(source_dir: Path, output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise SheetBuildError(f"refusing symlink output directory: {output_dir}")
    for candidate in source_dir.rglob("*"):
        if candidate.is_symlink():
            raise SheetBuildError(f"refusing symlink in source site: {candidate}")
    source = source_dir.resolve()
    output = output_dir.resolve()
    if output in {Path("/").resolve(), REPOSITORY_ROOT.resolve(), source}:
        raise SheetBuildError(f"refusing unsafe output directory: {output}")
    if len(output.parts) < 3:
        raise SheetBuildError(f"refusing broad output directory: {output}")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)


def build_site(
    tabs: Mapping[str, List[Dict[str, str]]],
    source_dir: Path,
    output_dir: Path,
    sheet_id: str,
    source_kind: str,
) -> None:
    catalog = _load_catalog(source_dir)
    lab_authors = _load_lab_authors(source_dir)
    _safe_prepare_output(source_dir, output_dir)

    publications = tabs["Publications"]
    research = tabs["Research"]
    projects = tabs["Projects"]

    _replace_block(
        output_dir / "publications.html",
        "<!-- PUBLICATIONS:START -->",
        "<!-- PUBLICATIONS:END -->",
        render_publications_page(publications, lab_authors),
    )
    _replace_block(
        output_dir / "index.html",
        "<!-- SHEET:RESEARCH_FOCUS:START -->",
        "<!-- SHEET:RESEARCH_FOCUS:END -->",
        render_home_research(research, catalog["research"]),
    )
    _replace_block(
        output_dir / "index.html",
        "<!-- SHEET:LATEST_PUBLICATIONS:START -->",
        "<!-- SHEET:LATEST_PUBLICATIONS:END -->",
        render_home_latest(publications),
    )
    _replace_block(
        output_dir / "research.html",
        "<!-- SHEET:RESEARCH_AREAS:START -->",
        "<!-- SHEET:RESEARCH_AREAS:END -->",
        render_research_areas(
            research,
            catalog["research"],
            publications,
            output_dir,
        ),
    )
    _replace_block(
        output_dir / "projects.html",
        "<!-- SHEET:PROJECTS:START -->",
        "<!-- SHEET:PROJECTS:END -->",
        render_projects(projects, catalog["projects"], publications),
    )

    metadata = {
        "schema_version": 1,
        "content_source": source_kind,
        "sheet_id": sheet_id,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "published_rows": {name: len(rows) for name, rows in tabs.items()},
    }
    (output_dir / "data/sheet-build.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the EconAI static site from Google Sheet tabs."
    )
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--csv-dir",
        type=Path,
        help="read Publications.csv, Research.csv, and Projects.csv locally instead of Google",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        tabs = load_sheet_tabs(args.sheet_id, args.csv_dir, args.timeout)
        build_site(
            tabs,
            args.source_dir,
            args.output_dir,
            args.sheet_id,
            "offline_csv" if args.csv_dir else "google_sheet",
        )
    except SheetBuildError as exc:
        print(f"site build failed: {exc}", file=sys.stderr)
        return 1

    counts = ", ".join(f"{name}={len(rows)}" for name, rows in tabs.items())
    print(f"Built {args.output_dir}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
