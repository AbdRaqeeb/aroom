import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cx } from './ui'

/** Agent output rendered as markdown. Raw HTML is never rendered. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cx('md min-w-0 text-[14.5px] leading-relaxed', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-lg border border-line">
              <table className="w-full border-collapse text-[13px]">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border-b border-line bg-sunken px-3 py-1.5 text-left font-semibold">{children}</th>,
          td: ({ children }) => <td className="border-b border-line px-3 py-1.5 align-top">{children}</td>,
          code: ({ children, className: c }) =>
            c ? (
              <code className="block">{children}</code>
            ) : (
              <code className="rounded bg-sunken px-1 py-0.5 font-mono text-[0.9em] [overflow-wrap:anywhere]">{children}</code>
            ),
          pre: ({ children }) => (
            <pre className="my-3 overflow-x-auto rounded-lg border border-line bg-sunken p-3 font-mono text-[12.5px] leading-relaxed">{children}</pre>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
