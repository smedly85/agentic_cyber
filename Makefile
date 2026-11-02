# Run from WSL/Linux with the pinned Docker images available.
# Host Python only orchestrates; compilation and candidate execution use Docker.
PYTHON ?= python3
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: all test
all: test

test:
	@output=$$(mktemp -d /tmp/linux-utilities-checks.XXXXXX) || exit 1; \
	echo "Validation logs: $$output"; \
	$(PYTHON) scripts/validate_linux_static.py --output "$$output/linux-static" && \
	$(PYTHON) scripts/validate_cross_language.py --output "$$output/cross-language"
