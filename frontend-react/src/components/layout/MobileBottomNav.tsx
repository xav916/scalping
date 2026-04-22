import clsx from 'clsx';
import { motion } from 'motion/react';
import { Link, useLocation } from 'react-router-dom';

/** Bottom tab bar mobile (fixed en bas, glass, toujours accessible au pouce).
 *  Cachée sur sm+ (desktop utilise la nav dans le Header).
 *
 *  Active indicator : pill animé AUTOUR de l'icône (layoutId partagé)
 *  — résout l'alignement visuel quand les icônes ont un center-of-mass
 *  décalé dans leur viewBox (Analytics, Trades).
 */
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: DashboardIcon },
  { to: '/cockpit', label: 'Cockpit', icon: CockpitIcon },
  { to: '/analytics', label: 'Analytics', icon: AnalyticsIcon },
  { to: '/trades', label: 'Trades', icon: TradesIcon },
];

export function MobileBottomNav() {
  const location = useLocation();

  return (
    <nav
      aria-label="Navigation principale"
      className={clsx(
        'sm:hidden fixed bottom-0 left-0 right-0 z-40',
        'border-t border-glass-soft backdrop-blur-glass bg-radar-deep/92',
        'pb-[env(safe-area-inset-bottom,0px)]'
      )}
    >
      <div className="grid grid-cols-4">
        {NAV_ITEMS.map((item) => {
          const active = location.pathname === item.to;
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              className={clsx(
                'relative flex flex-col items-center justify-center gap-1 pt-2 pb-2 transition-colors',
                active ? 'text-cyan-300' : 'text-white/55 active:text-white/90'
              )}
              aria-current={active ? 'page' : undefined}
            >
              {/* Pill wrapper AUTOUR de l'icône : centré par définition sur
                  l'icône, donc pas de décalage visuel quel que soit
                  l'asymétrie interne du SVG. */}
              <motion.span
                className="relative inline-flex items-center justify-center w-11 h-7 rounded-full"
                whileTap={{ scale: 0.92 }}
                transition={{ type: 'spring', stiffness: 500, damping: 28 }}
              >
                {active && (
                  <motion.span
                    layoutId="mobile-nav-active-pill"
                    aria-hidden
                    className={clsx(
                      'absolute inset-0 rounded-full',
                      'bg-gradient-to-b from-cyan-400/15 to-cyan-400/5',
                      'border border-cyan-400/40',
                      'shadow-[0_0_16px_rgba(34,211,238,0.18)]'
                    )}
                    transition={{ type: 'spring', stiffness: 500, damping: 34 }}
                  />
                )}
                <Icon active={active} />
              </motion.span>

              <span
                className={clsx(
                  'text-[10px] leading-none tracking-wider tabular-nums transition-[font-weight,color] duration-150',
                  active ? 'font-bold' : 'font-medium'
                )}
              >
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/* ─────────── Icônes SVG inlines ─────────── */
/* Taille uniforme 22×22, `relative z-10` pour rester au-dessus du pill. */

type IconProps = { active?: boolean };

function iconClass(active?: boolean): string {
  return clsx(
    'relative z-10 w-[22px] h-[22px] transition-transform',
    active && 'scale-110'
  );
}

function DashboardIcon({ active }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={iconClass(active)}
    >
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="11" width="7" height="10" rx="1.5" />
      <rect x="3" y="15" width="7" height="6" rx="1.5" />
    </svg>
  );
}

function CockpitIcon({ active }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={iconClass(active)}
    >
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
    </svg>
  );
}

function AnalyticsIcon({ active }: IconProps) {
  // viewBox rééquilibré : axes symétriques + courbe centrée
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={iconClass(active)}
    >
      <path d="M4 20V4M4 20h16" />
      <path d="M7 15l3-3 3 3 5-5" />
    </svg>
  );
}

function TradesIcon({ active }: IconProps) {
  // Déplacé légèrement vers la gauche pour rééquilibrer le visuel
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={iconClass(active)}
    >
      <circle cx="5" cy="6" r="1.3" />
      <circle cx="5" cy="12" r="1.3" />
      <circle cx="5" cy="18" r="1.3" />
      <path d="M9 6h11M9 12h11M9 18h11" />
    </svg>
  );
}
