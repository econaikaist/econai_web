# Research in-cell image bridge

This private standalone Apps Script is the narrow bridge between images stored
directly in the Google Sheet and the EconAI server publisher. The public CSV feed
contains the Research text fields, but it cannot expose a Google Sheets
`CellImage` value. The bridge reads those image cells as the account that deployed
the script and returns fresh, short-lived Google content URLs to the server.

Those URLs are transport only. During the same staged build, the server downloads
and validates every image and stores a deterministic local copy in that release.
Rendered HTML points only to that local file. A Google content URL must never be
written to HTML, build metadata, logs, the Sheet, Script Properties, or GitHub.

## Final Sheet columns

The final `Research` header row must include:

```text
publish
slug
figure_1_image
figure_1_alt
figure_1_credit
figure_2_image
figure_2_alt
figure_2_credit
```

- Use **Insert > Image > Insert image in cell** for both `figure_*_image` cells
  in every published Research row. Do not enter a URL, local path, or `=IMAGE()`
  formula in these cells.
- Keep `slug` stable and unique. It must contain only lowercase letters, numbers,
  and single hyphens, because the server uses it as the image identity.
- `publish` must be a checked checkbox (or `TRUE`) for the row to be exported.
- Put an accessible description in each `figure_*_alt` cell. Built-in image alt
  text is only a fallback. Credit/source text is optional.

The site builder temporarily supports a mutually exclusive legacy Research
schema with `figure_1_url` and `figure_2_url`. The bridge itself supports only the
final direct-image schema. Do not keep legacy URL headers beside final image
headers, and do not mix the two modes row by row.

## One-time owner setup and migration

Keep the Sheet in legacy URL mode until the compatibility-capable website code
and systemd unit have been installed on the server. Then complete these steps:

1. Sign in with the Google account that owns, or has edit access to, the Sheet.
   Create a **new standalone project** at <https://script.google.com/>. Do not
   create a Sheet-bound script through **Extensions > Apps Script**, and do not
   share the standalone project with Sheet editors.
2. Replace `Code.gs` with the file in this directory. In **Project Settings**,
   enable **Show "appsscript.json" manifest file in editor**, then replace the
   manifest with the included `appsscript.json`.
3. Under **Project Settings > Script Properties**, add:

   - `SPREADSHEET_ID` = `14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM`
   - `API_TOKEN` = a random secret of at least 32 characters; a 64-character
     value from `openssl rand -hex 32` is recommended

4. Select `authorizeOwner` in the editor and run it once. Approve the requested
   Sheets permission and confirm that it returns `ok: true`. This function works
   while the Sheet still has legacy headers.
5. Choose **Deploy > New deployment > Web app** and use:

   - **Execute as:** Me
   - **Who has access:** Anyone

   Deploy and copy the production URL ending in `/exec`, not the editor-only
   `/dev` URL. If the Google Workspace domain does not offer anonymous
   **Anyone** access, this bridge cannot be called by the server as designed;
   an administrator must allow it or a different authenticated bridge is needed.
6. On the server, create `/etc/econai-sheet-publisher.env` without putting either
   secret into the repository:

   ```bash
   sudo touch /etc/econai-sheet-publisher.env
   sudo chown root:root /etc/econai-sheet-publisher.env
   sudo chmod 600 /etc/econai-sheet-publisher.env
   sudoedit /etc/econai-sheet-publisher.env
   ```

   Enter exactly:

   ```dotenv
   ECONAI_SHEET_IMAGE_ENDPOINT=https://script.google.com/macros/s/DEPLOYMENT_ID/exec
   ECONAI_SHEET_IMAGE_TOKEN=replace-with-the-random-secret
   ```

   The system service reads this root-owned file before starting the unprivileged
   publisher. Never commit the deployed endpoint/token pair or put the token in
   a Sheet cell.
