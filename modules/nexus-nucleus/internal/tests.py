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
             "source": "s" * 400}
            for i in range(300)
        ]
        body = json.dumps({"records": records})
        self.assertGreater(len(body), 200 * 1024)  # the point of the test
        with patch.dict(os.environ, {"INTERNAL_API_KEY": "k"}):
            r = Client().post("/api/v1/internal/usage/", data=body,
                              content_type="application/json", HTTP_X_INTERNAL_API_KEY="k")
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.json()["saved"], 300)
        self.assertEqual(UsageRecord.objects.count(), 300)


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
