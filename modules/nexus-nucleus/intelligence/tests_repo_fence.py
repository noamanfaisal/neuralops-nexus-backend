"""
9b part 2 — the per-server repository allow-list, nucleus's half: the
normaliser (lowercase owner/repo, typos refused rather than silently
dropped), create/patch round-trip including the []-clears-the-fence PATCH
rule, and the internal payload that carries the list to the engine (whose
ApprovalGate does the enforcing — tests/test_repo_fence.py there).
"""
from workspace.fixtures import InviteGrantsFixture

from intelligence.services import (
    create_mcp_server_standalone,
    normalize_allowed_repos,
    update_mcp_server_standalone,
)
from internal.api import _mcp_internal


class NormalizeTests(InviteGrantsFixture):
    def test_entries_fold_trim_dedupe_and_keep_order(self):
        """GitHub names are case-insensitive → stored lowercase; a pasted
        github.com URL is forgiven; duplicates collapse to the first."""
        out = normalize_allowed_repos([
            "Mapax-IO/csv-mcp", "  mapax-io/csv-mcp ", "noamanfaisal/neuralops-nexus-backend",
            "https://github.com/mapax-io/neuralops-nexus/", "",
        ])
        self.assertEqual(out, ["mapax-io/csv-mcp",
                               "noamanfaisal/neuralops-nexus-backend",
                               "mapax-io/neuralops-nexus"])
        self.assertEqual(normalize_allowed_repos(None), [])
        self.assertEqual(normalize_allowed_repos([]), [])

    def test_a_typo_is_refused_not_dropped(self):
        """A malformed entry must stop the save — silently dropping it would
        fence the WRONG repo and the admin would never know."""
        for bad in (["just-a-name"], ["a/b/c"], ["owner/"], ["/repo"],
                    ["owner/re po"], "not-a-list"):
            with self.assertRaises(ValueError):
                normalize_allowed_repos(bad)


class RoundTripTests(InviteGrantsFixture):
    def _create(self, **extra):
        data = {"name": "GitHub", "project_id": str(self.p1.id),
                "server_type": "hosted", "transport": "http",
                "url": "https://api.example.test/mcp", **extra}
        return create_mcp_server_standalone(self.company, data)

    def test_create_patch_and_clear(self):
        """The list normalises on create, swaps on patch, and PATCH []
        deliberately clears the fence (None = not sent, keeps it)."""
        server = self._create(allowed_repos=["Mapax-IO/csv-mcp"])
        self.assertEqual(server.allowed_repos, ["mapax-io/csv-mcp"])

        server = update_mcp_server_standalone(
            self.company, str(server.id),
            {"allowed_repos": ["mapax-io/neuralops-nexus", "MAPAX-IO/csv-mcp"]})
        self.assertEqual(server.allowed_repos,
                         ["mapax-io/neuralops-nexus", "mapax-io/csv-mcp"])

        # None = not sent — the fence stays
        server = update_mcp_server_standalone(
            self.company, str(server.id), {"description": "unrelated"})
        self.assertEqual(len(server.allowed_repos), 2)

        # [] = clear it
        server = update_mcp_server_standalone(
            self.company, str(server.id), {"allowed_repos": []})
        self.assertEqual(server.allowed_repos, [])

    def test_the_internal_payload_carries_the_list_to_the_engine(self):
        """MCPServerInternal.allowed_repos is what the engine's gate reads —
        filled from the row; an unfenced row ships []."""
        fenced = self._create(allowed_repos=["mapax-io/csv-mcp"])
        payload = _mcp_internal(fenced, needs_reauth=False)
        self.assertEqual(payload.allowed_repos, ["mapax-io/csv-mcp"])

        open_row = self._create(name="GitHub 2")
        self.assertEqual(_mcp_internal(open_row, needs_reauth=False).allowed_repos, [])
