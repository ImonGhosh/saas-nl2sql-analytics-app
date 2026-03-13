"use client";

import { Bot, Send, User } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
};

type SqlChatbotProps = {
  onLogout: () => void;
};

export default function SqlChatbot({ onLogout }: SqlChatbotProps) {
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleChatSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      },
    ]);
    setChatInput("");
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">SQL Chatbot</h2>
        <p className="mt-1 text-sm text-slate-600">
          Ask questions about your connected Supabase database.
        </p>
      </div>
      <div className="flex min-h-[360px] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-slate-400 mt-8">
              <Bot className="mx-auto mb-3 h-12 w-12 text-slate-400" />
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
              }`}
            >
              {message.role === "assistant" && (
                <div className="flex-shrink-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900">
                    <Bot className="h-5 w-5 text-white" />
                  </div>
                </div>
              )}

              <div
                className={`max-w-[70%] rounded-lg p-3 text-sm ${
                  message.role === "user"
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-800"
                }`}
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
                <p
                  className={`mt-1 text-xs ${
                    message.role === "user"
                      ? "text-slate-300"
                      : "text-slate-400"
                  }`}
                >
                  {message.timestamp.toLocaleTimeString()}
                </p>
              </div>

              {message.role === "user" && (
                <div className="flex-shrink-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-600">
                    <User className="h-5 w-5 text-white" />
                  </div>
                </div>
              )}
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>

        <form
          onSubmit={handleChatSubmit}
          className="border-t border-slate-200 bg-slate-50 p-4"
        >
          <div className="flex gap-2">
            <input
              type="text"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask a SQL question..."
              className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
            />
            <button
              type="submit"
              disabled={!chatInput.trim()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              aria-label="Send message"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
        </form>
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="w-fit rounded-md border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
      >
        Logout
      </button>
    </div>
  );
}
