.PHONY: format test

format:
	black bin/check_formatter.py bin/durable_files.py bin/workflow.py bin/checkpoint.py bin/worktree.py bin/specialty.py tests

test:
	python3 -m unittest discover -s tests -v
