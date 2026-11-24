# Memory deployment and project use

See the [project memory guide](../../../docs/zh/guide/project-memory.md) for
Cowork onboarding and local setup. The commands below administer the local gateway.
Local `record` candidates and Cowork `body` candidates are different formats.
There is no automatic synchronization or transfer of approval between them.

## Local startup

Run from the Relax checkout with Python 3.10 or newer. No extra Python dependencies
are required for the gateway, client or MCP adapter. It runs directly inside the existing
Relax environment; no Dockerfile, Docker daemon or nested container is involved.
`local` remains an alias for `up`.

```bash
export RELAX_MEMORY_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/relax-memory"
bash scripts/tools/memory.sh up
```

The command initializes `memory.sqlite` and a private `admin.json`, then serves the
gateway on loopback port 8765 in the foreground. Set `RELAX_MEMORY_PORT` to choose
another port. Keep this terminal running; from another terminal:

```bash
export RELAX_MEMORY_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/relax-memory"
bash scripts/tools/memory.sh verify
```

If you chose a custom state directory or port, export the same values in both terminals.

The probe creates an isolated verification namespace and checks private staging,
review, snapshot isolation, cross-namespace isolation and persisted read replay.
It does not seed any business namespace. Stop the foreground server with Ctrl-C.

## Create a project/task and connect an agent

```bash
python -m relax.memory project \
  --endpoint http://127.0.0.1:8765 \
  --token-file "$RELAX_MEMORY_STATE/admin.json" \
  --namespace team-a/dev/my-project \
  --session task-001 \
  --output-dir "$RELAX_MEMORY_STATE/tasks/task-001"
```

This writes a bound `agent.json` and a generic MCP `mcp.json` fragment. Use the generated
command, arguments and environment in the client's MCP settings, retaining other tools.
Do not commit either credential file. A namespace is an opaque full isolation key;
include team, environment and project explicitly. The administrator controls assignments.
Reusing a Session ID intentionally shares its receipts/candidate identity; use a fresh
ID for independent tasks and sibling agents.

For a client installed on the same machine, register a uniquely named stdio server
from the Relax repository root. Inspect existing entries first; choose another name
if `relax-memory-task-001` already exists. The commands below add a configuration entry;
they do not start a model run or copy the administrator credential.

```bash
# Codex
codex mcp list
codex mcp add relax-memory-task-001 --env "PYTHONPATH=$PWD" -- \
  "$(command -v python)" -m relax.memory mcp \
  --endpoint http://127.0.0.1:8765 \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"

# Claude Code (alternative client)
claude mcp list
claude mcp add --env "PYTHONPATH=$PWD" --transport stdio relax-memory-task-001 -- \
  "$(command -v python)" -m relax.memory mcp \
  --endpoint http://127.0.0.1:8765 \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

Reload the client and ask it to call `memory_search` for the project's relevant knowledge.
Confirm the tool result and receipt, then try a candidate proposal; it must remain staged
until administrator review. Client registration alone is not an end-to-end agent test.
These stdio registration forms follow [Codex MCP](https://developers.openai.com/codex/mcp)
and [Claude Code MCP](https://code.claude.com/docs/en/mcp); use client help if an installed
version differs. The generic JSON fragment is not Codex TOML syntax.

The stdio entry point is:

```bash
python -m relax.memory mcp \
  --endpoint http://127.0.0.1:8765 \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

It waits for MCP JSON-RPC input, so running it in a terminal alone does not produce a
chat interface. The generated fragment uses an absolute Python executable and PYTHONPATH
for this checkout. A remote agent must use an endpoint reachable from its host and its
own valid local command/path; copying a laptop path into a hosted agent will not work.

## Add and review knowledge

The canonical sample is `examples/memory/knowledge.json`. Agent tools accept this
candidate format; ownership, verification and revision fields are assigned by the
service. This release implements the v1 core subset, not every optional coding field
in the design draft.

For an operator import, create a request file containing:

```json
{
  "namespace": "team-a/dev/my-project",
  "session": "manual-import-001",
  "idempotency_key": "knowledge-001",
  "record": {
    "schema_version": "1.0",
    "kind": "strategy",
    "domain": "knowledge",
    "subtype": "workflow",
    "title": "Check the code state when validating a repair",
    "summary": "Associate regression results with the tested code revision.",
    "content": {"text": "Reproduce the failure, repair it, and rerun the relevant regression."},
    "evidence": [{"evidence_id": "review:001", "type": "human_review"}]
  }
}
```

Pass it using the administrator credential; `--args-file` is JSON, never shell code:

```bash
python -m relax.memory request candidate_stage \
  --token-file "$RELAX_MEMORY_STATE/admin.json" --args-file stage.json
```

Review the content and actual evidence. Then prepare a separate decision:

