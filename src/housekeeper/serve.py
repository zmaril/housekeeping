"""`housekeeper serve`: a local web view of the fleet dashboard with a Regenerate
button that re-audits the fleet on demand (and an optional auto-refresh). The static
`--html` file output is untouched — the live controls are injected only into the
served page."""

from __future__ import annotations

import html
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

# Injected right after <body>. Uses __STATUS__ as the one placeholder so the JS/CSS
# braces don't need escaping. Falls back to literal colors if the page has no vars.
_CONTROLS = """\
<div id="hk-bar">
  <button id="hk-regen" type="button">&#8635; Regenerate</button>
  <label id="hk-auto"><input type="checkbox" id="hk-auto-cb"> auto (60s)</label>
  <span id="hk-status">__STATUS__</span>
</div>
<style>
#hk-bar { position: fixed; top: .6rem; right: .6rem; z-index: 99; display: flex; align-items: center;
  gap: .55rem; background: var(--head, #f6f8fa); border: 1px solid var(--line, #d0d7de); border-radius: 8px;
  padding: .4rem .6rem; font: 13px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  box-shadow: 0 1px 4px rgba(0,0,0,.12); }
#hk-regen { font: inherit; font-weight: 600; cursor: pointer; padding: .35rem .7rem; border-radius: 6px;
  border: 1px solid var(--line, #d0d7de); background: var(--bg, #fff); color: var(--fg, #1f2328); }
#hk-regen:disabled { opacity: .55; cursor: progress; }
#hk-auto { color: var(--skip, #8c959f); display: flex; align-items: center; gap: .25rem; cursor: pointer; }
#hk-status { color: var(--skip, #8c959f); white-space: nowrap; }
</style>
<script>
(function () {
  var btn = document.getElementById('hk-regen');
  var status = document.getElementById('hk-status');
  var auto = document.getElementById('hk-auto-cb');
  var timer = null;
  function regen() {
    btn.disabled = true;
    status.textContent = 'auditing the fleet…';
    fetch('/regen', { method: 'POST' }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t || r.status); });
      location.reload();
    }).catch(function (e) {
      status.textContent = 'regen failed: ' + e.message;
      btn.disabled = false;
    });
  }
  function sync() {
    sessionStorage.setItem('hk-auto', auto.checked ? '1' : '');
    if (auto.checked && !timer) timer = setInterval(regen, 60000);
    if (!auto.checked && timer) { clearInterval(timer); timer = null; }
  }
  btn.addEventListener('click', regen);
  auto.addEventListener('change', sync);
  if (sessionStorage.getItem('hk-auto') === '1') auto.checked = true;
  sync();
})();
</script>
"""


def _inject(doc: str, status: str) -> str:
    """Splice the live controls in right after the opening <body> tag."""
    controls = _CONTROLS.replace("__STATUS__", html.escape(status))
    return doc.replace("<body>\n", "<body>\n" + controls, 1)


def serve(
    generate: Callable[[], str],
    *,
    host: str = "127.0.0.1",
    port: int = 8799,
    open_browser: bool = True,
) -> int:
    """Serve the dashboard produced by `generate()` (a full HTML document), re-running
    it on POST /regen. Blocks until Ctrl-C."""
    lock = threading.Lock()

    def build() -> str:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return _inject(generate(), f"generated {stamp}")

    state = {"html": build()}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body, ctype="text/html; charset=utf-8") -> None:
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                with lock:
                    self._send(200, state["html"])
            elif self.path == "/favicon.ico":
                self._send(204, b"")
            else:
                self._send(404, "not found\n", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if self.path != "/regen":
                self._send(404, "not found\n", "text/plain; charset=utf-8")
                return
            try:
                fresh = build()
            except Exception as e:  # surface the failure to the button, keep serving
                self._send(500, f"audit failed: {e}\n", "text/plain; charset=utf-8")
                return
            with lock:
                state["html"] = fresh
            self._send(200, "ok\n", "text/plain; charset=utf-8")

        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"housekeeper serve → {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        httpd.server_close()
    return 0
