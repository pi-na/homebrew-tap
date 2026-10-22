"""Screen-level tests: drive the TUI through a pty and assert on what a real
terminal emulator renders. Run with:  python3 tests/test_screen.py

Set CS_BIN to test an installed binary instead of the file in this repo:
    CS_BIN=$(which claude-sessions) python3 tests/test_screen.py
"""
import os, sys, pty, time, fcntl, termios, struct, subprocess, threading
import pyte

ROWS, COLS = 30, 120
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("CS_BIN", os.path.join(HERE, "..", "claude-sessions.py"))
RUN = [SCRIPT] if os.access(SCRIPT, os.X_OK) else [sys.executable, SCRIPT]
FAILED = []

screen = pyte.Screen(COLS, ROWS)
stream = pyte.ByteStream(screen)
mfd, sfd = pty.openpty()
fcntl.ioctl(sfd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
p = subprocess.Popen(RUN + ["--all"], stdin=sfd, stdout=sfd,
                     stderr=sfd, env=dict(os.environ, TERM="xterm-256color"),
                     close_fds=True)
os.close(sfd)
lock = threading.Lock()
def drain():
    while True:
        try: b = os.read(mfd, 65536)
        except OSError: return
        if not b: return
        with lock: stream.feed(b)
threading.Thread(target=drain, daemon=True).start()

def shot():
    time.sleep(0.6)
    with lock: return [l.rstrip() for l in screen.display]

def send(*keys):
    for k in keys:
        os.write(mfd, k); time.sleep(0.12)

def check(label, cond, extra=""):
    if not cond:
        FAILED.append(label)
    tail = (" | " + extra) if extra and not cond else ""
    print("  " + ("PASS" if cond else "FAIL <<<") + "  " + label + tail)


time.sleep(2.2)
sc = shot()
print("1) tabla inicial")
check("header ALL DIRECTORIES", any("ALL DIRECTORIES" in l for l in sc))
check("columnas en ingles", any("LAST USED" in l and "MSGS" in l for l in sc))
check("pie con q quit", any("q quit" in l for l in sc))
check("sin texto en castellano", not any(("sesión" in l or "salir" in l or "ayuda" in l) for l in sc),
      " | ".join(l for l in sc if "sesión" in l or "salir" in l))
filas = sum(1 for l in sc if l.strip().startswith(("2026-", "> 2026-")) or " 2026-" in l[:24])
check(f"filas dinamicas = {filas} (esperado {ROWS-10})", filas == ROWS - 10)
check("aire antes del pie", sc[ROWS-5].strip() == "" and sc[ROWS-4].strip() == "",
      repr(sc[ROWS-6:ROWS-3]))

print("2) tecla d (acotar al dir de la fila)")
send(b"j", b"d"); sc = shot()
check("scope cambio a un path", any(l.strip().startswith("/Users/") for l in sc[:3]),
      repr(sc[1]))
check("mensaje 'only ...'", any("only /Users" in l for l in sc))

print("3) tecla a (toggle list all)")
send(b"a"); sc = shot()
check("vuelve a ALL DIRECTORIES", any("ALL DIRECTORIES" in l for l in sc))
check("pie dice 'a (toggle) list all'", any("a (toggle) list all" in l for l in sc),
      repr(sc[-1]))

print("4) fuzzy + esc")
send(b"/", b"k", b"l", b"e", b"e"); sc = shot()
check("prompt fuzzy visible", any("fuzzy: klee" in l for l in sc), repr(sc[-1]))
check("filtro aplicado (pocas filas)", any("session(s)" in l and not l.strip().startswith("47") for l in sc),
      " | ".join(l for l in sc if "session(s)" in l))
send(b"\x1b"); sc = shot()
check("esc sale del buscador", any("search cancelled" in l for l in sc), repr(sc[-1]))
check("lista restaurada a 47", any("47 session(s)" in l for l in sc),
      " | ".join(l for l in sc if "session(s)" in l))

print("5) enter -> vista foco")
send(b"\r"); sc = shot()
check("titulo SESSION", any("claude-sessions - SESSION" in l for l in sc))
for campo in ("DIRECTORY", "BRANCH", "MODEL", "DURATION", "FIRST PROMPT",
              "MESSAGES", "TOKENS"):
    check(f"campo {campo}", any(campo in l for l in sc))
check("TOOLS fuera", not any("  TOOLS" in l for l in sc))
check("FILES TOUCHED fuera", not any("FILES TOUCHED" in l for l in sc))
check("bloque LAST 10 MESSAGES", any("LAST 10 MESSAGES" in l for l in sc))
check("mensajes con rol you/claude", sum(1 for l in sc if "  you  " in l or "  claude " in l) >= 2,
      " | ".join(l for l in sc if "you" in l)[:200])
send(b"G"); sc = shot()
check("G llega al final: RESUME visible", any("RESUME" in l for l in sc))
check("comando de resume en el foco", any("claude --resume" in l for l in sc))
send(b"g"); sc = shot()
check("g vuelve al tope: DIRECTORY visible", any("DIRECTORY" in l for l in sc))
check("pie: enter resume", any("enter resume" in l for l in sc), repr(sc[-1]))

print("6) enter otra vez -> sale e imprime el comando")
send(b"\r")
try: rc = p.wait(timeout=8)
except subprocess.TimeoutExpired: p.kill(); rc = "TIMEOUT"
time.sleep(0.4)
with lock: final = "\n".join(l.rstrip() for l in screen.display)
check("exit 0", rc == 0, str(rc))
check("imprimio el comando de resume", "claude --resume" in final,
      final[-300:])
print("\n--- comando final en pantalla ---")
print("\n".join(l for l in final.splitlines() if "claude --resume" in l))

print()
print("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed")
sys.exit(1 if FAILED else 0)
