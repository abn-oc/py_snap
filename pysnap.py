import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Targets ───────────────────────────────────────────────────────────────────
TARGET_CHARS = {
    'gemini': 120_000,
    'claude': 760_000,
}
BUDGET_FILL  = 0.95
OVERHEAD_EST = 3_000   # preamble + tree + formatting overhead

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
CONFIG_EXTS  = {'.json','.yaml','.yml','.toml','.ini','.cfg','.xml'}
ALWAYS_FULL  = {
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
SKIP_TEST_PATTERNS = ('test_','_test.','.test.','.spec.','_spec.','mock_','_mock.','.mock.')
MAX_FILE_BYTES     = 200_000

# Priority tiers
TIER_ENTRY   = 0
TIER_SHALLOW = 1   # depth <= 2
TIER_DEEP    = 2   # depth 3-5
TIER_CONFIG  = 3
TIER_DEEPER  = 4   # depth > 5

# ── Helpers ───────────────────────────────────────────────────────────────────

def skip_file(name, skip_tests):
    if name in IGNORE_FILES: return True
    if any(name.endswith(s) for s in IGNORE_SUFFIXES): return True
    if skip_tests:
        nl = name.lower()
        if any(p in nl for p in SKIP_TEST_PATTERNS): return True
    return False

def strip_content(text, ext, do_strip):
    if not do_strip:
        return '\n'.join(l.rstrip() for l in text.splitlines() if l.strip())
    if ext in {'.js','.ts','.jsx','.tsx','.java','.kt','.go','.rs',
               '.cpp','.c','.h','.hpp','.cs','.swift','.php'}:
        text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    if ext == '.py':
        text = re.sub(r'"""[\s\S]*?"""', '', text)
        text = re.sub(r"'''[\s\S]*?'''", '', text)
    lines = []
    for l in text.splitlines():
        s = l.strip()
        if not s: continue
        if ext in {'.py','.sh','.rb'} and s.startswith('#'): continue
        if ext in {'.js','.ts','.jsx','.tsx','.java','.kt','.go','.rs',
                   '.cpp','.c','.h','.hpp','.cs','.swift','.php'} and s.startswith('//'): continue
        if ext in {'.html','.xml'} and s.startswith('<!--'): continue
        if ext in {'.css','.scss'} and s.startswith('/*'): continue
        if ext in {'.js','.ts','.jsx','.tsx','.java','.cs','.go','.cpp','.c','.h'}:
            l = re.sub(r'(?<!:)\s*//(?![/\s]*https?:).*$', '', l)
        lines.append(l.rstrip())
    return '\n'.join(l for l in lines if l.strip())

def read_raw_lines(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES: return None
        with open(path,'r',encoding='utf-8',errors='replace') as f:
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
    files = []
    for r, dirs, fnames in os.walk(root):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')])
        depth = os.path.relpath(r, root).count(os.sep)
        for fname in sorted(fnames):
            if skip_file(fname, skip_tests): continue
            ext   = os.path.splitext(fname)[1].lower()
            fpath = os.path.join(r, fname)
            rel   = os.path.relpath(fpath, root)
            if ext not in CONTENT_EXTS:
                files.append({'rel':rel,'binary':True,'tier':99})
                continue
            is_entry = fname in ALWAYS_FULL
            is_cfg   = ext in CONFIG_EXTS and not is_entry
            if   is_entry:    tier = TIER_ENTRY
            elif is_cfg:      tier = TIER_CONFIG
            elif depth <= 2:  tier = TIER_SHALLOW
            elif depth <= 5:  tier = TIER_DEEP
            else:             tier = TIER_DEEPER
            raw        = read_raw_lines(fpath)
            too_large  = raw is None
            line_count = len(raw) if raw else 0
            files.append({
                'rel':rel,'ext':ext,'tier':tier,'path':fpath,
                'lines':raw,'line_count':line_count,
                'too_large':too_large,'is_entry':is_entry,'is_cfg':is_cfg,
                'binary':False,
            })
    files.sort(key=lambda f:(f['tier'], f['rel']))
    return files

# ── Pass 2: Budget allocation ─────────────────────────────────────────────────

def allocate(files, budget, do_strip):
    """
    Two-pass budget allocation:
    - Small project: everything fits → full content for all files
    - Large project: entry points full, rest proportional, hard stop at budget
    """
    output = []

    binaries = [f for f in files if f['binary']]
    configs  = [f for f in files if not f['binary'] and f['is_cfg']]
    entries  = [f for f in files if not f['binary'] and f['is_entry']]
    code     = [f for f in files if not f['binary'] and not f['is_cfg'] and not f['is_entry']]

    # ── Fixed-cost items (name only) ──────────────────────────────────────────
    fixed_lines = []
    for f in binaries:
        fixed_lines.append(f'B:{f["rel"]}')
    for f in configs:
        fixed_lines.append(f'C:{f["rel"]}')
    fixed_cost = sum(len(l)+1 for l in fixed_lines)

    # ── Measure full stripped content for every entry + code file ─────────────
    def get_full_content(f):
        if f['too_large']:
            return f'[skipped:>{MAX_FILE_BYTES//1024}KB]', 0
        if not f['lines']:
            return '[empty]', 0
        stripped = strip_content(''.join(f['lines']), f['ext'], do_strip)
        return stripped or '[empty]', len(f['lines'])

    entry_chunks = []
    entry_cost   = 0
    for f in entries:
        content, lc = get_full_content(f)
        chunk = f'F:{f["rel"]}|{lc}L\n{content}'
        entry_chunks.append(chunk)
        entry_cost += len(chunk) + 1

    # Measure full content for all code files
    code_full = []
    for f in code:
        content, lc = get_full_content(f)
        full_chunk  = f'F:{f["rel"]}|{lc}L\n{content}'
        code_full.append((f, content, lc, full_chunk))

    total_code_cost = sum(len(c[3])+1 for c in code_full)
    total_cost      = fixed_cost + entry_cost + total_code_cost

    # ── Decision: does everything fit? ───────────────────────────────────────
    if total_cost <= budget:
        # Small project — copy everything fully
        output.extend(fixed_lines)
        output.extend(entry_chunks)
        for f, content, lc, chunk in code_full:
            output.append(chunk)
        return output, 'full'

    # ── Large project — proportional allocation ───────────────────────────────
    # Entry points always go in full
    output.extend(fixed_lines)
    output.extend(entry_chunks)

    remaining = budget - fixed_cost - entry_cost

    if remaining <= 0 or not code_full:
        # Entries alone blew the budget
        for f, content, lc, _ in code_full:
            output.append(f'P:{f["rel"]}|{lc}L\n[budget exhausted]')
        return output, 'truncated'

    # Total lines across all code files (weight for proportional split)
    total_lines = sum(lc for _, _, lc, _ in code_full) or 1
    # Avg chars per stripped line ≈ measure from entry content
    avg_cpl = 35  # conservative chars-per-line estimate after stripping

    for f, full_content, lc, full_chunk in code_full:
        if remaining <= 0:
            output.append(f'P:{f["rel"]}|{lc}L\n[budget exhausted]')
            continue

        # This file's proportional share of remaining budget
        share   = (lc / total_lines) * remaining
        alloc_lines = max(4, int(share / avg_cpl))

        if alloc_lines >= lc:
            # Full content fits within share
            chunk = full_chunk
        else:
            # Partial: re-strip only allocated lines
            snippet  = strip_content(''.join(f['lines'][:alloc_lines]), f['ext'], do_strip)
            leftover = lc - alloc_lines
            chunk    = f'P:{f["rel"]}|{lc}L\n{snippet}\n+{leftover}L'

        remaining -= len(chunk) + 1
        output.append(chunk)

    return output, 'proportional'

# ── Assemble ──────────────────────────────────────────────────────────────────

def snapshot(root, mode):
    skip_tests = (mode == 'gemini')
    do_strip   = (mode == 'gemini')
    budget     = int(TARGET_CHARS[mode] * BUDGET_FILL) - OVERHEAD_EST

    preamble = (
        'SNAPSHOT|F=full,P=preview,C=config(nameonly),B=binary\n'
        'For any P/C file ask user to share it directly.\n'
    )
    tree = 'TREE:\n' + build_tree(root, skip_tests) + '\n'

    files   = inventory(root, skip_tests)
    entries, mode_used = allocate(files, budget, do_strip)

    body = preamble + tree + 'FILES:\n' + '\n'.join(entries)
    return body, len(files), mode_used

# ── GUI ───────────────────────────────────────────────────────────────────────

def pick_mode():
    result = {'mode': None}
    win = tk.Toplevel()
    win.title('Snapshot Mode')
    win.resizable(False, False)
    win.grab_set()
    tk.Label(win, text='Choose output mode',
             font=('Segoe UI',11,'bold'), pady=10).pack()
    modes = [
        ('gemini','Gemini Free  (~32K tokens)',
         'Max compression. Comments stripped, tests skipped.\nFills to 95% of Gemini free limit.'),
        ('claude','Claude Free  (~200K tokens)',
         'More content. Comments/tests kept.\nFills to 95% of Claude free limit.'),
    ]
    for key, label, desc in modes:
        frm = tk.Frame(win, bd=1, relief='solid', padx=12, pady=8)
        frm.pack(fill='x', padx=16, pady=6)
        tk.Label(frm, text=label, font=('Segoe UI',10,'bold'), anchor='w').pack(fill='x')
        tk.Label(frm, text=desc, font=('Segoe UI',9), fg='#555',
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
    if not mode: return

    sel = filedialog.askdirectory(title='Select Project Folder')
    if not sel: return

    out, total_files, mode_used = snapshot(sel, mode)
    chars  = len(out)
    tokens = chars // 4
    target = TARGET_CHARS[mode]
    pct    = round(chars / target * 100, 1)

    mode_label = {
        'full':         '✅ Small project — all files copied fully',
        'proportional': '⚖️  Large project — content split proportionally',
        'truncated':    '⚠️  Very large — entry points only fit in budget',
    }[mode_used]

    save = filedialog.asksaveasfilename(
        defaultextension='.txt',
        initialfile=f'snapshot_{mode}.txt',
        title='Save Snapshot',
    )
    if save:
        with open(save,'w',encoding='utf-8') as f:
            f.write(out)
        messagebox.showinfo('Done',
            f'Mode: {mode.capitalize()}\n'
            f'{mode_label}\n\n'
            f'{chars:,} chars  (~{tokens:,} tokens)\n'
            f'{pct}% of {mode.capitalize()} free limit\n\n'
            f'Files processed: {total_files}'
        )

if __name__ == '__main__':
    run_app()