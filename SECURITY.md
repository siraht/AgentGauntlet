# Security policy

Please do not disclose suspected vulnerabilities in a public issue.

Use GitHub’s private vulnerability reporting for this repository. Include the affected AQG version, installation mode, reproduction steps, impact, and any evidence showing a policy bypass, unsafe command execution, stale evidence acceptance, secret exposure, or trust-boundary failure.

Only the latest published release is supported with security fixes until a longer support policy is announced.

AQG is a quality and governance control plane, not a sandbox. Local hooks can be bypassed by a sufficiently privileged repository owner or process; authoritative protection requires clean CI, protected branches, reviewed policy inputs, and separate release authority.
