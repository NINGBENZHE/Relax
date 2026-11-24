# Project Memory

Relax project memory stores reusable model configurations, troubleshooting lessons, and development workflows. Use Cowork to share team knowledge after administrator review. Run local memory for private experiments and offline work. Both can be registered in Codex at the same time. Each has its own data, credentials, and approval process. Sharing a local entry requires an explicit proposal.

| Capability | Cowork team center | Local memory |
| --- | --- | --- |
| Runtime | Standalone stdio MCP client connects to an existing HTTPS center | stdio MCP uses a local HTTP gateway or accesses SQLite directly |
| Credentials | Direct access requires an authorized application token. Proposing also requires a personal credential | An administrator credential handles review. An agent credential binds a namespace, task, and snapshot |
| Reads | Read-only mode shows current approved, unexpired entries. Personal tasks use a fixed snapshot | Each task reads the snapshot created at binding |
| Proposal format | `memory_propose(body, idempotency_key)` | `memory_propose(record, idempotency_key)` |

Installation requires Bash, Python 3.10+, and a Relax checkout containing project memory. Automatic registration requires the Codex CLI. Neither mode requires a GPU, Ray, Docker, or a model service.

## Connect to Cowork

Set `RELAX_MEMORY_COWORK_ENDPOINT` to the machine HTTPS base URL provided by your administrator, with no `/api/agent` or `/api/network/agent` suffix. For device enrollment, set `RELAX_MEMORY_LOGIN_URL` to the MiniApp base URL you can sign in to with a browser. The machine and browser URLs can differ. If an unauthenticated terminal request to the machine URL returns 401, use the browser URL supplied by your administrator.

The enable command downloads the compatible MCP client from the configured Cowork endpoint, verifies its release digest, installs it outside Git and registers it with Codex. With only `RELAX_MEMORY_COWORK_ENDPOINT` set, `bash scripts/tools/memory.sh enable` enables read-only access. Set `RELAX_MEMORY_LOGIN_URL` to enroll a device with write access. Repeating the command reuses a matching installation. The offline gateway runs independently.

### Read-only access

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh enable \
  --endpoint "$RELAX_MEMORY_COWORK_ENDPOINT" --read-only
```

Supply an authorized application token or file path at the hidden prompt, or pass a file with `--app-token-file`. The installer checks connectivity and registers `relax-memory`. Open a new session to use `memory_search` and `memory_get`. Read-only installation requires no personal credential.

### Access with proposals

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh enable \
  --endpoint "$RELAX_MEMORY_COWORK_ENDPOINT" --login-url "$RELAX_MEMORY_LOGIN_URL"
```

Supply the application token. Open the terminal's `registration_url` in a browser, sign in, and confirm the device. Keep the installer running. Once an administrator approves the device, the installer retrieves the personal credential, checks connectivity, and registers MCP. The enrollment window is 15 minutes. If you already have a personal credential, use `remote setup --client codex`. It also accepts `--credential-file` and `--app-token-file`.

The client installs under `${XDG_DATA_HOME:-$HOME/.local/share}/relax-memory-remote` and runs independently of the checkout afterward. Use `enable --prefix <directory> ...` to choose a directory outside the repository. Other stdio MCP clients can import the configuration from `--client config`.

Use `--replace --replace-mcp` to upgrade a read-only installation or replace an existing one in place. The installer reuses a saved application token only for the same endpoint. Use `--via-relay` if your administrator provides an existing intranet relay that holds the application token. If connectivity fails after the personal credential is retrieved, retry with the installed client's `check`, then run `register-codex`.

## Start local memory

Run from the repository root in terminal A. Keep the state directory on private persistent storage outside the repository.

```bash
export RELAX_MEMORY_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/relax-memory"
export RELAX_MEMORY_HOST=127.0.0.1
export RELAX_MEMORY_PORT=8765
export RELAX_MEMORY_ENDPOINT="http://127.0.0.1:$RELAX_MEMORY_PORT"
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh up
```

The gateway runs in the foreground. Ctrl-C stops it and retains data. If the port is occupied, update both `RELAX_MEMORY_PORT` and `RELAX_MEMORY_ENDPOINT`. Set the same state directory and local URL in terminal B, then create a task and register MCP.

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh status
python3 -m relax.memory project \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file "$RELAX_MEMORY_STATE/admin.json" \
  --namespace personal/dev/relax --session task-001 \
  --output-dir "$RELAX_MEMORY_STATE/tasks/task-001"
