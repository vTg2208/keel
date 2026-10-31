from uuid import uuid4

from locust import HttpUser, between, task


class PaymentUser(HttpUser):
    wait_time = between(0.2, 1)

    @task
    def create_and_replay(self):
        key = str(uuid4())
        body = {"amount_minor": 10000, "currency": "INR", "scenario": "success"}
        headers = {"Idempotency-Key": key}
        result = self.client.post("/payments", json=body, headers=headers)
        if result.status_code == 202:
            self.client.post("/payments", json=body, headers=headers, name="/payments replay")
            self.client.get(f"/payments/{result.json()['id']}", name="/payments/:id")
