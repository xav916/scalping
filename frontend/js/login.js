/**
 * Handler du formulaire de login.
 * Externalisé depuis login.html pour respecter la CSP stricte (script-src 'self').
 */
(function () {
    const form = document.getElementById('login-form');
    const submitBtn = document.getElementById('submit');
    const submitLabel = document.getElementById('submit-label');
    const submitSpinner = document.getElementById('submit-spinner');
    const errorEl = document.getElementById('error');
    const errorMsg = document.getElementById('error-msg');

    const setLoading = (loading) => {
        submitBtn.disabled = loading;
        submitLabel.textContent = loading ? 'Connexion…' : 'Se connecter';
        submitSpinner.hidden = !loading;
    };

    const showError = (text) => {
        errorMsg.textContent = text;
        errorEl.hidden = false;
    };

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.hidden = true;
        const username = document.getElementById('username').value.trim();
        const password = document.getElementById('password').value;
        if (!username || !password) {
            showError('Veuillez remplir les deux champs.');
            return;
        }
        setLoading(true);
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ username, password }),
            });
            if (res.ok) {
                const next = new URLSearchParams(window.location.search).get('next') || '/';
                window.location.replace(next);
                return;
            }
            const body = await res.json().catch(() => ({}));
            showError(body.detail || 'Identifiants incorrects.');
        } catch (err) {
            showError('Erreur réseau : ' + err.message);
        } finally {
            setLoading(false);
        }
    });
})();
