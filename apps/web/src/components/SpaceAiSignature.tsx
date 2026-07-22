import lightMark from "../assets/brand/space-ai-native/space-mark-parametric-orbit-accent.svg";
import darkMark from "../assets/brand/space-ai-native/space-mark-parametric-orbit-accent-dark.svg";

export type SpaceAiSignatureVariant = "horizontal" | "stacked" | "mark";

interface SpaceAiSignatureProps {
  className?: string;
  variant?: SpaceAiSignatureVariant;
}

export function SpaceAiSignature({
  className,
  variant = "horizontal",
}: SpaceAiSignatureProps) {
  const classes = [
    "space-ai-signature",
    `space-ai-signature--${variant}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      aria-label="Powered by SPACE AI Native"
      className={classes}
      role="img"
    >
      {variant === "mark" ? null : (
        <span className="space-ai-signature__copy" aria-hidden="true">
          POWERED BY
        </span>
      )}
      <span className="space-ai-signature__mark-wrap" aria-hidden="true">
        <img
          alt=""
          className="space-ai-signature__mark space-ai-signature__mark--light"
          src={lightMark}
        />
        <img
          alt=""
          className="space-ai-signature__mark space-ai-signature__mark--dark"
          src={darkMark}
        />
      </span>
      {variant === "mark" ? null : (
        <span className="space-ai-signature__native" aria-hidden="true">
          AI NATIVE
        </span>
      )}
    </div>
  );
}
