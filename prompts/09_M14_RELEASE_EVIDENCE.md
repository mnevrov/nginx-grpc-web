# M14 — Release Candidate Evidence

Issue: #16
Branch: `agent/m14-release-candidate-evidence`
Base milestone: M13 complete.

## Mission

Implement a conservative, auditable release-candidate evidence pipeline for `v0.1.0`.

The module implementation already satisfies the intended grpc-web v0.1 protocol scope. Do **not** treat M14 as a feature milestone. Treat it as release engineering: bind source, CI results, packaged binary, controlled performance evidence, soak evidence, and operator acceptance into one reproducible release verdict.

The central invariant is:

> No evidence may be reused, copied, inferred, or promoted into a release-ready verdict unless its provenance can be tied to the exact release-candidate source commit, compatible build identity, evidence class, and—where relevant—the same controlled host fingerprint.

## Read first

Before changing code, read:

- `AGENTS.md`
- `README.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/COMPATIBILITY.md`
- `docs/DEPLOYMENT.md`
- `docs/CONTROLLED_BENCHMARKS.md`
- `docs/SOAK_TESTING.md`
- `perf/README.md`
- M14 issue #16

Inspect the existing M11-M13 JSON structures and validation code before choosing a new schema. Reuse existing semantics instead of creating parallel definitions for capacity, host fingerprints, soak policy, or evidence classes.

## Scope freeze

Do not add client streaming, bidi streaming, grpc-web JSON, CORS, auth, routing, retries, service discovery, REST transcoding, or a custom HTTP/2 upstream transport.

Avoid modifying production module C code. If a new release gate exposes a real production defect, first add a deterministic regression that proves it, document why it is a release blocker, then make the narrowest possible fix.

## Required outcome

Implement one operator-facing command, preferably:

```bash
make release-check
```

that creates or validates a self-contained release evidence bundle and emits both machine-readable and human-readable verdicts.

A target bundle should contain the semantic equivalent of:

```text
dist/release/v0.1.0-rc/
  release-evidence.json
  release-evidence.md
  artifacts/
    <versioned package>/
      ngx_http_grpc_web_module.so
      MANIFEST.txt
      SHA256SUMS
  controlled/
    decision.json
    decision.md
    ... provenance-preserving raw evidence ...
  soak/
    soak.json
    events.json
    ... provenance-preserving raw evidence ...
```

The exact layout is not mandatory. Deterministic provenance and inspectability are mandatory.

## Evidence model

The final model must explicitly represent at least:

- release candidate/version;
- exact project commit SHA;
- source-tree cleanliness/provenance where locally observable;
- supported NGINX target identity;
- compiler/toolchain/build identity;
- compatibility/protocol/differential/browser/hardening gate state;
- artifact path/name;
- verified artifact SHA256;
- verified manifest metadata;
- controlled benchmark evidence identity;
- controlled host fingerprint;
- soak evidence identity;
- soak duration/policy identity;
- evidence class;
- verdict;
- deterministic reason codes.

Do not use prose strings as the only representation of important state. Keep verdict/reasons machine-readable.

## Verdict rules

Fail closed.

At minimum, the implementation must enforce these rules:

1. Missing mandatory evidence cannot produce `pass` / `release_ready`.
2. Shared CI / `harness_only` evidence can validate mechanics but can never become production readiness evidence.
3. A controlled benchmark from a different source commit is invalid.
4. A soak result from a different source commit is invalid.
5. Evidence from conflicting controlled host fingerprints cannot be combined into one controlled decision.
6. Artifact checksum must be recalculated and verified, not trusted from metadata alone.
7. Artifact manifest must identify the expected source/build target.
8. Unsupported or mismatched NGINX/compiler identity fails the relevant release gate.
9. Strict production soak must enforce the documented minimum duration rather than accepting a CI smoke duration.
10. Malformed or partially missing JSON/report input must generate an explicit failure reason rather than a traceback-only failure or implicit success.

Prefer explicit states such as `pass`, `fail`, `inconclusive`, with evidence classes such as `harness_only` and `controlled`, if those align with the existing M12/M13 model.

