from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import build_sheet_site as builder  # noqa: E402


PUBLICATION_HEADER = (
    "publish,date,title,authors,venue,paper_url,project_url,highlight\n"
)


class SheetBuilderTests(unittest.TestCase):
    def test_publications_are_sorted_by_exact_date_descending(self) -> None:
        text = PUBLICATION_HEADER + "\n".join(
            [
                "TRUE,2026-04-30,Older,A Author,arXiv,https://example.com/older,,",
                "TRUE,2026-07-12,Newer,B Author,COLM (2026),https://example.com/newer,,",
                "FALSE,2027-01-01,Hidden,C Author,arXiv,https://example.com/hidden,,",
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
            + "TRUE,,Legacy,A Author,Workshop (2017),https://example.com/paper,,\n"
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
            + "TRUE,2026-01-01,Unsafe,A Author,arXiv,javascript:alert(1),,\n"
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
            + "TRUE,2026-01-01,Only one,A Author,arXiv,https://example.com/paper,,\n"
        )
        with self.assertRaisesRegex(builder.SheetBuildError, "at least 20"):
            builder._read_csv_text(text, "Publications")

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


if __name__ == "__main__":
    unittest.main()
