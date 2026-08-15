package main

import (
	"encoding/base64"
	"encoding/binary"
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
