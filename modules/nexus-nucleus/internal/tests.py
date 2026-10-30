"""
The internal API nexus-ai calls back into. Only what the worker reads off it
is pinned here; the filtering itself is the worker's (nucleus_client.py).
"""
import os
from unittest.mock import patch

from django.test import Client

from chat.tests import MentionRightFixture
from nucleus.models import ChatMessage


class TopicHistoryInternalTests(MentionRightFixture):
    def history(self):
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().get(f"/api/v1/internal/topics/{self.t1.id}/history/", HTTP_X_INTERNAL_API_KEY="k")
        self.assertEqual(r.status_code, 200)
        return r.json()

    def reply(self, content, **metadata):
        return ChatMessage.objects.create(
            company=self.company, project=self.p1, topic=self.t1, sender=self.persona_sara.identity_user,
            content=content, sequence=ChatMessage.objects.filter(topic=self.t1).count() + 1,
            metadata={"persona_id": str(self.persona_sara.id), "persona_name": "Sara", **metadata},
        )

    def test_a_stopped_reply_is_marked_so_the_worker_can_leave_it_out(self):
        self.reply("full answer", render_as="chart", output_type="chart")
        self.reply('{"type": "bar", "ti', render_as="text", output_type="text", stopped=True)
        rows = self.history()
        self.assertEqual([(r["content"], r["stopped"], r["render_as"]) for r in rows], [
            ("full answer", False, "chart"),
            ('{"type": "bar", "ti', True, "text"),
        ])

    def test_the_wrong_key_is_refused(self):
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().get(f"/api/v1/internal/topics/{self.t1.id}/history/", HTTP_X_INTERNAL_API_KEY="nope")
        self.assertEqual(r.status_code, 401)


class SuggestAttachInternalTests(MentionRightFixture):
    """MCP suggest-attach (owner's "option 2", ruled 2026-10-22): the internal
    persona payload names the PROJECT's other external servers — name + one
    line and NOTHING else — so the engine can say "this project has X;
    someone with edit rights can attach it" without ever being able to reach
    one. Found live: "what shopping tools do you have?" → "none" while
    Shopping (demo) sat one tick away."""

    def persona_internal(self):
        # The internal endpoint 400s a persona without a prompt row — the
        # fixture's personas carry none (same seeding as PersonaInternalBriefTests).
        from nucleus.models import Prompt
        Prompt.objects.get_or_create(persona=self.persona_sara, defaults={"company": self.company, "system_prompt": "You are Sara.", "output_type": "text"})
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().get(f"/api/v1/internal/personas/{self.persona_sara.id}/", HTTP_X_INTERNAL_API_KEY="k")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_other_servers_ride_as_names_and_one_liners_only(self):
        from nucleus.models import MCPServer

        MCPServer.objects.create(
            company=self.company, project=self.p1, name="Shopping (demo)",
            description="Products, carts and orders in the demo shop.",
            transport="http", url="http://shop.example/mcp",
        )
        attached = MCPServer.objects.create(
            company=self.company, project=self.p1, name="GitHub",
            transport="http", url="http://gh.example/mcp",
        )
        self.persona_sara.mcp_servers.add(attached)
        # Another project's server must never leak across; an internal
        # capability row is not a suggestion either (it has no server to attach).
        MCPServer.objects.create(
            company=self.company, project=self.p2, name="Elsewhere",
            transport="http", url="http://e.example/mcp",
        )
        MCPServer.objects.create(
            company=self.company, project=self.p1, name="defaults",
            is_internal=True, auth_type="none", capability_config={"web_search": {}},
        )

        data = self.persona_internal()
        self.assertEqual(data["other_servers"], [
            {"name": "Shopping (demo)", "description": "Products, carts and orders in the demo shop."},
        ])
        # The attached one rides mcp_servers as always — never suggested again.
        self.assertIn("GitHub", [s["name"] for s in data["mcp_servers"]])
        # A suggestion is name + one line, and nothing else — no url, no
        # transport, no secrets, no tools (the schema pins the shape).
        self.assertEqual(set(data["other_servers"][0]), {"name", "description"})

    def test_a_persona_with_every_server_attached_suggests_nothing(self):
        from nucleus.models import MCPServer

        server = MCPServer.objects.create(
            company=self.company, project=self.p1, name="GitHub",
            transport="http", url="http://gh.example/mcp",
        )
        self.persona_sara.mcp_servers.add(server)
        self.assertEqual(self.persona_internal()["other_servers"], [])


