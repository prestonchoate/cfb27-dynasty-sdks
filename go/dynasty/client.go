// Package dynasty is a typed client for the CFB 27 Dynasty API.
//
// Client reads one dynasty's cached data from /v1:
//
//	c := dynasty.NewClient(os.Getenv("DYNASTY_API_KEY"))
//	sched, err := c.ListSchedule(ctx, &dynasty.ListScheduleParams{Week: dynasty.Ptr(3)})
//
// PartnerClient calls /partner/v1 with a partner key (cfbp_…); its Dynasty
// method returns a Client that reads a dynasty with the same key.
//
// GET responses are cached by ETag and revalidated with If-None-Match, so
// polling unchanged data costs a 304. Rate limits (429) with a short
// Retry-After are retried automatically; other failures return *APIError.
package dynasty

import (
	"net/http"
	"time"
)

// DefaultBaseURL is the API's site root.
const DefaultBaseURL = "https://dynasty.prestonchoate.dev"

// Version is this SDK's version, sent in the User-Agent.
const Version = "0.1.1"

// Client reads one dynasty's data from /v1. It is safe for concurrent use.
type Client struct {
	t         *transport
	dynastyID int
}

// NewClient returns a /v1 client. apiKey is a dynasty key (cfbk_…), or a
// partner key (cfbp_…) together with WithDynastyID.
func NewClient(apiKey string, opts ...Option) *Client {
	cfg := newConfig(apiKey, 30*time.Second, true)
	for _, o := range opts {
		o(cfg)
	}
	return &Client{t: newTransport(cfg, "/v1"), dynastyID: cfg.dynastyID}
}

// WithDynasty returns a client for another dynasty that shares this one's
// key, settings and ETag cache.
func (c *Client) WithDynasty(id int) *Client {
	return &Client{t: c.t, dynastyID: id}
}

// PartnerClient calls the partner API (/partner/v1). Requests that reach EA
// can take up to 150 s, so its default timeout is 180 s.
type PartnerClient struct {
	t         *transport
	dynastyID int // always 0; keeps generated code uniform
	cfg       *config
}

// NewPartnerClient returns a partner API client for a partner key (cfbp_…).
func NewPartnerClient(apiKey string, opts ...Option) *PartnerClient {
	cfg := newConfig(apiKey, 180*time.Second, false)
	for _, o := range opts {
		o(cfg)
	}
	return &PartnerClient{t: newTransport(cfg, "/partner/v1"), cfg: cfg}
}

// Dynasty returns a /v1 client that reads dynastyID with this partner key.
func (p *PartnerClient) Dynasty(dynastyID int) *Client {
	cfg := *p.cfg
	if !p.cfg.timeoutSet {
		cfg.timeout = 30 * time.Second
	}
	cfg.etagSize = 256
	return &Client{t: newTransport(&cfg, "/v1"), dynastyID: dynastyID}
}

type config struct {
	apiKey       string
	baseURL      string
	httpClient   *http.Client
	timeout      time.Duration
	timeoutSet   bool
	maxRetries   int
	maxRetryWait time.Duration
	etagSize     int
	userAgent    string
	dynastyID    int
	headers      http.Header
}

func newConfig(apiKey string, timeout time.Duration, cache bool) *config {
	c := &config{
		apiKey:       apiKey,
		baseURL:      DefaultBaseURL,
		timeout:      timeout,
		maxRetries:   2,
		maxRetryWait: time.Minute,
		userAgent:    "cfb27-dynasty-go/" + Version,
		headers:      http.Header{},
	}
	if cache {
		c.etagSize = 256
	}
	return c
}

// Option configures a client.
type Option func(*config)

// WithBaseURL sets the site root (without /v1). Default DefaultBaseURL.
func WithBaseURL(u string) Option { return func(c *config) { c.baseURL = u } }

// WithHTTPClient sets the HTTP client. Its Timeout, if set, also applies.
func WithHTTPClient(h *http.Client) Option { return func(c *config) { c.httpClient = h } }

// WithTimeout sets the per-attempt timeout (default 30 s, partner 180 s).
func WithTimeout(d time.Duration) Option {
	return func(c *config) { c.timeout, c.timeoutSet = d, true }
}

// WithMaxRetries sets how many times a request is retried after a 429 with
// a short Retry-After or, for GET, a network error or 502/503/504. Default 2.
func WithMaxRetries(n int) Option { return func(c *config) { c.maxRetries = n } }

// WithMaxRetryWait sets the longest Retry-After waited out automatically.
// Default one minute.
func WithMaxRetryWait(d time.Duration) Option { return func(c *config) { c.maxRetryWait = d } }

// WithETagCache sets how many GET responses are kept for If-None-Match
// revalidation (default 256); 0 turns the cache off.
func WithETagCache(size int) Option { return func(c *config) { c.etagSize = size } }

// WithDynastyID sets the dynasty a partner key reads (the Dynasty-Id header).
// A dynasty key names its own dynasty and ignores it.
func WithDynastyID(id int) Option { return func(c *config) { c.dynastyID = id } }

// WithHeader adds a header to every request.
func WithHeader(key, value string) Option { return func(c *config) { c.headers.Add(key, value) } }

// Ptr returns a pointer to v, for optional parameters:
// &ListScheduleParams{Season: dynasty.Ptr(2027)}.
func Ptr[T any](v T) *T { return &v }
