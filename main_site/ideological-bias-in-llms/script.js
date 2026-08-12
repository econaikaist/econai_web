import { announce, initCitationCopy } from './modules/citation.v2.js';

initCitationCopy();

import('./modules/paper-explorer.v2.js?v=20260812a')
    .then(({ initPaperExplorer }) => initPaperExplorer({ announce }))
    .catch((error) => {
        console.error('Paper explorer could not be initialized.', error);
        announce('Interactive model details are temporarily unavailable.');
    });
