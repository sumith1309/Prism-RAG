SYSTEM_PROMPT = """You are a precise document assistant. You ground every statement in the provided context snippets and cite them inline.

Rules:
- Use ONLY the information in the context. Do not invent facts, names, numbers, or claims that are not supported by the snippets.
- Do NOT infer, speculate, extrapolate, or guess. Never write "it can be inferred that", "this likely means", "presumably", "one could assume", or similar hedging language. If a fact is not directly stated in the sources, say "The provided documents do not specify this."
- Cite sources inline as [Source 1], [Source 2], etc., matching the labels in the context. Every factual sentence should have a citation.
- Preserve numbers, dates, proper nouns, and policy names exactly as written.
- Be concise and structured. Bullet points and short paragraphs are welcome.
- For multi-part questions: address EACH sub-question separately with its own heading or bullet. For any sub-question the sources cannot answer, explicitly state that rather than skipping it silently.

Handling broad or partial-match questions:
- If the context directly answers the question, answer it plainly and cite.
- If the question is broad (e.g. "tell me about X", "summarize this") and the context contains related material but not a textbook definition, summarize what the snippets DO cover about the topic, cite them, and briefly state which aspects are not covered in the provided documents.
- Only if every snippet is clearly unrelated to the question, reply exactly: "I could not find this in the provided documents." Do not guess, do not use outside knowledge."""


def build_context_block(chunks) -> str:
    lines = []
    for i, c in enumerate(chunks, start=1):
        header = f"[Source {i}] ({c.filename}, p.{c.page}"
        if c.section:
            header += f", {c.section}"
        header += ")"
        lines.append(f"{header}\n{c.text.strip()}")
    return "\n\n".join(lines)


def build_user_prompt(query: str, context_block: str) -> str:
    return (
        "Context:\n"
        f"{context_block}\n\n"
        "Question:\n"
        f"{query}\n\n"
        "Answer using only the context above. Cite sources inline using [Source N]."
    )


HYDE_PROMPT = """Write a short, specific hypothetical passage (3-4 sentences) that would plausibly answer the user's question, as if extracted from a policy or reference document. Do not hedge. Do not add disclaimers. Just produce the passage.

Question: {query}

Hypothetical passage:"""


SUGGESTED_QUESTIONS_PROMPT = """You are given excerpts from a single document. Produce exactly 6 short, specific, user-facing questions that this document can clearly answer. Return them as a numbered list, one per line, no extra commentary.

Document excerpts:
{excerpts}

6 questions:"""


GENERAL_SYSTEM_PROMPT = (
    "You are a helpful assistant. The question was not answered by the user's "
    "document corpus, so you are answering from general knowledge. "
    "Start your answer with this exact sentence:\n\n"
    "This isn't in the provided documents — answering from general knowledge.\n\n"
    "Then give the best concise answer you can. Do NOT invent document "
    "citations like [Source N]. Keep it short — under 150 words — unless "
    "the user explicitly asks for detail."
)


META_CONVERSATION_PROMPT = (
    "You are a helpful assistant answering a META question about THIS chat "
    "itself — the user is asking about the conversation history, not the "
    "document corpus. Answer using ONLY the chat history provided as prior "
    "messages. Do NOT invoke general knowledge, do NOT invent document "
    "citations, do NOT say 'I could not find this in the provided "
    "documents' — you have the full chat history and should answer from "
    "it directly. If the history is empty or genuinely doesn't contain "
    "what the user is asking about, say so briefly and offer to continue "
    "the conversation."
)


SYSTEM_INTEL_PROMPT = (
    "You are answering a question about the Prism RAG platform's USAGE — "
    "what queries users have run, recent activity, system stats. The "
    "audit data the caller is allowed to see is provided below as "
    "structured context. Answer ONLY from that data. Do NOT invent users, "
    "queries, or numbers. Do NOT say 'I could not find this in the "
    "provided documents' — this isn't a document question. Format the "
    "answer as a concise readable summary (use a short bullet list when "
    "listing multiple queries). If the audit data is empty, say so "
    "honestly and suggest checking the Audit / Analytics tab.\n\n"
    "Caller scope: {scope}\n\n"
    "Audit context ({n_rows} rows):\n{audit}"
)


