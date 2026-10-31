# Payment motion and loading feedback

The user requested an animated payment feel and clear feedback during running work.
Implement directly in the existing HTML/CSS/JavaScript surfaces without new dependencies.

- Add a real-state payment journey: accepted, waiting, provider, result. Active work
  animates; successful/rejected/failed/unknown outcomes remain distinguishable. No fake
  percentages, settlement claims, timed success, or forced minimum loading duration.
- Initial ledger/detail/history skeletons, visible refresh activity, submission spinner
  and slow-request feedback, stale/paused update status, recovery after request errors.
- Lab campaign elapsed time, prominent in-progress state, saved-report loading,
  history refresh loading, and replay busy feedback. Never invent server phases.
- CSS transform/opacity motion with reduced-motion and hidden-tab handling; functional
  text remains available without animation. Avoid reanimating every polling update.
- Test status presentation first, then browser-test delayed success/error, ambiguous
  outcomes, paused updates, selection races, reduced motion and mobile layouts.
- Rebuild the application image, verify the real payment flow, and update demo media
  if the recorded interaction becomes materially different.
