# Google Sheet to KAIST server automation

## Architecture

The production path is:

`Google Sheet + GitHub main → school-server systemd timer → build and validation → versioned release → Docker Nginx`

The existing `https://econai.kaist.ac.kr` URL, KAIST DNS A record, TLS certificate,
and school server stay unchanged. GitHub Pages, a CNAME change, an inbound webhook,
and Google Apps Script are not used.

Every five minutes the server:

1. refreshes a dedicated, unprivileged checkout of GitHub `main`;
2. downloads the five Sheet tabs;
3. builds and validates the complete static site in staging;
4. compares the result with the current release; and
5. atomically switches Nginx's `current` symlink only when content changed.

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
| `publish` | Checkbox |
| `date` | Published paper: actual publication date. Preprint: latest public version date. Use `YYYY-MM-DD`, `YYYY-MM`, or `YYYY`. |
| `title` | Paper title |
| `authors` | Comma-separated authors |
| `venue` | Full venue name and emphasized short form, for example `Conference on Language Modeling (COLM 2026)`; use `arXiv` while it is preprint-only |
| `paper_url` | One canonical full-text or paper landing-page URL |
| `project_url` | Optional lab project page |
| `highlight` | Optional award or presentation label |
| `research_title` | Optional shorter title used only on Research/News cards |
| `figure_src` | Local figure path for a selected Research paper; otherwise blank |
| `figure_alt` | Accessible description for `figure_src`; otherwise blank |
| `figure_credit` | Figure number/source/license line; otherwise blank |

The site groups papers by year and sorts every year by `date` descending. Title
links replace redundant Paper buttons. The home page automatically uses the first
three rows after date sorting.

### Research

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `slug` | Stable URL anchor, for example `llm-reasoning` |
| `title` | Research area title |
| `summary` | One concise area description |
| `question` | The question shown above the area summary |
| `home_summary` | One-line version shown on the home page |
| `selected_publication_1` | Exact title from Publications |
| `selected_publication_2` | Exact title from Publications |

The first three published rows become the home-page Research Focus cards. Figure
metadata is read from the matching Publications rows, so Research needs only the
two exact publication titles.

### Projects

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `title` | Project title |
| `summary` | One concise project description |
| `status` | `Ongoing` or `Completed` |
| `period` | Display period, for example `2025–` |
| `area` | Short research-area label |
| `url` | HTTPS or site-relative project/paper link |

### News

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `date` | Sort date in `YYYY-MM-DD`, `YYYY-MM`, or `YYYY` form |
| `display_date` | Visible label such as `Jul 2026` or `Spring 2026` |
| `tag` | Short category such as `Publications`, `Award`, or `People` |
| `title` | News headline |
| `summary` | Optional explanatory sentence |
| `related_publications` | Optional exact Publication titles separated by `|`; links are resolved automatically |
| `url` | Optional separate HTTPS or site-relative link |

News is sorted newest first. The first item is automatically featured.

### Members

| Column | What to enter |
| --- | --- |
| `publish` | Checkbox |
| `section` | `Faculty`, `Ph.D. Students`, `Master's Students`, `Lab Internship`, `Alumni`, or `Pre-EconAI Alumni` |
| `group` | Internship term such as `Spring 2026`; blank otherwise |
| `sort_order` | Positive integer within the section/term |
| `name_en`, `name_ko` | English name and optional Korean name |
| `role` | Current role for cards; degree/year for alumni |
| `details` | Research interests for students; current position for alumni |
| `photo` | Local image path for Faculty/Student cards |
| `email` | Public email address |
| `website`, `scholar`, `linkedin` | Optional HTTPS profile links |
| `phone`, `address` | Optional public faculty contact fields |
| `highlight_publications` | Checkbox; bold this English name in publication author lists |

The Members tab is publicly downloadable because the site builder reads it without
Google credentials. Store only information intended for public display.

## Safety behavior

The build rejects missing columns, invalid checkboxes, duplicate or blank records,
malformed dates, unsafe URLs, broken selected-publication references, missing local
images, duplicate HTML IDs, and any symlink in the generated site. It also refuses
to publish fewer than 20 publication rows, preventing an accidental mass deletion
from replacing the live list. A failed build leaves the last validated release live.

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
