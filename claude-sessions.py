#!/usr/bin/env python3
"""claude-sessions - browse and resume Claude Code sessions.

Starts listing every session. Pass a directory (or ".") to scope it.

Interactive when stdout is a terminal; otherwise prints a flat listing
(for pipes, scripts and cron).
"""
import curses
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import textwrap

STORE = os.path.expanduser("~/.claude/projects")
# Vertical layout of the table, in rows:
HEADER_ROWS = 5   # title bar, scope, count, air, column header
FOOTER_ROWS = 3   # session id, resume command, status bar
AIR = 2           # breathing room between the last row and the footer
HEAD_LINES = 400
TAIL_LINES = 200
TAIL_MSGS = 10    # messages kept for the focus view


# ---------------------------------------------------------------- data

class Session:
    __slots__ = ("sid", "path", "cwd", "real", "last", "title", "nmsg",
                 "size", "_detail")

    def __init__(self, path):
        self.path = path
        self.sid = os.path.basename(path)[:-6]
        self.size = os.path.getsize(path)
        self.cwd = self.real = self.last = self.title = None
        self.nmsg = 0
        self._detail = None
        self._scan()

    def _scan(self):
        with open(self.path, "rb") as fh:
            blob = fh.read()
        # user messages: cheap count, no JSON parsing
        self.nmsg = blob.count(b'"type":"user"')
        self.cwd = self._launch_dir(blob)
        self.real = os.path.realpath(self.cwd) if self.cwd else None
        lines = blob.splitlines()
        first = None
        ai = None
        for raw in lines[:HEAD_LINES]:
            d = _loads(raw)
            if not d:
                continue
            if d.get("customTitle"):
                self.title = d["customTitle"]
            if d.get("aiTitle"):
                ai = d["aiTitle"]
            if not first and d.get("type") == "user":
                t = _text(d.get("message", {}).get("content"))
                if t and not t.startswith("<") and not t.startswith("Caveat:"):
                    first = t
        # the last timestamp and a late /rename live at the end of the file
        for raw in lines[-TAIL_LINES:]:
            d = _loads(raw)
            if not d:
                continue
            if d.get("timestamp"):
                self.last = d["timestamp"]
            if d.get("customTitle"):
                self.title = d["customTitle"]
            if d.get("aiTitle"):
                ai = d["aiTitle"]
        # /rename beats Claude's own auto-title, which beats the first prompt
        self.title = self.title or ai or first or "(no text)"

    def _launch_dir(self, blob):
        """The directory the session was started in.

        Every event carries its own 'cwd', and it moves whenever a tool cds,
        so the first one is not necessarily where the session began. The
        authoritative answer is the project folder this file lives in, so pick
        the recorded cwd that encodes to that folder name.
        """
        folder = os.path.basename(os.path.dirname(self.path))
        fallback = None
        for mo in re.finditer(rb'"cwd":"((?:[^"\\]|\\.)*)"', blob):
            try:
                c = json.loads(b'"' + mo.group(1) + b'"')
            except Exception:
                continue
            if slug(c) == folder:
                return c
            if fallback is None:
                fallback = c
        return fallback

    @property
    def when(self):
        if not self.last:
            return "?"
        d = datetime.datetime.fromisoformat(self.last.replace("Z", "+00:00"))
        return d.astimezone().strftime("%Y-%m-%d %H:%M")

    @property
    def cmd(self):
        return f'cd "{self.cwd}" && claude --resume {self.sid}'


    def details(self):
        """Full parse of the transcript. Lazy: only for the session you open."""
        if self._detail is not None:
            return self._detail
        import collections
        d = {"tools": collections.Counter(), "files": set(), "nass": 0,
             "first_ts": None, "branch": None, "version": None, "model": None,
             "effort": None, "perm": None, "ai": None, "last_prompt": None,
             "first_prompt": None, "tok_out": 0, "tok_cache": 0, "tok_in": 0,
             "msgs": collections.deque(maxlen=TAIL_MSGS)}
        with open(self.path, errors="replace") as fh:
            for line in fh:
                e = _loads(line)
                if not e:
                    continue
                if e.get("timestamp") and not d["first_ts"]:
                    d["first_ts"] = e["timestamp"]
                for src, key in (("gitBranch", "branch"), ("version", "version"),
                                 ("effort", "effort"), ("permissionMode", "perm"),
                                 ("aiTitle", "ai")):
                    if e.get(src) and (key != "branch" or e[src] != "HEAD"):
                        d[key] = e[src]
                if e.get("type") == "last-prompt" and e.get("lastPrompt"):
                    d["last_prompt"] = str(e["lastPrompt"])
                if e.get("type") == "file-history-snapshot":
                    snap = e.get("snapshot") or {}
                    d["files"].update(snap.get("trackedFileBackups", {}))
                m = e.get("message") or {}
                if e.get("type") == "assistant":
                    d["nass"] += 1
                    if m.get("model"):
                        d["model"] = m["model"]
                u = m.get("usage") or {}
                d["tok_out"] += u.get("output_tokens", 0) or 0
                d["tok_in"] += u.get("input_tokens", 0) or 0
                d["tok_cache"] += u.get("cache_read_input_tokens", 0) or 0
                c = m.get("content")
                if isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "tool_use":
                            d["tools"][x.get("name")] += 1
                if e.get("type") in ("user", "assistant"):
                    t = _text(c)
                    if t and not t.startswith("<") and not t.startswith("Caveat:"):
                        if e["type"] == "user" and not d["first_prompt"]:
                            d["first_prompt"] = t
                        d["msgs"].append((e.get("timestamp"), e["type"], t))
        d["subagents"] = len(glob.glob(os.path.join(
            self.path[:-6], "subagents", "*.jsonl")))
        self._detail = d
        return d


