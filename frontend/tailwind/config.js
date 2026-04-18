/**
 * Config Tailwind v3 pour Scalping Radar.
 *
 * Usage : compilée à l'étape Docker `node:20-alpine` via tailwind CLI.
 * Le résultat (frontend/css/tailwind.css, purgé) est copié dans l'image
 * Python finale et servi par FastAPI.
 *
 * Tokens alignés sur la palette existante pour que les drops 21st.dev
 * (bg-card, text-foreground, border-border, etc.) matchent le thème
 * "Trading Desk haute densité" sans surprise visuelle.
 */
module.exports = {
    // Liste des fichiers scannés pour trouver les classes utilisées.
    // Sans ça, Tailwind ne purge pas et sort 3 MB de CSS.
    content: [
        './frontend/**/*.html',
        './frontend/**/*.js',
    ],
    // Préserve les CSS existants : on ne veut pas que Tailwind réinitialise
    // h1, button, input, etc. (notre style.css le fait déjà à sa sauce).
    corePlugins: {
        preflight: false,
    },
    theme: {
        extend: {
            colors: {
                // Tokens sémantiques façon shadcn, pour que les composants
                // 21st.dev fonctionnent out-of-the-box.
                background: '#0a0e14',
                foreground: '#e6edf3',
                card: {
                    DEFAULT: '#161c28',
                    foreground: '#e6edf3',
                },
                popover: {
                    DEFAULT: '#161c28',
                    foreground: '#e6edf3',
                },
                primary: {
                    DEFAULT: '#58a6ff',
                    foreground: '#0a0e14',
                },
                secondary: {
                    DEFAULT: '#1e2636',
                    foreground: '#e6edf3',
                },
                muted: {
                    DEFAULT: '#1e2636',
                    foreground: '#8b949e',
                },
                accent: {
                    DEFAULT: '#1e2636',
                    foreground: '#e6edf3',
                },
                destructive: {
                    DEFAULT: '#f85149',
                    foreground: '#ffffff',
                },
                border: '#1e2636',
                input: '#1e2636',
                ring: '#58a6ff',
                // Tokens maison (identiques à --accent-buy / --accent-sell
                // dans style.css)
                buy: '#00ffa3',
                sell: '#ff4976',
            },
            borderRadius: {
                lg: '0.625rem',
                md: '0.5rem',
                sm: '0.375rem',
            },
            fontFamily: {
                sans: ['-apple-system', 'BlinkMacSystemFont', 'Inter', 'Segoe UI', 'Helvetica', 'Arial', 'sans-serif'],
                mono: ['JetBrains Mono', 'ui-monospace', 'SF Mono', 'Cascadia Code', 'Consolas', 'monospace'],
            },
        },
    },
    plugins: [],
};
