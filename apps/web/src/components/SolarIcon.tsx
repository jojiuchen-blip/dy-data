import { Icon } from "@iconify/react";
import type { IconifyIcon } from "@iconify/react";
import billListLinear from "@iconify-icons/solar/bill-list-linear";
import buildings2Linear from "@iconify-icons/solar/buildings-2-linear";
import chart2BoldDuotone from "@iconify-icons/solar/chart-2-bold-duotone";
import chart2Linear from "@iconify-icons/solar/chart-2-linear";
import chatRoundDotsBoldDuotone from "@iconify-icons/solar/chat-round-dots-bold-duotone";
import chatRoundDotsLinear from "@iconify-icons/solar/chat-round-dots-linear";
import closeCircleLinear from "@iconify-icons/solar/close-circle-linear";
import copyLinear from "@iconify-icons/solar/copy-linear";
import eyeClosedLinear from "@iconify-icons/solar/eye-closed-linear";
import eyeLinear from "@iconify-icons/solar/eye-linear";
import graphNewUpBoldDuotone from "@iconify-icons/solar/graph-new-up-bold-duotone";
import home2Linear from "@iconify-icons/solar/home-2-linear";
import keyMinimalisticSquareLinear from "@iconify-icons/solar/key-minimalistic-square-linear";
import logout3Linear from "@iconify-icons/solar/logout-3-linear";
import refreshCircleLinear from "@iconify-icons/solar/refresh-circle-linear";
import settingsMinimalisticLinear from "@iconify-icons/solar/settings-minimalistic-linear";
import shieldCheckBoldDuotone from "@iconify-icons/solar/shield-check-bold-duotone";
import userCircleLinear from "@iconify-icons/solar/user-circle-linear";

const solarIcons = {
  accounts: userCircleLinear,
  admin: shieldCheckBoldDuotone,
  brand: graphNewUpBoldDuotone,
  chart: chart2BoldDuotone,
  close: closeCircleLinear,
  copy: copyLinear,
  details: billListLinear,
  eyeClosed: eyeClosedLinear,
  eye: eyeLinear,
  feedback: chatRoundDotsLinear,
  home: home2Linear,
  key: keyMinimalisticSquareLinear,
  logout: logout3Linear,
  ranking: chart2Linear,
  rules: settingsMinimalisticLinear,
  settlement: buildings2Linear,
  sync: refreshCircleLinear,
  clues: chatRoundDotsBoldDuotone,
  cluesLine: chatRoundDotsLinear,
} satisfies Record<string, IconifyIcon>;

export type SolarIconName = keyof typeof solarIcons;

interface SolarIconProps {
  className?: string;
  label?: string;
  name: SolarIconName;
  size?: number;
}

export function SolarIcon({
  className,
  label,
  name,
  size = 18,
}: SolarIconProps) {
  return (
    <Icon
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={["solar-icon", className].filter(Boolean).join(" ")}
      height={size}
      icon={solarIcons[name]}
      role={label ? "img" : undefined}
      width={size}
    />
  );
}
