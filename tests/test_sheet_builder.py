from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape as xml_escape


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import build_sheet_site as builder  # noqa: E402
import validate_site as site_validator  # noqa: E402


PUBLICATION_COLUMNS = (
    "publish",
    "date",
    "title",
    "authors",
    "venue",
    "paper_url",
    "project_url",
    "highlight",
    "research_title",
)
DIRECT_PUBLICATION_COLUMNS = PUBLICATION_COLUMNS + (
    "home_image",
    "home_image_alt",
    "home_image_credit",
)
RESEARCH_COLUMNS = (
    "publish",
    "slug",
    "title",
    "summary",
    "question",
    "home_summary",
    "selected_publication_1",
    "figure_1_url",
    "figure_1_alt",
    "figure_1_credit",
    "selected_publication_2",
    "figure_2_url",
    "figure_2_alt",
    "figure_2_credit",
)
DIRECT_RESEARCH_COLUMNS = (
    "publish",
    "slug",
    "title",
    "summary",
    "question",
    "home_summary",
    "selected_publication_1",
    "figure_1_image",
    "figure_1_alt",
    "figure_1_credit",
    "selected_publication_2",
    "figure_2_image",
    "figure_2_alt",
    "figure_2_credit",
)
PROJECT_COLUMNS = (
    "publish",
    "title",
    "summary",
    "status",
    "period",
    "area",
    "related_publication",
    "url",
)
NEWS_COLUMNS = (
    "publish",
    "date",
    "display_date",
    "tag",
    "title",
    "summary",
    "related_publication_1",
    "related_publication_2",
    "url",
)
MEMBER_COLUMNS = (
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
)
PUBLICATION_HEADER = ",".join(PUBLICATION_COLUMNS) + "\n"


# Actual one-pixel images keep the bridge tests independent of Pillow or other
# image libraries while still exercising MIME and file-signature validation.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////"
    "////////////////////////////////////////////////////2wBDAf//////////"
    "////////////////////////////////////////////////////////////////////"
    "////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/"
    "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAA"
    "AAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgB"
    "AwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAA"
    "AAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/a"
    "AAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oA"
    "CAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEA"
    "AAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="
)


class _FakeUrlResponse:
    def __init__(self, payload: bytes, content_type: str, url: str = "") -> None:
        self._payload = payload
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(payload))
        self.status = 200

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._payload
        return self._payload[:amount]

    def getcode(self) -> int:
        return self.status

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "_FakeUrlResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _csv_text(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


