import { strengthColor } from "@/lib/labels";

const BAND_LABELS = ["Very Weak", "Weak", "Fair", "Strong", "Very Strong"];

export function StrengthMeter({ score, label }: { score: number; label: string }) {
  const color = strengthColor(score);

  return (
    <div
      role="img"
      aria-label={`Strength: ${label}, ${score} out of ${BAND_LABELS.length - 1}`}
      className="w-full"
    >
      <div className="flex gap-1.5">
        {BAND_LABELS.map((band, index) => (
          <div
            key={band}
            className="h-2.5 flex-1 rounded-full transition-colors"
            style={{
              backgroundColor: index <= score ? color : "var(--surface-muted)",
            }}
          />
        ))}
      </div>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="text-lg font-semibold" style={{ color }}>
          {label}
        </span>
        <span className="text-xs text-muted">
          IndicPass score {score} / {BAND_LABELS.length - 1}
        </span>
      </div>
    </div>
  );
}
