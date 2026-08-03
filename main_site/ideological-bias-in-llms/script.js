(function () {
    const status = document.querySelector('.copy-status');
    const copyButtons = document.querySelectorAll('.copy-trigger');
    let statusTimer;

    function announce(message) {
        if (!status) return;
        status.textContent = message;
        status.classList.add('visible');
        window.clearTimeout(statusTimer);
        statusTimer = window.setTimeout(function () {
            status.classList.remove('visible');
        }, 2200);
    }

    async function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return;
        }

        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.setAttribute('readonly', '');
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        const copied = document.execCommand('copy');
        textArea.remove();
        if (!copied) throw new Error('Copy failed');
    }

    copyButtons.forEach(function (button) {
        button.addEventListener('click', async function () {
            const target = document.getElementById(button.dataset.copyTarget);
            const label = button.querySelector('span');
            const defaultLabel = button.dataset.defaultLabel || 'Copy';
            if (!target) return;

            try {
                await copyText(target.textContent.trim());
                if (label) label.textContent = 'Copied';
                announce('Citation copied to clipboard');
                window.setTimeout(function () {
                    if (label) label.textContent = defaultLabel;
                }, 1800);
            } catch (error) {
                announce('Could not copy automatically');
            }
        });
    });
})();
