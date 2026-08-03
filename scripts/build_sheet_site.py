#!/usr/bin/env python3
"""Build the static EconAI website from the lab's Google Sheet.

The source HTML contains the stable page shells. During a build this script
copies ``main_site`` to a staging directory, reads the five Sheet tabs, and
fills only explicitly marked content blocks. Dynamic content is not duplicated
in the Git checkout.

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
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET_ID = "14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM"
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "main_site"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "_site"
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
        "research_title",
        "figure_src",
        "figure_alt",
        "figure_credit",
    },
    "Research": {
        "publish",
        "slug",
        "title",
        "summary",
        "question",
        "home_summary",
        "selected_publication_1",
        "selected_publication_2",
    },
    "Projects": {
        "publish",
        "title",
        "summary",
        "status",
        "period",
        "area",
        "url",
    },
    "News": {
        "publish",
        "date",
        "display_date",
        "tag",
        "title",
        "summary",
        "related_publications",
        "url",
    },
    "Members": {
        "publish",
        "section",
        "group",
        "sort_order",
        "name_en",
        "name_ko",
        "role",
        "details",
        "photo",
        "email",
        "website",
        "scholar",
        "linkedin",
        "phone",
        "address",
        "highlight_publications",
    },
}
MINIMUM_PUBLISHED_ROWS = {
    "Publications": 20,
    "Research": 1,
    "Projects": 1,
    "News": 1,
    "Members": 1,
}
TRUTHY = {"1", "true", "yes", "y", "checked", "x"}
FALSEY = {"", "0", "false", "no", "n", "unchecked"}
DATE_PATTERN = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
VENUE_HIGHLIGHT_PATTERN = re.compile(
    r"\((?=[^()]*[A-Za-z])[^()]*(?:19|20)\d{2}\)"
)
SAFE_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MEMBER_SECTIONS = (
    "Faculty",
    "Ph.D. Students",
    "Master's Students",
    "Lab Internship",
    "Alumni",
    "Pre-EconAI Alumni",
)


class SheetBuildError(RuntimeError):
    """Raised when Sheet content cannot safely produce a site."""


def _read_csv_text(text: str, tab_name: str) -> List[Dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        raw_fieldnames = reader.fieldnames or []
        fieldnames = [name.strip() for name in raw_fieldnames if name]
    except csv.Error as exc:
        raise SheetBuildError(f"{tab_name}: invalid CSV: {exc}") from exc

    if len(fieldnames) != len(set(fieldnames)):
        raise SheetBuildError(f"{tab_name}: duplicate column names")
    missing = REQUIRED_COLUMNS[tab_name] - set(fieldnames)
    if missing:
        raise SheetBuildError(
            f"{tab_name}: missing columns: {', '.join(sorted(missing))}"
        )

    rows_with_numbers: List[Tuple[int, Dict[str, str]]] = []
    for sheet_row, source_row in enumerate(reader, start=2):
        overflow = source_row.get(None, [])
        if any((value or "").strip() for value in overflow):
            raise SheetBuildError(f"{tab_name} row {sheet_row}: too many cells")
        row = {
            (key or "").strip(): (value or "").strip()
            for key, value in source_row.items()
            if key is not None
        }
        if not any(row.values()):
            continue
        publish = row.get("publish", "").casefold()
        if publish not in TRUTHY | FALSEY:
            raise SheetBuildError(
                f"{tab_name} row {sheet_row}: publish must be a checkbox value"
            )
        if publish not in TRUTHY:
            continue
        rows_with_numbers.append((sheet_row, row))

    rows = [row for _, row in rows_with_numbers]

    minimum = MINIMUM_PUBLISHED_ROWS[tab_name]
    if len(rows) < minimum:
        raise SheetBuildError(
            f"{tab_name}: expected at least {minimum} published rows, found {len(rows)}"
        )

    unique_rows: set[str] = set()
    research_slugs: set[str] = set()
    for index, row in rows_with_numbers:
        if tab_name == "Members":
            name = row.get("name_en", "")
            if not name:
                raise SheetBuildError(f"{tab_name} row {index}: name_en is required")
            unique_key = "|".join(
                (row.get("section", ""), row.get("group", ""), name)
            ).casefold()
            duplicate_label = name
        else:
            title = row.get("title", "")
            if not title:
                raise SheetBuildError(f"{tab_name} row {index}: title is required")
            unique_key = _normalise_title(title)
            duplicate_label = title
        if unique_key in unique_rows:
            raise SheetBuildError(
                f"{tab_name} row {index}: duplicate entry {duplicate_label!r}"
            )
        unique_rows.add(unique_key)

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
            figure_values = [
                row.get(field, "")
                for field in ("figure_src", "figure_alt", "figure_credit")
            ]
            if any(figure_values) and not all(figure_values):
                raise SheetBuildError(
                    f"{tab_name} row {index}: figure_src, figure_alt, and figure_credit must be filled together"
                )
        elif tab_name == "Research":
            slug = row.get("slug", "")
            if SLUG_PATTERN.fullmatch(slug) is None:
                raise SheetBuildError(
                    f"{tab_name} row {index}: slug must contain lowercase letters, numbers, and hyphens"
                )
            if slug in research_slugs:
                raise SheetBuildError(f"{tab_name} row {index}: duplicate slug {slug!r}")
            research_slugs.add(slug)
            for field in (
                "summary",
                "question",
                "home_summary",
                "selected_publication_1",
                "selected_publication_2",
            ):
                if not row.get(field):
                    raise SheetBuildError(
                        f"{tab_name} row {index}: {field} is required"
                    )
        elif tab_name == "Projects":
            for field in ("summary", "status", "period", "area", "url"):
                if not row.get(field):
                    raise SheetBuildError(
                        f"{tab_name} row {index}: {field} is required"
                    )
            if row["status"].casefold() not in {"ongoing", "completed"}:
                raise SheetBuildError(
                    f"{tab_name} row {index}: status must be Ongoing or Completed"
                )
            _validate_url(row["url"], f"{tab_name} row {index} url")
        elif tab_name == "News":
            for field in ("date", "display_date", "tag"):
                if not row.get(field):
                    raise SheetBuildError(
                        f"{tab_name} row {index}: {field} is required"
                    )
            _date_tuple(row["date"], f"{tab_name} row {index} date")
            if row.get("url"):
                _validate_url(row["url"], f"{tab_name} row {index} url")
        elif tab_name == "Members":
            section = row.get("section", "")
            if section not in MEMBER_SECTIONS:
                raise SheetBuildError(
                    f"{tab_name} row {index}: unknown section {section!r}"
                )
            try:
                sort_order = int(row.get("sort_order", ""))
            except ValueError as exc:
                raise SheetBuildError(
                    f"{tab_name} row {index}: sort_order must be a positive integer"
                ) from exc
            if sort_order < 1:
                raise SheetBuildError(
                    f"{tab_name} row {index}: sort_order must be a positive integer"
                )
            if section == "Lab Internship" and not row.get("group"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: group is required for Lab Internship"
                )
            if section != "Lab Internship" and row.get("group"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: group is only used for Lab Internship"
                )
            if section in {"Faculty", "Ph.D. Students", "Master's Students"}:
                for field in ("role", "photo"):
                    if not row.get(field):
                        raise SheetBuildError(
                            f"{tab_name} row {index}: {field} is required for {section}"
                        )
            if section in {"Alumni", "Pre-EconAI Alumni"}:
                for field in ("role", "details"):
                    if not row.get(field):
                        raise SheetBuildError(
                            f"{tab_name} row {index}: {field} is required for alumni"
                        )
            email = row.get("email", "")
            if email and EMAIL_PATTERN.fullmatch(email) is None:
                raise SheetBuildError(f"{tab_name} row {index}: invalid email")
            for field in ("website", "scholar", "linkedin"):
                if row.get(field):
                    _validate_url(row[field], f"{tab_name} row {index} {field}")
            highlight = row.get("highlight_publications", "").casefold()
            if highlight not in TRUTHY | FALSEY:
                raise SheetBuildError(
                    f"{tab_name} row {index}: highlight_publications must be a checkbox value"
                )

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
        if value.startswith("#") or ".." in Path(parsed.path).parts:
            raise SheetBuildError(f"{label}: unsafe relative URL")
        return
    if parsed.scheme != "https" or not parsed.netloc:
        raise SheetBuildError(f"{label}: use an HTTPS or relative URL")


def _date_tuple(value: str, label: str) -> Tuple[int, int, int]:
    match = DATE_PATTERN.fullmatch(value)
    if match is None:
        raise SheetBuildError(f"{label}: use YYYY, YYYY-MM, or YYYY-MM-DD")
    year = int(match.group(1))
    month = int(match.group(2) or 0)
    day = int(match.group(3) or 0)
    if not 1900 <= year <= 2100 or not 0 <= month <= 12 or not 0 <= day <= 31:
        raise SheetBuildError(f"{label}: invalid date {value!r}")
    if month and day:
        try:
            datetime(year, month, day)
        except ValueError as exc:
            raise SheetBuildError(f"{label}: invalid date {value!r}") from exc
    return year, month, day


def _publication_sort_tuple(row: Mapping[str, str]) -> Tuple[int, int, int]:
    raw_date = row.get("date", "")
    if raw_date:
        return _date_tuple(
            raw_date, f"Publications: date for {row.get('title', '<untitled>')!r}"
        )

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


def render_home_research(research_rows: Sequence[Dict[str, str]]) -> str:
    lines = ['        <div class="research-focus-grid">']
    for index, row in enumerate(research_rows[:3], start=1):
        lines.extend(
            [
                '          <article class="focus-card">',
                f'            <span class="focus-number">{index:02d}</span>',
                f'            <h3>{_escape(row["title"])}</h3>',
                f'            <p>{_escape(row["home_summary"])}</p>',
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
    publication_title: str,
    publication_lookup: Mapping[str, Dict[str, str]],
    output_dir: Path,
) -> List[str]:
    publication = publication_lookup.get(_normalise_title(publication_title))
    if publication is None:
        raise SheetBuildError(
            f"selected publication not found in Publications tab: {publication_title}"
        )

    for field in ("figure_src", "figure_alt", "figure_credit"):
        if not publication.get(field):
            raise SheetBuildError(f"{publication_title}: Publications {field} is required")
    figure_path = (output_dir / publication["figure_src"]).resolve()
    try:
        figure_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise SheetBuildError(
            f"{publication_title}: figure_src must stay inside the site"
        ) from exc
    if not figure_path.is_file():
        raise SheetBuildError(f"{publication_title}: missing figure asset {figure_path}")

    display_title = publication.get("research_title") or publication["title"]
    paper_url = _escape(publication["paper_url"], quote=True)
    aria_label = _escape(f"Open {display_title}", quote=True)
    return [
        "                  <li>",
        f'                    <a class="selected-figure-link" href="{paper_url}" aria-label="{aria_label}">',
        f'                      <span class="selected-figure-frame"><img src="{_escape(publication["figure_src"], quote=True)}" alt="{_escape(publication["figure_alt"], quote=True)}" loading="lazy" decoding="async"></span>',
        "                    </a>",
        f'                    <a class="selected-title" href="{paper_url}">{_escape(display_title)}</a>',
        f'                    <span>{_escape(publication["venue"])}</span>',
        f'                    <small class="selected-figure-credit">{_escape(publication["figure_credit"])}</small>',
        "                  </li>",
    ]


def render_research_areas(
    research_rows: Sequence[Dict[str, str]],
    publications: Sequence[Dict[str, str]],
    output_dir: Path,
) -> str:
    lookup = _publication_lookup(publications)
    lines = ['        <div class="research-rows">']
    for index, row in enumerate(research_rows, start=1):
        slug = row["slug"]
        lines.extend(
            [
                f'          <article class="research-row" id="{_escape(slug, quote=True)}">',
                f'            <div class="research-index">{index:02d}</div>',
                '            <div class="research-body">',
                f'              <h2>{_escape(row["title"])}</h2>',
            ]
        )
        lines.append(
            f'              <p class="research-question">{_escape(row["question"])}</p>'
        )
        lines.append(f'              <p class="research-summary">{_escape(row["summary"])}</p>')

        lines.extend(
            [
                '              <div class="selected-publications">',
                '                <p class="selected-label">Selected Publications</p>',
                "                <ul>",
            ]
        )
        for field in ("selected_publication_1", "selected_publication_2"):
            lines.extend(_selected_publication_lines(row[field], lookup, output_dir))
        lines.extend(["                </ul>", "              </div>"])

        lines.extend(["            </div>", "          </article>"])
    lines.append("        </div>")
    return "\n".join(lines)


def _render_project_group(
    status_label: str,
    rows: Sequence[Dict[str, str]],
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
        status = row["status"]
        period = row["period"]
        area = row["area"]
        url = row["url"]
        status_class = " status-completed" if status.casefold() == "completed" else ""
        title_html = (
            f'<a href="{_escape(url, quote=True)}">{_escape(row["title"])}</a>'
        )
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


def render_projects(project_rows: Sequence[Dict[str, str]]) -> str:
    grouped: Dict[str, List[Dict[str, str]]] = {"Ongoing": [], "Completed": []}
    for row in project_rows:
        key = "Completed" if row["status"].casefold() == "completed" else "Ongoing"
        grouped[key].append(row)

    lines: List[str] = []
    for label in ("Ongoing", "Completed"):
        if grouped[label]:
            if lines:
                lines.append("")
            lines.extend(_render_project_group(label, grouped[label]))
    return "\n".join(lines)


def _sort_news(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            -_date_tuple(row["date"], f"News date for {row['title']!r}")[0],
            -_date_tuple(row["date"], f"News date for {row['title']!r}")[1],
            -_date_tuple(row["date"], f"News date for {row['title']!r}")[2],
            row["title"].casefold(),
        ),
    )


def _related_publication_links(
    value: str, publication_lookup: Mapping[str, Dict[str, str]]
) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    for title in (part.strip() for part in re.split(r"[|\n]+", value) if part.strip()):
        publication = publication_lookup.get(_normalise_title(title))
        if publication is None:
            raise SheetBuildError(
                f"News related publication not found in Publications tab: {title}"
            )
        links.append(
            (
                publication.get("research_title") or publication["title"],
                publication.get("project_url") or publication["paper_url"],
            )
        )
    return links


def render_news(
    news_rows: Sequence[Dict[str, str]], publications: Sequence[Dict[str, str]]
) -> str:
    publication_lookup = _publication_lookup(publications)
    lines = ['        <div class="news-list">']
    for index, row in enumerate(_sort_news(news_rows)):
        featured = " news-item-featured" if index == 0 else ""
        lines.extend(
            [
                f'          <article class="news-item sheet-news-item{featured}">',
                "            <div>",
                f'              <time class="news-date" datetime="{_escape(row["date"], quote=True)}">{_escape(row["display_date"])}</time>',
                f'              <span class="news-tag">{_escape(row["tag"])}</span>',
                "            </div>",
                '            <div class="news-content">',
                f'              <h3>{_escape(row["title"])}</h3>',
            ]
        )
        if row.get("summary"):
            lines.append(f'              <p>{_escape(row["summary"])}</p>')
        related = _related_publication_links(
            row.get("related_publications", ""), publication_lookup
        )
        if row.get("url"):
            related.append(("Read more", row["url"]))
        if related:
            lines.append('              <div class="news-paper-links">')
            for label, url in related:
                lines.append(
                    f'                <a href="{_escape(url, quote=True)}">{_escape(label)} →</a>'
                )
            lines.append("              </div>")
        lines.extend(["            </div>", "          </article>"])
    lines.append("        </div>")
    return "\n".join(lines)


def _member_sort_key(row: Mapping[str, str]) -> Tuple[int, int]:
    return MEMBER_SECTIONS.index(row["section"]), int(row["sort_order"])


def _member_name(row: Mapping[str, str]) -> str:
    if row.get("name_ko"):
        return f'{row["name_en"]} | {row["name_ko"]}'
    return row["name_en"]


def _member_link_lines(row: Mapping[str, str]) -> List[str]:
    links: List[Tuple[str, str, str]] = []
    if row.get("website"):
        links.append((row["website"], "Website", "fas fa-home"))
    if row.get("scholar"):
        links.append((row["scholar"], "Google Scholar", "fas fa-graduation-cap"))
    if row.get("linkedin"):
        links.append((row["linkedin"], "LinkedIn", "fab fa-linkedin-in"))
    if row.get("email"):
        links.append((f'mailto:{row["email"]}', "Email", "fas fa-envelope"))
    if not links:
        return []
    lines = ['                        <div class="member-links">']
    for url, label, icon in links:
        target = ' target="_blank" rel="noopener noreferrer"' if not url.startswith("mailto:") else ""
        aria = _escape(f'{label} {_member_name(row)}', quote=True)
        lines.append(
            f'                            <a href="{_escape(url, quote=True)}"{target} class="member-link-btn" aria-label="{aria}"><i class="{icon}"></i></a>'
        )
    lines.append("                        </div>")
    return lines


def _member_card_lines(row: Mapping[str, str], output_dir: Path) -> List[str]:
    photo_path = (output_dir / row["photo"]).resolve()
    try:
        photo_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise SheetBuildError(f'{row["name_en"]}: photo must stay inside the site') from exc
    if not photo_path.is_file():
        raise SheetBuildError(f'{row["name_en"]}: missing member photo {photo_path}')
    professor = " prof-card" if row["section"] == "Faculty" else ""
    lines = [
        f'                    <article class="member-card sheet-member-item{professor}">',
        f'                        <img src="{_escape(row["photo"], quote=True)}" alt="{_escape(row["name_en"], quote=True)}" class="member-photo">',
        '                        <div class="member-info">',
        f'                            <h3 class="member-name">{_escape(_member_name(row))}</h3>',
        f'                            <p class="member-role">{_escape(row["role"])}</p>',
    ]
    if row["section"] == "Faculty":
        contact: List[str] = []
        if row.get("email"):
            contact.append(f'<i class="fas fa-envelope fa-fw"></i> {_escape(row["email"])}')
        if row.get("phone"):
            contact.append(f'<i class="fas fa-phone fa-fw"></i> {_escape(row["phone"])}')
        if row.get("address"):
            contact.append(f'<i class="fas fa-map-marker-alt fa-fw"></i> {_escape(row["address"])}')
        if contact:
            lines.append(f'                            <p class="member-keywords">{"<br>".join(contact)}</p>')
    elif row.get("details"):
        lines.append(f'                            <p class="member-keywords">{_escape(row["details"])}</p>')
    lines.append("                        </div>")
    lines.extend(_member_link_lines(row))
    lines.append("                    </article>")
    return lines


def render_members(
    member_rows: Sequence[Dict[str, str]], output_dir: Path
) -> str:
    sections: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in member_rows:
        sections[row["section"]].append(row)

    lines: List[str] = []
    for section in MEMBER_SECTIONS:
        rows = sections.get(section, [])
        if not rows:
            continue
        lines.append(f'                <h2 class="members-category-title">{_escape(section)}</h2>')
        if section in {"Faculty", "Ph.D. Students", "Master's Students"}:
            lines.append('                <div class="members-grid">')
            for row in sorted(rows, key=_member_sort_key):
                lines.extend(_member_card_lines(row, output_dir))
            lines.append("                </div>")
        elif section == "Lab Internship":
            lines.append('                <div class="accordion" id="internshipAccordion">')
            groups: Dict[str, List[Dict[str, str]]] = {}
            for row in rows:
                groups.setdefault(row["group"], []).append(row)
            for group, group_rows in groups.items():
                slug = f'intern-{_slugify(group)}'
                lines.extend(
                    [
                        '                    <div class="accordion-item">',
                        f'                        <h2 class="accordion-header" id="heading-{slug}">',
                        f'                            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-{slug}" aria-expanded="false" aria-controls="collapse-{slug}">{_escape(group)}</button>',
                        "                        </h2>",
                        f'                        <div id="collapse-{slug}" class="accordion-collapse collapse" aria-labelledby="heading-{slug}" data-bs-parent="#internshipAccordion">',
                        '                            <div class="accordion-body">',
                        '                                <ul class="intern-list">',
                    ]
                )
                for row in sorted(group_rows, key=_member_sort_key):
                    lines.append(
                        f'                                    <li class="sheet-member-item">{_escape(_member_name(row))}</li>'
                    )
                lines.extend(
                    [
                        "                                </ul>",
                        "                            </div>",
                        "                        </div>",
                        "                    </div>",
                    ]
                )
            lines.append("                </div>")
        else:
            lines.append('                <ul class="alumni-list">')
            for row in sorted(rows, key=_member_sort_key):
                lines.append(
                    f'                    <li class="sheet-member-item"><strong>{_escape(_member_name(row))}</strong> — {_escape(row["role"])} · {_escape(row["details"])}</li>'
                )
            lines.append("                </ul>")
        lines.append("")
    return "\n".join(lines).rstrip()


def _lab_authors(member_rows: Sequence[Dict[str, str]]) -> set[str]:
    return {
        row["name_en"]
        for row in member_rows
        if row.get("highlight_publications", "").casefold() in TRUTHY
    }


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
    _safe_prepare_output(source_dir, output_dir)

    publications = tabs["Publications"]
    research = tabs["Research"]
    projects = tabs["Projects"]
    news = tabs["News"]
    members = tabs["Members"]
    lab_authors = _lab_authors(members)

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
        render_home_research(research),
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
            publications,
            output_dir,
        ),
    )
    _replace_block(
        output_dir / "projects.html",
        "<!-- SHEET:PROJECTS:START -->",
        "<!-- SHEET:PROJECTS:END -->",
        render_projects(projects),
    )
    _replace_block(
        output_dir / "index.html",
        "<!-- SHEET:NEWS:START -->",
        "<!-- SHEET:NEWS:END -->",
        render_news(news, publications),
    )
    _replace_block(
        output_dir / "members.html",
        "<!-- SHEET:MEMBERS:START -->",
        "<!-- SHEET:MEMBERS:END -->",
        render_members(members, output_dir),
    )

    metadata = {
        "schema_version": 1,
        "content_source": source_kind,
        "sheet_id": sheet_id,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "published_rows": {name: len(rows) for name, rows in tabs.items()},
    }
    metadata_path = output_dir / "data/sheet-build.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
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
        help="read the five named tab CSV files locally instead of Google",
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
