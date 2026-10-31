package discovery

import (
	"errors"
	"reflect"
	"slices"
	"testing"
)

func TestSeededSchedulesAreBoundedAndReproducible(t *testing.T) {
	first := Generate(42, 16)
	if !reflect.DeepEqual(first, Generate(42, 16)) {
		t.Fatal("same seed changed schedules")
	}
	if reflect.DeepEqual(first, Generate(43, 16)) {
		t.Fatal("different seeds produced same schedules")
	}
	for _, trace := range first {
		if len(trace) > 32 {
			t.Fatal("unbounded trace")
		}
	}
}

func TestReductionRemovesNoiseAndPreservesTheSameInvariant(t *testing.T) {
	oracle := func(actions []string, _ string) (Replay, error) {
		if slices.Contains(actions, "submit") && slices.Contains(actions, "crash") {
			return Replay{Violations: []Violation{{Invariant: "durable_intent"}}}, nil
		}
		return Replay{Violations: []Violation{}}, nil
	}
	trace, _, _, err := Minimize([]string{"observe", "submit", "publish", "crash", "observe"}, "omit_outbox", "durable_intent", oracle)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(trace, []string{"submit", "crash"}) {
		t.Fatalf("not minimal: %v", trace)
	}
	for i := range trace {
		candidate := append(append([]string{}, trace[:i]...), trace[i+1:]...)
		result, _ := oracle(candidate, "omit_outbox")
		if HasViolation(result, "durable_intent") {
			t.Fatal("single deletion still fails")
		}
	}
}

func TestOracleErrorsCannotBecomeSurvivingMutants(t *testing.T) {
	_, err := Run(Request{Protocol: 1, Seed: 42, Budget: 1, Mutations: []string{"omit_outbox"}}, func([]string, string) (Replay, error) { return Replay{}, errors.New("bridge unavailable") })
	if err == nil {
		t.Fatal("swallowed oracle error")
	}
}

func TestBaselineFailureInvalidatesCampaign(t *testing.T) {
	_, err := Run(Request{Protocol: 1, Seed: 42, Budget: 1, Mutations: []string{"omit_outbox"}}, func([]string, string) (Replay, error) {
		return Replay{Violations: []Violation{{Invariant: "durable_intent"}}}, nil
	})
	if err == nil {
		t.Fatal("counted a baseline failure as a killed mutant")
	}
}

func TestNoFindingIsReportedHonestly(t *testing.T) {
	result, err := Run(Request{Protocol: 1, Seed: 42, Budget: 2, Mutations: []string{"omit_outbox"}}, func([]string, string) (Replay, error) { return Replay{Violations: []Violation{}}, nil })
	if err != nil {
		t.Fatal(err)
	}
	if result.Killed != 0 || result.Findings[0].Status != "survived" || result.Findings[0].Attempted != 2 {
		t.Fatalf("wrong report: %+v", result)
	}
}

func TestValidationRejectsUnknownOrUnboundedRequests(t *testing.T) {
	for _, request := range []Request{
		{Protocol: 2, Budget: 1, Mutations: []string{"omit_outbox"}},
		{Protocol: 1, Budget: 0, Mutations: []string{"omit_outbox"}},
		{Protocol: 1, Budget: 33, Mutations: []string{"omit_outbox"}},
		{Protocol: 1, Budget: 1, Mutations: []string{"shell"}},
		{Protocol: 1, Budget: 1, Mutations: []string{"omit_outbox", "omit_outbox"}},
	} {
		if Validate(request) == nil {
			t.Fatalf("accepted invalid request: %+v", request)
		}
	}
}
