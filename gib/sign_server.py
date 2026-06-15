"""Phantom signing bridge — serves a local webpage that signs batched
transactions via Phantom in the user's browser.

The flow uses Phantom's `signAllTransactions` so the user sees ONE popup per
chunk of N transactions instead of one popup per tx. Each chunk is built
server-side with a fresh blockhash and pre-simulated to skip txs that would
revert on-chain.

Endpoints:
  GET  /                  — HTML signing page
  GET  /api/meta          — { total, chunk_size }
  GET  /api/chunk?start=N — builds chunk [N, N+chunk_size) with fresh
                            blockhash, pre-simulates each tx, returns the
                            valid ones (skipped txs are reported separately)
  POST /api/signed_chunk  — receives [signedB64...], broadcasts all in
                            parallel, returns per-tx success/error

Fork note (2026-06-15): server binds to 127.0.0.1 by default (was 0.0.0.0).
See CHANGES.md.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import rpc


SIGNING_PAGE = """<!DOCTYPE html>
<html>
<head>
<title>gib-bot</title>
<script src="https://unpkg.com/@solana/web3.js@1.95.4/lib/index.iife.min.js"></script>
<style>
  body { font-family: monospace; background: #1a1a2e; color: #eee; padding: 20px; max-width: 720px; margin: 0 auto; }
  h2 { color: #e94560; margin: 0 0 15px 0; }
  #status { padding: 12px; margin: 10px 0; border-radius: 4px; font-size: 15px; }
  .ok { background: #0a2e0a; border: 1px solid #1a5; }
  .err { background: #3d0000; border: 1px solid #e94560; }
  .pending { background: #16213e; border: 1px solid #0f3460; }
  #progress { height: 18px; background: #0f0f1a; border-radius: 4px; overflow: hidden; margin: 10px 0; }
  #bar { height: 100%; background: linear-gradient(90deg, #1a5, #1f8); width: 0; transition: width 0.3s; }
  #log { background: #0f0f1a; padding: 10px; border-radius: 4px; max-height: 380px; overflow-y: auto; font-size: 13px; white-space: pre-wrap; margin-top: 10px; }
</style>
</head>
<body>
<h2>gib-bot</h2>
<div id="status" class="pending">connecting to Phantom...</div>
<div id="progress"><div id="bar"></div></div>
<div id="log"></div>

<script>
function log(msg) {
  const el = document.getElementById('log');
  el.textContent += msg + '\\n';
  el.scrollTop = el.scrollHeight;
}
function setStatus(msg, cls) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = cls;
}
function setBar(done, total) {
  document.getElementById('bar').style.width = (100 * done / total) + '%';
}

(async function main() {
  if (!window.solana?.isPhantom) {
    setStatus('Phantom not found in this browser.', 'err');
    return;
  }
  if (!window.solanaWeb3) {
    setStatus('Failed to load @solana/web3.js — check internet/CDN.', 'err');
    return;
  }
  const { VersionedTransaction } = window.solanaWeb3;

  try {
    const resp = await window.solana.connect();
    log('wallet: ' + resp.publicKey.toString());
  } catch(e) {
    setStatus('Phantom connect rejected: ' + e.message, 'err');
    return;
  }

  let meta;
  try {
    meta = await (await fetch('/api/meta')).json();
    log('session ' + meta.session_id + ': ' + meta.total + ' tx(s), ' + meta.chunk_size + ' per popup -> ' +
        Math.ceil(meta.total / meta.chunk_size) + ' popup(s) needed');
  } catch(e) {
    setStatus('Failed to load meta', 'err');
    return;
  }
  if (!meta.total) { setStatus('No transactions to sign.', 'pending'); return; }
  const initialSessionId = meta.session_id;

  let totalSent = 0, totalFailed = 0, totalSkipped = 0, totalDone = 0;

  async function fetchWithStallGuard(url, label, timeoutMs = 30000, maxAttempts = 4) {
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(t);
        return await r.json();
      } catch(e) {
        clearTimeout(t);
        if (e.name === 'AbortError') {
          log(label + ' slow (attempt ' + attempt + '/' + maxAttempts + ', server still building) — retrying');
          setStatus(label + ' — server slow on attempt ' + attempt + '/' + maxAttempts + ', retrying...', 'pending');
        } else {
          throw e;
        }
      }
    }
    throw new Error(label + ' timed out after ' + maxAttempts + ' attempts');
  }

  for (let start = 0; start < meta.total; start += meta.chunk_size) {
    const chunkNum = Math.floor(start / meta.chunk_size) + 1;
    const totalChunks = Math.ceil(meta.total / meta.chunk_size);

    setStatus('Building chunk ' + chunkNum + '/' + totalChunks + ' (fresh blockhash, pre-simulating)...', 'pending');
    let chunk;
    try {
      chunk = await fetchWithStallGuard('/api/chunk?start=' + start, 'chunk ' + chunkNum);
    } catch(e) {
      log('chunk ' + chunkNum + ' build failed: ' + e.message);
      totalFailed += Math.min(meta.chunk_size, meta.total - start);
      continue;
    }

    if (chunk.skipped && chunk.skipped.length) {
      for (const s of chunk.skipped) {
        log('  SKIPPED ' + s.label + ': ' + s.reason);
      }
      totalSkipped += chunk.skipped.length;
      totalDone += chunk.skipped.length;
      setBar(totalDone, meta.total);
    }

    if (!chunk.txs || !chunk.txs.length) {
      log('chunk ' + chunkNum + ' has no valid txs to sign — moving on');
      continue;
    }

    const txs = chunk.txs.map(t =>
      VersionedTransaction.deserialize(Uint8Array.from(atob(t.base64), c => c.charCodeAt(0)))
    );

    setStatus('Approve ' + txs.length + ' tx(s) in Phantom (chunk ' + chunkNum + '/' + totalChunks + ')...', 'pending');

    let signed;
    try {
      signed = await window.solana.signAllTransactions(txs);
    } catch(e) {
      if (e.message && e.message.includes('User rejected')) {
        log('chunk ' + chunkNum + ': user rejected — stopping');
        setStatus('Stopped by user. ' + totalSent + ' sent so far.', 'err');
        return;
      }
      log('chunk ' + chunkNum + ' sign failed: ' + e.message);
      totalFailed += txs.length;
      totalDone += txs.length;
      setBar(totalDone, meta.total);
      continue;
    }

    setStatus('Broadcasting ' + signed.length + ' signed tx(s) from chunk ' + chunkNum + '...', 'pending');
    const signedB64 = signed.map(stx => btoa(String.fromCharCode(...stx.serialize())));
    const labels = chunk.txs.map(t => t.label);

    let result;
    try {
      result = await (await fetch('/api/signed_chunk', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ signed: signedB64, labels })
      })).json();
    } catch(e) {
      log('chunk ' + chunkNum + ' broadcast call failed: ' + e.message);
      totalFailed += signedB64.length;
      totalDone += signedB64.length;
      setBar(totalDone, meta.total);
      continue;
    }

    for (const r of result.results || []) {
      if (r.signature) log('  ' + r.label + ': ' + r.signature.slice(0, 24) + '...');
      else log('  FAILED ' + r.label + ': ' + (r.error || 'unknown'));
    }
    totalSent += result.sent || 0;
    totalFailed += result.failed || 0;
    totalDone += signedB64.length;
    setBar(totalDone, meta.total);
  }

  if (totalSent > 0 && totalFailed === 0 && totalSkipped === 0) {
    setStatus(totalSent + ' tx(s) submitted successfully', 'ok');
  } else {
    setStatus(totalSent + ' sent, ' + totalFailed + ' failed, ' + totalSkipped + ' skipped', totalSent > 0 ? 'ok' : 'err');
  }
  log('pass done — watching for next cascade pass...');

  let failStreak = 0;
  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    let next;
    try {
      next = await (await fetch('/api/meta')).json();
      failStreak = 0;
    } catch(e) {
      failStreak++;
      if (failStreak >= 10) {
        log('cascade complete (server closed)');
        return;
      }
      continue;
    }
    if (next.session_id && next.session_id !== initialSessionId) {
      log('new pass detected (session ' + next.session_id + ') — reloading');
      location.reload();
      return;
    }
  }
})();
</script>
</body>
</html>"""


class BridgeState:
    def __init__(self) -> None:
        self.total: int = 0
        self.chunk_size: int = 25
        self.session_id: int = 0
        self.build_chunk: Callable[[int, int], dict] | None = None
        self.results: list[dict] = []
        self.done = threading.Event()
        self.lock = threading.Lock()


class BridgeHandler(BaseHTTPRequestHandler):
    state: BridgeState

    def log_message(self, format, *args):
        pass

    def _json(self, obj, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SIGNING_PAGE.encode())
            return

        if self.path == "/api/meta":
            self._json({
                "total": self.state.total,
                "chunk_size": self.state.chunk_size,
                "session_id": self.state.session_id,
            })
            return

        if self.path.startswith("/api/chunk"):
            qs = parse_qs(urlparse(self.path).query)
            start = int(qs.get("start", [0])[0])
            try:
                chunk = self.state.build_chunk(start, self.state.chunk_size)
            except Exception as e:
                self._json({"error": str(e)}, status=500)
                return
            skipped = chunk.get("skipped") or []
            if skipped:
                with self.state.lock:
                    for s in skipped:
                        self.state.results.append({
                            "error": s.get("reason", "skipped"),
                            "label": s.get("label", "unknown"),
                        })
                    if len(self.state.results) >= self.state.total:
                        self.state.done.set()
            self._json(chunk)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/api/signed_chunk":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        signed_list: list[str] = body.get("signed", [])
        labels: list[str] = body.get("labels", [])

        per_tx_results: list[dict] = [{} for _ in signed_list]

        def broadcast(i: int, b64: str, label: str) -> dict:
            try:
                sig = rpc.send_transaction(b64)
                print(f"  {label}: {sig}")
                return {"signature": sig, "label": label}
            except Exception as e:
                print(f"  FAILED {label}: {e}")
                return {"error": str(e), "label": label}

        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [
                ex.submit(broadcast, i, signed_list[i], labels[i] if i < len(labels) else f"tx{i}")
                for i in range(len(signed_list))
            ]
            for i, fut in enumerate(futs):
                per_tx_results[i] = fut.result()

        sent = sum(1 for r in per_tx_results if "signature" in r)
        failed = sum(1 for r in per_tx_results if "error" in r)

        with self.state.lock:
            self.state.results.extend(per_tx_results)
            if len(self.state.results) >= self.state.total:
                self.state.done.set()

        self._json({"sent": sent, "failed": failed, "results": per_tx_results})


_SESSION_COUNTER = 0
_SESSION_LOCK = threading.Lock()


def _next_session_id() -> int:
    global _SESSION_COUNTER
    with _SESSION_LOCK:
        _SESSION_COUNTER += 1
        return _SESSION_COUNTER


def run_bridge(
    *,
    port: int,
    total: int,
    chunk_size: int,
    build_chunk: Callable[[int, int], dict],
    timeout: int = 1800,
    open_browser: bool = True,
    bind_host: str = "127.0.0.1",
) -> list[dict]:
    """Start the signing bridge and wait for all chunks to be processed.

    build_chunk(start, count) -> {
        "txs": [{"base64": str, "label": str, "index": int}, ...],
        "skipped": [{"label": str, "reason": str}, ...],
    }

    `bind_host` defaults to "127.0.0.1" (localhost-only). Pass "0.0.0.0"
    explicitly only if you intend the bridge to be reachable from other
    machines on the LAN — note that the bridge has no authentication and
    will broadcast any signed bytes posted to /api/signed_chunk.

    If open_browser=False, assumes a previous bridge session left a tab open;
    the page will auto-detect the new session_id and reload itself.
    """
    state = BridgeState()
    state.total = total
    state.chunk_size = chunk_size
    state.session_id = _next_session_id()
    state.build_chunk = build_chunk

    handler_class = type("Handler", (BridgeHandler,), {"state": state})
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((bind_host, port), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://{'localhost' if bind_host == '127.0.0.1' else bind_host}:{port}"
    n_chunks = (total + chunk_size - 1) // chunk_size
    print(f"\nPhantom bridge session {state.session_id}")
    print(f"  URL: {url}")
    print(f"  bind: {bind_host}:{port}")
    print(f"  {total} tx(s) in chunks of {chunk_size} -> {n_chunks} popup(s) expected\n")

    if open_browser:
        import webbrowser
        try:
            webbrowser.open(url)
            print("  (browser opened automatically)")
        except Exception:
            print(f"  Could not auto-open browser — open manually: {url}")
    else:
        print("  (existing tab will auto-reload via session_id watcher)")

    state.done.wait(timeout=timeout)
    time.sleep(0.3)
    server.shutdown()
    return state.results
