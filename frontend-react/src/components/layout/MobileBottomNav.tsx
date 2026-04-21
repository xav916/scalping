import clsx from 'clsx';
import { motion } from 'motion/react';
import { Link, useLocation } from 'react-router-dom';

/** Bottom tab bar mobile (fixed en bas, glass, toujours accessible au pouce).
 *  Cachée sur sm+ (desktop utilise la nav dans le Header). */
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
        'border-t border-glass-soft backdrop-blur-glass bg-radar-deep/90',
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
                'relative flex flex-col items-center justify-center gap-0.5 py-2.5 transition-colors',
                active ? 'text-cyan-300' : 'text-white/50 hover:text-white/80'
              )}
              aria-current={active ? 'page' : undefined}
            >
              {active && (
                <motion.span
                  layoutId="mobile-nav-active"
                  className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-[2px] rounded-full bg-gradient-to-r from-cyan-400 to-pink-400"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
              <Icon active={active} />
              <span className={clsx('text-[10px] font-semibold tracking-wider', active && 'font-bold')}>
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

type IconProps = { active?: boolean };

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
      className="w-5 h-5"
    >
      <path d="M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z" />
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
      className="w-5 h-5"
    >
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
    </svg>
  );
}

function AnalyticsIcon({ active }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-5 h-5"
    >
      <path d="M3 3v18h18" />
      <path d="M7 14l3-3 4 4 5-5" />
    </svg>
  );
}

function TradesIcon({ active }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="w-5 h-5"
    >
      <path d="M8 6h13M8 12h13M8 18h13" />
      <circle cx="4" cy="6" r="1.2" />
      <circle cx="4" cy="12" r="1.2" />
      <circle cx="4" cy="18" r="1.2" />
    </svg>
  );
}
