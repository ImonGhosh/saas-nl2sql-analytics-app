"use client";

import { X } from "lucide-react";

export type ConversationSummary = {
  sessionId: string;
  title: string;
  messageCount: number;
  updatedAt: string;
};

type ConversationsBarProps = {
  conversations: ConversationSummary[];
  onSelect?: (conversation: ConversationSummary) => void;
  onDelete?: (conversation: ConversationSummary) => void;
};

const formatTimestamp = (value: string) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
};

export default function ConversationsBar({
  conversations,
  onSelect,
  onDelete,
}: ConversationsBarProps) {
  return (
    <aside className="w-full rounded-xl border border-[#2a3b5a] bg-[#14223a]/90 p-4 shadow-sm lg:w-64">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#C7D2E6]">Conversations</h3>
        <span className="text-xs text-[#93A4BD]">{conversations.length}</span>
      </div>
      {conversations.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-[#2a3b5a] p-4 text-center text-xs text-[#93A4BD]">
          No conversations yet.
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {conversations.map((conversation) => (
            <div
              key={conversation.sessionId}
              className="rounded-lg border border-[#2a3b5a] bg-[#111c2e] p-3 shadow-sm transition hover:border-[#3a5177]"
              role="button"
              tabIndex={0}
              onClick={() => onSelect?.(conversation)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect?.(conversation);
                }
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-semibold text-[#E5ECF5]">
                  {conversation.title}
                </p>
                {onDelete && (
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(conversation);
                    }}
                    className="rounded-full border border-transparent p-1 text-[#93A4BD] transition hover:border-[#2a3b5a] hover:text-[#E5ECF5]"
                    aria-label="Delete conversation"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-[#93A4BD]">
                <span>{conversation.messageCount} messages</span>
                <span>{formatTimestamp(conversation.updatedAt)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
