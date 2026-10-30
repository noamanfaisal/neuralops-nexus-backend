"""
The tool catalog (W11): tool servers a team is likely to want, as content.

Not a registry and not a marketplace — a hand-kept list whose only job is to
save someone reading a README to learn which URL to paste and which secret to
have ready. Nothing here is a credential, and nothing is fetched at runtime:
picking an entry pre-fills the create dialog the person already uses, and the
server row is created exactly as a typed one would be.

Keeping it current is a maintenance job; it is listed in docs/OPEN-ITEMS.md so
it does not quietly rot.
"""

# id: stable, referenced by the app. url: what goes in the create dialog, with
# {placeholders} the person must replace. needs: what they should have ready
# BEFORE clicking add -- a token, a workspace name -- never the secret itself.
#
# oauth_preset (Step 6 Part C, ruling 8 -- the famous three ONLY: GitHub,
# Google Drive, Atlassian): the oauth_config the app pre-fills when the person
# picks "Connect with NeuralOps" instead of pasting their own app. Endpoints
# and scopes are the provider's public, stable values; client_id is the shared
# vendor "NeuralOps" app's PUBLIC identifier, filled in once those apps are
# registered with each provider (portal-side work, tracked in the doc) -- an
# empty client_id means the app offers only paste-your-own for now. The
# client SECRET never appears here and never ships in the image: redirect_mode
# "portal_relay" sends the provider's bounce through the portal, which is
# where any secret-requiring exchange would live. These are CONTENT, like the
# rest of the catalog -- copied into the server row's oauth_config at create.
MCP_CATALOG = [
    {
        "id": "github",
        "title": "GitHub",
        "description": "Issues, pull requests, code search and file contents in a repository.",
        "category": "Software",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-github",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["A GitHub personal access token with the scopes you want the persona to have"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
        # GitHub's token exchange DEMANDS the client secret even for PKCE
        # clients — covered by the portal's oauth-exchange function (road 2b,
        # WP4): the install sends the code there, only the portal holds the
        # secret. Connectable once the vendor app's client_id lands here.
        "oauth_preset": {
            "client_id": "",
            "authorize_endpoint": "https://github.com/login/oauth/authorize",
            "token_endpoint": "https://github.com/login/oauth/access_token",
            "scopes": ["repo", "read:org"],
            "authorize_params": {},
            "redirect_mode": "portal_relay",
            "exchange_mode": "portal",
            "exchange_provider": "github",
            "token_env_var": "GITHUB_TOKEN",
        },
    },
    {
        "id": "atlassian",
        "title": "Jira & Confluence",
        "description": "Atlassian's hosted server: issues, sprints and pages, through your own Atlassian sign-in.",
        "category": "Software",
        "server_type": "hosted",
        "transport": "http",
        "command": None,
        "url": "https://mcp.atlassian.com/v1/mcp",
        "auth_type": "oauth2",
        "needs": ["An Atlassian account with access to the site you want to reach"],
        "docs": "https://support.atlassian.com/atlassian-rovo-mcp-server/",
        "oauth_preset": {
            "client_id": "",
            "authorize_endpoint": "https://auth.atlassian.com/authorize",
            "token_endpoint": "https://auth.atlassian.com/oauth/token",
            # offline_access is what makes Atlassian hand back a refresh_token.
            "scopes": ["read:jira-work", "write:jira-work", "read:confluence-content.all", "offline_access"],
            "authorize_params": {"audience": "api.atlassian.com", "prompt": "consent"},
            "redirect_mode": "portal_relay",
            # Atlassian 3LO also demands the secret at the exchange — road 2b.
            "exchange_mode": "portal",
            "exchange_provider": "atlassian",
            "token_env_var": "ATLASSIAN_TOKEN",
        },
    },
    {
        "id": "postgres",
        "title": "PostgreSQL",
        "description": "Read-only SQL against a database, with the schema exposed so a persona can write queries.",
        "category": "Data",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-postgres {connection-url}",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["A connection URL for a role that may only read"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
    },
    {
        "id": "sqlite",
        "title": "SQLite",
        "description": "A single database file on the server — useful for a project's own small store.",
        "category": "Data",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-sqlite --db-path {path-to.db}",
        "url": None,
        "auth_type": "none",
        "needs": ["A path the server can read, inside the project folder"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
    },
    {
        "id": "slack",
        "title": "Slack",
        "description": "Read channels and post messages as an app you install in your workspace.",
        "category": "Communication",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-slack",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["A Slack bot token", "The workspace (team) id"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
    },
    {
        "id": "sentry",
        "title": "Sentry",
        "description": "Pull an issue's stack trace and context so a persona can work on the actual error.",
        "category": "Software",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-sentry",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["A Sentry auth token"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/sentry",
    },
    {
        "id": "google-drive",
        "title": "Google Drive",
        "description": "Search and read documents and sheets a persona has been given access to.",
        "category": "Documents",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-gdrive",
        "url": None,
        "auth_type": "oauth2",
        "needs": ["A Google Cloud project with the Drive API on, and its OAuth client"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive",
        "oauth_preset": {
            "client_id": "",
            "authorize_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            # access_type=offline + prompt=consent is what makes Google hand
            # back a refresh_token (it omits one otherwise).
            "authorize_params": {"access_type": "offline", "prompt": "consent"},
            "redirect_mode": "portal_relay",
            # Google demands the vendor secret at the exchange — the portal's
            # oauth-exchange function does it (road 2b, WP4).
            "exchange_mode": "portal",
            "exchange_provider": "google-drive",
            "token_env_var": "GDRIVE_TOKEN",
        },
    },
    {
        "id": "git",
        "title": "Git",
        "description": "History, diffs and blame for a repository already on the server.",
        "category": "Software",
        "server_type": "local",
        "transport": "stdio",
        "command": "mcp-server-git --repository {path-to-repo}",
        "url": None,
        "auth_type": "none",
        "needs": ["A repository inside the project folder"],
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/git",
    },
    # ── 1.2.0 tiles (owner's list, 2026-10-22 19:45): Bitbucket, a graph-DB
    # context server, AWS, Vercel, diagrams/charts. Content like everything
    # above — each entry is to be VERIFIED against the real service before
    # release (the ruling says tested, and package names rot).
    {
        "id": "bitbucket",
        "title": "Bitbucket",
        "description": "Pull requests, repositories and code search in your Bitbucket Cloud workspace.",
        "category": "Software",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y @aashari/mcp-server-atlassian-bitbucket",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["Your Bitbucket workspace name", "An Atlassian API token for a user with access to it"],
        "docs": "https://github.com/aashari/mcp-server-atlassian-bitbucket",
    },
    {
        "id": "neo4j",
        "title": "Neo4j graph",
        "description": "The graph-context option: run Cypher against a Neo4j graph, with the schema exposed so a persona can write its own queries.",
        "category": "Data",
        "server_type": "local",
        "transport": "stdio",
        "command": "uvx mcp-neo4j-cypher",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["The database's connection URI (neo4j:// or bolt://)", "A database user and password"],
        "docs": "https://github.com/neo4j-contrib/mcp-neo4j",
    },
    {
        "id": "aws",
        "title": "AWS",
        "description": "AWS Labs' API server: describe, create and change AWS resources — exactly as far as the credentials you give it reach.",
        "category": "Infrastructure",
        "server_type": "local",
        "transport": "stdio",
        "command": "uvx awslabs.aws-api-mcp-server@latest",
        "url": None,
        "auth_type": "static_secrets",
        "needs": ["AWS credentials (an access key, or a profile on the server) scoped to what the persona may touch", "The region to work in"],
        "docs": "https://github.com/awslabs/mcp",
    },
    {
        "id": "vercel",
        "title": "Vercel",
        "description": "Vercel's hosted server: projects, deployments and logs, through your own Vercel sign-in.",
        "category": "Infrastructure",
        "server_type": "hosted",
        "transport": "http",
        "command": None,
        "url": "https://mcp.vercel.com",
        "auth_type": "oauth2",
        # No oauth_preset: Vercel's MCP endpoint registers clients dynamically
        # (the RFC 8414 + dynamic-registration road the app already drives —
        # intelligence/tests_oauth_dyn.py); presets stay for the famous three.
        "needs": ["A Vercel account — the sign-in happens in your browser when you connect"],
        "docs": "https://vercel.com/docs/mcp/vercel-mcp",
    },
    {
        "id": "mermaid",
        "title": "Diagrams & charts",
        "description": "Generate and validate Mermaid diagrams — flowcharts, sequence diagrams, pies — which the chat already renders natively.",
        "category": "Documents",
        "server_type": "local",
        "transport": "stdio",
        "command": "npx -y mcp-mermaid",
        "url": None,
        "auth_type": "none",
        "needs": ["Nothing — diagrams render right in the chat"],
        "docs": "https://github.com/hustcc/mcp-mermaid",
    },
]

CATEGORIES = ["Software", "Data", "Communication", "Documents", "Infrastructure"]


def catalog() -> list[dict]:
    """The catalog as the app reads it. A copy, so a caller cannot edit the module."""
    return [dict(entry) for entry in MCP_CATALOG]


def entry(entry_id: str) -> dict | None:
    return next((dict(e) for e in MCP_CATALOG if e["id"] == entry_id), None)
