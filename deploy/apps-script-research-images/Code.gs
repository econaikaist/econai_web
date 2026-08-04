/**
 * Private, standalone Apps Script web app for exporting Research cell images.
 *
 * Required Script Properties:
 *   SPREADSHEET_ID - source Google Spreadsheet ID
 *   API_TOKEN      - random secret with at least 32 characters
 *
 * Deploy this script as a web app that executes as its deployer. The script is
 * deliberately standalone (not bound to the Sheet), so Sheet editors do not
 * receive access to this source or its Script Properties.
 */

const CONFIG = Object.freeze({
  sheetName: 'Research',
  minimumTokenLength: 32,
  slugPattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
  requiredHeaders: Object.freeze([
    'publish',
    'slug',
    'figure_1_image',
    'figure_1_alt',
    'figure_1_credit',
    'figure_2_image',
    'figure_2_alt',
    'figure_2_credit',
  ]),
  figureSlots: Object.freeze([
    Object.freeze({
      slot: 1,
      imageHeader: 'figure_1_image',
      altHeader: 'figure_1_alt',
      creditHeader: 'figure_1_credit',
    }),
    Object.freeze({
      slot: 2,
      imageHeader: 'figure_2_image',
      altHeader: 'figure_2_alt',
      creditHeader: 'figure_2_credit',
    }),
  ]),
});

/**
 * POST JSON body: {"token":"<API_TOKEN>"}
 *
 * ContentService does not expose response status controls, so callers must
 * inspect the top-level `ok` value instead of relying only on HTTP status.
 */
function doPost(event) {
  try {
    const request = parseRequest_(event);
    authenticate_(request.token);

    return jsonOutput_({
      ok: true,
      schema_version: 1,
      generated_at: new Date().toISOString(),
      sheet: CONFIG.sheetName,
      images: scanResearchImages_(true).images,
    });
  } catch (error) {
    return jsonOutput_({
      ok: false,
      error: {
        code: error.apiCode || 'INTERNAL_ERROR',
        message: error.apiCode ? error.message : 'Unexpected server error.',
      },
    });
  }
}

/**
 * Run once from the Apps Script editor before changing the legacy Sheet
 * headers. This triggers owner authorization without requiring the final
 * direct-image schema to be present yet.
 */
function authorizeOwner() {
  const properties = getRequiredProperties_();
  const spreadsheet = SpreadsheetApp.openById(properties.spreadsheetId);
  const sheet = spreadsheet.getSheetByName(CONFIG.sheetName);
  if (!sheet) {
    fail_('SHEET_NOT_FOUND', 'Research sheet not found.');
  }

  return {
    ok: true,
    spreadsheet: spreadsheet.getName(),
    sheet: CONFIG.sheetName,
  };
}

/**
 * Run after the Sheet uses the final figure_*_image headers. This validates all
 * published image cells and alt text without minting temporary content URLs.
 */
function validateSetup() {
  const result = scanResearchImages_(false);
  return {
    ok: true,
    sheet: CONFIG.sheetName,
    published_row_count: result.publishedRowCount,
    image_count: result.images.length,
    required_headers: CONFIG.requiredHeaders.slice(),
  };
}

function parseRequest_(event) {
  if (!event || !event.postData || !event.postData.contents) {
    fail_('BAD_REQUEST', 'A JSON POST body is required.');
  }

  let parsed;
  try {
    parsed = JSON.parse(event.postData.contents);
  } catch (error) {
    fail_('BAD_REQUEST', 'The POST body must be valid JSON.');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    fail_('BAD_REQUEST', 'The POST body must be a JSON object.');
  }
  if (typeof parsed.token !== 'string' || parsed.token.length === 0) {
    fail_('UNAUTHORIZED', 'Invalid token.');
  }
  return parsed;
}

function authenticate_(providedToken) {
  const properties = getRequiredProperties_();
  if (!constantTimeEquals_(providedToken, properties.apiToken)) {
    fail_('UNAUTHORIZED', 'Invalid token.');
  }
}

function getRequiredProperties_() {
  const properties = PropertiesService.getScriptProperties();
  const spreadsheetId = normalizeText_(properties.getProperty('SPREADSHEET_ID'));
  const apiToken = properties.getProperty('API_TOKEN') || '';

  if (!spreadsheetId) {
    fail_('CONFIG_ERROR', 'SPREADSHEET_ID is not configured.');
  }
  if (apiToken.length < CONFIG.minimumTokenLength) {
    fail_('CONFIG_ERROR', 'API_TOKEN must contain at least 32 characters.');
  }
  return {spreadsheetId: spreadsheetId, apiToken: apiToken};
}

function constantTimeEquals_(left, right) {
  const leftDigest = Utilities.computeDigest(
      Utilities.DigestAlgorithm.SHA_256,
      String(left),
      Utilities.Charset.UTF_8,
  );
  const rightDigest = Utilities.computeDigest(
      Utilities.DigestAlgorithm.SHA_256,
      String(right),
      Utilities.Charset.UTF_8,
  );

  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest[index] ^ rightDigest[index];
  }
  return difference === 0;
}

