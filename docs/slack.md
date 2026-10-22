# slack trigger

`triggers/slack.py` connects a slack workspace to an abra instance through the
shared trigger runtime ([triggers.md](triggers.md)). it uses socket mode, so the
host needs outbound https only and no public endpoint.

## behavior

- tagging the bot (`@abra ...`) in a channel starts a work item. the tagged
  message is the session's first message; the runtime posts its fixed
  announcement in that message's thread. tagging inside an existing thread starts
  a session keyed on that thread.
- the conversation key is `slack:<channel>:<thread ts>`; a thread is one session.
- every later reply in that thread, from anybody in the channel, is added to the
  session. top-level messages without a tag are ignored.
- a reply that tags the bot is handled once, through its `app_mention` event.
- direct messages and group dms are ignored. a group dm mention that slack does
  not label with a channel type cannot be told apart from a private channel
  without extra scopes, so do not add the bot to group dms.
- result text is escaped (`&`, `<`, `>`), so output cannot trigger `@channel`,
  `@here`, user mentions, or labeled links.
- the bot's own posts, other bots and apps, edits, deletes, joins, and other
  message subtypes are ignored (`thread_broadcast` and `file_share` replies count
  as ordinary replies; only their text is used). `<@BOTID>` in text becomes
  `@<name>`. mentions are matched by the bot user id from `auth.test`, never by
  display name.
- reactions on each message show its state: ⏳ queued, 👀 running, ✅ done,
  ❌ failed. each new state replaces the previous marker.
- results are posted in the thread, split into posts of at most 3900 characters
  at newlines where possible.
- queue and batch only: there is no steering, interrupt, or stop command.

## setup

1. create the app at <https://api.slack.com/apps> with "from an app manifest",
   pasting `triggers/slack-manifest.yml` after replacing `abra` with your bot name.
   the bot scopes are the minimum the adapter needs:

   | scope | used for |
   | --- | --- |
   | `app_mentions:read` | `app_mention` events that start a work item |
   | `channels:history` | thread replies and history in public channels |
   | `groups:history` | thread replies and history in private channels |
   | `chat:write` | announcement, result, and error posts |
   | `reactions:write` | state markers |

2. under basic information, generate an app-level token with only the
   `connections:write` scope (socket mode). this is `SLACK_APP_TOKEN` (`xapp-`).
3. install the app to the workspace and copy the bot user oauth token. this is
   `SLACK_BOT_TOKEN` (`xoxb-`).
4. keep both tokens in your secret store and inject them as environment
   variables at launch. never put them in the repo, a `.env` file in the repo,
   or command-line arguments.
5. invite the bot to each channel it should serve (`/invite @abra`). it only sees
   channels it is a member of.
6. install the adapter dependency in a virtualenv outside the abra checkout and
   instance roots (base abra stays stdlib):

   ```sh
   python3 -m venv ~/.venvs/abra-slack
   ~/.venvs/abra-slack/bin/pip install -r triggers/requirements-slack.txt
   ```

7. run it against an abra root, base or specialty:

   ```sh
   SLACK_BOT_TOKEN=... SLACK_APP_TOKEN=... \
     ~/.venvs/abra-slack/bin/python triggers/slack.py --root /path/to/abra-instance --name abra
   ```

   a missing or malformed token exits 1 naming the variable. sigint or sigterm
   closes the socket, lets running turns finish, and keeps queued messages stored
   for the next start.

## many instances

each process serves one slack app against one root. run several in parallel by
giving each its own slack app (tokens), root, and `--name`, for example a base
instance as `abra` and a specialty instance as `helper`. two slack processes on
the same root are refused by the runtime's store lock. `ABRA_ARCHIVE_DAYS` and
`ABRA_TRIGGER_WORKERS` apply as for any adapter.

## security

- anybody who can post in a channel the bot is in can start a work item, and
  anybody in the channel can add turns to an existing thread. invite the bot only
  to channels whose members may direct that abra instance. bin/abra treats every
  message as untrusted input from its sender, never operator authority.
- tokens are read from the environment only; they are never logged, printed, or
  stored. slack api failures are logged by error code only, never message text.
  library log lines are filtered to mask token-like values and drop tracebacks.
- the runtime store and temp files under `<root>/data/triggers/` hold message text
  in plaintext with mode 0600. keep the root on an encrypted volume on a
  single-tenant host or container.
