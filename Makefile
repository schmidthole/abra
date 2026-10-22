.PHONY: format test

format:
	black bin/worktree.py bin/abra bin/specialty.py triggers tests

test:
	python3 -m unittest discover -s tests -v
