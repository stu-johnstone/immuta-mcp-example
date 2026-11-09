# Immuta Agentic Data Access: MCP + Snowflake OBO demo

An AI agent that:

1. **Requests access** to data through the Immuta MCP server, and
2. **Queries Snowflake on behalf of a user** using a short-lived role vended by Immuta.

The agent never holds standing access. Each query runs under an ephemeral role that grants only
what **both** the agent and the user can see, and every query is audited.

> **This is an example, not a supported product.** It is meant for demos and learning, not
> production. Agentic Data Access is in **private preview**. Until the Immuta Agentic Access
> Gateway is available, this example uses a small local MCP server (`immuta_obo_mcp.py`) that
> calls the Immuta OBO API.

```
Claude Code
├── immuta      remote MCP (Immuta-hosted): search data products, request access
└── immuta-obo  local MCP (immuta_obo_mcp.py)
      1. POST /agents/roles  (agent PAT, on behalf of user)
      2. Immuta creates IMMUTA_VENDED_<uuid> in Snowflake = agent ∩ user entitlements
      3. Connects as the agent service user with that role and runs read-only SQL
      4. Role is dropped when its TTL expires
```

## Prerequisites

- Immuta tenant with Agentic Data Access (OBO) enabled and a Snowflake connection
- A published data product with a request form, and a demo end user in Immuta
- Snowflake `ACCOUNTADMIN`, a warehouse, and a database containing the data
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`)
- [Claude Code](https://docs.claude.com/en/docs/claude-code). See [Other clients](#other-clients).

## Values used below

Replace these placeholders throughout.

| Placeholder | Meaning | Example |
|---|---|---|
| `<AGENT_USER>` | Snowflake service user for the agent | `SVC_MCP_AGENT` |
| `<AGENT_NAME>` | Immuta agent name | `DEMO_AGENT` |
| `<AGENT_ID>` | Agent name, lowercase and without `_` (Immuta derives it) | `demoagent` |
| `<ROLE_PREFIX>` | Role prefix on the Immuta Snowflake connection | `IMMUTA_` |
| `<IMMUTA_DB>` | Immuta system database in Snowflake | `IMMUTA` |
| `<CONNECTION_KEY>` | Immuta Snowflake connection key | `snowflake` |
| `<WAREHOUSE>` / `<DATABASE>` | Snowflake warehouse and data database | `DEMO_WH` / `DEMO_DB` |
| `<SF_ACCOUNT>` | Snowflake account identifier | `myorg-myaccount` |
| `<USER_EMAIL>` | **Immuta** username of the end user | `alice@example.com` |

Endpoints (NA nonprod shown; use the ones for your Immuta region/environment):

- Immuta MCP server: `https://na.mcp.nonprod.immutacloud.com/mcp`
- Immuta OBO API: `https://na.api.nonprod.immutacloud.com`. This is **not** your tenant URL.

## Setup

### 1. Snowflake: create the agent user

Run as `ACCOUNTADMIN`. **Copy the token secret** returned by the last statement.

```sql
USE ROLE ACCOUNTADMIN;
ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE;  -- agent/vended roles are mixed case

CREATE USER IF NOT EXISTS <AGENT_USER>
  TYPE = SERVICE_AGENT
  DEFAULT_WAREHOUSE = <WAREHOUSE>;

CREATE AUTHENTICATION POLICY IF NOT EXISTS <DATABASE>.PUBLIC.MCP_AGENT_PAT_POLICY
  PAT_POLICY = (REQUIRE_ROLE_RESTRICTION_FOR_SERVICE_USERS = FALSE
                NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED);
ALTER USER <AGENT_USER> SET AUTHENTICATION POLICY <DATABASE>.PUBLIC.MCP_AGENT_PAT_POLICY;

-- Only allow the vended role (policy is created by Immuta when OBO is enabled)
ALTER USER <AGENT_USER> SET SESSION POLICY <IMMUTA_DB>.IMMUTA_POLICIES.BLOCK_SECONDARY_ROLES;

ALTER USER <AGENT_USER> ADD PROGRAMMATIC ACCESS TOKEN MCP_GATEWAY;  -- copy token_secret now
```

### 2. Immuta: create the agent

1. **Identities → Agents → Create**, with the name `<AGENT_NAME>`.
2. Open the agent and select **Generate credentials**. Copy the Immuta PAT.
3. Under **External Mapping**, set Snowflake = `<AGENT_USER>`. The case must match exactly.

### 3. Snowflake: grant the agent role

Immuta creates the agent role `<ROLE_PREFIX>_AGENT_<AGENT_ID>`. Confirm the name with
`SHOW ROLES LIKE '%AGENT%';`.

