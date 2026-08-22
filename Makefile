PREFIX ?= $(HOME)/.local
APP_ID = io.github.obaidaalbitar.gsub
# App IDs used by earlier releases; their desktop files/icons are removed on
# install and uninstall so old entries don't linger in the app grid.
LEGACY_APP_IDS = app.gsub io.github.obaida-albitar.gsub
PYTHON ?= python3

all: install

install: install-pip build-resources clean-legacy install-desktop install-icon update-cache
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

clean-legacy:
	@for id in $(LEGACY_APP_IDS); do \
		rm -f $(PREFIX)/share/applications/$$id.desktop \
		      $(PREFIX)/share/icons/hicolor/scalable/apps/$$id.svg; \
	done

update-cache:
	-gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor/ 2>/dev/null || true
	-update-desktop-database $(PREFIX)/share/applications 2>/dev/null || true

uninstall:
	$(PYTHON) -m pip uninstall -y gsub 2>/dev/null || true
	@for id in $(APP_ID) $(LEGACY_APP_IDS); do \
		rm -f $(PREFIX)/share/applications/$$id.desktop \
		      $(PREFIX)/share/icons/hicolor/scalable/apps/$$id.svg; \
	done
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

# --- Flatpak ---------------------------------------------------------------
# One-time setup: org.gnome.Sdk//50 from flathub (org.gnome.Platform is pulled
# in as an SDK dependency). Use the native flatpak-builder when installed
# (e.g. sudo dnf install flatpak-builder), otherwise the Flathub-packaged one
# (flatpak install flathub org.flatpak.Builder).
#
# All builder state lives OUTSIDE the project tree: the download cache can
# contain extracted trees with absolute symlinks back into the host (e.g.
# var/run/host/...), which loops directory walkers like setuptools' package
# discovery and makes `pip install -e .` hang forever.
FLATPAK_BUILDER := $(shell command -v flatpak-builder 2>/dev/null)
ifeq ($(FLATPAK_BUILDER),)
FLATPAK_BUILDER = flatpak run org.flatpak.Builder
endif
FLATPAK_MANIFEST = io.github.obaidaalbitar.gsub.yml
FLATPAK_WORK = $(HOME)/.cache/gsub-flatpak
FLATPAK_BUILDDIR = $(FLATPAK_WORK)/build
FLATPAK_REPO = $(FLATPAK_WORK)/repo
FLATPAK_STATE = $(FLATPAK_WORK)/state
VERSION := $(shell sed -n "s/^  version: '\([^']*\)'.*/\1/p" meson.build)

# Build and install into the user Flatpak for quick local testing
# (flatpak run io.github.obaidaalbitar.gsub). Incremental: module build state
# is cached under $(FLATPAK_WORK)/state between runs.
flatpak:
	$(FLATPAK_BUILDER) --state-dir=$(FLATPAK_STATE) --user --install \
		--force-clean --install-deps-from=flathub \
		$(FLATPAK_BUILDDIR) $(FLATPAK_MANIFEST)

# Produce the single-file release bundle (same artifact as the CI flatpak job).
bundle:
	$(FLATPAK_BUILDER) --state-dir=$(FLATPAK_STATE) --force-clean \
		--repo=$(FLATPAK_REPO) --install-deps-from=flathub \
		$(FLATPAK_BUILDDIR) $(FLATPAK_MANIFEST)
	flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/ \
		$(FLATPAK_REPO) gsub-v$(VERSION).x86_64.flatpak $(APP_ID)
	@echo "Bundle written to gsub-v$(VERSION).x86_64.flatpak"

clean-flatpak:
	rm -rf $(FLATPAK_WORK) builddir-flatpak flatpak-repo .flatpak-builder

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache .coverage htmlcov \
		gsub.egg-info builddir gsub/gsub.gresource \
		gsub/__pycache__ gsub/*/__pycache__ tests/__pycache__ \
		data/blueprints/*.ui

reinstall: uninstall install

.PHONY: all install install-pip build-resources install-desktop install-icon \
	clean-legacy update-cache uninstall reinstall test test-fast coverage lint \
	fmt run clean flatpak bundle clean-flatpak
