import { motion } from 'framer-motion';
import type { ReactNode } from 'react';

interface Props {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  delay?: number;
}

/** Standard panel: hairline border, dark surface, optional header row. */
export function Card({
  title, subtitle, action, children, className = '', bodyClassName = '', delay = 0,
}: Props) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={`panel flex min-h-0 flex-col ${className}`}
    >
      {(title || action) && (
        <header className="flex shrink-0 items-center justify-between gap-3 px-4 pb-2 pt-3">
          <h2 className="panel-title flex items-baseline gap-2">
            {title}
            {subtitle && <span className="panel-sub normal-case">{subtitle}</span>}
          </h2>
          {action}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </motion.section>
  );
}
