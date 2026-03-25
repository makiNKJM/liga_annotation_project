#liga_launcher_app.py

# lIGA 教師データ管理ランチャー
# - pending / skipped / done / approved の件数表示
# - 作成モード起動
# - 参照・修正・承認モード起動
# - 各フォルダを Finder で開く
# - 閲覧モード（将来拡張用）の入口

import sys
import subprocess
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox
    TK_AVAILABLE = True
except ModuleNotFoundError:
    TK_AVAILABLE = False
    tk = None

    class _DummyMessageBox:
        @staticmethod
        def showinfo(title, msg, **kwargs):
            print(f"[INFO] {title}: {msg}")

        @staticmethod
        def showerror(title, msg, **kwargs):
            print(f"[ERROR] {title}: {msg}")

    messagebox = _DummyMessageBox()


SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif")

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent / "data"

IMAGES_DIR = PROJECT_ROOT / "images"
MASKS_DIR = PROJECT_ROOT / "masks"
OVERLAYS_DIR = PROJECT_ROOT / "overlays"
META_DIR = PROJECT_ROOT / "meta"

PENDING_DIRNAME = "01_pending"
SKIPPED_DIRNAME = "02_skipped"
DONE_DIRNAME = "03_done"
APPROVED_DIRNAME = "04_approved"


def ensure_project_dirs():
    for base in [IMAGES_DIR, MASKS_DIR, OVERLAYS_DIR, META_DIR]:
        for sub in [PENDING_DIRNAME, SKIPPED_DIRNAME, DONE_DIRNAME, APPROVED_DIRNAME]:
            (base / sub).mkdir(parents=True, exist_ok=True)


def count_images_in_dir(d: Path) -> int:
    if not d.exists():
        return 0
    return sum(1 for p in d.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)


class IgaLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("lIGA 教師データ管理ランチャー")
        self.root.geometry("920x620")
        self.root.minsize(860, 560)

        self.python_executable = sys.executable

        self.build_ui()
        self.refresh_counts()

    def build_ui(self):
        # ===== タイトル =====
        title_frame = tk.Frame(self.root)
        title_frame.pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(
            title_frame,
            text="lIGA 教師データ管理ランチャー",
            font=("", 18, "bold"),
            anchor="w"
        ).pack(side=tk.LEFT)

        # ===== カウント表示 =====
        counts_outer = tk.LabelFrame(self.root, text="現在の状態", padx=12, pady=12)
        counts_outer.pack(fill=tk.X, padx=16, pady=8)

        counts_grid = tk.Frame(counts_outer)
        counts_grid.pack(fill=tk.X)

        self.card_pending = self._make_count_card(counts_grid, "未編集", "0")
        self.card_skipped = self._make_count_card(counts_grid, "保留", "0")
        self.card_done = self._make_count_card(counts_grid, "承認待ち", "0")
        self.card_approved = self._make_count_card(counts_grid, "承認済み", "0")

        self.card_pending["frame"].grid(row=0, column=0, padx=8, pady=4, sticky="nsew")
        self.card_skipped["frame"].grid(row=0, column=1, padx=8, pady=4, sticky="nsew")
        self.card_done["frame"].grid(row=0, column=2, padx=8, pady=4, sticky="nsew")
        self.card_approved["frame"].grid(row=0, column=3, padx=8, pady=4, sticky="nsew")

        for i in range(4):
            counts_grid.grid_columnconfigure(i, weight=1)

        # ===== モード起動 =====
        modes_outer = tk.LabelFrame(self.root, text="モード起動", padx=12, pady=12)
        modes_outer.pack(fill=tk.X, padx=16, pady=8)

        mode_row1 = tk.Frame(modes_outer)
        mode_row1.pack(fill=tk.X, pady=(0, 4))

        mode_row2 = tk.Frame(modes_outer)
        mode_row2.pack(fill=tk.X)

        self.btn_annotation_pending = tk.Button(
            mode_row1,
            text="作成モード（未編集画像）",
            command=self.launch_annotation_pending_mode,
            bg="#d9fdd3",
            fg="black",
            activebackground="#b7f0a8",
            activeforeground="black",
            width=22,
            height=2,
            bd=3,
            highlightthickness=2,
            highlightbackground="green",
            highlightcolor="green"
        )
        self.btn_annotation_pending.pack(side=tk.LEFT, padx=8, pady=4)

        self.btn_annotation_skipped = tk.Button(
            mode_row1,
            text="作成モード（保留画像）",
            command=self.launch_annotation_skipped_mode,
            bg="#e6f0ff",
            fg="black",
            activebackground="#cfe0ff",
            activeforeground="black",
            width=22,
            height=2,
            bd=3,
            highlightthickness=2,
            highlightbackground="#4a78c2",
            highlightcolor="#4a78c2"
        )
        self.btn_annotation_skipped.pack(side=tk.LEFT, padx=8, pady=4)

        self.btn_review = tk.Button(
            mode_row1,
            text="参照・修正・承認モードを開く",
            command=self.launch_review_mode,
            bg="#fff4cc",
            fg="black",
            activebackground="#ffe082",
            activeforeground="black",
            width=24,
            height=2,
            bd=3,
            highlightthickness=2,
            highlightbackground="#c9a500",
            highlightcolor="#c9a500"
        )
        self.btn_review.pack(side=tk.LEFT, padx=8, pady=4)

        self.btn_browser = tk.Button(
            mode_row2,
            text="閲覧モードを開く",
            command=self.launch_browser_mode,
            width=18,
            height=2
        )
        self.btn_browser.pack(side=tk.LEFT, padx=8, pady=4)

        self.btn_refresh = tk.Button(
            mode_row2,
            text="更新",
            command=self.refresh_counts,
            width=10,
            height=2
        )
        self.btn_refresh.pack(side=tk.LEFT, padx=8, pady=4)

        # ===== フォルダ操作 =====
        folders_outer = tk.LabelFrame(self.root, text="フォルダを開く", padx=12, pady=12)
        folders_outer.pack(fill=tk.X, padx=16, pady=8)

        row1 = tk.Frame(folders_outer)
        row1.pack(fill=tk.X, pady=4)

        row2 = tk.Frame(folders_outer)
        row2.pack(fill=tk.X, pady=4)

        tk.Button(row1, text="pending 画像", width=16,
                  command=lambda: self.open_in_finder(IMAGES_DIR / PENDING_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row1, text="skipped 画像", width=16,
                  command=lambda: self.open_in_finder(IMAGES_DIR / SKIPPED_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row1, text="done 画像", width=16,
                  command=lambda: self.open_in_finder(IMAGES_DIR / DONE_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row1, text="approved 画像", width=16,
                  command=lambda: self.open_in_finder(IMAGES_DIR / APPROVED_DIRNAME)).pack(side=tk.LEFT, padx=6)

        tk.Button(row2, text="done overlay", width=16,
                  command=lambda: self.open_in_finder(OVERLAYS_DIR / DONE_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row2, text="approved overlay", width=16,
                  command=lambda: self.open_in_finder(OVERLAYS_DIR / APPROVED_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row2, text="done mask", width=16,
                  command=lambda: self.open_in_finder(MASKS_DIR / DONE_DIRNAME)).pack(side=tk.LEFT, padx=6)
        tk.Button(row2, text="done meta", width=16,
                  command=lambda: self.open_in_finder(META_DIR / DONE_DIRNAME)).pack(side=tk.LEFT, padx=6)

        # ===== パス表示 =====
        info_outer = tk.LabelFrame(self.root, text="プロジェクト情報", padx=12, pady=12)
        info_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 16))

        info_text = (
            f"Python: {self.python_executable}\n"
            f"App フォルダ: {APP_DIR}\n"
            f"Data フォルダ: {PROJECT_ROOT}\n\n"
            f"作成モード: {APP_DIR / 'liga_annotation_app.py'}\n"
            f"レビュー: {APP_DIR / 'liga_review_approve_app.py'}\n"
            f"閲覧モード(予定): {APP_DIR / 'liga_browser_app.py'}"
        )

        self.lbl_info = tk.Label(info_outer, text=info_text, justify=tk.LEFT, anchor="nw")
        self.lbl_info.pack(fill=tk.BOTH, expand=True)

    def _make_count_card(self, parent, title: str, value: str):
        frame = tk.Frame(parent, bd=2, relief=tk.GROOVE, padx=12, pady=12)
        lbl_title = tk.Label(frame, text=title, font=("", 12, "bold"))
        lbl_title.pack(pady=(0, 8))
        lbl_value = tk.Label(frame, text=value, font=("", 24, "bold"))
        lbl_value.pack()
        return {"frame": frame, "title": lbl_title, "value": lbl_value}

    def refresh_counts(self):
        ensure_project_dirs()

        pending_count = count_images_in_dir(IMAGES_DIR / PENDING_DIRNAME)
        skipped_count = count_images_in_dir(IMAGES_DIR / SKIPPED_DIRNAME)
        done_count = count_images_in_dir(IMAGES_DIR / DONE_DIRNAME)
        approved_count = count_images_in_dir(IMAGES_DIR / APPROVED_DIRNAME)

        self.card_pending["value"].config(text=str(pending_count))
        self.card_skipped["value"].config(text=str(skipped_count))
        self.card_done["value"].config(text=str(done_count))
        self.card_approved["value"].config(text=str(approved_count))

    def _launch_script(self, script_path: Path, extra_args=None):
        if extra_args is None:
            extra_args = []

        if not script_path.exists():
            messagebox.showerror("エラー", f"スクリプトが見つかりません。\n{script_path}")
            return

        cmd = [self.python_executable, str(script_path)] + extra_args

        try:
            subprocess.Popen(cmd, cwd=str(APP_DIR.parent))
        except Exception as e:
            messagebox.showerror("起動エラー", f"スクリプト起動に失敗しました。\n{e}")

    def launch_annotation_pending_mode(self):
        self._launch_script(APP_DIR / "liga_annotation_app.py", ["--source", "pending"])

    def launch_annotation_skipped_mode(self):
        self._launch_script(APP_DIR / "liga_annotation_app.py", ["--source", "skipped"])

    def launch_review_mode(self):
        self._launch_script(APP_DIR / "liga_review_approve_app.py")

    def launch_browser_mode(self):
        browser_path = APP_DIR / "liga_browser_app.py"
        if browser_path.exists():
            self._launch_script(browser_path)
        else:
            messagebox.showinfo(
                "閲覧モード",
                "liga_browser_app.py はまだありません。\n\n"
                "先にランチャーと作成/レビュー導線を固めて、次に閲覧モードを作る想定です。"
            )

    def open_in_finder(self, target: Path):
        try:
            target.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            messagebox.showerror("フォルダ表示エラー", f"フォルダを開けませんでした。\n{e}")


def main():
    if not TK_AVAILABLE:
        print("tkinter が見つからないため GUI を起動できません。")
        return

    ensure_project_dirs()

    root = tk.Tk()
    app = IgaLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()