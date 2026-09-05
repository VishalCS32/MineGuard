import { motion } from 'framer-motion';
import {
  IconArrowRight, IconBrain, IconGateway, IconMonitor, IconNodes, IconSensor,
} from '@/components/ui/icons';

const STAGES = [
  { Icon: IconSensor, title: 'Sensor', sub: 'Node' },
  { Icon: IconNodes, title: 'LoRa Mesh', sub: 'Network' },
  { Icon: IconGateway, title: 'Gateway', sub: 'ESP32 + GSM' },
  { Icon: IconBrain, title: 'Cloud &', sub: 'AI Engine' },
  { Icon: IconMonitor, title: 'Dashboard /', sub: 'Alerts' },
];

/** The pipeline, end to end. Arrows animate in sequence so the direction of
 *  travel is unmistakable at a glance. */
export function DataFlow() {
  return (
    <div className="flex items-start justify-between gap-1 px-3 pb-3">
      {STAGES.map(({ Icon, title, sub }, i) => (
        <div key={title} className="flex flex-1 items-start gap-1">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 * i }}
            className="flex min-w-0 flex-1 flex-col items-center gap-1 text-center"
          >
            <span className="grid h-9 w-9 place-items-center rounded-lg border border-hairline bg-surface-2 text-ink-2">
              <Icon size={19} />
            </span>
            <div className="text-[9px] leading-tight text-ink-2">
              <div className="font-semibold text-ink">{title}</div>
              <div>{sub}</div>
            </div>
          </motion.div>
          {i < STAGES.length - 1 && (
            <motion.span
              aria-hidden="true"
              className="mt-2 shrink-0 text-ink-3"
              initial={{ opacity: 0.2 }}
              animate={{ opacity: [0.2, 0.9, 0.2], x: [0, 2, 0] }}
              transition={{ duration: 2.4, repeat: Infinity, delay: i * 0.35, ease: 'easeInOut' }}
            >
              <IconArrowRight size={14} />
            </motion.span>
          )}
        </div>
      ))}
    </div>
  );
}
