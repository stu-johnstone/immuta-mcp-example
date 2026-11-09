UV := uv
VENV := .venv
PY := $(VENV)/bin/python
SCRIPT := immuta_obo_mcp.py

.PHONY: check setup run shell clean

check:
	@command -v $(UV) >/dev/null || (echo "uv is not installed. Install it with: brew install uv"; exit 1)

setup: check
	$(UV) venv $(VENV)
	$(UV) pip install --python $(PY) -r requirements.txt

run:
	$(PY) $(SCRIPT)

shell: setup
	@echo "Run: source $(VENV)/bin/activate"

clean:
	rm -rf $(VENV)