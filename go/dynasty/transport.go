package dynasty

import (
	"bytes"
	"container/list"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// APIError is an error response from the API. Code is stable and
// machine-readable (for example "not_found" or "rate_limited").
type APIError struct {
	StatusCode int
	Code       string
	Message    string
	// RetryAfter is the Retry-After header's value, or 0.
	RetryAfter time.Duration
	// Body is the raw response body.
	Body []byte
}

func (e *APIError) Error() string {
	return fmt.Sprintf("dynasty api: %d %s: %s", e.StatusCode, e.Code, e.Message)
}

// ErrorCode returns the API error code in err's chain, or "".
func ErrorCode(err error) string {
	var e *APIError
	if errors.As(err, &e) {
		return e.Code
	}
	return ""
}

type transport struct {
	cfg   *config
	base  string
	http  *http.Client
	cache *etagCache
}

func newTransport(cfg *config, basePath string) *transport {
	h := cfg.httpClient
	if h == nil {
		h = &http.Client{}
	}
	t := &transport{cfg: cfg, base: strings.TrimRight(cfg.baseURL, "/") + basePath, http: h}
	if cfg.etagSize > 0 {
		t.cache = newETagCache(cfg.etagSize)
	}
	return t
}

func (t *transport) do(ctx context.Context, dynastyID int, method, path string, q url.Values, body, out any) error {
	u := t.base + path
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	var payload []byte
	if body != nil {
		var err error
		if payload, err = json.Marshal(body); err != nil {
			return fmt.Errorf("dynasty api: encode body: %w", err)
		}
	}
	var cacheKey string
	var cached *etagEntry
	if method == http.MethodGet && t.cache != nil {
		cacheKey = strconv.Itoa(dynastyID) + " " + u
		cached = t.cache.get(cacheKey)
	}

	for attempt := 0; ; attempt++ {
		res, err := t.attempt(ctx, dynastyID, method, u, payload, cached)
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if method == http.MethodGet && attempt < t.cfg.maxRetries {
				if err := sleep(ctx, backoff(attempt)); err != nil {
					return err
				}
				continue
			}
			return fmt.Errorf("dynasty api: %s %s: %w", method, path, err)
		}
		data, err := io.ReadAll(res.Body)
		res.Body.Close()
		if err != nil {
			return fmt.Errorf("dynasty api: read %s %s: %w", method, path, err)
		}
		switch {
		case res.StatusCode == http.StatusNotModified && cached != nil:
			return decode(cached.body, out)
		case res.StatusCode == http.StatusNoContent:
			return nil
		case res.StatusCode >= 200 && res.StatusCode < 300:
			if etag := res.Header.Get("ETag"); cacheKey != "" && etag != "" {
				t.cache.set(cacheKey, etag, data)
			}
			return decode(data, out)
		}
		retryAfter := parseRetryAfter(res.Header.Get("Retry-After"))
		retryable := (res.StatusCode == http.StatusTooManyRequests && res.Header.Get("Retry-After") != "" && retryAfter <= t.cfg.maxRetryWait) ||
			(method == http.MethodGet && (res.StatusCode == 502 || res.StatusCode == 503 || res.StatusCode == 504))
		if retryable && attempt < t.cfg.maxRetries {
			wait := retryAfter
			if res.Header.Get("Retry-After") == "" {
				wait = backoff(attempt)
			}
			if err := sleep(ctx, wait); err != nil {
				return err
			}
			continue
		}
		apiErr := &APIError{StatusCode: res.StatusCode, Code: "http_" + strconv.Itoa(res.StatusCode), Message: http.StatusText(res.StatusCode), RetryAfter: retryAfter, Body: data}
		var env struct {
			Error struct{ Code, Message string } `json:"error"`
		}
		if json.Unmarshal(data, &env) == nil && env.Error.Code != "" {
			apiErr.Code, apiErr.Message = env.Error.Code, env.Error.Message
		}
		return apiErr
	}
}

func (t *transport) attempt(ctx context.Context, dynastyID int, method, u string, payload []byte, cached *etagEntry) (*http.Response, error) {
	ctx, cancel := context.WithTimeout(ctx, t.cfg.timeout)
	var rd io.Reader
	if payload != nil {
		rd = bytes.NewReader(payload)
	}
	req, err := http.NewRequestWithContext(ctx, method, u, rd)
	if err != nil {
		cancel()
		return nil, err
	}
	for k, v := range t.cfg.headers {
		req.Header[k] = v
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", "Bearer "+t.cfg.apiKey)
	req.Header.Set("User-Agent", t.cfg.userAgent)
	if dynastyID != 0 {
		req.Header.Set("Dynasty-Id", strconv.Itoa(dynastyID))
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if cached != nil {
		req.Header.Set("If-None-Match", cached.etag)
	}
	res, err := t.http.Do(req)
	if err != nil {
		cancel()
		return nil, err
	}
	res.Body = &cancelBody{ReadCloser: res.Body, cancel: cancel}
	return res, nil
}

// cancelBody releases the attempt's timeout context once the body is closed.
type cancelBody struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (b *cancelBody) Close() error {
	err := b.ReadCloser.Close()
	b.cancel()
	return err
}

func decode(data []byte, out any) error {
	if out == nil || len(data) == 0 {
		return nil
	}
	if err := json.Unmarshal(data, out); err != nil {
		return fmt.Errorf("dynasty api: decode response: %w", err)
	}
	return nil
}

func parseRetryAfter(h string) time.Duration {
	if h == "" {
		return 0
	}
	if n, err := strconv.ParseFloat(h, 64); err == nil && n >= 0 {
		return time.Duration(n * float64(time.Second))
	}
	if at, err := http.ParseTime(h); err == nil {
		return max(0, time.Until(at))
	}
	return 0
}

func backoff(attempt int) time.Duration {
	d := 500 * time.Millisecond << attempt
	return time.Duration(float64(d) * (0.5 + rand.Float64()/2))
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

type etagEntry struct {
	key  string
	etag string
	body []byte
}

type etagCache struct {
	mu    sync.Mutex
	size  int
	order *list.List
	items map[string]*list.Element
}

func newETagCache(size int) *etagCache {
	return &etagCache{size: size, order: list.New(), items: map[string]*list.Element{}}
}

func (c *etagCache) get(key string) *etagEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.items[key]; ok {
		c.order.MoveToFront(el)
		return el.Value.(*etagEntry)
	}
	return nil
}

func (c *etagCache) set(key, etag string, body []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.items[key]; ok {
		el.Value = &etagEntry{key, etag, body}
		c.order.MoveToFront(el)
		return
	}
	c.items[key] = c.order.PushFront(&etagEntry{key, etag, body})
	for c.order.Len() > c.size {
		last := c.order.Back()
		c.order.Remove(last)
		delete(c.items, last.Value.(*etagEntry).key)
	}
}
