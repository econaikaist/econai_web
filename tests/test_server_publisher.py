from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import sync_server_site as publisher  # noqa: E402


class ServerPublisherTests(unittest.TestCase):
    def _write_site(self, root: Path, body: str, built_at: str) -> None:
        (root / "data").mkdir(parents=True)
        (root / "index.html").write_text(body, encoding="utf-8")
        (root / "data/sheet-build.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "built_at": built_at,
                    "published_rows": {
                        "Publications": 32,
                        "Research": 3,
                        "Projects": 5,
                        "News": 3,
                        "Members": 15,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_digest_ignores_only_build_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "first"
            second = root / "second"
            self._write_site(first, "same", "2026-08-03T01:00:00Z")
            self._write_site(second, "same", "2026-08-03T02:00:00Z")
            self.assertEqual(publisher.site_digest(first), publisher.site_digest(second))

            (second / "index.html").write_text("changed", encoding="utf-8")
            self.assertNotEqual(publisher.site_digest(first), publisher.site_digest(second))

    def test_digest_detects_news_or_members_metadata_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "first"
            second = root / "second"
            self._write_site(first, "same", "2026-08-03T01:00:00Z")
            self._write_site(second, "same", "2026-08-03T02:00:00Z")
            metadata_path = second / "data/sheet-build.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["published_rows"]["News"] += 1
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            self.assertNotEqual(publisher.site_digest(first), publisher.site_digest(second))

    def test_activation_uses_relative_atomic_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            deploy_root = Path(temporary_directory) / "econai-site"
            release = deploy_root / "releases" / "abc123"
            release.mkdir(parents=True)

            publisher.activate_release(release, deploy_root)

            current = deploy_root / "current"
            self.assertTrue(current.is_symlink())
            self.assertEqual(os.readlink(current), "releases/abc123")
            self.assertEqual(publisher._current_release(deploy_root), release.resolve())

    def test_pruning_retains_current_and_requested_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            deploy_root = Path(temporary_directory) / "econai-site"
            releases_dir = deploy_root / "releases"
            releases_dir.mkdir(parents=True)
            releases = []
            for index in range(6):
                release = releases_dir / f"release-{index}"
                release.mkdir()
                os.utime(release, (time.time() + index, time.time() + index))
                releases.append(release)
            publisher.activate_release(releases[-1], deploy_root)

            publisher._prune_releases(deploy_root, keep_releases=3)

            remaining = [path for path in releases_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(remaining), 3)
            self.assertTrue(releases[-1].exists())

    def test_non_symlink_current_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            deploy_root = Path(temporary_directory) / "econai-site"
            release = deploy_root / "releases" / "abc123"
            release.mkdir(parents=True)
            (deploy_root / "current").mkdir()

            with self.assertRaises(publisher.PublishError):
                publisher.activate_release(release, deploy_root)

    def test_failed_sheet_build_leaves_current_release_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            deploy_root = root / "econai-site"
            previous = deploy_root / "releases" / "previous"
            previous.mkdir(parents=True)
            (previous / "index.html").write_text("last good", encoding="utf-8")
            publisher.activate_release(previous, deploy_root)

            csv_dir = root / "csv"
            csv_dir.mkdir()
            (csv_dir / "Publications.csv").write_text(
                "publish,date,title,authors,venue,paper_url,project_url,highlight,"
                "research_title\n"
                "TRUE,2026-01-01,Only one,A Author,arXiv,https://example.com/paper,,,\n",
                encoding="utf-8",
            )
            (csv_dir / "Research.csv").write_text(
                "publish,slug,title,summary,question,home_summary,selected_publication_1,"
                "figure_1_url,figure_1_alt,figure_1_credit,selected_publication_2,"
                "figure_2_url,figure_2_alt,figure_2_credit\n"
                "TRUE,area,Area,Summary,Question,Home summary,Only one,"
                "img/research/slum-detection-figure-5.png,Alt,Credit,,,,\n",
                encoding="utf-8",
            )
            (csv_dir / "Projects.csv").write_text(
                "publish,title,summary,status,period,area,url\n"
                "TRUE,Project,Summary,Ongoing,2026–,Area,https://example.com/project\n",
                encoding="utf-8",
            )
            (csv_dir / "News.csv").write_text(
                "publish,date,display_date,tag,title,summary,related_publications,url\n"
                "TRUE,2026-08-03,Aug 2026,People,News,Summary,,https://example.com/news\n",
                encoding="utf-8",
            )
            (csv_dir / "Members.csv").write_text(
                "publish,section,group,name_en,name_ko,role,details,photo,email,"
                "website,scholar,linkedin,phone,address,affiliations,joint_supervisor,"
                "joint_supervisor_url\n"
                "TRUE,Faculty,,Example Professor,,Professor,Profile,img/prof_jihee.jpg,,"
                "https://example.com/,,,,,KAIST School of Business,,,,\n",
                encoding="utf-8",
            )
            arguments = SimpleNamespace(
                deploy_root=deploy_root,
                source_repo=REPOSITORY_ROOT,
                checkout_dir=root / "unused-checkout",
                remote_url=publisher.DEFAULT_REMOTE_URL,
                branch="main",
                sheet_id=publisher.DEFAULT_SHEET_ID,
                csv_dir=csv_dir,
                timeout=5.0,
                keep_releases=5,
            )

            with self.assertRaises(publisher.PublishError):
                publisher.publish_once(arguments)

            self.assertEqual(publisher._current_release(deploy_root), previous.resolve())
            self.assertEqual((deploy_root / "current/index.html").read_text(), "last good")

    def test_failed_members_sheet_build_leaves_current_release_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            deploy_root = root / "econai-site"
            previous = deploy_root / "releases" / "previous"
            previous.mkdir(parents=True)
            (previous / "index.html").write_text("last good", encoding="utf-8")
            publisher.activate_release(previous, deploy_root)

            csv_dir = root / "csv"
            csv_dir.mkdir()
            publication_rows = "\n".join(
                "TRUE,2026-01-{day:02d},Paper {day},A Author,arXiv,"
                "https://example.com/paper-{day},,,".format(day=day)
                for day in range(1, 21)
            )
            (csv_dir / "Publications.csv").write_text(
                "publish,date,title,authors,venue,paper_url,project_url,highlight,"
                "research_title\n"
                + publication_rows
                + "\n",
                encoding="utf-8",
            )
            (csv_dir / "Research.csv").write_text(
                "publish,slug,title,summary,question,home_summary,selected_publication_1,"
                "figure_1_url,figure_1_alt,figure_1_credit,selected_publication_2,"
                "figure_2_url,figure_2_alt,figure_2_credit\n"
                "TRUE,area,Area,Summary,Question,Home summary,Paper 1,"
                "img/research/slum-detection-figure-5.png,Alt 1,Credit 1,Paper 2,"
                "img/research/economic-development-figure-2.png,Alt 2,Credit 2\n",
                encoding="utf-8",
            )
            (csv_dir / "Projects.csv").write_text(
                "publish,title,summary,status,period,area,url\n"
                "TRUE,Project,Summary,Ongoing,2026–,Area,https://example.com/project\n",
                encoding="utf-8",
            )
            (csv_dir / "News.csv").write_text(
                "publish,date,display_date,tag,title,summary,related_publications,url\n"
                "TRUE,2026-08-03,Aug 2026,People,News,Summary,,https://example.com/news\n",
                encoding="utf-8",
            )
            (csv_dir / "Members.csv").write_text(
                # Deliberately omit the unique `section` sentinel column.
                "publish,group,name_en,name_ko,role,details,photo,email,website,"
                "scholar,linkedin,phone,address,affiliations,joint_supervisor,"
                "joint_supervisor_url\n"
                "TRUE,,Example Professor,,Professor,Profile,,,,,,,,,,\n",
                encoding="utf-8",
            )
            arguments = SimpleNamespace(
                deploy_root=deploy_root,
                source_repo=REPOSITORY_ROOT,
                checkout_dir=root / "unused-checkout",
                remote_url=publisher.DEFAULT_REMOTE_URL,
                branch="main",
                sheet_id=publisher.DEFAULT_SHEET_ID,
                csv_dir=csv_dir,
                timeout=5.0,
                keep_releases=5,
            )

            with self.assertRaises(publisher.PublishError):
                publisher.publish_once(arguments)

            self.assertEqual(publisher._current_release(deploy_root), previous.resolve())
            self.assertEqual((deploy_root / "current/index.html").read_text(), "last good")


if __name__ == "__main__":
    unittest.main()
