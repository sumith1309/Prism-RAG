import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComparisonCard } from "@/components/ComparisonCard";
import type { ComparisonColumn } from "@/types";

const baseColumns: ComparisonColumn[] = [
  {
    doc_id: "d1",
    filename: "HRMS-Portal.docx",
    label: "HRMS Portal",
    answer: "HRFlow is built on **Django 5.27** [Source 1].",
    sources: [
      {
        index: 1,
        doc_id: "d1",
        filename: "HRMS-Portal.docx",
        page: 1,
        section: "",
        text: "HRFlow is built on Django.",
        rrf_score: 0.03,
        rerank_score: 0.87,
      },
    ],
    ok: true,
    error: "",
  },
  {
    doc_id: "d2",
    filename: "HR-Policy.docx",
    label: "HR Policy",
    answer: "Leave policy: 18 days [Source 1].",
    sources: [
      {
        index: 1,
        doc_id: "d2",
        filename: "HR-Policy.docx",
        page: 3,
        section: "",
        text: "Employees are entitled to 18 days.",
        rrf_score: 0.025,
        rerank_score: 0.79,
      },
    ],
    ok: true,
    error: "",
  },
];

describe("ComparisonCard", () => {
  it("renders one column per doc with label + answer", () => {
    render(<ComparisonCard columns={baseColumns} />);
    expect(screen.getByText("HRMS Portal")).toBeInTheDocument();
    expect(screen.getByText("HR Policy")).toBeInTheDocument();
    expect(screen.getByText(/Side-by-side comparison/)).toBeInTheDocument();
    expect(screen.getByText(/2 documents/)).toBeInTheDocument();
  });

  it("shows weak-match fallback when ok=false + error=weak_match", () => {
    const cols: ComparisonColumn[] = [
      baseColumns[0],
      {
        ...baseColumns[1],
        ok: false,
        error: "weak_match",
        answer: "",
        sources: [],
      },
    ];
    render(<ComparisonCard columns={cols} />);
    expect(
      screen.getByText(/has no strong match/i)
    ).toBeInTheDocument();
  });

  it("renders nothing for empty columns array", () => {
    const { container } = render(<ComparisonCard columns={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
