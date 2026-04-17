/**
 * GSAP setup — register plugins once, export a configured instance.
 * Import `gsap` from this module (not from 'gsap' directly) so plugins
 * are always registered. GSAP and framer-motion coexist — GSAP handles
 * complex scene choreography (Pipeline Lab), framer handles component
 * transitions (cards, chips, bubbles).
 */
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";

// Register plugins once at module load.
gsap.registerPlugin(ScrollTrigger, MotionPathPlugin);

// Default easing for the premium SaaS feel — slightly bouncy, not
// mechanical. Used across all Pipeline Lab animations.
gsap.defaults({
  ease: "power2.out",
  duration: 0.6,
});

export { gsap, ScrollTrigger, MotionPathPlugin };
