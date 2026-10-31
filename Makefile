PYTHON ?= python3
.PHONY: init doctor install-tools bootstrap build deploy test lint up down demo teardown backup logs status jenkins
init doctor install-tools bootstrap build deploy test lint up down demo teardown backup logs status jenkins:
	$(PYTHON) ops.py $@ $(ARGS)