7. In every published Research row, replace both legacy URL values with actual
   in-cell images. Replace the two header names with `figure_1_image` and
   `figure_2_image`, and remove the legacy URL headers completely. A poll that
   lands during this short migration may fail, but the atomic publisher keeps
   the last validated release live.
8. Run `validateSetup` from the Apps Script editor. It checks the final headers,
   slug safety, duplicate slugs, both image cells, and alt text without creating
   temporary content URLs. Confirm `image_count` equals twice
   `published_row_count`.
9. Verify the deployed endpoint, then trigger one server refresh and inspect its
   result:

   ```bash
   sudo systemctl start econai-sheet-publisher.service
   systemctl status econai-sheet-publisher.service
   cat /srv/econai-site/state/status.json
   ```

Direct-image mode intentionally fails closed when either server environment
variable is absent, the token is wrong, an expected cell is not a real in-cell
image, or an image cannot be downloaded and validated. A failed staged build
does not replace the live release.

## Verify the endpoint

Read both values interactively so neither secret appears in shell history:

```bash
read -rp 'Image bridge /exec URL: ' ECONAI_SHEET_IMAGE_ENDPOINT
read -rsp 'Image bridge token: ' ECONAI_SHEET_IMAGE_TOKEN
echo
export ECONAI_SHEET_IMAGE_ENDPOINT ECONAI_SHEET_IMAGE_TOKEN
python3 -c 'import json, os; print(json.dumps({"token": os.environ["ECONAI_SHEET_IMAGE_TOKEN"]}))' \
  | curl --fail --silent --show-error --location \
      -H 'Content-Type: application/json' \
      --data-binary @- \
      "$ECONAI_SHEET_IMAGE_ENDPOINT" \
  | python3 -c 'import json, sys; r=json.load(sys.stdin); assert r.get("ok") is True, r; print(json.dumps(r, indent=2))'
unset ECONAI_SHEET_IMAGE_ENDPOINT ECONAI_SHEET_IMAGE_TOKEN
```

A successful response has one flat `images` entry for each of the two figure
cells in every published row:

```json
{
  "ok": true,
  "schema_version": 1,
  "generated_at": "2026-08-04T00:00:00.000Z",
  "sheet": "Research",
  "images": [
    {
      "slug": "llms-for-economic-reasoning-and-research",
      "slot": 1,
      "field": "figure_1_image",
      "alt": "Representative figure description",
      "credit": "Paper authors",
      "cell_alt_title": "",
      "cell_alt_description": "",
      "content_url": "https://..."
    }
  ]
}
```

Google documents that `CellImage.getContentUrl()` returns a requester-tagged URL
that expires after a short period. That is why the server must consume it during
the current staged build and publish only the validated local copy. Apps Script
Content Service also does not let this code choose application HTTP status codes,
so callers must inspect top-level `ok` even when the HTTP request succeeds.

## Security and maintenance

- The web app is anonymously reachable only so the server can call it without a
  Google login. Every useful request still needs the high-entropy token, which
  is compared by digest and is never echoed in a response.
- The request cannot select a spreadsheet, tab, row, or arbitrary URL. The script
  reads only the configured spreadsheet's `Research` tab and exports checked
  rows.
- The manifest requests the full Sheets scope because Google documents that
  `CellImage` alt-text and content-URL getters require it. This code performs no
  writes. Keep the standalone project private so no additional script editor can
  read its Script Properties or modify code running with the deployer's access.
- To rotate the token, update the Apps Script `API_TOKEN` property and the server
  environment file, then start the service. A temporary mismatch only causes a
  failed staged build; it cannot replace the live site.
- When `Code.gs` or `appsscript.json` changes, create a new deployment version (or
  edit the deployment to point to a new version) and retest the production
  `/exec` URL.

Official references: [CellImage](https://developers.google.com/apps-script/reference/spreadsheet/cell-image),
[web apps](https://developers.google.com/apps-script/guides/web),
[web-app manifest fields](https://developers.google.com/apps-script/manifest/web-app-api-executable),
and [Content Service](https://developers.google.com/apps-script/guides/content).
