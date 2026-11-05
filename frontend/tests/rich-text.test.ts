import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RichText } from "../src/components/rich-text";

const render = (children: string) => renderToStaticMarkup(createElement(RichText, null, children));

test("assessment Markdown renders emphasis, lists, tables, and literal code", () => {
  const html = render("The correct choice is **a**.\n\n- Reduce *memory traffic*.\n- Keep `attention` unchanged.\n\n| Before | After |\n| --- | --- |\n| 10 | 5 |");
  assert.match(html, /<strong>a<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<em>memory traffic<\/em>/);
  assert.match(html, /<code>attention<\/code>/);
  assert.match(html, /<table>/);
  assert.doesNotMatch(html, /\*\*a\*\*/);
});

test("saved lessons with null-delimited inline math render formulas instead of missing glyphs", () => {
  const html = render("Codes span \u0000-7 to 7\u0000, with scale \u0000s\u0000 and \u0000x^2\u0000. `\\u0000s\\u0000` stays literal.");
  assert.equal((html.match(/class="katex"/g) || []).length, 2);
  assert.match(html, /-7 to 7/);
  assert.match(html, /<msup>/);
  assert.doesNotMatch(html, /\u0000/);
  assert.match(html, /<code>\\u0000s\\u0000<\/code>/);
});

test("feedback renders both model-style and dollar math without rewriting code", () => {
  const html = render("Use \\(x^2\\) or $y=2x$.\n\n\\[z=x+y\\]\n\n`\\(literal\\)`");
  assert.equal((html.match(/class="katex"/g) || []).length, 3);
  assert.match(html, /katex-display/);
  assert.match(html, /<code>\\\(literal\\\)<\/code>/);
});

test("generated feedback cannot execute HTML, unsafe links, or embedded images", () => {
  const html = render('<script>alert(1)</script>\n\n<img src="https://untrusted.example/pixel">\n\n[click](javascript:alert%281%29)\n\n![remote image](https://untrusted.example/image.png)');
  assert.doesNotMatch(html, /<script|<img|javascript:|untrusted\.example/);
});

test("lesson variable names use the formula's full subscript labels and numerical powers", () => {
  const html = renderToStaticMarkup(createElement(RichText, {
    mathExpressions: [String.raw`\frac{t_{\text{before}}-t_{\text{after}}}{t_{\text{before}}}`],
  }, "Here, t_before and t_after are times. Compare x^2, 10^-3 and x_{i}."));
  assert.equal((html.match(/class="katex"/g) || []).length, 5);
  assert.match(html, /<msub>/);
  assert.match(html, /<mtext>before<\/mtext>/);
  assert.match(html, /<msup>/);
});

test("notation formatting preserves code, paths, links and existing math", () => {
  const html = renderToStaticMarkup(createElement(RichText, { mathExpressions: [String.raw`t_{\text{before}}`] },
    "`t_before` and `x^2` remain code. file_name.txt and folder/t_before.txt remain paths. [t_before](https://example.com/t_before) stays a link. $t_{before}$ is already math."));
  assert.equal((html.match(/class="katex"/g) || []).length, 1);
  assert.match(html, /<code>t_before<\/code>/);
  assert.match(html, /<code>x\^2<\/code>/);
  assert.match(html, /folder\/t_before\.txt/);
  assert.match(html, /href="https:\/\/example.com\/t_before">t_before<\/a>/);
});
