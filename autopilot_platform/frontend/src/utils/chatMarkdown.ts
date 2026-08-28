/** 轻量 Markdown → 安全 HTML（先转义再替换，避免 XSS）。 */

function escapeHtml(s: string): string {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeHref(url: string): string {
  const u = (url || "").trim();
  if (/^https?:\/\//i.test(u) || /^mailto:/i.test(u)) return u;
  return "#";
}

/** 将已转义文本中的 markdown 结构替换为 HTML。 */
export function renderChatMarkdown(src: string): string {
  const raw = String(src || "");
  if (!raw.trim()) return "";

  // 代码块（保留原文，整体 escape）
  const blocks: string[] = [];
  let text = raw.replace(/```([\w-]*)\n?([\s\S]*?)```/g, (_m, lang: string, code: string) => {
    const i = blocks.length;
    const langLabel = escapeHtml((lang || "text").trim() || "text");
    blocks.push(
      `<pre class="md-code"><code class="language-${langLabel}">${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`,
    );
    return `\u0000BLOCK${i}\u0000`;
  });

  text = escapeHtml(text);

  // 还原代码块占位
  text = text.replace(/\u0000BLOCK(\d+)\u0000/g, (_m, idx: string) => blocks[Number(idx)] || "");

  // 行内代码
  text = text.replace(/`([^`\n]+)`/g, (_m, code: string) => `<code class="md-inline">${code}</code>`);

  // 粗体 / 斜体（已 escape，* 安全）
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  // 链接 [text](url)
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label: string, url: string) => {
    const href = escapeHtml(safeHref(url.replace(/&amp;/g, "&")));
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  // 标题
  text = text.replace(/^######\s+(.+)$/gm, "<h6>$1</h6>");
  text = text.replace(/^#####\s+(.+)$/gm, "<h5>$1</h5>");
  text = text.replace(/^####\s+(.+)$/gm, "<h4>$1</h4>");
  text = text.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^#\s+(.+)$/gm, "<h1>$1</h1>");

  // 无序 / 有序列表（简单行级）
  text = text.replace(/^(?:[-*]\s+.+(?:\n|$))+?/gm, (block) => {
    const items = block
      .trim()
      .split(/\n/)
      .map((line) => line.replace(/^[-*]\s+/, "").trim())
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return items ? `<ul>${items}</ul>` : block;
  });
  text = text.replace(/^(?:\d+\.\s+.+(?:\n|$))+?/gm, (block) => {
    const items = block
      .trim()
      .split(/\n/)
      .map((line) => line.replace(/^\d+\.\s+/, "").trim())
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return items ? `<ol>${items}</ol>` : block;
  });

  // 段落：按双换行拆分，单换行转 <br>
  const parts = text.split(/\n{2,}/).map((p) => {
    const trimmed = p.trim();
    if (!trimmed) return "";
    if (/^<(?:h[1-6]|ul|ol|pre|blockquote)/.test(trimmed)) return trimmed;
    return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
  });

  return parts.filter(Boolean).join("\n");
}
