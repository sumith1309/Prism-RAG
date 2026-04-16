import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CitationCheckChip } from "@/components/CitationCheckChip";

describe("CitationCheckChip states", () => {
  it("hides entirely when no citations were in the answer", () => {
    const { container } = render(
      <CitationCheckChip
        check={{ total: 0, valid: 0, fabricated: [], weak: [], score: 1.0 }}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows green 'verified' pill when all citations are clean", () => {
    render(
      <CitationCheckChip
        check={{ total: 3, valid: 3, fabricated: [], weak: [], score: 1.0 }}
      />
    );
    expect(screen.getByText("3 citations verified")).toBeInTheDocument();
  });

  it("shows fabricated count when LLM hallucinates a source number", () => {
    render(
      <CitationCheckChip
        check={{ total: 2, valid: 1, fabricated: [7], weak: [], score: 0.5 }}
      />
    );
    expect(
      screen.getByText(/1 fabricated of 2/i)
    ).toBeInTheDocument();
  });

  it("shows weak count when citations have no word overlap with chunk", () => {
    render(
      <CitationCheckChip
        check={{ total: 2, valid: 1, fabricated: [], weak: [3], score: 0.5 }}
      />
    );
    expect(screen.getByText(/1 weak of 2/i)).toBeInTheDocument();
  });

  it("combines fabricated + weak counts in one message", () => {
    render(
      <CitationCheckChip
        check={{ total: 4, valid: 1, fabricated: [8], weak: [2, 3], score: 0.25 }}
      />
    );
    expect(
      screen.getByText(/1 fabricated, 2 weak of 4/i)
    ).toBeInTheDocument();
  });
});
