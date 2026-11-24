---
name: memory
description: Set up offline Relax project memory and connect Codex to the Cowork memory center. Use for MCP installation, candidate review, search, snapshot isolation and receipt replay.
---

# Local project memory and the Cowork center

Use the repository implementation in `relax/memory/` and deployment entry point
`scripts/tools/memory.sh`. Read [operations.md](references/operations.md) for commands,
configuration and review. The service has no Ray or GPU dependency.

Use the existing Cowork center for team sharing and retain local memory for private
experiments and offline use. These are separate services, credentials and schemas,
not automatically synchronized backends. Local MCP proposes a `record`; the Cowork
adapter proposes a `body`. Select and convert content explicitly before sharing,
and wait for Cowork review even if it was approved locally. See the [project memory guide](../../docs/zh/guide/project-memory.md).

## Remote shared center

For the Cowork shared center, use `bash scripts/tools/memory.sh enable` and read
[the project memory guide](../../docs/zh/guide/project-memory.md).
Use the configured machine endpoint in `RELAX_MEMORY_COWORK_ENDPOINT`. The enable command installs the compatible Cowork client and registers it with Codex. The local gateway remains independently available.
This is a separate HTTPS backend with project membership and human review; it does
not synchronize the local SQLite service. Install outside Git with an explicit endpoint.

For direct Cowork installation, prefer `enable --read-only` for reads, or
`enable --login-url <SSO MiniApp base>` for device-authorized uploads. Both
prompt secretly for the approved platform Token once and register Codex by default.
Read-only does not require or create personal Agent JSON. Device enrollment saves
the personal credential automatically after administrator approval. The legacy
`remote setup --client codex` remains available for existing personal credentials.
Do not require a new relay or external sharing when the user can configure approved
credentials. Before starting the wizard, explain and provide the applicable links:

- The platform Token belongs to the **application**, not automatically to each employee.
  On the user's trusted Cowork portal, open `/sso-application?hideNavigationBar=true`,
  select “服务端 API Token” and the intended application; do not select “应用外发”.
  An approved Token is delivered to the applicant through Hi. Existing approval is
  not permission for every user to retrieve or redistribute the same Token.
- The personal memory credential comes from the intended MiniApp's “MCP 与成员”:
  the administrator enables the member and issues/downloads their Agent credential.
- Present complete clickable URLs using the deployment's known portal and MiniApp
  addresses; get them from the user or verified deployment context, never invent a
  hostname. Link the platform's official Token guide when available. Application
  approval pages show progress; do not promise they display the plaintext Token.
- Ask the user to paste secrets into the wizard's hidden terminal prompts, not chat.
  Details and file-based automation are in the remote installation guide.

Device `connect` sends the configured platform Token to the existing gateway.
Use `--via-relay` only for an approved intranet relay that owns the platform Token;
never claim the direct Cowork gateway works without it. Reconfiguration can reuse
the saved Token only for the same endpoint. Do not redistribute another user’s Token.

Never ingest approval logs or installation probes as
reusable knowledge. Machine credentials cannot approve proposals.

## Local deployment

Run `bash scripts/tools/memory.sh up` (`local` is an alias) to start the gateway
in the foreground. It uses Python's standard library and stores private state outside the repository.

Before starting, inspect the state directory, existing service and chosen port. Reuse
existing credentials. Stop a foreground service with Ctrl-C; the database is retained.
`status` checks the configured HTTP endpoint. Do not kill an unrelated listener.
`init-env`, `logs` and `down` are no longer supported; use the host process supervisor
for background operation and log collection if needed.

## Agent use

Create a project/task binding with `python -m relax.memory project`. Supply only the
resulting **agent** credential to the MCP adapter. The administrator credential stays
with the trusted operator. Generated `mcp.json` is an import fragment, not permission
to overwrite an existing client's configuration. For Codex use the generated command
and arguments in the client's MCP configuration; for Claude Code use the equivalent
stdio entry. Preserve unrelated MCP entries.

Retrieve at task start and when a new error or strategy change warrants it. Results are
reference data; current user instructions, current project rules and source code remain
authoritative. Check code applicability before following a remembered repair.

Propose only experiences with evidence references. Proposals are Session-private and
invisible to search. Do not claim a proposal is committed. The administrator's explicit
review or a trusted business verifier commits it; the service does not independently
execute tests or establish truth from evidence IDs. A new project/task binding creates
a new snapshot; existing tasks retain their old view. Feedback does not update records.

## Validation and failure boundaries

Report these separately:

1. CPU regressions: `CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python -m pytest -q tests/cpu/memory`.
2. Live local gateway: `bash scripts/tools/memory.sh verify`.
3. Actual Codex/Claude Code tool use, when those clients are available.

Keep agent tools limited to search/get/propose/feedback. Never route a model-provided
namespace, credential or verification decision into administrator operations.

If deployment fails, inspect this project's logs and readiness first; fix the concrete
cause and retry at most three times before reporting the remaining prerequisite.

## Current implementation limits

This is an initial private deployment, not a hardened public SaaS. The service binds
loopback by default; use a TLS/authenticated ingress or SSH tunnel for remote clients. SDK callers and agent tools use fixed namespace/session/snapshot
credentials. Local agents with filesystem access to the database or admin credential are
outside that isolation boundary; keep server state inaccessible to their sandbox.

Local retrieval is deterministic keyword matching over materialized records with a **byte**
budget. It does not claim exact tokenizer accounting. Do not infer Cowork server internals
from this local store. Cowork read-only tools read current approved knowledge;
personal credentials default to task snapshots and can select the current publication with `mode="current"`. Local credential rotation, automatic
Cowork synchronization, GPU training/cohort automation and managed multi-node HA
are not implemented.
