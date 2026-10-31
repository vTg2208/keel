PYTHON ?= python3
.PHONY: init doctor install-tools bootstrap build deploy test lint up down demo teardown backup logs status jenkins
init doctor install-tools bootstrap build deploy test lint up down demo teardown backup logs status jenkins:
	$(PYTHON) ops.py $@ $(ARGS)

.PHONY: lab-build lab lab-test
lab-build:
	$(PYTHON) -m payops.lab build
lab:
	$(PYTHON) -m payops.lab serve $(ARGS)
lab-test:
	go test ./...
	go vet ./...
	$(PYTHON) -m pytest tests/test_lab_replay.py tests/test_lab_api.py -q
