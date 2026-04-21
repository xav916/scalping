import { useState } from 'react';
import clsx from 'clsx';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { KillSwitchModal } from '@/components/cockpit/KillSwitchModal';
import { StatusDot } from '@/components/cockpit/StatusDot';
import { useKillSwitch } from '@/hooks/useCockpit';
import { TIPS } from '@/lib/metricTips';

/** Carte "coupe-circuit" : affiche l'état actif/OK, permet toggle manuel via
 *  modal avec raison. Mutation invalide la query cockpit pour rafraîchir. */
export function KillSwitchCard({
  active,
  reason,
}: {
  active: boolean;
  reason: string | null;
}) {
  const { query, mutation } = useKillSwitch();
  const [modalOpen, setModalOpen] = useState(false);
  const manualEnabled = query.data?.manual_enabled ?? false;

  const handleClick = () => {
    if (manualEnabled) {
      mutation.mutate({ enabled: false });
    } else {
      setModalOpen(true);
    }
  };

  return (
    <>
      <GlassCard
        variant="elevated"
        className={clsx(
          'p-5 min-w-[240px] flex flex-col gap-3 transition-all',
          active ? 'border-rose-400/40 shadow-[0_0_24px_rgba(244,63,94,0.2)]' : 'border-glass-soft'
        )}
      >
        <div className="flex items-center justify-between">
          <LabelWithInfo
            label={<h3 className="text-xs font-bold uppercase tracking-[0.2em] text-white/60">Kill switch</h3>}
            tip={TIPS.killSwitch.title}
          />
          <Tooltip content={active ? TIPS.killSwitch.active : TIPS.killSwitch.okState}>
            <StatusDot active={active} />
          </Tooltip>
        </div>
        <div>
          <Tooltip content={active ? TIPS.killSwitch.active : TIPS.killSwitch.okState}>
            <div className={clsx('text-2xl font-bold tabular-nums', active ? 'text-rose-300' : 'text-emerald-300')}>
              {active ? 'ACTIF' : 'OK'}
            </div>
          </Tooltip>
          {reason && <p className="text-[11px] text-white/50 mt-1 leading-snug">{reason}</p>}
        </div>
        <Tooltip content={TIPS.killSwitch.manualToggle}>
          <button
            type="button"
            onClick={handleClick}
            disabled={mutation.isPending}
            className={clsx(
              'w-full text-xs px-3 py-2 rounded-lg border transition-all font-semibold uppercase tracking-wider',
              manualEnabled
                ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/20'
                : 'border-rose-400/40 bg-rose-400/10 text-rose-300 hover:bg-rose-400/20',
              mutation.isPending && 'opacity-40 cursor-wait'
            )}
          >
            {manualEnabled ? 'Réactiver auto-exec' : 'Geler auto-exec'}
          </button>
        </Tooltip>
      </GlassCard>
      <KillSwitchModal
        open={modalOpen}
        onConfirm={(r) => {
          mutation.mutate({ enabled: true, reason: r });
          setModalOpen(false);
        }}
        onCancel={() => setModalOpen(false)}
      />
    </>
  );
}
