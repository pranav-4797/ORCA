import { escapeHtml } from './helpers';
import { ICONS } from './icons';

export function renderMarkdown(markdown: string): string {
  if (!markdown) return '';

  let html = markdown;

  // 1. Code blocks with language tags
  // Replace ```lang ... ``` with structured HTML container
  const codeBlockRegex = /```([a-zA-Z0-9_\-\+\.]*)\n([\s\S]*?)```/g;
  html = html.replace(codeBlockRegex, (_match, lang, code) => {
    const language = (lang || 'plaintext').trim().toLowerCase();
    const rawCode = code.replace(/\n$/, '');
    const escapedCode = escapeHtml(rawCode);
    const highlighted = highlightSyntax(escapedCode, language);

    return `
      <div class="code-block-container" data-language="${language}">
        <div class="code-block-header">
          <div class="code-block-lang">
            <span class="code-lang-dot"></span>
            <span>${language}</span>
          </div>
          <button class="code-copy-btn" data-code="${encodeURIComponent(rawCode)}" title="Copy code" aria-label="Copy code">
            <span class="copy-icon">${ICONS.copy}</span>
            <span class="copy-label">Copy</span>
          </button>
        </div>
        <pre class="code-block-pre"><code class="language-${language}">${highlighted}</code></pre>
      </div>
    `;
  });

  // 2. GitHub-style callouts/alerts (> [!NOTE], > [!TIP], > [!IMPORTANT], > [!WARNING], > [!CAUTION])
  const alertRegex = /^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n((?:>.*(?:\n|$))*)/gim;
  html = html.replace(alertRegex, (_match, type, content) => {
    const alertType = type.toLowerCase();
    const cleanContent = content.replace(/^>\s?/gm, '').trim();
    const alertTitle = type.toUpperCase();
    return `
      <div class="callout callout-${alertType}">
        <div class="callout-header">
          <span class="callout-icon">${getCalloutIcon(alertType)}</span>
          <span class="callout-title">${alertTitle}</span>
        </div>
        <div class="callout-body">${renderInlineMarkdown(cleanContent)}</div>
      </div>
    `;
  });

  // 3. Regular blockquotes
  html = html.replace(/^>\s+(.+)$/gm, '<blockquote class="md-blockquote"><p>$1</p></blockquote>');

  // 4. Tables
  const tableRegex = /(?:\|(?:[^\n\r|]+\|)+\r?\n){2,}(?:\|(?:[^\n\r|]+\|)+(?:\r?\n|$))*/g;
  html = html.replace(tableRegex, (tableText) => {
    const lines = tableText.trim().split('\n').map(l => l.trim());
    if (lines.length < 2) return tableText;

    const headers = lines[0].split('|').slice(1, -1).map(h => h.trim());
    const isAlignRow = lines[1].includes('---');
    const dataRows = isAlignRow ? lines.slice(2) : lines.slice(1);

    let tableHtml = '<div class="table-wrapper"><table class="md-table"><thead><tr>';
    headers.forEach(h => {
      tableHtml += `<th>${renderInlineMarkdown(h)}</th>`;
    });
    tableHtml += '</tr></thead><tbody>';

    dataRows.forEach(row => {
      if (!row.trim()) return;
      const cells = row.split('|').slice(1, -1).map(c => c.trim());
      tableHtml += '<tr>';
      cells.forEach(c => {
        tableHtml += `<td>${renderInlineMarkdown(c)}</td>`;
      });
      tableHtml += '</tr>';
    });

    tableHtml += '</tbody></table></div>';
    return tableHtml;
  });

  // 5. Headings
  html = html.replace(/^### (.*$)/gim, '<h3 class="md-h3">$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2 class="md-h2">$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1 class="md-h1">$1</h1>');
  html = html.replace(/^#### (.*$)/gim, '<h4 class="md-h4">$1</h4>');

  // 6. Horizontal Rules
  html = html.replace(/^---$/gm, '<hr class="md-hr" />');

  // 7. Math blocks ($$...$$)
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, '<div class="math-block"><span class="math-tex">$1</span></div>');

  // 8. Inline markdown (bold, italic, inline code, inline math, links)
  html = renderInlineMarkdown(html);

  // 9. Unordered Lists
  html = html.replace(/^\s*[-*]\s+(.*)$/gm, '<li class="md-li">$1</li>');
  html = html.replace(/(<li class="md-li">[\s\S]*?<\/li>(\n|$))+/g, '<ul class="md-ul">$&</ul>');

  // 10. Ordered Lists
  html = html.replace(/^\s*(\d+)\.\s+(.*)$/gm, '<li class="md-oli" data-num="$1">$2</li>');
  html = html.replace(/(<li class="md-oli"[^>]*>[\s\S]*?<\/li>(\n|$))+/g, '<ol class="md-ol">$&</ol>');

  // 11. Paragraphs (lines that are not enclosed in HTML tags)
  const blockTags = ['div', 'p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'blockquote', 'table', 'hr', 'pre'];
  const blockRegex = new RegExp(`^<(${blockTags.join('|')})`, 'i');

  const lines = html.split('\n\n');
  const processed = lines.map(block => {
    const trimmed = block.trim();
    if (!trimmed) return '';
    if (blockRegex.test(trimmed)) {
      return trimmed;
    }
    return `<p class="md-p">${trimmed.replace(/\n/g, '<br/>')}</p>`;
  });

  return processed.join('\n');
}

export function renderInlineMarkdown(text: string): string {
  if (!text) return '';

  return text
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
    // Inline math $...$
    .replace(/\$([^\$\n]+)\$/g, '<span class="inline-math">$1</span>')
    // Bold + Italic
    .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
    // Bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>');
}

function getCalloutIcon(type: string): string {
  switch (type) {
    case 'tip':
      return ICONS.zap;
    case 'important':
      return ICONS.shield;
    case 'warning':
    case 'caution':
      return ICONS.sparkles;
    case 'note':
    default:
      return ICONS.brain;
  }
}

// Lightweight syntax highlighting tokenizer
function highlightSyntax(code: string, language: string): string {
  if (['typescript', 'javascript', 'js', 'ts', 'jsx', 'tsx', 'json'].includes(language)) {
    return code
      // Comments
      .replace(/(\/\/[^\n]*)/g, '<span class="tok-comment">$1</span>')
      .replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="tok-comment">$1</span>')
      // Strings
      .replace(/(".*?"|'.*?'|`.*?`)/g, '<span class="tok-string">$1</span>')
      // Keywords
      .replace(/\b(import|export|from|class|interface|type|extends|implements|const|let|var|function|return|if|else|for|while|switch|case|break|try|catch|finally|throw|new|async|await|public|private|protected|readonly|static|get|set|true|false|null|undefined|this|super)\b/g, '<span class="tok-keyword">$1</span>')
      // Types / Interfaces
      .replace(/\b(Promise|Record|Partial|Required|Array|Map|Set|AbortSignal|AbortController|DOMException|number|string|boolean|void|any|unknown|never)\b/g, '<span class="tok-type">$1</span>')
      // Numbers
      .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="tok-number">$1</span>');
  }

  if (['python', 'py'].includes(language)) {
    return code
      .replace(/(#[^\n]*)/g, '<span class="tok-comment">$1</span>')
      .replace(/(".*?"|'.*?'|""".*?""")/g, '<span class="tok-string">$1</span>')
      .replace(/\b(def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|pass|lambda|yield|True|False|None|self|async|await)\b/g, '<span class="tok-keyword">$1</span>')
      .replace(/\b(\d+)\b/g, '<span class="tok-number">$1</span>');
  }

  return code;
}
