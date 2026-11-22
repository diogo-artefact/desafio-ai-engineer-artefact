import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownMessageProps {
  content: string;
}

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <div className="flex flex-col gap-4 text-[16px] font-normal leading-[130%] text-[var(--color-ink-body)]">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="m-0 leading-[130%]">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-medium text-[var(--color-ink-primary)]">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          h1: ({ children }) => (
            <h3 className="m-0 text-[18px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
              {children}
            </h3>
          ),
          h2: ({ children }) => (
            <h4 className="m-0 text-[16px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
              {children}
            </h4>
          ),
          h3: ({ children }) => (
            <h5 className="m-0 text-[15px] font-medium leading-[130%] text-[var(--color-ink-primary)]">
              {children}
            </h5>
          ),
          ul: ({ children }) => (
            <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="m-0 flex list-decimal flex-col gap-1.5 pl-5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-[130%]">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-[var(--color-ink-primary)] underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="rounded-[6px] bg-[var(--color-bg-hover)] px-1.5 py-0.5 text-[14px] text-[var(--color-ink-primary)]">
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="m-0 overflow-x-auto rounded-[12px] border border-[var(--color-border-default)] bg-[var(--color-bg-subtle)] p-4 text-[14px] leading-[140%] text-[var(--color-ink-primary)]">
              {children}
            </pre>
          ),
          hr: () => <hr className="my-2 border-0 border-t border-[var(--color-border-default)]" />,
          blockquote: ({ children }) => (
            <blockquote className="m-0 border-l-2 border-[var(--color-border-strong)] pl-4 text-[var(--color-ink-secondary)]">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="w-full overflow-x-auto">
              <table className="w-full border-collapse text-left text-[14px] leading-[140%]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead>{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-[var(--color-border-default)]">{children}</tr>
          ),
          th: ({ children }) => (
            <th className="py-2 pr-4 font-medium text-[var(--color-ink-primary)] last:pr-0">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="tabular-nums py-2.5 pr-4 text-[var(--color-ink-body)] first:font-medium first:text-[var(--color-ink-primary)] last:pr-0">
              {children}
            </td>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}
