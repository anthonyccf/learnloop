type MarkdownNode = { type: string; value?: string; children?: MarkdownNode[]; data?: Record<string, unknown> };

// Use the lesson's formulas to disambiguate plain variable names from identifiers.
// For example t_{\text{before}} also recognizes the older spelling t_before.
export function remarkMathNotation({ expressions = [] }: { expressions?: string[] } = {}) {
  const aliases = new Map<string, string>();
  for (const expression of expressions) {
    const variables = expression.matchAll(/(?<![A-Za-z\\])([A-Za-z])([_^])(?:\{\\(?:text|mathrm)\{([^{}]+)\}\}|\{([^{}]+)\}|([A-Za-z0-9]+))/g);
    for (const match of variables) {
      const label = match[3] || match[4] || match[5];
      if (!/^[A-Za-z0-9+-]+$/.test(label)) continue;
      aliases.set(`${match[1]}${match[2]}${label}`, match[0]);
      aliases.set(`${match[1]}${match[2]}{${label}}`, match[0]);
    }
  }
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const names = [...aliases.keys()].sort((a, b) => b.length - a.length).map(escape);
  // Explicit braces and numerical powers are mathematical notation. Unbraced
  // snake_case needs a matching formula; filenames and code are left literal.
  const pattern = new RegExp(`(?<![\\w./\\\\])(?:${[...names, "[A-Za-z](?:[_^]\\{[A-Za-z0-9,+ -]+\\})+", "(?:[A-Za-z]|[0-9]+)\\^[+-]?[0-9]+"].join("|")})(?![\\w/\\\\]|\\.[A-Za-z0-9])`, "g");
  const literal = new Set(["code", "inlineCode", "math", "inlineMath", "html", "link", "linkReference", "image"]);
  return (tree: MarkdownNode) => {
    function visit(parent: MarkdownNode) {
      if (!parent.children || literal.has(parent.type)) return;
      parent.children = parent.children.flatMap(node => {
        if (node.type !== "text" || !node.value) { visit(node); return [node]; }
        const parts: MarkdownNode[] = [];
        let offset = 0;
        for (const match of node.value.matchAll(pattern)) {
          if (match.index! > offset) parts.push({ type: "text", value: node.value.slice(offset, match.index) });
          const math = aliases.get(match[0]) || match[0].replace(/\^([+-]?\d+)/g, "^{$1}");
          parts.push({ type: "inlineMath", value: math, data: {
            hName: "code", hProperties: { className: ["language-math", "math-inline"] },
            hChildren: [{ type: "text", value: math }],
          } });
          offset = match.index! + match[0].length;
        }
        if (!parts.length) return [node];
        if (offset < node.value.length) parts.push({ type: "text", value: node.value.slice(offset) });
        return parts;
      });
    }
    visit(tree);
  };
}
