# Google Sheet to KAIST server automation

## Architecture

The production path is:

`Google Sheet (public CSV/XLSX data and embedded images) + GitHub main → school-server systemd timer → build and validation → versioned release → Docker Nginx`

The existing `https://econai.kaist.ac.kr` URL, KAIST DNS A record, TLS certificate,
and school server stay unchanged. GitHub Pages, a CNAME change, an inbound webhook,
and an inbound Google-triggered webhook are not used. Research, Publications, and
Members images stored directly in Sheet cells are read from the same anonymous
XLSX workbook export. Normal CLI builds, GitHub validation, and server publishing
need no Apps Script endpoint, token, or Google owner login. The older private
Research image bridge remains available only to explicit Python callers that
provide bridge settings but no workbook; it is not used by normal publishing.

Every five minutes the server:

1. refreshes a dedicated, unprivileged checkout of GitHub `main`;
2. downloads the five Sheet tabs through their public CSV feeds and a matching
   XLSX workbook export whenever Research, Publications, or Members need images;
3. matches embedded images to published Sheet rows and validates their metadata,
   drawing anchors, workbook relationships, and image bytes before copying them
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
| `date` | Published paper: publication date. Accepted/forthcoming paper: acceptance date, or public acceptance-announcement date when the decision date is unavailable (note the source in the cell). Preprint: latest public version date. Use `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`; do not invent missing date components. |
| `title` | Paper title |
| `authors` | Comma-separated authors |
| `venue` | Full venue name and emphasized short form, for example `Conference on Language Modeling (COLM 2026)`; use `arXiv` while it is preprint-only |
| `paper_url` | One canonical full-text or paper landing-page URL. May be blank for an accepted paper whose public link is not yet available; its title is displayed without a link. A public URL is required before selecting it in a Research, News, or Projects publication dropdown. |
| `project_url` | Optional research group project page |
| `highlight` | Optional award or presentation label |
| `research_title` | Optional shorter title used on Research cards |
| `home_image` | Optional-schema column containing an image inserted with **Insert > Image > Insert image in cell** |
| `home_image_alt` | Accessible description of the homepage figure |
| `home_image_credit` | Optional figure number or source/credit line |

The Publications page first lists **Accepted & Published** papers, followed by
**Preprints**. Each section groups papers by year and sorts by `date` descending
within each year, regardless of Sheet row order. Equal dates use title order.
Venues beginning with `arXiv`, `Preprint`, or `Working paper` belong to Preprints;
change the venue to the accepted conference/workshop/journal and update `date`
when a paper is accepted. An arXiv **link** does not make an accepted paper a
preprint. List a paper accepted at multiple workshops once, naming both venues.
Title links replace redundant Paper buttons. The home page shows the three most
recent main-conference or journal papers with public links, excluding preprints
and venues containing `workshop`, so workshop additions do not replace the
homepage's representative figures.

The homepage pairs that three-paper list with one larger 5:3 figure card. Images use
`object-fit: contain`, so a paper figure is never cropped or distorted. Subtle
gray previous and next arrows sit over the vertical center of the image. The
paper title appears below the figure, followed by three small pagination dots;
the active dot changes opacity with the current slide. The left/right arrow keys
work while the card has focus. Venues, credits, and the numeric slide count are
not displayed. Add all three image headers together or omit
all three. With the headers omitted, or with a complete header set but zero
embedded or `IMAGE("https://...")` `home_image` cells, the homepage keeps the
original clean text-only publication panel. This lets the columns be created
before anyone signs in to upload figures. As soon as any image is inserted in
the `home_image` column, each of the current latest three eligible homepage papers must
have a real in-cell image or an allowed HTTPS `IMAGE()` formula and non-empty
`home_image_alt`; a partial set fails the staged build and keeps the last valid
release live.

The server securely reads only the `Publications` worksheet, its drawing anchors,
and the three matched media files from the anonymous XLSX export. It matches each
image's exact Sheet row and title, validates the workbook paths, XML, file counts,
sizes, and image signatures, and writes content-hashed local files under
`img/sheet-publications/`. The generated homepage never contains a Google image
URL. `home_image_credit` may be blank and is shown below the venue when provided.

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
an HTTPS URL, local path, or `=IMAGE()` formula: the source is the actual in-cell
image object. The builder reads the `Research` worksheet from the anonymous XLSX
export and requires its published slugs and text metadata to match the CSV. Each
published row must have exactly one embedded image in each figure column. Missing
or duplicate images, stale rows, external workbook relationships, unsafe ZIP
entries, and invalid image bytes fail the build. A failed workbook never falls
back to old pictures or to the private bridge.

The images become content-hashed local files under `img/sheet-research/`; rendered
HTML contains no temporary Google image URL. `figure_1_alt` and `figure_2_alt`
provide accessible descriptions. If one is blank, the builder uses the embedded
image's alternative-text description or title, and rejects a figure with no
usable alternative text. Credits may be blank. The whole website is validated
before any new release replaces the current site.

