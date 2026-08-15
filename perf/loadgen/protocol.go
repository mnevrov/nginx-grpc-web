package main

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"fmt"
)

const maxBenchmarkFrameBytes = 128 * 1024 * 1024

type grpcWebFrame struct {
	Trailer bool
	Payload []byte
}

type textFrameDecoder struct {
	encoded []byte
	binary  []byte
}

func (d *textFrameDecoder) Push(chunk []byte) ([]grpcWebFrame, error) {
	for _, b := range chunk {
		switch b {
		case ' ', '\t', '\r', '\n':
			continue
		default:
			d.encoded = append(d.encoded, b)
		}
	}

	for len(d.encoded) >= 4 {
		complete := len(d.encoded) / 4 * 4
		blockEnd := complete
		for i := 0; i < complete; i += 4 {
			q := d.encoded[i : i+4]
			if q[2] == '=' || q[3] == '=' {
				blockEnd = i + 4
				break
			}
		}

		dst := make([]byte, base64.StdEncoding.DecodedLen(blockEnd))
		n, err := base64.StdEncoding.Decode(dst, d.encoded[:blockEnd])
		if err != nil {
			return nil, fmt.Errorf("decode grpc-web-text: %w", err)
		}
		d.binary = append(d.binary, dst[:n]...)
		d.encoded = d.encoded[blockEnd:]

		// A block without padding can be decoded quartet-by-quartet. Keeping only
		// the non-complete tail prevents an 8 MiB DATA frame from becoming an
		// 11 MiB encoded-side allocation in addition to the decoded frame.
		if blockEnd == complete {
			break
		}
	}

	return consumeFrames(&d.binary)
}

func (d *textFrameDecoder) Finish() error {
	if len(d.encoded) != 0 {
		return fmt.Errorf("incomplete grpc-web-text quartet: %d bytes", len(d.encoded))
	}
	if len(d.binary) != 0 {
		return fmt.Errorf("incomplete grpc-web frame: %d decoded bytes", len(d.binary))
	}
	return nil
}

type binaryFrameDecoder struct {
	binary []byte
}

func (d *binaryFrameDecoder) Push(chunk []byte) ([]grpcWebFrame, error) {
	d.binary = append(d.binary, chunk...)
	return consumeFrames(&d.binary)
}

func (d *binaryFrameDecoder) Finish() error {
	if len(d.binary) != 0 {
		return fmt.Errorf("incomplete grpc-web frame: %d bytes", len(d.binary))
	}
	return nil
}

func consumeFrames(buffer *[]byte) ([]grpcWebFrame, error) {
	data := *buffer
	var frames []grpcWebFrame
	consumed := 0

	for len(data)-consumed >= 5 {
		header := data[consumed : consumed+5]
		payloadLen := int(binary.BigEndian.Uint32(header[1:5]))
		if payloadLen > maxBenchmarkFrameBytes {
			return nil, fmt.Errorf("grpc-web frame %d exceeds benchmark limit %d", payloadLen, maxBenchmarkFrameBytes)
		}
		total := 5 + payloadLen
		if len(data)-consumed < total {
			break
		}

		start := consumed + 5
		end := consumed + total
		frames = append(frames, grpcWebFrame{
			Trailer: header[0]&0x80 != 0,
			Payload: data[start:end],
		})
		consumed = end
	}

	if consumed == 0 {
		return frames, nil
	}

	// Preserve only an incomplete tail. Returned frame payloads continue to
	// reference the old backing array and are consumed by the caller before the
	// next Push; the decoder itself does not retain completed multi-MiB frames.
	remaining := append([]byte(nil), data[consumed:]...)
	*buffer = remaining
	return frames, nil
}

func encodeDataFrame(payload []byte) []byte {
	out := make([]byte, 5+len(payload))
	binary.BigEndian.PutUint32(out[1:5], uint32(len(payload)))
	copy(out[5:], payload)
	return out
}

