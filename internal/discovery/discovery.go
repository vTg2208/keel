// Package discovery searches and reduces real Python payment executions.
package discovery

import (
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"slices"
)

var Mutations = map[string]string{
	"omit_outbox":           "durable_intent",
	"ack_before_commit":     "commit_before_ack",
	"unstable_provider_key": "single_provider_effect",
	"accept_stale_result":   "stale_result_fenced",
}

type Request struct {
	Protocol  int      `json:"protocol"`
	Seed      int64    `json:"seed"`
	Budget    int      `json:"budget"`
	Mutations []string `json:"mutations"`
}
type Violation struct {
	Invariant string `json:"invariant"`
	Expected  string `json:"expected"`
	Actual    string `json:"actual"`
}
type Replay struct {
	Violations []Violation       `json:"violations"`
	Steps      []json.RawMessage `json:"steps"`
	State      json.RawMessage   `json:"state"`
}
type Oracle func(actions []string, mutation string) (Replay, error)
type Finding struct {
	Mutation        string   `json:"mutation"`
	Status          string   `json:"status"`
	Attempted       int      `json:"attempted"`
	OriginalTrace   []string `json:"original_trace,omitempty"`
	MinimalTrace    []string `json:"minimal_trace,omitempty"`
	Original        *Replay  `json:"original,omitempty"`
	Minimal         *Replay  `json:"minimal,omitempty"`
	Baseline        *Replay  `json:"baseline,omitempty"`
	ReductionChecks int      `json:"reduction_checks"`
	OneMinimal      bool     `json:"one_minimal"`
}
type Report struct {
	Protocol    int       `json:"protocol"`
	Seed        int64     `json:"seed"`
	Budget      int       `json:"budget"`
	Killed      int       `json:"killed"`
	Total       int       `json:"total"`
	Evaluations int       `json:"evaluations"`
	Findings    []Finding `json:"findings"`
	Scope       string    `json:"scope"`
}

func Validate(r Request) error {
	if r.Protocol != 1 || r.Seed < 0 || r.Seed > 2147483647 || r.Budget < 1 || r.Budget > 32 || len(r.Mutations) < 1 || len(r.Mutations) > 4 {
		return errors.New("protocol 1, seed 0..2147483647, budget 1..32 and 1..4 mutations required")
	}
	seen := map[string]bool{}
	for _, name := range r.Mutations {
		if _, ok := Mutations[name]; !ok || seen[name] {
			return fmt.Errorf("unknown or repeated mutation: %s", name)
		}
		seen[name] = true
	}
	return nil
}

// Generate mixes recovery templates with seeded random schedules. It is bounded
// exploration, not an exhaustive search or replay of production event timing.
func Generate(seed int64, budget int) [][]string {
	rng := rand.New(rand.NewSource(seed))
	templates := [][]string{
		{"submit", "publish", "deliver", "commit", "ack", "duplicate", "deliver"},
		{"submit", "publish", "deliver", "crash", "expire_lease", "publish", "deliver", "late_response", "commit", "ack"},
		{"submit", "publish", "deliver", "lose_response", "commit", "ack", "publish", "deliver", "commit", "ack"},
	}
	all := []string{"submit", "publish", "deliver", "lose_response", "commit", "ack", "crash", "expire_lease", "late_response", "duplicate", "observe"}
	traces := make([][]string, 0, budget)
	for i := 0; i < budget; i++ {
		trace := []string{}
		if i%4 == 3 {
			trace = append(trace, "submit")
			for j := 0; j < 18; j++ {
				trace = append(trace, all[rng.Intn(len(all))])
			}
		} else {
			for _, event := range templates[i%4] {
				if rng.Intn(3) == 0 {
					trace = append(trace, "observe")
				}
				trace = append(trace, event)
				if event == "publish" && rng.Intn(2) == 0 {
					trace = append(trace, "duplicate")
				}
			}
		}
		traces = append(traces, trace)
	}
	return traces
}

func HasViolation(r Replay, invariant string) bool {
	for _, violation := range r.Violations {
		if violation.Invariant == invariant {
			return true
		}
	}
	return false
}

// Minimize repeatedly tries every single deletion. After a successful deletion
// it starts again, so termination proves 1-minimality for this exact invariant.
func Minimize(trace []string, mutation, invariant string, oracle Oracle) ([]string, Replay, int, error) {
	current := slices.Clone(trace)
	checks := 0
	for {
		changed := false
		for i := 0; i < len(current); i++ {
			candidate := append(append([]string{}, current[:i]...), current[i+1:]...)
			result, err := oracle(candidate, mutation)
			checks++
			if err != nil {
				return nil, Replay{}, checks, err
			}
			if HasViolation(result, invariant) {
				current = candidate
				changed = true
				break
			}
		}
		if !changed {
			break
		}
	}
	result, err := oracle(current, mutation)
	checks++
	if err == nil && !HasViolation(result, invariant) {
		err = errors.New("failure stopped reproducing during reduction")
	}
	return current, result, checks, err
}

func Run(request Request, oracle Oracle) (Report, error) {
	if err := Validate(request); err != nil {
		return Report{}, err
	}
	report := Report{Protocol: 1, Seed: request.Seed, Budget: request.Budget,
		Total: len(request.Mutations), Findings: []Finding{},
		Scope: "Real payment domain and provider; isolated SQLite; controlled in-memory broker and lease expiry. Not a distributed chaos test."}
	evaluate := func(actions []string, mutation string) (Replay, error) {
		report.Evaluations++
		if report.Evaluations > 2500 {
			return Replay{}, errors.New("replay evaluation limit reached")
		}
		return oracle(actions, mutation)
	}
	schedules := Generate(request.Seed, request.Budget)
	for _, mutation := range request.Mutations {
		finding := Finding{Mutation: mutation, Status: "survived"}
		invariant := Mutations[mutation]
		for _, trace := range schedules {
			finding.Attempted++
			faulty, err := evaluate(trace, mutation)
			if err != nil {
				return Report{}, err
			}
			if !HasViolation(faulty, invariant) {
				continue
			}
			baseline, err := evaluate(trace, "baseline")
			if err != nil {
				return Report{}, err
			}
			if len(baseline.Violations) != 0 {
				return Report{}, errors.New("correct implementation failed; campaign invalid")
			}
			reduced, minimal, checks, err := Minimize(trace, mutation, invariant, evaluate)
			if err != nil {
				return Report{}, err
			}
			baseline, err = evaluate(reduced, "baseline")
			if err != nil {
				return Report{}, err
			}
			if len(baseline.Violations) != 0 {
				return Report{}, errors.New("reduced baseline failed; campaign invalid")
			}
			finding.Status, finding.OneMinimal = "killed", true
			finding.OriginalTrace, finding.MinimalTrace = slices.Clone(trace), reduced
			finding.Original, finding.Minimal, finding.Baseline = &faulty, &minimal, &baseline
			finding.ReductionChecks = checks
			report.Killed++
			break
		}
		report.Findings = append(report.Findings, finding)
	}
	return report, nil
}
