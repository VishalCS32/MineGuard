const TAGS = [
  'Continuous Monitoring', 'Early Detection', 'AI Prediction', 'Timely Alerts', 'Safer Mines',
];

export function Footer() {
  return (
    <footer className="flex h-9 shrink-0 items-center justify-center gap-3 border-t border-hairline bg-surface/40 text-[11px] font-medium text-brand">
      {TAGS.map((t, i) => (
        <span key={t} className="flex items-center gap-3">
          {t}
          {i < TAGS.length - 1 && <span className="text-brand/40">•</span>}
        </span>
      ))}
    </footer>
  );
}
