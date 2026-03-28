import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Targets ───────────────────────────────────────────────────────────────────
TARGET_CHARS = {
    'gemini': 120_000,
    'claude': 760_000,
}
BUDGET_FILL = 0.95  # stop at 95% of target to leave headroom

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
    '.generated.cs','.pb.go','.pb.swift','.designer.cs','.g.cs','.g.i.cs',
)
CONTENT_EXTS = {
    '.py','.js','.ts','.jsx','.tsx','.cpp','.c','.h','.hpp','.cs',
    '.java','.kt','.swift','.go','.rs','.php','.rb','.lua',
    '.html','.css','.scss','.xml','.json','.yaml','.yml',
    '.toml','.ini','.cfg','.md','.txt','.sh','.bat','.sql',
}
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

# Gemini mode strips these, Claude mode keeps them
SKIP_TESTS_PATTERNS = ('test_','_test.','.test.','.spec.','_spec.','mock_','_mock.','.mock.')

MAX_FILE_BYTES = 200_000  # never read files larger than this

# Priority tiers (lower = higher priority, filled first)
TIER_ENTRY   = 0  # entry point files (ALWAYS_FULL)
TIER_SHALLOW = 1  # depth <= 2, non-config code
TIER_DEEP    = 2  # depth 3-5, non-config code
TIER_CONFIG  = 3  # config files not in ALWAYS_FULL
TIER_DEEPER  = 4  # depth > 5

# ── Helpers ───────────────────────────────────────────────────────────────────

def skip_file(name, skip_tests):
    if name in IGNORE_FILES:
        return True
    if any(name.endswith(s) for s in IGNORE_SUFFIXES):
        return True
    if skip_tests:
        nl = name.lower()
        if any(p in nl for p in SKIP_TESTS_PATTERNS):
            return True
    return False

def strip_content(text, ext, do_strip):
    if not do_strip:
        lines = [l.rstrip() for l in text.splitlines() if l.strip()]
        return '\n'.join(lines)
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
        if ext in {'.py','.sh','.rb'} and s.startswith('#'):
            continue
        if ext in {'.js','.ts','.jsx','.tsx','.java','.kt','.go','.rs',
                   '.cpp','.c','.h','.hpp','.cs','.swift','.php'} and s.startswith('//'):
            continue
        if ext in {'.html','.xml'} and s.startswith('<!--'):
            continue
        if ext in {'.css','.scss'} and s.startswith('/*'):
            continue
        if ext in {'.js','.ts','.jsx','.tsx','.java','.cs','.go','.cpp','.c','.h'}:
            l = re.sub(r'(?<!:)\s*//(?![/\s]*https?:).*$', '', l)
        lines.append(l.rstrip())
    return '\n'.join(l for l in lines if l.strip())

