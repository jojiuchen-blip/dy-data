import type { CSSProperties, HTMLAttributes } from "react";

import {
  ATTRIBUTION_COMPACT_AI_MASK,
  ATTRIBUTION_COMPACT_NATIVE_MASK,
  ATTRIBUTION_COMPACT_POWERED_BY_MASK,
  ATTRIBUTION_STANDARD_AI_MASK,
  ATTRIBUTION_STANDARD_NATIVE_MASK,
  ATTRIBUTION_STANDARD_POWERED_BY_MASK,
  SPACE_FOCUS_MASK,
  SPACE_ORBIT_BACK_MASK,
  SPACE_ORBIT_FRONT_MASK,
  SPACE_WORDMARK_MASK,
} from "./brand-attribution-masks";

export type BrandAttributionVariant = "standard-stacked" | "compact-horizontal";
export type BrandAttributionPlacement =
  | "rail-footer"
  | "account-surface-footer"
  | "auth-panel-footer"
  | "authorization-panel-footer"
  | "home-footer";

export interface BrandAttributionProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "children" | "role" | "aria-label"> {
  placement: BrandAttributionPlacement;
}

function createMaskStyle(maskImage: string) {
  return {
    WebkitMaskImage: maskImage,
    maskImage,
  } satisfies CSSProperties;
}

const attributionGlyphStyles = {
  "standard-stacked": {
    poweredBy: createMaskStyle(ATTRIBUTION_STANDARD_POWERED_BY_MASK),
    ai: createMaskStyle(ATTRIBUTION_STANDARD_AI_MASK),
    native: createMaskStyle(ATTRIBUTION_STANDARD_NATIVE_MASK),
  },
  "compact-horizontal": {
    poweredBy: createMaskStyle(ATTRIBUTION_COMPACT_POWERED_BY_MASK),
    ai: createMaskStyle(ATTRIBUTION_COMPACT_AI_MASK),
    native: createMaskStyle(ATTRIBUTION_COMPACT_NATIVE_MASK),
  },
} satisfies Record<BrandAttributionVariant, Record<"poweredBy" | "ai" | "native", CSSProperties>>;

const identityLayerStyles = {
  word: createMaskStyle(SPACE_WORDMARK_MASK),
  focus: createMaskStyle(SPACE_FOCUS_MASK),
  orbitBack: createMaskStyle(SPACE_ORBIT_BACK_MASK),
  orbitFront: createMaskStyle(SPACE_ORBIT_FRONT_MASK),
};

function resolveVariant(placement: BrandAttributionPlacement): BrandAttributionVariant {
  return placement === "rail-footer" ? "standard-stacked" : "compact-horizontal";
}

export function BrandAttribution({ placement, className, ...props }: BrandAttributionProps) {
  const variant = resolveVariant(placement);
  const glyphStyles = attributionGlyphStyles[variant];
  const classes = [
    "dc-brand-attribution",
    `dc-brand-attribution--${variant}`,
    "dc-brand-attribution--material-flat",
    "dc-brand-attribution--accent-orbit-only",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      {...props}
      className={classes}
      data-accent-scope="orbit-only"
      data-material="flat"
      data-placement={placement}
      data-tone="brand"
      data-variant={variant}
      role="img"
      aria-label="Powered by SPACE AI Native"
    >
      <span className="dc-brand-attribution__copy" aria-hidden="true">
        <span
          className="dc-brand-attribution__glyph"
          data-brand-glyph="powered-by"
          style={glyphStyles.poweredBy}
        />
      </span>
      <span className="dc-brand-attribution__identity" aria-hidden="true">
        <span className="dc-brand-attribution__mark">
          <span
            className="dc-brand-attribution__mark-layer dc-brand-attribution__mark-layer--orbit-back"
            style={identityLayerStyles.orbitBack}
          />
          <span
            className="dc-brand-attribution__mark-layer dc-brand-attribution__mark-layer--neutral"
            style={identityLayerStyles.word}
          />
          <span
            className="dc-brand-attribution__mark-layer dc-brand-attribution__mark-layer--focus"
            style={identityLayerStyles.focus}
          />
          <span
            className="dc-brand-attribution__mark-layer dc-brand-attribution__mark-layer--orbit-front"
            style={identityLayerStyles.orbitFront}
          />
        </span>
        <span className="dc-brand-attribution__descriptor">
          <span className="dc-brand-attribution__ai">
            <span
              className="dc-brand-attribution__glyph"
              data-brand-glyph="ai"
              style={glyphStyles.ai}
            />
          </span>
          <span className="dc-brand-attribution__native">
            <span
              className="dc-brand-attribution__glyph"
              data-brand-glyph="native"
              style={glyphStyles.native}
            />
          </span>
        </span>
      </span>
    </div>
  );
}
