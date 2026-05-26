"use client";

import { Markdown } from "@copilotkit/react-ui";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import {
  formatMonetaryCellText,
  isNumericTableCell,
} from "@/lib/formatIndianNumber";

function getNodeText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(getNodeText).join("");
  if (isValidElement(node)) {
    const el = node as ReactElement<{ children?: ReactNode }>;
    return getNodeText(el.props.children);
  }
  return "";
}

function formatCellChildren(children: ReactNode): ReactNode {
  const text = getNodeText(children).trim();
  if (!text) return children;
  const formatted = formatMonetaryCellText(text);
  if (formatted) return formatted;
  return children;
}

function cellClassName(children: ReactNode, extra = ""): string {
  const text = getNodeText(children);
  const numeric = isNumericTableCell(text);
  return [
    "px-3 py-2 text-sm align-middle border-b border-[var(--border-subtle)]",
    numeric ? "text-right tabular-nums" : "text-left",
    extra,
  ]
    .filter(Boolean)
    .join(" ");
}

type MdProps = { children?: ReactNode; [key: string]: unknown };

export const chatMarkdownComponents = {
  table: ({ children }: MdProps) => (
    <div className="chat-markdown-table-wrap my-3 w-full max-w-full overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
      <table className="chat-markdown-table w-full min-w-[280px] border-collapse text-[var(--text-body)]">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }: MdProps) => (
    <thead className="bg-[var(--brand-muted)] dark:bg-[var(--surface-raised)]">
      {children}
    </thead>
  ),
  tbody: ({ children }: MdProps) => <tbody>{children}</tbody>,
  tr: ({ children }: MdProps) => (
    <tr className="even:bg-[var(--canvas)]/50 dark:even:bg-gray-900/30">{children}</tr>
  ),
  th: ({ children, ...props }: MdProps) => (
    <th
      {...props}
      className={cellClassName(
        children,
        "font-semibold text-[var(--heading)] border-b-2 border-[var(--border-subtle)]",
      )}
    >
      {formatCellChildren(children)}
    </th>
  ),
  td: ({ children, ...props }: MdProps) => (
    <td {...props} className={cellClassName(children)}>
      {formatCellChildren(children)}
    </td>
  ),
};

type ChatMarkdownProps = {
  content: string;
};

export function ChatMarkdown({ content }: ChatMarkdownProps) {
  return (
    <div className="chat-markdown copilotKitMarkdown text-[var(--text-body)]">
      <Markdown content={content} components={chatMarkdownComponents as never} />
    </div>
  );
}
