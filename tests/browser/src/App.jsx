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
    empty: params.get("empty") === "1",
    failAfter: Number(params.get("failAfter") ?? "0"),
    failCode: Number(params.get("failCode") ?? "13"),
    failMessage: params.get("failMessage") ?? "forced stream failure",
    cancelAfter: Number(params.get("cancelAfter") ?? "0"),
    grpcTimeout: params.get("grpcTimeout") ?? "",
  };
}

export function App() {
  const optionsRef = useRef(readOptions());
  const startedRef = useRef(performance.now());
  const [state, setState] = useState({ status: "running", events: [], error: null });

  useEffect(() => {
    const options = optionsRef.current;
    let disposed = false;
    let terminal = false;
    let stream = null;

    const publish = (next) => {
      if (disposed) return;
      window.__grpcWebHarness = next;
      setState(next);
    };

    const currentEvents = () => window.__grpcWebHarness?.events ?? [];

    const fail = (code, message) => {
      if (terminal) return;
      terminal = true;
      publish({
        status: "error",
        events: currentEvents(),
        error: { code: code ?? null, message: message ?? "" },
      });
    };

    const runUnary = (promise) => {
      promise
        .then((msg) => {
          if (terminal) return;
          terminal = true;
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
          fail(err.code, err.message ?? String(err));
        });
    };

    window.__grpcWebHarness = { status: "running", events: [], error: null };

    if (options.rpc === "unary-binary") {
      runUnary(unaryBinary(options.endpoint, options.message));
      return () => {
        disposed = true;
      };
    }

    if (options.rpc === "unary-text") {
      runUnary(unaryText(options.endpoint, options.message));
      return () => {
        disposed = true;
      };
    }

    if (options.rpc === "fail-text") {
      runUnary(failText(options.endpoint, options.code, options.message));
      return () => {
        disposed = true;
      };
    }

    stream = openStream(options.endpoint, options);

    const onData = (msg) => {
      if (terminal) return;

      setState((prev) => {
        const events = [
          ...prev.events,
          {
            sequence: msg.sequence,
            message: msg.message,
            t: performance.now() - startedRef.current,
          },
        ];

        if (options.cancelAfter && events.length >= options.cancelAfter) {
          terminal = true;
          stream.cancel();
          const next = { status: "cancelled", events, error: null };
          window.__grpcWebHarness = next;
          return next;
        }

        const next = { ...prev, events };
        window.__grpcWebHarness = next;
        return next;
      });
    };

    const onError = (err) => {
      fail(err.code, err.message ?? String(err));
    };

    const onStatus = (status) => {
      if (terminal || !status || status.code === 0) return;
      fail(status.code, status.details ?? status.message ?? "");
    };

    const onEnd = () => {
      if (terminal) return;
      terminal = true;
      setState((prev) => {
        const next = { ...prev, status: "done" };
        window.__grpcWebHarness = next;
        return next;
      });
    };

    stream.on("data", onData);
    stream.on("error", onError);
    stream.on("status", onStatus);
    stream.on("end", onEnd);

    return () => {
      disposed = true;
      if (!terminal) {
        terminal = true;
        // React StrictMode mounts effects twice in development. Cancel the first
        // stream so the harness still observes exactly one production-like call.
        stream.cancel();
      }
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
