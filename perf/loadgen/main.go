package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

const streamMethod = "/grpcwebtest.TestService/Stream"

type config struct {
	Name                string `json:"name"`
	Frontend            string `json:"frontend"`
	URL                 string `json:"url"`
	Transport           string `json:"transport"`
	Streams             int    `json:"streams"`
	Messages            int    `json:"messages_per_stream"`
	DelayMS             int    `json:"backend_delay_ms"`
	PayloadBytes        int    `json:"payload_bytes"`
	ConsumerDelayMS     int    `json:"consumer_delay_ms"`
	CancelAfterMessages int    `json:"cancel_after_messages,omitempty"`
	TimeoutSeconds      int    `json:"timeout_seconds"`
	Marker              string `json:"marker"`
	GOMAXPROCS          int    `json:"gomaxprocs"`
	CAFile              string `json:"ca_file,omitempty"`
	TLSServerName       string `json:"tls_server_name,omitempty"`
	RequireHTTP2        bool   `json:"require_http2"`
}

type streamResult struct {
	ID             int       `json:"id"`
	Error          string    `json:"error,omitempty"`
	Cancelled      bool      `json:"cancelled,omitempty"`
	HTTPStatus     int       `json:"http_status,omitempty"`
	HTTPProtocol   string    `json:"http_protocol,omitempty"`
	TLSALPN        string    `json:"tls_alpn,omitempty"`
	TLSVersion     string    `json:"tls_version,omitempty"`
	HeaderMS       float64   `json:"header_ms,omitempty"`
	TTFDMS         float64   `json:"ttfd_ms,omitempty"`
	DurationMS     float64   `json:"duration_ms,omitempty"`
	DataFrames     int       `json:"data_frames"`
	PayloadBytes   int64     `json:"payload_bytes"`
	WireBytes      int64     `json:"wire_bytes"`
	AddedMS        []float64 `json:"backend_to_client_ms,omitempty"`
	InterArrivalMS []float64 `json:"inter_arrival_ms,omitempty"`
	GRPCStatus     string    `json:"grpc_status,omitempty"`
}

type distribution struct {
	P50  float64 `json:"p50"`
	P95  float64 `json:"p95"`
	P99  float64 `json:"p99"`
	P999 float64 `json:"p99_9"`
}

type summary struct {
	StreamsRequested  int          `json:"streams_requested"`
	StreamsCompleted  int          `json:"streams_completed"`
	StreamsCancelled  int          `json:"streams_cancelled"`
	Errors            int          `json:"errors"`
	DataFrames        int          `json:"data_frames"`
	PayloadBytes      int64        `json:"payload_bytes"`
	WireBytes         int64        `json:"wire_bytes"`
	WallSeconds       float64      `json:"wall_seconds"`
	MessagesPerSecond float64      `json:"messages_per_second"`
	MiBPerSecond      float64      `json:"mib_per_second"`
	WireAmplification float64      `json:"wire_amplification"`
	HeaderMS          distribution `json:"header_ms"`
	TTFDMS            distribution `json:"ttfd_ms"`
	BackendToClientMS distribution `json:"backend_to_client_ms"`
	InterArrivalMS    distribution `json:"inter_arrival_ms"`
	StreamDurationMS  distribution `json:"stream_duration_ms"`
}

type runResult struct {
	Version   int            `json:"version"`
	Timestamp string         `json:"timestamp"`
	Config    config         `json:"config"`
	Summary   summary        `json:"summary"`
	Streams   []streamResult `json:"streams"`
}

type frameDecoder interface {
	Push([]byte) ([]grpcWebFrame, error)
	Finish() error
}

func percentile(values []float64, q float64) float64 {
	if len(values) == 0 {
		return 0
	}
	copyValues := append([]float64(nil), values...)
	sort.Float64s(copyValues)
	if q <= 0 {
		return copyValues[0]
	}
	if q >= 1 {
		return copyValues[len(copyValues)-1]
	}
	pos := q * float64(len(copyValues)-1)
	lower := int(pos)
	upper := lower + 1
	if upper >= len(copyValues) {
		return copyValues[lower]
	}
	fraction := pos - float64(lower)
	return copyValues[lower] + (copyValues[upper]-copyValues[lower])*fraction
}

func describe(values []float64) distribution {
	return distribution{
		P50:  percentile(values, 0.50),
		P95:  percentile(values, 0.95),
		P99:  percentile(values, 0.99),
		P999: percentile(values, 0.999),
	}
}

