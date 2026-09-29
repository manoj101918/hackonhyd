# Déjà Vu — common tasks. Windows without make: see "PowerShell equivalents" in README.md.
PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
endif

.PHONY: setup data seed seed-reset smoke dev backend frontend test build

setup:            ## create venv, install backend + frontend deps, create .env
	python -m venv .venv
	$(PY) -m pip install -q -e ".[dev]"
	cd frontend && npm ci
	@test -f .env || (cp .env.example .env && echo "created .env — add HINDSIGHT_API_KEY and GROQ_API_KEY")

data:             ## regenerate data/*.json (deterministic)
	$(PY) scripts/generate_data.py

seed:             ## create the Hindsight bank and retain the incident history (idempotent)
	$(PY) scripts/seed_memory.py

seed-reset:       ## delete the bank and seed from scratch
	$(PY) scripts/seed_memory.py --reset

smoke:            ## check Hindsight connectivity in a throwaway bank
	$(PY) scripts/smoke_memory.py

backend:          ## API on :8000
	$(PY) -m uvicorn dejavu.main:app --app-dir backend --port 8000 --reload

frontend:         ## UI on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

dev:              ## backend + frontend together
	$(MAKE) -j2 backend frontend

test:             ## backend unit tests + frontend type-check
	$(PY) -m pytest -q
	$(PY) scripts/generate_data.py --check
	cd frontend && npx tsc -b

build:            ## production build of the UI
	cd frontend && npm run build
