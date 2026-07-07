from __future__ import annotations

import sys

USAGE = (
    "usage: conductor <command> [options]\n"
    "\n"
    "commands:\n"
    "  status     show current run state\n"
    "  report     render the cost report\n"
    "  doctor     verify an install for a provider\n"
    "  install    install conductor hooks and policy\n"
    "  uninstall  remove conductor hooks and policy\n"
    "  gc         prune old ledger state\n"
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["-h"], ["--help"]):
        sys.stdout.write(USAGE)
        return 0
    if not args:
        sys.stderr.write(USAGE)
        return 2
    command, rest = args[0], args[1:]
    if command == "status":
        from conductor.status import main as run
        return run(rest)
    if command == "report":
        from conductor.report import main as run
        return run(rest)
    if command == "doctor":
        from conductor.doctor import main as run
        return run(rest)
    if command == "install":
        from conductor.install import main as run
        return run(rest)
    if command == "uninstall":
        from conductor.install import main as run
        return run([*rest, "--uninstall"])
    if command == "gc":
        from conductor.gc import main as run
        return run(rest)
    sys.stderr.write(f"conductor: unknown command {command!r}\n\n")
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
