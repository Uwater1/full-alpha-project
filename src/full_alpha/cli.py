"""Explicit intake, GET-only recovery, and registry inspection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from full_alpha.client import Client, ResearchError, atomic_write, encode, load_inputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("ASHARE_BASE_URL"))
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Read live health/readiness/metadata; no simulation")
    doctor.add_argument("--out", type=Path, required=True)
    catalog = commands.add_parser("catalog", help="Query live registries; paginate with --offset")
    catalog.add_argument("kind", choices=["fields", "operators", "universes", "compatibility-profiles"])
    catalog.add_argument("--search", default="")
    catalog.add_argument("--offset", type=int, default=0)
    catalog.add_argument("--limit", type=int, default=50)
    for name in ("validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--protocol", type=Path, required=True)
        command.add_argument("--candidates", type=Path, required=True)
        if name == "run":
            command.add_argument("--run-dir", type=Path, required=True)
            command.add_argument("--wait-seconds", type=float, default=600)
    resume = commands.add_parser("resume", help="Collect a known job with GET only")
    resume.add_argument("--run-dir", type=Path, required=True)
    resume.add_argument("--wait-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("Set ASHARE_BASE_URL or --base-url")
    client = None
    try:
        client = Client(args.base_url, token=os.environ.get("HF_TOKEN", ""),
                        api_key=os.environ.get("ASHARE_API_KEY", ""))
        if args.command == "doctor":
            evidence = client.doctor()
            args.out.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(args.out, encode(evidence))
            print("Readiness:", evidence["readiness"]["state"])
            return 0 if evidence["readiness"]["state"] == "READY" else 2
        if args.command == "catalog":
            print(json.dumps(client.json("GET", "/api/v1/" + args.kind,
                                         params={"q": args.search, "offset": args.offset,
                                                 "limit": args.limit}), indent=2))
            return 0
        if args.command == "resume":
            result = client.resume(args.run_dir, wait_seconds=args.wait_seconds)
        else:
            inputs = load_inputs(args.protocol, args.candidates)
            if args.command == "validate":
                result = client.json("POST", "/api/v1/mining/validate", json=inputs["payload"])
                for item in result["items"]:
                    print(item["candidate_id"], "valid" if item["valid"] else item["error"]["code"])
                return 0 if all(item["valid"] for item in result["items"]) else 2
            result = client.start(inputs, args.run_dir, wait_seconds=args.wait_seconds)
        for item in result["items"]:
            print(item["candidate_id"], item["state"],
                  item["result"]["run_id"] if item["result"] else (item.get("error") or {}).get("code", ""))
        print("Collection saved. Job completion is not alpha acceptance.")
        return 0 if result["state"] == "complete" else 2
    except (ResearchError, OSError, ValueError, KeyError, TypeError) as exc:
        # Known client errors are safe; malformed remote structures get a generic message.
        print(str(exc) if isinstance(exc, ResearchError) else f"Client failed: {type(exc).__name__}")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
