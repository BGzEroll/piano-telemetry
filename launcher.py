import sys

from piano_telemetry.app import main


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        from piano_telemetry.windows_desktop import run_windows_desktop

        raise SystemExit(run_windows_desktop())
    raise SystemExit(main())
