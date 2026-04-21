import clsx from 'clsx';
import type { ReactNode, HTMLAttributes } from 'react';

interface Props extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'elevated';
  children: ReactNode;
}

export function GlassCard({ variant = 'default', className, children, ...rest }: Props) {
  return (
    <div
      {...rest}
      className={clsx(
        'rounded-2xl border backdrop-blur-glass',
        variant === 'default' && 'border-glass-soft bg-white/[0.03] shadow-glass-ambient',
        variant === 'elevated' && 'border-glass-strong bg-white/[0.05] shadow-glass-elevated',
        className
      )}
    >
      {children}
    </div>
  );
}