def read_raw_lines(path):
    """Read all lines from file. Returns [] on error or oversize."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None  # None = too large
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()
    except:
        return []

def build_tree(root, skip_tests):
    lines = [os.path.basename(root)+'/']
    for r, dirs, files in os.walk(root):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')])
        depth = os.path.relpath(r, root).count(os.sep)
        if r != root:
            lines.append(' '*depth*2+os.path.basename(r)+'/')
        for f in sorted(files):
            if not skip_file(f, skip_tests):
                lines.append(' '*(depth+1)*2+f)
    return '\n'.join(lines)

# ── Pass 1: Inventory ─────────────────────────────────────────────────────────

def inventory(root, skip_tests):
    """
    Walk the directory and collect metadata for every relevant file.
    Returns list of dicts sorted by priority tier.
    """
    files = []
    for r, dirs, fnames in os.walk(root):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')])
        depth = os.path.relpath(r, root).count(os.sep)

        for fname in sorted(fnames):
            if skip_file(fname, skip_tests):
                continue
            ext   = os.path.splitext(fname)[1].lower()
            fpath = os.path.join(r, fname)
            rel   = os.path.relpath(fpath, root)

            if ext not in CONTENT_EXTS:
                files.append({'rel': rel, 'ext': ext, 'tier': 99,
                               'lines': None, 'path': fpath, 'binary': True})
                continue

            is_entry = fname in ALWAYS_FULL
            is_cfg   = ext in CONFIG_EXTS and not is_entry

            if is_entry:
                tier = TIER_ENTRY
            elif is_cfg:
                tier = TIER_CONFIG
            elif depth <= 2:
                tier = TIER_SHALLOW
            elif depth <= 5:
                tier = TIER_DEEP
            else:
                tier = TIER_DEEPER

            raw = read_raw_lines(fpath)
            line_count = len(raw) if raw is not None else 0
            too_large  = raw is None

            files.append({
                'rel':       rel,
                'ext':       ext,
                'tier':      tier,
                'path':      fpath,
                'lines':     raw,
                'line_count':line_count,
                'too_large': too_large,
                'is_entry':  is_entry,
                'is_cfg':    is_cfg,
                'binary':    False,
            })

    files.sort(key=lambda f: (f['tier'], f['rel']))
    return files

# ── Pass 2: Budget allocation ─────────────────────────────────────────────────

def allocate(files, budget_chars, do_strip):
    """
    Given sorted file list and char budget, decide how many lines each
    file gets. Returns list of (rel, tag, content_str) tuples.
    """
    used    = 0
    output  = []
    # Overhead estimate for tree + preamble
    OVERHEAD = 2_000

    remaining = budget_chars - OVERHEAD

    # ── Tier 0: Entry points — always include, up to their full line count ────
    entry_files = [f for f in files if not f['binary'] and f['tier'] == TIER_ENTRY]
    other_files = [f for f in files if f['binary'] or f['tier'] != TIER_ENTRY]

    for f in entry_files:
        if f['too_large']:
            content = f'[skipped:>{MAX_FILE_BYTES//1024}KB]'
            tag = 'F'
        else:
            stripped = strip_content(''.join(f['lines']), f['ext'], do_strip)
            content  = stripped
            if not content:
                content = '[empty]'
        chunk = f'F:{f["rel"]}|{f["line_count"]}L\n{content}'
        used += len(chunk)
        output.append(chunk)

    remaining -= used

    # ── Config files — name only, nearly free ─────────────────────────────────
    for f in other_files:
        if not f['binary'] and f['is_cfg']:
            chunk = f'C:{f["rel"]}'
            remaining -= len(chunk)
            output.append(chunk)

    # ── Binary files — name only ──────────────────────────────────────────────
    for f in other_files:
        if f['binary']:
            chunk = f'B:{f["rel"]}'
            remaining -= len(chunk)
            output.append(chunk)

    # ── Remaining code files — budget split by tier then proportionally ───────
    code_files = [f for f in other_files
                  if not f['binary'] and not f['is_cfg'] and not f['too_large']]

    if code_files and remaining > 0:
        total_lines = sum(f['line_count'] for f in code_files) or 1

        for f in code_files:
            if remaining <= 0:
                # Budget exhausted — name only
                output.append(f'P:{f["rel"]}|{f["line_count"]}L\n+alllines(budget exhausted)')
                continue

            # Proportional share of remaining budget (in chars)
            share_chars = int((f['line_count'] / total_lines) * remaining)
            # Avg ~40 chars/line after stripping
            line_alloc  = max(5, share_chars // 40)
            line_alloc  = min(line_alloc, f['line_count'])

            snippet = strip_content(''.join(f['lines'][:line_alloc]), f['ext'], do_strip)
            leftover = f['line_count'] - line_alloc
            suffix   = f'\n+{leftover}L' if leftover > 0 else ''
            content  = (snippet + suffix).strip() or '[empty]'

            chunk = f'P:{f["rel"]}|{f["line_count"]}L\n{content}'
            used      += len(chunk)
            remaining -= len(chunk)
            output.append(chunk)

    return output

# ── Assemble final output ─────────────────────────────────────────────────────

def snapshot(root, mode):
    skip_tests = (mode == 'gemini')
    do_strip   = (mode == 'gemini')
    budget     = int(TARGET_CHARS[mode] * BUDGET_FILL)

    preamble = (
        'SNAPSHOT|F=full,P=preview(proportional budget),C=config(nameonly),B=binary\n'
        'Ask user to share any P/C file directly for full content.\n'
    )
    tree = 'TREE:\n' + build_tree(root, skip_tests)

    print('Pass 1: inventorying files...')
    files = inventory(root, skip_tests)

    print(f'Pass 2: allocating {budget:,} char budget across {len(files)} files...')
    file_budget = budget - len(preamble) - len(tree) - 10
    entries = allocate(files, file_budget, do_strip)

    body = preamble + '\n' + tree + '\nFILES:\n' + '\n'.join(entries)
    return body, len(files)

# ── GUI ───────────────────────────────────────────────────────────────────────

def pick_mode():
    result = {'mode': None}
    win = tk.Toplevel()
    win.title('Snapshot Mode')
    win.resizable(False, False)
    win.grab_set()

    tk.Label(win, text='Choose output mode',
             font=('Segoe UI', 11, 'bold'), pady=10).pack()

    modes = [
        ('gemini', 'Gemini Free  (~32K tokens / 120K chars)',
         'Max compression. Comments stripped, tests skipped.\nBudget fills to 95% of Gemini free limit.'),
        ('claude', 'Claude Free  (~200K tokens / 760K chars)',
         'More content. Comments kept, tests included.\nBudget fills to 95% of Claude free limit.'),
    ]
    for key, label, desc in modes:
        frm = tk.Frame(win, bd=1, relief='solid', padx=12, pady=8)
        frm.pack(fill='x', padx=16, pady=6)
        tk.Label(frm, text=label, font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x')
        tk.Label(frm, text=desc, font=('Segoe UI', 9), fg='#555',
                 justify='left', anchor='w').pack(fill='x')
        def on_click(k=key):
            result['mode'] = k
            win.destroy()
        tk.Button(frm, text='Select', command=on_click, width=10).pack(anchor='e', pady=(4,0))

    tk.Button(win, text='Cancel', command=win.destroy, fg='red').pack(pady=(0,10))
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f'+{(sw-w)//2}+{(sh-h)//2}')
    win.wait_window()
    return result['mode']

def run_app():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    mode = pick_mode()
    if not mode:
        return

    sel = filedialog.askdirectory(title='Select Project Folder')
    if not sel:
        return

    out, total_files = snapshot(sel, mode)
    chars  = len(out)
    tokens = chars // 4
    target = TARGET_CHARS[mode]
    pct    = round(chars / target * 100, 1)

    save = filedialog.asksaveasfilename(
        defaultextension='.txt',
        initialfile=f'snapshot_{mode}.txt',
        title='Save Snapshot',
    )
    if save:
        with open(save, 'w', encoding='utf-8') as f:
            f.write(out)
        messagebox.showinfo('Done',
            f'Mode: {mode.capitalize()}\n\n'
            f'{chars:,} chars  (~{tokens:,} tokens)\n'
            f'{pct}% of {mode.capitalize()} free limit used\n\n'
            f'Total files seen: {total_files}'
        )

if __name__ == '__main__':
    run_app()