```json
{
  "namespace": "team-a/dev/my-project",
  "candidate_id": "COPY_THE_RETURNED_CANDIDATE_ID",
  "verification": {
    "state": "verified",
    "verifier_id": "maintainer-review",
    "evidence_ids": ["review:001"]
  }
}
```

```bash
python -m relax.memory request candidate_commit \
  --token-file "$RELAX_MEMORY_STATE/admin.json" --args-file decision.json
```

`evidence_ids` records the trusted operator's review, not an automatic execution check.
To update, stage a new candidate and add `record_id` and `expected_revision` to the
commit request. Conflicting revisions fail. To expire, call `record_expire` with
`namespace`, `record_id`, `expected_revision`; this creates an expired revision.
Use `candidate_list` with `namespace` to list pending candidates.

Create a new task binding with `project` after commits/expiry to see the new state.
Old task snapshots preserve their original records. Exact duplicate active records are
deduplicated within a namespace. A failed/ambiguous MemOS export is different: it must
be reconciled manually before retry because upstream write idempotency is not proven.

## Connect an existing private MemOS service

MemOS is optional. The startup script only starts the lightweight Relax Memory gateway;
it does not install or start MemOS, Neo4j, Qdrant or model services. To use MemOS, obtain
a reachable self-hosted `/product` API endpoint and an authorized user/cube from its
operator. Its model and storage dependencies are managed on that service's side.

Set `MEMOS_ENDPOINT` to the service base URL (without `/product`). If it requires
an authorization header, set `MEMOS_AUTHORIZATION` through your credential environment.
Select an existing authorized user with `MEMOS_VERIFY_USER` (default `root` for a fresh
upstream service). The real probe creates a new random cube, writes synthetic content,
retrieves it and stages the result in Relax; it retains the probe cube for inspection.

```bash
# Set MEMOS_ENDPOINT to your existing private service before this command.
bash scripts/tools/memory.sh verify-memos
```

There is no implicit MemOS address fallback. No endpoint means the script fails before
sending a probe. Local Memory can run and pass `verify` without MemOS or model services.
A successful protocol fixture does not establish real MemOS integration.

## Service lifecycle and persistence

`up`/`local` run in the foreground. Use Ctrl-C in the service terminal to stop; the
SQLite database, credentials and snapshots remain in `RELAX_MEMORY_STATE`. Start again
with the same directory to reuse them. `status` checks liveness at `RELAX_MEMORY_ENDPOINT`
or the configured local port; it does not validate credentials or perform a write test.

```bash
bash scripts/tools/memory.sh status
bash scripts/tools/memory.sh verify
```

For background operation, run the same foreground command under the environment's
existing process supervisor and collect stdout/stderr there. The script no longer offers
`init-env`, `logs` or `down`, and does not manage external services. Old environment files
or previously deployed upstream data are not removed automatically.

Stop the service and back up its state directory before migration, or use SQLite's
online backup API. Copying only a running `memory.sqlite` file can omit WAL data. This
package does not implement automated backup/HA. Keep the data directory on a mounted
persistent volume if the Relax environment itself runs in a container.

## Import and export

Import reads an authorized cube and stages retrieved content; it does not import a
complete cube or mark upstream summaries as verified. `MEMOS_AUTHORIZATION` can contain
the authorization header value required by an existing protected endpoint. Do not pass
credentials on the command line.

```bash
python -m relax.memory memos-import \
  --token-file "$RELAX_MEMORY_STATE/admin.json" \
  --namespace team-a/dev/my-project --session import-001 \
  --memos-endpoint http://127.0.0.1:8000 --memos-user my-user --cube my-cube \
  --query 'relevant project workflow'
```

Review/commit candidates, then create a new snapshot. Approved snapshots can be
explicitly exported with `memos-export`, the same endpoint/user/cube/namespace options,
and `--snapshot SNAPSHOT_ID`. The cube must already exist. This is a copy into the
selected MemOS cube, not automatic multi-business sharing or continuous synchronization.

## Troubleshooting and validation limits

- HTTP 403: wrong credential, agent attempting an admin action, or browser Origin.
- HTTP 400: invalid record, stale expected_revision, incorrect namespace/snapshot or
  missing required argument. Inspect the request locally without exposing credentials.
- MemOS application error: ask the service operator to inspect its logs; health alone does not
  validate Neo4j/Qdrant or model requests. No automatic fallback to public models.
- Search empty after review: the agent still has its old snapshot, or the keyword query
  does not match. Start a new task binding; do not overwrite the old receipt.
- Model context too large: lower `max_bytes`. This is a byte limit; exact model token
  budgeting must use that model's tokenizer at the harness boundary.
- No MemOS endpoint: local mode and CPU protocol tests remain available; report real
  MemOS integration as unverified. GPU integration is outside this first release.
