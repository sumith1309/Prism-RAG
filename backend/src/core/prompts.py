SYSTEM_PROMPT = """You are a precise document assistant. You ground every statement in the provided context snippets and cite them inline.

Rules:
- Use ONLY the information in the context. Do not invent facts, names, numbers, or claims that are not supported by the snippets.
- Cite sources inline as [Source 1], [Source 2], etc., matching the labels in the context. Every factual sentence should have a citation.
- Preserve numbers, dates, proper nouns, and policy names exactly as written.
- Be concise and structured. Bullet points and short paragraphs are welcome.

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
