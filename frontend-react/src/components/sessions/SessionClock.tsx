import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { TIPS } from '@/lib/metricTips';

const SESSION_TIPS: Record<string, string> = {
  SYD: TIPS.session.syd,
  TKY: TIPS.session.tky,
  LDN: TIPS.session.ldn,
  NY: TIPS.session.ny,
};

type Session = {
  name: string;
  shortName: string;
  openUtcH: number;
  closeUtcH: number;
  color: string;
};

const SESSIONS: Session[] = [
  { name: 'Sydney', shortName: 'SYD', openUtcH: 22, closeUtcH: 7, color: 'from-purple-400 to-pink-400' },
  { name: 'Tokyo', shortName: 'TKY', openUtcH: 0, closeUtcH: 9, color: 'from-rose-400 to-orange-400' },
  { name: 'London', shortName: 'LDN', openUtcH: 8, closeUtcH: 17, color: 'from-emerald-400 to-cyan-400' },
  { name: 'New York', shortName: 'NY', openUtcH: 13, closeUtcH: 22, color: 'from-cyan-400 to-blue-400' },
];

function isSessionActive(s: Session, nowUtcH: number): boolean {
  if (s.openUtcH < s.closeUtcH) {
    return nowUtcH >= s.openUtcH && nowUtcH < s.closeUtcH;
  }
  return nowUtcH >= s.openUtcH || nowUtcH < s.closeUtcH;
}

function isWeekendClosed(now: Date): boolean {
  const utcDay = now.getUTCDay();
  const utcH = now.getUTCHours();
  if (utcDay === 6) return true;
  if (utcDay === 0 && utcH < 22) return true;
  if (utcDay === 5 && utcH >= 22) return true;
  return false;
}

export function SessionClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const nowUtcH = now.getUTCHours() + now.getUTCMinutes() / 60;
  const weekendClosed = isWeekendClosed(now);

  const active = SESSIONS.filter((s) => !weekendClosed && isSessionActive(s, nowUtcH));

  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Sessions forex</h3>
        {weekendClosed && (
          <Tooltip content={TIPS.session.weekend}>
            <span className="text-[9px] font-bold uppercase tracking-wider text-rose-300 bg-rose-400/10 border border-rose-400/30 px-2 py-0.5 rounded-md cursor-help">
              Weekend
            </span>
          </Tooltip>
        )}
      </div>

      <div className="space-y-2.5">
        {SESSIONS.map((s) => {
          const isOn = !weekendClosed && isSessionActive(s, nowUtcH);
          return (
            <Tooltip key={s.name} content={SESSION_TIPS[s.shortName] ?? `${s.name} session`}>
              <div className="w-full flex items-center gap-3 cursor-help">
                <div className="w-12 flex items-center gap-1.5">
                  {isOn && (
                    <motion.span
                      className="w-1.5 h-1.5 rounded-full bg-emerald-400"
                      animate={{ opacity: [0.4, 1, 0.4] }}
                      transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                    />
                  )}
                  <span
                    className={clsx(
                      'text-[10px] font-mono font-bold uppercase tracking-wider',
                      isOn ? 'text-white' : 'text-white/30'
                    )}
                  >
                    {s.shortName}
                  </span>
                </div>
                <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden relative">
                  {isOn && (
                    <motion.div
                      className={clsx('absolute inset-0 rounded-full bg-gradient-to-r', s.color)}
                      initial={{ width: 0 }}
                      animate={{ width: '100%' }}
                      transition={{ duration: 0.6, ease: 'easeOut' }}
                    />
                  )}
                </div>
                <span
                  className={clsx(
                    'text-[10px] font-mono tabular-nums',
                    isOn ? 'text-white/70' : 'text-white/25'
                  )}
                >
                  {String(s.openUtcH).padStart(2, '0')}-{String(s.closeUtcH).padStart(2, '0')}
                </span>
              </div>
            </Tooltip>
          );
        })}
      </div>

      <div className="mt-4 pt-3 border-t border-glass-soft flex items-center justify-between text-[10px] uppercase tracking-wider text-white/40">
        <LabelWithInfo label="Actives" tip={TIPS.session.active} />
        <span className="font-mono text-white/70">
          {weekendClosed ? '—' : active.length > 0 ? active.map((s) => s.shortName).join(' · ') : 'aucune'}
        </span>
      </div>
    </GlassCard>
  );
}
