import { useEffect, useRef, type ReactNode } from "react";
import { gsap } from "@/lib/gsap";

/**
 * GSAP-powered stage card reveal. When `active` flips to true, the
 * card scales up from 0.92 → 1, fades in, and gets a subtle glow
 * border pulse. When a DIFFERENT stage activates, this one dims
 * gracefully. Creates the "spotlight moving through the pipeline"
 * effect.
 *
 * Wraps its children — use it around each stage card in the Pipeline Lab.
 */
export function StageReveal({
  active,
  completed,
  index,
  color = "#5b47ff",
  children,
}: {
  active: boolean;
  completed: boolean;
  index: number;
  color?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;

    if (active) {
      // Spotlight ON — scale up, full opacity, glow border.
      gsap.timeline()
        .to(el, {
          scale: 1,
          opacity: 1,
          y: 0,
          duration: 0.5,
          ease: "back.out(1.4)",
        })
        .to(
          el,
          {
            boxShadow: `0 0 20px ${color}33, 0 4px 16px rgba(0,0,0,0.08)`,
            borderColor: `${color}66`,
            duration: 0.4,
          },
          "-=0.3"
        );
    } else if (completed) {
      // Done — settle to normal, subtle check-mark state.
      gsap.to(el, {
        scale: 1,
        opacity: 0.85,
        y: 0,
        boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
        borderColor: `${color}22`,
        duration: 0.4,
      });
    } else {
      // Upcoming — dimmed, slightly pushed down.
      gsap.to(el, {
        scale: 0.97,
        opacity: 0.5,
        y: 4,
        boxShadow: "none",
        borderColor: "transparent",
        duration: 0.3,
      });
    }
  }, [active, completed, color]);

  // Initial state — hidden below, ready for reveal.
  return (
    <div
      ref={ref}
      className="rounded-lg border bg-white transition-none will-change-transform"
      style={{
        opacity: 0.5,
        transform: "scale(0.97) translateY(4px)",
      }}
    >
      {children}
    </div>
  );
}
