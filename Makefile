.DEFAULT_GOAL := help

PACKAGEDIR := dist

.PHONY: help init init-dev test test-smoke test-smoke-html test-html build upload upload-testpypi

help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  build               Build the package"
	@echo "  upload              Upload the package to the PyPi index"
	@echo "  upload-testpypi     Upload the package to the PyPi-test index"

build:
	-rm -rf $(PACKAGEDIR)/*
	python -m build

upload-testpypi:
	$(MAKE) build
	twine upload -r testpypi $(PACKAGEDIR)/* --verbose

upload:
	$(MAKE) build
	twine upload $(PACKAGEDIR)/* --verbose
