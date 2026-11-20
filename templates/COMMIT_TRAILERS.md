# Commit trailers for decisions

The journal holds narrative and cross-cutting lessons. A single commit's
decision belongs in the commit itself, as git trailers, so it stays greppable
with plain git and follows the change through rebases. Vocabulary follows the
Lore protocol (arXiv 2603.15566, `npm i -g lore-protocol` for queries; the
trailers work without it).

```
fix(retry): stop retrying on 4xx

Retrying client errors doubled load on the auth service during the incident.

Constraint: retry budget shared with the rate limiter -- max 3 attempts
Rejected: exponential backoff on all statuses | still retries auth failures
Confidence: high
Directive: do not add new statuses to the retry allowlist without a load test
Tested: 429 and 503 under the soak script
Not-tested: partial-response 200s
Supersedes: a1b2c3d4
```

Keys: `Constraint`, `Rejected: alternative | reason`, `Confidence: low|medium|high`,
`Directive`, `Tested`, `Not-tested`, `Supersedes: <lore-id or commit>`.
Use only the ones that apply. Queries without the CLI:

```
git log --format='%h %s%n%(trailers:key=Rejected,valueonly)' -- src/retry/
```