function scanResearchImages_(includeContentUrls) {
  const properties = getRequiredProperties_();
  const spreadsheet = SpreadsheetApp.openById(properties.spreadsheetId);
  const sheet = spreadsheet.getSheetByName(CONFIG.sheetName);
  if (!sheet) {
    fail_('SHEET_NOT_FOUND', 'Research sheet not found.');
  }

  const values = sheet.getDataRange().getValues();
  if (values.length === 0) {
    fail_('EMPTY_SHEET', 'Research sheet has no header row.');
  }
  const indexes = buildHeaderIndexes_(values[0]);
  const seenSlugs = {};
  const images = [];
  let publishedRowCount = 0;

  for (let rowIndex = 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex];
    if (!isPublished_(row[indexes.publish])) {
      continue;
    }
    publishedRowCount += 1;

    const sheetRow = rowIndex + 1;
    const slug = normalizeText_(row[indexes.slug]);
    if (!slug) {
      fail_('INVALID_ROW', 'Research row ' + sheetRow + ' has no slug.');
    }
    if (!CONFIG.slugPattern.test(slug)) {
      fail_(
          'INVALID_SLUG',
          'Research row ' + sheetRow + ' slug must contain only lowercase ' +
              'letters, numbers, and single hyphens.',
      );
    }
    if (seenSlugs[slug]) {
      fail_(
          'DUPLICATE_SLUG',
          'Research slug "' + slug + '" is duplicated on rows ' +
              seenSlugs[slug] + ' and ' + sheetRow + '.',
      );
    }
    seenSlugs[slug] = sheetRow;

    CONFIG.figureSlots.forEach(function(slotConfig) {
      const imageValue = row[indexes[slotConfig.imageHeader]];
      if (isBlank_(imageValue)) {
        fail_(
            'MISSING_IMAGE',
            'Research row ' + sheetRow + ' column ' +
                slotConfig.imageHeader + ' needs an in-cell image.',
        );
      }
      if (!imageValue || imageValue.valueType !== SpreadsheetApp.ValueType.IMAGE) {
        fail_(
            'INVALID_IMAGE',
            'Research row ' + sheetRow + ' column ' +
                slotConfig.imageHeader + ' must contain an in-cell image.',
        );
      }

      const cellAltTitle = normalizeText_(imageValue.getAltTextTitle());
      const cellAltDescription = normalizeText_(
          imageValue.getAltTextDescription(),
      );
      const configuredAlt = normalizeText_(row[indexes[slotConfig.altHeader]]);
      const alt = configuredAlt || cellAltDescription || cellAltTitle;
      if (!alt) {
        fail_(
            'MISSING_ALT',
            'Research row ' + sheetRow + ' column ' +
                slotConfig.imageHeader + ' needs alt text.',
        );
      }

      const image = {
        slug: slug,
        slot: slotConfig.slot,
        field: slotConfig.imageHeader,
        alt: alt,
        credit: normalizeText_(row[indexes[slotConfig.creditHeader]]),
        cell_alt_title: cellAltTitle,
        cell_alt_description: cellAltDescription,
      };

      if (includeContentUrls) {
        const contentUrl = normalizeText_(imageValue.getContentUrl());
        if (!/^https:\/\//i.test(contentUrl)) {
          fail_(
              'INVALID_CONTENT_URL',
              'Google did not return an HTTPS content URL for Research row ' +
                  sheetRow + ' column ' + slotConfig.imageHeader + '.',
          );
        }
        image.content_url = contentUrl;
      }
      images.push(image);
    });
  }

  return {
    publishedRowCount: publishedRowCount,
    images: images,
  };
}

function buildHeaderIndexes_(headerRow) {
  const allIndexes = {};
  headerRow.forEach(function(value, index) {
    const header = normalizeText_(value);
    if (!header) {
      return;
    }
    if (Object.prototype.hasOwnProperty.call(allIndexes, header)) {
      fail_('DUPLICATE_HEADER', 'Duplicate Research header: ' + header + '.');
    }
    allIndexes[header] = index;
  });

  const requiredIndexes = {};
  CONFIG.requiredHeaders.forEach(function(header) {
    if (!Object.prototype.hasOwnProperty.call(allIndexes, header)) {
      fail_('MISSING_HEADER', 'Missing Research header: ' + header + '.');
    }
    requiredIndexes[header] = allIndexes[header];
  });
  return requiredIndexes;
}

function isPublished_(value) {
  if (value === true) {
    return true;
  }
  if (typeof value === 'number') {
    return value === 1;
  }
  return /^(true|yes|1)$/i.test(normalizeText_(value));
}

function isBlank_(value) {
  return value === null || value === undefined || value === '';
}

function normalizeText_(value) {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value).trim();
}

function fail_(code, message) {
  const error = new Error(message);
  error.apiCode = code;
  throw error;
}

function jsonOutput_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
      .setMimeType(ContentService.MimeType.JSON);
}
