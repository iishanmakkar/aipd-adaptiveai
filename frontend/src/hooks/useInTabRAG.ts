import { useCallback, useMemo, useState } from 'react';

interface IndexableMessage {
  content: string;
  role: string;
}

interface IndexedChunk {
  text: string;
  source: string;
  tokens: Map<string, number>;
}

function tokenize(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (const tok of text.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2)) {
    counts.set(tok, (counts.get(tok) ?? 0) + 1);
  }
  return counts;
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (const [, v] of a) na += v * v;
  for (const [, v] of b) nb += v * v;
  if (na === 0 || nb === 0) return 0;
  for (const [k, v] of a) dot += v * (b.get(k) ?? 0);
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

function chunkText(text: string, maxChars = 800): string[] {
  const out: string[] = [];
  for (let i = 0; i < text.length; i += maxChars) out.push(text.slice(i, i + maxChars));
  return out.filter((c) => c.trim().length > 40);
}

/**
 * Phase 1.3 — In-tab RAG (offline-first, no model download).
 * Indexes the current page DOM + chat history with TF cosine similarity.
 * Falls back to backend RAG (returns null) when nothing local matches.
 */
export function useInTabRAG() {
  const [indexed, setIndexed] = useState<IndexedChunk[]>([]);
  const [indexedAt, setIndexedAt] = useState<number | null>(null);

  // Builds the index synchronously and returns it, so callers can query
  // the fresh chunks immediately instead of waiting for React state.
  const indexPage = useCallback((history: IndexableMessage[]): IndexedChunk[] => {
    const chunks: IndexedChunk[] = [];
    const bodyText = document.body?.innerText ?? '';
    for (const c of chunkText(bodyText)) {
      chunks.push({ text: c, source: 'page-dom', tokens: tokenize(c) });
    }
    for (const m of history.slice(-20)) {
      for (const c of chunkText(m.content, 600)) {
        chunks.push({ text: c, source: `chat:${m.role}`, tokens: tokenize(c) });
      }
    }
    setIndexed(chunks);
    setIndexedAt(Date.now());
    return chunks;
  }, []);

  const searchChunks = useCallback(
    (chunks: IndexedChunk[], question: string, topK = 3): { text: string; source: string }[] | null => {
      if (chunks.length === 0) return null;
      const q = tokenize(question);
      const scored = chunks
        .map((c) => ({ c, s: cosine(q, c.tokens) }))
        .filter((r) => r.s > 0.05)
        .sort((x, y) => y.s - x.s)
        .slice(0, topK);
      if (scored.length === 0) return null; // caller falls back to backend RAG
      return scored.map((r) => ({ text: r.c.text, source: r.c.source }));
    },
    [],
  );

  const askPage = useCallback(
    (question: string, topK = 3): { text: string; source: string }[] | null =>
      searchChunks(indexed, question, topK),
    [indexed, searchChunks],
  );

  // Build + search in one synchronous pass: no stale-state fallthrough on
  // the first click. Also commits the fresh index for later askPage calls.
  const askFresh = useCallback(
    (history: IndexableMessage[], question: string, topK = 3) => {
      const fresh = indexPage(history);
      return searchChunks(fresh, question, topK);
    },
    [indexPage, searchChunks],
  );

  const stats = useMemo(
    () => ({ chunks: indexed.length, indexedAt }),
    [indexed.length, indexedAt],
  );

  return { indexPage, askPage, askFresh, stats };
}
