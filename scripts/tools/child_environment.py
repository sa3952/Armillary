"""The one definition of what a check's child process may inherit.

Some variables change what a tool selects, loads or reads without appearing on
its command line: PYTEST_ADDOPTS='-k nothing' or '--deselect=...' empties a
suite that still passes; PYTHONPATH and NODE_OPTIONS load other code; GIT_DIR
points git at another repository; PLAYWRIGHT_*/PW* move or pause the browser.
Every runner that starts a check, a gate or a test run filters its children
through this module, so the lists cannot drift apart:

  * `allowed_environment` is the check's allow-list (`make check`, `make slow`
    under Gate F): only the names in CHILD_ENVIRONMENT_NAMES pass;
  * `without_tool_control` is the gates' deny-list (they keep the caller's
    Docker, scanner and proxy settings): every tool-control name is dropped;
  * `selection_environment` names the variables set that would leave tests out
    of a pytest run without a skip to account for them (tests/conftest.py
    refuses them where every layer must run).

Where every layer must run (CI and Gate F set ARMILLARY_REQUIRE_ALL=1), a
layer that could not be observed is a failure, not a pass: `skip_is_failure`
is that rule for a skipped test, applied by tests/conftest.py to pytest and by
verify_delivery to the node runner's skips.
"""
from __future__ import annotations

from collections.abc import Mapping
import os


# The only variables a check's child sees.
CHILD_ENVIRONMENT_NAMES = (
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "ARMILLARY_PUBLICATION_RULES_FILE",
    "TMPDIR", "XDG_CACHE_HOME", "PYTHONPYCACHEPREFIX", "CI", "GITHUB_ACTIONS", "ARMILLARY_REQUIRE_ALL",
)

# Variables that change which tests a pytest run collects.
SELECTION_ENVIRONMENT = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")

TOOL_CONTROL_ENVIRONMENT = frozenset({
    *SELECTION_ENVIRONMENT, "PYTEST_DEBUG",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONUSERBASE",
    "NODE_OPTIONS", "NODE_PATH",
    "ARMILLARY_E2E_SERVE_ROOT", "PWDEBUG", "PWDEBUGIMPL", "PWPAUSE",
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
    "MAKEFLAGS", "MAKEFILES", "GNUMAKEFLAGS", "MFLAGS",
})
TOOL_CONTROL_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "PLAYWRIGHT_", "PW_", "PWTEST_")


def is_tool_control(name: str) -> bool:
    return name in TOOL_CONTROL_ENVIRONMENT or name.startswith(TOOL_CONTROL_PREFIXES)


def allowed_environment(environment: Mapping[str, str] | None = None, /, **extra: str) -> dict[str, str]:
    """The allow-listed names of `environment` (default: this process's), plus `extra`."""
    source = os.environ if environment is None else environment
    allowed = {name: source[name] for name in CHILD_ENVIRONMENT_NAMES if name in source}
    allowed.update(extra)
    return allowed


def without_tool_control(environment: Mapping[str, str] | None = None, /, **extra: str) -> dict[str, str]:
    """`environment` (default: this process's) without any tool-control name, plus `extra`."""
    source = os.environ if environment is None else environment
    kept = {name: value for name, value in source.items() if not is_tool_control(name)}
    kept.update(extra)
    return kept


def tool_control_names(environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The tool-control names set in `environment`, sorted."""
    source = os.environ if environment is None else environment
    return tuple(sorted(name for name in source if is_tool_control(name)))


def selection_environment(environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The SELECTION_ENVIRONMENT names set to a non-blank value."""
    source = os.environ if environment is None else environment
    return tuple(name for name in SELECTION_ENVIRONMENT if source.get(name, "").strip())


REQUIRE_ALL = "ARMILLARY_REQUIRE_ALL"

# Skips that are a property of who runs the suite, not a layer left unobserved:
# each names the one test (pytest node id, parameters aside) that may skip, with
# its reason, and only as root.  A reason alone would admit any test using it.
EXPECTED_SKIPS = {
    "tests/repository/test_verifiers_fail_closed_on_empty_input.py"
    "::test_root_owned_tree_check_refuses_a_subtree_it_cannot_list": "root lists every directory",
    "tests/repository/test_verifiers_fail_closed_on_empty_input.py"
    "::test_candidate_clean_script_fails_when_its_pollution_search_fails": "root lists every directory",
    "tests/deployment/test_host_install.py"
    "::test_the_readback_of_the_host_itself_refuses_to_run_without_root":
        "the refusal is for another user than root",
}


def require_all(environment: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return source.get(REQUIRE_ALL) == "1"


def _dotted_test(node_id: str) -> str:
    """One spelling for a pytest node id and its JUnit form (dotted class name
    plus test name), without parameters."""
    return node_id.split("[", 1)[0].replace(".py::", ".").replace("/", ".").replace("::", ".")


_EXPECTED_DOTTED = {_dotted_test(node_id): reason for node_id, reason in EXPECTED_SKIPS.items()}


def skip_is_failure(reason: str, node_id: str, environment: Mapping[str, str] | None = None,
                    *, euid: int | None = None) -> bool:
    # The whole reason must be the expected one (pytest prefixes "Skipped: "):
    # a reason that merely contains one is another skip.
    if not require_all(environment):
        return False
    reason = reason.strip().removeprefix("Skipped: ")
    euid = os.geteuid() if euid is None else euid
    return not (euid == 0 and _EXPECTED_DOTTED.get(_dotted_test(node_id)) == reason)