```sql
USE ROLE ACCOUNTADMIN;
ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE;

-- Compute + namespace only. No data is granted here.
ALTER USER <AGENT_USER> SET DEFAULT_ROLE = "<ROLE_PREFIX>_AGENT_<AGENT_ID>";
GRANT USAGE ON WAREHOUSE <WAREHOUSE> TO ROLE "<ROLE_PREFIX>_AGENT_<AGENT_ID>";
GRANT USAGE ON DATABASE  <DATABASE>  TO ROLE "<ROLE_PREFIX>_AGENT_<AGENT_ID>";

-- Preview workaround 1: Immuta does not grant the agent role to the user
GRANT ROLE "<ROLE_PREFIX>_AGENT_<AGENT_ID>" TO USER <AGENT_USER>;

-- Preview workaround 2: vending looks for IMMUTA_AGENT_<AGENT_ID> (ignores the role prefix)
CREATE ROLE IF NOT EXISTS "IMMUTA_AGENT_<AGENT_ID>";
GRANT ROLE "<ROLE_PREFIX>_AGENT_<AGENT_ID>" TO ROLE "IMMUTA_AGENT_<AGENT_ID>";
GRANT ROLE "IMMUTA_AGENT_<AGENT_ID>" TO USER <AGENT_USER>;
GRANT OWNERSHIP ON ROLE "IMMUTA_AGENT_<AGENT_ID>" TO ROLE <IMMUTA_DB>_SYSTEM COPY CURRENT GRANTS;

-- Verify
SHOW GRANTS TO USER <AGENT_USER>;                          -- both agent roles
SHOW GRANTS OF ROLE "IMMUTA_AGENT_<AGENT_ID>";             -- granted to <AGENT_USER>
SHOW ROLES LIKE '%USER%';                                  -- end user's Immuta role exists
SHOW SESSION POLICIES IN SCHEMA <IMMUTA_DB>.IMMUTA_POLICIES;  -- BLOCK_SECONDARY_ROLES
```

### 4. Install the local MCP server

```bash
make setup   # creates .venv and installs requirements.txt
```

### 5. Configure Claude Code

Run from this directory:

```bash
claude mcp add --transport http immuta https://na.mcp.nonprod.immutacloud.com/mcp

claude mcp add --scope user immuta-obo \
  -e IMMUTA_API=https://na.api.nonprod.immutacloud.com \
  -e IMMUTA_AGENT_PAT='<Immuta agent PAT>' \
  -e IMMUTA_CONNECTION_KEY=<CONNECTION_KEY> \
  -e ON_BEHALF_OF=<USER_EMAIL> \
  -e SF_ACCOUNT=<SF_ACCOUNT> \
  -e SF_AGENT_USER=<AGENT_USER> \
  -e SF_AGENT_PAT='<Snowflake PAT>' \
  -e SF_WAREHOUSE=<WAREHOUSE> \
  -- "$(pwd)/.venv/bin/python" "$(pwd)/immuta_obo_mcp.py"
```

Start `claude`, then run `/mcp` and authenticate `immuta` **as the end user**.

> `ON_BEHALF_OF` is set in the config, never in a prompt. It must be the **Immuta** username,
> not the Snowflake one.

## Other clients

Other MCP clients can work, but many don't. The client needs all of the following:

1. **OAuth with CIMD** (Client ID Metadata Document) to sign in to the Immuta MCP server. DCR is not supported.
2. **Elicitation** (forms) for `request_access`.
3. **Local stdio MCP servers** to run `immuta_obo_mcp.py`.

To use another client, register the same two servers with the same `env` values. Use absolute paths to
`.venv/bin/python` and `immuta_obo_mcp.py`.

## Smoke test

| Prompt | Expected |
|---|---|
| "Use whoami" | Agent `<AGENT_USER>`, on behalf of `<USER_EMAIL>` |
| "Run `SELECT CURRENT_USER(), CURRENT_ROLE()`" | `<AGENT_USER>`, `IMMUTA_VENDED_...` |

## Demo flow

1. **No access:** ask a question about the data product. `run_sql` is denied.
2. **Request:** "Find the right data product and request access." The request form appears.
3. **Approve:** a data steward approves the request in Immuta, ideally with a time limit.
4. **Query:** "Refresh my access and run it again." `refresh_access` vends a new role, and the
   query returns results with masking applied.
5. **Proof:** in Snowsight, run `SHOW ROLES LIKE 'IMMUTA_VENDED_%';` and filter Query History by
   `<AGENT_USER>`. The role disappears after its TTL.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `405 MethodNotAllowed` (AmazonS3) | You used the tenant URL. Use the `na.mcp` / `na.api` endpoints. |
| "Request could not be found or has expired" at sign-in | Use a private window and finish sign-in promptly. |
| `Unknown tool: submit_access_request` | The client lacks form support (elicitation). Use Claude Code. |
| `/agents/roles` returns 404 | `ON_BEHALF_OF` must be the Immuta username (email). |
| `AGENT_ROLE_NOT_FOUND` or an empty agent role grant | Re-run the workarounds in step 3. |
| Role is READY but the query is "not authorized" | The user has no access yet. Approve the request, then `refresh_access`. |
| `ModuleNotFoundError: mcp` | Point the client at `.venv/bin/python`. |
| Mixed-case role errors | `ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE;` |

## Links

- [Immuta documentation](https://documentation.immuta.com)
- [Claude Code](https://docs.claude.com/en/docs/claude-code) and [connecting MCP servers](https://docs.claude.com/en/docs/claude-code/mcp)
- [Model Context Protocol](https://modelcontextprotocol.io)
- Snowflake: [programmatic access tokens](https://docs.snowflake.com/en/user-guide/programmatic-access-tokens), [CREATE USER](https://docs.snowflake.com/en/sql-reference/sql/create-user)
- [uv](https://docs.astral.sh/uv/)

## License

[MIT](LICENSE). Provided as is, with no support or warranty.
