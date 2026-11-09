#!/usr/bin/env python3
"""
Example local MCP server: lets an AI agent query Snowflake as an Immuta agent ON BEHALF OF a user.
Every query runs under an ephemeral role vended by Immuta (agent rights ∩ user rights).

The on-behalf-of user is fixed in config (ON_BEHALF_OF), never chosen by the model.
See README.md for setup and the required environment variables.
"""
import os, sys, time, requests
import snowflake.connector
from mcp.server.fastmcp import FastMCP

API = os.environ["IMMUTA_API"].rstrip("/")
ON_BEHALF_OF = os.environ["ON_BEHALF_OF"]
TTL_MIN = int(os.environ.get("OBO_TTL_MIN", "15"))
HEADERS = {"Authorization": f"Bearer {os.environ['IMMUTA_AGENT_PAT']}",
           "Content-Type": "application/json"}

mcp = FastMCP("immuta-obo")
_state = {"role": None, "request_id": None, "vended_at": 0.0}


def log(msg):  # stdout is the MCP channel; log to stderr only
    print(msg, file=sys.stderr, flush=True)


def _vend() -> str:
    platform = {"technology": "Snowflake"}
    if os.environ.get("IMMUTA_CONNECTION_KEY"):
        platform["connectionKeys"] = [os.environ["IMMUTA_CONNECTION_KEY"]]
    r = requests.post(f"{API}/agents/roles", headers=HEADERS, timeout=30,
                      json={"username": ON_BEHALF_OF, "platforms": [platform],
                            "ttl": TTL_MIN * 60_000})
    r.raise_for_status()
    req_id = r.json()["requestId"]
    deadline = time.time() + 60
    while time.time() < deadline:
        g = requests.get(f"{API}/agents/roles/{req_id}", headers=HEADERS, timeout=30)
        g.raise_for_status()
        role = next(x for x in g.json()["roles"] if x["technology"] == "Snowflake")
        if role["status"] == "READY":
            _state.update(role=role["metadata"]["roleName"], request_id=req_id,
                          vended_at=time.time())
            log(f"Vended {_state['role']} for {ON_BEHALF_OF}")
            return _state["role"]
        if role["status"] in ("FAILED", "DROPPED", "ABANDONED"):
            raise RuntimeError(f"Immuta could not vend role: {role.get('metadata')}")
        time.sleep(2)
    raise RuntimeError("Timed out waiting for Immuta to vend role")


def _role(force_new=False) -> str:
    fresh = _state["role"] and time.time() - _state["vended_at"] < (TTL_MIN * 60 - 60)
    return _state["role"] if (fresh and not force_new) else _vend()


def _query(role: str, sql: str, max_rows: int = 100) -> str:
    conn = snowflake.connector.connect(
        account=os.environ["SF_ACCOUNT"], user=os.environ["SF_AGENT_USER"],
        password=os.environ["SF_AGENT_PAT"], warehouse=os.environ.get("SF_WAREHOUSE"),
        role=f'"{role}"')
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows)
        out = [" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows]
        return "\n".join(out)
    finally:
        conn.close()


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run read-only SQL on Snowflake as the Immuta agent on behalf of the configured user.
    Immuta policies (access, masking, row filters) apply. Use fully qualified names
    like <database>.<schema>.<table>. If access is denied, suggest requesting access
    through the Immuta MCP server, then call refresh_access once it is approved."""
    if not sql.strip().split()[0].upper() in ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC"):
        return "Only read-only queries are allowed."
    role = _role()
    header = f"[on behalf of {ON_BEHALF_OF} | vended role {role}]\n"
    try:
        return header + _query(role, sql)
    except Exception as e:
        return header + f"Query failed: {e}"


@mcp.tool()
def refresh_access() -> str:
    """Request a NEW vended role from Immuta. Call this after an access request or
    masking exception has been approved so the new entitlements take effect."""
    return f"New vended role for {ON_BEHALF_OF}: {_role(force_new=True)}"


@mcp.tool()
def whoami() -> str:
    """Show which user the agent is acting for and the current vended role."""
    return (f"Agent: {os.environ['SF_AGENT_USER']} | On behalf of: {ON_BEHALF_OF} | "
            f"Vended role: {_state['role'] or '(none yet)'}")


if __name__ == "__main__":
    mcp.run()
