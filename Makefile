PYTHON ?= $(if $(wildcard /opt/homebrew/bin/python3.13),/opt/homebrew/bin/python3.13,python3)
export PYTHONDONTWRITEBYTECODE := 1
.PHONY: check test lint build release release-push deploy
check: lint test
lint:
	@$(PYTHON) tools/check.py
test:
	@$(PYTHON) -m unittest discover -s tests -v
build:
	@$(PYTHON) tools/build.py
release:
	@sh tools/release.sh
release-push:
	@$(PYTHON) tools/release_push.py
deploy:
	@$(PYTHON) tools/deploy.py
