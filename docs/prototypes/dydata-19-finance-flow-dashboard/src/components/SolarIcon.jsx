import { Icon } from "@iconify/react";
import arrowRight from "@iconify-icons/solar/arrow-right-linear";
import bill from "@iconify-icons/solar/bill-list-linear";
import calendar from "@iconify-icons/solar/calendar-linear";
import check from "@iconify-icons/solar/check-circle-linear";
import copy from "@iconify-icons/solar/copy-linear";
import danger from "@iconify-icons/solar/danger-triangle-linear";
import document from "@iconify-icons/solar/document-text-linear";
import history from "@iconify-icons/solar/history-linear";
import home from "@iconify-icons/solar/home-2-linear";
import info from "@iconify-icons/solar/info-circle-linear";
import moon from "@iconify-icons/solar/moon-linear";
import settings from "@iconify-icons/solar/settings-linear";
import shop from "@iconify-icons/solar/shop-linear";
import sun from "@iconify-icons/solar/sun-linear";
import user from "@iconify-icons/solar/user-circle-linear";
import wallet from "@iconify-icons/solar/wallet-money-linear";

const icons = {
  arrowRight,
  bill,
  calendar,
  check,
  copy,
  danger,
  document,
  history,
  home,
  info,
  moon,
  settings,
  shop,
  sun,
  user,
  wallet,
};

export function SolarIcon({ name, size = 20, className, label }) {
  return (
    <Icon
      icon={icons[name] ?? info}
      width={size}
      height={size}
      className={className}
      aria-hidden={label ? undefined : true}
      aria-label={label}
    />
  );
}
