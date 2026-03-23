# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability, please report it privately by emailing the maintainer directly. Do not open a public issue.

You should receive an acknowledgment within 48 hours. A fix will be prioritized and released as soon as practical.

## How this project handles security

### Receipt signing

Every execution result is stored as a **signed receipt** using HMAC-SHA256. The signing secret is generated per database on first initialization (`secrets.token_hex(32)`) and stored in the SQLite `metadata` table.

Before a cached receipt is returned, the signature is verified using `hmac.compare_digest` (constant-time comparison). Tampered receipts are rejected and treated as cache misses.

### What the signing protects against

- Modified outputs in the receipt store (accidental or intentional).
- Replayed receipts from a different database (different signing secret).

### What the signing does not protect against

- An attacker with write access to the SQLite file can read the signing secret and forge receipts.
- The signing secret is stored in plaintext in the database. This is a local-first tool, not a remote trust boundary.

### Pickle deserialization

If a tool returns a value that is not JSON-serializable, it falls back to `pickle` for storage. Pickle deserialization is inherently unsafe with untrusted data. Only use this library with receipt databases you trust.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
