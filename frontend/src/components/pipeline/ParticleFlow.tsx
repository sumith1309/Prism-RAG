import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

/**
 * Animated particles that flow along an SVG path — the signature
 * visual for the Pipeline Lab. When a stage completes, particles
 * pulse from the source node to the target node along the connecting
 * edge, creating a "data flowing through the pipeline" effect.
 *
 * Usage:
 *   <svg>
 *     <path id="edge-embed-dense" d="M100,50 C150,50 200,80 250,80" />
 *     <ParticleFlow pathId="edge-embed-dense" active={stage === "dense"} />
 *   </svg>
 *
 * Each particle is a small glowing circle that follows the path with
 * staggered start times. The glow uses a radial gradient filter.
 */

const PARTICLE_COUNT = 5;
const PARTICLE_RADIUS = 3;

export function ParticleFlow({
  pathId,
  active,
  color = "#5b47ff",
  particleCount = PARTICLE_COUNT,
  duration = 1.8,
}: {
  pathId: string;
  active: boolean;
  color?: string;
  particleCount?: number;
  duration?: number;
}) {
  const groupRef = useRef<SVGGElement>(null);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);

  useEffect(() => {
    if (!groupRef.current) return;
    const circles = groupRef.current.querySelectorAll("circle");
    const path = document.getElementById(pathId);
    if (!path || circles.length === 0) return;

    // Kill any running timeline before starting a new one.
    timelineRef.current?.kill();

    if (!active) {
      // Fade out particles when stage is inactive.
      gsap.to(circles, { opacity: 0, duration: 0.3 });
      return;
    }

    const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.3 });

    circles.forEach((circle, i) => {
      tl.fromTo(
        circle,
        {
          opacity: 0,
          motionPath: {
            path: `#${pathId}`,
            align: `#${pathId}`,
            alignOrigin: [0.5, 0.5],
            start: 0,
            end: 0,
          },
        },
        {
          opacity: 1,
          motionPath: {
            path: `#${pathId}`,
            align: `#${pathId}`,
            alignOrigin: [0.5, 0.5],
            start: 0,
            end: 1,
          },
          duration,
          ease: "power1.inOut",
          onComplete: () => {
            gsap.to(circle, { opacity: 0, duration: 0.2 });
          },
        },
        i * (duration / particleCount) // stagger
      );
    });

    timelineRef.current = tl;

    return () => {
      tl.kill();
    };
  }, [active, pathId, duration, particleCount]);

  return (
    <g ref={groupRef}>
      {Array.from({ length: particleCount }, (_, i) => (
        <circle
          key={i}
          r={PARTICLE_RADIUS}
          fill={color}
          opacity={0}
          filter="url(#particle-glow)"
        />
      ))}
    </g>
  );
}

/**
 * SVG filter definition for the particle glow effect. Add this ONCE
 * inside the Pipeline Lab's SVG <defs> block:
 *
 *   <ParticleGlowFilter />
 */
export function ParticleGlowFilter() {
  return (
    <defs>
      <filter id="particle-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
        <feColorMatrix
          in="blur"
          type="matrix"
          values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7"
          result="glow"
        />
        <feMerge>
          <feMergeNode in="glow" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
  );
}
