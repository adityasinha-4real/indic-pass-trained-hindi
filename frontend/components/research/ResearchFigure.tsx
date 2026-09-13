/**
 * Embeds one of the project's own pre-rendered research SVGs
 * (`public/research/figures/` / `public/research/evaluation-figures/`,
 * copied from `results/figures/` / `results/evaluation/figures/`).
 *
 * This component never draws a chart itself — every pixel comes from the
 * SVG file the research/evaluation code already generated. It only adds the
 * caption and source citation around it, consistent with "prefer embedding
 * existing SVGs rather than recreating the research plots".
 */
export function ResearchFigure({
  src,
  alt,
  caption,
  source,
}: {
  src: string;
  alt: string;
  caption?: string;
  source: string;
}) {
  return (
    <figure className="rounded-lg border bg-background p-3">
      {/* eslint-disable-next-line @next/next/no-img-element -- a static, pre-rendered research SVG, not an optimizable photo */}
      <img src={src} alt={alt} className="w-full" />
      {caption && <figcaption className="mt-2 text-xs text-muted">{caption}</figcaption>}
      <p className="mt-1 text-[11px] text-muted/80">
        Source: <code className="font-mono">{source}</code>
      </p>
    </figure>
  );
}
