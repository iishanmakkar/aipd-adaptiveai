import type { ReactNode } from 'react';

/**
 * Minimal, dependency-free markdown renderer for assistant answers.
 *
 * LLM answers routinely use **bold**, *italics*, `code`, `-` bullets and
 * numbered steps; rendering them as literal text looked broken. This parses
 * only the constructs the models actually emit and returns React elements -
 * never dangerouslySetInnerHTML - so model output can't inject markup.
 */

function parseInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Order matters: code first so its contents are never formatted further.
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const token = match[0];
    const key = `${keyPrefix}-${i++}`;
    if (token.startsWith('`')) {
      nodes.push(<code key={key} className="md-code">{token.slice(1, -1)}</code>);
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  return nodes;
}

export function renderMarkdown(source: string): ReactNode {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let key = 0;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(<p key={`p-${key++}`}>{parseInline(paragraph.join(' '), `p${key}`)}</p>);
      paragraph = [];
    }
  };

  const flushList = () => {
    if (list) {
      const items = list.items.map((item, idx) => (
        <li key={`li-${key}-${idx}`}>{parseInline(item, `l${key}${idx}`)}</li>
      ));
      blocks.push(list.ordered
        ? <ol key={`ol-${key++}`} className="md-list">{items}</ol>
        : <ul key={`ul-${key++}`} className="md-list">{items}</ul>);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    if (bullet) {
      flushParagraph();
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(bullet[1]);
      continue;
    }
    if (numbered) {
      flushParagraph();
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(numbered[1]);
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      flushParagraph();
      flushList();
      const heading = line.replace(/^#{1,6}\s+/, '');
      blocks.push(<p key={`h-${key++}`} className="md-heading">{parseInline(heading, `h${key}`)}</p>);
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();

  return blocks;
}
