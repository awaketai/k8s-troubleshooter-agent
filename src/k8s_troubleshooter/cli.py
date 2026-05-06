from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from k8s_troubleshooter.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k8s-troubleshooter",
        description="Kubernetes troubleshooting agent",
    )
    parser.add_argument("--kubeconfig", help="Path to kubeconfig file")
    parser.add_argument("--context", help="Kubeconfig context name")
    parser.add_argument("--config", help="Path to YAML config file")
    parser.add_argument("--namespace", help="Default namespace")
    parser.add_argument("--max-tool-calls", type=int, help="Max tool calls per diagnosis")
    parser.add_argument("--log-tail-lines", type=int, help="Max log lines per container")
    parser.add_argument(
        "--enable-secret-check",
        action="store_true",
        default=None,
        help="Enable Secret metadata check (requires secrets get permission)",
    )
    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    overrides = {}
    if args.kubeconfig:
        overrides["kubeconfig"] = args.kubeconfig
    if args.context:
        overrides["context"] = args.context
    if args.namespace:
        overrides["namespace"] = args.namespace
    if args.max_tool_calls is not None:
        overrides["max_tool_calls"] = args.max_tool_calls
    if args.log_tail_lines is not None:
        overrides["log_tail_lines"] = args.log_tail_lines
    if args.enable_secret_check is not None:
        overrides["enable_secret_check"] = args.enable_secret_check

    config = load_config(config_path=args.config, **overrides)

    from k8s_troubleshooter.main import run

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
