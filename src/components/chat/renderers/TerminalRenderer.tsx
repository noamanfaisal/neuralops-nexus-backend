export function TerminalRenderer({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <pre className="overflow-x-auto rounded-md border border-border bg-[hsl(220_13%_10%)] p-4 font-mono text-xs leading-relaxed">
      {lines.map((line, i) => {
        const isCmd = line.trimStart().startsWith("$");
        return (
          <div
            key={i}
            className={isCmd ? "text-[hsl(142_71%_65%)]" : "text-[hsl(0_0%_85%)]"}
          >
            {line || "\u00A0"}
          </div>
        );
      })}
    </pre>
  );
}
