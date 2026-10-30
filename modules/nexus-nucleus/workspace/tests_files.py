"""
Step 5 — the project file viewer (docs/NUCLEUS-REVAMP.md §3).

Browse, download, view-as-HTML over the project's folder, with the walls
proven: paths can't leave the folder (`..`, absolute, symlinks out), big
files are download-only, binary is never "rendered", rendered pages carry
CSP sandbox, and someone without the project gets a 404 like everywhere else.
"""
import os
import shutil
import tempfile
from pathlib import Path

from django.test import Client

from chat.tests import MentionRightFixture
from nucleus.models import CompanyAccess, User
from workspace.services import get_project_folder_name


class FileViewerTests(MentionRightFixture):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="nx-files-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = self.settings(PROJECTS_ROOT=Path(self.tmp))
        override.enable()
        self.addCleanup(override.disable)

        self.root = Path(self.tmp) / get_project_folder_name(self.p1)
        (self.root / "sub").mkdir(parents=True)
        (self.root / "readme.md").write_text("# Hello\n\nSome **bold** text.\n")
        (self.root / "script.py").write_text("print('hi')\n")
        (self.root / "data.bin").write_bytes(b"\x00\x01\x02\x03")
        (self.root / "sub" / "note.txt").write_text("plain note")
        # A symlink pointing OUT of the project folder — must never be served.
        os.symlink("/etc/hostname", self.root / "sneaky")

        self.base = f"/api/v1/projects/{self.p1.id}/files/"

    def listing(self, user, path=""):
        return self.call("get", self.base, user, {"path": path} if path else None)

    def content(self, user, path, as_html=False):
        params = {"path": path}
        if as_html:
            params["as"] = "html"
        return self.call("get", f"{self.base}content/", user, params)

    @staticmethod
    def body(response) -> bytes:
        if hasattr(response, "streaming_content"):
            return b"".join(response.streaming_content)
        return response.content

    # ── Browse ────────────────────────────────────────────────────────────

    def test_listing_shows_folders_first_then_files(self):
        r = self.listing(self.owner)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["path"], "")
        self.assertFalse(data["truncated"])
        names = [e["name"] for e in data["entries"]]
        self.assertEqual(names[0], "sub")                      # folders first
        self.assertEqual(data["entries"][0]["type"], "dir")
        self.assertIn("readme.md", names)
        readme = next(e for e in data["entries"] if e["name"] == "readme.md")
        self.assertEqual(readme["type"], "file")
        self.assertGreater(readme["size"], 0)
        self.assertTrue(readme["modified"])

    def test_listing_a_subfolder(self):
        r = self.listing(self.owner, "sub")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["path"], "sub")
        self.assertEqual([e["name"] for e in data["entries"]], ["note.txt"])

    def test_a_viewer_can_browse_but_an_outsider_404s(self):
        r = self.listing(self.vera)                            # company Viewer
        self.assertEqual(r.status_code, 200, r.content)
        outsider = User.objects.create_user(username="out", email="out@acme.test", password="x")
        CompanyAccess.objects.create(company=self.company, user=outsider, role="member", invited_by=self.owner)
        r = self.listing(outsider)                             # no role → no project
        self.assertEqual(r.status_code, 404, r.content)

    def test_a_project_with_no_folder_yet_is_a_409(self):
        r = self.call("get", f"/api/v1/projects/{self.p2.id}/files/", self.owner)
        self.assertEqual(r.status_code, 409, r.content)

    # ── Download ──────────────────────────────────────────────────────────

    def test_download_returns_the_bytes_as_an_attachment(self):
        r = self.content(self.owner, "script.py")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.body(r), b"print('hi')\n")
        self.assertIn("attachment", r.headers.get("Content-Disposition", ""))

    def test_missing_file_and_mixed_up_kinds(self):
        self.assertEqual(self.content(self.owner, "nope.txt").status_code, 404)
        self.assertEqual(self.content(self.owner, "sub").status_code, 400)      # a folder
        self.assertEqual(self.listing(self.owner, "readme.md").status_code, 400)  # a file

    # ── The wall ──────────────────────────────────────────────────────────

    def test_paths_cannot_leave_the_project_folder(self):
        self.assertEqual(self.listing(self.owner, "../").status_code, 400)
        self.assertEqual(self.content(self.owner, "../../etc/passwd").status_code, 400)
        # A leading slash is read project-relative (friendly to frontends),
        # so this asks for <project>/etc/passwd — which simply doesn't exist.
        self.assertEqual(self.content(self.owner, "/etc/passwd").status_code, 404)
        # A symlink that points out resolves out — refused the same way.
        self.assertEqual(self.content(self.owner, "sneaky").status_code, 400)
        self.assertEqual(self.content(self.owner, "sneaky", as_html=True).status_code, 400)

    # ── View as HTML ──────────────────────────────────────────────────────

    def test_markdown_views_as_a_sandboxed_html_page(self):
        r = self.content(self.owner, "readme.md", as_html=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("text/html", r.headers["Content-Type"])
        self.assertEqual(r.headers.get("Content-Security-Policy"), "sandbox")
        self.assertIn(b"Hello", r.content)
        # Rendered (markdown installed) or readable escaped text (not yet) —
        # both are a page, never a blank or an error.
        self.assertTrue(b"<h1>" in r.content or b"<pre>" in r.content, r.content)

    def test_code_views_as_html_too(self):
        r = self.content(self.owner, "script.py", as_html=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(b"print", r.content)

    def test_big_files_are_download_only(self):
        from workspace import files as file_viewer
        (self.root / "big.txt").write_bytes(b"x" * (file_viewer.RENDER_MAX_BYTES + 1))
        r = self.content(self.owner, "big.txt", as_html=True)
        self.assertEqual(r.status_code, 413)
        r = self.content(self.owner, "big.txt")                # download still fine
        self.assertEqual(r.status_code, 200)

    def test_binary_is_never_rendered(self):
        r = self.content(self.owner, "data.bin", as_html=True)
        self.assertEqual(r.status_code, 415)
        r = self.content(self.owner, "data.bin")               # download still fine
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.body(r), b"\x00\x01\x02\x03")


# ── Part 2: one-use download tickets ──────────────────────────────────

from unittest.mock import patch  # noqa: E402

from chat.stop_signals import MemoryStore  # noqa: E402
from workspace import files as file_viewer  # noqa: E402


class DownloadTicketTests(FileViewerTests):
    """FILE-VIEWER-PANE §3: a short-lived, single-use ticket — minted with the
    project read, honoured with no login at all, dead after one use."""

    def setUp(self):
        super().setUp()
        # The shared store, swapped for a memory one with a steerable clock —
        # the same pattern the hooks tests use.
        self.clock = [0.0]
        self.store = MemoryStore(now=lambda: self.clock[0])
        patcher = patch("chat.stop_signals.signal_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mint(self, user, path):
        return self.call("post", f"{self.base}ticket/", user, {"path": path})

    def fetch(self, url):
        """The public GET — deliberately WITHOUT any Authorization header."""
        return Client().get(url)

    def test_a_ticket_downloads_the_file_once_and_only_once(self):
        r = self.mint(self.owner, "script.py")
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        self.assertEqual(out["expires_in"], file_viewer.TICKET_TTL_SECONDS)
        self.assertTrue(out["url"].startswith("/api/v1/files/download/"))
        first = self.fetch(out["url"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.body(first), b"print('hi')\n")
        self.assertIn("attachment", first.headers.get("Content-Disposition", ""))
        # One use: the second GET of the SAME url is refused.
        self.assertEqual(self.fetch(out["url"]).status_code, 410)

    def test_an_expired_or_unknown_ticket_answers_the_same_410(self):
        out = self.mint(self.owner, "script.py").json()
        self.clock[0] += file_viewer.TICKET_TTL_SECONDS + 1
        self.assertEqual(self.fetch(out["url"]).status_code, 410)
        self.assertEqual(self.fetch("/api/v1/files/download/no-such-ticket").status_code, 410)

    def test_minting_keeps_every_wall(self):
        # The read check: a viewer may mint (same as browsing), an outsider 404s.
        self.assertEqual(self.mint(self.vera, "script.py").status_code, 200)
        outsider = User.objects.create_user(username="out2", email="out2@acme.test", password="x")
        CompanyAccess.objects.create(company=self.company, user=outsider, role="member", invited_by=self.owner)
        self.assertEqual(self.mint(outsider, "script.py").status_code, 404)
        # The path wall and the kinds, exactly as the other file routes.
        self.assertEqual(self.mint(self.owner, "../../etc/passwd").status_code, 400)
        self.assertEqual(self.mint(self.owner, "sneaky").status_code, 400)
        self.assertEqual(self.mint(self.owner, "nope.txt").status_code, 404)
        self.assertEqual(self.mint(self.owner, "sub").status_code, 400)

    def test_a_ticket_is_tied_to_its_own_project_s_file(self):
        """The payload binds project AND path at mint time — there is no field a
        caller could vary, so cross-project reuse is impossible by shape; this
        pins that the served bytes are the minted project's."""
        out = self.mint(self.owner, "sub/note.txt").json()
        r = self.fetch(out["url"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.body(r), b"plain note")

    def test_a_file_deleted_after_the_mint_is_an_honest_404(self):
        out = self.mint(self.owner, "script.py").json()
        (self.root / "script.py").unlink()
        self.assertEqual(self.fetch(out["url"]).status_code, 404)


# ── Part 2: the reply's file chips ───────────────────────────────────────

import uuid as _uuid  # noqa: E402

from asgiref.sync import async_to_sync  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402


class FileChipTests(FileViewerTests):
    """FILE-VIEWER-PANE §3, second half: a reply whose WRITE tools touched files
    carries them as chips — confirmed against the project folder, real sizes,
    claims the folder can't back silently dropped."""

    def reply_with_stream(self, events):
        from chat.nexus_ai import NexusAIClient
        from chat.relay import trigger_ai_response_async

        async def fake_stream(self, job, should_stop):
            for e in events:
                yield e

        with self.settings(NEXUS_AI_URL="http://fake-engine"), \
             patch.object(NexusAIClient, "stream_trigger", fake_stream), \
             patch.object(NexusAIClient, "embed_message", new_callable=AsyncMock), \
             patch("chat.relay.publish_async", new_callable=AsyncMock) as publish, \
             patch("chat.relay.repost_untaken_nudges", new_callable=AsyncMock):
            msg_id = async_to_sync(trigger_ai_response_async)(
                company=self.company, project=self.p1, topic=self.t1,
                persona=self.persona_sara, user_message="write the summary",
                user_message_id=str(_uuid.uuid4()), topic_id=str(self.t1.id),
                triggered_by=self.sara,
            )
        return msg_id, publish

    def test_written_files_ride_the_row_the_wire_and_the_serialiser(self):
        from nucleus.models import ChatMessage
        from chat.services import _serialise

        end = lambda **kw: {"type": "tool_call_end", "id": "x", "tool_result": {"name": "write_file", "ok": True, "duration_ms": 3, "preview": "ok", **kw}}
        msg_id, publish = self.reply_with_stream([
            end(path="readme.md"),
            end(path="readme.md"),                 # written twice — one chip
            end(path="ghost.md"),                  # never landed on disk — dropped
            end(path="../outside.txt"),            # outside the wall — dropped
            {"type": "tool_call_end", "id": "x", "tool_result": {"name": "read_file", "ok": True, "duration_ms": 1}},
            {"type": "message_done", "id": "x", "content": "Saved.", "output_type": "text", "render_as": "text"},
        ])
        row = ChatMessage.objects.get(id=msg_id)
        expected = [{"path": "readme.md", "name": "readme.md", "size": (self.root / "readme.md").stat().st_size}]
        self.assertEqual(row.metadata["files"], expected)
        self.assertEqual(_serialise(row)["files"], expected)
        # The live message_done carries the same chips.
        done = next(c.args[1] for c in publish.call_args_list if c.args[1].get("type") == "message_done")
        self.assertEqual(done["files"], expected)

    def test_a_reply_that_wrote_nothing_carries_no_files_key(self):
        from nucleus.models import ChatMessage
        from chat.services import _serialise

        msg_id, publish = self.reply_with_stream([
            {"type": "message_done", "id": "x", "content": "Just words.", "output_type": "text", "render_as": "text"},
        ])
        row = ChatMessage.objects.get(id=msg_id)
        self.assertNotIn("files", row.metadata)
        self.assertEqual(_serialise(row)["files"], [])
        done = next(c.args[1] for c in publish.call_args_list if c.args[1].get("type") == "message_done")
        self.assertEqual(done["files"], [])


# ── Part 3: upload ──────────────────────────────────────────────────────────

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402


class UploadTests(FileViewerTests):
    """FILE-VIEWER-PANE §4: one file into one folder — the project.files_write
    right, the bare-name rules, the size cap, the overwrite flag, the wall."""

    def upload(self, user, name, data=b"hello", path="", overwrite=False):
        params = []
        if path:
            params.append(f"path={path}")
        if overwrite:
            params.append("overwrite=true")
        url = f"{self.base}upload/" + (f"?{'&'.join(params)}" if params else "")
        with patch("authn.auth.verify_supabase_token", return_value={"email": user.email}):
            return Client().post(url, data={"file": SimpleUploadedFile(name, data)}, HTTP_AUTHORIZATION="Bearer t")

    def test_a_member_uploads_and_the_bytes_land(self):
        r = self.upload(self.sara, "notes.txt", b"three lines\n")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), {"path": "notes.txt", "name": "notes.txt", "size": 12})
        self.assertEqual((self.root / "notes.txt").read_bytes(), b"three lines\n")

    def test_into_a_subfolder(self):
        r = self.upload(self.owner, "deep.txt", b"x", path="sub")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["path"], "sub/deep.txt")
        self.assertTrue((self.root / "sub" / "deep.txt").is_file())

    def test_the_right_gates_it(self):
        # A Viewer may browse but never write; an outsider doesn't see the project.
        r = self.upload(self.vera, "nope.txt")
        self.assertEqual(r.status_code, 403, r.content)
        self.assertIn("permission", r.json()["detail"])
        outsider = User.objects.create_user(username="out3", email="out3@acme.test", password="x")
        CompanyAccess.objects.create(company=self.company, user=outsider, role="member", invited_by=self.owner)
        self.assertEqual(self.upload(outsider, "nope.txt").status_code, 404)
        self.assertFalse((self.root / "nope.txt").exists())

    def test_overwrite_needs_the_flag(self):
        before = (self.root / "readme.md").read_bytes()
        r = self.upload(self.owner, "readme.md", b"new text")
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual((self.root / "readme.md").read_bytes(), before)  # untouched
        r = self.upload(self.owner, "readme.md", b"new text", overwrite=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.root / "readme.md").read_bytes(), b"new text")

    def test_too_big_is_a_413_and_nothing_lands(self):
        with self.settings(FILES_UPLOAD_MAX_BYTES=10):
            r = self.upload(self.owner, "big.bin", b"x" * 11)
        self.assertEqual(r.status_code, 413, r.content)
        self.assertIn("too big", r.json()["detail"])
        self.assertFalse((self.root / "big.bin").exists())

    def test_name_and_folder_rules(self):
        # Through HTTP, Django itself strips directories from a multipart file
        # name, so the separator rule is pinned on save_upload directly.
        for bad in ("a/b.txt", "a\\b.txt", "..", ".", "", "x" * 256, "nul\x00l.txt"):
            with self.assertRaises(file_viewer.FileViewerError) as caught:
                file_viewer.save_upload(self.p1, "", bad, SimpleUploadedFile("n", b"x"))
            self.assertEqual(caught.exception.status, 400, bad)
        # A folder's name, a symlink's name, a missing folder, a file as folder.
        self.assertEqual(self.upload(self.owner, "sub").status_code, 400)
        self.assertEqual(self.upload(self.owner, "sneaky").status_code, 400)
        self.assertEqual(self.upload(self.owner, "x.txt", path="nowhere").status_code, 404)
        self.assertEqual(self.upload(self.owner, "x.txt", path="readme.md").status_code, 400)
        # The wall: a folder path pointing out is refused like everywhere else.
        self.assertEqual(self.upload(self.owner, "x.txt", path="..%2F..").status_code, 400)

    def test_a_lying_size_is_stopped_while_writing(self):
        """The cap holds even when the declared size is absent or false."""
        upload = SimpleUploadedFile("liar.bin", b"x" * 11)
        upload.size = 1  # claims tiny, streams big
        with self.settings(FILES_UPLOAD_MAX_BYTES=10):
            with self.assertRaises(file_viewer.FileViewerError) as caught:
                file_viewer.save_upload(self.p1, "", "liar.bin", upload)
        self.assertEqual(caught.exception.status, 413)
        self.assertFalse((self.root / "liar.bin").exists())
