import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'motion/react';
import clsx from 'clsx';

export type ToastLevel = 'info' | 'success' | 'warning' | 'error';

interface Toast {
  id: number;
  level: ToastLevel;
  title: string;
  message?: string;
  duration: number;
}

interface ToastApi {
  push: (t: { level?: ToastLevel; title: string; message?: string; duration?: number }) => void;
  info: (title: string, message?: string) => void;
  success: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast doit être utilisé dans <ToastProvider>');
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback<ToastApi['push']>((t) => {
    const id = ++idRef.current;
    const duration = t.duration ?? (t.level === 'error' ? 6000 : 3500);
    const toast: Toast = {
      id,
      level: t.level ?? 'info',
      title: t.title,
      message: t.message,
      duration,
    };
    setToasts((prev) => [...prev, toast]);
    if (duration > 0) {
      window.setTimeout(() => remove(id), duration);
    }
  }, [remove]);

  const api: ToastApi = {
    push,
    info: (title, message) => push({ level: 'info', title, message }),
    success: (title, message) => push({ level: 'success', title, message }),
    warning: (title, message) => push({ level: 'warning', title, message }),
    error: (title, message) => push({ level: 'error', title, message }),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      {typeof document !== 'undefined' &&
        createPortal(<ToastStack toasts={toasts} onDismiss={remove} />, document.body)}
    </ToastContext.Provider>
  );
}

function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div
      className="fixed top-4 right-4 z-[10000] flex flex-col gap-2 pointer-events-none"
      style={{ maxWidth: 'calc(100vw - 2rem)' }}
    >
      <AnimatePresence>
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const toneFor = (lvl: ToastLevel) => {
    if (lvl === 'success') return 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300';
    if (lvl === 'error') return 'border-rose-400/40 bg-rose-400/10 text-rose-300';
    if (lvl === 'warning') return 'border-amber-400/40 bg-amber-400/10 text-amber-300';
    return 'border-cyan-400/30 bg-cyan-400/10 text-cyan-300';
  };
  return (
    <motion.div
      initial={{ opacity: 0, x: 40, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.95 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      onClick={onDismiss}
      className={clsx(
        'pointer-events-auto min-w-[280px] max-w-[360px] px-4 py-3 rounded-lg border',
        'backdrop-blur-xl bg-[#0d111a]/95 shadow-[0_8px_24px_rgba(0,0,0,0.5)] cursor-pointer',
        'transition-transform hover:scale-[1.02]'
      )}
    >
      <div className={clsx('flex items-start gap-3', toneFor(toast.level))}>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold leading-tight">{toast.title}</div>
          {toast.message && (
            <div className="text-xs text-white/60 mt-1 leading-snug">{toast.message}</div>
          )}
        </div>
        <button
          type="button"
          aria-label="Fermer"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          className="text-white/40 hover:text-white/90 text-lg leading-none font-mono"
        >
          ×
        </button>
      </div>
    </motion.div>
  );
}

/** Hook utilitaire : joue un toast quand une query key spécifique change. */
export function useEnsureToastProvider(): void {
  const ctx = useContext(ToastContext);
  useEffect(() => {
    if (!ctx) {
      console.warn('ToastProvider manquant dans l\'arbre React — les toasts ne s\'afficheront pas.');
    }
  }, [ctx]);
}
