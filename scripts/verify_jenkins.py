"""Run a healthy local pipeline followed by a deliberately broken release."""

import json
import time

import httpx

import ops


def build(client, broken):
    crumb = client.get("/crumbIssuer/api/json")
    crumb.raise_for_status()
    csrf = crumb.json()
    response = client.post(
        "/job/PayOps/buildWithParameters",
        data={"GIT_REPOSITORY": "", "BROKEN_RELEASE": str(broken).lower()},
        headers={csrf["crumbRequestField"]: csrf["crumb"]},
    )
    response.raise_for_status()
    queue = response.headers["Location"].replace("http://localhost:8080", "http://127.0.0.1:8080")
    deadline = time.monotonic() + 1200
    number = None
    while time.monotonic() < deadline:
        queued = client.get(queue + "api/json").json()
        if "executable" in queued:
            number = queued["executable"]["number"]
            break
        if queued.get("cancelled"):
            raise RuntimeError("Jenkins build was cancelled")
        time.sleep(2)
    if number is None:
        raise RuntimeError("Jenkins did not start the queued build")
    print(f"Jenkins build {number} started; broken_release={broken}", flush=True)
    previous = None
    while time.monotonic() < deadline:
        state = client.get(f"/job/PayOps/{number}/api/json").json()
        stages = client.get(f"/job/PayOps/{number}/wfapi/describe")
        if stages.status_code == 200:
            current = [(s["name"], s["status"]) for s in stages.json().get("stages", [])]
            if current != previous:
                print(json.dumps({"build": number, "stages": current}), flush=True)
                previous = current
        if not state["building"]:
            console = client.get(f"/job/PayOps/{number}/consoleText").text
            (ops.LOCAL / f"jenkins-build-{number}.log").write_text(console, encoding="utf-8")
            print(f"Jenkins build {number}: {state['result']}", flush=True)
            return number, state["result"], console
        time.sleep(5)
    raise RuntimeError(f"Jenkins build {number} did not finish within 20 minutes")


def main():
    creds = ops.credentials()
    with httpx.Client(
        base_url="http://127.0.0.1:8080", timeout=30, auth=("admin", creds["JENKINS_PASSWORD"])
    ) as client:
        deadline = time.monotonic() + 180
        while True:
            try:
                ready = client.get("/job/PayOps/api/json")
                if ready.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Jenkins or the PayOps job did not become ready")
            time.sleep(2)
        good_number, good_result, _ = build(client, False)
        assert good_result == "SUCCESS", f"Inspect .local/jenkins-build-{good_number}.log"
        bad_number, bad_result, console = build(client, True)
        assert bad_result == "FAILURE" and "restoring previous release" in console, console[-2000:]
        state = ops.release_history()
        current = json.loads(state["current"])
        images = {
            item["spec"]["template"]["spec"]["containers"][0]["image"]
            for item in current["items"]
            if item["kind"] == "Deployment"
            and item["metadata"]["name"] in {"api", "simulator", "worker", "publisher"}
        }
        assert images == {f"payops:build-{good_number}"}, images
        plugins = client.get(
            "/pluginManager/api/json", params={"tree": "plugins[shortName,version,active]"}
        ).json()
        (ops.LOCAL / "jenkins-plugin-versions.json").write_text(json.dumps(plugins, indent=2))
        result = {
            "healthy_build": good_number,
            "healthy_result": good_result,
            "broken_build": bad_number,
            "broken_result": bad_result,
            "restored_image": next(iter(images)),
        }
        (ops.LOCAL / "jenkins-results.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
