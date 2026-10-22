"""A7C II Tools desktop entry. Device access occurs only in explicit worker jobs."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def main():
    if '--offline-self-test' in sys.argv:
        import json
        import runpy
        result = runpy.run_path(str(ROOT / 'dev/desktop/offline_smoke.py'))['run']()
        target = Path(sys.argv[sys.argv.index('--offline-self-test') + 1])
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == '--privileged-worker':
        from desktopapp.platforms.macos_authorization import privileged
        return privileged(Path(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]))
    if len(sys.argv) >= 3 and sys.argv[1] == '--worker':
        from desktopapp.worker import execute_request
        return execute_request(Path(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == '--raw-profile-worker':
        sys.path.insert(0, str(ROOT / 'src/looks'))
        from looktool.rawauto import main as raw_worker
        return raw_worker(['worker', *sys.argv[2:]])
    from desktopapp.worker import setup_runtime
    setup_runtime()  # The GUI may inspect an existing look/recovery job at startup.
    from desktopapp.window import main as gui
    return gui()


if __name__ == '__main__':
    raise SystemExit(main())
