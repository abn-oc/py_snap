import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Targets ───────────────────────────────────────────────────────────────────
# ~30K tokens  = Gemini free tier (gemini.google.com)
# ~190K tokens = Claude free tier (claude.ai)
TARGET_GEMINI_CHARS  = 120_000   # ~30K tokens
TARGET_CLAUDE_CHARS  = 760_000   # ~190K tokens

# ── Ignore lists ──────────────────────────────────────────────────────────────
IGNORE_DIRS = {
    '.git','__pycache__','node_modules','venv','.venv','env',
    '.vs','.vscode','.idea','obj','bin','dist','build',
    '.gradle','.dart_tool','.flutter-plugins','Pods','migrations',
    'coverage','htmlcov','.pytest_cache','__tests__','fixtures',
    'assets','public','static','media','images','icons','fonts',
}
IGNORE_FILES = {
    'package-lock.json','yarn.lock','poetry.lock','Pipfile.lock',
    'composer.lock','.DS_Store','Thumbs.db','.env','.env.local',
    '.env.example','CHANGELOG.md','LICENCE','LICENSE','NOTICE',
}
IGNORE_SUFFIXES = (
    '.min.js','.min.css','.map','.lock','.log','.snap',
    '.generated.cs','.pb.go','.pb.swift',  # protobuf generated
    '.designer.cs',  # WinForms generated
    '.g.cs', '.g.i.cs',  # Roslyn generated
)
# Skip these entirely — not useful for LLM codebase understanding
SKIP_PATTERNS = (
    'test_', '_test.', '.test.', '.spec.', '_spec.',
    'mock_', '_mock.', '.mock.',
)
CONTENT_EXTS = {
    '.py','.js','.ts','.jsx','.tsx','.cpp','.c','.h','.hpp','.cs',
    '.java','.kt','.swift','.go','.rs','.php','.rb','.lua',
    '.html','.css','.scss','.xml','.json','.yaml','.yml',
    '.toml','.ini','.cfg','.md','.txt','.sh','.bat','.sql',
}
# Only these get any content at all beyond entry-point files
# Config files: just filename, no content
CONFIG_EXTS = {'.json','.yaml','.yml','.toml','.ini','.cfg','.xml'}

ALWAYS_FULL = {
    'main.py','app.py','manage.py','settings.py','urls.py','wsgi.py',
    'index.js','index.ts','app.js','app.ts','main.ts','main.js',
    'server.js','server.ts','router.js','router.ts',
    'package.json','tsconfig.json','vite.config.ts','vite.config.js',
    'webpack.config.js','next.config.js',
    'Program.cs','Startup.cs','GameManager.cs',
    'Makefile','Dockerfile','docker-compose.yml','README.md',
    'requirements.txt','pyproject.toml','CMakeLists.txt','build.gradle',
    '.gitignore','Pipfile',
}

MAX_DEPTH        = 4      # skip file contents beyond this folder depth
MAX_FILE_BYTES   = 50_000 # skip content for files larger than this
PREVIEW_LINES    = 8      # lines shown for non-entry-point code files
FULL_LINE_LIMIT  = 250    # max lines for entry-point files

# ── Helpers ───────────────────────────────────────────────────────────────────

def skip_file(name: str) -> bool:
    if name in IGNORE_FILES:
        return True
    if any(name.endswith(s) for s in IGNORE_SUFFIXES):
        return True
    nl = name.lower()
    if any(p in nl for p in SKIP_PATTERNS):
        return True
    return False

def strip_content(text: str, ext: str) -> str:
    """Aggressive: remove blank lines, single-line comments, block comments."""
    # Strip block comments /* ... */ and Python docstrings (rough)
    if ext in {'.js','.ts','.jsx','.tsx','.java','.kt','.go','.rs',
               '.cpp','.c','.h','.hpp','.cs','.swift','.php'}:
        text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    if ext == '.py':
        text = re.sub(r'"""[\s\S]*?"""', '', text)
        text = re.sub(r"'''[\s\S]*?'''", '', text)

    lines = []
    for l in text.splitlines():
        s = l.strip()
        if not s:
            continue
        # drop pure comment lines
        if ext in {'.py','.sh','.rb','.pl','.r'} and s.startswith('#'):
            continue
        if ext in {'.js','.ts','.jsx','.tsx','.java','.kt','.go','.rs',
                   '.cpp','.c','.h','.hpp','.cs','.swift','.php'} and s.startswith('//'):
            continue
        if ext in {'.html','.xml'} and s.startswith('<!--'):
            continue
        if ext in {'.css','.scss'} and s.startswith('/*'):
            continue
        # strip inline // comments (avoid URLs https://)
        if ext in {'.js','.ts','.jsx','.tsx','.java','.cs','.go','.cpp','.c','.h'}:
            l = re.sub(r'(?<!:)\s*//(?![/\s]*https?:).*$', '', l)
        lines.append(l.rstrip())

    return '\n'.join(l for l in lines if l.strip())

