import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

/**
 * Letter-by-letter text reveal — GSAP-powered split-text effect.
 * Each character appears with a stagger, creating a "typing into
 * existence" feel. Used for stage titles and key metrics in the
 * Pipeline Lab.
 *
 * No GSAP SplitText plugin needed — we split manually with spans,
 * then stagger-animate them. Same visual result, zero cost.
 */
export function TextReveal({
  text,
  active,
  className = "",
  stagger = 0.03,
  duration = 0.4,
}: {
  text: string;
  active: boolean;
  className?: string;
  stagger?: number;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chars = ref.current.querySelectorAll(".char");

    if (active) {
      gsap.fromTo(
        chars,
        { opacity: 0, y: 12, rotateX: -40 },
        {
          opacity: 1,
          y: 0,
          rotateX: 0,
          duration,
          stagger,
          ease: "back.out(1.7)",
        }
      );
    } else {
      gsap.to(chars, {
        opacity: 0.4,
        y: 0,
        duration: 0.2,
      });
    }
  }, [active, stagger, duration]);

  return (
    <span ref={ref} className={className} style={{ perspective: 400 }}>
      {text.split("").map((char, i) => (
        <span
          key={i}
          className="char inline-block"
          style={{ opacity: 0.4 }}
        >
          {char === " " ? "\u00A0" : char}
        </span>
      ))}
    </span>
  );
}