func encodeStreamRequest(marker string, count, delayMS, payloadBytes uint32, includeTiming bool) []byte {
	var payload []byte
	payload = appendProtoBytes(payload, 1, []byte(marker))
	payload = appendProtoVarint(payload, 2, uint64(count))
	payload = appendProtoVarint(payload, 3, uint64(delayMS))
	if payloadBytes != 0 {
		payload = appendProtoVarint(payload, 8, uint64(payloadBytes))
	}
	if includeTiming {
		payload = appendProtoVarint(payload, 9, 1)
	}
	return payload
}

func appendProtoBytes(dst []byte, field int, value []byte) []byte {
	dst = appendVarint(dst, uint64(field<<3|2))
	dst = appendVarint(dst, uint64(len(value)))
	return append(dst, value...)
}

func appendProtoVarint(dst []byte, field int, value uint64) []byte {
	dst = appendVarint(dst, uint64(field<<3))
	return appendVarint(dst, value)
}

func appendVarint(dst []byte, value uint64) []byte {
	for value >= 0x80 {
		dst = append(dst, byte(value)|0x80)
		value >>= 7
	}
	return append(dst, byte(value))
}

func readVarint(data []byte, offset *int) (uint64, error) {
	var value uint64
	for shift := uint(0); shift < 64; shift += 7 {
		if *offset >= len(data) {
			return 0, fmt.Errorf("truncated varint")
		}
		b := data[*offset]
		*offset = *offset + 1
		value |= uint64(b&0x7f) << shift
		if b&0x80 == 0 {
			return value, nil
		}
	}
	return 0, fmt.Errorf("varint overflow")
}

type protoFields struct {
	Bytes   map[int][]byte
	Varints map[int]uint64
}

func scanProtoFields(data []byte) (protoFields, error) {
	fields := protoFields{Bytes: map[int][]byte{}, Varints: map[int]uint64{}}
	for offset := 0; offset < len(data); {
		key, err := readVarint(data, &offset)
		if err != nil {
			return fields, err
		}
		field := int(key >> 3)
		wire := int(key & 7)
		if field == 0 {
			return fields, fmt.Errorf("invalid protobuf field 0")
		}

		switch wire {
		case 0:
			value, err := readVarint(data, &offset)
			if err != nil {
				return fields, err
			}
			fields.Varints[field] = value
		case 1:
			if offset+8 > len(data) {
				return fields, fmt.Errorf("truncated fixed64 field %d", field)
			}
			offset += 8
		case 2:
			length, err := readVarint(data, &offset)
			if err != nil {
				return fields, err
			}
			if length > uint64(len(data)-offset) {
				return fields, fmt.Errorf("truncated bytes field %d", field)
			}
			end := offset + int(length)
			fields.Bytes[field] = data[offset:end]
			offset = end
		case 5:
			if offset+4 > len(data) {
				return fields, fmt.Errorf("truncated fixed32 field %d", field)
			}
			offset += 4
		default:
			return fields, fmt.Errorf("unsupported protobuf wire type %d", wire)
		}
	}
	return fields, nil
}

type echoObservation struct {
	Sequence        uint64
	ServerElapsedNS uint64
	MessageBytes    int
	MarkerOK        bool
}

func parseEchoReply(payload []byte, marker string) (echoObservation, error) {
	fields, err := scanProtoFields(payload)
	if err != nil {
		return echoObservation{}, err
	}
	message, ok := fields.Bytes[1]
	if !ok {
		return echoObservation{}, fmt.Errorf("EchoReply missing message field")
	}
	sequence, ok := fields.Varints[2]
	if !ok {
		return echoObservation{}, fmt.Errorf("EchoReply missing sequence field")
	}
	return echoObservation{
		Sequence:        sequence,
		ServerElapsedNS: fields.Varints[3],
		MessageBytes:    len(message),
		MarkerOK:        bytes.HasPrefix(message, []byte(marker)),
	}, nil
}

func parseTrailers(payload []byte) map[string]string {
	out := make(map[string]string)
	for _, line := range bytes.Split(payload, []byte("\r\n")) {
		if len(line) == 0 {
			continue
		}
		parts := bytes.SplitN(line, []byte(":"), 2)
		if len(parts) != 2 {
			continue
		}
		out[string(bytes.ToLower(bytes.TrimSpace(parts[0])))] = string(bytes.TrimSpace(parts[1]))
	}
	return out
}
