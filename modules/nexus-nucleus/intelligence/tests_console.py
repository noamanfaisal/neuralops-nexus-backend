"""
Project console v1 (docs/MISSING.md "project console") — nucleus's half.

The two gates (Project.console_enabled + the caller's mcp.playground right),
the server rows the engine receives (slugged names, decrypted secrets, the
trigger-time bearer rule), the project folder they point at, and the
ConsoleLog audit row that every line writes whatever happened. The engine
itself is mocked — its own behaviour is tests/test_console.py on the
nexus-ai side.
"""
from unittest.mock import patch

from ninja.errors import HttpError

from nucleus.models import ConsoleLog, MCPServer
from workspace.api import _require_console
from workspace.fixtures import InviteGrantsFixture
from workspace.services import get_project_folder_name, update_project

from intelligence.console import console_rows, list_servers, run_line, server_slug


class ConsoleFixture(InviteGrantsFixture):
    """Alpha with two dialable external servers (one stdio with secrets, one
    HTTP with a static client_secret), one internal capability row and one
    inactive server — the rows every test below reads."""

    def setUp(self):
        super().setUp()
        self.stdio = MCPServer.objects.create(
            company=self.company, project=self.p1, name="Node3 Code",
            server_type="local", transport="stdio",
            command="ssh dev@node3 run-mcp",
        )
        self.stdio.set_secrets({"SSH_PRIVATE_KEY": "not-a-real-key"})
        self.stdio.save(update_fields=["secrets_encrypted"])
        self.http = MCPServer.objects.create(
            company=self.company, project=self.p1, name="GitHub",
            server_type="hosted", transport="http",
            url="https://api.example.test/mcp",
            tools=[{"name": "search", "description": "Search code", "read_only": True}],
        )
        self.http.set_secrets({"client_secret": "shh-bearer"})
        self.http.save(update_fields=["secrets_encrypted"])
        MCPServer.objects.create(
            company=self.company, project=self.p1, name="Alpha Capabilities",
            is_internal=True, auth_type=MCPServer.AuthType.NONE,
            capability_config={"filesystem": {}},
        )
        dead = MCPServer.objects.create(
            company=self.company, project=self.p1, name="Retired",
            server_type="hosted", transport="http", url="https://old.example.test/mcp",
        )
        dead.is_active = False
        dead.save(update_fields=["is_active"])


class ConsoleGatesTests(ConsoleFixture):
    def test_both_gates_hold_and_in_the_right_order(self):
        """Gate 1 — console_enabled off answers the same 403 to EVERYONE, the
        owner included (the switch leaks nothing about who holds what).
        Gate 2 — with the switch on, mcp.playground decides: the Owner and
        Admin bundles hold it, a Member does not."""
        with self.assertRaisesRegex(HttpError, "switched off"):
            _require_console(self.owner, self.p1)
        with self.assertRaisesRegex(HttpError, "switched off"):
            _require_console(self.sara, self.p1)

        self.p1.console_enabled = True
        self.p1.save(update_fields=["console_enabled"])
        _require_console(self.owner, self.p1)  # passes — Owner holds everything
        with self.assertRaisesRegex(HttpError, "permission"):
            _require_console(self.sara, self.p1)  # Member — no mcp.playground

    def test_the_toggle_rides_project_update(self):
        """update_project flips the switch on True/False and keeps it on None
        — the same not-sent dance as every other project setting."""
        update_project(self.p1, self.owner, console_enabled=True)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.console_enabled)
        update_project(self.p1, self.owner, description="unrelated edit")
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.console_enabled)   # None = keeps
        update_project(self.p1, self.owner, console_enabled=False)
        self.p1.refresh_from_db()
        self.assertFalse(self.p1.console_enabled)


class ConsoleRowsTests(ConsoleFixture):
    def test_rows_carry_slugs_secrets_and_the_bearer(self):
        """The engine receives exactly the dialable external rows: the stdio
        row with its command, DECRYPTED secrets and server_id (the engine's
        SSH key file name); the HTTP row with its url and the trigger-time
        bearer (client_secret for static rows). Internal and inactive rows
        never ship."""
        rows = {r["name"]: r for r in console_rows(self.p1)}
        self.assertEqual(set(rows), {"node3_code", "github"})
        self.assertEqual(rows["node3_code"]["command"], "ssh dev@node3 run-mcp")
        self.assertEqual(rows["node3_code"]["env"], {"SSH_PRIVATE_KEY": "not-a-real-key"})
        self.assertEqual(rows["node3_code"]["server_id"], str(self.stdio.id))
        self.assertEqual(rows["github"]["url"], "https://api.example.test/mcp")
        self.assertEqual(rows["github"]["bearer_token"], "shh-bearer")

    def test_list_servers_names_tools_and_never_secrets(self):
        """The CLI's `servers` listing: slugged console names and the STORED
        tool catalog — and not one secret or url-credential field."""
        listed = {s["name"]: s for s in list_servers(self.p1)}
        self.assertEqual(set(listed), {"node3_code", "github"})
        self.assertEqual(listed["github"]["tools"][0]["name"], "search")
        for entry in listed.values():
            for forbidden in ("env", "bearer_token", "secrets", "command", "url"):
                self.assertNotIn(forbidden, entry)

    def test_the_slug_rule_matches_the_engine_registry(self):
        self.assertEqual(server_slug("Node3 Code"), "node3_code")
        self.assertEqual(server_slug("GitHub"), "github")
        self.assertEqual(server_slug("  --  "), "mcp")


class ConsoleRunTests(ConsoleFixture):
    def _engine(self, status=200, body=None):
        return patch("chat.nexus_ai.NexusAIClient.console_run",
                     return_value=(status, body if body is not None else {
                         "ok": True, "server": "github", "tool": "search",
                         "result": {"result": "hit"}, "saved_to": "/out/hit.json",
                         "duration_ms": 42,
                     }))

    def test_a_line_ships_the_folder_and_lands_in_the_audit(self):
        """run_line sends the line, the rows and THE PROJECT FOLDER (the same
        path the Filesystem capability points at), and writes the ConsoleLog
        row — who, what, against which server, where the result was piped."""
        with self._engine() as mock_run:
            status, body = run_line(self.company, self.owner, self.p1,
                                    'github.search({"query": "x"}) > /out/hit.json')
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        payload = mock_run.call_args.args[0]
        self.assertTrue(payload["workspace_root"].endswith(get_project_folder_name(self.p1)))
        self.assertEqual({r["name"] for r in payload["servers"]}, {"node3_code", "github"})
        log = ConsoleLog.objects.get(project=self.p1)
        self.assertEqual((log.user, log.server, log.tool), (self.owner, "github", "search"))
        self.assertTrue(log.ok)
        self.assertEqual(log.saved_to, "/out/hit.json")
        self.assertEqual(log.duration_ms, 42)

    def test_an_engine_fault_is_worded_and_still_audited(self):
        """A dead engine (502) comes back as a worded detail, not a raise —
        and the audit row records the failed line too."""
        with self._engine(status=502, body="ConnectError: boom"):
            status, body = run_line(self.company, self.owner, self.p1, "github.search({})")
        self.assertEqual(status, 502)
        log = ConsoleLog.objects.get(project=self.p1)
        self.assertFalse(log.ok)
        self.assertIn("boom", log.error)

    def test_an_empty_line_never_reaches_the_engine(self):
        with self._engine() as mock_run:
            status, _ = run_line(self.company, self.owner, self.p1, "   ")
        self.assertEqual(status, 422)
        mock_run.assert_not_called()
