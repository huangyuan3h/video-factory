"""Phase 3: error-code enum (E_* surfaced in --json). No network, no render."""
from src.services import error_codes as ec


def test_all_five_required_codes_exist():
    for code in ("E_CREDENTIALS", "E_BACKEND_OVERLOAD", "E_PNG_READ", "E_QA_FAIL", "E_MEMORY"):
        assert code in ec.ALL_CODES, f"missing {code}"


def test_code_for_direct_passthrough():
    assert ec.code_for("E_CREDENTIALS") == "E_CREDENTIALS"
    assert ec.code_for("E_QA_FAIL") == "E_QA_FAIL"
    assert ec.code_for("E_MEMORY") == "E_MEMORY"
    assert ec.code_for("E_PNG_READ") == "E_PNG_READ"
    assert ec.code_for("E_BACKEND_OVERLOAD") == "E_BACKEND_OVERLOAD"


def test_code_for_known_keys():
    assert ec.code_for("usage") == ec.E_USAGE
    assert ec.code_for("ledger-missing") == ec.E_LEDGER
    assert ec.code_for("not-found") == ec.E_NOT_FOUND
    assert ec.code_for("qa-fail") == ec.E_QA_FAIL
    assert ec.code_for("low-disk") == ec.E_MEMORY
    assert ec.code_for("public-needs-force") == ec.E_CREDENTIALS
    assert ec.code_for("import-fail") == ec.E_BACKEND_OVERLOAD


def test_code_for_heuristics():
    assert ec.code_for("invalid_grant expired") == ec.E_CREDENTIALS
    assert ec.code_for("backend overloaded 503") == ec.E_BACKEND_OVERLOAD
    assert ec.code_for("Invalid upload request png") == ec.E_PNG_READ
    assert ec.code_for("qa gate failed") == ec.E_QA_FAIL
    assert ec.code_for("low memory pressure") == ec.E_MEMORY


def test_code_for_unknown_defaults_blocked():
    assert ec.code_for("something-weird") == ec.E_BLOCKED
    assert ec.code_for("") == ec.E_BLOCKED
    assert ec.code_for(None) == ec.E_BLOCKED
