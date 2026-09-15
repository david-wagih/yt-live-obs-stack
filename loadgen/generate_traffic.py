#!/usr/bin/env python3
"""Tiny traffic generator for the observability demo API. No dependencies beyond stdlib."""
import argparse
import random
import time
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://localhost:8000"
NORMAL_ENDPOINTS = ["/", "/api/orders", "/health"]
INCIDENT_ENDPOINTS = ["/", "/api/orders", "/health", "/error", "/slow"]
INCIDENT_WEIGHTS = [3, 3, 2, 2, 1]


def hit(base_url: str, path: str, timeout: float = 10.0):
    start = time.monotonic()
    url = f"{base_url}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError:
        status = None
    elapsed = time.monotonic() - start
    return path, status, elapsed


def pick_path(mode: str) -> str:
    if mode == "normal":
        return random.choice(NORMAL_ENDPOINTS)
    if mode == "errors":
        return "/error"
    if mode == "slow":
        return "/slow"
    if mode == "incident":
        return random.choices(INCIDENT_ENDPOINTS, weights=INCIDENT_WEIGHTS)[0]
    raise ValueError(f"unknown mode: {mode}")


def run(mode: str, base_url: str, duration, rate: float) -> None:
    end_time = time.monotonic() + duration if duration else None
    count = 0
    try:
        while end_time is None or time.monotonic() < end_time:
            path = pick_path(mode)
            path, status, elapsed = hit(base_url, path)
            count += 1
            if count % 5 == 0 or status is None or (status and status >= 500):
                print(f"[{count}] {path} -> {status} ({elapsed:.2f}s)")
            time.sleep(max(0.0, 1.0 / rate))
    except KeyboardInterrupt:
        print("\nstopped by user")
    print(f"total requests: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Traffic generator for the observability demo")
    parser.add_argument("mode", choices=["normal", "errors", "slow", "incident"])
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument(
        "--duration", type=float, default=None, help="seconds to run; omit to run until interrupted"
    )
    parser.add_argument("--rate", type=float, default=2.0, help="requests per second")
    args = parser.parse_args()

    print(f"generating '{args.mode}' traffic against {args.base_url} (ctrl-c to stop)")
    run(args.mode, args.base_url, args.duration, args.rate)


if __name__ == "__main__":
    main()
