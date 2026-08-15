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
  constructor(options = {}) {
    this.message = options.message ?? "browser";
    this.count = options.count ?? 3;
    this.delayMs = options.delayMs ?? 250;
    this.empty = options.empty ?? false;
    this.failAfter = options.failAfter ?? 0;
    this.failCode = options.failCode ?? 0;
    this.failMessage = options.failMessage ?? "";
  }

  serializeBinary() {
    const w = new BinaryWriter();
    if (this.message) w.writeString(1, this.message);
    if (this.count) w.writeUint32(2, this.count);
    if (this.delayMs) w.writeUint32(3, this.delayMs);
    if (this.empty) w.writeBool(4, this.empty);
    if (this.failAfter) w.writeUint32(5, this.failAfter);
    if (this.failCode) w.writeInt32(6, this.failCode);
    if (this.failMessage) w.writeString(7, this.failMessage);
    return w.getResultBuffer();
  }
}

class FailRequest {
  constructor(code = 3, message = "forced failure") {
    this.code = code;
    this.message = message;
  }

  serializeBinary() {
    const w = new BinaryWriter();
    if (this.code) w.writeInt32(1, this.code);
    if (this.message) w.writeString(2, this.message);
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

const failMethod = new grpcWeb.MethodDescriptor(
  "/grpcwebtest.TestService/Fail",
  grpcWeb.MethodType.UNARY,
  FailRequest,
  EchoReply,
  (request) => request.serializeBinary(),
  EchoReply.deserializeBinary,
);

function unaryClient(format) {
  return new grpcWeb.GrpcWebClientBase({ format });
}

export function unaryBinary(baseUrl, message = "browser") {
  const client = unaryClient("binary");
  const request = new UnaryRequest(message);

  return client.unaryCall(
    `${baseUrl}/grpcwebtest.TestService/Unary`,
    request,
    {},
    unaryMethod,
  );
}

export function unaryText(baseUrl, message = "browser") {
  const client = unaryClient("text");
  const request = new UnaryRequest(message);

  return client.unaryCall(
    `${baseUrl}/grpcwebtest.TestService/Unary`,
    request,
    {},
    unaryMethod,
  );
}

export function failText(baseUrl, code = 3, message = "forced failure") {
  const client = unaryClient("text");
  const request = new FailRequest(code, message);

  return client.unaryCall(
    `${baseUrl}/grpcwebtest.TestService/Fail`,
    request,
    {},
    failMethod,
  );
}

export function openStream(baseUrl, options = {}) {
  const client = new grpcWeb.GrpcWebClientBase({ format: "text" });
  const request = new StreamRequest(options);
  const metadata = {};

  if (options.grpcTimeout) {
    metadata["grpc-timeout"] = options.grpcTimeout;
  }

  if (options.faultMode) {
    metadata["x-fault-mode"] = options.faultMode;
  }

  return client.serverStreaming(
    `${baseUrl}/grpcwebtest.TestService/Stream`,
    request,
    metadata,
    streamMethod,
  );
}