class SheetBuilderTests(unittest.TestCase):
    IMAGE_ENDPOINT = "https://script.google.com/macros/s/test-deployment/exec"
    IMAGE_TOKEN = "t" * 32
    IMAGE_1_URL = "https://lh3.googleusercontent.com/research-image-one"
    IMAGE_2_URL = "https://images.ggpht.com/research-image-two"

    def _allow_small_fixtures(self, *tab_names: str) -> None:
        original = {
            tab_name: builder.MINIMUM_PUBLISHED_ROWS[tab_name]
            for tab_name in tab_names
        }
        for tab_name in tab_names:
            builder.MINIMUM_PUBLISHED_ROWS[tab_name] = 1

        def restore() -> None:
            for tab_name, minimum in original.items():
                builder.MINIMUM_PUBLISHED_ROWS[tab_name] = minimum

        self.addCleanup(restore)

    def _publication_reference_tabs(
        self,
        *,
        research_publication_1: str = "Published Paper",
        research_publication_2: str = "Second Published Paper",
        project_publication: str = "Published Paper",
        news_publication_1: str = "Published Paper",
        news_publication_2: str = "Second Published Paper",
    ) -> dict[str, list[dict[str, str]]]:
        self._allow_small_fixtures(
            "Publications", "Research", "Projects", "News", "Members"
        )
        publication_rows = [
            {
                "publish": "TRUE",
                "date": "2026-08-01",
                "title": "Published Paper",
                "authors": "Example Author",
                "venue": "Example Journal (2026)",
                "paper_url": "https://example.com/published-paper",
            },
            {
                "publish": "TRUE",
                "date": "2026-07-01",
                "title": "Second Published Paper",
                "authors": "Example Author",
                "venue": "Example Conference (2026)",
                "paper_url": "https://example.com/second-published-paper",
            },
            {
                "publish": "FALSE",
                "date": "2026-09-01",
                "title": "Unchecked Paper",
                "authors": "Example Author",
                "venue": "Example Conference (2026)",
                "paper_url": "https://example.com/unchecked-paper",
            },
        ]
        research_rows = [
            {
                "publish": "TRUE",
                "slug": "reference-test",
                "title": "Reference Test",
                "summary": "Summary",
                "question": "Question?",
                "home_summary": "Home summary",
                "selected_publication_1": research_publication_1,
                "figure_1_url": "img/research/slum-detection-figure-5.png",
                "figure_1_alt": "First figure",
                "figure_1_credit": "First figure credit",
                "selected_publication_2": research_publication_2,
                "figure_2_url": "img/research/economic-development-figure-2.png",
                "figure_2_alt": "Second figure",
                "figure_2_credit": "Second figure credit",
            }
        ]
        project_rows = [
            {
                "publish": "TRUE",
                "title": "Publication-backed Project",
                "summary": "Summary",
                "status": "Ongoing",
                "period": "2026–",
                "area": "Reference Test",
                "related_publication": project_publication,
            }
        ]
        news_rows = [
            {
                "publish": "TRUE",
                "date": "2026-08-01",
                "display_date": "Aug 2026",
                "tag": "Publications",
                "title": "Publication news",
                "summary": "Summary",
                "related_publication_1": news_publication_1,
                "related_publication_2": news_publication_2,
            }
        ]
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "name_en": "Example Author",
                "role": "Professor",
                "details": "Profile",
                "photo": "img/prof_jihee.jpg",
                "email": "example-author@example.com",
                "address": "KAIST N5, Daejeon, South Korea",
                "affiliations": "KAIST School of Business and Technology Management",
            }
        ]
        return {
            "Publications": builder._read_csv_text(
                _csv_text(PUBLICATION_COLUMNS, publication_rows), "Publications"
            ),
            "Research": builder._read_csv_text(
                _csv_text(RESEARCH_COLUMNS, research_rows), "Research"
            ),
            "Projects": builder._read_csv_text(
                _csv_text(PROJECT_COLUMNS, project_rows), "Projects"
            ),
            "News": builder._read_csv_text(
                _csv_text(NEWS_COLUMNS, news_rows), "News"
            ),
            "Members": builder._read_csv_text(
                _csv_text(MEMBER_COLUMNS, member_rows), "Members"
            ),
        }

    def _direct_image_tabs(self) -> dict[str, list[dict[str, str]]]:
        tabs = self._publication_reference_tabs()
        direct_rows = [
            {
                "publish": "TRUE",
                "slug": "reference-test",
                "title": "Reference Test",
                "summary": "Summary",
                "question": "Question?",
                "home_summary": "Home summary",
                "selected_publication_1": "Published Paper",
                "figure_1_alt": "First direct figure",
                "figure_1_credit": "First direct figure credit",
                "selected_publication_2": "Second Published Paper",
                "figure_2_alt": "Second direct figure",
                "figure_2_credit": "Second direct figure credit",
            }
        ]
        tabs["Research"] = builder._read_csv_text(
            _csv_text(DIRECT_RESEARCH_COLUMNS, direct_rows), "Research"
        )
        return tabs

    def _direct_image_manifest(self) -> dict[str, object]:
        return {
            "ok": True,
            "schema_version": 1,
            "generated_at": "2026-08-04T00:00:00.000Z",
            "sheet": "Research",
            "images": [
                {
                    "slug": "reference-test",
                    "slot": 1,
                    "field": "figure_1_image",
                    "content_url": self.IMAGE_1_URL,
                    "alt": "First direct figure",
                    "credit": "First direct figure credit",
                    "cell_alt_title": "",
                    "cell_alt_description": "",
                },
                {
                    "slug": "reference-test",
                    "slot": 2,
                    "field": "figure_2_image",
                    "content_url": self.IMAGE_2_URL,
                    "alt": "Second direct figure",
                    "credit": "Second direct figure credit",
                    "cell_alt_title": "",
                    "cell_alt_description": "",
                },
            ],
        }

    def _bridge_urlopen(
        self,
        manifest: object,
        *,
        image_payloads: dict[str, tuple[bytes, str]] | None = None,
    ) -> tuple[object, list[tuple[str, bytes | None, float | None]]]:
        requests: list[tuple[str, bytes | None, float | None]] = []
        payloads = image_payloads or {
            self.IMAGE_1_URL: (TINY_PNG, "image/png"),
            self.IMAGE_2_URL: (TINY_JPEG, "image/jpeg"),
        }

        def urlopen(
            request: object, timeout: float | None = None
        ) -> _FakeUrlResponse:
            url = getattr(request, "full_url", str(request))
            data = getattr(request, "data", None)
            requests.append((url, data, timeout))
            if url == self.IMAGE_ENDPOINT:
                self.assertEqual(
                    json.loads((data or b"").decode("utf-8")),
                    {"token": self.IMAGE_TOKEN},
                )
                return _FakeUrlResponse(
                    json.dumps(manifest).encode("utf-8"), "application/json", url
                )
            try:
                image_bytes, content_type = payloads[url]
            except KeyError as exc:  # make unexpected network access conspicuous
                raise AssertionError(f"unexpected URL requested: {url}") from exc
            return _FakeUrlResponse(image_bytes, content_type, url)

        return urlopen, requests

    def _direct_publication_tabs(self) -> dict[str, list[dict[str, str]]]:
        tabs = self._publication_reference_tabs()
        publication_rows = [
            {
                "publish": "TRUE",
                "date": "2026-08-01",
                "title": "Published Paper",
                "authors": "Example Author",
                "venue": "Example Journal (2026)",
                "paper_url": "https://example.com/published-paper",
                "home_image_alt": "Overview of the published paper",
                "home_image_credit": "Figure 1",
            },
            {
                "publish": "TRUE",
                "date": "2026-07-01",
                "title": "Second Published Paper",
                "authors": "Example Author",
                "venue": "Conference on Language Modeling (COLM 2026)",
                "paper_url": "https://example.com/second-published-paper",
                "home_image_alt": "Results from the second paper",
                "home_image_credit": "Paper authors",
            },
            {
                "publish": "TRUE",
                "date": "2026-06-01",
                "title": "Third Published Paper",
                "authors": "Example Author",
                "venue": "Example Conference (2026)",
                "paper_url": "https://example.com/third-published-paper",
                "home_image_alt": "Method diagram from the third paper",
                "home_image_credit": "",
            },
        ]
        tabs["Publications"] = builder._read_csv_text(
            _csv_text(DIRECT_PUBLICATION_COLUMNS, publication_rows),
            "Publications",
        )
        return tabs

    def _publication_workbook(
        self,
        publication_rows: list[dict[str, str]],
        *,
        omit_image_for: str = "",
        omit_all_images: bool = False,
    ) -> bytes:
        def column_name(index: int) -> str:
            value = index + 1
            result = ""
            while value:
                value, remainder = divmod(value - 1, 26)
                result = chr(ord("A") + remainder) + result
            return result

        def inline_cell(row: int, column: int, value: str) -> str:
            reference = f"{column_name(column)}{row}"
            return (
                f'<c r="{reference}" t="inlineStr"><is><t>'
                f"{xml_escape(value)}</t></is></c>"
            )

        worksheet_rows = []
        worksheet_rows.append(
            '<row r="1">'
            + "".join(
                inline_cell(1, column, header)
                for column, header in enumerate(DIRECT_PUBLICATION_COLUMNS)
            )
            + "</row>"
        )
        for sheet_row, row in enumerate(publication_rows, start=2):
            worksheet_rows.append(
                f'<row r="{sheet_row}">'
                + "".join(
                    inline_cell(sheet_row, column, row.get(header, ""))
                    for column, header in enumerate(DIRECT_PUBLICATION_COLUMNS)
                    if header != "home_image"
                )
                + "</row>"
            )

        image_payloads = (TINY_PNG, TINY_JPEG, TINY_PNG)
        anchors = []
        image_relationships = []
        media: list[tuple[str, bytes]] = []
        relationship_index = 0
        for sheet_row, (row, payload) in enumerate(
            zip(publication_rows, image_payloads), start=2
        ):
            if omit_all_images or row["title"] == omit_image_for:
                continue
            relationship_index += 1
            extension = "jpg" if payload.startswith(b"\xff\xd8\xff") else "png"
            media_name = f"image{relationship_index}.{extension}"
            anchors.append(
                '<xdr:oneCellAnchor>'
                '<xdr:from><xdr:col>9</xdr:col><xdr:colOff>0</xdr:colOff>'
                f'<xdr:row>{sheet_row - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff>'
                '</xdr:from><xdr:ext cx="4000000" cy="3000000"/>'
                '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="0" '
                f'name="{media_name}"/><xdr:cNvPicPr/></xdr:nvPicPr>'
                '<xdr:blipFill><a:blip '
                f'r:embed="rId{relationship_index}"/>'
                '<a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/>'
                '</a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/>'
                '</xdr:oneCellAnchor>'
            )
            image_relationships.append(
                '<Relationship '
                f'Id="rId{relationship_index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/image" '
                f'Target="../media/{media_name}"/>'
            )
            media.append((f"xl/media/{media_name}", payload))

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships"><sheets><sheet name="Publications" '
            'sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        worksheet_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships"><sheetData>'
            + "".join(worksheet_rows)
            + '</sheetData><drawing r:id="rId1"/></worksheet>'
        )
        worksheet_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/drawing" Target="../drawings/drawing1.xml"/>'
            '</Relationships>'
        )
        drawing_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/'
            '2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships">'
            + "".join(anchors)
            + '</xdr:wsDr>'
        )
        drawing_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            + "".join(image_relationships)
            + '</Relationships>'
        )

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr(
                "xl/_rels/workbook.xml.rels", workbook_relationships
            )
            archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
            archive.writestr(
                "xl/worksheets/_rels/sheet1.xml.rels",
                worksheet_relationships,
            )
            archive.writestr("xl/drawings/drawing1.xml", drawing_xml)
            archive.writestr(
                "xl/drawings/_rels/drawing1.xml.rels",
                drawing_relationships,
            )
            for name, payload in media:
                archive.writestr(name, payload)
        return output.getvalue()

    def _member_workbook(
        self,
        member_rows: list[dict[str, str]],
        image_payloads: dict[str, bytes],
        *,
        duplicate_image_for: str = "",
    ) -> bytes:
        def column_name(index: int) -> str:
            value = index + 1
            result = ""
            while value:
                value, remainder = divmod(value - 1, 26)
                result = chr(ord("A") + remainder) + result
            return result

        def inline_cell(row: int, column: int, value: str) -> str:
            reference = f"{column_name(column)}{row}"
            return (
                f'<c r="{reference}" t="inlineStr"><is><t>'
                f"{xml_escape(value)}</t></is></c>"
            )

        worksheet_rows = [
            '<row r="1">'
            + "".join(
                inline_cell(1, column, header)
                for column, header in enumerate(MEMBER_COLUMNS)
            )
            + "</row>"
        ]
        for sheet_row, row in enumerate(member_rows, start=2):
            worksheet_rows.append(
                f'<row r="{sheet_row}">'
                + "".join(
                    inline_cell(sheet_row, column, row.get(header, ""))
                    for column, header in enumerate(MEMBER_COLUMNS)
                    if header != "photo" or row.get(header, "")
                )
                + "</row>"
            )

        anchors: list[str] = []
        image_relationships: list[str] = []
        media: list[tuple[str, bytes]] = []
        relationship_index = 0
        for sheet_row, row in enumerate(member_rows, start=2):
            payload = image_payloads.get(row.get("name_en", ""))
            if payload is None:
                continue
            copies = 2 if row.get("name_en") == duplicate_image_for else 1
            for _ in range(copies):
                relationship_index += 1
                extension = "jpg" if payload.startswith(b"\xff\xd8\xff") else "png"
                media_name = f"member{relationship_index}.{extension}"
                anchors.append(
                    '<xdr:oneCellAnchor><xdr:from>'
                    '<xdr:col>7</xdr:col><xdr:colOff>0</xdr:colOff>'
                    f'<xdr:row>{sheet_row - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff>'
                    '</xdr:from><xdr:ext cx="2000000" cy="2000000"/>'
                    '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="0" '
                    f'name="{media_name}"/><xdr:cNvPicPr/></xdr:nvPicPr>'
                    '<xdr:blipFill><a:blip '
                    f'r:embed="rId{relationship_index}"/>'
                    '<a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                    '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/>'
                    '</a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/>'
                    '</xdr:oneCellAnchor>'
                )
                image_relationships.append(
                    '<Relationship '
                    f'Id="rId{relationship_index}" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/'
                    '2006/relationships/image" '
                    f'Target="../media/{media_name}"/>'
                )
                media.append((f"xl/media/{media_name}", payload))

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships"><sheets><sheet name="Members" '
            'sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        worksheet_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships"><sheetData>'
            + "".join(worksheet_rows)
            + '</sheetData><drawing r:id="rId1"/></worksheet>'
        )
        worksheet_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/drawing" Target="../drawings/drawing1.xml"/>'
            '</Relationships>'
        )
        drawing_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/'
            '2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships">'
            + "".join(anchors)
            + '</xdr:wsDr>'
        )
        drawing_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            + "".join(image_relationships)
            + '</Relationships>'
        )

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr(
                "xl/_rels/workbook.xml.rels", workbook_relationships
            )
            archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
            archive.writestr(
                "xl/worksheets/_rels/sheet1.xml.rels",
                worksheet_relationships,
            )
            archive.writestr("xl/drawings/drawing1.xml", drawing_xml)
            archive.writestr(
                "xl/drawings/_rels/drawing1.xml.rels",
                drawing_relationships,
            )
            for name, payload in media:
                archive.writestr(name, payload)
        return output.getvalue()

    def test_publications_are_sorted_by_exact_date_descending(self) -> None:
        text = PUBLICATION_HEADER + "\n".join(
            [
                "TRUE,2026-04-30,Older,A Author,arXiv,https://example.com/older,, ,",
                "TRUE,2026-07-12,Newer,B Author,COLM (2026),https://example.com/newer,, ,",
                "FALSE,2027-01-01,Hidden,C Author,arXiv,https://example.com/hidden,, ,",
            ]
        )
        original_minimum = builder.MINIMUM_PUBLISHED_ROWS["Publications"]
        builder.MINIMUM_PUBLISHED_ROWS["Publications"] = 1
        self.addCleanup(
            builder.MINIMUM_PUBLISHED_ROWS.__setitem__,
            "Publications",
            original_minimum,
        )
        rows = builder._read_csv_text(text, "Publications")
        self.assertEqual([row["title"] for row in rows], ["Older", "Newer"])
        self.assertEqual(
            [row["title"] for row in builder._sort_publications(rows)],
            ["Newer", "Older"],
        )

    def test_home_latest_excludes_newer_arxiv_preprints(self) -> None:
        rows = [
            {
                "date": "2026-09-01",
                "title": "Newest Preprint",
                "authors": "A Author",
                "venue": "arXiv",
                "paper_url": "https://arxiv.org/abs/2609.00001",
            }
        ] + [
            {
                "date": f"2026-0{8 - index}-01",
                "title": f"Published Paper {index + 1}",
                "authors": "A Author",
                "venue": "Example Conference (2026)",
                "paper_url": f"https://example.com/published-{index + 1}",
            }
            for index in range(3)
        ]
        rendered = builder.render_home_latest(rows)
        self.assertNotIn("Newest Preprint", rendered)
        self.assertLess(
            rendered.index("Published Paper 1"),
            rendered.index("Published Paper 2"),
        )
        self.assertLess(
            rendered.index("Published Paper 2"),
            rendered.index("Published Paper 3"),
        )

    def test_publication_image_formula_urls_are_narrowly_allowlisted(self) -> None:
        formula = 'IMAGE("https://econai.kaist.ac.kr/img/example.png")'
        self.assertEqual(
            builder._publication_image_formula_url(formula, "Example image"),
            "https://econai.kaist.ac.kr/img/example.png",
        )
        with self.assertRaisesRegex(builder.SheetBuildError, "not allowed"):
            builder._publication_image_formula_url(
                'IMAGE("https://127.0.0.1/private.png")',
                "Example image",
            )

    def test_publications_page_uses_sheet_order_within_newest_first_years(self) -> None:
        rows = [
            {
                "date": "2025-12-01",
                "title": "First 2025 Sheet Row",
                "authors": "A Author",
                "venue": "Journal of Example Studies (2025)",
                "paper_url": "https://example.com/first-2025",
            },
            {
                "date": "2026-01-01",
                "title": "First 2026 Sheet Row",
                "authors": "B Author",
                "venue": "Example Conference (2026)",
                "paper_url": "https://example.com/first-2026",
            },
            {
                "date": "2026-08-01",
                "title": "Second 2026 Sheet Row",
                "authors": "C Author",
                "venue": "Conference on Language Modeling (COLM 2026)",
                "paper_url": "https://example.com/second-2026",
            },
            {
                "date": "2025-02-01",
                "title": "Second 2025 Sheet Row",
                "authors": "D Author",
                "venue": "AAAI Conference on Artificial Intelligence (AAAI 2025)",
                "paper_url": "https://example.com/second-2025",
            },
        ]

        publication_page = builder.render_publications_page(rows, set())
        self.assertLess(
            publication_page.index('id="publications-2026"'),
            publication_page.index('id="publications-2025"'),
        )
        self.assertLess(
            publication_page.index("First 2026 Sheet Row"),
            publication_page.index("Second 2026 Sheet Row"),
        )
        self.assertLess(
            publication_page.index("First 2025 Sheet Row"),
            publication_page.index("Second 2025 Sheet Row"),
        )

        home_latest = builder.render_home_latest(rows)
        self.assertLess(
            home_latest.index("Second 2026 Sheet Row"),
            home_latest.index("First 2026 Sheet Row"),
        )
        self.assertLess(
            home_latest.index("First 2026 Sheet Row"),
            home_latest.index("First 2025 Sheet Row"),
        )

    def test_home_latest_renders_accessible_three_slide_carousel(self) -> None:
        rows = [
            {
                "date": f"2026-0{8 - index}-01",
                "title": f"Paper {index + 1}",
                "authors": "A Author, B Author",
                "venue": "Example Conference (2026)",
                "paper_url": f"https://example.com/paper-{index + 1}",
            }
            for index in range(3)
        ]
        rendered = builder.render_home_latest(
            rows,
            {
                f"Paper {index + 1}": {
                    "url": "img/sheet-publications/paper.png",
                    "alt": "Paper overview",
                    "credit": "Figure 1",
                }
                for index in range(3)
            },
        )
        self.assertEqual(
            site_validator._classes(rendered, "publication-figure-slide"), 3
        )
        self.assertEqual(
            site_validator._classes(rendered, "publication-carousel-button"), 2
        )
        self.assertNotIn("publication-figure-fallback", rendered)
        self.assertIn('aria-roledescription="carousel"', rendered)
        self.assertIn('aria-live="polite"', rendered)
        self.assertIn('aria-label="Show previous publication figure"', rendered)
        self.assertIn('aria-label="Show next publication figure"', rendered)
        self.assertIn('aria-label="Open paper: Paper 1"', rendered)
        self.assertIn('alt="Paper overview"', rendered)
        self.assertEqual(
            site_validator._classes(rendered, "publication-figure-caption"), 3
        )
        self.assertEqual(
            site_validator._classes(rendered, "publication-carousel-dot"), 3
        )
        self.assertIn(">Paper 1</a>", rendered)
        self.assertNotIn("publication-figure-title", rendered)
        self.assertNotIn("publication-figure-venue", rendered)
        self.assertNotIn("publication-figure-credit", rendered)
        self.assertNotIn("publication-carousel-controls", rendered)
        self.assertEqual(
            site_validator._classes(
                rendered, "publication-carousel-button--previous"
            ),
            1,
        )
        self.assertEqual(
            site_validator._classes(rendered, "publication-carousel-button--next"),
            1,
        )
        self.assertEqual(rendered.count('loading="eager"'), 3)
        self.assertEqual(rendered.count('fetchpriority="high"'), 1)
        self.assertEqual(rendered.count('fetchpriority="low"'), 2)
        self.assertEqual(rendered.count('decoding="sync"'), 3)
        self.assertEqual(rendered.count(" hidden>"), 4)
        index_source = (REPOSITORY_ROOT / "main_site/index.html").read_text(
            encoding="utf-8"
        )
        stylesheet = (REPOSITORY_ROOT / "main_site/site.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('event.key === "ArrowLeft"', index_source)
        self.assertIn('event.key === "ArrowRight"', index_source)
        self.assertIn('dot.setAttribute("aria-current", "true")', index_source)
        self.assertIn('caption.hidden = captionIndex !== current', index_source)
        self.assertIn("(index + slides.length) % slides.length", index_source)
        self.assertNotIn("setInterval", index_source)
        self.assertIn("aspect-ratio: 5 / 3", stylesheet)
        self.assertRegex(
            stylesheet,
            r"\.publication-figure-image\s*\{[^}]*object-fit:\s*contain",
        )
        self.assertRegex(
            stylesheet,
            r"\.publication-figure-image\s*\{[^}]*mix-blend-mode:\s*multiply",
        )
        self.assertRegex(
            stylesheet,
            r"\.publication-carousel-button\s*\{[^}]*position:\s*absolute"
            r"[^}]*top:\s*50%",
        )
        self.assertRegex(
            stylesheet,
            r"\.publication-carousel-button\s*\{[^}]*background:\s*rgba\(255, 255, 255",
        )
        self.assertIn('class="publication-carousel-icon"', rendered)
        self.assertIn('.publication-carousel-dot[aria-current="true"]', stylesheet)
        self.assertRegex(
            stylesheet,
            r"\.publication-figure-caption\s*\{[^}]*text-align:\s*center",
        )
        self.assertNotIn("weather-card", index_source)
        self.assertNotIn("open-meteo.com", index_source)
        legacy_stylesheet = (REPOSITORY_ROOT / "main_site/style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("scrollbar-gutter: stable", stylesheet)
        self.assertIn("scrollbar-gutter: stable", legacy_stylesheet)
        self.assertIn("max-width: 1120px", legacy_stylesheet)

        for page_name in (
            "index.html",
            "members.html",
            "research.html",
            "publications.html",
            "projects.html",
            "contact.html",
        ):
            page_source = (REPOSITORY_ROOT / "main_site" / page_name).read_text(
                encoding="utf-8"
            )
            self.assertIn('class="site-header"', page_source)
            self.assertIn('class="desktop-nav"', page_source)
            self.assertIn('class="mobile-nav"', page_source)
            self.assertIn("site.css?v=20260805-alumni-links", page_source)
            self.assertNotIn("fixed-top", page_source)
            self.assertNotIn("bootstrap", page_source.lower())

        self.assertNotIn("Latest Publications", index_source)
        self.assertIn('<h2 id="recent-work-title">Publications</h2>', index_source)
        self.assertNotIn("Researchers and students working", (REPOSITORY_ROOT / "main_site/members.html").read_text(encoding="utf-8"))
        self.assertNotIn("We combine artificial intelligence", (REPOSITORY_ROOT / "main_site/research.html").read_text(encoding="utf-8"))

    def test_publication_home_image_columns_must_be_complete(self) -> None:
        self._allow_small_fixtures("Publications")
        columns = PUBLICATION_COLUMNS + ("home_image", "home_image_alt")
        with self.assertRaisesRegex(
            builder.SheetBuildError, "home_image_credit"
        ):
            builder._read_csv_text(
                _csv_text(
                    columns,
                    [
                        {
                            "publish": "TRUE",
                            "date": "2026-08-01",
                            "title": "Paper",
                            "authors": "A Author",
                            "venue": "arXiv",
                            "paper_url": "https://example.com/paper",
                        }
                    ],
                ),
                "Publications",
            )

    def test_blank_date_uses_one_unambiguous_venue_year(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,,Legacy,A Author,Workshop (2017),https://example.com/paper,,,\n"
        )
        original_minimum = builder.MINIMUM_PUBLISHED_ROWS["Publications"]
        builder.MINIMUM_PUBLISHED_ROWS["Publications"] = 1
        self.addCleanup(
            builder.MINIMUM_PUBLISHED_ROWS.__setitem__,
            "Publications",
            original_minimum,
        )
        rows = builder._read_csv_text(text, "Publications")
        self.assertEqual(builder._publication_sort_tuple(rows[0]), (2017, 0, 0))

    def test_non_https_publication_link_is_rejected(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,2026-01-01,Unsafe,A Author,arXiv,javascript:alert(1),,,\n"
        )
        original_minimum = builder.MINIMUM_PUBLISHED_ROWS["Publications"]
        builder.MINIMUM_PUBLISHED_ROWS["Publications"] = 1
        self.addCleanup(
            builder.MINIMUM_PUBLISHED_ROWS.__setitem__,
            "Publications",
            original_minimum,
        )
        with self.assertRaises(builder.SheetBuildError):
            builder._read_csv_text(text, "Publications")

    def test_publication_mass_deletion_guardrail(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,2026-01-01,Only one,A Author,arXiv,https://example.com/paper,,,\n"
        )
        with self.assertRaisesRegex(builder.SheetBuildError, "at least 20"):
            builder._read_csv_text(text, "Publications")

    def test_publication_csv_cannot_be_mistaken_for_news_or_members(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,2026-01-01,Paper,A Author,arXiv,https://example.com/paper,,,\n"
        )
        for tab_name in ("News", "Members"):
            with self.subTest(tab_name=tab_name):
                with self.assertRaisesRegex(builder.SheetBuildError, "missing columns"):
                    builder._read_csv_text(text, tab_name)

    def test_news_and_members_contract_rows_are_parsed(self) -> None:
        self._allow_small_fixtures("News", "Members")
        news_text = _csv_text(
            NEWS_COLUMNS,
            [
                {
                    "publish": "TRUE",
                    "date": "2026-07-12",
                    "display_date": "Jul 2026",
                    "tag": "Publications",
                    "title": "Two papers accepted",
                    "summary": "The lab will present two papers.",
                    "related_publication_1": "Paper A",
                    "related_publication_2": "Paper B",
                },
                {
                    "publish": "FALSE",
                    "date": "2027-01-01",
                    "display_date": "Jan 2027",
                    "tag": "People",
                    "title": "Hidden news",
                    "summary": "This row must not be rendered.",
                },
            ],
        )
        member_text = _csv_text(
            MEMBER_COLUMNS,
            [
                {
                    "publish": "TRUE",
                    "section": "Master's Students",
                    "name_en": "Example Student",
                    "name_ko": "예시",
                    "role": "Master's Student",
                    "details": "Economic AI",
                    "photo": "img/basic_profile.png",
                    "email": "student@example.com",
                }
            ],
        )

        news = builder._read_csv_text(news_text, "News")
        members = builder._read_csv_text(member_text, "Members")

        self.assertEqual([row["title"] for row in news], ["Two papers accepted"])
        self.assertEqual([row["name_en"] for row in members], ["Example Student"])

    def test_news_pipe_delimited_publication_column_is_rejected(self) -> None:
        old_columns = (
            "publish",
            "date",
            "display_date",
            "tag",
            "title",
            "summary",
            "related_publications",
            "url",
        )
        text = _csv_text(
            old_columns,
            [
                {
                    "publish": "TRUE",
                    "date": "2026-08-01",
                    "display_date": "Aug 2026",
                    "tag": "Publications",
                    "title": "Legacy references",
                    "related_publications": "Paper A | Paper B",
                }
            ],
        )
        with self.assertRaisesRegex(
            builder.SheetBuildError,
            r"missing columns: .*related_publication_1.*related_publication_2",
        ):
            builder._read_csv_text(text, "News")

    def test_alumni_joint_supervision_footnote_is_sheet_driven(self) -> None:
        self._allow_small_fixtures("Members")
        rows = [
            {
                "publish": "TRUE",
                "section": "Alumni",
                "name_en": "Minhyuk Song",
                "details": "AI Researcher, LIG Defense & Aerospace",
                "joint_supervisor": "Prof. Meeyoung Cha",
                "joint_supervisor_url": "https://www.mpi-sp.org/cha",
            },
            {
                "publish": "TRUE",
                "section": "Alumni",
                "name_en": "Sumin Lee",
                "details": "Ph.D Student, Max Planck Institute for Security and Privacy",
                "joint_supervisor": "Prof. Meeyoung Cha",
                "joint_supervisor_url": "https://www.mpi-sp.org/cha",
            },
        ]
        members = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, rows), "Members"
        )
        rendered = builder.render_members(members, REPOSITORY_ROOT / "main_site")

        self.assertIn(
            "Minhyuk Song<sup class=\"alumni-note-marker\"", rendered
        )
        self.assertIn("AI Researcher, LIG Defense &amp; Aerospace", rendered)
        self.assertIn(
            "Sumin Lee<sup class=\"alumni-note-marker\"", rendered
        )
        self.assertEqual(rendered.count("Jointly supervised with"), 1)
        self.assertEqual(rendered.count("https://www.mpi-sp.org/cha"), 1)
        lab_authors = builder._lab_authors(
            members
            + [
                {
                    "section": "Pre-EconAI Alumni",
                    "name_en": "Legacy Author",
                }
            ]
        )
        self.assertEqual(
            lab_authors,
            {"Minhyuk Song", "Sumin Lee", "Legacy Author"},
        )
        publication_html = builder.render_publications_page(
            [
                {
                    "date": "2026-01-01",
                    "title": "Legacy Collaboration",
                    "authors": "External Author, Legacy Author",
                    "venue": "arXiv",
                    "paper_url": "https://example.com/legacy-collaboration",
                }
            ],
            lab_authors,
        )
        self.assertIn(
            '<strong class="publication-lab-author">Legacy Author</strong>',
            publication_html,
        )

    def test_alumni_profile_links_use_the_shared_member_sheet_columns(self) -> None:
        self._allow_small_fixtures("Members")
        rows = [
            {
                "publish": "TRUE",
                "section": "Alumni",
                "name_en": "Linked Alumni",
                "role": "M.S. 2026",
                "details": "Data Scientist, Example Company",
                "email": "alumni@example.com",
                "website": "https://example.com/alumni",
                "scholar": "https://scholar.google.com/citations?user=example",
                "linkedin": "https://www.linkedin.com/in/example-alumni",
            },
            {
                "publish": "TRUE",
                "section": "Pre-EconAI Alumni",
                "name_en": "Legacy Alumni",
                "details": "Research Fellow, Example Institute",
                "linkedin": "https://www.linkedin.com/in/legacy-alumni",
            },
            {
                "publish": "TRUE",
                "section": "Alumni",
                "name_en": "Unlinked Alumni",
                "details": "Researcher, Example Lab",
            },
        ]
        members = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, rows), "Members"
        )

        rendered = builder.render_members(members, REPOSITORY_ROOT / "main_site")

        self.assertEqual(site_validator._classes(rendered, "alumni-item"), 3)
        self.assertEqual(site_validator._classes(rendered, "member-links"), 2)
        self.assertEqual(site_validator._classes(rendered, "member-link-btn"), 5)
        self.assertIn('href="mailto:alumni@example.com"', rendered)
        self.assertIn(
            'aria-label="LinkedIn Linked Alumni"', rendered
        )
        self.assertIn(
            'aria-label="Google Scholar Linked Alumni"', rendered
        )
        self.assertIn(
            'aria-label="LinkedIn Legacy Alumni"', rendered
        )
        self.assertNotIn('aria-label="Email Unlinked Alumni"', rendered)
        self.assertIn(
            '<div class="alumni-summary"><strong>Linked Alumni</strong> — '
            "M.S. 2026 · Data Scientist, Example Company</div>",
            rendered,
        )

    def test_internship_terms_are_visible_and_staff_uses_canonical_position(self) -> None:
        self._allow_small_fixtures("Members")
        rows = [
            {
                "publish": "TRUE",
                "section": "Alumni",
                "name_en": "Example Alumni",
                "details": "Researcher",
            },
            {
                "publish": "TRUE",
                "section": "Staff",
                "name_en": "Sohyun Han",
                "name_ko": "한소현",
                "role": "Lab Administration & Operations",
            },
            {
                "publish": "TRUE",
                "section": "Lab Internship",
                "group": "Summer 2026",
                "name_en": "Junsik Min",
            },
            {
                "publish": "TRUE",
                "section": "Lab Internship",
                "group": "Spring 2026",
                "name_en": "Junsik Min",
            },
            {
                "publish": "TRUE",
                "section": "Lab Internship",
                "group": "Summer 2026",
                "name_en": "Jaewoo Choi",
            },
            {
                "publish": "TRUE",
                "section": "Lab Internship",
                "group": "Winter 2025",
                "name_en": "Woojin Park",
            },
            {
                "publish": "TRUE",
                "section": "Lab Internship",
                "group": "Fall 2025",
                "name_en": "Hyunwoo Oh",
            },
        ]
        members = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, rows), "Members"
        )

        rendered = builder.render_members(members, REPOSITORY_ROOT / "main_site")

        self.assertNotIn("accordion", rendered)
        self.assertNotIn("collapse", rendered)
        self.assertNotIn("<button", rendered)
        self.assertLess(rendered.index("Summer 2026"), rendered.index("Spring 2026"))
        self.assertLess(rendered.index("Spring 2026"), rendered.index("Winter 2025"))
        self.assertLess(rendered.index("Winter 2025"), rendered.index("Fall 2025"))
        summer_start = rendered.index("Summer 2026")
        summer = rendered[
            summer_start : rendered.index("</section>", summer_start)
        ]
        self.assertLess(summer.index("Junsik Min"), summer.index("Jaewoo Choi"))
        self.assertLess(
            rendered.index("Lab Internship"),
            rendered.index(">Staff</h2>"),
        )
        self.assertLess(rendered.index(">Staff</h2>"), rendered.index(">Alumni</h2>"))
        self.assertIn("Sohyun Han | 한소현", rendered)
        self.assertIn(
            '<p class="member-role">Lab Administration &amp; Operations</p>',
            rendered,
        )
        self.assertIn('src="img/basic_profile.png" alt="Sohyun Han"', rendered)

    def test_member_cell_images_are_materialised_with_incremental_fallbacks(
        self,
    ) -> None:
        tabs = self._publication_reference_tabs()
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "name_en": "Example Author",
                "role": "Professor",
                "photo": "",
                "email": "example-author@example.com",
                "address": "KAIST N5, Daejeon, South Korea",
                "affiliations": "KAIST School of Business and Technology Management",
            },
            {
                "publish": "TRUE",
                "section": "Master's Students",
                "name_en": "Legacy Student",
                "role": "Master's Student",
                "photo": "img/basic_profile.png",
            },
            {
                "publish": "TRUE",
                "section": "Staff",
                "name_en": "Uploaded Staff",
                "role": "Lab Administration & Operations",
                "photo": "",
            },
            {
                "publish": "TRUE",
                "section": "Staff",
                "name_en": "Fallback Staff",
                "role": "Lab Operations",
                "photo": "",
            },
        ]
        tabs["Members"] = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, member_rows), "Members"
        )
        workbook = self._member_workbook(
            member_rows,
            {
                "Example Author": TINY_PNG,
                "Uploaded Staff": TINY_JPEG,
            },
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with mock.patch.object(
                builder.urllib.request,
                "urlopen",
                side_effect=AssertionError(
                    "embedded member photos must not request image URLs"
                ),
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                    publication_workbook=workbook,
                )

            assets = sorted((output / "img/sheet-members").iterdir())
            self.assertEqual(len(assets), 2)
            self.assertEqual(
                sorted(asset.read_bytes() for asset in assets),
                sorted((TINY_PNG, TINY_JPEG)),
            )
            member_text = (output / "members.html").read_text(encoding="utf-8")
            for asset in assets:
                self.assertIn(asset.relative_to(output).as_posix(), member_text)
            self.assertIn('src="img/basic_profile.png" alt="Legacy Student"', member_text)
            self.assertIn('src="img/basic_profile.png" alt="Fallback Staff"', member_text)
            self.assertNotIn("googleusercontent.com", member_text)
            self.assertNotIn("ggpht.com", member_text)
            self.assertEqual(site_validator.validate(output), [])

    def test_required_member_cell_image_fails_closed_when_missing(self) -> None:
        tabs = self._publication_reference_tabs()
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "name_en": "Example Author",
                "role": "Professor",
                "photo": "",
                "affiliations": "KAIST School of Business and Technology Management",
            }
        ]
        tabs["Members"] = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, member_rows), "Members"
        )
        workbook = self._member_workbook(member_rows, {})
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                builder.SheetBuildError,
                "Example Author.*add a photo image",
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    Path(temporary_directory) / "output",
                    "test-sheet",
                    "offline_csv",
                    publication_workbook=workbook,
                )

    def test_required_member_cell_image_requires_workbook_export(self) -> None:
        tabs = self._publication_reference_tabs()
        tabs["Members"][0]["photo"] = ""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                builder.SheetBuildError,
                "Members in-cell photos require an XLSX workbook export",
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    Path(temporary_directory) / "output",
                    "test-sheet",
                    "offline_csv",
                )

    def test_live_cli_fetches_workbook_for_member_cell_images(self) -> None:
        tabs = self._publication_reference_tabs()
        tabs["Members"][0]["photo"] = ""
        args = mock.Mock(
            sheet_id="test-sheet",
            source_dir=REPOSITORY_ROOT / "main_site",
            output_dir=REPOSITORY_ROOT / "_unused-test-output",
            csv_dir=None,
            xlsx_file=None,
            timeout=12.5,
        )
        with (
            mock.patch.object(builder, "parse_args", return_value=args),
            mock.patch.object(builder, "load_sheet_tabs", return_value=tabs),
            mock.patch.object(
                builder, "_fetch_workbook", return_value=b"sheet-workbook"
            ) as fetch_workbook,
            mock.patch.object(builder, "build_site") as build_site,
        ):
            self.assertEqual(builder.main(), 0)

        fetch_workbook.assert_called_once_with("test-sheet", 12.5)
        self.assertEqual(
            build_site.call_args.kwargs["publication_workbook"],
            b"sheet-workbook",
        )

    def test_offline_cli_keeps_blank_staff_photo_fallback_without_workbook(
        self,
    ) -> None:
        tabs = self._publication_reference_tabs()
        tabs["Members"].append(
            {
                "publish": "TRUE",
                "section": "Staff",
                "group": "",
                "name_en": "Fallback Staff",
                "name_ko": "",
                "role": "Lab Operations",
                "details": "",
                "photo": "",
                "email": "",
                "website": "",
                "scholar": "",
                "linkedin": "",
                "phone": "",
                "address": "",
                "affiliations": "",
                "joint_supervisor": "",
                "joint_supervisor_url": "",
            }
        )
        args = mock.Mock(
            sheet_id="test-sheet",
            source_dir=REPOSITORY_ROOT / "main_site",
            output_dir=REPOSITORY_ROOT / "_unused-test-output",
            csv_dir=REPOSITORY_ROOT / "tests/fixtures",
            xlsx_file=None,
            timeout=12.5,
        )
        with (
            mock.patch.object(builder, "parse_args", return_value=args),
            mock.patch.object(builder, "load_sheet_tabs", return_value=tabs),
            mock.patch.object(builder, "_fetch_workbook") as fetch_workbook,
            mock.patch.object(builder, "build_site") as build_site,
        ):
            self.assertEqual(builder.main(), 0)

        fetch_workbook.assert_not_called()
        self.assertIsNone(build_site.call_args.kwargs["publication_workbook"])

    def test_duplicate_member_cell_image_is_rejected(self) -> None:
        tabs = self._publication_reference_tabs()
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "name_en": "Example Author",
                "role": "Professor",
                "photo": "",
                "affiliations": "KAIST School of Business and Technology Management",
            }
        ]
        tabs["Members"] = builder._read_csv_text(
            _csv_text(MEMBER_COLUMNS, member_rows), "Members"
        )
        workbook = self._member_workbook(
            member_rows,
            {"Example Author": TINY_PNG},
            duplicate_image_for="Example Author",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                builder.SheetBuildError,
                "Members photo for 'Example Author' is duplicated",
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    Path(temporary_directory) / "output",
                    "test-sheet",
                    "offline_csv",
                    publication_workbook=workbook,
                )

    def test_joint_supervisor_fields_must_be_paired(self) -> None:
        self._allow_small_fixtures("Members")
        text = _csv_text(
            MEMBER_COLUMNS,
            [
                {
                    "publish": "TRUE",
                    "section": "Alumni",
                    "name_en": "Example Alumni",
                    "details": "Researcher",
                    "joint_supervisor": "Prof. Example",
                }
            ],
        )
        with self.assertRaisesRegex(
            builder.SheetBuildError,
            "joint_supervisor and joint_supervisor_url must be filled together",
        ):
            builder._read_csv_text(text, "Members")

    def test_five_tab_build_and_validation_are_consistent(self) -> None:
        self._allow_small_fixtures(
            "Publications", "Research", "Projects", "News", "Members"
        )
        publication_rows = [
            {
                "publish": "TRUE",
                "date": "2026-07-12",
                "title": "Newer Paper",
                "authors": "A Author, B Author",
                "venue": "arXiv",
                "paper_url": "https://example.com/newer-paper",
                "research_title": "Test Research Area",
            },
            {
                "publish": "TRUE",
                "date": "2026-04-30",
                "title": "Older Paper",
                "authors": "C Author",
                "venue": "arXiv",
                "paper_url": "https://example.com/older-paper",
                "research_title": "Test Research Area",
            },
        ]
        research_rows = [
            {
                "publish": "TRUE",
                "slug": "test-research-area",
                "title": "Test Research Area",
                "summary": "A detailed research summary.",
                "question": "What can this research measure?",
                "home_summary": "A concise home-page summary.",
                "selected_publication_1": "Newer Paper",
                "figure_1_url": "img/research/slum-detection-figure-5.png",
                "figure_1_alt": "Example result map",
                "figure_1_credit": "Example figure credit",
                "selected_publication_2": "Older Paper",
                "figure_2_url": "img/research/economic-development-figure-2.png",
                "figure_2_alt": "Example comparison chart",
                "figure_2_credit": "Second example figure credit",
            }
        ]
        project_rows = [
            {
                "publish": "TRUE",
                "title": "Test Project",
                "summary": "A project summary.",
                "status": "Ongoing",
                "period": "2026–",
                "area": "Test Research Area",
                "related_publication": "Newer Paper",
            },
            {
                "publish": "TRUE",
                "title": "Standalone Project",
                "summary": "A standalone project summary.",
                "status": "Completed",
                "period": "2025",
                "area": "Test Research Area",
                "url": "https://example.com/standalone-project",
            },
            {
                "publish": "TRUE",
                "title": "Project Page and Paper",
                "summary": "A project with its own page and a related paper.",
                "status": "Ongoing",
                "period": "2026–",
                "area": "Test Research Area",
                "related_publication": "Older Paper",
                "url": "https://example.com/project-page",
            }
        ]
        news_rows = [
            {
                "publish": "TRUE",
                "date": "2026-03-01",
                "display_date": "Mar 2026",
                "tag": "People",
                "title": "Older lab news",
                "summary": "An older update.",
                "url": "https://example.com/older-news",
            },
            {
                "publish": "TRUE",
                "date": "2026-07-01",
                "display_date": "Jul 2026",
                "tag": "Award",
                "title": "Newer lab news",
                "summary": "A newer update.",
                "related_publication_1": "Newer Paper",
                "related_publication_2": "Older Paper",
            },
        ]
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "name_en": "A Author",
                "role": "Professor",
                "details": "Faculty profile",
                "photo": "img/prof_jihee.jpg",
                "email": "professor@example.com",
                "address": "KAIST Bldg. N5 #2108, Daejeon, South Korea",
                "affiliations": "KAIST School of Business and Technology Management|School of Computing",
            },
            {
                "publish": "TRUE",
                "section": "Master's Students",
                "name_en": "Second Student",
                "role": "Master's Student",
                "details": "Second in display order",
                "photo": "img/basic_profile.png",
            },
            {
                "publish": "TRUE",
                "section": "Master's Students",
                "name_en": "First Student",
                "role": "Master's Student",
                "details": "First in display order",
                "photo": "img/basic_profile.png",
            },
        ]
        tabs = {
            "Publications": builder._read_csv_text(
                _csv_text(PUBLICATION_COLUMNS, publication_rows), "Publications"
            ),
            "Research": builder._read_csv_text(
                _csv_text(RESEARCH_COLUMNS, research_rows), "Research"
            ),
            "Projects": builder._read_csv_text(
                _csv_text(PROJECT_COLUMNS, project_rows), "Projects"
            ),
            "News": builder._read_csv_text(_csv_text(NEWS_COLUMNS, news_rows), "News"),
            "Members": builder._read_csv_text(
                _csv_text(MEMBER_COLUMNS, member_rows), "Members"
            ),
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            output = root / "output"
            shutil.copytree(REPOSITORY_ROOT / "main_site", source)

            builder.build_site(tabs, source, output, "test-sheet", "offline_csv")

            metadata = json.loads(
                (output / "data/sheet-build.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                metadata["published_rows"],
                {
                    "Publications": 2,
                    "Research": 1,
                    "Projects": 3,
                    "News": 2,
                    "Members": 3,
                },
            )
            index_text = (output / "index.html").read_text(encoding="utf-8")
            member_text = (output / "members.html").read_text(encoding="utf-8")
            contact_text = (output / "contact.html").read_text(encoding="utf-8")
            publication_text = (output / "publications.html").read_text(
                encoding="utf-8"
            )
            project_text = (output / "projects.html").read_text(encoding="utf-8")
            self.assertEqual(site_validator._classes(index_text, "sheet-news-item"), 2)
            self.assertEqual(site_validator._classes(member_text, "sheet-member-item"), 3)
            self.assertIn("Professor A Author", contact_text)
            self.assertIn('mailto:professor@example.com', contact_text)
            self.assertLess(
                index_text.index("Newer lab news"), index_text.index("Older lab news")
            )
            self.assertLess(
                member_text.index("Second Student"), member_text.index("First Student")
            )
            self.assertIn('href="https://example.com/newer-paper"', index_text)
            self.assertIn('href="https://example.com/older-paper"', index_text)
            self.assertIn('href="https://example.com/newer-paper"', project_text)
            self.assertIn('href="https://example.com/standalone-project"', project_text)
            self.assertIn(
                '<h3><a href="https://example.com/project-page">Project Page and Paper</a></h3>',
                project_text,
            )
            self.assertIn(
                '<a class="project-publication-link" href="https://example.com/older-paper">Related publication →</a>',
                project_text,
            )
            self.assertIn(
                '<strong class="publication-lab-author">A Author</strong>',
                publication_text,
            )
            self.assertIn(
                '<li class="footer-affiliation">KAIST School of Business and Technology Management</li>',
                index_text,
            )
            self.assertIn(
                '<li class="footer-affiliation">School of Computing</li>',
                index_text,
            )
            for page_name in (
                "index.html",
                "members.html",
                "research.html",
                "publications.html",
                "projects.html",
                "contact.html",
            ):
                page_text = (output / page_name).read_text(encoding="utf-8")
                self.assertIn("Daejeon, ROK · 2026 EconAI Lab", page_text)
            self.assertEqual(site_validator.validate(output), [])

            metadata["published_rows"]["News"] = 3
            metadata["published_rows"]["Members"] = 4
            (output / "data/sheet-build.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            errors = site_validator.validate(output)
            self.assertIn("index.html news row count does not match Sheet metadata", errors)
            self.assertIn("members.html row count does not match Sheet metadata", errors)

    def test_direct_in_cell_images_are_materialised_without_url_leaks(self) -> None:
        tabs = self._direct_image_tabs()
        manifest = self._direct_image_manifest()
        fake_urlopen, requests = self._bridge_urlopen(manifest)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with mock.patch.object(builder.urllib.request, "urlopen", fake_urlopen):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                    image_endpoint=self.IMAGE_ENDPOINT,
                    image_token=self.IMAGE_TOKEN,
                    timeout=7.5,
                )

            first_hash = hashlib.sha256(TINY_PNG).hexdigest()[:16]
            second_hash = hashlib.sha256(TINY_JPEG).hexdigest()[:16]
            first_candidates = list(
                (output / "img/sheet-research").glob(
                    f"reference-test-1-{first_hash}.*"
                )
            )
            second_candidates = list(
                (output / "img/sheet-research").glob(
                    f"reference-test-2-{second_hash}.*"
                )
            )
            self.assertEqual(len(first_candidates), 1)
            self.assertEqual(len(second_candidates), 1)
            self.assertEqual(first_candidates[0].suffix, ".png")
            self.assertIn(second_candidates[0].suffix, {".jpg", ".jpeg"})
            self.assertEqual(first_candidates[0].read_bytes(), TINY_PNG)
            self.assertEqual(second_candidates[0].read_bytes(), TINY_JPEG)

            research_html = (output / "research.html").read_text(encoding="utf-8")
            rendered_sources = re.findall(
                r'<img src="(img/sheet-research/[^"]+)"', research_html
            )
            self.assertEqual(
                set(rendered_sources),
                {
                    first_candidates[0].relative_to(output).as_posix(),
                    second_candidates[0].relative_to(output).as_posix(),
                },
            )

            forbidden_values = (
                self.IMAGE_ENDPOINT,
                self.IMAGE_TOKEN,
                self.IMAGE_1_URL,
                self.IMAGE_2_URL,
            )
            for path in output.rglob("*"):
                if not path.is_file():
                    continue
                payload = path.read_bytes()
                for forbidden in forbidden_values:
                    self.assertNotIn(forbidden.encode("utf-8"), payload, path)
            metadata_text = (output / "data/sheet-build.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("content_url", metadata_text)

        self.assertEqual([url for url, _, _ in requests][0], self.IMAGE_ENDPOINT)
        self.assertEqual(
            set(url for url, _, _ in requests[1:]),
            {self.IMAGE_1_URL, self.IMAGE_2_URL},
        )
        self.assertTrue(all(timeout == 7.5 for _, _, timeout in requests))

    def test_publication_xlsx_images_are_materialised_without_url_leaks(self) -> None:
        tabs = self._direct_publication_tabs()
        workbook = self._publication_workbook(tabs["Publications"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with mock.patch.object(
                builder.urllib.request,
                "urlopen",
                side_effect=AssertionError(
                    "offline XLSX build must not request image URLs"
                ),
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                    publication_workbook=workbook,
                )

            assets = sorted((output / "img/sheet-publications").iterdir())
            self.assertEqual(len(assets), 3)
            self.assertEqual(
                sorted(asset.read_bytes() for asset in assets),
                sorted((TINY_PNG, TINY_JPEG, TINY_PNG)),
            )
            index_text = (output / "index.html").read_text(encoding="utf-8")
            self.assertEqual(
                site_validator._classes(index_text, "publication-figure-image"),
                3,
            )
            self.assertEqual(
                site_validator._classes(index_text, "publication-figure-slide"),
                3,
            )
            self.assertIn("Overview of the published paper", index_text)
            self.assertEqual(
                site_validator._classes(index_text, "publication-figure-caption"),
                3,
            )
            self.assertEqual(
                site_validator._classes(index_text, "publication-carousel-dot"),
                3,
            )
            self.assertNotIn("publication-figure-credit", index_text)
            self.assertNotIn("googleusercontent.com", index_text)
            self.assertNotIn("ggpht.com", index_text)
            self.assertEqual(site_validator.validate(output), [])

    def test_direct_publication_images_fail_closed_when_latest_image_is_missing(
        self,
    ) -> None:
        tabs = self._direct_publication_tabs()
        workbook = self._publication_workbook(
            tabs["Publications"],
            omit_image_for="Second Published Paper",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with self.assertRaisesRegex(
                builder.SheetBuildError,
                "latest published papers need home images",
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                    publication_workbook=workbook,
                )

    def test_direct_publication_columns_allow_zero_image_migration_state(self) -> None:
        tabs = self._direct_publication_tabs()
        workbook = self._publication_workbook(
            tabs["Publications"],
            omit_all_images=True,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            builder.build_site(
                tabs,
                REPOSITORY_ROOT / "main_site",
                output,
                "test-sheet",
                "offline_csv",
                publication_workbook=workbook,
            )
            index_text = (output / "index.html").read_text(encoding="utf-8")
            self.assertEqual(
                site_validator._classes(index_text, "publication-figure-slide"), 0
            )
            self.assertNotIn("publication-figure-carousel", index_text)
            self.assertIn("publication-panel-wide", index_text)
            self.assertFalse((output / "img/sheet-publications").exists())
            self.assertEqual(site_validator.validate(output), [])

    def test_direct_publication_images_require_workbook_export(self) -> None:
        tabs = self._direct_publication_tabs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with self.assertRaisesRegex(
                builder.SheetBuildError,
                "require an XLSX workbook export",
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                )

    def test_publication_workbook_rejects_unsafe_zip_entries(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../outside.xml", "unsafe")
        with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
            with self.assertRaisesRegex(builder.SheetBuildError, "unsafe ZIP entry"):
                builder._validate_xlsx_archive(archive)

    def test_direct_image_mode_requires_both_bridge_credentials(self) -> None:
        cases = (
            (None, None),
            (self.IMAGE_ENDPOINT, None),
            (None, self.IMAGE_TOKEN),
            (self.IMAGE_ENDPOINT, "too-short"),
        )
        for endpoint, token in cases:
            with self.subTest(endpoint=endpoint, token=token):
                tabs = self._direct_image_tabs()
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output = Path(temporary_directory) / "output"
                    with self.assertRaises(builder.SheetBuildError) as context:
                        builder.build_site(
                            tabs,
                            REPOSITORY_ROOT / "main_site",
                            output,
                            "test-sheet",
                            "offline_csv",
                            image_endpoint=endpoint,
                            image_token=token,
                        )
                self.assertRegex(str(context.exception).casefold(), r"image|token")

    def test_manifest_mapping_must_exactly_match_published_slots(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        missing = self._direct_image_manifest()
        missing["images"] = list(missing["images"])[0:1]  # type: ignore[arg-type]
        cases.append(("missing", missing, "missing"))

        duplicate = self._direct_image_manifest()
        duplicate_images = list(duplicate["images"])  # type: ignore[arg-type]
        duplicate_images.append(dict(duplicate_images[0]))
        duplicate["images"] = duplicate_images
        cases.append(("duplicate", duplicate, "duplicate"))

        extra = self._direct_image_manifest()
        extra_images = list(extra["images"])  # type: ignore[arg-type]
        extra_images.append(
            {
                "slug": "unpublished-area",
                "slot": 1,
                "field": "figure_1_image",
                "content_url": "https://lh3.googleusercontent.com/extra-image",
                "alt": "Extra image",
                "credit": "Extra credit",
            }
        )
        extra["images"] = extra_images
        cases.append(("extra", extra, r"extra|unexpected"))

        for label, manifest, expected_word in cases:
            with self.subTest(case=label):
                tabs = self._direct_image_tabs()
                fake_urlopen, _ = self._bridge_urlopen(manifest)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output = Path(temporary_directory) / "output"
                    with mock.patch.object(
                        builder.urllib.request, "urlopen", fake_urlopen
                    ):
                        with self.assertRaises(builder.SheetBuildError) as context:
                            builder.build_site(
                                tabs,
                                REPOSITORY_ROOT / "main_site",
                                output,
                                "test-sheet",
                                "offline_csv",
                                image_endpoint=self.IMAGE_ENDPOINT,
                                image_token=self.IMAGE_TOKEN,
                            )
                self.assertRegex(str(context.exception).casefold(), expected_word)

    def test_malformed_bridge_payload_is_rejected(self) -> None:
        malformed_payloads: tuple[tuple[str, object], ...] = (
            ("not-an-object", ["not", "an", "object"]),
            (
                "reported-error",
                {"ok": False, "error": {"code": "INVALID_IMAGE", "message": "bad"}},
            ),
            (
                "wrong-version",
                {
                    "ok": True,
                    "schema_version": 2,
                    "sheet": "Research",
                    "images": [],
                },
            ),
            (
                "wrong-sheet",
                {
                    "ok": True,
                    "schema_version": 1,
                    "sheet": "Projects",
                    "images": [],
                },
            ),
            (
                "images-not-list",
                {
                    "ok": True,
                    "schema_version": 1,
                    "sheet": "Research",
                    "images": {},
                },
            ),
        )
        for label, manifest in malformed_payloads:
            with self.subTest(case=label):
                tabs = self._direct_image_tabs()
                fake_urlopen, _ = self._bridge_urlopen(manifest)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output = Path(temporary_directory) / "output"
                    with mock.patch.object(
                        builder.urllib.request, "urlopen", fake_urlopen
                    ):
                        with self.assertRaises(builder.SheetBuildError):
                            builder.build_site(
                                tabs,
                                REPOSITORY_ROOT / "main_site",
                                output,
                                "test-sheet",
                                "offline_csv",
                                image_endpoint=self.IMAGE_ENDPOINT,
                                image_token=self.IMAGE_TOKEN,
                            )

    def test_malformed_manifest_entries_are_rejected(self) -> None:
        mutations = {
            "field-mismatch": {"field": "figure_2_image"},
            "non-https-url": {"content_url": "http://lh3.googleusercontent.com/x"},
            "untrusted-host": {"content_url": "https://example.com/image.png"},
            "missing-alt": {"alt": ""},
            "non-string-credit": {"credit": 123},
            "string-slot": {"slot": "1"},
        }
        for label, replacement in mutations.items():
            with self.subTest(case=label):
                manifest = self._direct_image_manifest()
                images = list(manifest["images"])  # type: ignore[arg-type]
                images[0] = {**images[0], **replacement}
                manifest["images"] = images
                tabs = self._direct_image_tabs()
                fake_urlopen, _ = self._bridge_urlopen(manifest)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output = Path(temporary_directory) / "output"
                    with mock.patch.object(
                        builder.urllib.request, "urlopen", fake_urlopen
                    ):
                        with self.assertRaises(builder.SheetBuildError):
                            builder.build_site(
                                tabs,
                                REPOSITORY_ROOT / "main_site",
                                output,
                                "test-sheet",
                                "offline_csv",
                                image_endpoint=self.IMAGE_ENDPOINT,
                                image_token=self.IMAGE_TOKEN,
                            )

    def test_malformed_downloaded_image_is_rejected(self) -> None:
        cases = (
            (b"<html>not an image</html>", "image/png"),
            (TINY_PNG, "text/plain"),
            (TINY_JPEG, "image/png"),
        )
        for payload, content_type in cases:
            with self.subTest(content_type=content_type, prefix=payload[:8]):
                tabs = self._direct_image_tabs()
                manifest = self._direct_image_manifest()
                fake_urlopen, _ = self._bridge_urlopen(
                    manifest,
                    image_payloads={
                        self.IMAGE_1_URL: (payload, content_type),
                        self.IMAGE_2_URL: (TINY_JPEG, "image/jpeg"),
                    },
                )
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output = Path(temporary_directory) / "output"
                    with mock.patch.object(
                        builder.urllib.request, "urlopen", fake_urlopen
                    ):
                        with self.assertRaises(builder.SheetBuildError):
                            builder.build_site(
                                tabs,
                                REPOSITORY_ROOT / "main_site",
                                output,
                                "test-sheet",
                                "offline_csv",
                                image_endpoint=self.IMAGE_ENDPOINT,
                                image_token=self.IMAGE_TOKEN,
                            )

    def test_legacy_research_images_do_not_call_the_image_bridge(self) -> None:
        tabs = self._publication_reference_tabs()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with mock.patch.object(
                builder.urllib.request,
                "urlopen",
                side_effect=AssertionError("legacy build must not use the network"),
            ):
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                )
            research_html = (output / "research.html").read_text(encoding="utf-8")
            self.assertIn(
                'src="img/research/slum-detection-figure-5.png"', research_html
            )
            self.assertFalse((output / "img/sheet-research").exists())

    def test_unmatched_cross_tab_publication_references_fail_the_build(self) -> None:
        cases = (
            (
                "Research",
                "Missing Paper",
                {"research_publication_1": "Missing Paper"},
            ),
            (
                "Projects",
                "Missing Paper",
                {"project_publication": "Missing Paper"},
            ),
            ("News", "Missing Paper", {"news_publication_1": "Missing Paper"}),
            (
                "Research",
                "published Paper",
                {"research_publication_1": "published Paper"},
            ),
        )
        for tab_name, bad_title, overrides in cases:
            with self.subTest(tab_name=tab_name, bad_title=bad_title):
                tabs = self._publication_reference_tabs(**overrides)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    output = root / "output"
                    with self.assertRaises(builder.SheetBuildError) as context:
                        builder.build_site(
                            tabs,
                            REPOSITORY_ROOT / "main_site",
                            output,
                            "test-sheet",
                            "offline_csv",
                        )
                message = str(context.exception)
                self.assertIn(tab_name, message)
                self.assertIn(bad_title, message)

    def test_unchecked_publication_cannot_be_referenced_from_another_tab(self) -> None:
        tabs = self._publication_reference_tabs(
            project_publication="Unchecked Paper"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            with self.assertRaises(builder.SheetBuildError) as context:
                builder.build_site(
                    tabs,
                    REPOSITORY_ROOT / "main_site",
                    output,
                    "test-sheet",
                    "offline_csv",
                )

        message = str(context.exception)
        self.assertIn("Projects", message)
        self.assertIn("Unchecked Paper", message)

    def test_project_requires_a_page_url_or_publication_dropdown(self) -> None:
        self._allow_small_fixtures("Projects")
        rows = [
            {
                "publish": "TRUE",
                "title": "Unlinked Project",
                "summary": "Summary",
                "status": "Ongoing",
                "period": "2026–",
                "area": "Research Area",
            }
        ]
        with self.assertRaisesRegex(
            builder.SheetBuildError,
            r"Projects row 2: .*related_publication.*url|Projects row 2: .*url.*related_publication",
        ):
            builder._read_csv_text(_csv_text(PROJECT_COLUMNS, rows), "Projects")

    def test_marker_replacement_preserves_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "page.html"
            path.write_text(
                "before\n  <!-- START -->\n  old\n  <!-- END -->\nafter\n",
                encoding="utf-8",
            )
            builder._replace_block(path, "<!-- START -->", "<!-- END -->", "  new")
            result = path.read_text(encoding="utf-8")
            self.assertIn("  <!-- START -->\n  new\n  <!-- END -->", result)
            self.assertEqual(result.count("<!-- START -->"), 1)
            self.assertEqual(result.count("<!-- END -->"), 1)

    def test_output_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "index.html").write_text("source", encoding="utf-8")
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            output = root / "output"
            output.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(builder.SheetBuildError, "symlink output"):
                builder._safe_prepare_output(source, output)
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
