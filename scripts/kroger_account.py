#!/usr/bin/env python3
"""Local Kroger sign-in, preview, and separately confirmed real-cart addition."""

import argparse
import hashlib
import html
import json
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grocery_web.kroger_account import KrogerAccount, AccountError  # noqa: E402
from grocery_web.real_cart import RealCartBridge  # noqa: E402
from grocery_bench.kroger import KrogerAPIError, KrogerConfigurationError  # noqa: E402


def connect(account, redirect_uri=None, timeout=600):
    flow = account.start(redirect_uri)
    uri = urllib.parse.urlsplit(flow["redirect_uri"])
    finished = {"authorized": False, "oauth_completed": False}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log the callback URL, authorization code or state.

        def send_html(self, status, text):
            data = ("<!doctype html><meta charset=utf-8><title>Kroger connection</title>"
                    "<main><h1>Kroger account connection</h1><p>" + text + "</p></main>").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Host") not in {uri.netloc, f"127.0.0.1:{uri.port}", f"localhost:{uri.port}"}:
                self.send_html(400, "Invalid local host")
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/":
                self.send_html(200, 'Sign in to authorize this project to ADD items to your Kroger cart. '
                    'This does not place orders. <a href="' + html.escape(flow["authorization_url"], quote=True) + '">Continue to Kroger</a>')
            elif path == uri.path:
                try:
                    account.complete(f"{uri.scheme}://{uri.netloc}{self.path}")
                except (AccountError, ValueError) as error:
                    self.send_html(400, html.escape(str(error)))
                    return
                finished["oauth_completed"] = True
                self.send_response(303)
                self.send_header("Location", "/connected")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
            elif path == "/connected" and finished["oauth_completed"]:
                self.send_html(200, "Connected. No items have been added. You may close this page.")
                finished["authorized"] = True
            else:
                self.send_html(404, "Not found")

    server = HTTPServer(("127.0.0.1", uri.port), Callback)
    server.timeout = 1
    try:
        print(json.dumps({"status": "waiting_for_kroger_sign_in", "open_url": f"{uri.scheme}://{uri.netloc}/",
                          "registered_redirect_uri_required": flow["redirect_uri"], "scope": flow["scope"]}), flush=True)
        deadline = time.monotonic() + min(timeout, 600)
        while not finished["authorized"] and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not finished["authorized"]:
        raise AccountError("Login timed out; no cart changes were sent. Run connect again when ready")
    return account.status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("connect")
    auth.add_argument("--redirect-uri")
    commands.add_parser("status")
    preview = commands.add_parser("prepare")
    preview.add_argument("--result", type=Path, required=True, help="completed live local workflow JSON")
    preview.add_argument("--purchase-id", help="defaults to SHA-256 of the unchanged result file; reuse on retries")
    preview.add_argument("--modality", choices=["PICKUP", "DELIVERY"], default="PICKUP")
    submit = commands.add_parser("commit")
    submit.add_argument("--plan-id", required=True)
    submit.add_argument("--confirm", required=True, help="repeat the exact reviewed plan ID to authorize real addition")
    args = parser.parse_args()
    try:
        account = KrogerAccount()
        if args.command == "connect":
            result = connect(account, args.redirect_uri)
        elif args.command == "status":
            result = account.status()
        elif args.command == "prepare":
            data = args.result.read_bytes()
            result = RealCartBridge(account).prepare(json.loads(data), args.purchase_id or hashlib.sha256(data).hexdigest(), args.modality)
        else:
            result = RealCartBridge(account).commit(args.plan_id, args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    except (AccountError, KrogerAPIError, KrogerConfigurationError, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
