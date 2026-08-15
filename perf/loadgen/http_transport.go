package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net/http"
	"os"
	"time"
)

func newHTTPTransport(cfg config) (*http.Transport, error) {
	transport := &http.Transport{
		DisableCompression:    true,
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          cfg.Streams * 2,
		MaxIdleConnsPerHost:   cfg.Streams * 2,
		MaxConnsPerHost:       0,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: time.Duration(cfg.TimeoutSeconds) * time.Second,
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
