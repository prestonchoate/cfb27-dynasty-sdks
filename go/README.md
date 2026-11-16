# dynasty (Go)

Typed Go client for the CFB 27 [Dynasty API](https://dynasty.prestonchoate.dev/v1/docs). No dependencies.

```sh
go get github.com/prestonchoate/cfb27-dynasty-sdks/go
```

```go
import "github.com/prestonchoate/cfb27-dynasty-sdks/go/dynasty"

c := dynasty.NewClient(os.Getenv("DYNASTY_API_KEY"))

league, err := c.GetLeague(ctx)
if err != nil {
	return err
}
fmt.Println(league.Data.Name)

sched, err := c.ListSchedule(ctx, &dynasty.ListScheduleParams{
	Week:      dynasty.Ptr(3),
	UserGames: dynasty.Ptr(true),
})

_, err = c.GetGame(ctx, 123456, nil)
if dynasty.ErrorCode(err) == "not_found" {
	// ...
}
```

Optional parameters and fields are pointers; `dynasty.Ptr(v)` makes one. Pass
`nil` params to use the server's defaults.

## Partner API

```go
p := dynasty.NewPartnerClient(os.Getenv("PARTNER_KEY"))
list, err := p.ListDynasties(ctx)

// read a dynasty you have access to with the same key
standings, err := p.Dynasty(list.Accounts[0].Dynasties[0].DynastyID).ListStandings(ctx, nil)

// join an invite (waits on EA; up to ~150 s)
res, err := p.JoinInvite(ctx, inviteID, &dynasty.JoinInviteBody{TeamID: 42})
```

## Options

`WithBaseURL`, `WithHTTPClient`, `WithTimeout` (30 s; partner 180 s),
`WithMaxRetries` (2), `WithMaxRetryWait` (1 min), `WithETagCache(size)` (256;
0 disables), `WithDynastyID` (with a partner key) and `WithHeader`.
`c.WithDynasty(id)` returns a client for another dynasty sharing the same key
and cache. Clients are safe for concurrent use.

Errors from the API are `*dynasty.APIError` (`StatusCode`, `Code`, `Message`,
`RetryAfter`, `Body`); use `errors.As` or `dynasty.ErrorCode(err)`.
