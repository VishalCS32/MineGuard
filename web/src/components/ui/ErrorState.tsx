import { IconRefresh, IconWarning } from './icons';

interface Props {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({
  title = 'Failed to connect to backend',
  message = 'The MineGuard telemetry endpoint could not be reached. Check network connection or backend service status.',
  onRetry,
}: Props) {
  return (
    <div className="flex min-h-[220px] w-full flex-col items-center justify-center rounded-xl border border-critical/25 bg-critical/5 p-6 text-center">
      <span className="mb-3 grid h-10 w-10 place-items-center rounded-full bg-critical/15 text-critical">
        <IconWarning size={22} />
      </span>
      <h3 className="text-sm font-semibold text-critical">{title}</h3>
      <p className="mt-1 max-w-md text-xs text-ink-2">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="focus-ring mt-4 flex items-center gap-1.5 rounded-lg bg-surface-2 px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-surface-3 hover:text-brand"
        >
          <IconRefresh size={14} /> Retry Connection
        </button>
      )}
    </div>
  );
}
