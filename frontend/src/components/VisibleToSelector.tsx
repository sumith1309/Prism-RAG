import { Shield, ShieldCheck, Lock, Crown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Exec-only "who should see this document?" picker.
 *
 * The UI is a single set of four checkboxes (Guest / Employee / Manager /
 * Executive — executive is always on and read-only because exec must
 * retain visibility to manage toggles). From that selection we derive:
 *
 *   doc_level           = lowest clearance among the selected roles
 *                         (so their L-filter passes the bar)
 *   disabled_for_roles  = any selected role whose clearance is below
 *                         doc_level (there are none by construction —
 *                         but we also add roles whose clearance IS above
 *                         doc_level but are NOT selected, so they're
 *                         blocked despite clearance)
 *
 * Effectively: the checkbox set is the source of truth. Backend
 * classification + hide-list are computed once on save.
 */

export type VisibleRole = "guest" | "employee" | "manager" | "executive";

export const ROLE_LEVEL: Record<VisibleRole, number> = {
  guest: 1,
  employee: 2,
  manager: 3,
  executive: 4,
};

export const ROLE_LABEL: Record<VisibleRole, string> = {
  guest: "Guest",
  employee: "Employee",
  manager: "Manager",
  executive: "Executive",
};

const ROLE_ICON: Record<VisibleRole, typeof Shield> = {
  guest: Shield,
  employee: Shield,
  manager: ShieldCheck,
  executive: Crown,
};

const ROLE_COLOR: Record<VisibleRole, string> = {
  guest: "text-clearance-public",
  employee: "text-clearance-internal",
  manager: "text-clearance-confidential",
  executive: "text-clearance-restricted",
};

/**
 * Given a "who should see this" set of roles, derive the (doc_level,
 * disabled_for_roles) pair the backend PATCH expects. Executive is
 * always visible so we ignore it when computing the floor.
 */
export function deriveBackendFields(visible: Set<VisibleRole>): {
  doc_level: number;
  disabled_for_roles: VisibleRole[];
} {
  const nonExec: VisibleRole[] = ["guest", "employee", "manager"];
  const visibleNonExec = nonExec.filter((r) => visible.has(r));

  if (visibleNonExec.length === 0) {
    // Executive-only.
    return { doc_level: 4, disabled_for_roles: [] };
  }

  const floorRole = visibleNonExec.reduce<VisibleRole>(
    (acc, r) => (ROLE_LEVEL[r] < ROLE_LEVEL[acc] ? r : acc),
    visibleNonExec[0]
  );
  const docLevel = ROLE_LEVEL[floorRole];

  // Any non-exec role with clearance >= doc_level that is NOT in the
  // visible set must be explicitly hidden.
  const disabled = nonExec.filter(
    (r) => ROLE_LEVEL[r] >= docLevel && !visible.has(r)
  );

  return { doc_level: docLevel, disabled_for_roles: disabled };
}

/**
 * Inverse: given the backend's (doc_level, disabled_for_roles), compute
 * which roles actually see the doc today.
 */
export function inferVisibleRoles(
  doc_level: number,
  disabled: string[]
): Set<VisibleRole> {
  const disabledSet = new Set(disabled);
  const out = new Set<VisibleRole>(["executive"]);
  for (const r of ["guest", "employee", "manager"] as VisibleRole[]) {
    if (ROLE_LEVEL[r] >= doc_level && !disabledSet.has(r)) {
      out.add(r);
    }
  }
  return out;
}

export function VisibleToSelector({
  value,
  onChange,
  disabled = false,
  compact = false,
}: {
  value: Set<VisibleRole>;
  onChange: (next: Set<VisibleRole>) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const toggle = (role: VisibleRole) => {
    if (role === "executive") return; // always on
    const next = new Set(value);
    next.has(role) ? next.delete(role) : next.add(role);
    // Guarantee executive stays in.
    next.add("executive");
    onChange(next);
  };

  const roles: VisibleRole[] = ["guest", "employee", "manager", "executive"];

  return (
    <div className={cn("space-y-0.5", compact && "space-y-0")}>
      {roles.map((r) => {
        const Icon = ROLE_ICON[r];
        const checked = value.has(r);
        const isExec = r === "executive";
        return (
          <label
            key={r}
            className={cn(
              "flex items-center gap-2 px-2 py-1.5 rounded text-[12px]",
              isExec
                ? "cursor-default opacity-70"
                : "cursor-pointer hover:bg-bg-subtle",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => toggle(r)}
              disabled={disabled || isExec}
              className="accent-accent"
            />
            <Icon
              className={cn("w-3.5 h-3.5 shrink-0", ROLE_COLOR[r])}
              strokeWidth={1.75}
            />
            <span className="text-fg">{ROLE_LABEL[r]}</span>
            {isExec && (
              <span className="ml-auto text-[9.5px] uppercase tracking-wider text-fg-subtle">
                always
              </span>
            )}
          </label>
        );
      })}
    </div>
  );
}