def read_file(path: str, ext: str, full: bool) -> tuple:
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            return f'[skipped:{size//1024}KB]', 0
        with open(path,'r',encoding='utf-8',errors='replace') as f:
            raw = f.readlines()
    except Exception as e:
        return f'[ERR:{e}]', 0

    total = len(raw)
    limit = FULL_LINE_LIMIT if full else PREVIEW_LINES
    text = ''.join(raw[:limit])
    text = strip_content(text, ext)

    suffix = f'\n+{total-limit}L' if total > limit else ''
    return (text + suffix).strip(), total

def build_tree(root: str) -> str:
    lines = [os.path.basename(root)+'/']
    for r, dirs, files in os.walk(root):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')])
        depth = os.path.relpath(r, root).count(os.sep)
        if r != root:
            lines.append(' '*depth*2+os.path.basename(r)+'/')
        for f in sorted(files):
            if not skip_file(f):
                lines.append(' '*(depth+1)*2+f)
    return '\n'.join(lines)

def snapshot(root: str) -> tuple:
    parts = [
        'SNAPSHOT|F=full,P=preview,C=config(nameonly),B=binary,S=skipped\n'
        'To get full content of any P/C file ask user to share it directly.\n'
    ]
    parts.append('TREE:\n'+build_tree(root))
    parts.append('FILES:')

    counts = {'F':0,'P':0,'C':0,'B':0,'S':0}

    for r, dirs, files in os.walk(root):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')])
        depth = os.path.relpath(r, root).count(os.sep)

        for fname in sorted(files):
            if skip_file(fname):
                counts['S'] += 1
                continue

            ext  = os.path.splitext(fname)[1].lower()
            fpath = os.path.join(r, fname)
            rel   = os.path.relpath(fpath, root)

            if ext not in CONTENT_EXTS:
                parts.append(f'B:{rel}')
                counts['B'] += 1
                continue

            is_full = fname in ALWAYS_FULL

            # Config-only files beyond root level: name only
            if ext in CONFIG_EXTS and not is_full:
                parts.append(f'C:{rel}')
                counts['C'] += 1
                continue

            # Deep files: preview only regardless
            effective_full = is_full and depth <= MAX_DEPTH

            content, total = read_file(fpath, ext, full=effective_full)
            tag = 'F' if effective_full else 'P'
            parts.append(f'{tag}:{rel}|{total}L\n{content}')
            counts[tag] += 1

    body = '\n'.join(parts)
    return body, counts

# ── Entry point ───────────────────────────────────────────────────────────────

def run_app():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    sel = filedialog.askdirectory(title='Select Project Folder')
    if not sel:
        return

    out, counts = snapshot(sel)
    chars  = len(out)
    tokens = chars // 4

    gemini_pct = min(100, round(chars / TARGET_GEMINI_CHARS * 100))
    claude_pct  = min(100, round(chars / TARGET_CLAUDE_CHARS  * 100))

    save = filedialog.asksaveasfilename(
        defaultextension='.txt',
        initialfile='snapshot.txt',
        title='Save Snapshot',
    )
    if save:
        with open(save,'w',encoding='utf-8') as f:
            f.write(out)

        warn = ''
        if chars > TARGET_CLAUDE_CHARS:
            warn = '\n⚠️ Exceeds Claude free context. Use paid tier.'
        elif chars > TARGET_GEMINI_CHARS:
            warn = '\n⚠️ Too large for Gemini free (32K). OK for Claude free.'

        messagebox.showinfo('Done',
            f'Saved!\n\n'
            f'{chars:,} chars  (~{tokens:,} tokens)\n\n'
            f'Gemini free (32K):  {gemini_pct}% full\n'
            f'Claude free (200K): {claude_pct}% full\n'
            f'{warn}\n\n'
            f'F:{counts["F"]} full  P:{counts["P"]} preview  '
            f'C:{counts["C"]} config  S:{counts["S"]} skipped'
        )

if __name__ == '__main__':
    run_app()