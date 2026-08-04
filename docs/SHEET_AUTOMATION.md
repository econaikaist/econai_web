# Google Sheet to KAIST server automation

## Architecture

The production path is:

`Google Sheet (public tab data + private image bridge) + GitHub main → school-server systemd timer → build and validation → versioned release → Docker Nginx`

The existing `https://econai.kaist.ac.kr` URL, KAIST DNS A record, TLS certificate,
and school server stay unchanged. GitHub Pages, a CNAME change, an inbound webhook,
and an inbound Google-triggered webhook are not used. A small standalone Google
Apps Script is used only for Research images stored directly in Sheet cells,
because the anonymous CSV feed cannot expose those image objects. It is not the
site host and it does not push or deploy anything.

Every five minutes the server:

1. refreshes a dedicated, unprivileged checkout of GitHub `main`;
2. downloads the five Sheet tabs through their public CSV feeds;
3. in direct-image mode, requests fresh image transport URLs from the
   token-authenticated Apps Script bridge and immediately downloads the images
   into staging;
4. builds and validates the complete static site in staging;
5. compares the result with the current release; and
6. atomically switches Nginx's `current` symlink only when content changed.

If GitHub is temporarily unavailable, the last downloaded source is used so Sheet
updates can continue. If the Sheet download, schema validation, build, or site
validation fails, the current production release is not touched. Runs are serialized
with a file lock, and the last five releases are retained for rollback.

The publisher runs as `econai-publisher`, which has no login shell, sudo access, or
Docker-group membership. It can write only its managed Git checkout and
`/srv/econai-site`. Nginx mounts the release directory, configuration, and TLS files
read-only.

## Sheet contract

Sheet ID: `14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM`

Keep the five tab names and header names exact. Rows with an unchecked `publish`
cell are omitted.

### Publications

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox; checked rows are published |
| `date` | Published paper: actual publication date. Preprint: latest public version date. Use `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`. |
| `title` | Paper title |
| `authors` | Comma-separated authors |
| `venue` | Full venue name and emphasized short form, for example `Conference on Language Modeling (COLM 2026)`; use `arXiv` while it is preprint-only |
| `paper_url` | One canonical full-text or paper landing-page URL |
| `project_url` | Optional lab project page |
| `highlight` | Optional award or presentation label |
| `research_title` | Optional shorter title used on Research cards |

The site groups papers by year and sorts every year by `date` descending. Title
links replace redundant Paper buttons. The home page automatically uses the first
three rows after date sorting.

### Research

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox; checked rows are published |
| `slug` | Stable URL anchor, for example `llm-reasoning` |
| `title` | Research area title |
| `summary` | One concise area description |
| `question` | The question shown above the area summary |
| `home_summary` | One-line version shown on the home page |
| `selected_publication_1`, `selected_publication_2` | Exact paper-title dropdowns sourced from `Publications!C2:C` |
| `figure_1_image`, `figure_2_image` | Image inserted directly into the cell with **Insert > Image > Insert image in cell** |
| `figure_1_alt`, `figure_2_alt` | Accessible description of each image |
| `figure_1_credit`, `figure_2_credit` | Figure number, source, and license/credit line |

The first three checked rows become the home-page Research Focus cards. The
selected-publication cells use dropdowns sourced from the Publications title
column with invalid input rejected. The builder also requires an exact,
case-sensitive match to a checked Publications row. It then automatically reuses
that publication's paper URL, venue, and optional short title. Figure presentation
data belongs to Research because it controls the Research cards.

Both direct image cells are required in every checked Research row. Do not enter
an HTTPS URL, local path, or `=IMAGE()` formula: the final Sheet source is the
actual in-cell image object. The private Apps Script bridge calls the authorized
`CellImage` API and returns a fresh, short-lived content URL. During that same
staged build, the server downloads and validates the bytes and writes a
deterministic local image into the release. Rendered HTML references only that
local file; the temporary Google URL is never stored in HTML, release metadata,
logs, the Sheet, or GitHub.

#### Research image schema transition

The builder temporarily accepts one of two complete, mutually exclusive Research
schemas:

- Legacy mode has both `figure_1_url` and `figure_2_url`. It does not call the
  image bridge and exists only to keep the current site publishable during the
  migration.
- Final direct-image mode replaces those headers with `figure_1_image` and
  `figure_2_image`. Every checked row needs both real in-cell images, and both
  `ECONAI_SHEET_IMAGE_ENDPOINT` and `ECONAI_SHEET_IMAGE_TOKEN` must be configured
  on the server.

Mixed headers or mixed row-level modes are rejected. A missing bridge setting,
missing image, expired/invalid response, failed download, or invalid image file
fails the staged build and leaves the previous release live. The exact one-time
owner authorization, deployment, server-secret, and Sheet migration procedure is
in [`deploy/apps-script-research-images/README.md`](../deploy/apps-script-research-images/README.md).

### Projects

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox; checked rows are published |
| `title` | Project title |
| `summary` | One concise project description |
| `status` | `Ongoing` or `Completed` |
| `period` | Display period, for example `2025–` |
| `area` | Short research-area label |
| `related_publication` | Optional exact paper-title dropdown sourced from `Publications!C2:C` |
| `url` | Optional HTTPS or site-relative standalone project-page link |

Every project needs at least one of `related_publication` or `url`. With only a
related publication, the project title links to that paper's canonical `paper_url`.
With only `url`, the title links to the standalone project page. When both are
filled, the title links to the project page and a separate Related publication
link uses the selected paper's canonical `paper_url`.

