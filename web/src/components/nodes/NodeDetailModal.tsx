import { useEffect } from 'react';
import type { NodeDetailViewModel } from '@/data/telemetry/types';
import { NodeDetailPanel } from './NodeDetailPanel';
import { IconX } from '@/components/ui/icons';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  viewModel: NodeDetailViewModel | null;
}

export function NodeDetailModal({ isOpen, onClose, viewModel }: Props) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !viewModel) return null;

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-6">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity animate-fade-in"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative z-10 flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl border border-hairline bg-plane shadow-2xl overflow-hidden animate-scale-up">
        <div className="flex items-center justify-between border-b border-hairline bg-surface-2/90 px-4 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm text-ink">Node Comprehensive Telemetry Inspector</span>
            <span className="rounded bg-brand/15 px-2 py-0.5 text-[10px] font-bold text-brand uppercase">
              {viewModel.nodeId}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-hairline p-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink transition-colors"
            aria-label="Close modal"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <NodeDetailPanel viewModel={viewModel} />
        </div>
      </div>
    </div>
  );
}
