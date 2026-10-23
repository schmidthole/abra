# codex exec 0.163.0 contract fixture

`success.jsonl` is a synthetic protocol fixture based on the official JSONL example at
https://developers.openai.com/codex/noninteractive and local `codex exec --help`
from codex-cli 0.163.0. it is not an authenticated live capture. intermediate
messages and a completed command exercise final-answer extraction; tests mutate
it to cover interrupted output, terminal errors, and nonzero exit. live acceptance
must still verify the installed cli and its model/authentication configuration.

`captured-fresh.jsonl` and `captured-resume.jsonl` are genuine codex-cli 0.163.0
stdout captured by the coordinator on 2026-10-23 through the integrated headless
runner. a fresh no-tool prompt supplied the harmless marker `copper-otter-731`;
the resumed prompt asked for the marker again and returned it on the same native
thread. only `thread_id` is normalized to the fixed fixture uuid; event shapes,
item ids, answer and usage fields are preserved. no credentials or private task
content are present. these captures establish fresh/resume protocol behavior;
they do not prove specialty tools, permissions, or native delegation.
