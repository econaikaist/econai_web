from __future__ import annotations

import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


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
    "figure_src",
    "figure_alt",
    "figure_credit",
)
RESEARCH_COLUMNS = (
    "publish",
    "slug",
    "title",
    "summary",
    "question",
    "home_summary",
    "selected_publication_1",
    "selected_publication_2",
)
PROJECT_COLUMNS = ("publish", "title", "summary", "status", "period", "area", "url")
NEWS_COLUMNS = (
    "publish",
    "date",
    "display_date",
    "tag",
    "title",
    "summary",
    "related_publications",
    "url",
)
MEMBER_COLUMNS = (
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
)
PUBLICATION_HEADER = ",".join(PUBLICATION_COLUMNS) + "\n"


def _csv_text(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


class SheetBuilderTests(unittest.TestCase):
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

    def test_publications_are_sorted_by_exact_date_descending(self) -> None:
        text = PUBLICATION_HEADER + "\n".join(
            [
                "TRUE,2026-04-30,Older,A Author,arXiv,https://example.com/older,,,,,,",
                "TRUE,2026-07-12,Newer,B Author,COLM (2026),https://example.com/newer,,,,,,",
                "FALSE,2027-01-01,Hidden,C Author,arXiv,https://example.com/hidden,,,,,,",
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

    def test_blank_date_uses_one_unambiguous_venue_year(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,,Legacy,A Author,Workshop (2017),https://example.com/paper,,,,,,\n"
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
            + "TRUE,2026-01-01,Unsafe,A Author,arXiv,javascript:alert(1),,,,,,\n"
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
            + "TRUE,2026-01-01,Only one,A Author,arXiv,https://example.com/paper,,,,,,\n"
        )
        with self.assertRaisesRegex(builder.SheetBuildError, "at least 20"):
            builder._read_csv_text(text, "Publications")

    def test_publication_csv_cannot_be_mistaken_for_news_or_members(self) -> None:
        text = (
            PUBLICATION_HEADER
            + "TRUE,2026-01-01,Paper,A Author,arXiv,https://example.com/paper,,,,,,\n"
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
                    "related_publications": "Paper A | Paper B",
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
                    "sort_order": "1",
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
                "figure_src": "img/research/slum-detection-figure-5.png",
                "figure_alt": "Example result map",
                "figure_credit": "Example figure credit",
            },
            {
                "publish": "TRUE",
                "date": "2026-04-30",
                "title": "Older Paper",
                "authors": "C Author",
                "venue": "arXiv",
                "paper_url": "https://example.com/older-paper",
                "research_title": "Test Research Area",
                "figure_src": "img/research/economic-development-figure-2.png",
                "figure_alt": "Example comparison chart",
                "figure_credit": "Second example figure credit",
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
                "selected_publication_2": "Older Paper",
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
                "url": "https://example.com/project",
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
                "related_publications": "Newer Paper | Older Paper",
            },
        ]
        member_rows = [
            {
                "publish": "TRUE",
                "section": "Faculty",
                "sort_order": "1",
                "name_en": "A Author",
                "role": "Professor",
                "details": "Faculty profile",
                "photo": "img/prof_jihee.jpg",
                "email": "professor@example.com",
                "highlight_publications": "TRUE",
            },
            {
                "publish": "TRUE",
                "section": "Master's Students",
                "sort_order": "2",
                "name_en": "Second Student",
                "role": "Master's Student",
                "details": "Second in display order",
                "photo": "img/basic_profile.png",
            },
            {
                "publish": "TRUE",
                "section": "Master's Students",
                "sort_order": "1",
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
                    "Projects": 1,
                    "News": 2,
                    "Members": 3,
                },
            )
            index_text = (output / "index.html").read_text(encoding="utf-8")
            member_text = (output / "members.html").read_text(encoding="utf-8")
            publication_text = (output / "publications.html").read_text(
                encoding="utf-8"
            )
            self.assertEqual(site_validator._classes(index_text, "sheet-news-item"), 2)
            self.assertEqual(site_validator._classes(member_text, "sheet-member-item"), 3)
            self.assertLess(
                index_text.index("Newer lab news"), index_text.index("Older lab news")
            )
            self.assertLess(
                member_text.index("First Student"), member_text.index("Second Student")
            )
            self.assertIn('href="https://example.com/newer-paper"', index_text)
            self.assertIn('href="https://example.com/older-paper"', index_text)
            self.assertIn(
                '<strong class="publication-lab-author">A Author</strong>',
                publication_text,
            )
            self.assertEqual(site_validator.validate(output), [])

            metadata["published_rows"]["News"] = 3
            metadata["published_rows"]["Members"] = 4
            (output / "data/sheet-build.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            errors = site_validator.validate(output)
            self.assertIn("index.html news row count does not match Sheet metadata", errors)
            self.assertIn("members.html row count does not match Sheet metadata", errors)

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
