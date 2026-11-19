import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="trae2api")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "login"],
                        help="serve: start the OpenAI-compatible proxy (default); "
                             "login: run the full OAuth login flow and save credentials")
    parser.add_argument("--timeout", type=float, default=1800.0, help="login callback timeout (seconds)")
    parser.add_argument("--no-browser", action="store_true", help="login: do not auto-open the browser")
    parser.add_argument("--creds", default=None, help="credentials file path (default trae2api/trae2api.json)")
    parser.add_argument("--prepare-device", action="store_true", help="login: register/activate the independent device without OAuth")
    args, extra = parser.parse_known_args()

    if args.command == "login":
        if extra:
            parser.error("unrecognized login arguments: " + " ".join(extra))
        from .login import run_login
        try:
            run_login(timeout_sec=args.timeout, open_browser=not args.no_browser,
                      creds_file=args.creds, prepare_only=args.prepare_device)
        except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
            parser.exit(1, f"Login failed: {exc}\n")
        return
    from .server import main as serve_main
    serve_main()


if __name__ == "__main__":
    main()

