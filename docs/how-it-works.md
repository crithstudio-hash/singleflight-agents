# How It Works

This document walks through what happens when multiple agents call the same tool at the same time.

## The problem

You have a multi-agent system. Agent A needs to look up a customer record. Agent B, independently, needs the same customer record. Agent C needs it too.

Without singleflight, all three agents make separate calls. You pay 3x the cost and wait 3x as long (or the same wall-clock if concurrent, but still 3x the API cost).

## The solution in 5 steps

### Step 1: Fingerprint

When a tool is called, singleflight creates a deterministic key from:

```
tool_name + scope + namespace + version + normalized(args) + normalized(kwargs)
    │
    └──> JSON serialize (sorted keys) ──> SHA-256 hash ──> fingerprint key
```

Example key: `singleflight:crm.lookup:a1b2c3d4e5f6...`

Arguments are recursively normalized before hashing:
- Dicts: keys sorted alphabetically
- Sets: converted to sorted lists
- Lists/tuples: preserved in order
- Primitives: used as-is

This means `lookup(email="a@b.com")` always produces the same fingerprint regardless of dict key ordering or other trivial differences.

### Step 2: Check cache

Before doing anything else, check if a valid (non-expired, signature-verified) receipt already exists for this fingerprint.

```
Fingerprint ──> SQLite lookup ──> Receipt exists and not expired?
                                       │
                                  Yes: verify HMAC signature
                                       │
                                  Valid: return cached result (source="cache_hit")
                                  Invalid: treat as cache miss
```

### Step 3: Acquire lease

If no cached receipt exists, try to acquire an exclusive lease on the fingerprint.

```
Try acquire lease
    │
    ├── No existing lease ──> INSERT lease row ──> Acquired (you are the executor)
    │
    ├── Existing lease expired ──> UPDATE lease row ──> Acquired (previous holder crashed)
    │
    └── Existing lease active ──> Not acquired (someone else is executing)
```

The lease is protected by a Python `threading.Lock` to prevent race conditions on the SQLite write.

### Step 4: Execute or wait

**If you acquired the lease (you are the executor):**

```
Execute the tool function
    │
    ├── Measure latency
    ├── Serialize the result (JSON preferred, pickle fallback)
    ├── Sign the result with HMAC-SHA256
    ├── Store as a Receipt in SQLite
    └── Release the lease
```

**If you did not acquire the lease (someone else is executing):**

```
Poll SQLite every 50ms for a receipt
    │
    ├── Receipt appears ──> Verify signature ──> Return shared result (source="shared_wait")
    │
    └── Timeout (35s default) ──> Try to acquire lease again (fallback)
         │
         ├── Acquired ──> Execute the tool yourself
         └── Not acquired ──> Check one more time for receipt ──> Final fallback: execute directly
```

### Step 5: Fan out

All callers end up with the same `ExecutionOutcome`:

```
ExecutionOutcome
    ├── value: the deserialized tool result
    ├── receipt: the signed Receipt object
    └── source: how the result was obtained
         ├── "executed"           ── you ran the tool
         ├── "cache_hit"          ── receipt was already in the store
         ├── "shared_wait"        ── you waited for another caller's result
         ├── "executed_unshared"  ── tool is side-effecting, no dedup
         └── "executed_fallback"  ── all dedup paths failed, ran directly
```

## Receipt signing

Every receipt is signed with HMAC-SHA256 to prevent tampering.

```
signing_secret (generated once per database, stored in metadata table)
    │
    ├── Canonical JSON of: fingerprint, args_hash, output_json,
    │   created_at, expires_at, latency_ms, cost_usd
    │
    └── HMAC-SHA256(secret, canonical_json) ──> hex digest ──> stored as signature
```

Before returning a cached receipt, the signature is re-computed and compared using `hmac.compare_digest` (constant-time) to prevent timing attacks.

If a receipt fails verification, it is treated as a cache miss and the tool is re-executed.

## Safety model

Not all tools should be deduplicated. The `ToolExecutionOptions` safety flags control this:

```
Is the tool side_effecting?
    │
    Yes ──> Always execute independently (source="executed_unshared")
    │
    No ──> Is deterministic OR bounded_read?
              │
              Yes ──> Eligible for dedup (fingerprint, lease, share)
              No ──> Not shared (treated as side-effecting)
```

- `deterministic=True`: Pure function. Same inputs, same output, every time.
- `bounded_read=True`: Read-only call. Output may change over time but is fresh enough within the TTL.
- `side_effecting=True`: Writes, sends, deletes. Never shared, never cached.

## Storage

All data lives in a single SQLite file (default: `.singleflight/receipts.db`).

Three tables:

| Table | Purpose |
|-------|---------|
| `metadata` | Stores the HMAC signing secret (one row). |
| `receipts` | Stores signed execution results, keyed by fingerprint. |
| `leases` | Stores active locks, keyed by fingerprint with owner ID and expiry. |

The database is created automatically on first use. Thread safety is handled via `threading.Lock` around all SQLite operations.
