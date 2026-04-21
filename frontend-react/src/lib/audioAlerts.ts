/** Bip audio généré via Web Audio API — aucune dépendance, aucun asset.
 *  Pattern : deux tons rapides rising (cyan → magenta en fréquences) signalant
 *  un nouveau setup TAKE. Volume faible, ~350 ms total.
 *
 *  Web Audio nécessite une interaction user avant de jouer du son (policy
 *  moderne navigateurs). Le premier clic sur le toggle "sound on" fait office
 *  d'unlock : l'AudioContext est créé dans le handler click, puis réutilisé.
 */

let ctx: AudioContext | null = null;

function getContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (ctx) return ctx;
  const Ctor =
    (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext })
      .AudioContext ??
    (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!Ctor) return null;
  ctx = new Ctor();
  return ctx;
}

/** Crée le contexte audio suite à une interaction utilisateur.
 *  À appeler dans un event handler click pour bypasser l'autoplay policy. */
export function unlockAudio(): void {
  const c = getContext();
  if (c && c.state === 'suspended') {
    c.resume().catch(() => undefined);
  }
}

/** Joue un bip court à deux tons (rising), environ 350 ms. */
export function playTakeAlert(): void {
  const c = getContext();
  if (!c) return;
  if (c.state === 'suspended') {
    c.resume().catch(() => undefined);
  }
  const now = c.currentTime;
  playTone(c, now, 520, 0.12);
  playTone(c, now + 0.14, 780, 0.18);
}

function playTone(c: AudioContext, startAt: number, freq: number, duration: number): void {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  // enveloppe : fade-in rapide, sustain court, fade-out doux — évite le clic
  gain.gain.setValueAtTime(0, startAt);
  gain.gain.linearRampToValueAtTime(0.08, startAt + 0.02);
  gain.gain.linearRampToValueAtTime(0, startAt + duration);
  osc.connect(gain).connect(c.destination);
  osc.start(startAt);
  osc.stop(startAt + duration + 0.02);
}
