import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { ServerList } from "@/components/auth/ServerList";
import { useAuthStore } from "@/store/auth.store";
import { Button } from "@/components/ui/button";
import { signOut } from "@/services/auth.service";
import { Sparkles } from "lucide-react";

export const Route = createFileRoute("/servers")({
  head: () => ({
    meta: [{ title: "Select a server — NeuralOps" }],
  }),
  component: ServersPage,
});

function ServersPage() {
  const navigate = useNavigate();
  const supabaseToken = useAuthStore((s) => s.supabaseToken);
  const email = useAuthStore((s) => s.email);
  const clearAuth = useAuthStore((s) => s.clearAuth);

  useEffect(() => {
    if (!supabaseToken) navigate({ to: "/", replace: true });
  }, [supabaseToken, navigate]);

  async function handleSignOut() {
    try {
      await signOut();
    } catch {
      /* ignore */
    }
    clearAuth();
    navigate({ to: "/" });
  }

  return (
    <div className="flex min-h-screen items-start justify-center bg-background-subtle px-4 py-12">
      <div className="w-full max-w-xl">
        <div className="mb-8 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                Select a server
              </h1>
              {email && (
                <p className="mt-0.5 text-xs text-foreground-muted">
                  Welcome back, {email}
                </p>
              )}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={handleSignOut}>
            Sign out
          </Button>
        </div>
        <ServerList />
      </div>
    </div>
  );
}
