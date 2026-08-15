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
    faultMode: params.get("faultMode") ?? "",
  };
}

function initialHarness() {
  return { status: "running", events: [], error: null, trace: [] };
}

export function App() {
  const optionsRef = useRef(readOptions());
  const startedRef = useRef(performance.now());
  const [state, setState] = useState(initialHarness());

  useEffect(() => {
    const options = optionsRef.current;
    let disposed = false;
    let terminal = false;
    let stream = null;

    const current = () => window.__grpcWebHarness ?? initialHarness();

    const publish = (next) => {
      if (disposed) return;
      window.__grpcWebHarness = next;
      setState(next);
    };

    const trace = (type, detail = null) => {
      if (disposed) return;
      const prev = current();
      publish({
        ...prev,
        trace: [
          ...(prev.trace ?? []),
          { type, detail, t: performance.now() - startedRef.current },
        ],
      });
    };

    const fail = (code, message, source) => {
      if (terminal) return;
      trace(source, { code: code ?? null, message: message ?? "" });
      terminal = true;
      const prev = current();
      publish({
        ...prev,
        status: "error",
        error: { code: code ?? null, message: message ?? "" },
      });
    };

    const runUnary = (promise) => {
      promise
        .then((msg) => {
          if (terminal) return;
          terminal = true;
          const next = {
            ...current(),
            status: "done",
            events: [
              {
                sequence: msg.sequence,
                message: msg.message,
                t: performance.now() - startedRef.current,
              },
            ],
            error: null,
          };
          publish(next);
        })
        .catch((err) => {
          fail(err.code, err.message ?? String(err), "error");
        });
    };

    window.__grpcWebHarness = initialHarness();
    setState(window.__grpcWebHarness);

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

      const prev = current();
      const event = {
        sequence: msg.sequence,
        message: msg.message,
        t: performance.now() - startedRef.current,
      };
      const events = [...prev.events, event];
      const next = {
        ...prev,
        events,
        trace: [...(prev.trace ?? []), { type: "data", detail: event, t: event.t }],
      };

      if (options.cancelAfter && events.length >= options.cancelAfter) {
        terminal = true;
        stream.cancel();
        publish({ ...next, status: "cancelled", error: null });
        return;
      }

      publish(next);
    };

    const onError = (err) => {
      fail(err.code, err.message ?? String(err), "error");
    };

    const onStatus = (status) => {
      if (terminal || !status) return;
      if (status.code !== 0) {
        fail(status.code, status.details ?? status.message ?? "", "status");
        return;
      }
      trace("status", {
        code: status.code,
        message: status.details ?? status.message ?? "",
      });
    };

    const onEnd = () => {
      if (terminal) return;
      trace("end");
      terminal = true;
      publish({ ...current(), status: "done" });
    };

    stream.on("data", onData);
    stream.on("error", onError);
    stream.on("status", onStatus);
    stream.on("end", onEnd);

    return () => {
      disposed = true;
      if (!terminal) {
        terminal = true;
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
