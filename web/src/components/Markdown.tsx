import dockerfile from "highlight.js/lib/languages/dockerfile";
import { common } from "lowlight";
import ReactMarkdown, { type Options } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

const remarkPlugins: Options["remarkPlugins"] = [remarkGfm];
const rehypePlugins: Options["rehypePlugins"] = [[rehypeHighlight, { languages: { ...common, dockerfile } }]];

/** Markdown with GFM and code highlighting. `inline` drops the wrapping paragraph (for choice texts). */
export function Markdown({ children, inline = false }: { children: string; inline?: boolean }) {
  const markdown = (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      disallowedElements={inline ? ["p"] : undefined}
      unwrapDisallowed={inline}
    >
      {children}
    </ReactMarkdown>
  );
  return inline ? <span className="md md-inline">{markdown}</span> : <div className="md">{markdown}</div>;
}
