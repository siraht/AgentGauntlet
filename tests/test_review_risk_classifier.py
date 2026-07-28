"""Focused contract tests for the review engine's risk-path classifier."""

from __future__ import annotations

from aqg.review import _risk_factor_path_hints, _risk_product_surface


def test_product_surface_classifies_every_supported_path_kind() -> None:
    changed = [
        "src/app.py",
        "src/query.sql",
        "docs/query.graphql",
        "docs/service.proto",
        "api/README",
        "migrations/001.txt",
        "schemas/model.json",
        "tests/test_app.py",
        "docs/note.md",
    ]

    assert _risk_product_surface(changed) == changed[:7]


def test_path_hints_have_a_complete_stable_factor_contract() -> None:
    changed = [
        "src/auth_login.py",
        "src/permission_policy.py",
        "src/privacy_consent.py",
        "src/payment_refund.py",
        "migrations/alembic_001.sql",
        "api/openapi_contract.yaml",
        "src/async_worker.py",
        "src/delete_records.py",
        ".github/workflows/quality.yml",
        "tests/test_auth_login.py",
    ]

    assert _risk_factor_path_hints(changed) == {
        "authentication": ["src/auth_login.py"],
        "authorization": ["src/permission_policy.py"],
        "privacy": ["src/privacy_consent.py"],
        "money": ["src/payment_refund.py"],
        "migration": ["migrations/alembic_001.sql"],
        "external_contract": ["api/openapi_contract.yaml"],
        "concurrency": ["src/async_worker.py"],
        "data_loss": ["src/delete_records.py"],
        "supply_chain": [".github/workflows/quality.yml"],
    }
