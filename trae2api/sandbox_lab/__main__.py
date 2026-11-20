"""Independent CLI; no production command or credential path is imported."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ExperimentConfig, local_config
from .fixtures import FIXTURE_IDS, FixtureStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local synthetic-device laboratory (no real accounts or rewards)")
    commands = parser.add_subparsers(dest="command", required=True)
    fixtures = commands.add_parser("fixtures", help="persist synthetic fixtures and lab-only P-256 installation keys")
    fixtures.add_argument("--output-directory", default="logs/sandbox-device-lab/default")
    server = commands.add_parser("mock-server", help="serve the local register/activate protocol")
    server.add_argument("--port", type=int, default=8765)
    experiment = commands.add_parser("run", help="prepare offline, or explicitly execute against loopback")
    experiment.add_argument("--config", required=True, type=Path)
    experiment.add_argument("--execute", action="store_true")
    demo = commands.add_parser("demo", help="run once against an ephemeral loopback server, then stop it")
    demo.add_argument("--output-directory", default="logs/sandbox-device-lab/demo")
    binding_demo = commands.add_parser("binding-demo", help="run signed local account/device quota cases on an ephemeral mock")
    binding_demo.add_argument("--output-directory", default="logs/sandbox-device-lab/binding-demo")
    binding_run = commands.add_parser("binding-run", help="prepare signed identities offline or explicitly test loopback quota")
    binding_run.add_argument("--config", required=True, type=Path)
    binding_run.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            config = local_config(8765, args.output_directory)
            store = FixtureStore(config.output_directory)
            for fixture_id in FIXTURE_IDS:
                store.load_or_create(fixture_id)
            for physical in ("lab-physical-h1", "lab-physical-h2"):
                for installation in ("I1", "I2"):
                    store.installation(physical, installation)
            print(json.dumps({"source_kind": "offline_fixture", "fixtures": list(FIXTURE_IDS),
                "output_directory": str(config.output_directory), "requests_sent": 0,
                "account_binding": "not_run", "online_checkin": "not_run"}))
            return 0
        if args.command == "mock-server":
            from .mock_server import MockServer
            with MockServer(port=args.port) as mock:
                print(f"Local mock: http://127.0.0.1:{mock.server_port}; synthetic accounts and test ledger only", flush=True)
                try:
                    mock.serve_forever(poll_interval=0.1)
                except KeyboardInterrupt:
                    pass
            return 0
        from .runner import run
        if args.command in ("binding-demo", "binding-run"):
            from .binding_runner import run_binding
            if args.command == "binding-demo":
                from .mock_server import running_mock
                with running_mock() as mock:
                    report = run_binding(local_config(mock.server_port, args.output_directory, scenario="binding_quota"), execute=True)
            else:
                report = run_binding(ExperimentConfig.load(args.config), execute=args.execute)
        elif args.command == "demo":
            from .mock_server import running_mock
            with running_mock() as mock:
                report = run(local_config(mock.server_port, args.output_directory), execute=True)
        else:
            report = run(ExperimentConfig.load(args.config), execute=args.execute)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return {"passed": 0, "dry_run": 0, "failed": 1, "budget_exhausted": 3}[report["completion_status"]]
    except (OSError, ValueError, TypeError):
        # Configuration/parser exceptions may contain user-supplied secrets or
        # arbitrary paths. Keep CLI diagnostics fixed rather than echoing them.
        print("Lab input/storage error: check the local config and isolated profiles.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