#### Research image schema transition

The builder temporarily accepts one of two complete, mutually exclusive Research
schemas:

- Legacy mode has both `figure_1_url` and `figure_2_url`. It does not call the
  image bridge and exists only to keep the current site publishable during the
  migration.
- Direct-image mode replaces those headers with `figure_1_image` and
  `figure_2_image`. Every checked row needs both real in-cell images. The normal
  builder fetches their XLSX export automatically; no private image bridge
  configuration is required.

Mixed headers or mixed row-level modes are rejected. Missing images, mismatched
CSV/XLSX snapshots, failed workbook downloads, or invalid image files fail the
staged build and leave the previous release live. Offline builds using direct
images must supply a matching `--xlsx-file` alongside `--csv-dir`.

The historical bridge setup guide remains in
[`deploy/apps-script-research-images/README.md`](../deploy/apps-script-research-images/README.md)
for explicit callers without an XLSX workbook. When a workbook is supplied, it
always takes precedence, including when obsolete bridge settings still exist.

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
| `section` | `Faculty`, `Postdoctoral Researcher`, `Ph.D. Students`, `Master's Students`, `Research Interns`, `Staff`, `Alumni`, or `Pre-EconAI Alumni` |
| `group` | Internship term such as `Spring 2026`; blank otherwise |
| `name_en`, `name_ko` | English name and optional Korean name |
| `role` | Current role shown directly below a card name; for alumni, include the degree, graduation year, and KAIST department, e.g. `M.S. 2026 (School of Computing)`; for Staff, use a descriptive function such as `Research Group Administration & Operations` rather than the generic `Staff` |
| `details` | Optional longer description for Faculty/Student/Staff cards; required current position for alumni |
| `photo` | Optional for every Faculty/Student/Staff card. Use **Insert > Image > Insert image in cell** to upload a photo; leave it blank to use the basic profile image |
| `email` | Optional public email address for any member or alumnus |
| `website`, `scholar`, `linkedin` | Optional HTTPS profile links for any member or alumnus |
| `phone`, `address` | Optional public faculty contact fields |
| `affiliations` | Faculty footer affiliations separated by `|` |
| `joint_supervisor`, `joint_supervisor_url` | Optional paired alumni footnote label and HTTPS profile URL |

Sections use the canonical order listed above, with Staff between Research Interns
and Alumni. Rows within each section follow the physical Sheet order; internship
terms follow the order in which each `group` first appears and are always expanded.
Keep internship groups newest-first in the Sheet. For example, use `Summer 2026`,
`Spring 2026`, `Winter 2025`, then `Fall 2025`; people within a term follow their
row order. A person attending more than one term should have one row per term.
Publication author names are bolded automatically for every checked member,
including `Pre-EconAI Alumni`, so no manual highlight flag is needed. Repeated
joint-supervisor pairs are rendered once as a numbered, linked footnote below that alumni
section. Each alumnus's superscript matches the correct supervisor's number; numbering
restarts in each alumni section. The first checked Faculty row also supplies Contact and every page's footer
affiliations.

Member photos need no URL, file path, alt-text column, or Apps Script change.
Select the person's `photo` cell and choose **Insert > Image > Insert image in
cell**; replacing that cell's image later replaces the website photo on the next
normal publisher run. The builder copies the uploaded binary into a hashed local
asset and generates accessible alt text from `name_en`, so temporary Google image
URLs are never exposed on the public site. A blank `photo` cell uses
`img/basic_profile.png` in every card section. Legacy local paths and tightly
restricted `IMAGE("https://econai.kaist.ac.kr/img/...")` formulas remain accepted
only to let the existing server photos move into the Sheet one row at a time.

Alumni and Pre-EconAI Alumni use the same `email`, `website`, `scholar`, and
`linkedin` cells as current members. Every nonblank value becomes the same profile
icon button at the right of that alumnus's current-position row; blank cells simply
omit their button. Sheet edits are picked up by the normal publisher without a code
change.

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

The normal publisher needs no Research image endpoint or token. Existing
`/etc/econai-sheet-publisher.env` settings may remain for compatibility, but the
current CLI uses the XLSX workbook and does not call that bridge. Do not put old
bridge credentials in the Sheet or GitHub. An already installed, running publisher
picks up builder changes from `main` on its normal polling cycle; changing the
builder does not require a new server login.

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

A workbook, anchor, alternative-text, or image error appears in the service
journal with its Research, Publications, or Members context. The status file
remains the last successful/no-change result, and the `current` symlink and public
site remain on the previous validated release. Correct the Sheet cell and allow
the next timer run, or start the service again.

The GitHub workflow validates code and builds the Sheet-driven site; it does not
deploy to KAIST or control the server timer. A successful GitHub run therefore
confirms the source and current Sheet can build, not that the KAIST server has
published them. If new content remains absent after the polling interval, someone
with server access must inspect the timer/service logs above.

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
