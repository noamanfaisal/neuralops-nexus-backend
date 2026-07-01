import { useEffect, useRef, useState } from "react";
import { Paperclip, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const MOCK_PERSONAS = [
  { id: "p1", name: "Nova" },
  { id: "p2", name: "Sara" },
  { id: "p3", name: "Atlas" },
];

export function MessageInput({
  disabled,
  onSend,
  placeholder,
}: {
  disabled?: boolean;
  onSend?: (text: string, file?: File) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const maxHeight = 6 * 24;
    ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`;
  }, [text]);

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    setText(v);
    // simple @mention detection
    const caret = e.target.selectionStart;
    const upto = v.slice(0, caret);
    const m = upto.match(/@(\w*)$/);
    if (m) {
      setMentionOpen(true);
      setMentionQuery(m[1].toLowerCase());
    } else {
      setMentionOpen(false);
    }
  }

  function pickMention(name: string) {
    setText((t) => t.replace(/@(\w*)$/, `@${name} `));
    setMentionOpen(false);
    textareaRef.current?.focus();
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const trimmed = text.trim();
    if (!trimmed && !file) return;
    onSend?.(trimmed, file ?? undefined);
    setText("");
    setFile(null);
  }

  if (disabled) {
    return (
      <div className="border-t border-sidebar-border bg-sidebar px-4 py-3 text-center text-sm text-foreground-muted">
        {placeholder ?? "Select a conversation to start messaging"}
      </div>
    );
  }

  const suggestions = MOCK_PERSONAS.filter((p) =>
    p.name.toLowerCase().startsWith(mentionQuery),
  );

  return (
    <div className="relative border-t border-sidebar-border bg-sidebar px-3 py-3">
      {file && (
        <div className="mb-2 inline-flex items-center gap-2 rounded-md border border-border bg-card px-2 py-1 text-xs">
          <span className="max-w-[240px] truncate">{file.name}</span>
          <button
            type="button"
            onClick={() => setFile(null)}
            className="text-foreground-muted hover:text-foreground"
            aria-label="Remove file"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {mentionOpen && suggestions.length > 0 && (
        <div className="absolute bottom-full left-3 mb-2 w-56 rounded-md border border-border bg-popover p-1 shadow-md">
          {suggestions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => pickMention(s.name)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground"
            >
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-[10px] font-semibold text-accent-foreground">
                {s.name.slice(0, 1)}
              </span>
              {s.name}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2 rounded-md border border-border bg-background px-2 py-1.5">
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept="image/*,.pdf,.doc,.docx,.txt,.csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach file"
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKey}
          rows={1}
          placeholder="Type a message... (@ to mention)"
          className="max-h-36 min-h-[24px] flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-foreground-muted"
        />
        <Button
          type="button"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={submit}
          disabled={!text.trim() && !file}
          aria-label="Send"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
