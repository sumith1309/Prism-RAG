import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DisambiguationCard } from "@/components/DisambiguationCard";
import type { ChatMessage } from "@/types";

const baseCandidates = [
  {
    doc_id: "d1",
    filename: "HRMS-Portal.docx",
    label: "HRMS Portal",
    hint: "HRFlow is a multi-tenant HR Management System built on Django.",
    top_score: 0.87,
    chunk_count: 3,
  },
  {
    doc_id: "d2",
    filename: "HR-Policy.docx",
    label: "HR Policy",
    hint: "Leave policy: 18 days paid annual leave.",
    top_score: 0.79,
    chunk_count: 2,
  },
];

function buildMessage(
  overrides: Partial<NonNullable<ChatMessage["disambiguation"]>> = {}
): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "Clarifying...",
    answerMode: "disambiguate",
    disambiguation: {
      query: "HRMS flow",
      candidates: baseCandidates,
      ...overrides,
    },
  };
}

describe("DisambiguationCard", () => {
  it("renders one button per candidate with label + hint + chunk count", () => {
    render(<DisambiguationCard message={buildMessage()} onPick={vi.fn()} />);
    expect(screen.getByText("HRMS Portal")).toBeInTheDocument();
    expect(screen.getByText("HR Policy")).toBeInTheDocument();
    expect(screen.getByText(/HRFlow is a multi-tenant HR/i)).toBeInTheDocument();
    expect(screen.getByText(/Leave policy: 18 days/i)).toBeInTheDocument();
  });

  it("firing onPick passes doc_id + query + messageId", async () => {
    const onPick = vi.fn();
    render(<DisambiguationCard message={buildMessage()} onPick={onPick} />);
    const hrmsButton = screen.getByText("HRMS Portal").closest("button")!;
    await userEvent.click(hrmsButton);
    expect(onPick).toHaveBeenCalledWith("d1", "HRMS flow", "m-1");
  });

  it("frozen state: chosen_doc_id shows the Scoped badge + disables buttons", () => {
    render(
      <DisambiguationCard
        message={buildMessage({ chosen_doc_id: "d1" })}
        onPick={vi.fn()}
      />
    );
    expect(screen.getByText(/Scoped/)).toBeInTheDocument();
    // Buttons exist but should be disabled after freeze
    const allButtons = screen.getAllByRole("button");
    allButtons.forEach((b) => expect(b).toBeDisabled());
  });

  it("'Compare all' button fires onCompareAll with ALL doc ids", async () => {
    const onCompareAll = vi.fn();
    render(
      <DisambiguationCard
        message={buildMessage()}
        onPick={vi.fn()}
        onCompareAll={onCompareAll}
      />
    );
    const compareBtn = screen.getByRole("button", { name: /Compare all/ });
    await userEvent.click(compareBtn);
    expect(onCompareAll).toHaveBeenCalledWith(["d1", "d2"], "HRMS flow", "m-1");
  });

  it("'Compare all' button hidden when onCompareAll not provided", () => {
    render(<DisambiguationCard message={buildMessage()} onPick={vi.fn()} />);
    expect(screen.queryByText(/Compare all/)).not.toBeInTheDocument();
  });

  it("'Compare all' button hidden after user has chosen (frozen state)", () => {
    render(
      <DisambiguationCard
        message={buildMessage({ chosen_doc_id: "d1" })}
        onPick={vi.fn()}
        onCompareAll={vi.fn()}
      />
    );
    expect(screen.queryByText(/Compare all/)).not.toBeInTheDocument();
  });

  it("returns null for empty candidates", () => {
    const emptyMsg: ChatMessage = {
      id: "m-2",
      role: "assistant",
      content: "",
      answerMode: "disambiguate",
      disambiguation: { query: "x", candidates: [] },
    };
    const { container } = render(
      <DisambiguationCard message={emptyMsg} onPick={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });
});
