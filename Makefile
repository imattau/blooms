DOMAIN = blooms-in-gnome
POT = locale/$(DOMAIN).pot
PO_DIR = locale

.PHONY: extract init update compile

extract:
	pybabel extract \
		--project="Blooms in Gnome" \
		--version="0.1.0" \
		--copyright="Blooms in Gnome contributors" \
		--license="LGPL-3.0-or-later" \
		--msgid-bugs-address="https://github.com/anomalyco/blooms" \
		--output-file=$(POT) \
		--keywords="_" \
		blooms_in_gnome/

init: extract
	pybabel init --input-file=$(POT) --output-dir=$(PO_DIR) --domain=$(DOMAIN) --locale=$(LANG)

update:
	pybabel update --input-file=$(POT) --output-dir=$(PO_DIR) --domain=$(DOMAIN)

compile:
	pybabel compile --directory=$(PO_DIR) --domain=$(DOMAIN)

install-locale: compile
	@mkdir -p ~/.local/share/locale
	@for po in $(PO_DIR)/*/LC_MESSAGES/$(DOMAIN).po; do \
		lang=$$(echo $$po | sed 's|.*/\([^/]*\)/LC_MESSAGES/.*|\1|'); \
		mkdir -p ~/.local/share/locale/$$lang/LC_MESSAGES; \
		cp "$${po%.po}.mo" ~/.local/share/locale/$$lang/LC_MESSAGES/; \
		echo "installed $$lang locale"; \
	done
