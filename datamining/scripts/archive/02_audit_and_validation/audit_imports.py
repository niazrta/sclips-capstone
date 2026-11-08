import ast, os, sys

SKIP = {"venv", "__pycache__", ".git", "data", "exports", "backup", "migrations"}
LOCAL = {"db", "scraper", "utils", "scripts", "config", "main"}

files = []
for root, dirs, names in os.walk("."):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for n in names:
        if n.endswith(".py"):
            files.append(os.path.normpath(os.path.join(root, n)))

imports = {}
for f in sorted(files):
    try:
        tree = ast.parse(open(f, encoding="utf-8").read())
    except Exception as e:
        print("GAGAL BACA", f, e)
        continue
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module + " -> " + ",".join(a.name for a in node.names))
    imports[f] = sorted(i for i in found if i.split(" ")[0].split(".")[0] in LOCAL)

print("=== Import lokal per file ===")
for f, imps in imports.items():
    print(f)
    for i in imps:
        print("    ", i)

print("\n=== Siapa dipakai oleh siapa (modul di scripts/ dan main) ===")
for f in imports:
    mod = f[:-3].replace(os.sep, ".")
    users = [g for g, imps in imports.items() if g != f and any(i.split(" ")[0] == mod for i in imps)]
    if f.startswith("scripts") or f == "main.py":
        print(f"{f:40} dipakai oleh: {users or '-'}")