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
import hashlib
import html
import io
import json
import os
import posixpath
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple
from xml.etree import ElementTree


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET_ID = "14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM"
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "main_site"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "_site"
PRIMARY_PAGE_NAMES = (
    "index.html",
    "members.html",
    "research.html",
    "publications.html",
    "projects.html",
    "contact.html",
)
SITE_FOOTER_META = "Daejeon, ROK · 2026 Economic Progress and AI Research Group"
RESEARCH_IMAGE_ENDPOINT_ENV = "ECONAI_SHEET_IMAGE_ENDPOINT"
RESEARCH_IMAGE_TOKEN_ENV = "ECONAI_SHEET_IMAGE_TOKEN"
RESEARCH_IMAGE_SCHEMA_VERSION = 1
RESEARCH_IMAGE_RESPONSE_LIMIT = 1024 * 1024
RESEARCH_IMAGE_FILE_LIMIT = 10 * 1024 * 1024
RESEARCH_IMAGE_ASSET_DIR = Path("img/sheet-research")
PUBLICATION_WORKBOOK_LIMIT = 50 * 1024 * 1024
PUBLICATION_WORKBOOK_UNCOMPRESSED_LIMIT = 128 * 1024 * 1024
PUBLICATION_WORKBOOK_MEMBER_LIMIT = 20 * 1024 * 1024
PUBLICATION_WORKBOOK_MAX_MEMBERS = 2048
PUBLICATION_IMAGE_ASSET_DIR = Path("img/sheet-publications")
PUBLICATION_IMAGE_FILE_LIMIT = 10 * 1024 * 1024
MEMBER_IMAGE_ASSET_DIR = Path("img/sheet-members")
MEMBER_IMAGE_FILE_LIMIT = 10 * 1024 * 1024
PUBLICATION_IMAGE_FORMULA_HOSTS = {
    "arxiv.org",
    "econai.kaist.ac.kr",
    "media.springernature.com",
}
RESEARCH_LEGACY_IMAGE_COLUMNS = {
    "figure_1_url",
    "figure_2_url",
}
RESEARCH_DIRECT_IMAGE_COLUMNS = {
    "figure_1_image",
    "figure_2_image",
}
PUBLICATION_DIRECT_IMAGE_COLUMNS = {
    "home_image",
    "home_image_alt",
    "home_image_credit",
}
GOOGLE_IMAGE_HOST_SUFFIXES = (
    ".googleusercontent.com",
    ".ggpht.com",
)
XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_DOCUMENT_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
XLSX_PACKAGE_REL_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
XLSX_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
)
XLSX_DRAWING_MAIN_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
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
    },
    "Research": {
        "publish",
        "slug",
        "title",
        "summary",
        "question",
        "home_summary",
        "selected_publication_1",
        "figure_1_alt",
        "figure_1_credit",
        "selected_publication_2",
        "figure_2_alt",
        "figure_2_credit",
    },
    "Projects": {
        "publish",
        "title",
        "summary",
        "status",
        "period",
        "area",
        "related_publication",
        "url",
    },
    "News": {
        "publish",
        "date",
        "display_date",
        "tag",
        "title",
        "summary",
        "related_publication_1",
        "related_publication_2",
        "url",
    },
    "Members": {
        "publish",
        "section",
        "group",
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
        "affiliations",
        "joint_supervisor",
        "joint_supervisor_url",
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
    "Staff",
    "Alumni",
    "Pre-EconAI Alumni",
)
MEMBER_CARD_SECTIONS = {
    "Faculty",
    "Ph.D. Students",
    "Master's Students",
    "Staff",
}
DEFAULT_MEMBER_PHOTO = "img/basic_profile.png"


class SheetBuildError(RuntimeError):
    """Raised when Sheet content cannot safely produce a site."""


def _research_image_schema(columns: Iterable[str]) -> str:
    column_set = set(columns)
    legacy_present = RESEARCH_LEGACY_IMAGE_COLUMNS & column_set
    direct_present = RESEARCH_DIRECT_IMAGE_COLUMNS & column_set
    legacy_complete = legacy_present == RESEARCH_LEGACY_IMAGE_COLUMNS
    direct_complete = direct_present == RESEARCH_DIRECT_IMAGE_COLUMNS

    if legacy_complete and not direct_present:
        return "legacy_url"
    if direct_complete and not legacy_present:
        return "direct_cell"
    if legacy_complete and direct_complete:
        raise SheetBuildError(
            "Research: use either figure_1_url/figure_2_url or "
            "figure_1_image/figure_2_image, not both"
        )

    missing_legacy = sorted(RESEARCH_LEGACY_IMAGE_COLUMNS - column_set)
    missing_direct = sorted(RESEARCH_DIRECT_IMAGE_COLUMNS - column_set)
    raise SheetBuildError(
        "Research: incomplete image columns; provide either both legacy URL "
        f"columns (missing: {', '.join(missing_legacy) or 'none'}) or both "
        f"direct image columns (missing: {', '.join(missing_direct) or 'none'})"
    )


