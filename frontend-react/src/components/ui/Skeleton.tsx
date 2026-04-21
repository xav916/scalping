import clsx from 'clsx';

interface Props {
  className?: string;
}

export function Skeleton({ className }: Props) {
  return (
    <div
      className={clsx(
        'animate-pulse-slow rounded-lg bg-white/[0.04] border border-glass-soft',
        className
      )}
    />
  );
}
