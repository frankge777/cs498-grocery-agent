"""Local, single-user Kroger authorization and durable submission ledger.

Credentials stay in a private local SQLite file, never in model/checkpoint JSON.
This is deliberately not mounted as a public multi-user HTTP service.
"""

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from grocery_bench.kroger import KrogerClient, KrogerConfigurationError

BASE = "https://api.kroger.com/v1"
DEFAULT_REDIRECT = "http://127.0.0.1:8765/oauth/callback"


class AccountError(RuntimeError):
    pass


class AccountHTTPError(AccountError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Kroger account endpoint returned HTTP {status}")


class AccountTransport:
    def request(self, method, url, headers, data, timeout=30):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        request = urllib.request.Request(url, headers=headers, data=data, method=method)
        try:
            # Do not forward application/user credentials to a redirected host.
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            # Do not expose OAuth codes/tokens or provider response bodies.
            raise AccountHTTPError(error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AccountError("Kroger account request failed; outcome may be unknown") from None


class AccountStore:
    def __init__(self, path=None):
        default = Path(__file__).resolve().parents[2] / ".kroger-account" / "account.sqlite3"
        self.path = Path(path or os.environ.get("KROGER_ACCOUNT_DB") or default).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise AccountError("Account database must not be a symlink")
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS oauth (state_hash TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions (
                  operation_id TEXT PRIMARY KEY, plan_id TEXT UNIQUE NOT NULL,
                  grant_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=35)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def account(self, db=None):
        if db is None:
            with self.transaction() as db:
                return self.account(db)
        row = db.execute("SELECT data FROM account WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def save_account(self, account, db):
        db.execute("INSERT OR REPLACE INTO account VALUES (1, ?)", (json.dumps(account),))


class KrogerAccount:
    def __init__(self, store=None, client=None, transport=None, clock=time.time):
        self.store = store or AccountStore()
        # Reuse only application credentials, never the product-only token.
        self.client = client or KrogerClient()
        self.transport = transport or AccountTransport()
        self.clock = clock

    @staticmethod
    def validate_redirect(uri):
        parsed = urllib.parse.urlsplit(uri)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.port or parsed.path != "/oauth/callback"):
            raise ValueError("Local callback must be http://127.0.0.1:PORT/oauth/callback (or localhost)")
        return uri

    def start(self, redirect_uri=None):
        uri = self.validate_redirect(redirect_uri or os.environ.get("KROGER_REDIRECT_URI") or DEFAULT_REDIRECT)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self.store.transaction() as db:
            db.execute("INSERT INTO oauth VALUES (?, ?)",
                       (hashlib.sha256(state.encode()).hexdigest(), json.dumps({"verifier": verifier,
                        "redirect_uri": uri, "expires_at": self.clock() + 600})))
        params = {"client_id": self.client.client_id, "response_type": "code", "redirect_uri": uri,
                  "scope": "cart.basic:write", "state": state, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        return {"authorization_url": BASE + "/connect/oauth2/authorize?" + urllib.parse.urlencode(params),
                "redirect_uri": uri, "scope": "cart.basic:write"}

    def _token(self, fields):
        credentials = base64.b64encode(f"{self.client.client_id}:{self.client.client_secret}".encode()).decode()
        result = self.transport.request("POST", BASE + "/connect/oauth2/token",
            {"Authorization": "Basic " + credentials, "Content-Type": "application/x-www-form-urlencoded",
             "Accept": "application/json"}, urllib.parse.urlencode(fields).encode(), 30)
        if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"]:
            raise AccountError("Kroger did not return a user access token")
        if not isinstance(result.get("token_type", "Bearer"), str) or result.get("token_type", "Bearer").casefold() != "bearer":
            raise AccountError("Unsupported account token type")
        if "scope" in result and (not isinstance(result["scope"], str) or "cart.basic:write" not in result["scope"].split()):
            raise AccountError("Kroger did not grant cart.basic:write")
        try:
            lifetime = int(result.get("expires_in", 1800))
        except (ValueError, TypeError):
            raise AccountError("Invalid token expiry") from None
        if lifetime <= 0:
            raise AccountError("Invalid token expiry")
        return {"access_token": result["access_token"], "refresh_token": result.get("refresh_token"),
                "expires_at": self.clock() + lifetime, "scope": "cart.basic:write"}

    def complete(self, redirect_url):
        parsed = urllib.parse.urlsplit(redirect_url)
        query = urllib.parse.parse_qs(parsed.query)
        if len(query.get("state", [])) != 1:
            raise AccountError("Missing or duplicate OAuth state")
        digest = hashlib.sha256(query["state"][0].encode()).hexdigest()
        with self.store.transaction() as db:
            row = db.execute("SELECT data FROM oauth WHERE state_hash=?", (digest,)).fetchone()
            if not row:
                raise AccountError("OAuth state is unknown or already consumed")
            pending = json.loads(row[0])
            expected = urllib.parse.urlsplit(pending["redirect_uri"])
            if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
                raise AccountError("OAuth redirect URI mismatch")
            if self.clock() >= pending["expires_at"]:
                raise AccountError("OAuth request expired; start again")
            db.execute("DELETE FROM oauth WHERE state_hash=?", (digest,))
        if query.get("error"):
            raise AccountError("Kroger authorization was declined or app scope/redirect is not registered")
        if len(query.get("code", [])) != 1:
            raise AccountError("Missing or duplicate authorization code")
        token = self._token({"grant_type": "authorization_code", "code": query["code"][0],
                             "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"]})
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM submissions WHERE status='submitting'").fetchone():
                raise AccountError("A submission is in flight; resolve it before replacing the account")
            self.store.save_account({**token, "grant_id": secrets.token_urlsafe(24),
                                      "client_id": self.client.client_id}, db)
        return self.status()

    def status(self):
        value = self.store.account()
        return {"authorized": bool(value and value.get("client_id") == self.client.client_id),
                "access_token_unexpired": bool(value and value.get("expires_at", 0) > self.clock()),
                "can_refresh": bool(value and value.get("refresh_token")),
                "scope": value.get("scope") if value else None,
                "real_cart_read_supported": False, "checkout_supported": False}

    def access(self, expected_grant=None):
        with self.store.transaction() as db:
            value = self.store.account(db)
            if not value or value.get("client_id") != self.client.client_id:
                raise AccountError("Kroger user authorization required; run connect")
            if expected_grant and value["grant_id"] != expected_grant:
                raise AccountError("Account authorization changed; prepare a new plan")
            if value["expires_at"] <= self.clock() + 30:
                if not value.get("refresh_token"):
                    raise AccountError("User token expired; sign in again")
                refreshed = self._token({"grant_type": "refresh_token", "refresh_token": value["refresh_token"]})
                refreshed["refresh_token"] = refreshed["refresh_token"] or value["refresh_token"]
                value.update(refreshed)
                self.store.save_account(value, db)
            return value

    def add(self, items, access_token):
        return self.transport.request("PUT", BASE + "/cart/add",
            {"Authorization": "Bearer " + access_token, "Content-Type": "application/json", "Accept": "application/json"},
            json.dumps({"items": items}).encode(), 30)
