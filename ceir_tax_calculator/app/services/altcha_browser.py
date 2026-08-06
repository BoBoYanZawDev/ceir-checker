"""Embedded-webview worker, run as its own process.

pywebview owns the platform GUI run loop (Cocoa/WebView2/GTK) and cannot
share the main thread with the app's Tkinter loop, so this runs standalone.
It loads the real CEIR page so Cloudflare's browser challenge clears the
same way it does for a human visitor, then proxies HTTP requests through
that page's JavaScript so they carry the resulting session cookies.
"""

from __future__ import annotations

import json
import sys

from app.utils.constants import CEIR_CHALLENGE_URL

_REQUEST_SCRIPT = """
(function() {
    try {
        var xhr = new XMLHttpRequest();
        xhr.open(%(method)s, %(url)s, false);
        var headers = %(headers)s;
        for (var key in headers) {
            try { xhr.setRequestHeader(key, headers[key]); } catch (error) {}
        }
        xhr.send(%(body)s);
        return JSON.stringify({status: xhr.status, text: xhr.responseText});
    } catch (error) {
        return JSON.stringify({error: String(error)});
    }
})()
"""


def _run_request(window, method: str, url: str, headers: dict, body: str | None) -> dict:
    # A synchronous XHR (not fetch()) so evaluate_js gets a plain return value
    # instead of a Promise, which this pywebview backend never awaits.
    script = _REQUEST_SCRIPT % {
        "method": json.dumps(method),
        "url": json.dumps(url),
        "headers": json.dumps(headers),
        "body": json.dumps(body),
    }
    result = window.evaluate_js(script)
    if not isinstance(result, str):
        return {"error": "No response from webview."}
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"error": "Unreadable webview response."}


def _handle(window, command: dict) -> dict:
    action = command.get("action")
    if action == "peek":
        text = window.evaluate_js("document.body ? document.body.innerText : ''")
        return {"text": text or ""}
    if action == "request":
        return _run_request(window, command["method"], command["url"], command.get("headers") or {}, command.get("body"))
    return {"error": f"Unknown action: {action}"}


def _serve(window) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            continue
        if command.get("action") == "stop":
            break
        try:
            response = _handle(window, command)
        except Exception as exc:  # noqa: BLE001 - reported to the parent, not raised here
            response = {"error": str(exc)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    window.destroy()


def main() -> None:
    import webview

    window = webview.create_window(
        "CEIR session", CEIR_CHALLENGE_URL, hidden=True, width=480, height=360,
    )
    webview.start(_serve, window)


if __name__ == "__main__":
    main()
