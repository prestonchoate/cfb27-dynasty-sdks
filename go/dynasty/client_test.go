package dynasty

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

type reply struct {
	status  int
	headers map[string]string
	body    string
}

// server answers from a queue and records each request and its body.
func server(t *testing.T, replies ...reply) (*httptest.Server, *[]*http.Request, *[]string) {
	t.Helper()
	var mu sync.Mutex
	var reqs []*http.Request
	var bodies []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		b, _ := io.ReadAll(r.Body)
		reqs = append(reqs, r)
		bodies = append(bodies, string(b))
		if len(replies) == 0 {
			t.Errorf("unexpected request %s %s", r.Method, r.URL)
			w.WriteHeader(500)
			return
		}
		rp := replies[0]
		replies = replies[1:]
		for k, v := range rp.headers {
			w.Header().Set(k, v)
		}
		if rp.status == 0 {
			rp.status = 200
		}
		w.WriteHeader(rp.status)
		io.WriteString(w, rp.body)
	}))
	t.Cleanup(srv.Close)
	return srv, &reqs, &bodies
}

const league = `{"league_id":7,"data_version":3,"data":{"league_id":7,"name":"Test","season_text":"2027","calendar_year":2027,"status":"active","last_sync_at":null,"last_sync_status":"ok","current_period":null,"seasons":[2027]}}`

func TestQueryAuthAndDynastyID(t *testing.T) {
	srv, reqs, _ := server(t, reply{body: `{"league_id":7,"data_version":1,"season":2027,"data":[]}`})
	c := NewClient("cfbp_x", WithBaseURL(srv.URL), WithDynastyID(7))
	res, err := c.ListSchedule(context.Background(), &ListScheduleParams{Season: Ptr(2027), Played: Ptr(true)})
	if err != nil {
		t.Fatal(err)
	}
	if res.Season != 2027 {
		t.Fatalf("season = %d", res.Season)
	}
	r := (*reqs)[0]
	if got := r.URL.String(); got != "/v1/schedule?played=true&season=2027" {
		t.Errorf("url = %s", got)
	}
	if r.Header.Get("Authorization") != "Bearer cfbp_x" || r.Header.Get("Dynasty-Id") != "7" {
		t.Errorf("headers = %v", r.Header)
	}
}

func TestETagRevalidation(t *testing.T) {
	srv, reqs, _ := server(t,
		reply{headers: map[string]string{"ETag": `W/"3"`}, body: league},
		reply{status: 304},
	)
	c := NewClient("k", WithBaseURL(srv.URL))
	a, err := c.GetLeague(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	b, err := c.GetLeague(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if a == b || b.Data.Name != "Test" || b.Data.LastSyncAt != nil {
		t.Errorf("cached league = %+v", b.Data)
	}
	if got := (*reqs)[1].Header.Get("If-None-Match"); got != `W/"3"` {
		t.Errorf("If-None-Match = %q", got)
	}
	// another dynasty doesn't reuse the entry
	srv2, reqs2, _ := server(t, reply{body: league})
	c2 := NewClient("k", WithBaseURL(srv2.URL))
	c2.t.cache.set("0 "+srv2.URL+"/v1/league", `"x"`, []byte(league))
	if _, err := c2.WithDynasty(5).GetLeague(context.Background()); err != nil {
		t.Fatal(err)
	}
	if (*reqs2)[0].Header.Get("If-None-Match") != "" {
		t.Error("cache leaked across dynasties")
	}
}

func TestRetries429(t *testing.T) {
	srv, reqs, _ := server(t,
		reply{status: 429, headers: map[string]string{"Retry-After": "0"}, body: `{"error":{"code":"rate_limited","message":"slow"}}`},
		reply{body: `{"league_id":1,"data_version":1,"data":[]}`},
	)
	if _, err := NewClient("k", WithBaseURL(srv.URL)).ListSeasons(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(*reqs) != 2 {
		t.Errorf("requests = %d", len(*reqs))
	}
}

func TestLongRetryAfterReturnsError(t *testing.T) {
	srv, _, _ := server(t, reply{status: 429, headers: map[string]string{"Retry-After": "300"}, body: `{"error":{"code":"rate_limited","message":"once per 5 minutes"}}`})
	_, err := NewPartnerClient("cfbp_x", WithBaseURL(srv.URL)).RefreshDynasties(context.Background())
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 429 || apiErr.RetryAfter != 300*time.Second || ErrorCode(err) != "rate_limited" {
		t.Fatalf("err = %#v", err)
	}
}

func TestErrorEnvelope(t *testing.T) {
	srv, _, _ := server(t, reply{status: 404, body: `{"error":{"code":"not_found","message":"no such game"}}`})
	_, err := NewClient("k", WithBaseURL(srv.URL)).GetGame(context.Background(), 1, nil)
	if ErrorCode(err) != "not_found" || err.Error() != "dynasty api: 404 not_found: no such game" {
		t.Fatalf("err = %v", err)
	}
}

func TestPostBodyAnd204(t *testing.T) {
	srv, reqs, bodies := server(t,
		reply{status: 201, body: `{"payment_id":"pi_1","dynasty_id":3,"amount_cents":299,"period_start":"2026-11-01T00:00:00Z","period_end":"2026-12-01T00:00:00Z","billing":{"status":"active"}}`},
		reply{status: 204},
		reply{status: 201, body: `{"dynasty_id":3}`},
	)
	p := NewPartnerClient("cfbp_x", WithBaseURL(srv.URL))
	start := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	pay, err := p.ReportPayment(context.Background(), 3, &ReportPaymentBody{PaymentID: "pi_1", PeriodStart: start, PeriodEnd: start.AddDate(0, 1, 0)})
	if err != nil {
		t.Fatal(err)
	}
	if pay.Billing.Status != "active" || !pay.PeriodStart.Equal(start) {
		t.Errorf("payment = %+v", pay)
	}
	var sent map[string]any
	json.Unmarshal([]byte((*bodies)[0]), &sent)
	if sent["payment_id"] != "pi_1" || sent["period_start"] != "2026-11-01T00:00:00Z" {
		t.Errorf("body = %s", (*bodies)[0])
	}
	if (*reqs)[0].Header.Get("Content-Type") != "application/json" {
		t.Error("no content type")
	}
	if err := p.StopSync(context.Background(), 3); err != nil {
		t.Fatal(err)
	}
	// optional body may be nil: no body is sent
	if _, err := p.CreateAccessRequest(context.Background(), 3, nil); err != nil {
		t.Fatal(err)
	}
	if (*bodies)[2] != "" {
		t.Errorf("nil body sent %q", (*bodies)[2])
	}
}

func TestPartnerDynasty(t *testing.T) {
	srv, reqs, _ := server(t, reply{body: league})
	if _, err := NewPartnerClient("cfbp_x", WithBaseURL(srv.URL)).Dynasty(42).GetLeague(context.Background()); err != nil {
		t.Fatal(err)
	}
	r := (*reqs)[0]
	if r.URL.Path != "/v1/league" || r.Header.Get("Dynasty-Id") != "42" {
		t.Errorf("%s %v", r.URL.Path, r.Header)
	}
}

func TestContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := NewClient("k", WithBaseURL("http://127.0.0.1:1")).GetLeague(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
}