def _publication_image_schema(columns: Iterable[str]) -> str:
    column_set = set(columns)
    direct_present = PUBLICATION_DIRECT_IMAGE_COLUMNS & column_set
    if not direct_present:
        return "none"
    if direct_present == PUBLICATION_DIRECT_IMAGE_COLUMNS:
        return "direct_cell"
    missing = sorted(PUBLICATION_DIRECT_IMAGE_COLUMNS - column_set)
    raise SheetBuildError(
        "Publications: incomplete home image columns; add home_image, "
        f"home_image_alt, and home_image_credit (missing: {', '.join(missing)})"
    )


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
    research_image_schema = (
        _research_image_schema(fieldnames) if tab_name == "Research" else None
    )
    if tab_name == "Publications":
        _publication_image_schema(fieldnames)

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
            if research_image_schema == "legacy_url":
                for slot in (1, 2):
                    for field in (
                        f"figure_{slot}_url",
                        f"figure_{slot}_alt",
                        f"figure_{slot}_credit",
                    ):
                        if not row.get(field):
                            raise SheetBuildError(
                                f"{tab_name} row {index}: {field} is required"
                            )
                    _validate_url(
                        row[f"figure_{slot}_url"],
                        f"{tab_name} row {index} figure_{slot}_url",
                    )
        elif tab_name == "Projects":
            for field in ("summary", "status", "period", "area"):
                if not row.get(field):
                    raise SheetBuildError(
                        f"{tab_name} row {index}: {field} is required"
                    )
            if not row.get("related_publication") and not row.get("url"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: choose related_publication or provide url"
                )
            if row["status"].casefold() not in {"ongoing", "completed"}:
                raise SheetBuildError(
                    f"{tab_name} row {index}: status must be Ongoing or Completed"
                )
            if row.get("url"):
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
            if section == "Lab Internship" and not row.get("group"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: group is required for Lab Internship"
                )
            if section != "Lab Internship" and row.get("group"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: group is only used for Lab Internship"
                )
            if section in MEMBER_CARD_SECTIONS and not row.get("role"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: role is required for {section}"
                )
            if section in {"Alumni", "Pre-EconAI Alumni"} and not row.get("details"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: details is required for alumni"
                )
            if section == "Faculty" and not row.get("affiliations"):
                raise SheetBuildError(
                    f"{tab_name} row {index}: affiliations is required for Faculty"
                )
            email = row.get("email", "")
            if email and EMAIL_PATTERN.fullmatch(email) is None:
                raise SheetBuildError(f"{tab_name} row {index}: invalid email")
            for field in ("website", "scholar", "linkedin"):
                if row.get(field):
                    _validate_url(row[field], f"{tab_name} row {index} {field}")
            supervisor = row.get("joint_supervisor", "")
            supervisor_url = row.get("joint_supervisor_url", "")
            if bool(supervisor) != bool(supervisor_url):
                raise SheetBuildError(
                    f"{tab_name} row {index}: joint_supervisor and joint_supervisor_url must be filled together"
                )
            if supervisor:
                if section not in {"Alumni", "Pre-EconAI Alumni"}:
                    raise SheetBuildError(
                        f"{tab_name} row {index}: joint supervision is only used for alumni"
                    )
                _validate_url(
                    supervisor_url,
                    f"{tab_name} row {index} joint_supervisor_url",
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


def _validate_image_bridge_endpoint(value: str) -> None:
    try:
        parsed = urllib.parse.urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise SheetBuildError(
            f"{RESEARCH_IMAGE_ENDPOINT_ENV}: invalid endpoint URL"
        ) from None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise SheetBuildError(
            f"{RESEARCH_IMAGE_ENDPOINT_ENV}: use an HTTPS URL without credentials"
        )


def _validate_google_image_url(value: str, label: str) -> None:
    try:
        parsed = urllib.parse.urlparse(value)
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
    except (TypeError, ValueError):
        raise SheetBuildError(f"{label}: invalid image URL") from None
    google_host = any(
        hostname == suffix[1:] or hostname.endswith(suffix)
        for suffix in GOOGLE_IMAGE_HOST_SUFFIXES
    )
    if (
        parsed.scheme != "https"
        or not google_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise SheetBuildError(
            f"{label}: expected an HTTPS Google-hosted image URL"
        )


def _read_limited_response(response: object, limit: int, label: str) -> bytes:
    headers = getattr(response, "headers", None)
    raw_length = headers.get("Content-Length") if headers is not None else None
    if raw_length:
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise SheetBuildError(f"{label}: invalid Content-Length") from exc
        if content_length < 0 or content_length > limit:
            raise SheetBuildError(f"{label}: response exceeds the size limit")
    payload = response.read(limit + 1)  # type: ignore[attr-defined]
    if len(payload) > limit:
        raise SheetBuildError(f"{label}: response exceeds the size limit")
    return payload


def _response_content_type(response: object) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    return (headers.get("Content-Type") or "").partition(";")[0].strip().casefold()


def _fetch_workbook(sheet_id: str, timeout: float) -> bytes:
    query = urllib.parse.urlencode(
        {
            "format": "xlsx",
            "t": str(time.time_ns()),
        }
    )
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "EconAI-Site-Builder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise SheetBuildError(
                    "Sheet workbook export returned an HTTP error"
                )
            payload = _read_limited_response(
                response,
                PUBLICATION_WORKBOOK_LIMIT,
                "Sheet workbook export",
            )
    except SheetBuildError:
        raise
    except Exception:
        raise SheetBuildError("Sheet workbook export failed") from None
    if not payload.startswith(b"PK"):
        raise SheetBuildError("Sheet workbook export is not an XLSX file")
    return payload


def _fetch_research_image_manifest(
    research_rows: Sequence[Dict[str, str]],
    endpoint: str | None,
    token: str | None,
    timeout: float,
) -> Dict[Tuple[str, int], Dict[str, str]]:
    if not endpoint:
        raise SheetBuildError(
            f"Research direct images require {RESEARCH_IMAGE_ENDPOINT_ENV}"
        )
    if not token:
        raise SheetBuildError(
            f"Research direct images require {RESEARCH_IMAGE_TOKEN_ENV}"
        )
    if len(token) < 32:
        raise SheetBuildError(
            f"{RESEARCH_IMAGE_TOKEN_ENV} must contain at least 32 characters"
        )
    _validate_image_bridge_endpoint(endpoint)

    request_body = json.dumps(
        {"token": token},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=request_body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "Content-Type": "application/json",
            "User-Agent": "EconAI-Site-Builder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise SheetBuildError("Research image bridge returned an HTTP error")
            content_type = _response_content_type(response)
            if content_type != "application/json":
                raise SheetBuildError(
                    "Research image bridge did not return application/json"
                )
            payload = _read_limited_response(
                response,
                RESEARCH_IMAGE_RESPONSE_LIMIT,
                "Research image bridge",
            )
    except SheetBuildError:
        raise
    except Exception:
        # Transport exceptions can embed the request URL. Keep diagnostics free
        # of endpoint parameters and any redirected temporary URLs.
        raise SheetBuildError("Research image bridge request failed") from None

    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SheetBuildError("Research image bridge returned invalid JSON") from None
    if not isinstance(manifest, dict):
        raise SheetBuildError("Research image bridge response must be a JSON object")
    if manifest.get("ok") is not True:
        error = manifest.get("error")
        raw_code = error.get("code") if isinstance(error, dict) else None
        code = (
            raw_code
            if isinstance(raw_code, str)
            and len(raw_code) <= 64
            and re.fullmatch(r"[A-Z0-9_]+", raw_code)
            else "UNKNOWN_ERROR"
        )
        raise SheetBuildError(f"Research image bridge rejected request ({code})")
    if manifest.get("schema_version") != RESEARCH_IMAGE_SCHEMA_VERSION:
        raise SheetBuildError("Research image bridge schema version is unsupported")
    if manifest.get("sheet") != "Research":
        raise SheetBuildError("Research image bridge returned the wrong Sheet tab")
    if not isinstance(manifest.get("generated_at"), str):
        raise SheetBuildError("Research image bridge is missing generated_at")
    images = manifest.get("images")
    if not isinstance(images, list):
        raise SheetBuildError("Research image bridge images must be a JSON array")

    expected = {
        (row["slug"], slot)
        for row in research_rows
        for slot in (1, 2)
    }
    validated: Dict[Tuple[str, int], Dict[str, str]] = {}
    for entry in images:
        if not isinstance(entry, dict):
            raise SheetBuildError("Research image bridge contains an invalid entry")
        slug = entry.get("slug")
        slot = entry.get("slot")
        if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
            raise SheetBuildError("Research image bridge contains an invalid slug")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot not in (1, 2):
            raise SheetBuildError("Research image bridge contains an invalid slot")
        key = (slug, slot)
        if key not in expected:
            raise SheetBuildError(
                f"Research image bridge returned unexpected image {slug!r} slot {slot}"
            )
        if key in validated:
            raise SheetBuildError(
                f"Research image bridge duplicated image {slug!r} slot {slot}"
            )
        if entry.get("field") != f"figure_{slot}_image":
            raise SheetBuildError(
                f"Research image bridge returned the wrong field for {slug!r} slot {slot}"
            )
        content_url = entry.get("content_url")
        if not isinstance(content_url, str) or not content_url:
            raise SheetBuildError(
                f"Research image bridge omitted image data for {slug!r} slot {slot}"
            )
        _validate_google_image_url(
            content_url,
            f"Research image {slug!r} slot {slot}",
        )
        alt = entry.get("alt")
        credit = entry.get("credit")
        if not isinstance(alt, str) or not alt.strip() or len(alt) > 4000:
            raise SheetBuildError(
                f"Research image {slug!r} slot {slot}: invalid alt text"
            )
        if not isinstance(credit, str) or len(credit) > 4000:
            raise SheetBuildError(
                f"Research image {slug!r} slot {slot}: invalid credit"
            )
        validated[key] = {
            "content_url": content_url,
            "alt": alt.strip(),
            "credit": credit.strip(),
        }

    missing = sorted(expected - set(validated))
    if missing:
        labels = ", ".join(f"{slug} slot {slot}" for slug, slot in missing)
        raise SheetBuildError(f"Research image bridge is missing: {labels}")
    return validated


def _detect_image_format(payload: bytes) -> Tuple[str, set[str]]:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", {"image/png"}
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg", {"image/jpeg", "image/jpg"}
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "gif", {"image/gif"}
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp", {"image/webp"}
    raise SheetBuildError("Sheet image has an unsupported or invalid file signature")


def _download_research_image(
    content_url: str,
    slug: str,
    slot: int,
    output_dir: Path,
    timeout: float,
) -> str:
    label = f"Research image {slug!r} slot {slot}"
    _validate_google_image_url(content_url, label)
    request = urllib.request.Request(
        content_url,
        headers={
            "Accept": "image/png,image/jpeg,image/gif,image/webp",
            "Cache-Control": "no-store",
            "User-Agent": "EconAI-Site-Builder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise SheetBuildError(f"{label}: download returned an HTTP error")
            get_final_url = getattr(response, "geturl", None)
            final_url = get_final_url() if callable(get_final_url) else content_url
            _validate_google_image_url(final_url, label)
            content_type = _response_content_type(response)
            payload = _read_limited_response(
                response,
                RESEARCH_IMAGE_FILE_LIMIT,
                label,
            )
    except SheetBuildError:
        raise
    except Exception:
        # urllib exceptions can include the temporary content URL. Never expose
        # it through the CLI, systemd journal, or publisher status.
        raise SheetBuildError(f"{label}: download failed") from None

    extension, accepted_content_types = _detect_image_format(payload)
    if content_type not in accepted_content_types:
        raise SheetBuildError(f"{label}: Content-Type does not match the image")
    digest = hashlib.sha256(payload).hexdigest()
    relative_path = RESEARCH_IMAGE_ASSET_DIR / (
        f"{slug}-{slot}-{digest[:16]}.{extension}"
    )
    target = output_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != payload:
        raise SheetBuildError(f"{label}: generated asset name collision")
    target.write_bytes(payload)
    return relative_path.as_posix()


def _materialise_research_images(
    research_rows: Sequence[Dict[str, str]],
    output_dir: Path,
    endpoint: str | None,
    token: str | None,
    timeout: float,
) -> Dict[Tuple[str, int], Dict[str, str]]:
    manifest = _fetch_research_image_manifest(
        research_rows,
        endpoint,
        token,
        timeout,
    )
    assets: Dict[Tuple[str, int], Dict[str, str]] = {}
    for key in sorted(manifest):
        slug, slot = key
        entry = manifest[key]
        assets[key] = {
            "url": _download_research_image(
                entry["content_url"],
                slug,
                slot,
                output_dir,
                timeout,
            ),
            "alt": entry["alt"],
            "credit": entry["credit"],
        }
    return assets


def _xlsx_relationships_path(source_path: str) -> str:
    parent, name = posixpath.split(source_path)
    return posixpath.join(parent, "_rels", f"{name}.rels")


def _xlsx_resolve_target(source_path: str, target: str, label: str) -> str:
    if not target or "\\" in target:
        raise SheetBuildError(f"{label}: invalid XLSX relationship target")
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme or parsed.netloc or target.startswith("/"):
        raise SheetBuildError(f"{label}: external XLSX relationship is not allowed")
    resolved = posixpath.normpath(
        posixpath.join(posixpath.dirname(source_path), target)
    )
    parts = PurePosixPath(resolved).parts
    if not parts or parts[0] != "xl" or ".." in parts:
        raise SheetBuildError(f"{label}: XLSX relationship escapes the workbook")
    return resolved


def _validate_xlsx_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > PUBLICATION_WORKBOOK_MAX_MEMBERS:
        raise SheetBuildError("Sheet workbook contains too many files")
    seen: set[str] = set()
    total_size = 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name).parts
        if (
            not name
            or "\\" in name
            or name.startswith("/")
            or ".." in parts
            or name in seen
        ):
            raise SheetBuildError("Sheet workbook has an unsafe ZIP entry")
        seen.add(name)
        if info.flag_bits & 0x1:
            raise SheetBuildError("Sheet workbook contains an encrypted file")
        if ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise SheetBuildError("Sheet workbook contains a symbolic link")
        if info.file_size > PUBLICATION_WORKBOOK_MEMBER_LIMIT:
            raise SheetBuildError("Sheet workbook file exceeds the size limit")
        total_size += info.file_size
        if total_size > PUBLICATION_WORKBOOK_UNCOMPRESSED_LIMIT:
            raise SheetBuildError(
                "Sheet workbook exceeds the uncompressed size limit"
            )


def _xlsx_read_member(
    archive: zipfile.ZipFile,
    name: str,
    label: str,
) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise SheetBuildError(f"{label}: missing XLSX file {name}") from exc
    if info.file_size > PUBLICATION_WORKBOOK_MEMBER_LIMIT:
        raise SheetBuildError(f"{label}: XLSX file exceeds the size limit")
    try:
        with archive.open(info) as stream:
            payload = stream.read(PUBLICATION_WORKBOOK_MEMBER_LIMIT + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SheetBuildError(f"{label}: invalid XLSX file {name}") from exc
    if len(payload) > PUBLICATION_WORKBOOK_MEMBER_LIMIT:
        raise SheetBuildError(f"{label}: XLSX file exceeds the size limit")
    if len(payload) != info.file_size:
        raise SheetBuildError(f"{label}: incomplete XLSX file {name}")
    return payload


def _xlsx_xml(
    archive: zipfile.ZipFile,
    name: str,
    label: str,
) -> ElementTree.Element:
    payload = _xlsx_read_member(archive, name, label)
    if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
        raise SheetBuildError(f"{label}: XML entities are not allowed")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise SheetBuildError(f"{label}: malformed XLSX XML") from exc


def _xlsx_relationship_target(
    archive: zipfile.ZipFile,
    source_path: str,
    relationship_id: str,
    expected_type: str,
    label: str,
) -> str:
    relationships = _xlsx_xml(
        archive,
        _xlsx_relationships_path(source_path),
        label,
    )
    matches = [
        node
        for node in relationships.findall(
            f"{{{XLSX_PACKAGE_REL_NS}}}Relationship"
        )
        if node.get("Id") == relationship_id
    ]
    if len(matches) != 1:
        raise SheetBuildError(f"{label}: XLSX relationship is missing or duplicated")
    relationship = matches[0]
    if relationship.get("TargetMode", "Internal") != "Internal":
        raise SheetBuildError(f"{label}: external XLSX relationship is not allowed")
    relationship_type = relationship.get("Type", "")
    if not relationship_type.endswith(f"/{expected_type}"):
        raise SheetBuildError(f"{label}: XLSX relationship has the wrong type")
    return _xlsx_resolve_target(
        source_path,
        relationship.get("Target", ""),
        label,
    )


def _xlsx_named_sheet(
    archive: zipfile.ZipFile,
    sheet_name: str,
) -> Tuple[str, ElementTree.Element]:
    workbook_path = "xl/workbook.xml"
    workbook = _xlsx_xml(archive, workbook_path, "Sheet workbook")
    sheets = [
        node
        for node in workbook.findall(
            f".//{{{XLSX_MAIN_NS}}}sheet"
        )
        if node.get("name") == sheet_name
    ]
    if len(sheets) != 1:
        raise SheetBuildError(
            f"Sheet workbook must contain exactly one {sheet_name} sheet"
        )
    relationship_id = sheets[0].get(f"{{{XLSX_DOCUMENT_REL_NS}}}id", "")
    worksheet_path = _xlsx_relationship_target(
        archive,
        workbook_path,
        relationship_id,
        "worksheet",
        f"{sheet_name} workbook",
    )
    return (
        worksheet_path,
        _xlsx_xml(archive, worksheet_path, f"{sheet_name} worksheet"),
    )


def _xlsx_publications_sheet(
    archive: zipfile.ZipFile,
) -> Tuple[str, ElementTree.Element]:
    return _xlsx_named_sheet(archive, "Publications")


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _xlsx_xml(
        archive,
        "xl/sharedStrings.xml",
        "Sheet shared strings",
    )
    return [
        "".join(
            text.text or ""
            for text in item.findall(f".//{{{XLSX_MAIN_NS}}}t")
        )
        for item in root.findall(f"{{{XLSX_MAIN_NS}}}si")
    ]


def _xlsx_column_index(cell_reference: str) -> int:
    match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", cell_reference)
    if match is None:
        raise SheetBuildError("XLSX worksheet has an invalid cell reference")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _xlsx_cell_values(
    worksheet: ElementTree.Element,
    shared_strings: Sequence[str],
) -> Dict[Tuple[int, int], str]:
    values: Dict[Tuple[int, int], str] = {}
    for cell in worksheet.findall(f".//{{{XLSX_MAIN_NS}}}c"):
        reference = cell.get("r", "")
        match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", reference)
        if match is None:
            raise SheetBuildError(
                "XLSX worksheet has an invalid cell reference"
            )
        column = _xlsx_column_index(reference)
        row = int(match.group(2)) - 1
        cell_type = cell.get("t", "")
        if cell_type == "inlineStr":
            value = "".join(
                text.text or ""
                for text in cell.findall(f".//{{{XLSX_MAIN_NS}}}t")
            )
        else:
            value_node = cell.find(f"{{{XLSX_MAIN_NS}}}v")
            raw_value = value_node.text if value_node is not None else ""
            if cell_type == "s" and raw_value:
                try:
                    shared_index = int(raw_value)
                    value = shared_strings[shared_index]
                except (ValueError, IndexError) as exc:
                    raise SheetBuildError(
                        "XLSX worksheet has an invalid shared string"
                    ) from exc
            else:
                value = raw_value or ""
        key = (row, column)
        if key in values:
            raise SheetBuildError("XLSX worksheet duplicated a cell")
        values[key] = value.strip()
    return values


def _xlsx_cell_formulas(
    worksheet: ElementTree.Element,
) -> Dict[Tuple[int, int], str]:
    formulas: Dict[Tuple[int, int], str] = {}
    for cell in worksheet.findall(f".//{{{XLSX_MAIN_NS}}}c"):
        formula_node = cell.find(f"{{{XLSX_MAIN_NS}}}f")
        if formula_node is None or not (formula_node.text or "").strip():
            continue
        reference = cell.get("r", "")
        match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", reference)
        if match is None:
            raise SheetBuildError(
                "XLSX worksheet has an invalid cell reference"
            )
        key = (int(match.group(2)) - 1, _xlsx_column_index(reference))
        if key in formulas:
            raise SheetBuildError("XLSX worksheet duplicated a formula cell")
        formulas[key] = (formula_node.text or "").strip()
    return formulas


def _publication_image_formula_url(formula: str, label: str) -> str:
    match = re.fullmatch(
        r'(?:_xlfn\.)?IMAGE\(\s*"([^"]+)"\s*\)',
        formula,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise SheetBuildError(
            f'{label}: home_image formula must use IMAGE("https://...")'
        )
    value = match.group(1)
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise SheetBuildError(
            f"{label}: home_image formula has an invalid URL"
        ) from None
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or hostname not in PUBLICATION_IMAGE_FORMULA_HOSTS
        or not parsed.path
        or parsed.fragment
    ):
        raise SheetBuildError(f"{label}: home_image formula URL is not allowed")
    return value


def _download_publication_formula_image(
    content_url: str,
    title: str,
    timeout: float,
) -> bytes:
    label = f"Publications image for {title!r}"
    _publication_image_formula_url(f'IMAGE("{content_url}")', label)
    request = urllib.request.Request(
        content_url,
        headers={
            "Accept": "image/png,image/jpeg,image/gif,image/webp",
            "Cache-Control": "no-store",
            "User-Agent": "EconAI-Site-Builder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise SheetBuildError(f"{label}: download returned an HTTP error")
            get_final_url = getattr(response, "geturl", None)
            final_url = get_final_url() if callable(get_final_url) else content_url
            _publication_image_formula_url(f'IMAGE("{final_url}")', label)
            content_type = _response_content_type(response)
            payload = _read_limited_response(
                response,
                PUBLICATION_IMAGE_FILE_LIMIT,
                label,
            )
    except SheetBuildError:
        raise
    except Exception:
        raise SheetBuildError(f"{label}: download failed") from None

    extension, accepted_content_types = _detect_image_format(payload)
    if content_type not in accepted_content_types:
        raise SheetBuildError(f"{label}: Content-Type does not match the image")
    return payload


def _publication_asset_key(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


def _materialise_publication_images(
    workbook_payload: bytes,
    publications: Sequence[Dict[str, str]],
    output_dir: Path,
    timeout: float = 30.0,
) -> Dict[str, Dict[str, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(workbook_payload))
    except zipfile.BadZipFile as exc:
        raise SheetBuildError("Publications workbook export is not a valid XLSX") from exc

    with archive:
        _validate_xlsx_archive(archive)
        worksheet_path, worksheet = _xlsx_publications_sheet(archive)
        values = _xlsx_cell_values(worksheet, _xlsx_shared_strings(archive))
        formulas = _xlsx_cell_formulas(worksheet)

        headers: Dict[str, int] = {}
        for (row, column), value in values.items():
            if row != 0 or not value:
                continue
            if value in headers:
                raise SheetBuildError(
                    f"Publications workbook duplicated header {value!r}"
                )
            headers[value] = column
        if _publication_image_schema(headers) != "direct_cell":
            raise SheetBuildError(
                "Publications workbook is missing the direct home image columns"
            )
        for required in ("publish", "title"):
            if required not in headers:
                raise SheetBuildError(
                    f"Publications workbook is missing header {required!r}"
                )

        latest = _latest_home_publications(publications)
        expected_titles = {row["title"] for row in latest}
        title_rows: Dict[str, int] = {}
        worksheet_rows = {row for row, _ in values if row > 0}
        for row in sorted(worksheet_rows):
            publish = values.get((row, headers["publish"]), "").casefold()
            if publish not in TRUTHY:
                continue
            title = values.get((row, headers["title"]), "")
            if title not in expected_titles:
                continue
            if title in title_rows:
                raise SheetBuildError(
                    f"Publications workbook duplicated published title {title!r}"
                )
            title_rows[title] = row
        missing_rows = expected_titles - set(title_rows)
        if missing_rows:
            labels = ", ".join(sorted(missing_rows))
            raise SheetBuildError(
                f"Publications workbook is out of sync for latest published papers: {labels}"
            )

        drawing = worksheet.find(f"{{{XLSX_MAIN_NS}}}drawing")
        drawing_path = ""
        drawing_root = None
        if drawing is not None:
            drawing_relationship_id = drawing.get(
                f"{{{XLSX_DOCUMENT_REL_NS}}}id", ""
            )
            drawing_path = _xlsx_relationship_target(
                archive,
                worksheet_path,
                drawing_relationship_id,
                "drawing",
                "Publications drawing",
            )
            drawing_root = _xlsx_xml(
                archive,
                drawing_path,
                "Publications drawing",
            )
        row_to_title = {row: title for title, row in title_rows.items()}
        image_column = headers["home_image"]
        image_targets: Dict[str, str] = {}
        home_image_anchor_count = 0
        anchors = (
            drawing_root.findall(f"{{{XLSX_DRAWING_NS}}}oneCellAnchor")
            if drawing_root is not None
            else []
        )
        for anchor in anchors:
            row_text = anchor.findtext(
                f"{{{XLSX_DRAWING_NS}}}from/{{{XLSX_DRAWING_NS}}}row"
            )
            column_text = anchor.findtext(
                f"{{{XLSX_DRAWING_NS}}}from/{{{XLSX_DRAWING_NS}}}col"
            )
            try:
                row = int(row_text or "")
                column = int(column_text or "")
            except ValueError as exc:
                raise SheetBuildError(
                    "Publications drawing has an invalid image anchor"
                ) from exc
            if column != image_column:
                continue
            home_image_anchor_count += 1
            title = row_to_title.get(row)
            if title is None:
                continue
            blip = anchor.find(f".//{{{XLSX_DRAWING_MAIN_NS}}}blip")
            relationship_id = (
                blip.get(f"{{{XLSX_DOCUMENT_REL_NS}}}embed", "")
                if blip is not None
                else ""
            )
            if not relationship_id:
                raise SheetBuildError(
                    f"Publications image for {title!r} has no embedded file"
                )
            if title in image_targets:
                raise SheetBuildError(
                    f"Publications image for {title!r} is duplicated"
                )
            image_targets[title] = _xlsx_relationship_target(
                archive,
                drawing_path,
                relationship_id,
                "image",
                f"Publications image for {title!r}",
            )

        formula_urls: Dict[str, str] = {}
        for title, row in title_rows.items():
            formula = formulas.get((row, image_column), "")
            if not formula:
                continue
            if title in image_targets:
                raise SheetBuildError(
                    f"Publications image for {title!r} is both embedded and formula-based"
                )
            formula_urls[title] = _publication_image_formula_url(
                formula,
                f"Publications image for {title!r}",
            )

        if home_image_anchor_count == 0 and not formula_urls:
            return {}
        missing_images = expected_titles - set(image_targets) - set(formula_urls)
        if missing_images:
            labels = ", ".join(sorted(missing_images))
            raise SheetBuildError(
                f"Publications: latest published papers need home images: {labels}"
            )

        assets: Dict[str, Dict[str, str]] = {}
        for row in latest:
            title = row["title"]
            sheet_row = title_rows[title]
            alt = values.get((sheet_row, headers["home_image_alt"]), "")
            credit = values.get((sheet_row, headers["home_image_credit"]), "")
            if not alt or len(alt) > 4000:
                raise SheetBuildError(
                    f"Publications image for {title!r} needs valid alt text"
                )
            if len(credit) > 4000:
                raise SheetBuildError(
                    f"Publications image for {title!r} has invalid credit text"
                )
            if title in image_targets:
                payload = _xlsx_read_member(
                    archive,
                    image_targets[title],
                    f"Publications image for {title!r}",
                )
            else:
                payload = _download_publication_formula_image(
                    formula_urls[title],
                    title,
                    timeout,
                )
            extension, _ = _detect_image_format(payload)
            digest = hashlib.sha256(payload).hexdigest()
            relative_path = PUBLICATION_IMAGE_ASSET_DIR / (
                f"{_publication_asset_key(title)}-{digest[:16]}.{extension}"
            )
            target = output_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != payload:
                raise SheetBuildError(
                    f"Publications image for {title!r}: asset name collision"
                )
            target.write_bytes(payload)
            assets[title] = {
                "url": relative_path.as_posix(),
                "alt": alt,
                "credit": credit,
            }
    return assets


def _member_identity(row: Mapping[str, str]) -> Tuple[str, str, str]:
    return (
        row.get("section", ""),
        row.get("group", ""),
        row.get("name_en", ""),
    )


def _member_asset_key(identity: Tuple[str, str, str]) -> str:
    return hashlib.sha256("\0".join(identity).encode("utf-8")).hexdigest()[:16]


def _member_formula_image_payload(
    formula: str,
    member_name: str,
    output_dir: Path,
) -> bytes:
    label = f"Members photo for {member_name!r}"
    match = re.fullmatch(
        r'(?:_xlfn\.)?IMAGE\(\s*"([^"]+)"\s*\)',
        formula,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise SheetBuildError(
            f'{label}: formula must use IMAGE("https://econai.kaist.ac.kr/img/...")'
        )
    try:
        parsed = urllib.parse.urlsplit(match.group(1))
        port = parsed.port
        decoded_path = urllib.parse.unquote(parsed.path)
    except ValueError:
        raise SheetBuildError(f"{label}: formula URL is invalid") from None
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "econai.kaist.ac.kr"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not decoded_path.startswith("/img/")
        or "\\" in decoded_path
        or parsed.query
        or parsed.fragment
    ):
        raise SheetBuildError(f"{label}: formula URL is not allowed")
    relative_path = PurePosixPath(decoded_path.lstrip("/"))
    if not relative_path.parts or ".." in relative_path.parts:
        raise SheetBuildError(f"{label}: formula path is unsafe")
    source = (output_dir / Path(*relative_path.parts)).resolve()
    try:
        source.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise SheetBuildError(f"{label}: formula path leaves the site") from exc
    try:
        if not source.is_file() or source.stat().st_size > MEMBER_IMAGE_FILE_LIMIT:
            raise SheetBuildError(f"{label}: source image is missing or too large")
        payload = source.read_bytes()
    except OSError as exc:
        raise SheetBuildError(f"{label}: source image cannot be read") from exc
    _detect_image_format(payload)
    return payload


def _materialise_member_images(
    workbook_payload: bytes,
    members: Sequence[Dict[str, str]],
    output_dir: Path,
) -> Dict[Tuple[str, str, str], str]:
    """Extract member photos from the Members ``photo`` cells.

    Google renders an in-cell image as an empty value in the CSV feed, while
    retaining its binary and cell anchor in the XLSX export.  Member identity,
    rather than the physical row number, binds each extracted image to a card.
    During migration, a tightly scoped IMAGE formula may reference an existing
    image under this site's own ``/img/`` directory.
    """

    try:
        archive = zipfile.ZipFile(io.BytesIO(workbook_payload))
    except zipfile.BadZipFile as exc:
        raise SheetBuildError("Members workbook export is not a valid XLSX") from exc

    with archive:
        _validate_xlsx_archive(archive)
        worksheet_path, worksheet = _xlsx_named_sheet(archive, "Members")
        values = _xlsx_cell_values(worksheet, _xlsx_shared_strings(archive))
        formulas = _xlsx_cell_formulas(worksheet)

        headers: Dict[str, int] = {}
        for (row, column), value in values.items():
            if row != 0 or not value:
                continue
            if value in headers:
                raise SheetBuildError(f"Members workbook duplicated header {value!r}")
            headers[value] = column
        for required in ("publish", "section", "group", "name_en", "photo"):
            if required not in headers:
                raise SheetBuildError(
                    f"Members workbook is missing header {required!r}"
                )

        expected = {
            _member_identity(row): row
            for row in members
            if row["section"] in MEMBER_CARD_SECTIONS
        }
        identity_rows: Dict[Tuple[str, str, str], int] = {}
        worksheet_rows = {row for row, _ in values if row > 0}
        for row in sorted(worksheet_rows):
            publish = values.get((row, headers["publish"]), "").casefold()
            if publish not in TRUTHY:
                continue
            identity = (
                values.get((row, headers["section"]), ""),
                values.get((row, headers["group"]), ""),
                values.get((row, headers["name_en"]), ""),
            )
            if identity not in expected:
                continue
            if identity in identity_rows:
                raise SheetBuildError(
                    f"Members workbook duplicated published member {identity[2]!r}"
                )
            identity_rows[identity] = row

        missing_rows = set(expected) - set(identity_rows)
        if missing_rows:
            labels = ", ".join(sorted(identity[2] for identity in missing_rows))
            raise SheetBuildError(
                f"Members workbook is out of sync for published cards: {labels}"
            )

        image_column = headers["photo"]
        drawing = worksheet.find(f"{{{XLSX_MAIN_NS}}}drawing")
        drawing_path = ""
        drawing_root = None
        if drawing is not None:
            drawing_relationship_id = drawing.get(
                f"{{{XLSX_DOCUMENT_REL_NS}}}id", ""
            )
            drawing_path = _xlsx_relationship_target(
                archive,
                worksheet_path,
                drawing_relationship_id,
                "drawing",
                "Members drawing",
            )
            drawing_root = _xlsx_xml(archive, drawing_path, "Members drawing")
        row_to_identity = {row: identity for identity, row in identity_rows.items()}
        image_targets: Dict[Tuple[str, str, str], str] = {}
        anchors = (
            drawing_root.findall(f"{{{XLSX_DRAWING_NS}}}oneCellAnchor")
            if drawing_root is not None
            else []
        )
        for anchor in anchors:
            row_text = anchor.findtext(
                f"{{{XLSX_DRAWING_NS}}}from/{{{XLSX_DRAWING_NS}}}row"
            )
            column_text = anchor.findtext(
                f"{{{XLSX_DRAWING_NS}}}from/{{{XLSX_DRAWING_NS}}}col"
            )
            try:
                row = int(row_text or "")
                column = int(column_text or "")
            except ValueError as exc:
                raise SheetBuildError(
                    "Members drawing has an invalid image anchor"
                ) from exc
            if column != image_column:
                continue
            identity = row_to_identity.get(row)
            if identity is None:
                continue
            blip = anchor.find(f".//{{{XLSX_DRAWING_MAIN_NS}}}blip")
            relationship_id = (
                blip.get(f"{{{XLSX_DOCUMENT_REL_NS}}}embed", "")
                if blip is not None
                else ""
            )
            if not relationship_id:
                raise SheetBuildError(
                    f"Members photo for {identity[2]!r} has no embedded file"
                )
            if identity in image_targets:
                raise SheetBuildError(
                    f"Members photo for {identity[2]!r} is duplicated"
                )
            image_targets[identity] = _xlsx_relationship_target(
                archive,
                drawing_path,
                relationship_id,
                "image",
                f"Members photo for {identity[2]!r}",
            )

        formula_payloads: Dict[Tuple[str, str, str], bytes] = {}
        for identity, row in identity_rows.items():
            formula = formulas.get((row, image_column), "")
            if not formula:
                continue
            if identity in image_targets:
                raise SheetBuildError(
                    f"Members photo for {identity[2]!r} is both embedded and formula-based"
                )
            formula_payloads[identity] = _member_formula_image_payload(
                formula,
                identity[2],
                output_dir,
            )

        assets: Dict[Tuple[str, str, str], str] = {}
        for identity in sorted(set(image_targets) | set(formula_payloads)):
            if identity in image_targets:
                payload = _xlsx_read_member(
                    archive,
                    image_targets[identity],
                    f"Members photo for {identity[2]!r}",
                )
            else:
                payload = formula_payloads[identity]
            if len(payload) > MEMBER_IMAGE_FILE_LIMIT:
                raise SheetBuildError(
                    f"Members photo for {identity[2]!r} exceeds the size limit"
                )
            extension, _ = _detect_image_format(payload)
            digest = hashlib.sha256(payload).hexdigest()
            relative_path = MEMBER_IMAGE_ASSET_DIR / (
                f"{_member_asset_key(identity)}-{digest[:16]}.{extension}"
            )
            target = output_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != payload:
                raise SheetBuildError(
                    f"Members photo for {identity[2]!r}: asset name collision"
                )
            target.write_bytes(payload)
            assets[identity] = relative_path.as_posix()
    return assets


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


def _latest_home_publications(
    rows: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    published = [
        row
        for row in rows
        if not row.get("venue", "").strip().casefold().startswith("arxiv")
    ]
    return _sort_publications(published)[:3]


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
            f'                                <a class="publication-project-link publication-distinction publication-distinction--project" href="{project_url}" aria-label="{label}">Project Page</a>'
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
    by_year: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    # The Sheet is the editorial ordering surface for each year.  Grouping the
    # original sequence preserves that order while the year headings themselves
    # remain newest first.  The home page intentionally uses date sorting via
    # ``_sort_publications`` instead.
    for row in publications:
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


def render_home_latest(
    publications: Sequence[Dict[str, str]],
    publication_images: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    latest = _latest_home_publications(publications)
    images = publication_images or {}

    # Keep the production page clean while the optional Sheet image cells are
    # being prepared.  The figure carousel is an enhancement, so it appears
    # only after all three latest conference/journal papers have real images.
    if not images:
        lines = [
            '        <div class="publication-panel publication-panel-wide">',
            '          <ol class="publication-list">',
        ]
        for row in latest:
            lines.extend(
                [
                    "            <li>",
                    f'              <a href="{_escape(row["paper_url"], quote=True)}">{_escape(row["title"])}</a>',
                    f'              <p class="publication-authors">{_escape(_short_authors(row["authors"]))}</p>',
                    f'              <p class="publication-venue">{_escape(row["venue"])}</p>',
                    "            </li>",
                ]
            )
        lines.extend(
            [
                "          </ol>",
                '          <a class="text-link" href="publications.html">View all publications →</a>',
                "        </div>",
            ]
        )
        return "\n".join(lines)

    missing_images = {row["title"] for row in latest} - set(images)
    if missing_images:
        labels = ", ".join(sorted(missing_images))
        raise SheetBuildError(
            f"Homepage carousel is missing publication images: {labels}"
        )

    lines = [
        '        <div class="latest-publications-layout">',
        '          <div class="publication-panel">',
        '            <ol class="publication-list">',
    ]
    for row in latest:
        lines.extend(
            [
                "              <li>",
                f'                <a href="{_escape(row["paper_url"], quote=True)}">{_escape(row["title"])}</a>',
                f'                <p class="publication-authors">{_escape(_short_authors(row["authors"]))}</p>',
                f'                <p class="publication-venue">{_escape(row["venue"])}</p>',
                "              </li>",
            ]
        )
    lines.extend(
        [
            "            </ol>",
            '            <a class="text-link" href="publications.html">View all publications →</a>',
            "          </div>",
            '          <div class="publication-figure-carousel" data-publication-carousel tabindex="0" role="region" aria-roledescription="carousel" aria-label="Representative figures from the latest publications">',
            '            <div class="publication-figure-stage">',
            '              <div class="publication-figure-slides" id="latest-publication-figures">',
        ]
    )
    slide_count = len(latest)
    for index, row in enumerate(latest):
        figure = images[row["title"]]
        hidden = "" if index == 0 else " hidden"
        fetch_priority = "high" if index == 0 else "low"
        visual_lines = [
            f'                    <img class="publication-figure-image" src="{_escape(figure["url"], quote=True)}" alt="{_escape(figure["alt"], quote=True)}" loading="eager" fetchpriority="{fetch_priority}" decoding="sync">'
        ]
        lines.extend(
            [
                f'                <article class="publication-figure-slide" data-carousel-slide role="group" aria-roledescription="slide" aria-label="{index + 1} of {slide_count}"{hidden}>',
                f'                  <a class="publication-figure-link" href="{_escape(row["paper_url"], quote=True)}" aria-label="Open paper: {_escape(row["title"], quote=True)}">',
                '                    <span class="publication-figure-frame">',
                *visual_lines,
                "                    </span>",
                "                  </a>",
                "                </article>",
            ]
        )
    lines.extend(
        [
            "              </div>",
            '              <button class="publication-carousel-button publication-carousel-button--previous" type="button" data-carousel-previous aria-controls="latest-publication-figures" aria-label="Show previous publication figure"><svg class="publication-carousel-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M15 5 8 12l7 7"/></svg></button>',
            '              <button class="publication-carousel-button publication-carousel-button--next" type="button" data-carousel-next aria-controls="latest-publication-figures" aria-label="Show next publication figure"><svg class="publication-carousel-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 5 7 7-7 7"/></svg></button>',
            "            </div>",
            '            <div class="publication-figure-captions">',
        ]
    )
    for index, row in enumerate(latest):
        hidden = "" if index == 0 else " hidden"
        lines.append(
            f'              <a class="publication-figure-caption" data-carousel-caption href="{_escape(row["paper_url"], quote=True)}"{hidden}>{_escape(row["title"])}</a>'
        )
    lines.extend(
        [
            "            </div>",
            '            <div class="publication-carousel-pagination" aria-label="Choose publication figure">',
        ]
    )
    for index, row in enumerate(latest):
        current = ' aria-current="true"' if index == 0 else ""
        lines.append(
            f'              <button class="publication-carousel-dot" type="button" data-carousel-dot aria-label="Show figure {index + 1}: {_escape(row["title"], quote=True)}"{current}></button>'
        )
    lines.extend(
        [
            "            </div>",
            f'            <span class="publication-carousel-status" data-carousel-status aria-live="polite" aria-atomic="true">1 / {slide_count}</span>',
            "          </div>",
            "        </div>",
        ]
    )
    return "\n".join(lines)


def _publication_lookup(
    publications: Sequence[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    return {row["title"]: row for row in publications}


def _resolve_publication(
    publication_title: str,
    publication_lookup: Mapping[str, Dict[str, str]],
    reference_label: str,
) -> Dict[str, str]:
    publication = publication_lookup.get(publication_title)
    if publication is None:
        raise SheetBuildError(
            f"{reference_label} does not exactly match a published "
            f"Publications title: {publication_title!r}"
        )
    return publication


def _validate_publication_references(
    tabs: Mapping[str, List[Dict[str, str]]],
) -> None:
    publication_lookup = _publication_lookup(tabs["Publications"])
    for row in tabs["Research"]:
        for slot in (1, 2):
            field = f"selected_publication_{slot}"
            _resolve_publication(
                row[field],
                publication_lookup,
                f"Research {row['slug']!r} {field}",
            )
    for row in tabs["News"]:
        for slot in (1, 2):
            field = f"related_publication_{slot}"
            if row.get(field):
                _resolve_publication(
                    row[field],
                    publication_lookup,
                    f"News {row['title']!r} {field}",
                )
    for row in tabs["Projects"]:
        if row.get("related_publication"):
            _resolve_publication(
                row["related_publication"],
                publication_lookup,
                f"Projects {row['title']!r} related_publication",
            )


def _selected_publication_lines(
    publication_title: str,
    figure_url: str,
    figure_alt: str,
    figure_credit: str,
    publication_lookup: Mapping[str, Dict[str, str]],
    output_dir: Path,
) -> List[str]:
    publication = _resolve_publication(
        publication_title,
        publication_lookup,
        "Research selected publication",
    )

    parsed_figure = urllib.parse.urlparse(figure_url)
    if not parsed_figure.scheme and not parsed_figure.netloc:
        figure_path = (output_dir / figure_url).resolve()
        try:
            figure_path.relative_to(output_dir.resolve())
        except ValueError as exc:
            raise SheetBuildError(
                f"{publication_title}: figure URL must stay inside the site"
            ) from exc
        if not figure_path.is_file():
            raise SheetBuildError(
                f"{publication_title}: missing figure asset {figure_path}"
            )

    display_title = publication.get("research_title") or publication["title"]
    paper_url = _escape(publication["paper_url"], quote=True)
    aria_label = _escape(f"Open {display_title}", quote=True)
    return [
        "                  <li>",
        f'                    <a class="selected-figure-link" href="{paper_url}" aria-label="{aria_label}">',
        f'                      <span class="selected-figure-frame"><img src="{_escape(figure_url, quote=True)}" alt="{_escape(figure_alt, quote=True)}" loading="lazy" decoding="async"></span>',
        "                    </a>",
        f'                    <a class="selected-title" href="{paper_url}">{_escape(display_title)}</a>',
        f'                    <span>{_escape(publication["venue"])}</span>',
        f'                    <small class="selected-figure-credit">{_escape(figure_credit)}</small>',
        "                  </li>",
    ]


def render_research_areas(
    research_rows: Sequence[Dict[str, str]],
    publications: Sequence[Dict[str, str]],
    output_dir: Path,
    research_images: Mapping[Tuple[str, int], Mapping[str, str]] | None = None,
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
        for slot in (1, 2):
            if research_images is None:
                figure_url = row[f"figure_{slot}_url"]
                figure_alt = row[f"figure_{slot}_alt"]
                figure_credit = row[f"figure_{slot}_credit"]
            else:
                image = research_images.get((slug, slot))
                if image is None:
                    raise SheetBuildError(
                        f"Research image asset is missing for {slug!r} slot {slot}"
                    )
                figure_url = image["url"]
                figure_alt = image["alt"]
                figure_credit = image["credit"]
            lines.extend(
                _selected_publication_lines(
                    row[f"selected_publication_{slot}"],
                    figure_url,
                    figure_alt,
                    figure_credit,
                    lookup,
                    output_dir,
                )
            )
        lines.extend(["                </ul>", "              </div>"])

        lines.extend(["            </div>", "          </article>"])
    lines.append("        </div>")
    return "\n".join(lines)


def _render_project_group(
    status_label: str,
    rows: Sequence[Dict[str, str]],
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
        status = row["status"]
        period = row["period"]
        area = row["area"]
        url = row.get("url", "")
        related_publication = None
        if row.get("related_publication"):
            related_publication = _resolve_publication(
                row["related_publication"],
                publication_lookup,
                f"Projects {row['title']!r} related_publication",
            )
        primary_url = url or (
            related_publication["paper_url"] if related_publication else ""
        )
        status_class = " status-completed" if status.casefold() == "completed" else ""
        title_html = (
            f'<a href="{_escape(primary_url, quote=True)}">{_escape(row["title"])}</a>'
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
                (
                    f'              <a class="project-publication-link" href="{_escape(related_publication["paper_url"], quote=True)}">Related publication →</a>'
                    if related_publication and url
                    else ""
                ),
                "            </article>",
            ]
        )
    lines.extend(["          </div>", "        </section>"])
    return [line for line in lines if line]


def render_projects(
    project_rows: Sequence[Dict[str, str]],
    publications: Sequence[Dict[str, str]],
) -> str:
    publication_lookup = _publication_lookup(publications)
    grouped: Dict[str, List[Dict[str, str]]] = {"Ongoing": [], "Completed": []}
    for row in project_rows:
        key = "Completed" if row["status"].casefold() == "completed" else "Ongoing"
        grouped[key].append(row)

    lines: List[str] = []
    for label in ("Ongoing", "Completed"):
        if grouped[label]:
            if lines:
                lines.append("")
            lines.extend(
                _render_project_group(label, grouped[label], publication_lookup)
            )
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
    titles: Iterable[str], publication_lookup: Mapping[str, Dict[str, str]]
) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    for title in (value for value in titles if value):
        publication = _resolve_publication(
            title,
            publication_lookup,
            "News related publication",
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
            (
                row.get("related_publication_1", ""),
                row.get("related_publication_2", ""),
            ),
            publication_lookup,
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


def _member_name(row: Mapping[str, str]) -> str:
    if row.get("name_ko"):
        return f'{row["name_en"]} | {row["name_ko"]}'
    return row["name_en"]


def _alumni_name_html(row: Mapping[str, str]) -> str:
    rendered = _escape(_member_name(row))
    if row.get("joint_supervisor"):
        rendered += (
            '<sup class="alumni-note-marker" '
            'aria-label="Jointly supervised">†</sup>'
        )
    return rendered


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
            f'                            <a href="{_escape(url, quote=True)}"{target} class="member-link-btn" aria-label="{aria}"><i class="{icon}" aria-hidden="true"></i></a>'
        )
    lines.append("                        </div>")
    return lines


def _member_card_lines(
    row: Mapping[str, str],
    output_dir: Path,
    member_images: Mapping[Tuple[str, str, str], str],
) -> List[str]:
    photo = member_images.get(_member_identity(row)) or row.get("photo", "")
    if not photo:
        photo = DEFAULT_MEMBER_PHOTO
    photo_path = (output_dir / photo).resolve()
    try:
        photo_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise SheetBuildError(f'{row["name_en"]}: photo must stay inside the site') from exc
    if not photo_path.is_file():
        raise SheetBuildError(f'{row["name_en"]}: missing member photo {photo_path}')
    professor = " prof-card" if row["section"] == "Faculty" else ""
    lines = [
        f'                    <article class="member-card sheet-member-item{professor}">',
        f'                        <img src="{_escape(photo, quote=True)}" alt="{_escape(row["name_en"], quote=True)}" class="member-photo">',
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
    member_rows: Sequence[Dict[str, str]],
    output_dir: Path,
    member_images: Mapping[Tuple[str, str, str], str] | None = None,
) -> str:
    resolved_member_images = member_images or {}
    sections: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in member_rows:
        sections[row["section"]].append(row)

    lines: List[str] = []
    for section in MEMBER_SECTIONS:
        rows = sections.get(section, [])
        if not rows:
            continue
        lines.append(f'                <h2 class="members-category-title">{_escape(section)}</h2>')
        if section in MEMBER_CARD_SECTIONS:
            lines.append('                <div class="members-grid">')
            for row in rows:
                lines.extend(
                    _member_card_lines(row, output_dir, resolved_member_images)
                )
            lines.append("                </div>")
        elif section == "Lab Internship":
            lines.append('                <div class="internship-terms">')
            groups: Dict[str, List[Dict[str, str]]] = {}
            for row in rows:
                groups.setdefault(row["group"], []).append(row)
            for group, group_rows in groups.items():
                lines.extend(
                    [
                        '                    <section class="internship-term">',
                        f'                        <h3 class="internship-term-label">{_escape(group)}</h3>',
                        '                        <ul class="intern-list">',
                    ]
                )
                for row in group_rows:
                    lines.append(
                        f'                            <li class="sheet-member-item">{_escape(_member_name(row))}</li>'
                    )
                lines.extend(
                    [
                        "                        </ul>",
                        "                    </section>",
                    ]
                )
            lines.append("                </div>")
        else:
            lines.append('                <ul class="alumni-list">')
            footnotes: List[Tuple[str, str]] = []
            for row in rows:
                alumni_detail = " · ".join(
                    value for value in (row.get("role", ""), row["details"]) if value
                )
                lines.extend(
                    [
                        '                    <li class="alumni-item sheet-member-item">',
                        f'                        <div class="alumni-summary"><strong>{_alumni_name_html(row)}</strong> — {_escape(alumni_detail)}</div>',
                        *_member_link_lines(row),
                        "                    </li>",
                    ]
                )
                if row.get("joint_supervisor"):
                    note = (row["joint_supervisor"], row["joint_supervisor_url"])
                    if note not in footnotes:
                        footnotes.append(note)
            lines.append("                </ul>")
            if footnotes:
                lines.append('                <div class="alumni-footnotes">')
                for supervisor, url in footnotes:
                    lines.append(
                        '                    <p><span aria-hidden="true">†</span> '
                        'Jointly supervised with '
                        f'<a href="{_escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{_escape(supervisor)}</a></p>'
                    )
                lines.append("                </div>")
        lines.append("")
    return "\n".join(lines).rstrip()


def _lab_authors(member_rows: Sequence[Dict[str, str]]) -> set[str]:
    return {row["name_en"] for row in member_rows}


def render_contact(member_rows: Sequence[Dict[str, str]]) -> str:
    faculty = [row for row in member_rows if row["section"] == "Faculty"]
    if not faculty:
        raise SheetBuildError("Members: at least one published Faculty row is required")
    primary = faculty[0]
    for field in ("email", "address"):
        if not primary.get(field):
            raise SheetBuildError(
                f"Members: first Faculty row requires {field} for contact.html"
            )
    office, separator, street_address = primary["address"].partition(", ")
    if not separator:
        office = "KAIST"
        street_address = primary["address"]
    contact_name = " ".join(
        part for part in (primary.get("role", ""), primary["name_en"]) if part
    )
    return "\n".join(
        [
            '                    <article class="frame-card">',
            '                        <div class="frame-eyebrow">Office</div>',
            f'                        <h2 class="frame-title">{_escape(office)}</h2>',
            f'                        <p class="frame-text">{_escape(street_address)}</p>',
            "                    </article>",
            '                    <article class="frame-card">',
            '                        <div class="frame-eyebrow">Email</div>',
            f'                        <h2 class="frame-title">{_escape(contact_name)}</h2>',
            f'                        <p class="frame-text"><a href="mailto:{_escape(primary["email"], quote=True)}">{_escape(primary["email"])}</a></p>',
            "                    </article>",
        ]
    )


def render_footer_affiliations(member_rows: Sequence[Dict[str, str]]) -> str:
    primary = next(
        (row for row in member_rows if row["section"] == "Faculty"),
        None,
    )
    if primary is None:
        raise SheetBuildError("Members: at least one published Faculty row is required")
    affiliations = [
        value.strip() for value in primary["affiliations"].split("|") if value.strip()
    ]
    if not affiliations:
        raise SheetBuildError("Members: first Faculty row requires affiliations")
    items = "\n".join(
        f'        <li class="footer-affiliation">{_escape(affiliation)}</li>'
        for affiliation in affiliations
    )
    return "\n".join(
        [
            '      <ul class="footer-school footer-affiliations">',
            items,
            "      </ul>",
        ]
    )


def render_site_footer(member_rows: Sequence[Dict[str, str]]) -> str:
    """Render the one canonical footer shared by every primary site page."""
    affiliations = render_footer_affiliations(member_rows)
    return "\n".join(
        [
            '  <footer class="site-footer">',
            '    <div class="container footer-inner">',
            '      <!-- SHEET:FOOTER_AFFILIATIONS:START -->',
            affiliations,
            '      <!-- SHEET:FOOTER_AFFILIATIONS:END -->',
            f'      <p class="footer-meta">{_escape(SITE_FOOTER_META)}</p>',
            "    </div>",
            "  </footer>",
        ]
    )


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
    *,
    image_endpoint: str | None = None,
    image_token: str | None = None,
    publication_workbook: bytes | None = None,
    timeout: float = 30.0,
) -> None:
    _validate_publication_references(tabs)
    _safe_prepare_output(source_dir, output_dir)

    publications = tabs["Publications"]
    research = tabs["Research"]
    projects = tabs["Projects"]
    news = tabs["News"]
    members = tabs["Members"]
    lab_authors = _lab_authors(members)
    research_image_schema = _research_image_schema(research[0].keys())
    publication_image_schema = _publication_image_schema(publications[0].keys())
    member_image_candidates = [
        row
        for row in members
        if row["section"] in MEMBER_CARD_SECTIONS and not row.get("photo")
    ]
    research_images = (
        _materialise_research_images(
            research,
            output_dir,
            image_endpoint,
            image_token,
            timeout,
        )
        if research_image_schema == "direct_cell"
        else None
    )
    if publication_image_schema == "direct_cell" and publication_workbook is None:
        raise SheetBuildError(
            "Publications direct home images require an XLSX workbook export"
        )
    publication_images = (
        _materialise_publication_images(
            publication_workbook or b"",
            publications,
            output_dir,
            timeout,
        )
        if publication_image_schema == "direct_cell"
        else None
    )
    member_images = (
        _materialise_member_images(
            publication_workbook or b"",
            members,
            output_dir,
        )
        if publication_workbook is not None and member_image_candidates
        else {}
    )

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
        render_home_latest(publications, publication_images),
    )
    _replace_block(
        output_dir / "research.html",
        "<!-- SHEET:RESEARCH_AREAS:START -->",
        "<!-- SHEET:RESEARCH_AREAS:END -->",
        render_research_areas(
            research,
            publications,
            output_dir,
            research_images,
        ),
    )
    _replace_block(
        output_dir / "projects.html",
        "<!-- SHEET:PROJECTS:START -->",
        "<!-- SHEET:PROJECTS:END -->",
        render_projects(projects, publications),
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
        render_members(members, output_dir, member_images),
    )
    _replace_block(
        output_dir / "contact.html",
        "<!-- SHEET:CONTACT:START -->",
        "<!-- SHEET:CONTACT:END -->",
        render_contact(members),
    )
    site_footer = render_site_footer(members)
    for page_name in PRIMARY_PAGE_NAMES:
        _replace_block(
            output_dir / page_name,
            "<!-- SITE:FOOTER:START -->",
            "<!-- SITE:FOOTER:END -->",
            site_footer,
        )

    metadata = {
        "schema_version": 2,
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
    parser.add_argument(
        "--xlsx-file",
        type=Path,
        help=(
            "offline XLSX export used for in-cell images; required with "
            "--csv-dir when Publications or Members need embedded images"
        ),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        tabs = load_sheet_tabs(args.sheet_id, args.csv_dir, args.timeout)
        publication_workbook = None
        blank_member_photo_cells = any(
            row["section"] in MEMBER_CARD_SECTIONS and not row.get("photo")
            for row in tabs["Members"]
        )
        member_image_candidates = (
            blank_member_photo_cells
            and (args.csv_dir is None or args.xlsx_file is not None)
        )
        workbook_needed = (
            _publication_image_schema(tabs["Publications"][0].keys())
            == "direct_cell"
            or member_image_candidates
        )
        if workbook_needed:
            if args.xlsx_file is not None:
                try:
                    if args.xlsx_file.stat().st_size > PUBLICATION_WORKBOOK_LIMIT:
                        raise SheetBuildError(
                            "Sheet workbook file exceeds the size limit"
                        )
                    publication_workbook = args.xlsx_file.read_bytes()
                except OSError as exc:
                    raise SheetBuildError(
                        f"cannot read Sheet workbook: {args.xlsx_file}"
                    ) from exc
            elif args.csv_dir is not None:
                raise SheetBuildError(
                    "in-cell images require --xlsx-file with --csv-dir"
                )
            else:
                publication_workbook = _fetch_workbook(args.sheet_id, args.timeout)
        build_site(
            tabs,
            args.source_dir,
            args.output_dir,
            args.sheet_id,
            "offline_csv" if args.csv_dir else "google_sheet",
            image_endpoint=os.environ.get(RESEARCH_IMAGE_ENDPOINT_ENV),
            image_token=os.environ.get(RESEARCH_IMAGE_TOKEN_ENV),
            publication_workbook=publication_workbook,
            timeout=args.timeout,
        )
    except SheetBuildError as exc:
        print(f"site build failed: {exc}", file=sys.stderr)
        return 1

    counts = ", ".join(f"{name}={len(rows)}" for name, rows in tabs.items())
    print(f"Built {args.output_dir}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
