import clsx from 'clsx';
import type { ReactNode, HTMLAttributes } from 'react';

interface Props extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'accent' | 'buy' | 'sell';
  children: ReactNode;
}

export function GradientText({ variant = 'accent', className, children, ...rest }: Props) {
  const cls =
    variant === 'buy'
      ? 'gradient-buy'
      : variant === 'sell'
      ? 'gradient-sell'
      : 'gradient-accent';
  return (
    <span {...rest} className={clsx(cls, 'font-mono font-semibold', className)}>
      {children}
    </span>
  );
}
