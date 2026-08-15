import React, { useEffect, useRef, useState } from "react";

import { failText, openStream, unaryBinary, unaryText } from "./client.mjs";

function readOptions() {
  const params = new URLSearchParams(window.location.search);
  return {
    endpoint: params.get("endpoint") ?? "http://127.0.0.1:18081",
    rpc: params.get("rpc") ?? "stream-text",
    count: Number(params.get("count") ?? "3"),
    delayMs: Number(params.get("delayMs") ?? "200"),
    code: Number(params.get("code") ?? "3"),
    message: params.get("message") ?? "browser",
  };
}

export function App() {
  const optionsRef = useRef(readOptions());
  const startedRef = useRef(performance.now());
  const [state, setState] = useState({ status: "running", events: [], error: null });

  useEffect(() => {
    const options = optionsRef.current;
    let cancelled = false;
    let stream = null;

    const publish = (next) => {
      if (cancelled) return;
      window.__grpcWebHarness = next;
      setState(next);
    };

    const runUnary = (promise) => {
      promise
        .then((msg) => {
          publish({
            status: "done",
            events: [
              {
                sequence: msg.sequence,
                message: msg.message,
                t: performance.now() - startedRef.current,
              },
            ],
            error: null,
          });
        })
        .catch((err) => {
          publish({
            status: "error",
            events: [],
            error: { code: err.code ?? null, message: err.message ?? String(err) },
          });
        });
    };

    window.__grpcWebHarness = { status: "running", events: [], error: null };

    if (options.rpc === "unary-binary") {
      runUnary(unaryBinary(options.endpoint, options.message));
      return () => {
        cancelled = true;
      };
    }

    if (options.rpc === "unary-text") {
      runUnary(unaryText(options.endpoint, options.message));
      return () => {
        cancelled = true;
      };
    }

    if (options.rpc === "fail-text") {
      runUnary(failText(options.endpoint, options.code, options.message));
      return () => {
        cancelled = true;
      };
    }

    stream = openStream(options.endpoint, options);

    const onData = (msg) => {
      setState((prev) => {
        const next = {
          ...prev,
          events: [
            ...prev.events,
            {
              sequence: msg.sequence,
              message: msg.message,
              t: performance.now() - startedRef.current,
            },
          ],
        };
        window.__grpcWebHarness = next;
        return next;
      });
    };

    const onError = (err) => {
      publish({
        status: "error",
        events: window.__grpcWebHarness?.events ?? [],
        error: { code: err.code ?? null, message: err.message ?? String(err) },
      });
    };

    const onEnd = () => {
      setState((prev) => {
        const next = { ...prev, status: "done" };
        window.__grpcWebHarness = next;
        return next;
      });
    };

    stream.on("data", onData);
    stream.on("error", onError);
    stream.on("end", onEnd);

    return () => {
      cancelled = true;
      // React StrictMode mounts effects twice in development. Cancel the first
      // stream so the harness still observes exactly one production-like call.
      stream.cancel();
    };
  }, []);

  return (
    <main>
      <h1>gRPC-Web browser harness</h1>
      <div data-testid="status">{state.status}</div>
      <div data-testid="event-count">{state.events.length}</div>
      {state.error ? <pre data-testid="error">{JSON.stringify(state.error)}</pre> : null}
    </main>
  );
}
