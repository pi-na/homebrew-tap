# claude-sessions

A TUI to browse and resume Claude Code sessions, distributed as a Homebrew tap.

This repository is **both the source and the tap**. That is deliberate: it keeps
distribution to a single repo and a single command for users.

```
claude-sessions.py            the whole program, one file
Formula/claude-sessions.rb    the Homebrew formula
tests/test_screen.py          screen-level tests
```

## Hard constraints

- **The GitHub repo must stay named `homebrew-tap`.** Homebrew resolves
  `brew install pi-na/tap/claude-sessions` to the repo `pi-na/homebrew-tap`.
  Renaming it breaks every installation. The local directory name is free.
- **Standard library only.** No runtime dependencies beyond Python itself.
  If you ever need a third party package, the formula has to switch to
  `virtualenv_install_with_resources` and every dependency must be pinned as a
  `resource` block, which is a much larger change.
- **macOS only** (`depends_on :macos`), because the clipboard uses `pbcopy`.
- **English only.** There is no i18n layer; all user-facing text is in English.

## Releasing

The formula points at a release tarball, so a code change is not live until a
new tag exists and the formula's `url` and `sha256` both move.

```sh
git tag v0.1.3 && git push && git push origin v0.1.3
gh release create v0.1.3 --title v0.1.3 --notes "..."
SHA=$(curl -sL https://github.com/pi-na/homebrew-tap/archive/refs/tags/v0.1.3.tar.gz | shasum -a 256 | cut -d' ' -f1)
# edit Formula/claude-sessions.rb: bump the version in url, replace sha256 with $SHA
git commit -am "claude-sessions 0.1.3" && git push
```

To verify an upgrade locally, pull the tap clone first or Homebrew keeps
building the old formula:

```sh
git -C "$(brew --repo pi-na/tap)" pull && brew upgrade claude-sessions
```

## Testing

```sh
python3 -m venv .venv && .venv/bin/pip install pyte     # test-only dependency
.venv/bin/python tests/test_data.py                     # data layer, against the real store
.venv/bin/python tests/test_screen.py                   # the UI, on a pty
CS_BIN=$(which claude-sessions) .venv/bin/python tests/test_screen.py   # the installed binary
```

`test_screen.py` spawns the program on a pty, feeds keystrokes, and asserts on
the screen as rendered by a terminal emulator. `test_data.py` checks the
invariants of the session store.

Neither suite may hardcode how many sessions exist. Claude Code deletes old
transcripts on its own schedule, so the total changes under you; read it off
the screen and compare against that.

**Do not assert on the raw pty byte stream.** ncurses only emits the diff
against the previous frame, so a string that is plainly visible on screen often
never appears contiguously in the bytes. Typing `klee` into the search emits
`k`, then `l`, then `e` — never `fuzzy: klee`. Every such assertion will give a
false negative. That is why `pyte` is a dependency of the tests.

Before shipping a release, also run `brew audit --strict pi-na/tap/claude-sessions`.

## How the data works

Sessions are JSONL files under `~/.claude/projects/<encoded-cwd>/<id>.jsonl`,
where the directory name is the absolute cwd with every non-alphanumeric
character replaced by `-`.

- That encoding is **lossy**, so the folder name cannot be decoded back into a
  path.
- **`cwd` moves within a session.** Every event carries its own, and it changes
  whenever a tool `cd`s, so the first one is not necessarily where the session
  started. 22 of 47 transcripts in one real store recorded more than one, and
  two of them reported a first `cwd` that was not the launch directory at all.
  Getting this wrong is not cosmetic: the printed `cd ... && claude --resume`
  lands in a directory where Claude Code cannot find the session, and it fails
  silently. `Session._launch_dir()` resolves it by scanning every recorded
  `cwd` and taking the one that encodes to the project folder the file lives
  in. `tests/test_data.py` guards that invariant.
- **Timestamps are UTC**; the UI converts to local time.
- **The file mtime lies** — Claude Code touches it on exit and when indexing.
  Ordering by "last used" must use the last `timestamp` in the transcript.
- Subdirectories named `<id>/subagents/` hold subagent transcripts. They are
  not resumable sessions and must never appear in the listing.
- The session description prefers `customTitle` (set by `/rename`), then
  `aiTitle` (Claude Code's own auto-title), then the first user prompt.

## Design notes worth preserving

- **The listing scan is cheap, the detail parse is lazy.** Loading every
  session only reads the head and tail of each file and counts user messages
  with a byte count, no JSON parsing. `Session.details()` parses the whole
  transcript and runs only for the session you actually open. Keep that split;
  some transcripts are over 10 MB.
- **`ESCDELAY` must stay at 25 ms.** Otherwise ncurses waits a full second
  after `esc` to see whether an escape sequence follows, and leaving the search
  feels broken.
- **Table height is computed, never hardcoded:**
  `page = h - HEADER_ROWS - FOOTER_ROWS - AIR`. `AIR` is the blank gap above
  the footer and is intentional.
- **The footer picks the widest hint string that fits.** When adding a key,
  add it to every tier of that tuple, not just the first, or it disappears on
  narrow terminals.
- Running without a tty prints a flat listing instead of opening the UI, so
  piping and cron keep working. Do not break that path.
