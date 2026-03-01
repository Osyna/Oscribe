VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')
DIST    := dist

.PHONY: dist wheel checksums release clean

dist:
	git archive --format=tar.gz --prefix="Oscribe-$(VERSION)/" HEAD \
		-o "$(DIST)/oscribe-$(VERSION).tar.gz"

wheel:
	python -m build

checksums: dist wheel
	cd $(DIST) && sha256sum * > SHA256SUMS

release: checksums
	@echo "Release artifacts in $(DIST)/"
	@ls -lh $(DIST)/

clean:
	rm -rf $(DIST) build *.egg-info src/*.egg-info
