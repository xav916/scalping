import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import clsx from 'clsx';
import { useAudioAlerts } from '@/hooks/useAudioAlerts';
import { useKillSwitch } from '@/hooks/useCockpit';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/components/ui/Toast';

interface Command {
  id: string;
  label: string;
  hint?: string;
  group: 'Navigation' | 'Actions' | 'Système';
  icon?: string;
  keywords?: string[];
  run: () => void;
}

/** Palette de commandes (⌘K / Ctrl+K) : navigation rapide + actions système.
 *  Ouvre un overlay fullscreen avec search + liste filtrée + navigation clavier. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const navigate = useNavigate();
  const audio = useAudioAlerts();
  const killSwitch = useKillSwitch();
  const { logout } = useAuth();
  const toast = useToast();

  const commands: Command[] = useMemo(() => {
    const ksActive = killSwitch.query.data?.manual_enabled ?? false;
    return [
      // Navigation
      {
        id: 'nav-dashboard',
        label: 'Aller au Dashboard',
        hint: '/v2/',
        group: 'Navigation',
        icon: '▣',
        keywords: ['home', 'accueil'],
        run: () => navigate('/'),
      },
      {
        id: 'nav-cockpit',
        label: 'Aller au Cockpit',
        hint: '/v2/cockpit',
        group: 'Navigation',
        icon: '◎',
        keywords: ['tour de contrôle', 'control'],
        run: () => navigate('/cockpit'),
      },
      {
        id: 'nav-analytics',
        label: 'Aller à Analytics',
        hint: '/v2/analytics',
        group: 'Navigation',
        icon: '▤',
        keywords: ['stats', 'win rate', 'performance'],
        run: () => navigate('/analytics'),
      },
      {
        id: 'nav-trades',
        label: 'Aller aux Trades',
        hint: '/v2/trades',
        group: 'Navigation',
        icon: '≡',
        keywords: ['journal', 'positions'],
        run: () => navigate('/trades'),
      },
      // Actions
      {
        id: 'action-audio-toggle',
        label: audio.enabled ? 'Désactiver le son' : 'Activer le son',
        hint: 'Alertes audio sur nouveau TAKE',
        group: 'Actions',
        icon: audio.enabled ? '🔊' : '🔇',
        keywords: ['bip', 'alert', 'notification'],
        run: () => {
          audio.toggle();
          toast.info(audio.enabled ? 'Son désactivé' : 'Son activé');
        },
      },
      {
        id: 'action-kill-switch',
        label: ksActive ? 'Désactiver le kill switch' : 'Activer le kill switch',
        hint: ksActive ? 'Réactive l\'auto-exec' : 'Gèle l\'auto-exec',
        group: 'Actions',
        icon: ksActive ? '⏵' : '⏸',
        keywords: ['pause', 'gel', 'stop', 'freeze'],
        run: () => {
          killSwitch.mutation.mutate({
            enabled: !ksActive,
            reason: ksActive ? undefined : 'via palette ⌘K',
          });
        },
      },
      // Système
      {
        id: 'system-logout',
        label: 'Logout',
        hint: 'Fin de session',
        group: 'Système',
        icon: '⎋',
        keywords: ['déconnexion', 'exit', 'signout'],
        run: () => {
          logout.mutate(undefined, {
            onSuccess: () => {
              window.location.href = '/v2/login';
            },
          });
        },
      },
      {
        id: 'system-reload',
        label: 'Recharger la page',
        hint: 'Hard refresh (invalide le SW)',
        group: 'Système',
        icon: '⟳',
        keywords: ['refresh', 'reload'],
        run: () => window.location.reload(),
      },
    ];
  }, [navigate, audio, killSwitch, logout, toast]);

  // Filtrage fuzzy simple : match par chaque token dans label + keywords
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    const tokens = q.split(/\s+/);
    return commands.filter((c) => {
      const haystack = [c.label, c.hint ?? '', ...(c.keywords ?? [])].join(' ').toLowerCase();
      return tokens.every((t) => haystack.includes(t));
    });
  }, [commands, query]);

  // Reset sélection quand le filtre change
  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  // Raccourci global ⌘K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]);

  // Focus input à l'ouverture
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Navigation clavier dans la liste
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(filtered.length - 1, i + 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = filtered[selectedIdx];
        if (cmd) {
          cmd.run();
          setOpen(false);
        }
      }
    },
    [filtered, selectedIdx]
  );

  // Scroll l'item sélectionné visible
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${selectedIdx}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  const node = (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-[9998] flex items-start justify-center pt-[15vh] px-4 backdrop-blur-xl bg-radar-deep/70"
        >
          <motion.div
            onClick={(e) => e.stopPropagation()}
            initial={{ scale: 0.96, opacity: 0, y: -8 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.96, opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="w-full max-w-xl rounded-2xl border border-cyan-400/30 bg-[#0d111a]/95 shadow-[0_24px_48px_rgba(0,0,0,0.5)] overflow-hidden"
          >
            {/* Input */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-glass-soft">
              <span className="text-cyan-300 font-mono text-sm">⌘K</span>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Naviguer, agir, chercher…"
                className="flex-1 bg-transparent text-sm text-white placeholder-white/30 focus:outline-none"
                autoComplete="off"
                spellCheck={false}
              />
              <span className="text-[10px] text-white/30 font-mono">Esc</span>
            </div>

            {/* Liste */}
            <div ref={listRef} className="max-h-[50vh] overflow-y-auto py-2">
              {filtered.length === 0 ? (
                <div className="py-10 text-center text-sm text-white/40">
                  Aucune commande ne correspond à "{query}"
                </div>
              ) : (
                groupByGroup(filtered).map(({ group, items, startIdx }) => (
                  <div key={group} className="mb-2 last:mb-0">
                    <div className="px-4 pt-2 pb-1 text-[9px] uppercase tracking-[0.2em] text-white/40 font-mono">
                      {group}
                    </div>
                    {items.map((cmd, i) => {
                      const absIdx = startIdx + i;
                      const isSel = absIdx === selectedIdx;
                      return (
                        <button
                          key={cmd.id}
                          data-idx={absIdx}
                          type="button"
                          onMouseEnter={() => setSelectedIdx(absIdx)}
                          onClick={() => {
                            cmd.run();
                            setOpen(false);
                          }}
                          className={clsx(
                            'w-full flex items-center gap-3 px-4 py-2 text-left transition-colors',
                            isSel
                              ? 'bg-cyan-400/10 text-white'
                              : 'text-white/80 hover:bg-white/[0.03]'
                          )}
                        >
                          {cmd.icon && (
                            <span className={clsx('text-base w-5 text-center', isSel && 'text-cyan-300')}>
                              {cmd.icon}
                            </span>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold truncate">{cmd.label}</div>
                            {cmd.hint && (
                              <div className="text-[11px] text-white/40 truncate">{cmd.hint}</div>
                            )}
                          </div>
                          {isSel && (
                            <span className="text-[9px] text-cyan-300/70 font-mono">⏎</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-4 px-4 py-2 border-t border-glass-soft text-[10px] text-white/40 font-mono">
              <span>↑↓ naviguer</span>
              <span>⏎ exécuter</span>
              <span>Esc fermer</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  if (typeof document === 'undefined') return null;
  return createPortal(node, document.body);
}

function groupByGroup(items: Command[]): Array<{ group: Command['group']; items: Command[]; startIdx: number }> {
  const groups: Record<string, Command[]> = {};
  for (const c of items) {
    if (!groups[c.group]) groups[c.group] = [];
    groups[c.group].push(c);
  }
  const order: Command['group'][] = ['Navigation', 'Actions', 'Système'];
  let cursor = 0;
  const out: Array<{ group: Command['group']; items: Command[]; startIdx: number }> = [];
  for (const g of order) {
    if (groups[g]?.length) {
      out.push({ group: g, items: groups[g], startIdx: cursor });
      cursor += groups[g].length;
    }
  }
  return out;
}
