.PHONY: format test

format:
	black bin/worktree.py tests

test:
	python3 -m unittest discover -s tests -v
