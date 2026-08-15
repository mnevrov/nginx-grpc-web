import * as grpcWeb from "grpc-web";
import jspbPkg from "google-protobuf";

const { BinaryReader, BinaryWriter } = jspbPkg;

class UnaryRequest {
  constructor(message = "") {
    this.message = message;
  }

  serializeBinary() {
    const w = new BinaryWriter();
    if (this.message) w.writeString(1, this.message);
    return w.getResultBuffer();
  }
}

class StreamRequest {
  constructor(message = "", count = 3, delayMs = 250) {
    this.message = message;
    this.count = count;
    this.delayMs = delayMs;
  }

  serializeBinary() {
    const w = new BinaryWriter();
    if (this.message) w.writeString(1, this.message);
    if (this.count) w.writeUint32(2, this.count);
    if (this.delayMs) w.writeUint32(3, this.delayMs);
    return w.getResultBuffer();
  }
}

class EchoReply {
  constructor() {
    this.message = "";
    this.sequence = 0;
  }

  static deserializeBinary(bytes) {
    const out = new EchoReply();
    const r = new BinaryReader(bytes);

    while (r.nextField()) {
      if (r.isEndGroup()) break;
      switch (r.getFieldNumber()) {
        case 1:
          out.message = r.readString();
          break;
        case 2:
          out.sequence = r.readUint32();
          break;
        default:
          r.skipField();
      }
    }

    return out;
  }
}

const unaryMethod = new grpcWeb.MethodDescriptor(
  "/grpcwebtest.TestService/Unary",
  grpcWeb.MethodType.UNARY,
  UnaryRequest,
  EchoReply,
  (request) => request.serializeBinary(),
  EchoReply.deserializeBinary,
);

const streamMethod = new grpcWeb.MethodDescriptor(
  "/grpcwebtest.TestService/Stream",
  grpcWeb.MethodType.SERVER_STREAMING,
  StreamRequest,
  EchoReply,
  (request) => request.serializeBinary(),
  EchoReply.deserializeBinary,
);

export function unaryBinary(baseUrl, message = "browser") {
  const client = new grpcWeb.GrpcWebClientBase({ format: "binary" });
  const request = new UnaryRequest(message);

  return client.unaryCall(
    `${baseUrl}/grpcwebtest.TestService/Unary`,
    request,
    {},
    unaryMethod,
  );
}

export function openStream(baseUrl, options = {}) {
  const client = new grpcWeb.GrpcWebClientBase({ format: "text" });
  const request = new StreamRequest(
    options.message ?? "browser",
    options.count ?? 3,
    options.delayMs ?? 250,
  );

  return client.serverStreaming(
    `${baseUrl}/grpcwebtest.TestService/Stream`,
    request,
    {},
    streamMethod,
  );
}
