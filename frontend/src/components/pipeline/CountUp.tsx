import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

/**
 * Animated number counter — counts from 0 to `value` with easing.
 * Used for latency ms, rerank scores, chunk counts, confidence %.
 * The number physically rolls up like a scoreboard when it first
 * appears or when `value` changes.
 *
 * Props:
 *   value     — target number (can be int or float)
 *   duration  — animation duration in seconds (default 1.2)
 *   decimals  — decimal places to show (default 0)
 *   prefix    — text before number (e.g. "+" or "$")
 *   suffix    — text after number (e.g. "ms" or "%")
 *   className — passed to the outer span
 */
export function CountUp({
  value,
  duration = 1.2,
  decimals = 0,
  prefix = "",
  suffix = "",
  className = "",
}: {
  value: number;
  duration?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const counterRef = useRef({ val: 0 });

  useEffect(() => {
    if (!ref.current) return;
    const counter = counterRef.current;

    const tween = gsap.to(counter, {
      val: value,
      duration,
      ease: "power2.out",
      onUpdate: () => {
        if (ref.current) {
          ref.current.textContent = `${prefix}${counter.val.toFixed(decimals)}${suffix}`;
        }
      },
    });

    return () => {
      tween.kill();
    };
  }, [value, duration, decimals, prefix, suffix]);

  return (
    <span ref={ref} className={className}>
      {prefix}0{suffix}
    </span>
  );
}
