# Keel demo recordings

Two real browser recordings made on 31 October 2026, Asia/Calcutta. They use synthetic
payment data and contain no credentials. Caption bars are recording overlays, not
changes to the application. There is no audio track.

| Recording | Duration | Demonstrated behavior |
|---|---|---|
| [Payment recovery](keel-payment-recovery.mp4) | 64 seconds | Animated payment journey, provider retry, API idempotency, actual Compose worker outage, pending work, recovery with one processing attempt |
| [Failure discovery](keel-failure-discovery.mp4) | 65 seconds | Running screen with elapsed time, seed 42 / budget 4, four faults detected, original/reduced execution, provider effects, passing baseline, replay, regression export and persistent history |

The GIF files are short animated excerpts for GitHub Markdown compatibility. The MP4
files contain complete recordings, encoded as H.264 with a front-loaded playback index.
Poster JPGs are actual screenshots. The source WebM recordings and execution checks
remain under ignored `.local/demo-recordings/`.

## Re-record

Requires Node, Playwright with Chromium and its video recorder, the project's Python
environment, and a full FFmpeg build with libx264 and GIF filters.

1. Start the full Compose application and its worker on `http://127.0.0.1:8000`.
2. Build the lab controller and start `python -m payops.lab serve --port 8010`.
3. Make Playwright available through `NODE_PATH`, or set `PLAYWRIGHT_MODULE` to the
   installed module path. Then run `node scripts/record_demos.cjs` from the repository.
4. Run `python scripts/render_demos.py --ffmpeg /path/to/ffmpeg`.

Override the application URLs through `PAYMENT_URL` and `LAB_URL` if necessary.
`node scripts/record_demos.cjs --only payments` or `--only discovery` records one video.
The recorder stops the Compose worker during the payment demo and restarts it in a
`finally` block if recording fails. Use an isolated local lab, not shared infrastructure.

Recording assertions verify all four discovered faults, successful baseline/replay,
the downloaded regression test, API `202` on creation, `200` and the same payment ID
on idempotent replay, then success with one attempt after the worker outage. Browser
runtime errors fail the recording. Conversion fully decodes each MP4 to check integrity.
