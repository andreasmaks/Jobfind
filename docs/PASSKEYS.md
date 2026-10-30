# Passkey sign-in

Jobfind supports the native WebAuthn API. Keep the password as a recovery method.
After signing in, choose **Manage passkeys** in the header information/settings.
Enter a label and confirm the current Jobfind password. Then tap **Create passkey
on this device** and approve the native device/password-manager prompt. This second
explicit tap opens WebAuthn directly from a user gesture, without a preceding network
await. Password-check failures keep the input for correction and show a focused alert
above the fields. The login page offers **Sign in with passkey**.
The same management dialog can revoke a key after password confirmation. This
revokes its server credential and sessions signed in with that key, not the copy
held by a device/password manager. The confirming browser receives a fresh password-
authenticated session so removing its own key does not lock out the owner.

Production requires the configured HTTPS `server.public_origin`. The RP ID is
exactly its hostname; credentials cannot automatically move to a different domain.
Loopback HTTP is only supported for local development. No browser-side library,
third-party login provider or paid authentication service is needed. Install
`requirements.txt` before restarting the service.

Private keys and device biometrics do not go to Jobfind. Only public credential
keys, counters, labels and timestamps are kept in the existing private auth database.
Registration and removal require a valid session, same-origin request, CSRF token
and password confirmation. Authentication requires user presence and verification,
an exact origin/RP ID match, signature verification and the expected owner handle.
Challenges expire after five minutes, are single-use, and are bound to an HttpOnly,
SameSite=Strict browser cookie; registration also binds them to the current session.
Limits apply to pending ceremonies, stored credentials and failed login attempts.
No passkey ceremonies or credentials are stored in the offline queue/service-worker
cache. Offline snapshots retain their existing access behavior; passkey changes need
an online connection. Existing logged-in sessions do not need re-enrollment.

`jobfind.py password` is the recovery/reset operation: it now revokes both existing
sessions and all passkeys/challenges. Back up the private auth database before an
upgrade; never publish it, its keys or private configuration.

Verification: `python tests/check_passkeys.py` generates ephemeral EC keys and runs
real signed ceremonies against an isolated local server. It covers successful login,
tampering, origin/RP mismatch, missing user verification, replay, cookie binding,
expiry, cross-origin clients, deletion, rate limits and password-reset recovery.
No production credentials, browser automation or external requests are used.
Device-specific native prompts (Face ID, Touch ID, device PIN, password-manager sync)
must still be checked by the owner on their device.

Implementation references: [Duo registration](https://duo-labs.github.io/py_webauthn/registration.html),
[Duo authentication](https://duo-labs.github.io/py_webauthn/authentication.html),
[WebAuthn specification](https://www.w3.org/TR/webauthn-3/).
