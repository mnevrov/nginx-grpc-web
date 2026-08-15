package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

func newHTTPTransport(cfg config) (*http.Transport, error) {
	transport := &http.Transport{
		DisableCompression:    true,
		MaxIdleConns:          cfg.Streams * 2,
		MaxIdleConnsPerHost:   cfg.Streams * 2,
		MaxConnsPerHost:       0,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: time.Duration(cfg.TimeoutSeconds) * time.Second,
	}

	// Keep the original cleartext HTTP/1.1 benchmark transport unchanged.
	// HTTP/2 is an explicit property of the TLS/H2 frontend rather than a
	// global client setting shared by both benchmark baselines.
	if cfg.RequireHTTP2 || strings.HasPrefix(strings.ToLower(cfg.URL), "https://") {
		transport.ForceAttemptHTTP2 = true
	}

	if cfg.CAFile == "" && cfg.TLSServerName == "" {
		return transport, nil
	}

	tlsConfig := &tls.Config{MinVersion: tls.VersionTLS12}
	if cfg.CAFile != "" {
		pemBytes, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("read CA %s: %w", cfg.CAFile, err)
		}
		roots, err := x509.SystemCertPool()
		if err != nil || roots == nil {
			roots = x509.NewCertPool()
		}
		if ok := roots.AppendCertsFromPEM(pemBytes); !ok {
			return nil, fmt.Errorf("CA file %s contains no certificates", cfg.CAFile)
		}
		tlsConfig.RootCAs = roots
	}
	if cfg.TLSServerName != "" {
		tlsConfig.ServerName = cfg.TLSServerName
	}
	transport.TLSClientConfig = tlsConfig
	return transport, nil
}

func validateResponseProtocol(response *http.Response, requireHTTP2 bool) error {
	if !requireHTTP2 {
		return nil
	}
	if response.ProtoMajor != 2 {
		return fmt.Errorf("HTTP/2 required, negotiated %s", response.Proto)
	}
	if response.TLS == nil {
		return fmt.Errorf("HTTP/2 required over TLS, response has no TLS state")
	}
	if response.TLS.NegotiatedProtocol != "h2" {
		return fmt.Errorf("HTTP/2 required, ALPN=%q", response.TLS.NegotiatedProtocol)
	}
	return nil
}

func tlsVersionName(version uint16) string {
	switch version {
	case tls.VersionTLS13:
		return "TLS1.3"
	case tls.VersionTLS12:
		return "TLS1.2"
	case tls.VersionTLS11:
		return "TLS1.1"
	case tls.VersionTLS10:
		return "TLS1.0"
	default:
		if version == 0 {
			return ""
		}
		return fmt.Sprintf("0x%04x", version)
	}
}
