import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# ================= CONFIG =================

PROJECT_ROOT = Path(__file__).resolve().parent
MEGA_DIR = PROJECT_ROOT / "mega"

DEFAULT_PORT = "/dev/ttyACM0"
FQBN = "arduino:avr:mega"

# ================= UTIL ===================

def run_cmd(cmd, cwd=PROJECT_ROOT):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


def is_git_repo():
    return (PROJECT_ROOT / ".git").exists()


def get_git_changes():
    """
    Returns list of (status, path) from git porcelain output.
    """
    rc, out = run_cmd("git status --porcelain")
    if rc != 0:
        return None, out

    changes = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        path = line[3:].strip()

        if " -> " in path:  # rename
            path = path.split(" -> ", 1)[1].strip()

        changes.append((status, path))

    return changes, ""


# ================= FILE SELECT DIALOG =================

class SelectFilesDialog(tk.Toplevel):
    def __init__(self, parent, changes):
        super().__init__(parent)
        self.title("Select files to commit")
        self.geometry("700x450")

        self.result = None
        self.vars = []

        ttk.Label(
            self,
            text="Select files/folders to stage (git add):"
        ).pack(anchor="w", padx=10, pady=(10, 5))

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas)

        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for status, path in changes:
            var = tk.BooleanVar(value=not path.startswith("data/"))
            self.vars.append((var, path))
            ttk.Checkbutton(
                frame,
                text=f"{status}  {path}",
                variable=var
            ).pack(anchor="w")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=10)

        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(btns, text="OK", command=self.ok).pack(side="right", padx=5)

        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def ok(self):
        self.result = [p for v, p in self.vars if v.get()]
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


# ================= MAIN GUI =================

class TeamHelper(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HERC-26 Team Helper")
        self.geometry("1000x700")

        if not is_git_repo():
            messagebox.showerror(
                "Not a Git repository",
                f"No .git folder found in:\n{PROJECT_ROOT}"
            )

        self.build_ui()

    # ---------- UI ----------

    def build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        # -------- Git TAB --------
        git_tab = ttk.Frame(notebook)
        notebook.add(git_tab, text="Git")

        top = ttk.Frame(git_tab)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Button(top, text="Status", command=self.git_status).pack(side="left")
        ttk.Button(top, text="Pull", command=self.git_pull).pack(side="left", padx=5)
        ttk.Button(top, text="Push", command=self.git_push).pack(side="left", padx=5)

        ttk.Label(top, text="Commit message:").pack(side="left", padx=(20, 5))
        self.commit_msg = ttk.Entry(top, width=40)
        self.commit_msg.pack(side="left")

        ttk.Button(
            top,
            text="Commit (select files)",
            command=self.git_commit_flow
        ).pack(side="left", padx=5)

        # -------- Mega TAB --------
        mega_tab = ttk.Frame(notebook)
        notebook.add(mega_tab, text="Mega Upload")

        mtop = ttk.Frame(mega_tab)
        mtop.pack(fill="x", padx=10, pady=8)

        ttk.Label(mtop, text="Firmware:").pack(side="left")

        self.firmware_var = tk.StringVar()
        self.firmware_box = ttk.Combobox(
            mtop,
            textvariable=self.firmware_var,
            values=self.list_firmwares(),
            state="readonly",
            width=40
        )
        self.firmware_box.pack(side="left", padx=5)
        if self.firmware_box["values"]:
            self.firmware_box.current(0)

        ttk.Button(mtop, text="Compile", command=self.mega_compile).pack(side="left", padx=5)
        ttk.Button(mtop, text="Upload", command=self.mega_upload).pack(side="left", padx=5)

        ttk.Label(mtop, text=f"Port: {DEFAULT_PORT}").pack(side="left", padx=20)

        # -------- Output --------
        ttk.Label(self, text="Output").pack(anchor="w", padx=10)
        self.output = tk.Text(self, height=30)
        self.output.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ---------- Output helper ----------

    def log(self, text):
        self.output.insert(tk.END, text + "\n")
        self.output.see(tk.END)

    def run_and_log(self, cmd):
        self.log(f"$ {cmd}")
        rc, out = run_cmd(cmd)
        self.log(out.rstrip())
        self.log("")
        return rc, out

    # ---------- Git ----------

    def git_status(self):
        self.run_and_log("git status")

    def git_pull(self):
        self.run_and_log("git pull")

    def git_push(self):
        self.run_and_log("git push")

    def git_commit_flow(self):
        msg = self.commit_msg.get().strip()
        if not msg:
            messagebox.showwarning("Commit", "Enter a commit message.")
            return

        changes, err = get_git_changes()
        if changes is None:
            self.log(err)
            return

        if not changes:
            messagebox.showinfo("Commit", "Nothing to commit.")
            return

        dlg = SelectFilesDialog(self, changes)
        selected = dlg.result

        if not selected:
            self.log("Commit cancelled or no files selected.\n")
            return

        paths = " ".join(f'"{p}"' for p in selected)
        rc, _ = self.run_and_log(f"git add -- {paths}")
        if rc != 0:
            messagebox.showerror("Git", "git add failed.")
            return

        self.run_and_log("git diff --cached --name-status")

        rc, out = self.run_and_log(f'git commit -m "{msg}"')
        if rc != 0:
            if "Author identity unknown" in out:
                messagebox.showerror(
                    "Git identity not set",
                    "Run once:\n"
                    'git config --global user.name "Your Name"\n'
                    'git config --global user.email "you@example.com"'
                )
            return

        if messagebox.askyesno("Push", "Commit successful. Push now?"):
            self.git_push()

    # ---------- Mega ----------

    def list_firmwares(self):
        if not MEGA_DIR.exists():
            return []
        return [p.name for p in MEGA_DIR.iterdir() if p.is_dir()]

    def mega_compile(self):
        fw = self.firmware_var.get()
        if fw:
            self.run_and_log(f"arduino-cli compile --fqbn {FQBN} mega/{fw}")

    def mega_upload(self):
        fw = self.firmware_var.get()
        if fw:
            self.run_and_log(f"arduino-cli upload -p {DEFAULT_PORT} --fqbn {FQBN} mega/{fw}")


# ================= RUN =================

if __name__ == "__main__":
    TeamHelper().mainloop()
