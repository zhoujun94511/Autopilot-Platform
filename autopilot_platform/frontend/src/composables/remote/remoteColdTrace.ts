/** 浏览器侧远控冷启动耗时（与 Runner ``[runner] remote-cold`` 对齐）。 */

let t0 = 0;
let last = 0;
let activeSid = "";
let runnerConnectedLogged = false;

function enabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem("MC_REMOTE_COLD_TRACE") === "1";
  } catch {
    return false;
  }
}

export function resetRemoteColdTrace(sessionId: string): void {
  if (!enabled()) return;
  activeSid = (sessionId || "").slice(0, 12);
  runnerConnectedLogged = false;
  t0 = performance.now();
  last = t0;
  console.info(`[remote-cold] sid=${activeSid} +0.000s (Δ0.000s) trace.reset`);
}

export function markRunnerConnectedOnce(): void {
  if (!enabled() || runnerConnectedLogged) return;
  runnerConnectedLogged = true;
  markRemoteCold("ui.runner.connected");
}

export function markRemoteCold(
  phase: string,
  extra?: Record<string, unknown>,
): void {
  if (!enabled()) return;
  const now = performance.now();
  const step = (now - last) / 1000;
  const total = (now - t0) / 1000;
  last = now;
  const sid = activeSid || "?";
  if (extra && Object.keys(extra).length) {
    console.info(
      `[remote-cold] sid=${sid} +${total.toFixed(3)}s (Δ${step.toFixed(3)}s) ${phase}`,
      extra,
    );
  } else {
    console.info(
      `[remote-cold] sid=${sid} +${total.toFixed(3)}s (Δ${step.toFixed(3)}s) ${phase}`,
    );
  }
}

export function summaryRemoteCold(
  label: string,
  extra?: Record<string, unknown>,
): void {
  if (!enabled()) return;
  const total = (performance.now() - t0) / 1000;
  const sid = activeSid || "?";
  if (extra && Object.keys(extra).length) {
    console.info(
      `[remote-cold] sid=${sid} DONE ${label} total=${total.toFixed(3)}s`,
      extra,
    );
  } else {
    console.info(
      `[remote-cold] sid=${sid} DONE ${label} total=${total.toFixed(3)}s`,
    );
  }
}