func validateConfig(cfg config) error {
	if cfg.Streams <= 0 || cfg.Messages <= 0 || cfg.TimeoutSeconds <= 0 {
		return fmt.Errorf("streams, messages and timeout must be positive")
	}
	if cfg.CancelAfterMessages < 0 {
		return fmt.Errorf("cancel-after must be >= 0")
	}
	if cfg.CancelAfterMessages > 0 && cfg.CancelAfterMessages >= cfg.Messages {
		return fmt.Errorf("cancel-after must be smaller than messages")
	}
	if cfg.RequireHTTP2 && !strings.HasPrefix(strings.ToLower(cfg.URL), "https://") {
		return fmt.Errorf("--require-http2 requires an https:// URL")
	}
	return nil
}

func buildRequestBody(cfg config) ([]byte, string, error) {
	if cfg.Messages <= 0 || cfg.Messages > int(^uint32(0)) {
		return nil, "", fmt.Errorf("messages out of uint32 range: %d", cfg.Messages)
	}
	if cfg.DelayMS < 0 || cfg.DelayMS > int(^uint32(0)) {
		return nil, "", fmt.Errorf("delay-ms out of uint32 range: %d", cfg.DelayMS)
	}
	if cfg.PayloadBytes < 0 || cfg.PayloadBytes > int(^uint32(0)) {
		return nil, "", fmt.Errorf("payload-bytes out of uint32 range: %d", cfg.PayloadBytes)
	}

	proto := encodeStreamRequest(
		cfg.Marker,
		uint32(cfg.Messages),
		uint32(cfg.DelayMS),
		uint32(cfg.PayloadBytes),
		true,
	)
	frame := encodeDataFrame(proto)

	switch cfg.Transport {
	case "text":
		encoded := make([]byte, base64.StdEncoding.EncodedLen(len(frame)))
		base64.StdEncoding.Encode(encoded, frame)
		return encoded, "application/grpc-web-text+proto", nil
	case "binary":
		return frame, "application/grpc-web+proto", nil
	default:
		return nil, "", fmt.Errorf("unsupported transport %q", cfg.Transport)
	}
}

func newDecoder(transport string) (frameDecoder, error) {
	switch transport {
	case "text":
		return &textFrameDecoder{}, nil
	case "binary":
		return &binaryFrameDecoder{}, nil
	default:
		return nil, fmt.Errorf("unsupported transport %q", transport)
	}
}