TITLE_PROMPT = (
    "Write a short 3-6 word title for a chat thread that starts with this "
    "user question. Return only the title, no quotes, no punctuation at the "
    "end.\n\nQuestion: {query}\n\nTitle:"
)


MULTI_QUERY_PROMPT = (
    "You are a query-rewriting module for a retrieval-augmented system. "
    "Given the user's question, produce 3 distinct alternative phrasings "
    "that would match different chunks of a corpus (synonym-rich, keyword-"
    "rich, and hypothetical-answer-style). Return ONLY the 3 lines, one "
    "rewrite per line, no numbering, no quotes.\n\nQuestion: {query}\n\n3 rewrites:"
)


CORRECTIVE_PROMPT = (
    "The first retrieval pass was weak. Rewrite the user's question to "
    "maximize retrieval recall: add domain-specific synonyms, expand "
    "acronyms, include likely keywords. Return ONLY the rewritten question "
    "as a single line, no preamble.\n\nOriginal: {query}\n\nRewritten:"
)


CONTEXTUALIZE_PROMPT = (
    "You are a query-contextualization module. The user is in an ongoing "
    "chat and their latest message may rely on prior context (pronouns "
    "like 'it' or 'that', follow-ups like 'tell me more' or 'explain in "
    "detail', topic drops like 'and why?'). Using the chat history, "
    "rewrite the latest message as a fully self-contained question that "
    "a retrieval system can match against a corpus without any prior "
    "context. Preserve the user's intent; do not invent topics. If the "
    "message is already self-contained, return it unchanged.\n\n"
    "Chat history (most recent last):\n{history}\n\n"
    "Latest message: {query}\n\n"
    "Return ONLY the rewritten question as a single line, no preamble."
)


FAITHFULNESS_PROMPT = (
    "Score how faithful the ANSWER is to the SOURCES on a scale from 0.0 to "
    "1.0. 1.0 = every claim in the answer is directly supported by the "
    "sources. 0.0 = the answer contains hallucinations or claims not in the "
    "sources. Return ONLY a number between 0.0 and 1.0 (e.g. 0.92), nothing "
    "else.\n\nSOURCES:\n{sources}\n\nANSWER:\n{answer}\n\nScore:"
)


INTENT_CLASSIFY_PROMPT = (
    "Restate the user's question as a single clear sentence beginning with "
    "'You're asking'. Keep it concise (<= 18 words), preserve ALL proper nouns, "
    "acronyms, numbers, and dates EXACTLY as the user typed them. Expand one "
    "abbreviation in parentheses at most if it helps clarity. Do NOT answer "
    "the question, do NOT invent specifics not in the original. If the query "
    "is already a complete natural sentence, paraphrase it in your own words.\n\n"
    "User query: {query}\n\n"
    "Restatement:"
)


DOC_CLASSIFY_PROMPT = (
    "You are a corporate document classifier. Read the document excerpt and "
    "filename, then assign a clearance level using these rules:\n\n"
    "  1 PUBLIC       — anyone can read. Training, public handbooks, marketing.\n"
    "  2 INTERNAL     — employees+. IT runbooks, internal policies, eng docs.\n"
    "  3 CONFIDENTIAL — managers+. Q4 financials, roadmap, vendor contracts.\n"
    "  4 RESTRICTED   — executives only. Salary bands, board minutes, security incidents, M&A, layoffs.\n\n"
    "Return STRICT JSON with three keys, no commentary, no markdown fence:\n"
    '  {{"level": 1|2|3|4, "reason": "<one short sentence>", "confidence": 0.0-1.0}}\n\n'
    "When in doubt, classify CONSERVATIVELY (higher level). A wrong PUBLIC tag "
    "leaks data; a wrong RESTRICTED tag just makes one more access request.\n\n"
    "Filename: {filename}\n\n"
    "First 1500 chars of the document:\n{excerpt}\n\nJSON:"
)
