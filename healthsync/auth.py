from __future__ import annotations

import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
_SCOPES = "read:recovery read:cycles read:sleep offline"


def run_auth_flow(client_id: str, client_secret: str, port: int = 8765) -> dict:
    """Open a browser for WHOOP OAuth authorization and return the token response dict."""
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)

    auth_url = _AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
        },
        quote_via=urllib.parse.quote,
    )

    result: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                query = urllib.parse.parse_qs(parsed.query)

                if "error" in query:
                    error = query["error"][0]
                    desc = query.get("error_description", [error])[0]
                    result["error"] = desc
                    self._respond(f"<h2>Authorization failed</h2><p>{desc}</p>")
                    return

                returned_state = query.get("state", [None])[0]
                if returned_state != state:
                    result["error"] = "State mismatch — possible CSRF; try again."
                    self._respond("<h2>Authorization failed</h2><p>State mismatch.</p>")
                    return

                code = query.get("code", [None])[0]
                if code:
                    result["code"] = code
                    self._respond(
                        "<h2>Authorization successful!</h2>"
                        "<p>You can close this window and return to the terminal.</p>"
                    )
                    return

                result["error"] = "No authorization code in callback"
                self._respond("<h2>Authorization failed</h2><p>No code received.</p>")
            else:
                self.send_response(204)
                self.end_headers()

        def _respond(self, body: str):
            html = f"<html><body>{body}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", port), _Handler)

    print(f"\nOpening browser for WHOOP authorization...")
    print(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for authorization callback (Ctrl+C to cancel)...")
    while not result:
        server.handle_request()
    server.server_close()

    if "error" in result:
        raise RuntimeError(f"Authorization error: {result['error']}")

    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")

    return resp.json()
