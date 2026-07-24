# Authentication and authorization testing

> Verify identity establishment and every authorization decision separately; test denial, cross-tenant isolation, revocation, replay, and information leakage as first-class behavior.

## Authentication

Test valid and invalid credentials without account enumeration, lockout/rate policy, password-manager/copy-paste compatibility, session rotation after login/privilege change, logout/revocation, expiry, CSRF/session binding, MFA recovery, OAuth/OIDC state/nonce/PKCE and redirect validation, and safe errors/logs. Control clocks for expiry tests.

## Authorization matrix

Create a decision table across role, tenant/owner, resource state, action, and channel/API. Test every allow and representative deny combination. Denial must occur server-side even when the UI hides the action. Verify direct object references, bulk endpoints, exports, background jobs, and websocket/event subscriptions.

## Monotonicity and negative properties

A user with fewer permissions must never gain an action solely through another route or object representation. Changing object IDs, nested tenant IDs, filter parameters, or pagination cursors must not cross the authorization boundary. Denied actions must create no forbidden side effect and should not reveal whether a protected resource exists unless specified.

## State changes

Test role change, account suspension, session revocation, token refresh, stale cached authorization, concurrent revocation/action, and privilege reduction. High-assurance QA verifies audit events and operational detection for repeated denial or credential abuse.