func runStream(ctx context.Context, client *http.Client, cfg config, id int, start <-chan struct{}) streamResult {
	result := streamResult{ID: id}
	<-start
	started := time.Now()

	body, contentType, err := buildRequestBody(cfg)
	if err != nil {
		result.Error = err.Error()
		return result
	}

	streamCtx := ctx
	var streamCancel context.CancelFunc
	if cfg.CancelAfterMessages > 0 {
		streamCtx, streamCancel = context.WithCancel(ctx)
		defer streamCancel()
	}

	request, err := http.NewRequestWithContext(streamCtx, http.MethodPost, strings.TrimRight(cfg.URL, "/")+streamMethod, bytes.NewReader(body))
	if err != nil {
		result.Error = err.Error()
		return result
	}
	request.Header.Set("Content-Type", contentType)
	request.Header.Set("Accept", contentType)
	request.Header.Set("X-Grpc-Web", "1")
	request.Header.Set("X-User-Agent", "nginx-grpc-web-perf/1")

	response, err := client.Do(request)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	defer response.Body.Close()

	result.HTTPStatus = response.StatusCode
	result.HTTPProtocol = response.Proto
	if response.TLS != nil {
		result.TLSALPN = response.TLS.NegotiatedProtocol
		result.TLSVersion = tlsVersionName(response.TLS.Version)
	}
	result.HeaderMS = float64(time.Since(started).Nanoseconds()) / 1e6
	if err := validateResponseProtocol(response, cfg.RequireHTTP2); err != nil {
		result.Error = err.Error()
		_, _ = io.Copy(io.Discard, response.Body)
		return result
	}
	if response.StatusCode != http.StatusOK {
		result.Error = fmt.Sprintf("HTTP %d", response.StatusCode)
		_, _ = io.Copy(io.Discard, response.Body)
		return result
	}

	decoder, err := newDecoder(cfg.Transport)
	if err != nil {
		result.Error = err.Error()
		return result
	}

	readBuffer := make([]byte, 128*1024)
	expectedSequence := uint64(1)
	expectedMessageBytes := cfg.PayloadBytes
	if expectedMessageBytes == 0 {
		expectedMessageBytes = len(cfg.Marker)
	}
	var lastData time.Duration
	seenTrailer := false

	for {
		n, readErr := response.Body.Read(readBuffer)
		if n > 0 {
			result.WireBytes += int64(n)
			frames, decodeErr := decoder.Push(readBuffer[:n])
			if decodeErr != nil {
				result.Error = decodeErr.Error()
				return result
			}
			for _, frame := range frames {
				if frame.Trailer {
					trailers := parseTrailers(frame.Payload)
					result.GRPCStatus = trailers["grpc-status"]
					seenTrailer = true
					continue
				}

				arrival := time.Since(started)
				obs, parseErr := parseEchoReply(frame.Payload, cfg.Marker)
				if parseErr != nil {
					result.Error = parseErr.Error()
					return result
				}
				if !obs.MarkerOK {
					result.Error = "response marker mismatch"
					return result
				}
				if obs.MessageBytes != expectedMessageBytes {
					result.Error = fmt.Sprintf("message bytes=%d want=%d", obs.MessageBytes, expectedMessageBytes)
					return result
				}
				if obs.Sequence != expectedSequence {
					result.Error = fmt.Sprintf("sequence=%d want=%d", obs.Sequence, expectedSequence)
					return result
				}
				expectedSequence++

				if result.DataFrames == 0 {
					result.TTFDMS = float64(arrival.Nanoseconds()) / 1e6
				} else {
					result.InterArrivalMS = append(result.InterArrivalMS, float64((arrival-lastData).Nanoseconds())/1e6)
				}
				lastData = arrival
				result.DataFrames++
				result.PayloadBytes += int64(obs.MessageBytes)
				if obs.ServerElapsedNS > 0 {
					addedNS := arrival.Nanoseconds() - int64(obs.ServerElapsedNS)
					result.AddedMS = append(result.AddedMS, float64(addedNS)/1e6)
				}

				if cfg.CancelAfterMessages > 0 && result.DataFrames >= cfg.CancelAfterMessages {
					result.Cancelled = true
					result.DurationMS = float64(time.Since(started).Nanoseconds()) / 1e6
					if streamCancel != nil {
						streamCancel()
					}
					_ = response.Body.Close()
					return result
				}

				if cfg.ConsumerDelayMS > 0 {
					time.Sleep(time.Duration(cfg.ConsumerDelayMS) * time.Millisecond)
				}
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			result.Error = readErr.Error()
			return result
		}
	}

	if err := decoder.Finish(); err != nil {
		result.Error = err.Error()
		return result
	}
	result.DurationMS = float64(time.Since(started).Nanoseconds()) / 1e6
	if result.DataFrames != cfg.Messages {
		result.Error = fmt.Sprintf("DATA frames=%d want=%d", result.DataFrames, cfg.Messages)
		return result
	}
	if !seenTrailer {
		result.Error = "missing grpc-web trailer frame"
		return result
	}
	if result.GRPCStatus != "0" {
		result.Error = fmt.Sprintf("grpc-status=%q", result.GRPCStatus)
		return result
	}
	return result
}

func summarize(cfg config, streams []streamResult, wall time.Duration) summary {
	out := summary{StreamsRequested: cfg.Streams, WallSeconds: wall.Seconds()}
	var headers, ttfd, added, inter, durations []float64

	for _, stream := range streams {
		if stream.Error != "" {
			out.Errors++
			continue
		}
		if stream.Cancelled {
			out.StreamsCancelled++
		} else {
			out.StreamsCompleted++
		}
		out.DataFrames += stream.DataFrames
		out.PayloadBytes += stream.PayloadBytes
		out.WireBytes += stream.WireBytes
		headers = append(headers, stream.HeaderMS)
		ttfd = append(ttfd, stream.TTFDMS)
		added = append(added, stream.AddedMS...)
		inter = append(inter, stream.InterArrivalMS...)
		durations = append(durations, stream.DurationMS)
	}

	if wall > 0 {
		out.MessagesPerSecond = float64(out.DataFrames) / wall.Seconds()
		out.MiBPerSecond = float64(out.PayloadBytes) / (1024 * 1024) / wall.Seconds()
	}
	if out.PayloadBytes > 0 {
		out.WireAmplification = float64(out.WireBytes) / float64(out.PayloadBytes)
	}
	out.HeaderMS = describe(headers)
	out.TTFDMS = describe(ttfd)
	out.BackendToClientMS = describe(added)
	out.InterArrivalMS = describe(inter)
	out.StreamDurationMS = describe(durations)
	return out
}

func execute(cfg config) (runResult, error) {
	if cfg.GOMAXPROCS > 0 {
		runtime.GOMAXPROCS(cfg.GOMAXPROCS)
	}

	transport, err := newHTTPTransport(cfg)
	if err != nil {
		return runResult{}, err
	}
	client := &http.Client{Transport: transport}
	defer transport.CloseIdleConnections()

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.TimeoutSeconds)*time.Second)
	defer cancel()

	start := make(chan struct{})
	streams := make([]streamResult, cfg.Streams)
	var wg sync.WaitGroup
	wg.Add(cfg.Streams)
	for i := 0; i < cfg.Streams; i++ {
		go func(index int) {
			defer wg.Done()
			streams[index] = runStream(ctx, client, cfg, index, start)
		}(i)
	}

	wallStarted := time.Now()
	close(start)
	wg.Wait()
	wall := time.Since(wallStarted)

	return runResult{
		Version:   3,
		Timestamp: time.Now().UTC().Format(time.RFC3339Nano),
		Config:    cfg,
		Summary:   summarize(cfg, streams, wall),
		Streams:   streams,
	}, nil
}

