"""Data-layer tests against the real ~/.claude/projects store.

The invariant that matters: the directory reported for a session must be the
one Claude Code will look in, otherwise the resume command we print silently
fails. Run with:  python3 tests/test_data.py
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "cs", os.path.join(HERE, "..", "claude-sessions.py"))
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

failed = []


def check(label, cond, extra=""):
    if not cond:
        failed.append(label)
    tail = (" | " + extra) if extra and not cond else ""
    print("  " + ("PASS" if cond else "FAIL <<<") + "  " + label + tail)


t0 = time.time()
sessions = cs.load(None)
elapsed = time.time() - t0

print(f"{len(sessions)} sessions loaded in {elapsed:.2f}s")
check("the store is not empty", sessions)
check("loading stays under 2s", elapsed < 2.0, f"{elapsed:.2f}s")

bad = [s for s in sessions
       if cs.slug(s.cwd or "") != os.path.basename(os.path.dirname(s.path))]
check("every session's directory encodes to its project folder", not bad,
      ", ".join(f"{s.sid[:8]} -> {s.cwd}" for s in bad[:4]))

unresolvable = [s for s in sessions
                if not os.path.exists(os.path.join(
                    cs.STORE, cs.encode(s.cwd), s.sid + ".jsonl"))]
check("the resume command lands where the session actually is", not unresolvable,
      ", ".join(s.sid[:8] for s in unresolvable[:4]))

check("no subagent transcript is listed as a session",
      not any("subagents" in s.path for s in sessions))
check("every session has a last-used timestamp",
      all(s.last for s in sessions))
check("sessions come back most recent first",
      all(a.last >= b.last for a, b in zip(sessions, sessions[1:])))

if sessions:
    s = sessions[0]
    t0 = time.time()
    d = s.details()
    print(f"  (detail parse of {s.size / 1048576:.1f}MB took {time.time() - t0:.2f}s)")
    check("details() returns the message tail", "msgs" in d)
    check("scoping by a session's own directory finds it",
          s.sid in {x.sid for x in cs.load(s.cwd)})

print()
print("FAILED: " + ", ".join(failed) if failed else "all checks passed")
sys.exit(1 if failed else 0)
