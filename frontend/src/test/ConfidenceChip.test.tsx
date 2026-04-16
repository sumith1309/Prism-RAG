import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfidenceChip } from "@/components/ConfidenceChip";

/** Tier 1.3 — verify the 4-band classification + Broaden button gating.
 * These thresholds are the user-facing contract for the chip, so any
 * regression here is a visible UX break.
 */
describe("ConfidenceChip bands", () => {
  it("80+ → High confidence, no Broaden button", () => {
    const onBroaden = vi.fn();
    render(<ConfidenceChip value={85} onBroaden={onBroaden} />);
    expect(screen.getByText("High confidence")).toBeInTheDocument();
    expect(screen.queryByText("Broaden")).not.toBeInTheDocument();
  });

  it("60-79 → Confident, no Broaden button", () => {
    render(<ConfidenceChip value={70} onBroaden={vi.fn()} />);
    expect(screen.getByText("Confident")).toBeInTheDocument();
    expect(screen.queryByText("Broaden")).not.toBeInTheDocument();
  });

  it("40-59 → Limited confidence with Broaden button", async () => {
    const onBroaden = vi.fn();
    render(<ConfidenceChip value={50} onBroaden={onBroaden} />);
    expect(screen.getByText("Limited confidence")).toBeInTheDocument();
    const broadenBtn = screen.getByText("Broaden");
    await userEvent.click(broadenBtn);
    expect(onBroaden).toHaveBeenCalledTimes(1);
  });

  it("<40 → Low confidence with Broaden button", () => {
    render(<ConfidenceChip value={25} onBroaden={vi.fn()} />);
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
    expect(screen.getByText("Broaden")).toBeInTheDocument();
  });

  it("Broaden button hidden when onBroaden not provided even on low scores", () => {
    render(<ConfidenceChip value={30} />);
    expect(screen.queryByText("Broaden")).not.toBeInTheDocument();
  });

  it("displays the raw score next to the label", () => {
    render(<ConfidenceChip value={73} />);
    expect(screen.getByText("73")).toBeInTheDocument();
  });

  it("exactly 80 → High (boundary)", () => {
    render(<ConfidenceChip value={80} />);
    expect(screen.getByText("High confidence")).toBeInTheDocument();
  });

  it("exactly 60 → Confident (boundary)", () => {
    render(<ConfidenceChip value={60} />);
    expect(screen.getByText("Confident")).toBeInTheDocument();
  });

  it("exactly 40 → Limited (boundary)", () => {
    render(<ConfidenceChip value={40} onBroaden={vi.fn()} />);
    expect(screen.getByText("Limited confidence")).toBeInTheDocument();
    expect(screen.getByText("Broaden")).toBeInTheDocument();
  });
});