codex mcp add relax-memory-local --env "PYTHONPATH=$PWD" -- \
  "$(command -v python3)" -m relax.memory mcp \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

The task directory contains `agent.json` and `mcp.json` for other stdio MCP clients. Keep `admin.json` with the operator and give the agent only its task credential. Open a new session to use `relax-memory-local`. An initially empty database produces an empty result.

After binding, you can also configure MCP with the command below, keeping the repository on `PYTHONPATH`. You can then stop the gateway. New task bindings and administrative review still use HTTP.

```bash
python3 -m relax.memory mcp \
  --state-dir "$RELAX_MEMORY_STATE" \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

## Search, propose, and review

At task start, ask the agent to search by model, module, or symptom, then open relevant entries by ID and check current code, versions, and applicability. MCP's `max_bytes` controls the response in bytes. Clients with write access can submit candidates with `memory_propose` or use a read receipt to mark evidence helpful, outdated, or incorrect with `memory_feedback`. Feedback records an assessment without changing the entry.

You can also call the installed Cowork client directly. With a custom install directory, use the launcher path printed by the installer.

```bash
MEMORY="${XDG_DATA_HOME:-$HOME/.local/share}/relax-memory-remote/relax-memory"
"$MEMORY" check
"$MEMORY" search 'Qwen3.5 OOM' --limit 5
"$MEMORY" get '<memory-id>'
"$MEMORY" propose --body-file ./candidate.json --idempotency-key 'issue-123-oom-v1'
"$MEMORY" feedback '<receipt-id>' helpful
```

Each candidate should address one reusable problem. Describe the trigger, actions, validation, and limits. Cite the actual revision, documentation, or experiment. The following Cowork `candidate.json` illustrates the format. Replace the values with your own evidence.

```json
{
  "title": "Investigate Qwen3.5 log-prob memory usage",
  "summary": "Identify the OOM phase before adjusting its token budget.",
  "content": "Trigger: OOM in train_log_probs. Action: reduce the log-prob token budget. Validation: measure peak memory and timing with the same input. Limit: covers only this phase.",
  "source": "Relax@<commit>; docs/en/guide/oom-troubleshooting.md",
  "owner": "<maintainer>",
  "kind": "strategy",
  "evidence_level": "documented",
  "topic": "diagnosis/oom",
  "tags": ["Qwen3.5", "OOM"],
  "conditions": "Megatron training path. Repeat on the target hardware.",
  "review_after": null,
  "expires_at": null
}
```

Required fields are `title`, `summary`, `content`, `source`, `owner`, `kind`, and `evidence_level`. Use `strategy`, `lesson`, or `episode` for `kind`. The evidence levels `documented`, `tested`, and `hypothesis` distinguish documentation, actual tests, and unverified claims. Dates are timezone-aware ISO8601 or `null`. The review date prompts a check, while expiry affects inclusion in new snapshots. Reuse the same idempotency key for a network retry with the same content.

A Cowork proposal returns `pending` and a candidate ID for administrator review. A personal MCP process starts its task snapshot on the first tool call. After approval, restart the MCP process or open a new session to see the update. Read-only mode shows current approved entries.

Local proposals use `record`. See the [local candidate example](../../../examples/memory/knowledge.json). After checking the evidence, an administrator uses `candidate_list` and `candidate_commit`. See the [local operations reference](../../../skills/memory/references/operations.md#add-and-review-knowledge). After approval, bind a new session in a new directory and update the MCP credential path. Ordinary revisions and expiry preserve old snapshots. To share a local entry, convert it to the Cowork candidate format and submit it for review there.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cowork returns 401 or 403 | Verify the machine URL, application token, personal credential expiry, and membership. Run the installed client's `check` |
| Local gateway is unreachable | Check `status`, the port, and whether `RELAX_MEMORY_ENDPOINT` points to this machine |
| An approved entry is missing | Check the snapshot, query, expiry, and byte budget. A personal task needs a new binding or MCP process |
| MCP is missing or the name already exists | Open a new session and check registration. Use different names for local and Cowork clients, and explicitly replace a registration when updating it |

Optional MemOS import and export support an explicitly configured self-hosted service. See the [local operations reference](../../../skills/memory/references/operations.md).
