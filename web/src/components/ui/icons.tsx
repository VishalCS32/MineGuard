/** Inline SVG icon set. Stroke-based, 1.6px, sized by the `size` prop.
 *  Icons always accompany a text label -- status is never carried by colour alone. */
import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
});

export const IconShield = ({ size = 20, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M12 3 5 6v6c0 4.2 2.9 7.9 7 9 4.1-1.1 7-4.8 7-9V6l-7-3Z" />
    <path d="m9.2 12.2 1.9 1.9 3.7-4" />
  </svg>
);

export const IconGrid = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </svg>
);

export const IconMap = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="m9 4-6 2.5v13L9 17l6 3 6-2.5v-13L15 7 9 4Z" />
    <path d="M9 4v13M15 7v13" />
  </svg>
);

export const IconNodes = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="5" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" />
    <path d="M10.5 6.6 6.4 16M13.5 6.6 17.6 16M7 18h10" />
  </svg>
);

export const IconBell = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7Z" />
    <path d="M13.7 20a2 2 0 0 1-3.4 0" />
  </svg>
);

export const IconChart = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);

export const IconHistory = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="4" y="3" width="16" height="18" rx="2" />
    <path d="M8 8h8M8 12h8M8 16h5" />
  </svg>
);

export const IconBrain = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
  </svg>
);

export const IconReport = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
    <path d="M14 3v5h5M9 13h6M9 17h4" />
  </svg>
);

export const IconGear = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </svg>
);

export const IconHeart = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M12 3 5 6v6c0 4.2 2.9 7.9 7 9 4.1-1.1 7-4.8 7-9V6l-7-3Z" />
    <path d="M8.5 12h2l1.5-3 1.5 5 1.2-2h1.8" />
  </svg>
);

export const IconWarning = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </svg>
);

export const IconCloud = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.2 9.4 4 4 0 0 0 6.5 19h11Z" />
  </svg>
);

export const IconClock = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
);

export const IconBattery = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="2" y="7" width="17" height="10" rx="2.5" />
    <path d="M22 11v2" />
  </svg>
);

export const IconTilt = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M3 19h18M5 19 15 6M9 19a6 6 0 0 1 4-5.6" />
  </svg>
);

export const IconStrain = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M12 2v5l-3 3 4 3-2 4 3 5" />
    <path d="M4 21h16" />
  </svg>
);

export const IconPacket = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M12 21s7-5.4 7-11a7 7 0 1 0-14 0c0 5.6 7 11 7 11Z" />
    <circle cx="12" cy="10" r="2.5" />
  </svg>
);

export const IconChevron = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m9 6 6 6-6 6" /></svg>
);

export const IconUser = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="8" r="3.5" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
  </svg>
);

export const IconWifi = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M2.5 9a15 15 0 0 1 19 0M5.5 12.5a10 10 0 0 1 13 0M8.5 16a5.5 5.5 0 0 1 7 0" />
    <path d="M12 19.5h.01" />
  </svg>
);

export const IconDatabase = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </svg>
);

export const IconGateway = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="2.5" y="13" width="19" height="6" rx="2" />
    <path d="M6 16h.01M9.5 16h5M7 9.5a7 7 0 0 1 10 0M9.6 12a3.5 3.5 0 0 1 4.8 0" />
  </svg>
);

export const IconCpu = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="7" y="7" width="10" height="10" rx="2" />
    <path d="M4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3" />
  </svg>
);

export const IconMonitor = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <rect x="2.5" y="4" width="19" height="13" rx="2" />
    <path d="M9 21h6M12 17v4" />
  </svg>
);

export const IconSensor = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="M12 13v8M8 21h8" />
    <circle cx="12" cy="8" r="2" />
    <path d="M8.5 4.5a5 5 0 0 0 0 7M15.5 4.5a5 5 0 0 1 0 7" />
  </svg>
);

export const IconArrowRight = ({ size = 18, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M4 12h15M13 6l6 6-6 6" /></svg>
);

export const IconPlus = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 5v14M5 12h14" /></svg>
);

export const IconMinus = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M5 12h14" /></svg>
);

export const IconCrosshair = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="12" r="7" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </svg>
);

export const IconLayers = ({ size = 16, ...p }: IconProps) => (
  <svg {...base(size)} {...p}>
    <path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5" />
  </svg>
);
