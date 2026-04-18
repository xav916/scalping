/**
 * Handler du formulaire de login.
 * Externalisé depuis login.html pour respecter la CSP stricte (script-src 'self').
 */
(function () {
    const form = document.getElementById('login-form');
    const submitBtn = document.getElementById('submit');
    const errorEl = document.getElementById('error');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.hidden = true;
        submitBtn.disabled = true;
        const originalLabel = submitBtn.textContent;
        submitBtn.textContent = 'Connexion…';

        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value,
                }),
            });
            if (res.ok) {
                const next = new URLSearchParams(window.location.search).get('next') || '/';
                window.location.replace(next);
                return;
            }
            const body = await res.json().catch(() => ({}));
            errorEl.textContent = body.detail || 'Identifiants incorrects';
            errorEl.hidden = false;
        } catch (err) {
            errorEl.textContent = 'Erreur réseau : ' + err.message;
            errorEl.hidden = false;
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalLabel;
        }
    });
})();
