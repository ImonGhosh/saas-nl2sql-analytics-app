"use client";

export type ConversationSummary = {
  sessionId: string;
  title: string;
  messageCount: number;
  updatedAt: string;
};

type ConversationsBarProps = {
  conversations: ConversationSummary[];
  onSelect?: (conversation: ConversationSummary) => void;
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
}: ConversationsBarProps) {
  return (
    <aside className="w-full rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm lg:w-64">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Conversations</h3>
        <span className="text-xs text-slate-400">{conversations.length}</span>
      </div>
      {conversations.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
          No conversations yet.
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {conversations.map((conversation) => (
            <div
              key={conversation.sessionId}
              className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition hover:border-slate-300"
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
              <p className="text-sm font-semibold text-slate-800">
                {conversation.title}
              </p>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
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