class InternalBodySizeTests(MentionRightFixture):
    """The 64 KB pause bug (docs/MISSING.md, found live 2026-10-27): the global
    DATA_UPLOAD_MAX_MEMORY_SIZE capped every engine→nucleus POST, and a pause
    carries the whole run so far — RequestDataTooBig → 500 → the approval card
    answered "Nothing is waiting on this message". The cap is per-route now
    (16 MB global; the public hook enforces its own 64 KB), so a big pause and
    a big usage batch must simply save."""

    def _reply(self):
        return ChatMessage.objects.create(
            company=self.company, project=self.p1, topic=self.t1,
            sender=self.persona_sara.identity_user, content="working…",
            sequence=ChatMessage.objects.filter(topic=self.t1).count() + 1,
            metadata={"persona_id": str(self.persona_sara.id), "persona_name": "Sara"},
        )

    def test_a_1mb_pause_state_is_saved_intact(self):
        import json

        from nucleus.models import PausedRun

        reply = self._reply()
        state = "x" * (1024 * 1024)  # far over the old 64 KB wall
        body = {
            "job_id": "job-1", "topic_id": str(self.t1.id),
            "persona_id": str(self.persona_sara.id), "state": state,
            "catalog_hash": "h1", "role": "STANDARD",
            "pending": [{"call_id": "c1", "tool": "aaf_analytics__run_sql",
                         "capability_id": "prefixed-s1", "args_preview": "SELECT 1",
                         "kind": "approval"}],
        }
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().post(
                f"/api/v1/internal/messages/{reply.id}/pause/",
                data=json.dumps(body), content_type="application/json",
                HTTP_X_INTERNAL_API_KEY="k",
            )
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.json(), {"ok": True, "pending": 1})
        row = PausedRun.objects.get(message_id=reply.id)
        self.assertEqual(len(row.state), len(state))      # stored intact, not truncated
        self.assertEqual(row.state[:4], "xxxx")
        self.assertEqual(row.pending[0]["call_id"], "c1")

    def test_a_200kb_usage_batch_is_accepted(self):
        import json

        from django.utils import timezone

        from nucleus.models import UsageRecord

        called_at = timezone.now().isoformat()
        records = [
            {"message_id": f"m-{i}", "job_id": f"j-{i}", "kind": "chat_reply",
             "provider": "openai", "model_id": "gpt-test", "role": "STANDARD",
             "input_tokens": 1000, "output_tokens": 50, "called_at": called_at,
             # source is a varchar(50) — stay within the REAL column; the body
             # gets its size from the record count, not from an oversized field.
             "source": "s" * 50}
            for i in range(1000)  # ~240 bytes each ≈ 235 KB on the wire
        ]
        body = json.dumps({"records": records})
        self.assertGreater(len(body), 200 * 1024)  # the point of the test
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().post("/api/v1/internal/usage/", data=body,
                              content_type="application/json", HTTP_X_INTERNAL_API_KEY="k")
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.json()["saved"], 1000)
        self.assertEqual(UsageRecord.objects.count(), 1000)


class PersonaInternalBriefTests(MentionRightFixture):
    def payload(self):
        from nucleus.models import Prompt
        Prompt.objects.get_or_create(persona=self.persona_sara, defaults={"company": self.company, "system_prompt": "You are Sara.", "output_type": "text"})
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().get(f"/api/v1/internal/personas/{self.persona_sara.id}/", HTTP_X_INTERNAL_API_KEY="k")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_the_project_brief_rides_with_the_persona(self):
        self.p1.brief = "Ship the Q4 launch."
        self.p1.save(update_fields=["brief"])
        self.assertEqual(self.payload()["project_brief"], "Ship the Q4 launch.")

    def test_no_brief_is_null_not_an_empty_block(self):
        self.assertIsNone(self.payload()["project_brief"])
