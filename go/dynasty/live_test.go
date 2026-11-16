package dynasty

import (
	"context"
	"os"
	"testing"
)

// TestLive calls every /v1 endpoint against a real server. It runs only when
// DYNASTY_API_KEY is set (DYNASTY_BASE_URL optionally overrides the host).
func TestLive(t *testing.T) {
	key := os.Getenv("DYNASTY_API_KEY")
	if key == "" {
		t.Skip("DYNASTY_API_KEY not set")
	}
	opts := []Option{}
	if u := os.Getenv("DYNASTY_BASE_URL"); u != "" {
		opts = append(opts, WithBaseURL(u))
	}
	c := NewClient(key, opts...)
	ctx := context.Background()
	sched, err := c.ListSchedule(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	calls := map[string]func() error{
		"GetLeague":              func() error { _, err := c.GetLeague(ctx); return err },
		"ListPeriods":            func() error { _, err := c.ListPeriods(ctx); return err },
		"ListSeasons":            func() error { _, err := c.ListSeasons(ctx); return err },
		"ListStandings":          func() error { _, err := c.ListStandings(ctx, nil); return err },
		"ListTeamStats":          func() error { _, err := c.ListTeamStats(ctx, nil); return err },
		"ListMembers":            func() error { _, err := c.ListMembers(ctx, nil); return err },
		"ListPlayerStats":        func() error { _, err := c.ListPlayerStats(ctx, nil); return err },
		"ListAwards":             func() error { _, err := c.ListAwards(ctx, nil); return err },
		"ListRecruits":           func() error { _, err := c.ListRecruits(ctx, nil); return err },
		"ListRecruitCommits":     func() error { _, err := c.ListRecruitCommits(ctx, nil); return err },
		"ListRecruitingClasses":  func() error { _, err := c.ListRecruitingClasses(ctx, nil); return err },
		"ListRosters":            func() error { _, err := c.ListRosters(ctx, nil); return err },
		"ListRosterSkills":       func() error { _, err := c.ListRosterSkills(ctx, nil); return err },
		"ListSyncRuns":           func() error { _, err := c.ListSyncRuns(ctx); return err },
		"ListSchoolGrades":       func() error { _, err := c.ListSchoolGrades(ctx, nil); return err },
		"ListPlayingStyleGrades": func() error { _, err := c.ListPlayingStyleGrades(ctx, nil); return err },
		"ListProPotentialGrades": func() error { _, err := c.ListProPotentialGrades(ctx, nil); return err },
		"ListHeismanWatch":       func() error { _, err := c.ListHeismanWatch(ctx, nil); return err },
		"ListAwardWatches":       func() error { _, err := c.ListAwardWatches(ctx, nil); return err },
		"ListAllAmericans":       func() error { _, err := c.ListAllAmericans(ctx, nil); return err },
		"ListLeagueHistory":      func() error { _, err := c.ListLeagueHistory(ctx, nil); return err },
	}
	if len(sched.Data) > 0 {
		g := sched.Data[0]
		calls["GetGame"] = func() error { _, err := c.GetGame(ctx, g.Key, nil); return err }
		calls["GetTeamSchedule"] = func() error { _, err := c.GetTeamSchedule(ctx, g.Home.TeamKey, nil); return err }
	}
	for name, call := range calls {
		t.Run(name, func(t *testing.T) {
			if err := call(); err != nil {
				t.Error(err)
			}
		})
	}
}
