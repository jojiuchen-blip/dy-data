export interface TertiaryNavItem {
  current?: boolean;
  disabled?: boolean;
  href: string;
  label: string;
}

interface TertiaryNavProps {
  items: TertiaryNavItem[];
  label: string;
}

export function TertiaryNav({ items, label }: TertiaryNavProps) {
  return (
    <nav aria-label={label} className="tertiary-nav">
      {items.map((item) =>
        item.disabled ? (
          <span
            aria-disabled="true"
            className="tertiary-nav__item is-disabled"
            key={item.href}
          >
            {item.label}
          </span>
        ) : (
          <a
            aria-current={item.current ? "page" : undefined}
            className="tertiary-nav__item"
            href={item.href}
            key={item.href}
          >
            {item.label}
          </a>
        ),
      )}
    </nav>
  );
}
