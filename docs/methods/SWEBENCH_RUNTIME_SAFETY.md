# SWE-bench runtime safety

The `swebench-is-mh-v7` result schema and `swebench-testbed-v2` task environment
protocol apply the same runtime protections to baseline and scaling sessions.
They change execution semantics and configuration fingerprints: use a new run tag
or output directory instead of resuming a previous protocol's results.

## Prepared task environment

Each tool call activates `/opt/miniconda3/envs/testbed`. Before sampling, a probe
checks the interpreter, checkout directory, repository import, and test-runner
import. Startup failures are recorded and their containers are cleaned up.
Checkpoint restoration checks the interpreter and directory without importing
candidate-modified project code.

Use `experiments.swebench.preflight --task-instance INSTANCE_ID --skip-api` to
probe an actual task environment without a model call. The option is repeatable.

The tool shell enables `pipefail`, so an upstream test failure piped into `tail`
is not reported as success merely because `tail` succeeded. This is not a general
test oracle: later successful commands, explicit error suppression, or nested
shells can still mask failures. Inspect actual test output and prefer focused,
standalone repository test commands. Global `errexit` is not enabled.

## Submission checks

A `Submitted` event is accepted only when its content is nonempty, contains a
git diff header, and is parsed successfully by `git apply --numstat -z -` in an
isolated temporary directory. Rejected submissions become tool observations so
the agent can correct them within its existing budgets. Validation results and
submission hashes are retained in trajectory runtime metadata.

This checks syntax, not applicability to the task checkout or correctness.
Official evaluation remains authoritative. Explanatory prose is not substituted
for a patch, and no official hidden tests are used to guide generation.

## Finalization and audit

`agent.finalization_reserve_steps` defaults to **5**. One reminder is inserted
before prompt tokenization when at most that many model calls remain. It does not
extend budgets or switch a Thinking IS sampler to ordinary generation.
Checkpoint messages preserve the reminder so it is not duplicated on restore.
Set the option to `0` to disable it.

`agent.audit_patch_timeout_seconds` defaults to **10**. Before cleaning up a
non-submitted session, a bounded read-only audit records the tracked workspace
diff and names of untracked files. Each output is capped at 1 MiB and truncation
is recorded. Untracked file contents are not saved. Audit failures are diagnostic
only; **the audit never becomes an official submission**. Set the option to `0`
to disable it.

Both options participate in configuration fingerprints. Old configurations that
omit them now resolve to these new defaults; historical reproduction requires the
historical source/configuration rather than silently reusing old result folders.

## Sampling diagnostics storage

Full Thinking IS diagnostics are stored losslessly in
`thinking_is.<SHA256>.json.gz`. The lightweight `record.json` retains summary
counts, protocol metadata, the artifact reference, and its checksum. Predictions
and routine summaries do not need to parse all sampling details. Resume checks
reject missing or corrupt diagnostic artifacts.

```python
from pathlib import Path
from experiments.swebench.io import load_record

record = load_record(Path("instance/record.json"), include_sampling_details=True)
requests = record["diagnostics"]["thinking_is"]["requests"]
```

This loader also supports historical inline diagnostics. Archive the record and
referenced gzip artifact together. Compression reduces storage and summary-read
cost, but does not stream sampling details out of memory during generation.
