# Payment motion and loading feedback

Verified 31 October 2026, Asia/Calcutta. The feature retains the existing payment
API, currency handling and idempotency behavior. No frontend runtime dependency was added.

## What changed

- A payment journey follows actual submission, waiting, provider and outcome states.
  Active states have restrained motion; terminal/review states stop active movement.
- Receipt summaries carry their own state feedback while the drawer is open.
- Skeletons and busy feedback cover initial ledger/catalog/history/detail loads.
- Submission, campaign and replay feedback shows elapsed time and slow-request copy.
  Elapsed time is not a progress percentage or estimate of completion.
- Automatic refresh keeps rows visible and does not repeatedly insert a loading panel.
- Paused or unavailable live updates are labeled. Unconfirmed submissions preserve
  their idempotency keys; conflicts and validation failures are distinguished.
- Older ledger/receipt responses cannot replace a newer confirmed payment snapshot.
- Reduced-motion and hidden/off-screen states suspend decorative movement without
  removing functional text. No artificial loading delay is used in the application.

## Executed checks

| Check | Result |
|---|---|
| Node helpers | 7 passed, including observed-state presentation and stale snapshot protection |
| FastAPI frontend/static asset tests | 2 passed, including the new shared CSS and module |
| Ruff | Passed across the repository |
| Desktop browser | 1440x1000; initial loading, detail fetch, submission, duplicate-click prevention, success, retry and review states |
| Error behavior | Failed refresh retains rows; ambiguous submission retains key; conflict shown distinctly; failed campaign/saved-report loading clear busy state |
| Selection races | An old payment request cannot clear another payment's loader; old receipt data cannot rewind a newer successful state |
| Replay races | Feedback clears even when a concurrent saved-report request fails or the finding changes; concurrent replay/campaign actions disabled |
| Mobile | 390x844 payment and campaign surfaces; no horizontal overflow |
| Reduced motion | Tested on an active pending payment: current-step pulse disabled, status text retained |
| Slow requests | Browser virtual clock advances beyond 8 seconds; slow copy and elapsed time update; finishing stops the timer; repeated cleanup cannot dismiss a newer operation |
| App runtime errors | None in the controlled browser flows; deliberate failed network responses are expected test conditions |
| Docker | Updated application image built and API recreated successfully; real UI recordings exercised the rebuilt app |
| Real application | New request accepted; same-key replay returned same payment; actual worker outage retained pending work; restart completed with one processing attempt |
| Real workbench | Seed 42 / budget 4 exposed four faults; baseline comparison, replay, regression export and saved-run reload succeeded |

The browser plugin is not available; checks use the already bundled Playwright and
Chromium. The repeatable browser script is `scripts/verify_frontend.cjs`. It uses
controlled API responses to expose timing and network failures; it does not change
the application. Screenshots are ignored under `.local/frontend-qa/`.

An independent read-only review identified replay-cleanup and stale-response races.
Both have regression checks; the replay check was observed failing before its fix,
and the snapshot guard was implemented after its failing Node check.

## Demonstration and limits

The README's MP4/GIF demos were re-recorded against the real application with motion
enabled. Recording captions are temporary browser overlays. MP4 conversion checks
decode integrity and Chromium playback. The worker is restored after the outage.

Backend domain, broker and Go discovery code did not change, so their full suites
were not repeated for this UI change. No real-device or Safari/Firefox verification
was performed. The upstream Starlette/HTTPX test-client deprecation warning remains.
