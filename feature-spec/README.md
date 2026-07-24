# Feature specifications

Use flat, dot-namespaced Markdown files.

```text
Product.md
Product.Accounts.md
Product.Accounts.PasswordReset.md
TODO.Product.Accounts.Passkeys.md
```

Each file begins with an H1 exactly matching the feature name without the `TODO.` prefix.

Use observable, testable normative requirements:

```markdown
# Product.Accounts.PasswordReset

## Requirements

- A reset link MUST expire after the configured lifetime.
- A used reset link MUST NOT be accepted again.
- Requesting a reset MUST NOT reveal whether an email address has an account.
```

Avoid source paths, class names, function names, implementation plans, priorities, or estimates. Tests should reference the most specific active feature name in a comment or annotation.
