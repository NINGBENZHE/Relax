---
name: memory
description: Deploy and use Relax project knowledge and experience memory, connect the optional private MemOS backend, configure agent MCP access, and validate isolation and replay. Use for project memory setup, knowledge import, candidate review, MemOS API integration or memory troubleshooting; GPU training integration is a separate workflow.
---

# Project memory and MemOS

Use the repository implementation in `relax/memory/` and deployment entry point
`scripts/tools/memory.sh`. Read [operations.md](references/operations.md) for commands,
configuration, review and import/export. The service has no Ray or GPU dependency.

## Remote shared center

For the Cowork shared center, use `bash scripts/tools/memory.sh remote` and read
[the remote installation guide](../../docs/zh/guide/project-memory-remote.md).
This is a separate HTTPS backend with project membership and human review; it does
not synchronize the local SQLite service. Install outside Git with an explicit endpoint.

For direct Cowork installation, prefer `remote connect --read-only` for reads, or
`remote connect --login-url <SSO MiniApp base>` for device-authorized uploads. Both
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

## Choose the deployment

- Local knowledge/experience use: `bash scripts/tools/memory.sh up` (`local` is an
  alias). It runs Python directly in the foreground and stores private state outside
  the repository. No Docker, MemOS, model service or additional Python package is required.
- Existing MemOS: use `memos-import`/`memos-export` against its self-hosted `/product`
  API; do not substitute the hosted Cloud API. Check its version and response contract.
  This package connects to an endpoint; it does not deploy the upstream service.

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

Run `verify` against the gateway. Run `verify-memos` only with an explicitly configured `MEMOS_ENDPOINT`;
it writes synthetic probes to a new cube and leaves them for inspection. Record the
returned namespace/cube for subsequent operator cleanup.

Report these separately:

1. CPU regressions: `CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python -m pytest -q tests/cpu/memory`.
2. Live local gateway: `bash scripts/tools/memory.sh verify`.
3. Live MemOS: `bash scripts/tools/memory.sh verify-memos`.
4. Actual Codex/Claude Code tool use, when those clients are available.

An HTTP fixture proves protocol handling, not MemOS deployment. A health check proves
liveness, not working embedding or retrieval. A local read-only snapshot is not a
snapshot of all upstream MemOS data: imports materialize only reviewed retrieved entries.
Keep agent tools limited to search/get/propose/feedback. Never route a model-provided
namespace, cube, credential or verification decision into administrator operations.

If deployment fails, inspect this project's logs and readiness first; fix the concrete
cause and retry at most three times before reporting the remaining prerequisite.
Without an existing MemOS endpoint, complete local validation and report MemOS checks
as unavailable. Do not install infrastructure or send project data to hosted services
merely to turn a check green.

## Current implementation limits

This is an initial private deployment, not a hardened public SaaS. The service binds
loopback by default; use a TLS/authenticated ingress or SSH tunnel for remote clients and keep
MemOS itself private. SDK callers and agent tools use fixed namespace/session/snapshot
credentials. Local agents with filesystem access to the database or admin credential are
outside that isolation boundary; keep server state inaccessible to their sandbox.

Retrieval is deterministic keyword matching over materialized records with a **byte**
budget. It does not claim exact tokenizer accounting. MemOS writes are explicit and not
automatically retried; ambiguous network failures need reconciliation. The separate center demo supports expiry scheduling. Credential rotation, shared-library
publication UI, GPU training/cohort automation and managed multi-node HA are not implemented. Do not present those draft
features as available.

## Performance diagnosis prototype

For script/log/trace input with historical performance cases, follow
[the performance walkthrough](references/performance-prototype.md). It runs locally
without a service, produces an offline review page, and demonstrates selected remote
publication and cached reads through a temporary real HTTP service. Use `perf-doctor`
for evidence-based interpretation. The prototype's rule-generated suggestions are
hypotheses, not measured bottlenecks; synthetic parser tests are not GPU validation.
Local MCP also accepts `--state-dir` with a bound agent token, avoiding a local HTTP daemon.

## Visual memory center demo

Use `python examples/memory/center_demo.py up` to run the single-operator browser
center in the background. `status` returns its access URL and `down` stops only its
own process, retaining data. Defaults: loopback port 8766 and
`~/.local/state/relax-memory-center`. For shared access use an explicitly reachable
host and protect the management capability; this is not multi-user authorization.

The UI supports submit, approve/reject, revisions, review reminders, manual expiry,
automatic TTL processing and actual Agent read preview. New core snapshots filter TTL
independently of the center's 10-second sweep; old snapshots retain their contents.
See [the demo handbook](../../docs/draft/memory-center-demo.md). Center and performance
walkthrough databases remain separate unless deliberately integrated.
