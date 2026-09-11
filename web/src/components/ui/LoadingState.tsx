import { motion } from 'framer-motion';

interface Props {
  message?: string;
  subMessage?: string;
  rows?: number;
}

export function LoadingState({
  message = 'Loading live telemetry...',
  subMessage = 'Connecting to MineGuard Node 1 backend',
  rows = 3,
}: Props) {
  return (
    <div className="flex min-h-[220px] w-full flex-col items-center justify-center p-6 text-center">
      <div className="relative mb-4 flex h-10 w-10 items-center justify-center">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'linear' }}
          className="h-9 w-9 rounded-full border-2 border-brand/20 border-t-brand"
        />
        <span className="absolute h-2 w-2 rounded-full bg-brand animate-ping" />
      </div>
      <div className="text-sm font-semibold text-ink">{message}</div>
      {subMessage && <div className="mt-1 text-xs text-ink-3">{subMessage}</div>}

      <div className="mt-6 w-full max-w-sm space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-3 rounded bg-surface-3/60 animate-pulse"
            style={{ width: `${100 - i * 15}%`, margin: '0 auto' }}
          />
        ))}
      </div>
    </div>
  );
}
