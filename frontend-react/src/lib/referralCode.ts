/**
 * Utilitaire pour gérer le code de parrainage côté client.
 *
 * Flow :
 * 1. Visiteur arrive avec ?ref=CODE → on store dans localStorage avec expiry 30j
 * 2. Au signup, on lit le code stocké et on l'envoie au backend
 * 3. Le backend track_signup() enregistre le parrainage
 */

const STORAGE_KEY = 'scalping_radar_ref_code';
const EXPIRY_DAYS = 30;

interface StoredRef {
  code: string;
  expires_at: number; // ms timestamp
}

/**
 * Capture le code de parrainage depuis l'URL query string.
 * À appeler au mount de la LandingPage et autres pages publiques.
 */
export function captureRefCodeFromUrl(): void {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams(window.location.search);
  const code = params.get('ref');
  if (!code) return;

  const expires_at = Date.now() + EXPIRY_DAYS * 24 * 60 * 60 * 1000;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ code: code.toUpperCase(), expires_at }));
  } catch {
    // localStorage indisponible (private mode strict, etc.)
  }
}

/**
 * Lit le code de parrainage stocké, retourne null si absent ou expiré.
 */
export function getStoredRefCode(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredRef;
    if (Date.now() > parsed.expires_at) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed.code;
  } catch {
    return null;
  }
}

export function clearRefCode(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
