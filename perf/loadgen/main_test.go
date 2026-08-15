package main

import (
	"encoding/base64"
	"encoding/binary"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func dataFrame(payload []byte) []byte {
	out := make([]byte, 5+len(payload))
	binary.BigEndian.PutUint32(out[1:5], uint32(len(payload)))
	copy(out[5:], payload)
	return out
}

func trailerFrame(payload []byte) []byte {
	out := make([]byte, 5+len(payload))
	out[0] = 0x80
	binary.BigEndian.PutUint32(out[1:5], uint32(len(payload)))
	copy(out[5:], payload)
	return out
}

func TestTextDecoderHandlesIndependentPaddedBlocksAndFragmentation(t *testing.T) {
	first := dataFrame([]byte{0x0a, 0x01, 'a', 0x10, 0x01})
	trailers := trailerFrame([]byte("grpc-status:0\r\n"))

	// Envoy/module may encode complete grpc-web frames as independent Base64
	// documents. Padding can therefore appear in the middle of the HTTP body.
	wire := append([]byte(base64.StdEncoding.EncodeToString(first)), []byte(base64.StdEncoding.EncodeToString(trailers))...)

	var decoder textFrameDecoder
	var got []grpcWebFrame
	for _, cut := range []int{1, 2, 5, 3, 7, 4, 11, 13, 17, 19} {
		if len(wire) == 0 {
			break
		}
		if cut > len(wire) {
			cut = len(wire)
		}
		frames, err := decoder.Push(wire[:cut])
		if err != nil {
			t.Fatalf("Push: %v", err)
		}
		got = append(got, frames...)
		wire = wire[cut:]
	}
	if len(wire) > 0 {
		frames, err := decoder.Push(wire)
		if err != nil {
			t.Fatalf("Push remainder: %v", err)
		}
		got = append(got, frames...)
	}

	if len(got) != 2 {
		t.Fatalf("got %d frames, want 2", len(got))
	}
	if got[0].Trailer {
		t.Fatal("first frame unexpectedly trailer")
	}
	if !got[1].Trailer {
		t.Fatal("second frame must be trailer")
	}
}

func TestEncodeStreamRequestIncludesPerfControls(t *testing.T) {
	payload := encodeStreamRequest("perf", 8, 25, 4*1024*1024, true)
	if len(payload) == 0 {
		t.Fatal("empty request")
	}

	fields, err := scanProtoFields(payload)
	if err != nil {
		t.Fatalf("scan request: %v", err)
	}
	if string(fields.Bytes[1]) != "perf" {
		t.Fatalf("marker=%q", fields.Bytes[1])
	}
	if fields.Varints[2] != 8 || fields.Varints[3] != 25 {
		t.Fatalf("count/delay=%d/%d", fields.Varints[2], fields.Varints[3])
	}
	if fields.Varints[8] != 4*1024*1024 {
		t.Fatalf("payload bytes=%d", fields.Varints[8])
	}
	if fields.Varints[9] != 1 {
		t.Fatalf("include timing=%d", fields.Varints[9])
	}
}

func TestParseEchoReplyReadsLengthSequenceAndServerTimingWithoutCopyingMessage(t *testing.T) {
	message := []byte("perf" + "xxxxxxxxxxxxxxxx")
	payload := appendProtoBytes(nil, 1, message)
	payload = appendProtoVarint(payload, 2, 7)
	payload = appendProtoVarint(payload, 3, 123456789)

	obs, err := parseEchoReply(payload, "perf")
	if err != nil {
		t.Fatalf("parseEchoReply: %v", err)
	}
	if obs.Sequence != 7 || obs.ServerElapsedNS != 123456789 {
		t.Fatalf("sequence/timing=%d/%d", obs.Sequence, obs.ServerElapsedNS)
	}
	if obs.MessageBytes != len(message) {
		t.Fatalf("message bytes=%d want=%d", obs.MessageBytes, len(message))
	}
	if !obs.MarkerOK {
		t.Fatal("marker validation failed")
	}
}

func TestPercentileUsesNearestRankInterpolation(t *testing.T) {
	values := []float64{1, 2, 3, 4, 5}
	if got := percentile(values, 0.50); got != 3 {
		t.Fatalf("p50=%v", got)
	}
	if got := percentile(values, 0.95); got < 4.7 || got > 5.0 {
		t.Fatalf("p95=%v", got)
	}
}

func TestNewHTTPTransportPreservesCleartextHTTP1Baseline(t *testing.T) {
	transport, err := newHTTPTransport(config{
		URL:            "http://127.0.0.1:19080",
		Streams:        1,
		TimeoutSeconds: 5,
	})
	if err != nil {
		t.Fatalf("newHTTPTransport: %v", err)
	}
	defer transport.CloseIdleConnections()

	if transport.ForceAttemptHTTP2 {
		t.Fatal("cleartext HTTP/1.1 baseline must not force HTTP/2")
	}
	if transport.TLSClientConfig != nil {
		t.Fatal("cleartext HTTP/1.1 baseline must not install TLS config")
	}
}

func TestNewHTTPTransportNegotiatesHTTP2WithCustomCA(t *testing.T) {
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	server.EnableHTTP2 = true
	server.StartTLS()
	defer server.Close()

	certificate := server.Certificate()
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certificate.Raw})
	caFile := filepath.Join(t.TempDir(), "ca.crt")
	if err := os.WriteFile(caFile, caPEM, 0o600); err != nil {
		t.Fatalf("write CA: %v", err)
	}

	transport, err := newHTTPTransport(config{
		URL:             server.URL,
		Streams:         1,
		TimeoutSeconds:  5,
		CAFile:          caFile,
		RequireHTTP2:    true,
	})
	if err != nil {
		t.Fatalf("newHTTPTransport: %v", err)
	}
	defer transport.CloseIdleConnections()

	if !transport.ForceAttemptHTTP2 {
		t.Fatal("TLS/H2 transport must explicitly attempt HTTP/2")
	}

	response, err := (&http.Client{Transport: transport}).Get(server.URL)
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer response.Body.Close()

	if response.ProtoMajor != 2 {
		t.Fatalf("protocol=%s, want HTTP/2", response.Proto)
	}
	if response.TLS == nil || response.TLS.NegotiatedProtocol != "h2" {
		t.Fatalf("ALPN=%q, want h2", response.TLS.NegotiatedProtocol)
	}
}

func TestValidateResponseProtocolRejectsHTTP11WhenHTTP2Required(t *testing.T) {
	response := &http.Response{Proto: "HTTP/1.1", ProtoMajor: 1, ProtoMinor: 1}
	if err := validateResponseProtocol(response, true); err == nil {
		t.Fatal("expected HTTP/1.1 rejection when HTTP/2 is required")
	}
	if err := validateResponseProtocol(response, false); err != nil {
		t.Fatalf("HTTP/1.1 must be accepted when HTTP/2 is optional: %v", err)
	}
}
