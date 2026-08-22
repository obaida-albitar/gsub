PREFIX ?= $(HOME)/.local
APP_ID = io.github.obaidaalbitar.gsub
PYTHON ?= python3

all: install

install: install-pip build-resources install-desktop install-icon update-cache
	@echo "gsub installed. You can now launch it from the GNOME app grid."
	@echo "Run 'gsub' from the terminal."

install-pip:
	$(PYTHON) -m pip install -e .

build-resources:
	@command -v blueprint-compiler >/dev/null 2>&1 || { echo "blueprint-compiler not found; install it (e.g. blueprint-compiler) before building resources."; exit 1; }
	@command -v glib-compile-resources >/dev/null 2>&1 || { echo "glib-compile-resources not found; install gtk4 dev tools before building resources."; exit 1; }
	@for f in data/blueprints/*.blp; do \
		blueprint-compiler compile --output "$${f%.blp}.ui" "$$f"; \
	done
	glib-compile-resources --target gsub/gsub.gresource \
		--sourcedir data/blueprints --sourcedir data data/gsub.gresource.xml
	@echo "Built gsub/gsub.gresource"

install-desktop:
	install -d $(PREFIX)/share/applications
	install -m 644 data/$(APP_ID).desktop $(PREFIX)/share/applications/

install-icon:
	install -d $(PREFIX)/share/icons/hicolor/scalable/apps
	install -m 644 data/$(APP_ID).svg $(PREFIX)/share/icons/hicolor/scalable/apps/

update-cache:
	-gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor/ 2>/dev/null || true
	-update-desktop-database $(PREFIX)/share/applications 2>/dev/null || true

uninstall:
	$(PYTHON) -m pip uninstall -y gsub 2>/dev/null || true
	rm -f $(PREFIX)/share/applications/$(APP_ID).desktop
	rm -f $(PREFIX)/share/icons/hicolor/scalable/apps/$(APP_ID).svg
	-gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor/ 2>/dev/null || true
	-update-desktop-database $(PREFIX)/share/applications 2>/dev/null || true
	@echo "gsub uninstalled."

test:
	$(PYTHON) -m pytest

# Parallel test run (requires pytest-xdist from requirements-dev.txt).
test-fast:
	$(PYTHON) -m pytest -n auto

coverage:
	$(PYTHON) -m pytest --cov-report=html
	@echo "HTML coverage report written to htmlcov/index.html"

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

run:
	$(PYTHON) -m gsub.main

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache .coverage htmlcov \
		gsub.egg-info builddir gsub/gsub.gresource \
		gsub/__pycache__ gsub/*/__pycache__ tests/__pycache__ \
		data/blueprints/*.ui

reinstall: uninstall install

.PHONY: all install install-pip build-resources install-desktop install-icon \
	update-cache uninstall reinstall test test-fast coverage lint fmt run clean
