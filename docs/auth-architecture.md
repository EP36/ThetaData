# Auth Architecture Note (Current + Future)

## Implemented Now
- Single-user admin authentication for backend and dashboard.
- DB-backed `users` table with role and active status.
- DB-backed hashed session tokens (`auth_sessions`) with expiration + revocation.
- Login throttling (`login_attempts`) to reduce brute-force risk.
- Server-enforced route protection on sensitive API endpoints.
- Structured audit events for login/logout and sensitive admin actions.

## Not Implemented Yet
- Self-serve signup, invitations, org/workspace switching, billing, email verification.
- Multi-tenant data partitioning.
- Fine-grained per-resource ACLs beyond role checks.

## Future Multi-User / Product Mode Integration Points
- Add new roles (for example `viewer`, `operator`) by extending role checks in auth dependencies.
- Introduce ownership fields (`user_id`, `owner_id`, or `account_id`) on domain tables where records should be scoped.
- Add tenant/account boundary enforcement in repository query helpers.
- Split auth/session and authorization policy from endpoint handlers into dedicated policy modules.
- Keep frontend as a client of backend authorization decisions (no trust in UI-only route gating).

## Design Intent
- Keep current implementation minimal and secure for single-user operations.
- Preserve schema and service boundaries so future multi-user expansion is additive, not a rewrite.
