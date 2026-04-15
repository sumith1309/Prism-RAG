import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function BentoGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-1 md:grid-cols-3 auto-rows-[minmax(200px,auto)] gap-3",
        className
      )}
    >
      {children}
    </div>
  );
}

export function BentoCard({
  icon,
  title,
  description,
  className,
  children,
  span,
  accent,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
  span?: "1" | "2" | "3";
  accent?: boolean;
}) {
  const colSpan =
    span === "3" ? "md:col-span-3" : span === "2" ? "md:col-span-2" : "md:col-span-1";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.4 }}
      className={cn(
        colSpan,
        "group relative rounded-xl border border-light-border bg-light-surface shadow-light-sm hover:shadow-light-card hover:border-light-borderStrong transition-all p-5 overflow-hidden",
        accent &&
          "bg-gradient-to-br from-white via-light-accent/4 to-white border-light-accent/25",
        className
      )}
    >
      {/* glow on hover */}
      <div className="pointer-events-none absolute -inset-px rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-[radial-gradient(circle_at_50%_0%,rgba(91,71,255,0.08),transparent_60%)]" />

      <div className="relative">
        <div className="flex items-center gap-2 mb-2.5">
          <div className="w-8 h-8 rounded-md bg-light-accent/10 border border-light-accent/20 flex items-center justify-center">
            {icon}
          </div>
          <h3 className="text-[14.5px] font-semibold text-light-fg">{title}</h3>
        </div>
        <p className="text-[12.5px] text-light-fgMuted leading-relaxed">{description}</p>
        {children && <div className="mt-4">{children}</div>}
      </div>
    </motion.div>
  );
}
