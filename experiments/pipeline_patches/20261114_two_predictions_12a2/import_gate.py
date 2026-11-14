"""Hard import gate for deploy scripts (orchestrator 09:12Z Nov 14, after the Nov 14 arm-2 `ctrl` import miss).

Run it exactly as the job runs: same user, same cwd, `env -u PYTHONPATH` (plus the PYTHONPATH the job itself sets, if any), same python.
For every target it imports every module the script names in ANY import statement (top level, inside functions, inside try blocks),
with sys.path built the way `python3 script.py` builds it: the script's own dir first (none with --isolated, as `python3 -I`), then
the paths the script itself inserts with sys.path.insert(<literal / os.path.expanduser(literal)>), then PYTHONPATH and site-packages.
The script itself is NOT executed. Imported modules run their own top-level code (that is how a missing transitive import, e.g.
training_window -> ctrl, is caught). Targets "-m:pkg.mod" are imported as `python3 -m pkg.mod` would (cwd first).
Any failure -> exit 1 with one line per failure. usage: python3 import_gate.py [--isolated] <script.py | -m:pkg.mod> ...
"""
import ast
import importlib
import os
import pwd
import sys

if sys.path and sys.path[0] == os.path.dirname(os.path.abspath(__file__)):
    sys.path.pop(0)   # the gate's own dir is not on a job's path (with -I / -P it was never added)
BASE = list(sys.path)
args = sys.argv[1:]
iso = bool(args) and args[0] == "--isolated"
args = args[1:] if iso else args
bad, n_ok = [], 0


def try_import(mod, names, where):
    global n_ok
    try:
        m = importlib.import_module(mod)
        for a in names:
            if a != "*" and not hasattr(m, a):
                importlib.import_module(f"{mod}.{a}")   # `from pkg import submodule`
        n_ok += 1
    except Exception as e:   # noqa: BLE001  (ImportError, or a transitive import failing at module top level)
        bad.append(f"{where}: import {mod}{' (' + ','.join(names) + ')' if names else ''} -> {type(e).__name__}: {str(e)[:160]}")


for t in args:
    before = set(sys.modules)
    if t.startswith("-m:"):
        sys.path[:] = [os.getcwd()] + BASE
        try_import(t[3:], [], t)
    else:
        s = os.path.abspath(t)
        tree = ast.parse(open(s).read(), s)
        extra = []
        ns = {"__builtins__": {}, "os": os, "__file__": s}   # literals, __file__-relative paths and simple top-level names (HERE = ...)
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                try:
                    ns[n.targets[0].id] = eval(ast.unparse(n.value), ns)
                except Exception:   # noqa: BLE001
                    pass
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "insert"
                    and ast.unparse(n.func.value) == "sys.path" and len(n.args) == 2):
                try:
                    extra.insert(0, os.path.normpath(eval(ast.unparse(n.args[1]), ns)))   # each insert(0, x) goes in front
                except Exception:   # noqa: BLE001
                    print(f"note {t}: sys.path.insert({ast.unparse(n.args[1])}) not resolvable statically", flush=True)
        sys.path[:] = extra + ([] if iso else [os.path.dirname(s)]) + BASE
        mods = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    mods.setdefault(a.name, [])
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.setdefault(n.module, []).extend(a.name for a in n.names)
        for m in sorted(mods):
            try_import(m, mods[m], os.path.basename(s))
    for k in set(sys.modules) - before:   # same-named project modules from different trees (e.g. two history_retrain.py) must not mask
        f = getattr(sys.modules.get(k), "__file__", None) or ""   # each other; installed packages (numpy...) stay loaded
        if f and "-packages" not in f and not f.startswith((sys.base_prefix, sys.prefix)):
            sys.modules.pop(k, None)

for b in bad:
    print("IMPORT GATE FAIL", b, flush=True)
print(f"import gate: {n_ok} imports ok, {len(bad)} failed ({len(args)} targets, cwd {os.getcwd()}, "
      f"PYTHONPATH={os.environ.get('PYTHONPATH', '<unset>')}, user {pwd.getpwuid(os.geteuid()).pw_name}, {sys.executable})", flush=True)
sys.exit(1 if bad else 0)
