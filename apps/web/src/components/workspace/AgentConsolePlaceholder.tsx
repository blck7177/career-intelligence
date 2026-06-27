import type { AgentConsoleProps } from "@/lib/workspace/workspaceTypes";
import { Send } from "lucide-react";

export function AgentConsolePlaceholder({ messages, disabled, placeholder }: AgentConsoleProps) {
  return (
    <div className="flex flex-col border-t border-zinc-200 bg-zinc-50/50">
      {/* Message history */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 max-h-36">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={[
              "text-xs px-3 py-2 rounded-lg max-w-[90%]",
              msg.role === "system"
                ? "bg-zinc-100 text-zinc-500 italic"
                : msg.role === "user"
                ? "ml-auto bg-zinc-800 text-white"
                : "bg-white border border-zinc-200 text-zinc-700",
            ].join(" ")}
          >
            {msg.content}
          </div>
        ))}
      </div>

      {/* Input row */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-zinc-200">
        <input
          disabled={disabled}
          placeholder={placeholder ?? "Agent chat coming soon…"}
          className="flex-1 text-xs px-2.5 py-1.5 rounded border border-zinc-200 bg-white text-zinc-400 cursor-not-allowed"
          readOnly
        />
        <button
          disabled={disabled}
          className="p-1.5 rounded text-zinc-300 cursor-not-allowed"
          tabIndex={-1}
          aria-label="Send (disabled)"
        >
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}
