.PHONY: format test

format:
	black bin/worktree.py bin/specialty.py tests

test:
	python3 -m unittest discover -s tests -v
