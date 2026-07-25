import { Hash, Plus } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useTopics, useMarkTopicRead, useCreateTopic } from "@/hooks/useWorkspace";
import { useUIStore } from "@/store/ui.store";
import { useProjects } from "@/hooks/useWorkspace";

export function TopicList({
  projectId,
  channelId,
}: {
  projectId: string;
  channelId: string;
}) {
  const { data: topics, isLoading } = useTopics(projectId, channelId);
  const { data: projects } = useProjects();
  const activeTopicId = useUIStore((s) => s.activeTopicId);
  const setActiveTopicId = useUIStore((s) => s.setActiveTopicId);
  const { mutate: markRead } = useMarkTopicRead(projectId, channelId);
  const { mutate: createTopic, isPending: creating } = useCreateTopic(
    projectId,
    channelId,
    // on success: auto-select the newest topic
  );

  const project = projects?.find((p) => p.id === projectId);
  const channel = project?.channels.find((c) => c.id === channelId);

  function handleNewTopic() {
    const nextNum = (topics?.length ?? 0) + 1;
    const title = `Chat #${nextNum}`;
    createTopic(
      { title },
      {
        onSuccess: (data) => {
          if (data && "id" in data) setActiveTopicId((data as { id: string }).id);
        },
      },
    );
  }

  function handleTopicClick(topicId: string) {
    setActiveTopicId(topicId);
    markRead(topicId);
  }

  return (
    <div className="flex h-full w-[220px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex items-center gap-2 border-b border-sidebar-border px-3 py-3">
        <Hash className="h-4 w-4 text-foreground-muted" />
        <span className="truncate text-sm font-semibold text-foreground flex-1">
          {channel?.name ?? "channel"}
        </span>
        <button
          type="button"
          onClick={handleNewTopic}
          disabled={creating}
          title="New conversation"
          className="rounded p-0.5 text-foreground-muted hover:bg-sidebar-accent hover:text-foreground disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-3/4" />
            <Skeleton className="h-7 w-2/3" />
          </div>
        )}
        {!isLoading && (!topics || topics.length === 0) && (
          <button
            type="button"
            onClick={handleNewTopic}
            className="w-full px-2 py-3 text-left text-xs text-foreground-muted hover:text-primary"
          >
            + Start a conversation
          </button>
        )}
        {!isLoading &&
          topics?.map((t) => {
            const active = t.id === activeTopicId;
            const unread = !active && t.has_unread;
            return (
              <button
                key={t.id}
                onClick={() => handleTopicClick(t.id)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm ${
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : unread
                      ? "text-foreground font-semibold hover:bg-sidebar-accent"
                      : "text-foreground-muted hover:bg-sidebar-accent hover:text-foreground"
                }`}
              >
                {/* Unread dot */}
                <span
                  className={`h-2 w-2 shrink-0 rounded-full transition-colors ${
                    unread ? "bg-primary" : "bg-transparent"
                  }`}
                />
                <span className="truncate">{t.title}</span>
              </button>
            );
          })}
      </div>
    </div>
  );
}