### News

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox; checked rows are published |
| `date` | Sort date in `YYYY-MM-DD`, `YYYY-MM`, or `YYYY` form |
| `display_date` | Visible label such as `Jul 2026` or `Spring 2026` |
| `tag` | Short category such as `Publications`, `Award`, or `People` |
| `title` | News headline |
| `summary` | Optional explanatory sentence |
| `related_publication_1`, `related_publication_2` | Optional exact paper-title dropdowns sourced from `Publications!C2:C` |
| `url` | Optional separate HTTPS or site-relative link |

News is sorted newest first. The first item is automatically featured.

### Publication-reference dropdowns

Research, News, and Projects must cite papers through their Publications-backed
dropdown columns; do not copy titles into another free-text column or combine
multiple titles with `|`. Each dropdown uses **Dropdown (from a range)** with
`Publications!$C$2:$C` as the range and **Reject input** enabled:

- Research: `selected_publication_1`, `selected_publication_2`
- News: `related_publication_1`, `related_publication_2`
- Projects: `related_publication`

The CSV builder cannot tell whether an exact value was clicked or pasted, so the
Sheet's reject-input validation enforces dropdown-only editing. The builder is the
second safety layer: every nonblank reference must equal the `title` of a checked
Publications row, including capitalization and punctuation. An unchecked paper,
stale title, typo, or value absent from Publications fails the staged build. The
publisher does not switch the live symlink, so the last validated website remains
online.

If a title is renamed in Publications, the dropdown choices update but existing
selected cells may retain the previous title. Search the Research, News, and
Projects tabs for the old title and reselect the renamed title from each dropdown.
If a reference should not be public yet, either clear that optional reference or
check the matching Publications row; do not bypass the dropdown with a manually
entered paper URL in a standalone `url` column. The failed row and title are
reported in the publisher log.

### Members

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox; checked rows are published |
| `section` | `Faculty`, `Ph.D. Students`, `Master's Students`, `Lab Internship`, `Alumni`, or `Pre-EconAI Alumni` |
| `group` | Internship term such as `Spring 2026`; blank otherwise |
| `name_en`, `name_ko` | English name and optional Korean name |
| `role` | Current role for cards; optional degree/year for alumni |
| `details` | Research interests for students; required current position for alumni |
| `photo` | Local image path for Faculty/Student cards |
| `email` | Public email address |
| `website`, `scholar`, `linkedin` | Optional HTTPS profile links |
| `phone`, `address` | Optional public faculty contact fields |
| `affiliations` | Faculty footer affiliations separated by `|` |
| `joint_supervisor`, `joint_supervisor_url` | Optional paired alumni footnote label and HTTPS profile URL |

Members and section order follow the physical row order in the Sheet; no separate
sort column is used. Publication author names are bolded automatically for every
checked member except `Pre-EconAI Alumni`, so no manual highlight flag is needed.
Repeated joint-supervisor pairs are rendered once as a linked footnote below that
alumni section. The first checked Faculty row also supplies Contact and every page's
footer affiliations.

The Members tab is publicly downloadable because the site builder reads it without
Google credentials. Store only information intended for public display.

## Safety behavior

The build rejects missing or mixed columns, invalid checkboxes, duplicate or blank
records, malformed dates, unsafe URLs, broken cross-tab publication references,
missing local or direct-cell images, invalid image downloads, duplicate HTML IDs,
and any symlink in the generated site. It also refuses to publish fewer than 20
publication rows, preventing an accidental mass deletion from replacing the live
list. A failed build leaves the last validated release live.

The generated release is never written into the Git checkout or the live Nginx
directory. The source checkout and immutable releases are separate, and the
`current` symlink is replaced atomically on the same filesystem.

## One-time server installation

After this change is merged and `/srv/econai_web` is updated, run:

```bash
cd /srv/econai_web
sudo ./deploy/install_server_publisher.sh
```

The installer creates the unprivileged publisher account and directories, installs
the systemd units and root-owned publisher entrypoint, creates the first validated
release, recreates the existing Nginx container with the read-only release mount,
and enables the timer. It does not change DNS, the public URL, or TLS certificates.

Install the compatibility-capable publisher while Research is still in legacy URL
mode. Before switching the Sheet to direct-image headers, complete the bridge setup
and create the root-owned `/etc/econai-sheet-publisher.env` described in the bridge
README. The service imports that file before dropping to the unprivileged publisher
account; the endpoint and token must not be committed to GitHub.

## Operations

```bash
# Timer and last run
systemctl status econai-sheet-publisher.timer
systemctl status econai-sheet-publisher.service

# Trigger an immediate refresh after editing the Sheet
sudo systemctl start econai-sheet-publisher.service

# Review recent publisher output or failures
journalctl -u econai-sheet-publisher.service -n 100 --no-pager

# Inspect the last successful/no-change result
cat /srv/econai-site/state/status.json
```

In direct-image mode, a bridge or image error appears in the service journal. The
status file remains the last successful/no-change result, and the `current`
symlink and public site remain on the previous validated release. Correct the
Sheet cell or bridge configuration and start the service again.

To roll back, point `/srv/econai-site/current` to one of the retained directories
under `/srv/econai-site/releases` using a temporary relative symlink and atomic
rename. Do not replace `current` with a real directory.

## Local verification

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build_sheet_site.py --output-dir /tmp/econai-site-build
python3 scripts/validate_site.py /tmp/econai-site-build
python3 scripts/sync_server_site.py \
  --source-repo . \
  --deploy-root /tmp/econai-site-releases
python3 -m http.server 8895 \
  --directory /tmp/econai-site-releases/current
```

Open `http://127.0.0.1:8895/index.html`, `members.html`, `research.html`,
`projects.html`, and `publications.html`.
