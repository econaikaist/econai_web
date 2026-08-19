#!/usr/bin/env python3
"""Validate a generated EconAI static site before GitHub Pages deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from validate_econcausal_data import ValidationError as EconCausalDataError
from validate_econcausal_data import validate_core as validate_econcausal_data


SITE_FOOTER_PAIR = (
    "<!-- SITE:FOOTER:START -->",
    "<!-- SITE:FOOTER:END -->",
)
MARKER_PAIRS = {
    "index.html": (
        ("<!-- SHEET:RESEARCH_FOCUS:START -->", "<!-- SHEET:RESEARCH_FOCUS:END -->"),
        ("<!-- SHEET:LATEST_PUBLICATIONS:START -->", "<!-- SHEET:LATEST_PUBLICATIONS:END -->"),
        ("<!-- SHEET:NEWS:START -->", "<!-- SHEET:NEWS:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
    "members.html": (
        ("<!-- SHEET:MEMBERS:START -->", "<!-- SHEET:MEMBERS:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
    "contact.html": (
        ("<!-- SHEET:CONTACT:START -->", "<!-- SHEET:CONTACT:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
    "research.html": (
        ("<!-- SHEET:RESEARCH_AREAS:START -->", "<!-- SHEET:RESEARCH_AREAS:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
    "projects.html": (
        ("<!-- SHEET:PROJECTS:START -->", "<!-- SHEET:PROJECTS:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
    "publications.html": (
        ("<!-- PUBLICATIONS:START -->", "<!-- PUBLICATIONS:END -->"),
        ("<!-- SHEET:FOOTER_AFFILIATIONS:START -->", "<!-- SHEET:FOOTER_AFFILIATIONS:END -->"),
        SITE_FOOTER_PAIR,
    ),
}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data"}
class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: List[Tuple[str, str]] = []
        self.ids: List[str] = []
        self.classes: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"] or "")
        if attributes.get("class"):
            self.classes.extend((attributes["class"] or "").split())
        for attribute in ("href", "src"):
            value = attributes.get(attribute)
            if value:
                self.references.append((attribute, value))


def _classes(text: str, class_name: str) -> int:
    parser = LinkCollector()
    parser.feed(text)
    parser.close()
    return parser.classes.count(class_name)


def _resolve_local_reference(site_dir: Path, html_path: Path, value: str) -> Path | None:
    parsed = urllib.parse.urlparse(value)
    if parsed.netloc == "econai.kaist.ac.kr":
        relative = urllib.parse.unquote(parsed.path.lstrip("/")) or "index.html"
        target = site_dir / relative
    elif parsed.scheme in EXTERNAL_SCHEMES or value.startswith("//"):
        return None
    elif value.startswith("#"):
        return None
    elif parsed.path.startswith("/"):
        target = site_dir / urllib.parse.unquote(parsed.path.lstrip("/"))
    else:
        target = html_path.parent / urllib.parse.unquote(parsed.path)

    if str(target).endswith("/"):
        target = target / "index.html"
    elif target.is_dir():
        target = target / "index.html"
    return target


def validate(site_dir: Path) -> List[str]:
    errors: List[str] = []
    rendered_footers: Dict[str, str] = {}
    site_dir = site_dir.resolve()
    metadata_path = site_dir / "data/sheet-build.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [f"invalid or missing {metadata_path}: {exc}"]

    expected_counts = metadata.get("published_rows", {})
    for candidate in site_dir.rglob("*"):
        if candidate.is_symlink():
            errors.append(
                f"generated site must not contain symlinks: {candidate.relative_to(site_dir)}"
            )
    for name in ("Publications", "Research", "Projects", "News", "Members"):
        if not isinstance(expected_counts.get(name), int) or expected_counts[name] < 1:
            errors.append(f"sheet-build.json has invalid count for {name}")

    for file_name, marker_pairs in MARKER_PAIRS.items():
        html_path = site_dir / file_name
        try:
            text = html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            errors.append(f"missing required page: {file_name}")
            continue
        if "Preview" in text or "preview.css" in text:
            errors.append(f"{file_name}: preview-only text or stylesheet remains")
        if 'rel="icon"' not in text or "favicon.svg" not in text:
            errors.append(f"{file_name}: EconAI favicon is missing")
        for start, end in marker_pairs:
            if text.count(start) != 1 or text.count(end) != 1:
                errors.append(f"{file_name}: invalid marker pair {start} / {end}")
            elif text.index(start) > text.index(end):
                errors.append(f"{file_name}: reversed marker pair {start} / {end}")

        if _classes(text, "site-header") != 1:
            errors.append(f"{file_name}: canonical site header is missing")
        if _classes(text, "site-footer") != 1:
            errors.append(f"{file_name}: canonical site footer is missing")
        if _classes(text, "desktop-nav") != 1 or _classes(text, "mobile-nav") != 1:
            errors.append(f"{file_name}: canonical navigation is missing")
        if "site.css?" not in text:
            errors.append(f"{file_name}: shared site stylesheet is missing")
        if (
            "fixed-top" in text
            or "navbar-expand" in text
            or "cdn.jsdelivr.net/npm/bootstrap" in text.lower()
        ):
            errors.append(f"{file_name}: legacy Bootstrap page shell remains")
        if file_name != "index.html" and _classes(text, "page-hero") != 1:
            errors.append(f"{file_name}: canonical page hero is missing")

        footer_start, footer_end = SITE_FOOTER_PAIR
        if text.count(footer_start) == 1 and text.count(footer_end) == 1:
            start = text.index(footer_start)
            end = text.index(footer_end, start) + len(footer_end)
            rendered_footers[file_name] = text[start:end]

    if len(rendered_footers) == len(MARKER_PAIRS):
        reference_name = next(iter(MARKER_PAIRS))
        reference_footer = rendered_footers[reference_name]
        mismatched = [
            file_name
            for file_name, footer in rendered_footers.items()
            if footer != reference_footer
        ]
        if mismatched:
            errors.append(
                "primary page footers differ from index.html: "
                + ", ".join(sorted(mismatched))
            )

    publication_text = (site_dir / "publications.html").read_text(encoding="utf-8")
    research_text = (site_dir / "research.html").read_text(encoding="utf-8")
    project_text = (site_dir / "projects.html").read_text(encoding="utf-8")
    index_text = (site_dir / "index.html").read_text(encoding="utf-8")
    member_text = (site_dir / "members.html").read_text(encoding="utf-8")

    if _classes(publication_text, "publication-item") != expected_counts.get("Publications"):
        errors.append("publications.html row count does not match Sheet metadata")
    if _classes(research_text, "research-row") != expected_counts.get("Research"):
        errors.append("research.html row count does not match Sheet metadata")
    if _classes(project_text, "project-card") != expected_counts.get("Projects"):
        errors.append("projects.html row count does not match Sheet metadata")
    if _classes(index_text, "focus-card") != min(expected_counts.get("Research", 0), 3):
        errors.append("index.html research focus count is incorrect")
    if _classes(index_text, "publication-list") < 1:
        errors.append("index.html is missing latest publications")
    carousel_slides = _classes(index_text, "publication-figure-slide")
    expected_slides = min(expected_counts.get("Publications", 0), 3)
    if carousel_slides not in {0, expected_slides}:
        errors.append("index.html publication figure carousel count is incorrect")
    expected_controls = 2 if carousel_slides else 0
    if _classes(index_text, "publication-carousel-button") != expected_controls:
        errors.append("index.html publication figure carousel controls are missing")
    if _classes(index_text, "publication-figure-caption") != carousel_slides:
        errors.append("index.html publication carousel title count is incorrect")
    if _classes(index_text, "publication-carousel-dot") != carousel_slides:
        errors.append("index.html publication carousel dot count is incorrect")
    if "weather-card" in index_text or "open-meteo.com" in index_text:
        errors.append("index.html still contains the removed weather widget")
    if "googleusercontent.com" in index_text or "ggpht.com" in index_text:
        errors.append("index.html leaks a temporary Google image URL")
    if _classes(index_text, "sheet-news-item") != expected_counts.get("News"):
        errors.append("index.html news row count does not match Sheet metadata")
    if _classes(member_text, "sheet-member-item") != expected_counts.get("Members"):
        errors.append("members.html row count does not match Sheet metadata")
    if _classes(member_text, "member-photo") != _classes(member_text, "member-card"):
        errors.append("members.html member cards and photos do not match")
    if "googleusercontent.com" in member_text or "ggpht.com" in member_text:
        errors.append("members.html leaks a temporary Google image URL")

    selected_count = research_text.count('class="selected-figure-frame"')
    if selected_count and selected_count != research_text.count("loading=\"lazy\""):
        errors.append("every selected research figure must be lazy-loaded")

    for html_path in sorted(site_dir.rglob("*.html")):
        text = html_path.read_text(encoding="utf-8")
        parser = LinkCollector()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            errors.append(f"{html_path.relative_to(site_dir)}: HTML parse error: {exc}")
            continue
        duplicate_ids = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
        if duplicate_ids:
            errors.append(
                f"{html_path.relative_to(site_dir)}: duplicate ids {', '.join(duplicate_ids)}"
            )
        for attribute, value in parser.references:
            target = _resolve_local_reference(site_dir, html_path, value)
            if target is not None and not target.exists():
                errors.append(
                    f"{html_path.relative_to(site_dir)}: broken local {attribute}={value!r}"
                )

    for required in ("site.css", "favicon.svg", "banner.png", "img/EconAI@KAIST.svg"):
        if not (site_dir / required).exists():
            errors.append(f"missing required static asset: {required}")

    econcausal_dir = site_dir / "econcausal"
    if econcausal_dir.exists():
        for relative_path in (
            "index.html",
            "styles.css",
            "script.js",
            "data/paper-data.v1.json",
            "assets/og-card.png",
        ):
            if not (econcausal_dir / relative_path).is_file():
                errors.append(f"econcausal: missing required asset {relative_path}")
        data_path = econcausal_dir / "data/paper-data.v1.json"
        if data_path.is_file():
            try:
                validate_econcausal_data(json.loads(data_path.read_text(encoding="utf-8")))
            except (EconCausalDataError, json.JSONDecodeError) as exc:
                errors.append(f"econcausal: invalid paper data: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_dir", type=Path, nargs="?", default=Path("_site"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate(args.site_dir)
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated static site: {args.site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
