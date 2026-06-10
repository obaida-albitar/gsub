PREFIX ?= $(HOME)/.local
APP_ID = app.gsub
PYTHON ?= python3

all: install

install: install-pip install-desktop install-icon update-cache
	@echo "gsub installed. You can now launch it from the GNOME app grid."
	@echo "Run 'gsub' from the terminal."

install-pip:
	$(PYTHON) -m pip install -e .

install-desktop:
	install -d $(PREFIX)/share/applications
	install -m 644 data/$(APP_ID).desktop $(PREFIX)/share/applications/

install-icon:
	install -d $(PREFIX)/share/icons/hicolor/scalable/apps
	install -m 644 data/$(APP_ID).svg $(PREFIX)/share/icons/hicolor/scalable/apps/

update-cache:
	-gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor/ 2>/dev/null || true
	-update-desktop-database $(PREFIX)/share/applications/ 2>/dev/null || true

uninstall:
	$(PYTHON) -m pip uninstall -y gsub 2>/dev/null || true
	rm -f $(PREFIX)/share/applications/$(APP_ID).desktop
	rm -f $(PREFIX)/share/icons/hicolor/scalable/apps/$(APP_ID).svg
	-gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor/ 2>/dev/null || true
	-update-desktop-database $(PREFIX)/share/applications/ 2>/dev/null || true
	@echo "gsub uninstalled."

reinstall: uninstall install

.PHONY: all install install-pip install-desktop install-icon update-cache uninstall reinstall
