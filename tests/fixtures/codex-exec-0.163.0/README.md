# codex exec 0.163.0 contract fixture

`success.jsonl` is a synthetic protocol fixture based on the official JSONL example at
https://developers.openai.com/codex/noninteractive and local `codex exec --help`
from codex-cli 0.163.0. it is not an authenticated live capture. intermediate
messages and a completed command exercise final-answer extraction; tests mutate
it to cover interrupted output, terminal errors, and nonzero exit. live acceptance
must still verify the installed cli and its model/authentication configuration.
