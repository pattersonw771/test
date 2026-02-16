(function () {
    const form = document.getElementById('analyze-form');
    const button = document.getElementById('analyze-button');

    if (form && button) {
        form.addEventListener('submit', function () {
            button.disabled = true;
            button.textContent = 'Analyzing...';
        });
    }

    const fills = document.querySelectorAll('.fill');
    fills.forEach(function (bar, idx) {
        const raw = bar.getAttribute('data-width');
        const value = Number(raw);
        if (!Number.isFinite(value)) {
            return;
        }
        const clamped = Math.max(0, Math.min(100, value));
        window.setTimeout(function () {
            bar.style.width = clamped + '%';
        }, 100 + idx * 120);
    });

    const reveals = document.querySelectorAll('.reveal');
    reveals.forEach(function (el, idx) {
        window.setTimeout(function () {
            el.classList.add('is-visible');
        }, 120 + idx * 110);
    });

    const THEME_KEY = 'equilens-theme';
    const supportedThemes = ['theme-newsroom', 'theme-city', 'theme-monochrome', 'theme-dark'];
    const themeButtons = document.querySelectorAll('[data-theme-btn]');

    function applyTheme(themeName) {
        const theme = supportedThemes.includes(themeName) ? themeName : 'theme-newsroom';

        supportedThemes.forEach(function (className) {
            document.body.classList.remove(className);
        });
        document.body.classList.add(theme);

        themeButtons.forEach(function (chip) {
            const isActive = chip.getAttribute('data-theme-btn') === theme;
            chip.classList.toggle('is-active', isActive);
            chip.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        try {
            window.localStorage.setItem(THEME_KEY, theme);
        } catch (e) {
            // ignore storage failures
        }
    }

    let startingTheme = 'theme-newsroom';
    try {
        const savedTheme = window.localStorage.getItem(THEME_KEY);
        if (savedTheme) {
            startingTheme = savedTheme;
        }
    } catch (e) {
        // ignore storage failures
    }

    applyTheme(startingTheme);

    themeButtons.forEach(function (chip) {
        chip.addEventListener('click', function () {
            const requestedTheme = chip.getAttribute('data-theme-btn');
            applyTheme(requestedTheme);
        });
    });
})();

