.PHONY: format test

format:
	black bin/worktree.py tests

test:
	python3 -m unittest discover -s tests -v
	node --check extensions/linear/core.mjs
	node --check extensions/linear/pi.mjs
	node --check extensions/linear/session.mjs
	node --check extensions/linear/auth.mjs
	node --check extensions/linear/setup.mjs
	node --check extensions/linear/managed.mjs
	node --check extensions/linear/diagnostics.mjs
	node --check extensions/linear/watch.mjs
	node --check bin/linear-watch
	node --check .pi/extensions/abra-linear/index.ts
	node --test tests/linear/*.test.mjs
