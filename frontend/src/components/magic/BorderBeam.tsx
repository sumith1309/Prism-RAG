import { cn } from "@/lib/utils";

/**
 * BorderBeam — an animated light-trail that loops around the border of a
 * rounded container. Drop on any relative/rounded element.
 * Inspired by magic-ui / 21st.dev.
 */
export function BorderBeam({
  size = 200,
  duration = 7,
  colorFrom = "#a18dff",
  colorTo = "#5b47ff",
  className,
}: {
  size?: number;
  duration?: number;
  colorFrom?: string;
  colorTo?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit] [border:1px_solid_transparent]",
        "![mask-clip:padding-box,border-box] ![mask-composite:intersect]",
        "[mask:linear-gradient(transparent,transparent),linear-gradient(#000,#000)]",
        "after:absolute after:aspect-square after:w-[var(--size)]",
        "after:animate-[border-beam_var(--duration)s_infinite_linear]",
        "after:[background:linear-gradient(to_left,var(--color-from),var(--color-to),transparent)]",
        "after:[offset-path:rect(0_auto_auto_0_round_var(--size))]",
        className
      )}
      style={
        {
          "--size": `${size}px`,
          "--duration": String(duration),
          "--color-from": colorFrom,
          "--color-to": colorTo,
        } as React.CSSProperties
      }
    />
  );
}
