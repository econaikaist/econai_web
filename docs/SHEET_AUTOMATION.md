# Google Sheet to GitHub Pages automation

## Architecture

The production path is:

`Google Sheet (content) → GitHub Actions (build and validation) → GitHub Pages (hosting) → econai.kaist.ac.kr (CNAME)`

The KAIST web server is not part of this path. KAIST's authoritative DNS remains responsible only for resolving `econai.kaist.ac.kr` to GitHub Pages.

The deploy workflow runs whenever `main` changes, four times per hour at minutes 07, 22, 37, and 52, and on manual or `repository_dispatch` requests. A Sheet edit therefore appears automatically after the next scheduled run and GitHub's queue/deploy time. Scheduled runs can be delayed; use **Actions → Deploy Sheet-driven site to GitHub Pages → Run workflow** when an immediate refresh matters.

## Sheet contract

Sheet ID: `14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM`

Keep the three tab names and header names exact. Rows with an unchecked `publish` cell are omitted.

### Publications

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `date` | Published paper: actual publication date. Preprint: latest public version date. Use `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`. |
| `title` | Paper title |
| `authors` | Comma-separated authors |
| `venue` | Full venue name and emphasized short form, for example `Conference on Language Modeling (COLM 2026)`; use `arXiv` while it is preprint-only |
| `paper_url` | One canonical full-text or paper landing-page URL |
| `project_url` | Optional lab project page |
| `highlight` | Optional award or presentation label |

The site groups papers by year and sorts every year by `date` descending. Title links replace redundant Paper buttons. The home page automatically uses the first three rows after date sorting.

### Research

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `title` | Research area title |
| `summary` | One concise area description |

The first three published rows become the home-page Research Focus cards. `main_site/data/site_catalog.json` adds stable questions, short home descriptions, and two representative publications/figures for the current three areas. If an area title changes, update the matching catalog key in the same PR.

### Projects

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `title` | Project title |
| `summary` | One concise project description |

New project rows work with only these three fields and default to Ongoing. `main_site/data/site_catalog.json` optionally supplies status, period, area, and a link for recurring/current projects, keeping the Sheet short.

## Safety behavior

The build aborts without replacing production when a required column, title, summary, author, venue, date, HTTPS paper link, selected publication, or local figure is invalid. It also refuses to publish fewer than 20 publication rows, preventing an accidental mass deletion from replacing the live list. The generated site is then checked for row counts, duplicate HTML IDs, and broken local links/assets before upload.

The Sheet content is intentionally public, but edit access must not be public. Before enabling the deployment workflow, change Google sharing from **Anyone with the link: Editor** to **Viewer**, then grant Editor only to named lab Google accounts. The GitHub workflow needs anonymous view access, not anonymous edit access.

## One-time GitHub Pages and DNS cutover

These actions require an `econaikaist` owner/repository admin and KAIST DNS administrator:

1. In the `econaikaist` account Pages settings, add and verify `econai.kaist.ac.kr`; keep GitHub's TXT record in KAIST DNS.
2. In `econaikaist/econai_web` → **Settings → Pages**, select **GitHub Actions** as the publishing source and set the custom domain to `econai.kaist.ac.kr`.
3. Only after GitHub accepts that custom domain, replace the current DNS record with `econai.kaist.ac.kr. CNAME econaikaist.github.io.`
4. Verify the site and all existing paths, then enable **Enforce HTTPS**. DNS/certificate propagation can take up to 24 hours.

GitHub Actions-based Pages does not require a committed `CNAME` file; the custom domain lives in the repository Pages settings.

## Local verification

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build_sheet_site.py --output-dir /tmp/econai-site
python3 scripts/validate_site.py /tmp/econai-site
python3 -m http.server 8895 --directory /tmp/econai-site
```

Open `http://127.0.0.1:8895/index.html`, `research.html`, `projects.html`, and `publications.html`.