def _loads(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def _text(c):
    if isinstance(c, str):
        return c.strip().replace("\n", " ")
    if isinstance(c, list):
        parts = [x.get("text", "") for x in c
                 if isinstance(x, dict) and x.get("type") == "text"]
        return " ".join(parts).strip().replace("\n", " ")
    return ""


def fuzzy(q, text):
    """Score q as a subsequence of text (fzf style). None means no match.

    Rewards consecutive characters and word starts; penalises long gaps
    and very long haystacks.
    """
    t = text.lower()
    score = i = 0
    prev = -2
    streak = 0
    for ch in q:
        j = t.find(ch, i)
        if j < 0:
            return None
        if j == prev + 1:
            streak += 1
            score += 8 + streak * 4
        else:
            streak = 0
            score -= min(j - i, 12)
        if j == 0 or not t[j - 1].isalnum():
            score += 10
        prev = j
        i = j + 1
    return score - len(t) // 40


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def span(a, b):
    if not a or not b:
        return "?"
    fmt = lambda t: datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    secs = int((fmt(b) - fmt(a)).total_seconds())
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h {secs % 3600 // 60:02d}m"


def slug(path):
    """Claude Code encodes the cwd replacing every non-alphanumeric with '-'."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def encode(path):
    return slug(os.path.realpath(os.path.expanduser(path)))


def load(target):
    if target is None:
        files = glob.glob(os.path.join(STORE, "*", "*.jsonl"))
    else:
        files = glob.glob(os.path.join(STORE, encode(target), "*.jsonl"))
    out = []
    for f in files:
        try:
            out.append(Session(f))
        except Exception:
            pass
    out.sort(key=lambda s: s.last or "", reverse=True)
    return out


# ---------------------------------------------------------------- copy

HELP = """\
KEYS

  NAVIGATION
    j  down      move one row down
    k  up        move one row up
    n  space     next page
    p  b         previous page
    g            first session
    G            last session

  SCOPE AND SEARCH
    a            (toggle) list all
    d            show only sessions from the highlighted row's directory
    /            live fuzzy search over directory + title + id
                 (several words = all must match; enter keeps the result,
                  esc leaves and discards it, up/down move without exiting)
    esc          clear the current search

  ACTIONS
    enter        open the focus view with the session's details;
                 press enter again there to quit and print the resume command
    c            copy that command to the clipboard (pbcopy)

  WINDOWS
    h  ?         this help
    r            readme: how session storage works
    q            quit  (from h/r it returns to the table)
"""

README = """\
HOW CLAUDE CODE STORES SESSIONS

  There is no database. Everything is plain text under:

      ~/.claude/projects/

  One subdirectory per project, one .jsonl file per session:

      ~/.claude/projects/-Users-you-code-project/
          7ddce3b2-....jsonl              <- resumable session
          7ddce3b2-.../subagents/*.jsonl  <- subagents, NOT resumable

  The subdirectory name is the absolute cwd with every non-alphanumeric
  character replaced by '-'. That is lossy: two different directories can
  collapse into the same folder, which is why this program reads the 'cwd'
  field inside each file instead of trusting the folder name.

FORMAT

  Every line is one JSON event. The fields that matter:

      cwd           the session's real directory
      timestamp     IN UTC (shown here converted to local time)
      type          'user' / 'assistant' / 'summary' / ...
      customTitle   the name you set with /rename

TWO TRAPS

  1. The file mtime lies: Claude touches it on exit and when indexing.
     To sort by real usage you must read the last 'timestamp'.

  2. 'claude --resume' only lists sessions whose cwd matches the directory
     you launched it from. The rest did not disappear, they are right here.
     That is what the 'a' key is for.

RETENTION

  Sessions are deleted automatically according to 'cleanupPeriodDays'
  (default: 30 days, based on mtime). To keep them, in
  ~/.claude/settings.json:

      { "cleanupPeriodDays": 365 }

IF A MESSAGE IS MISSING

  ~/.claude/history.jsonl keeps every prompt you have typed, with its
  project. If a prompt is there but not in the transcript, it was lost on
  exit; if it is in neither, it was never sent.
"""


# ---------------------------------------------------------------- tui

class App:
    def __init__(self, scr, target):
        self.scr = scr
        self.target = target          # None = every directory
        self.home = target
        self.view = "list"            # list | help | readme
        self.sel = 0
        self.top = 0
        self.scroll = 0
        self.filter = ""
        self.msg = ""
        self.all = load(None)
        self.refresh_rows()

    # -- data

    def refresh_rows(self):
        if self.target is None:
            rows = self.all
        else:
            want = os.path.realpath(os.path.expanduser(self.target))
            rows = [s for s in self.all if s.real == want]
        if self.filter:
            # every token must match; ties keep the base order (recency)
            # because sort() is stable
            scored = []
            for s in rows:
                hay = f"{s.cwd or ''} {s.title} {s.sid}"
                total = 0
                for tok in self.filter.lower().split():
                    sc = fuzzy(tok, hay)
                    if sc is None:
                        break
                    total += sc
                else:
                    scored.append((total, s))
            scored.sort(key=lambda p: -p[0])
            rows = [s for _, s in scored]
        self.rows = rows
        self.sel = max(0, min(self.sel, len(rows) - 1))
        self.top = min(self.top, max(0, len(rows) - 1))

    @property
    def page(self):
        """Visible rows: as many as the window fits, minus the air."""
        h, _ = self.scr.getmaxyx()
        return max(1, h - HEADER_ROWS - FOOTER_ROWS - AIR)

    # -- drawing

    def put(self, y, x, s, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                self.scr.addnstr(y, x, s, w - x - 1, attr)
            except curses.error:
                pass

    def draw(self):
        self.scr.erase()
        if self.view == "list":
            self.draw_list()
        elif self.view == "detail":
            self.draw_detail()
        else:
            self.draw_text(HELP if self.view == "help" else README,
                           "HELP" if self.view == "help" else "README")
        self.scr.refresh()

    def draw_list(self):
        h, w = self.scr.getmaxyx()
        scope = "ALL DIRECTORIES" if self.target is None else self.target
        self.put(0, 0, " claude-sessions ".ljust(w - 1),
                 curses.A_REVERSE | curses.A_BOLD)
        self.put(1, 1, scope, curses.A_BOLD)
        sub = f"{len(self.rows)} session(s) - most recent first"
        if self.filter:
            sub += f"   fuzzy: /{self.filter}"
        self.put(2, 1, sub, curses.A_DIM)

        wide = self.target is None and w > 96
        hdr = f'{"":2}{"LAST USED":17}{"MSGS":>5}{"MB":>7}   '
        hdr += f'{"DIRECTORY":34}' if wide else ""
        hdr += "SESSION"
        self.put(4, 1, hdr, curses.A_UNDERLINE | curses.A_BOLD)

        page = self.page
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + page:
            self.top = self.sel - page + 1

        for i in range(page):
            idx = self.top + i
            if idx >= len(self.rows):
                break
            s = self.rows[idx]
            cur = idx == self.sel
            line = f'{">" if cur else " ":2}{s.when:17}{s.nmsg:>5}{s.size / 1048576:>7.1f}   '
            if wide:
                d = (s.cwd or "?").replace(os.path.expanduser("~"), "~")
                line += f"{d[-33:]:34}"
            line += s.title
            self.put(5 + i, 1, line.ljust(w - 2),
                     curses.A_REVERSE if cur else 0)

        if not self.rows:
            self.put(5, 1, "no sessions match this search", curses.A_DIM)

        pages = max(1, (len(self.rows) + page - 1) // page)
        now = self.top // page + 1 if self.rows else 1
        if self.rows:
            s = self.rows[self.sel]
            self.put(h - 3, 1, s.sid, curses.A_BOLD)
            self.put(h - 2, 1, s.cmd.replace(os.path.expanduser("~"), "~"),
                     curses.A_DIM)
        prefix = f" page {now}/{pages}   "
        hints = ("j/k move - n/p page - enter details - c copy - "
                 "a (toggle) list all - d this dir - / fuzzy - h help - "
                 "r readme - q quit",
                 "j/k - n/p - enter - c copy - a (toggle) list all - d dir - "
                 "/ fuzzy - h help - q quit",
                 "j/k - enter - a (toggle) list all - d dir - / fuzzy - q quit",
                 "j/k - enter - a list all - d dir - / fuzzy - q quit",
                 "h help - q quit")
        bar = prefix + next((x for x in hints if len(prefix) + len(x) + 2 <= w),
                            hints[-1])
        if self.msg:
            bar = f" {self.msg} "
        self.put(h - 1, 0, bar.ljust(w - 1), curses.A_REVERSE)

    def detail_lines(self, s, w):
        """(text, attr) pairs for the focus view."""
        d = s.details()
        B, D, U = curses.A_BOLD, curses.A_DIM, curses.A_UNDERLINE
        home = os.path.expanduser("~")
        started = "?"
        if d["first_ts"]:
            started = datetime.datetime.fromisoformat(
                d["first_ts"].replace("Z", "+00:00")
            ).astimezone().strftime("%Y-%m-%d %H:%M")
        L = [(s.title, B), (s.sid, D), ("", 0)]

        def pair(k1, v1, k2, v2):
            L.append((f"  {k1:<11}{str(v1):<30}{k2:<12}{v2}", 0))

        pair("DIRECTORY", (s.cwd or "?").replace(home, "~"),
             "BRANCH", d["branch"] or "-")
        pair("STARTED", started, "MODEL", d["model"] or "-")
        pair("LAST USED", s.when, "EFFORT", d["effort"] or "-")
        pair("DURATION", span(d["first_ts"], s.last), "PERMISSION",
             d["perm"] or "-")
        pair("MESSAGES", f'{s.nmsg} you / {d["nass"]} claude',
             "CLAUDE CODE", d["version"] or "-")
        pair("SIZE", f"{s.size / 1048576:.1f} MB", "SUBAGENTS",
             d["subagents"] or "-")
        pair("TOKENS", f'out {human(d["tok_out"])}', "CACHE READ",
             human(d["tok_cache"]))

        def block(label, body, limit=3):
            L.append(("", 0))
            L.append((f"  {label}", U | B))
            if not body:
                L.append(("    -", D))
                return
            if isinstance(body, str):
                body = textwrap.wrap(body, max(20, w - 8))
            for ln in body[:limit if isinstance(limit, int) else None]:
                L.append((f"    {ln}", 0))

        block("FIRST PROMPT", d["first_prompt"] or "", 2)
        msgs = list(d["msgs"])
        L.append(("", 0))
        L.append((f"  LAST {len(msgs)} MESSAGES  (j/k or arrows to scroll)", U | B))
        if not msgs:
            L.append(("    -", D))
        for ts, role, txt in msgs:
            when = ""
            if ts:
                when = datetime.datetime.fromisoformat(
                    ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
            who = "you" if role == "user" else "claude"
            head = f"    {when:>5}  {who:<7}"
            wrapped = textwrap.wrap(txt, max(20, w - len(head) - 4)) or [""]
            L.append((head + wrapped[0], B if role == "user" else 0))
            for extra in wrapped[1:3]:
                L.append((" " * len(head) + extra, D))
            if len(wrapped) > 3:
                L.append((" " * len(head) + "...", D))

        L.append(("", 0))
        L.append(("  RESUME", U | B))
        L.append((f"    {s.cmd.replace(home, '~')}", B))
        return L

    def draw_detail(self):
        h, w = self.scr.getmaxyx()
        self.put(0, 0, " claude-sessions - SESSION ".ljust(w - 1),
                 curses.A_REVERSE | curses.A_BOLD)
        lines = self.detail_lines(self.rows[self.sel], w)
        avail = h - 3
        self.scroll = max(0, min(self.scroll, max(0, len(lines) - avail)))
        for i in range(avail):
            if self.scroll + i >= len(lines):
                break
            txt, attr = lines[self.scroll + i]
            self.put(2 + i, 2, txt, attr)
        more = "" if self.scroll + avail >= len(lines) else "   more below"
        bar = f" enter resume - c copy - j/k scroll - g/G top/end - q back{more} "
        if self.msg:
            bar = f" {self.msg} "
        self.put(h - 1, 0, bar.ljust(w - 1), curses.A_REVERSE)

    def draw_text(self, body, label):
        h, w = self.scr.getmaxyx()
        self.put(0, 0, f" claude-sessions - {label} ".ljust(w - 1),
                 curses.A_REVERSE | curses.A_BOLD)
        lines = body.splitlines()
        avail = h - 3
        self.scroll = max(0, min(self.scroll, max(0, len(lines) - avail)))
        for i in range(avail):
            if self.scroll + i >= len(lines):
                break
            ln = lines[self.scroll + i]
            attr = curses.A_BOLD if ln[:2].isupper() and ln[:1].strip() else 0
            self.put(2 + i, 2, ln, attr)
        more = "" if self.scroll + avail >= len(lines) else "   more below"
        self.put(h - 1, 0, f" j/k scroll - q back to table{more} ".ljust(w - 1),
                 curses.A_REVERSE)

    # -- input

    def filter_mode(self):
        """Incremental fuzzy search: the table reorders on every keystroke."""
        curses.curs_set(1)
        while True:
            self.draw()
            h, w = self.scr.getmaxyx()
            self.put(h - 1, 0, f" fuzzy: {self.filter}█".ljust(w - 1),
                     curses.A_REVERSE)
            self.scr.refresh()
            k = self.scr.getch()
            if k in (curses.KEY_ENTER, 10, 13):
                break
            if k == 27:                      # esc: leave the search
                self.filter = ""
                self.sel = self.top = 0
                self.refresh_rows()
                self.msg = "search cancelled"
                break
            if k in (curses.KEY_BACKSPACE, 127, 8):
                self.filter = self.filter[:-1]
            elif k == curses.KEY_DOWN:
                self.sel = min(self.sel + 1, len(self.rows) - 1)
                continue
            elif k == curses.KEY_UP:
                self.sel = max(self.sel - 1, 0)
                continue
            elif 32 <= k < 127:
                self.filter += chr(k)
            else:
                continue
            self.sel = self.top = 0
            self.refresh_rows()
        curses.curs_set(0)

    def copy(self):
        if not self.rows:
            return
        try:
            subprocess.run(["pbcopy"], input=self.rows[self.sel].cmd.encode(),
                           check=True)
            self.msg = "command copied to clipboard"
        except Exception as e:
            self.msg = f"could not copy: {e}"

    def run(self):
        curses.curs_set(0)
        while True:
            self.draw()
            try:
                k = self.scr.getch()
            except KeyboardInterrupt:
                return None
            self.msg = ""

            if self.view == "detail":
                if k in (curses.KEY_ENTER, 10, 13):
                    return self.rows[self.sel]
                if k in (ord("q"), ord("Q"), 27):
                    self.view, self.scroll = "list", 0
                elif k in (ord("j"), curses.KEY_DOWN):
                    self.scroll += 1
                elif k in (ord("k"), curses.KEY_UP):
                    self.scroll -= 1
                elif k in (ord(" "), curses.KEY_NPAGE, ord("n")):
                    self.scroll += max(1, self.scr.getmaxyx()[0] - 4)
                elif k in (ord("b"), curses.KEY_PPAGE, ord("p")):
                    self.scroll -= max(1, self.scr.getmaxyx()[0] - 4)
                elif k == ord("g"):
                    self.scroll = 0
                elif k == ord("G"):
                    self.scroll = 10 ** 6
                elif k == ord("c"):
                    self.copy()
                elif k in (ord("h"), ord("?")):
                    self.view, self.scroll = "help", 0
                elif k == ord("r"):
                    self.view, self.scroll = "readme", 0
                continue

            if self.view != "list":
                if k in (ord("q"), ord("Q"), 27):
                    self.view = "list"
                    self.scroll = 0
                elif k in (ord("j"), curses.KEY_DOWN):
                    self.scroll += 1
                elif k in (ord("k"), curses.KEY_UP):
                    self.scroll -= 1
                elif k in (ord(" "), curses.KEY_NPAGE, ord("n")):
                    self.scroll += max(1, self.scr.getmaxyx()[0] - 4)
                elif k in (ord("b"), curses.KEY_PPAGE, ord("p")):
                    self.scroll -= max(1, self.scr.getmaxyx()[0] - 4)
                elif k in (ord("h"), ord("?")):
                    self.view, self.scroll = "help", 0
                elif k == ord("r"):
                    self.view, self.scroll = "readme", 0
                continue

            if k in (ord("q"), ord("Q")):
                return None
            elif k in (ord("h"), ord("?")):
                self.view, self.scroll = "help", 0
            elif k == ord("r"):
                self.view, self.scroll = "readme", 0
            elif k in (ord("j"), curses.KEY_DOWN):
                self.sel = min(self.sel + 1, len(self.rows) - 1)
            elif k in (ord("k"), curses.KEY_UP):
                self.sel = max(self.sel - 1, 0)
            elif k in (ord("n"), ord(" "), curses.KEY_NPAGE):
                self.sel = min(self.sel + self.page, len(self.rows) - 1)
            elif k in (ord("p"), ord("b"), curses.KEY_PPAGE):
                self.sel = max(self.sel - self.page, 0)
            elif k == ord("g"):
                self.sel = self.top = 0
            elif k == ord("G"):
                self.sel = max(0, len(self.rows) - 1)
            elif k == ord("d"):
                if self.rows and self.rows[self.sel].cwd:
                    self.home = self.target = self.rows[self.sel].cwd
                    self.filter = ""
                    self.sel = self.top = 0
                    self.refresh_rows()
                    self.msg = f"only {self.target}"
            elif k == ord("a"):
                self.target = None if self.target is not None else (
                    self.home or os.getcwd())
                self.sel = self.top = 0
                self.refresh_rows()
            elif k == ord("/"):
                self.filter_mode()
            elif k == 27:
                if self.filter:
                    self.filter = ""
                    self.refresh_rows()
            elif k in (curses.KEY_ENTER, 10, 13):
                if self.rows:
                    self.view, self.scroll = "detail", 0
            elif k == ord("c"):
                self.copy()
            elif k == curses.KEY_RESIZE:
                try:
                    curses.update_lines_cols()
                except AttributeError:
                    pass
                self.scr.clear()


# ---------------------------------------------------------------- main

def plain(target):
    rows = load(target)
    if target is not None:
        print(f"dir  : {os.path.realpath(os.path.expanduser(target))}")
        print(f"store: ~/.claude/projects/{encode(target)}/\n")
    for s in rows:
        print(f"{s.when:17}{s.nmsg:>5} msgs {s.size / 1048576:>6.1f}MB  {s.sid}")
        if target is None:
            print(f"{'':17}  {s.cwd}")
        print(f"{'':17}  -> {s.title[:80]}\n")
    print(f"{len(rows)} session(s). Resume: cd <dir> && claude --resume <id>")


def main():
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        print(HELP)
        return
    # no argument means every directory; pass a path (or ".") to scope it
    rest = [a for a in argv if not a.startswith("-")]
    target = rest[0] if rest else None

    if not sys.stdout.isatty():
        plain(target)
        return

    os.environ.setdefault("ESCDELAY", "25")   # else ncurses waits 1s after ESC

    def boot(scr):
        try:
            curses.set_escdelay(25)
        except AttributeError:
            pass
        return App(scr, target).run()

    picked = curses.wrapper(boot)
    if picked:
        print(picked.cmd)


if __name__ == "__main__":
    main()