func main() {
	cfg := config{}
	flag.StringVar(&cfg.Name, "name", "benchmark", "result label")
	flag.StringVar(&cfg.Frontend, "frontend", "http1", "frontend mode label: http1 or tls-h2")
	flag.StringVar(&cfg.URL, "url", "http://127.0.0.1:19080", "gateway base URL")
	flag.StringVar(&cfg.Transport, "transport", "text", "grpc-web transport: text or binary")
	flag.IntVar(&cfg.Streams, "streams", 10, "concurrent server streams")
	flag.IntVar(&cfg.Messages, "messages", 20, "DATA messages per stream")
	flag.IntVar(&cfg.DelayMS, "delay-ms", 20, "backend delay before each DATA message")
	flag.IntVar(&cfg.PayloadBytes, "payload-bytes", 4096, "EchoReply.message bytes")
	flag.IntVar(&cfg.ConsumerDelayMS, "consumer-delay-ms", 0, "sleep after each decoded DATA frame")
	flag.IntVar(&cfg.CancelAfterMessages, "cancel-after", 0, "cancel each stream after N decoded DATA frames (0 disables)")
	flag.IntVar(&cfg.TimeoutSeconds, "timeout", 120, "whole run timeout in seconds")
	flag.StringVar(&cfg.Marker, "marker", "perf", "payload prefix marker")
	flag.IntVar(&cfg.GOMAXPROCS, "gomaxprocs", 0, "load generator GOMAXPROCS (0 keeps runtime default)")
	flag.StringVar(&cfg.CAFile, "ca-file", "", "PEM CA file for HTTPS benchmark endpoints")
	flag.StringVar(&cfg.TLSServerName, "tls-server-name", "", "TLS certificate server name override")
	flag.BoolVar(&cfg.RequireHTTP2, "require-http2", false, "require TLS HTTP/2 with ALPN h2")
	output := flag.String("output", "", "JSON output path; stdout when empty")
	flag.Parse()

	if err := validateConfig(cfg); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	result, err := execute(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "execute benchmark: %v\n", err)
		os.Exit(1)
	}
	encoded, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "encode result: %v\n", err)
		os.Exit(1)
	}
	encoded = append(encoded, '\n')

	if *output == "" {
		_, _ = os.Stdout.Write(encoded)
	} else if err := os.WriteFile(*output, encoded, 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "write %s: %v\n", *output, err)
		os.Exit(1)
	}

	if result.Summary.Errors != 0 {
		fmt.Fprintf(os.Stderr, "%d/%d streams failed\n", result.Summary.Errors, result.Summary.StreamsRequested)
		os.Exit(1)
	}
	if cfg.CancelAfterMessages > 0 && result.Summary.StreamsCancelled != result.Summary.StreamsRequested {
		fmt.Fprintf(os.Stderr, "%d/%d streams cancelled, expected all\n", result.Summary.StreamsCancelled, result.Summary.StreamsRequested)
		os.Exit(1)
	}
}
