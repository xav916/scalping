import clsx from 'clsx';
import { motion } from 'motion/react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';

/** Bottom tab bar mobile (fixed en bas, glass, toujours accessible au pouce).
 *  Cachée sur sm+ (desktop utilise la nav dans le Header).
 *
 *  Active indicator : pill animé AUTOUR de l'icône (layoutId partagé)
 *  -- résout l'alignement visuel quand les icônes ont un center-of-mass
 *  décalé dans leur viewBox.
 *
 *  Items admin (Admin / Infra / V1) ajoutés conditionnellement si
 *  whoami.is_admin -- pour parité avec la navbar desktop Header.tsx.
 */
const NAV_ITEMS = [
  { to: '/cockpit', label: 'Cockpit', icon: CockpitIcon, admin: false },
  { to: '/candidates', label: 'Candidats', icon: CandidatesIcon, admin: false },
  { to: '/settings', label: 'Réglages', icon: SettingsIcon, admin: false },
];

const ADMIN_NAV_ITEMS = [
  { to: '/admin', label: 'Admin', icon: AdminIcon, admin: true },
  { to: '/control-tower', label: 'Infra', icon: InfraIcon, admin: true },
  { to: '/v1', label: 'V1', icon: V1Icon, admin: true },
];

export function MobileBottomNav() {
  const location = useLocation();
  const { whoami } = useAuth();
  const isAdmin = whoami.data?.is_admin ?? false;
  const items = isAdmin ? [...NAV_ITEMS, ...ADMIN_NAV_ITEMS] : NAV_ITEMS;
  const gridColsClass = items.length === 2 ? 'grid-cols-2' : 'grid-cols-5';

  return (
    <nav
      aria-label="Navigation principale"
      className={clsx(
        'sm:hidden fixed bottom-0 left-0 right-0 z-40',
        'border-t border-glass-soft backdrop-blur-glass bg-radar-deep/92',
        'pb-[env(safe-area-inset-bottom,0px)]'
      )}
    >
      <div className={clsx('grid', gridColsClass)}>
        {items.map((item) => {
          const active = location.pathname === item.to;
          const Icon = item.icon;
          // Items admin : accent amber pour distinguer du flux user normal
          const accentColor = item.admin
            ? (active ? 'text-amber-300' : 'text-white/55 active:text-white/90')
            : (active ? 'text-cyan-300' : 'text-white/55 active:text-white/90');
          const pillBg = item.admin
            ? 'bg-gradient-to-b from-amber-400/15 to-amber-400/5'
            : 'bg-gradient-to-b from-cyan-400/15 to-cyan-400/5';
          const pillBorder = item.admin
            ? 'border border-amber-400/40 shadow-[0_0_16px_rgba(251,191,36,0.18)]'
            : 'border border-cyan-400/40 shadow-[0_0_16px_rgba(34,211,238,0.18)]';
          return (
            <Link
              key={item.to}
              to={item.to}
              className={clsx(
                'relative flex flex-col items-center justify-center gap-1 pt-2 pb-2 transition-colors',
                accentColor
              )}
              aria-current={active ? 'page' : undefined}
            >
              <motion.span
                className="relative inline-flex items-center justify-center w-11 h-7 rounded-full"
                whileTap={{ scale: 0.92 }}
                transition={{ type: 'spring', stiffness: 500, damping: 28 }}
              >
                {active && (
                  <motion.span
                    layoutId="mobile-nav-active-pill"
                    aria-hidden
                    className={clsx('absolute inset-0 rounded-full', pillBg, pillBorder)}
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
/* Taille uniforme 22x22, `relative z-10` pour rester au-dessus du pill. */

type IconProps = { active?: boolean };

function iconClass(active?: boolean): string {
  return clsx(
    'relative z-10 w-[22px] h-[22px] transition-transform',
    active && 'scale-110'
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

function CandidatesIcon({ active }: IconProps) {
  // Eye icon -- Candidats = supports en observation shadow log
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
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function AdminIcon({ active }: IconProps) {
  // Shield icon -- Admin = controle d'acces
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
      <path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

function InfraIcon({ active }: IconProps) {
  // Server stack icon -- Infra / Control Tower
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
      <rect x="3" y="4" width="18" height="6" rx="1.5" />
      <rect x="3" y="14" width="18" height="6" rx="1.5" />
      <circle cx="7" cy="7" r="0.6" fill="currentColor" />
      <circle cx="7" cy="17" r="0.6" fill="currentColor" />
    </svg>
  );
}

function SettingsIcon({ active }: IconProps) {
  // Gear icon — Réglages (paires + niveau de confiance + EA)
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
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function V1Icon({ active }: IconProps) {
  // Archive box icon -- V1 = ancien hub legacy
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
      <rect x="3" y="4" width="18" height="5" rx="1" />
      <path d="M5 9v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
}
