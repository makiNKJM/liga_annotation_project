# liga_browser_app.py
# 閲覧モード
# - 状態別に画像を一覧表示
# - done は overlay を優先表示
# - 画像選択で右側にプレビュー
# - done の画像は参照・修正・承認モードで開ける

import sys
import subprocess
import json
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

from PIL import Image, ImageTk, ImageFile

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass


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


def list_images_in_dir(d: Path):
    if not d.exists():
        return []
    return sorted([p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS])


class LigaBrowserApp:
    def __init__(self, root):
        self.root = root
        self.root.title("lIGA 閲覧モード")
        self.root.geometry("1260x820")
        self.root.minsize(1000, 700)

        self.python_executable = sys.executable

        self.state_var = tk.StringVar(value=DONE_DIRNAME)

        self.entries = []
        self.selected_index = None

        self.thumb_refs = []
        self.preview_photo = None
        self.preview_mode = tk.StringVar(value="overlay")

        self.build_ui()
        self.refresh_entries()

    def build_ui(self):
        # ===== 上段 =====
        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=12, pady=(12, 8))

        tk.Label(top, text="閲覧モード", font=("", 16, "bold")).pack(side=tk.LEFT, padx=(0, 16))

        radio_wrap = tk.LabelFrame(top, text="状態")
        radio_wrap.pack(side=tk.LEFT, padx=(0, 12))

        tk.Radiobutton(
            radio_wrap, text="未編集", variable=self.state_var, value=PENDING_DIRNAME,
            command=self.refresh_entries
        ).pack(side=tk.LEFT, padx=6)

        tk.Radiobutton(
            radio_wrap, text="保留", variable=self.state_var, value=SKIPPED_DIRNAME,
            command=self.refresh_entries
        ).pack(side=tk.LEFT, padx=6)

        tk.Radiobutton(
            radio_wrap, text="承認待ち", variable=self.state_var, value=DONE_DIRNAME,
            command=self.refresh_entries
        ).pack(side=tk.LEFT, padx=6)

        tk.Radiobutton(
            radio_wrap, text="承認済み", variable=self.state_var, value=APPROVED_DIRNAME,
            command=self.refresh_entries
        ).pack(side=tk.LEFT, padx=6)

        self.lbl_count = tk.Label(top, text="0件")
        self.lbl_count.pack(side=tk.LEFT, padx=(8, 16))

        tk.Button(top, text="更新", command=self.refresh_entries, width=10).pack(side=tk.RIGHT)

        # ===== 本体 2ペイン =====
        body = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # 左: 一覧
        left = tk.Frame(body)
        body.add(left, minsize=320)

        tk.Label(left, text="サムネイル一覧", font=("", 12, "bold")).pack(anchor="w", pady=(0, 6))

        self.list_canvas = tk.Canvas(left, bg="#f5f5f5")
        self.list_scroll = tk.Scrollbar(left, orient=tk.VERTICAL, command=self.list_canvas.yview)
        self.list_canvas.configure(yscrollcommand=self.list_scroll.set)

        self.list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.list_inner = tk.Frame(self.list_canvas)
        self.list_canvas_window = self.list_canvas.create_window((0, 0), window=self.list_inner, anchor="nw")

        self.list_inner.bind("<Configure>", self._on_list_inner_configure)
        self.list_canvas.bind("<Configure>", self._on_list_canvas_configure)
        self.list_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 右: プレビュー
        right = tk.Frame(body)
        body.add(right, minsize=520)

        header = tk.Frame(right)
        header.pack(fill=tk.X)

        tk.Label(header, text="プレビュー", font=("", 12, "bold")).pack(side=tk.LEFT, pady=(0, 6))

        preview_mode_frame = tk.Frame(header)
        preview_mode_frame.pack(side=tk.RIGHT, padx=(8, 0))

        tk.Radiobutton(
            preview_mode_frame,
            text="overlay",
            variable=self.preview_mode,
            value="overlay",
            command=self.refresh_selected_preview
        ).pack(side=tk.LEFT, padx=2)

        tk.Radiobutton(
            preview_mode_frame,
            text="元画像",
            variable=self.preview_mode,
            value="image",
            command=self.refresh_selected_preview
        ).pack(side=tk.LEFT, padx=2)

        self.btn_open_review = tk.Button(
            header,
            text="この画像をレビューで開く",
            command=self.open_selected_in_review,
            state=tk.DISABLED,
            bg="#fff4cc",
            fg="black",
            activebackground="#ffe082",
            activeforeground="black",
            disabledforeground="black",
            bd=3,
            highlightthickness=2,
            highlightbackground="#c9a500",
            highlightcolor="#c9a500"
        )
        self.btn_open_review.pack(side=tk.RIGHT, padx=(0, 8))

        self.preview_name = tk.Label(right, text="画像未選択", anchor="w", justify=tk.LEFT)
        self.preview_name.pack(fill=tk.X, pady=(0, 6))

        self.preview_canvas = tk.Canvas(right, bg="#2f2f2f", height=520)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        meta_box = tk.LabelFrame(right, text="情報")
        meta_box.pack(fill=tk.X, pady=(8, 0))

        self.lbl_meta = tk.Label(meta_box, text="meta: -", justify=tk.LEFT, anchor="w")
        self.lbl_meta.pack(fill=tk.X, padx=8, pady=8)

    def _on_list_inner_configure(self, event):
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))

    def _on_list_canvas_configure(self, event):
        self.list_canvas.itemconfigure(self.list_canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        try:
            self.list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def get_current_state(self):
        return self.state_var.get()

    def get_image_dir(self):
        return IMAGES_DIR / self.get_current_state()

    def get_overlay_dir(self):
        return OVERLAYS_DIR / self.get_current_state()

    def get_meta_dir(self):
        return META_DIR / self.get_current_state()

    def get_mask_dir(self):
        return MASKS_DIR / self.get_current_state()

    def refresh_entries(self):
        ensure_project_dirs()

        for w in self.list_inner.winfo_children():
            w.destroy()

        self.thumb_refs.clear()
        self.entries.clear()
        self.selected_index = None
        self.preview_canvas.delete("all")
        self.preview_name.config(text="画像未選択")
        self.lbl_meta.config(text="meta: -")

        state = self.get_current_state()
        image_dir = self.get_image_dir()
        overlay_dir = self.get_overlay_dir()
        meta_dir = self.get_meta_dir()

        image_files = list_images_in_dir(image_dir)
        self.lbl_count.config(text=f"{len(image_files)}件")

        for idx, image_path in enumerate(image_files):
            stem = image_path.stem

            overlay_path = overlay_dir / f"{stem}_overlay.png"
            meta_path = meta_dir / f"{stem}_meta.json"

            thumb_source = overlay_path if overlay_path.exists() else image_path

            entry = {
                "stem": stem,
                "image_path": image_path,
                "overlay_path": overlay_path,
                "meta_path": meta_path,
                "thumb_source": thumb_source,
            }
            self.entries.append(entry)

            self._add_thumbnail_row(idx, entry)

        self._update_review_button_state()

    def _add_thumbnail_row(self, idx, entry):
        outer = tk.Frame(self.list_inner, bd=1, relief=tk.GROOVE, padx=6, pady=6)
        outer.pack(fill=tk.X, padx=4, pady=4)

        thumb_label = tk.Label(outer)
        thumb_label.pack(side=tk.LEFT, padx=(0, 8))

        img = self._load_thumbnail(entry["thumb_source"], size=(120, 90))
        if img is not None:
            thumb_label.configure(image=img)
            self.thumb_refs.append(img)
        else:
            thumb_label.configure(text="No Image", width=16, height=6)

        text_wrap = tk.Frame(outer)
        text_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(text_wrap, text=entry["image_path"].name, anchor="w", justify=tk.LEFT).pack(fill=tk.X)

        meta = self._read_meta(entry["meta_path"])
        status = meta.get("status", "-")
        updated = meta.get("updated_at", "")
        tk.Label(
            text_wrap,
            text=f"status: {status}    updated: {updated}",
            anchor="w",
            justify=tk.LEFT,
            fg="#444444"
        ).pack(fill=tk.X)

        def on_click(_event=None, i=idx):
            self.select_index(i)

        outer.bind("<Button-1>", on_click)
        thumb_label.bind("<Button-1>", on_click)
        text_wrap.bind("<Button-1>", on_click)

        entry["row_widget"] = outer

    def _load_thumbnail(self, path: Path, size=(120, 90)):
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail(size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _load_preview(self, path: Path, max_size=(760, 560)):
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _read_meta(self, meta_path: Path):
        if not meta_path.exists():
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
        
    def _show_preview_for_index(self, idx: int):
        entry = self.entries[idx]

        if self.preview_mode.get() == "image":
            preview_source = entry["image_path"]
        else:
            preview_source = entry["overlay_path"] if entry["overlay_path"].exists() else entry["image_path"]

        photo = self._load_preview(preview_source)
        self.preview_canvas.delete("all")

        if photo is not None:
            self.preview_photo = photo
            self.preview_canvas.create_image(10, 10, anchor="nw", image=self.preview_photo)
        else:
            self.preview_canvas.create_text(80, 60, text="プレビュー読込失敗", fill="white", anchor="nw")

        mode_label = "元画像" if self.preview_mode.get() == "image" else "overlay"
        self.preview_name.config(
            text=f"{entry['image_path'].name}\n表示: {preview_source.name} ({mode_label})"
        )

    def select_index(self, idx: int):
        if not (0 <= idx < len(self.entries)):
            return

        self.selected_index = idx

        for i, entry in enumerate(self.entries):
            row = entry.get("row_widget")
            if row is None:
                continue
            if i == idx:
                row.config(bg="#dbeafe")
            else:
                row.config(bg=self.root.cget("bg"))

        entry = self.entries[idx]
        self._show_preview_for_index(idx)

        meta = self._read_meta(entry["meta_path"])
        if meta:
            text = (
                f"status: {meta.get('status', '-')}\n"
                f"annotator: {meta.get('annotator', '')}\n"
                f"reviewer: {meta.get('reviewer', '')}\n"
                f"created_at: {meta.get('created_at', '')}\n"
                f"updated_at: {meta.get('updated_at', '')}\n"
                f"comment: {meta.get('comment', '')}"
            )
        else:
            text = "meta: なし"
        self.lbl_meta.config(text=text)

        self._update_review_button_state()

    def refresh_selected_preview(self):
        if self.selected_index is None:
            return
        self._show_preview_for_index(self.selected_index)

    def _update_review_button_state(self):
        state = self.get_current_state()
        if state == DONE_DIRNAME and self.selected_index is not None:
            self.btn_open_review.config(state=tk.NORMAL)
        else:
            self.btn_open_review.config(state=tk.DISABLED)

    def open_selected_in_review(self):
        if self.selected_index is None:
            return
        if self.get_current_state() != DONE_DIRNAME:
            messagebox.showinfo("案内", "レビュー起動は承認待ち画像（03_done）のみ対応です。")
            return

        entry = self.entries[self.selected_index]
        review_script = APP_DIR / "liga_review_approve_app.py"
        if not review_script.exists():
            messagebox.showerror("エラー", f"レビューアプリが見つかりません。\n{review_script}")
            return

        cmd = [
            sys.executable,
            str(review_script),
            "--input",
            str(entry["image_path"])
        ]

        try:
            subprocess.Popen(cmd, cwd=str(APP_DIR.parent))
        except Exception as e:
            messagebox.showerror("起動エラー", f"レビューアプリを起動できませんでした。\n{e}")


def main():
    if not TK_AVAILABLE:
        print("tkinter が見つからないため GUI を起動できません。")
        return

    ensure_project_dirs()

    root = tk.Tk()
    app = LigaBrowserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()