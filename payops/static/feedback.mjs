// Shared feedback for real requests. Elapsed time conveys activity, not progress.
const activeFeedback = new WeakMap();
export function startActivity(element, title, detail, slowDetail = detail) {
  activeFeedback.get(element)?.();
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const icon = make("span", "", "activity-ring");
  icon.setAttribute("aria-hidden", "true");
  const copy = make("div", "", "activity-copy");
  const note = make("p", detail);
  copy.append(make("strong", title), note);
  const elapsed = make("span", "0s elapsed", "activity-elapsed");
  elapsed.setAttribute("aria-hidden", "true");
  element.replaceChildren(icon, copy, elapsed);
  element.classList.add("activity-feedback");
  element.setAttribute("role", "status");
  element.hidden = false;
  const started = performance.now();
  let slow = false;
  const timer = setInterval(() => {
    const seconds = Math.floor((performance.now() - started) / 1000);
    elapsed.textContent = `${seconds}s elapsed`;
    if (seconds >= 8 && !slow) {
      slow = true;
      note.textContent = slowDetail;
    }
  }, 1000);
  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    if (activeFeedback.get(element) === stop) {
      element.hidden = true;
      activeFeedback.delete(element);
    }
  };
  activeFeedback.set(element, stop);
  return stop;
}

export function busyButton(button, busy, label) {
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  if (label) button.textContent = label;
}

// Preserve a useful visual structure while a genuinely empty surface loads.
export function skeleton(target, lines = 3) {
  target.replaceChildren();
  const wrapper = document.createElement("div");
  wrapper.className = "skeleton-stack";
  wrapper.setAttribute("aria-hidden", "true");
  for (let i = 0; i < lines; i++) {
    const line = document.createElement("span");
    line.className = "skeleton-line";
    wrapper.append(line);
  }
  target.append(wrapper);
}

document.addEventListener("visibilitychange", () => {
  document.documentElement.classList.toggle("motion-paused", document.hidden);
});
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) entry.target.classList.toggle("motion-offscreen", !entry.isIntersecting);
  }, { rootMargin: "30px" });
  document.querySelectorAll(".payment-journey, [id$='-progress'], #progress, #history, #ledger, #payment-form, #payment-detail").forEach((element) => observer.observe(element));
}
