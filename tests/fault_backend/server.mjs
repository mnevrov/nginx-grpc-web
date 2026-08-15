import http2 from "node:http2";

const {
  HTTP2_HEADER_STATUS,
  HTTP2_HEADER_CONTENT_TYPE,
  NGHTTP2_INTERNAL_ERROR,
} = http2.constants;

const port = Number(process.env.PORT ?? "50052");
const rawSockets = new Set();

function varint(value) {
  const out = [];
  let n = value >>> 0;

  while (true) {
    const byte = n & 0x7f;
    n >>>= 7;
    if (n) out.push(byte | 0x80);
    else {
      out.push(byte);
      return Buffer.from(out);
    }
  }
}

function echoReply(message = "before-transport-fault", sequence = 1) {
  const text = Buffer.from(message, "utf8");
  const payload = Buffer.concat([
    Buffer.from([0x0a]),
    varint(text.length),
    text,
    Buffer.from([0x10]),
    varint(sequence),
  ]);
  const header = Buffer.alloc(5);
  header[0] = 0x00;
  header.writeUInt32BE(payload.length, 1);
  return Buffer.concat([header, payload]);
}

function oversizedFrameHeader(length = 4096) {
  const header = Buffer.alloc(5);
  header[0] = 0x00;
  header.writeUInt32BE(length >>> 0, 1);
  return header;
}

function resetRawSockets() {
  for (const socket of rawSockets) {
    try {
      if (typeof socket.resetAndDestroy === "function") socket.resetAndDestroy();
      else socket.destroy(new Error("injected tcp reset"));
    } catch {
      socket.destroy();
    }
  }
}

const server = http2.createServer();

server.on("connection", (socket) => {
  rawSockets.add(socket);
  socket.on("close", () => rawSockets.delete(socket));
  socket.on("error", () => {});
});

server.on("stream", (stream, headers) => {
  stream.on("error", () => {});

  const mode = String(headers["x-fault-mode"] ?? "rst-after-data");
  let bodyBytes = 0;

  stream.on("data", (chunk) => {
    bodyBytes += chunk.length;
  });

  stream.on("end", () => {
    if (mode === "rst-before-headers") {
      stream.close(NGHTTP2_INTERNAL_ERROR);
      return;
    }

    stream.respond({
      [HTTP2_HEADER_STATUS]: 200,
      [HTTP2_HEADER_CONTENT_TYPE]: "application/grpc",
      "x-fault-body-bytes": String(bodyBytes),
    });

    if (mode === "oversized-frame") {
      stream.end(oversizedFrameHeader());
      return;
    }

    if (mode === "truncated-frame") {
      const header = oversizedFrameHeader(16);
      stream.end(Buffer.concat([header, Buffer.from("xx")]));
      return;
    }

    const frame = echoReply();
    stream.write(frame, () => {
      if (mode === "rst-after-data") {
        stream.close(NGHTTP2_INTERNAL_ERROR);
        return;
      }

      if (mode === "tcp-reset-after-data") {
        setTimeout(resetRawSockets, 25);
        return;
      }

      if (mode === "clean-without-trailers") {
        // Keep DATA and END_STREAM distinct so the proxy has a real chance to
        // forward the completed DATA frame before observing malformed gRPC EOF.
        setTimeout(() => stream.end(), 25);
        return;
      }

      stream.close(NGHTTP2_INTERNAL_ERROR);
    });
  });
});

server.on("sessionError", () => {});
server.on("error", (error) => {
  console.error(error);
  process.exitCode = 1;
});

server.listen(port, "0.0.0.0", () => {
  console.log(`fault backend listening on :${port}`);
});
