import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { remarkMathNotation } from "../lib/math-notation";

export function RichText({ children, className = "", inline = false, mathExpressions = [] }: { children?: string; className?: string; inline?: boolean; mathExpressions?: string[] }) {
  if (!children) return null;
  // Normalize model-style math delimiters outside literal code spans/blocks.
  const source = children.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g)
    .map((part, index) => index % 2 ? part : part
      .replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `\n\n$$\n${math}\n$$\n\n`)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => `$${math}$`)
      // Some saved lessons wrap inline math in NUL characters. Browsers draw those as diamonds.
      // A plain word such as "to" stays text; formulas and symbols are rendered.
      .replace(/\u0000([^\u0000]+)\u0000/g, (_, math: string) => /(?<!\\)[A-Za-z]{2,}/.test(math) ? math : `$${math}$`)).join("");
  const Wrapper = inline ? "span" : "div";
  return <Wrapper className={`rich-text ${className}`}>
    <Markdown skipHtml disallowedElements={["img"]}
      remarkPlugins={[remarkGfm, remarkMath, [remarkMathNotation, { expressions: mathExpressions }]]}
      components={inline ? { p: ({ children }) => <span>{children}</span> } : undefined}
      rehypePlugins={[[rehypeKatex, { trust: false, maxExpand: 500, maxSize: 20 }]]}>
      {source}
    </Markdown>
  </Wrapper>;
}
