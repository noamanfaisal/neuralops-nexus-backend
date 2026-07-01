export function WebRenderer({ content }: { content: string }) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-card">
      <div className="truncate border-b border-border bg-muted px-3 py-1.5 text-xs text-muted-foreground">
        {content}
      </div>
      {/* sandbox attribute applied */}
      <iframe
        src={content}
        title="web preview"
        className="h-[400px] w-full"
        sandbox="allow-scripts allow-same-origin"
      />
    </div>
  );
}