## Development sequence

Use test-first incremental commits.

### Step 1 — inventory and schema contract

Map all existing M8-M13 artifacts and identify which fields already provide:

- source SHA;
- target/version;
- evidence class;
- host fingerprint;
- capacity verdict;
- soak verdict/policy/duration;
- package manifest/checksum.

Write the release evidence schema/contract and pure unit tests before orchestration.

### Step 2 — pure evidence evaluator

Implement deterministic pure logic that consumes fixture inputs and produces the final verdict/reason codes.

Tests must include:

- complete valid controlled evidence;
- missing artifact;
- checksum mismatch;
- manifest mismatch;
- source SHA mismatch;
- unsupported NGINX/build identity;
- missing compatibility/browser gate;
- mixed host fingerprints;
- stale capacity decision;
- stale soak result;
- soak below strict minimum duration;
- harness-only attempted promotion;
- malformed report files.

### Step 3 — artifact/provenance collector

Implement filesystem/report inspection that converts actual repository outputs into the pure evaluator input.

Keep collection separate from decision logic where practical. This makes failure-mode testing reliable and prevents shell orchestration from becoming the source of truth.

### Step 4 — `make release-check`

Wire packaging, evidence collection, validation, JSON/Markdown rendering, and exit status behind one command.

Make it possible to run a bounded mechanics mode in CI without pretending that CI has supplied controlled production evidence.

### Step 5 — GitHub Actions mechanics gate

Add a bounded M14 workflow that validates:

- evaluator tests;
- fixture failure cases;
- module packaging;
- checksum verification;
- manifest/source linkage;
- generated evidence determinism;
- `harness_only -> inconclusive` safety property.

Do not run multi-hour controlled workloads in shared Actions.

### Step 6 — documentation and checklist

Create `docs/RELEASE_EVIDENCE.md` and reconcile `docs/RELEASE_CHECKLIST.md` with the actual M13/M14 state.

The checklist must visibly distinguish:

- code/source gates already demonstrated by repository CI;
- artifact gates;
- controlled-host capacity gates;
- 2-hour strict soak;
- recommended 8-hour RC soak;
- staging acceptance;
- manual tag/GitHub Release creation;
- canary/rollback rollout.

Never mark an item complete just because tooling exists to perform it.

## Validation expectations

Before declaring M14 ready:

- run the new pure unit/fixture tests;
- run packaging validation;
- run the bounded release evidence command in CI/harness mode;
- run relevant existing unit/protocol/hardening tests affected by the changes;
- ensure existing M11-M13 report consumers still work;
- inspect generated JSON and Markdown manually for provenance clarity;
- confirm the final CI-generated result is explicitly non-production (`harness_only/inconclusive` or equivalent);
- confirm no tag or GitHub Release is created automatically.

## Review checklist

During self-review, look specifically for:

- accepting stale evidence by path/name only;
- trusting a SHA stored inside untrusted copied evidence without cross-checking;
- checksum metadata copied but never recalculated;
- accidental mixing of `main` SHA and PR head SHA;
- host fingerprint comparison that ignores relevant fields;
- CI environment accidentally satisfying controlled gates;
- broad exception handling that converts malformed evidence into an empty-but-passing structure;
- timestamps/non-deterministic fields making otherwise identical evidence bundles differ unnecessarily;
- hidden dependency on GitHub API availability for local release verification;
- production C changes unrelated to an observed release blocker.

## Completion criteria

M14 is not complete until every acceptance criterion in issue #16 is satisfied and the exact PR head has green required workflows.

When opening/updating the PR, report:

- exact head SHA;
- new release evidence model;
- commands executed;
- failure cases covered by tests;
- exact CI evidence class/verdict;
- any evidence still requiring M15 controlled/staging execution;
- explicit confirmation that no tag/release was created.

The intended next milestone is M15: execute real controlled-host RC runs, 2h/8h soak evidence, staging acceptance, and canary preparation before manually tagging `v0.1.0`.