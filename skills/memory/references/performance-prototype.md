# Performance memory prototype

This is a runnable workflow prototype, not a general performance root-cause engine.
It uses Python standard-library storage and parsing. It never executes input scripts,
submits training, calls a model, installs dependencies, or uploads data implicitly.
The existing design drafts remain unchanged.

## One-command walkthrough

Run from the repository root, choosing a **new** output directory:

```bash
PYTHONPATH=. python examples/memory/performance_demo.py --output /tmp/relax-performance-demo
```

The walkthrough uses the real Kimi K3 script and optimization document. It creates a
private SQLite store, extracts five source-attributed cases, inspects the script,
retrieves a fixed snapshot and emits `diagnosis/report.html`, `report.json` and a
candidate. A trusted demo reviewer records only that the inspection/plan exists,
not that any bottleneck or performance improvement has been proven.

It also runs a real MCP subprocess with local SQLite, starts a temporary loopback HTTP
server, publishes **one selected historical case** as a remote candidate, reviews source
attribution, binds a new remote task, caches its search result locally, and tests a second
business's isolation. The server is shut down before the offline cache is used again.
`walkthrough.json`, `sync-receipt.json`, and `mcp-response.json` retain evidence.

The HTML page is an offline, filterable, read-only review surface. Administration uses
CLI/API. It is not a deployed cloud service or a complete browser management console.
Tests use explicitly synthetic logs/traces to verify parsing, not performance gains.

## Diagnose your own inputs

```bash
export PYTHONPATH=.
python examples/memory/performance.py --db /tmp/my-performance/memory.sqlite seed
python examples/memory/performance.py --db /tmp/my-performance/memory.sqlite diagnose \
  --script examples/models/kimi-k3/scripts/run-kimi-k3-pokemon-lora-64xblackwell.sh \
  --query 'Kimi K3 MLA 编译缓存' --output /tmp/my-performance/task-1
```

Add `--log /path/to/log` or `--trace /path/to/trace.json.gz`; each input flag is repeatable.
Script inspection is static and does not resolve source, environment or trailing argument
overrides. Supply the actual invocation/environment evidence before asserting effective
configuration. No hardware is inferred from filenames.

The log prototype accepts normalized lines `MEMORY_METRIC step=1 duration_s=12.5`
and counts OOM mentions; other log formats are not silently interpreted. Chrome trace
complete kernel events are aggregated with interval unions per pid across streams.
Kernel duration sums are not wall time, MFU, GPU utilization or causal bottleneck proof.
Inputs are capped at 64 MiB decoded; use a bounded window for larger traces.

Reports include exact input hashes, historical evidence, suggested checks and the actual
memory read receipt. Candidate plans remain pending until explicitly reviewed:

```bash
python examples/memory/performance.py --db /tmp/my-performance/memory.sqlite list
python examples/memory/performance.py --db /tmp/my-performance/memory.sqlite review \
  --candidate-id '<id>' --reviewer '<operator>' --claim 'source inspection only; optimization not executed'
```

Do not grant this trusted local review CLI to a restricted agent. Filesystem access to
SQLite bypasses credential isolation; local use assumes one trusted OS user. Keep output
and database directories private, and inspect candidate contents before publication.

## Selected remote publication and task-start cache

Use the existing `project` command to obtain an **agent** credential bound to the intended
remote namespace/session/snapshot; the remote administrator handles provisioning/review.

```bash
python examples/memory/sync.py --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file /path/to/agent.json --db /path/to/local.sqlite publish \
  --namespace relax/performance --snapshot '<local-snapshot-id>' --record-id '<selected-id>'
python examples/memory/sync.py --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file /path/to/new-task-agent.json --db /path/to/local.sqlite pull \
  --namespace cache/team/performance --query 'Kimi 编译缓存'
```

Publish stages candidates only. Remote review does not reuse the local verification decision.
Pull preserves remote IDs/revisions, receipt hash, snapshot and original verification in a
separate cache namespace. It copies only bounded search results, not the whole library;
this is not incremental synchronization. New task credentials are needed for new remote
snapshots. Old cache snapshots remain reproducible and are not automatically refreshed or
revoked. Each pull creates a fresh cache subnamespace and returns `cache_namespace` with its snapshot.
Use that returned namespace for offline diagnosis; repeated pulls never merge old and new selections.

For no-service local MCP, use an agent token bound to the selected local snapshot:

```bash
python -m relax.memory mcp --state-dir /path/to/local-state --token-file /path/to/agent.json
```

`local-state/memory.sqlite` must already exist. The walkthrough leaves a working example
under its `local/` directory. This proves protocol execution, not automatic activation in
an installed Codex/Claude Code client.

## Knowledge contract for the next iteration

Organize performance cases by startup/compilation, input pipeline, rollout, compute,
communication/parallel layout, memory, and end-to-end cost. Keep observed facts,
explanations, and proposed experiments separate. A case should identify the baseline,
changed variables, model/data/code/environment, metric scope, correctness checks,
counterexamples, dependencies on earlier optimizations and original evidence.

Next product increments are effective-argument adapters, actual log format adapters,
applicability checks, source refresh, and authenticated browser review/publication.
Do not present these as implemented by this prototype.
