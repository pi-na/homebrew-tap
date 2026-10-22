# claude-sessions

Browse and resume [Claude Code](https://claude.com/claude-code) sessions from
the terminal.

`claude --resume` only lists sessions whose working directory matches the one
you launched it from. Everything else is still on disk under
`~/.claude/projects/`, just invisible. This finds all of it.

## Install

```sh
brew install pi-na/tap/claude-sessions
```

## Use

```sh
claude-sessions          # every session, with its directory
claude-sessions .        # only the current directory
claude-sessions <dir>    # only that directory
```

Piping is supported: if stdout is not a terminal it prints a flat listing
instead of opening the UI, so it works in scripts and cron.

## Keys

| Key | Action |
| --- | --- |
| `j` `k` arrows | move |
| `n` `space` / `p` `b` | next / previous page |
| `g` `G` | first / last |
| `/` | live fuzzy search over directory, title and id |
| `esc` | leave the search, or clear it |
| `a` | (toggle) list all directories |
| `d` | only sessions from the highlighted row's directory |
| `enter` | focus view with the session's details |
| `enter` again | quit and print the resume command |
| `c` | copy that command to the clipboard |
| `h` `?` | help |
| `r` | readme: how session storage works |
| `q` | quit (from a sub-window, back to the table) |

## The focus view

Shows the directory, git branch, model, reasoning effort, permission mode,
Claude Code version, duration, message counts, token usage, tools used, files
touched, subagent count and the last 10 messages of the conversation.

The transcript is only fully parsed for the session you open, so the listing
stays fast even with hundreds of megabytes of history.

## How it works

Sessions are plain JSONL under `~/.claude/projects/<encoded-cwd>/<id>.jsonl`,
where the directory name is the absolute path with every non-alphanumeric
character replaced by `-`. That encoding is lossy, so this reads the `cwd`
field inside each file instead of trusting the folder name.

Timestamps in those files are UTC and are shown here in local time. The file
mtime is not a reliable "last used" signal because Claude Code touches it on
exit and when indexing, so ordering uses the last `timestamp` in the
transcript.

## Requirements

macOS, and the Python that Homebrew installs as a dependency. No third-party
Python packages.

## License

MIT
