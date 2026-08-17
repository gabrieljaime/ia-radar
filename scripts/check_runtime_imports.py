#!/usr/bin/env python3
"""Import production entrypoints without running their external operations."""

from importlib import import_module

ENTRYPOINT_MODULES = (
    "scripts.check_sources",
    "scripts.run_radar",
    "scripts.send_digest",
    "scripts.show_latest_run",
)


def main() -> int:
    for module_name in ENTRYPOINT_MODULES:
        import_module(module_name)
    print("Runtime entrypoint imports: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
