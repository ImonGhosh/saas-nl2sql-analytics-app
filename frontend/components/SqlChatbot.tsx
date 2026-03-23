"use client";

import { useAuth } from "@clerk/nextjs";
import { Bot, Plus, Send, User } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sql?: string;
};

type SqlChatbotProps = {
  onLogout: () => void;
  activeConversation?: {
    sessionId: string;
    messages: Array<{
      role: "user" | "assistant";
      content: string;
      timestamp?: string;
      sql?: string;
    }>;
  } | null;
  onConversationUpdated?: () => void;
  onNewConversation?: () => void;
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";
const clerkJwtTemplate =
  process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE ?? "backend";

function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ ...props }) => (
          <a
            {...props}
            className="text-[#7aa2f7] underline underline-offset-2"
            target={props.href?.startsWith("#") ? undefined : "_blank"}
            rel={props.href?.startsWith("#") ? undefined : "noreferrer"}
          />
        ),
        p: ({ ...props }) => <p {...props} className="whitespace-pre-wrap" />,
        ul: ({ ...props }) => <ul {...props} className="list-disc pl-6 space-y-1" />,
        ol: ({ ...props }) => <ol {...props} className="list-decimal pl-6 space-y-1" />,
        li: ({ ...props }) => <li {...props} />,
        code: ({ children, className, ...props }) => (
          <code
            {...props}
            className={[
              "rounded bg-[#111c2e] px-1 py-0.5 text-[12px] text-[#c7d2e6]",
              className ?? "",
            ].join(" ")}
          >
            {children}
          </code>
        ),
        pre: ({ ...props }) => (
          <pre
            {...props}
            className="overflow-x-auto rounded bg-[#111c2e] p-3 text-[12px] text-[#c7d2e6]"
          />
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

export default function SqlChatbot({
  onLogout,
  activeConversation,
  onConversationUpdated,
  onNewConversation,
}: SqlChatbotProps) {
  const { getToken } = useAuth();
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!activeConversation) return;
    setSessionId(activeConversation.sessionId);
    const mapped = activeConversation.messages.map((message, index) => ({
      id: `${activeConversation.sessionId}-${index}-${message.role}`,
      role: message.role,
      content: message.content,
      timestamp: message.timestamp ? new Date(message.timestamp) : new Date(),
      sql: message.sql,
    }));
    setMessages(mapped);
  }, [activeConversation]);

  const handleNewConversation = () => {
    setMessages([]);
    setSessionId(null);
    setChatInput("");
    onNewConversation?.();
  };

  const handleChatSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSending) return;
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setChatInput("");

    setIsSending(true);
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        throw new Error("Authentication required.");
      }

      const response = await fetch(`${backendUrl}/sql/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question: trimmed,
          session_id: sessionId || undefined,
        }),
      });

      let payload:
        | { answer?: string; sql?: string; session_id?: string; detail?: string }
        | null = null;
      try {
        payload = (await response.json()) as {
          answer?: string;
          detail?: string;
        };
      } catch {
        payload = null;
      }

      if (!response.ok) {
        const detail = payload?.detail || `Request failed (${response.status}).`;
        throw new Error(detail);
      }

      const answer =
        typeof payload?.answer === "string"
          ? payload.answer
          : "No response returned.";
      const sql =
        typeof payload?.sql === "string" && payload.sql.trim()
          ? payload.sql
          : undefined;
      if (!sessionId && payload?.session_id) {
        setSessionId(payload.session_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: answer,
          timestamp: new Date(),
          sql,
        },
      ]);
      onConversationUpdated?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to get response.";
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-error`,
          role: "assistant",
          content: `Error: ${message}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-[#E5ECF5]">SQL Chatbot</h2>
          <p className="mt-1 text-sm text-[#A7B6CC]">
            Ask questions about your connected Supabase database.
          </p>
        </div>
        <button
          type="button"
          onClick={handleNewConversation}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-[#2a3b5a] bg-[#14223a] text-[#A7B6CC] transition hover:bg-[#1b2f4b]"
          aria-label="New conversation"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <div className="flex min-h-[360px] flex-col overflow-hidden rounded-xl border border-[#2a3b5a] bg-[#14223a] shadow-sm">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-[#93A4BD] mt-8">
              <Bot className="mx-auto mb-3 h-12 w-12 text-[#A7B6CC]" />
              <p>Hello! I&apos;m your SQL assistant.</p>
              <p className="mt-2 text-sm">
                Ask me about your tables, metrics, or trends.
              </p>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex gap-3 ${
                message.role === "user" ? "justify-end" : "justify-start"
              }`}>
              {message.role === "assistant" && (
                <div className="flex-shrink-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-r from-[#3B82F6] to-[#2563EB]">
                    <Bot className="h-5 w-5 text-white" />
                  </div>
                </div>
              )}

              <div
                className={`max-w-[70%] rounded-lg p-3 text-sm ${
                  message.role === "user"
                    ? "bg-[linear-gradient(135deg,_#3B82F6,_#2563EB)] text-white"
                    : "border border-[#2a3b5a] bg-[#111c2e] text-[#E5ECF5]"
                }`}>
                {message.role === "assistant" ? (
                  <Markdown>{message.content}</Markdown>
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
                {message.role === "assistant" && message.sql && (
                  <details className="mt-3 rounded-md border border-[#2a3b5a] bg-[#14223a] px-3 py-2 text-xs text-[#A7B6CC]">
                    <summary className="cursor-pointer font-semibold text-[#A7B6CC]">
                      View SQL
                    </summary>
                    <pre className="mt-2 whitespace-pre-wrap text-[11px] text-[#A7B6CC]">
                      {message.sql}
                    </pre>
                  </details>
                )}
                <p
                  className={`mt-1 text-xs ${
                    message.role === "user"
                      ? "text-[#cfe0ff]"
                      : "text-[#93A4BD]"
                  }`}>
                  {message.timestamp.toLocaleTimeString()}
                </p>
              </div>

              {message.role === "user" && (
                <div className="flex-shrink-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#22304a]">
                    <User className="h-5 w-5 text-white" />
                  </div>
                </div>
              )}
            </div>
          ))}

          {isSending && (
            <div className="flex gap-3 justify-start">
              <div className="flex-shrink-0">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-r from-[#3B82F6] to-[#2563EB]">
                  <Bot className="h-5 w-5 text-white" />
                </div>
              </div>
              <div className="rounded-lg border border-[#2a3b5a] bg-[#111c2e] p-3">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-[#7aa2f7] [animation-delay:0ms]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-[#7aa2f7] [animation-delay:120ms]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-[#7aa2f7] [animation-delay:240ms]" />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form
          onSubmit={handleChatSubmit}
          className="border-t border-[#2a3b5a] bg-[#111c2e] p-4"
        >
          <div className="flex gap-2">
            <input
              type="text"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask a SQL question..."
              disabled={isSending}
              className="flex-1 rounded-lg border border-[#2a3b5a] bg-[#14223a] px-4 py-2 text-sm text-[#E5ECF5] focus:border-[#3B82F6] focus:outline-none"
            />
            <button
              type="submit"
              disabled={!chatInput.trim() || isSending}
              className="rounded-lg bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-4 py-2 text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8] disabled:cursor-not-allowed disabled:bg-[#384b77]"
              aria-label="Send message"
            >
              {isSending ? (
                <span
                  className="h-5 w-5 animate-spin rounded-full border-2 border-white/60 border-t-white"
                  aria-hidden="true"
                />
              ) : (
                <Send className="h-5 w-5" />
              )}
            </button>
          </div>
        </form>
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="w-fit rounded-md border border-[#2a3b5a] bg-[#14223a] px-6 py-3 text-sm font-semibold text-[#C7D2E6] transition hover:bg-[#1b2f4b]"
      >
        Logout
      </button>
    </div>
  );
}
