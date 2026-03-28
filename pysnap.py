import os
import tkinter as tk
from tkinter import filedialog, messagebox

def map_directory(target_path, allowed_extensions):
    tree_data = []
    
    for root, dirs, files in os.walk(target_path):
        # Optional: Skip hidden folders like .git or .vscode
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, target_path)
            
            entry = f"\n{'='*60}\nFILE: {rel_path}\n{'='*60}\n"
            
            if any(file.endswith(ext) for ext in allowed_extensions):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        entry += f.read()
                except Exception as e:
                    entry += f"[Error reading file: {e}]"
            else:
                entry += "[Content Skipped - Extension not in whitelist]"
            
            tree_data.append(entry)
    
    return "\n".join(tree_data)

def run_app():
    # 1. Initialize Tkinter and hide the main root window
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True) # Bring the dialog to the front

    # 2. Ask user for the directory
    selected_dir = filedialog.askdirectory(title="Select Folder to Map")
    
    if not selected_dir:
        print("No folder selected. Exiting.")
        return

    # 3. Define allowed extensions
    extensions = [".txt", ".cpp", ".py", ".h", ".md", ".js"]

    # 4. Process the files
    print(f"Processing: {selected_dir}...")
    output_text = map_directory(selected_dir, extensions)

    # 5. Save the result to a file
    save_path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt")],
        title="Save Map As"
    )

    if save_path:
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(output_text)
        messagebox.showinfo("Success", f"Directory map saved to:\n{save_path}")
    else:
        print("Save cancelled.")

if __name__ == "__main__":
    run_app()