.PHONY: format test

format:
	black bin/checkpoint.py bin/worktree.py bin/abra bin/specialty.py docker/entrypoint.py triggers tests

test:
	python3 -m unittest discover -s tests -v
