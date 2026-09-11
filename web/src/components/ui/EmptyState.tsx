import { IconCheck } from './icons';

interface Props {
  title?: string;
  message?: string;
  icon?: React.ReactNode;
}

export function EmptyState({
  title = 'No Data Available',
  message = 'There are currently no records to display.',
  icon,
}: Props) {
  return (
    <div className="flex min-h-[180px] w-full flex-col items-center justify-center p-6 text-center text-ink-3">
      <span className="mb-2 grid h-9 w-9 place-items-center rounded-full bg-surface-2 text-ink-2">
        {icon || <IconCheck size={18} />}
      </span>
      <div className="text-xs font-semibold text-ink-2">{title}</div>
      <div className="mt-0.5 text-[11px]">{message}</div>
    </div>
  );
}
