# liga_annotation_app.py
# フリーペイントで lIGA 用 5クラスマスク（0〜4）を作成する専用アプリ
# 依存: Pillow (pip install pillow)

import argparse
from pathlib import Path
import glob
import os
import sys
import warnings
import json
import shutil
from datetime import datetime

# --- tkinter は環境に無い場合があるためガード ---
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
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

        @staticmethod
        def askyesno(title, msg, **kwargs):
            # コンソール環境用の簡易確認
            print(f"[QUESTION] {title}: {msg}  (y/n)")
            try:
                ans = input("> ").strip().lower()
                return ans in ("y", "yes")
            except Exception:
                return False

    class _DummyFileDialog:
        @staticmethod
        def askopenfilename(**kwargs):
            return ""

        @staticmethod
        def asksaveasfilename(**kwargs):
            return ""

        @staticmethod
        def askdirectory(**kwargs):
            return ""

    filedialog = _DummyFileDialog()
    messagebox = _DummyMessageBox()

from PIL import Image, ImageDraw, ImageFile
try:
    from PIL import ImageTk as PIL_ImageTk
    IMAGETK_AVAILABLE = True
except Exception:
    PIL_ImageTk = None
    IMAGETK_AVAILABLE = False
from PIL.Image import DecompressionBombWarning

# ====== 超大判画像対応 ======
Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

# HEICファイル対応
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    print("HEIC support enabled")
except ImportError:
    print("HEIC support not available (pillow-heif not installed)")

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif")

PROJECT_ROOT = Path("data")
IMAGES_DIR = PROJECT_ROOT / "images"
MASKS_DIR = PROJECT_ROOT / "masks"
OVERLAYS_DIR = PROJECT_ROOT / "overlays"
META_DIR = PROJECT_ROOT / "meta"

PENDING_DIRNAME = "01_pending"
SKIPPED_DIRNAME = "02_skipped"
DONE_DIRNAME = "03_done"
APPROVED_DIRNAME = "04_approved"

def expand_inputs_from_dir(in_dir):
    p = Path(in_dir)
    if not p.exists() or not p.is_dir():
        return []
    return sorted([str(x) for x in p.iterdir() if x.suffix.lower() in SUPPORTED_EXTS])


def expand_inputs(inputs_raw):
    if not inputs_raw:
        return []
    results = []
    for token in inputs_raw:
        matched = glob.glob(token)
        results.extend(matched if matched else [token])
    uniq, seen = [], set()
    for q in results:
        q = str(Path(q))
        if q not in seen and Path(q).exists():
            uniq.append(q)
            seen.add(q)
    return uniq

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_project_dirs():
    for base in [IMAGES_DIR, MASKS_DIR, OVERLAYS_DIR, META_DIR]:
        for sub in [PENDING_DIRNAME, SKIPPED_DIRNAME, DONE_DIRNAME, APPROVED_DIRNAME]:
            (base / sub).mkdir(parents=True, exist_ok=True)


def find_image_path_by_stem(stem: str, state_dirname: str):
    d = IMAGES_DIR / state_dirname
    if not d.exists():
        return None
    for ext in SUPPORTED_EXTS:
        p = d / f"{stem}{ext}"
        if p.exists():
            return p
    return None


class FreePaintMaskApp:
    """
    フリーペイントで lIGA 用 5クラスマスク(0〜4)を作る専用アプリ。
    - self.image: 元画像 (RGBA)
    - self.mask:  ラベルマスク (L モード, 0〜4)
    """

    def bring_to_front(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def __init__(self, root, inputs=None, output_dir=None):
        self.root = root
        self.root.title("フリーペイント lIGAマスク作成（0〜4）")
        self.root.geometry("900x650")

        # 入出力管理
        self.inputs = inputs or []
        self.cur_index = 0
        self.output_dir = Path(output_dir) if output_dir else None
        self.chosen_output_dir = None
        self.skipped = []
        self.current_input_path = None

        # 画像状態
        self.image = None        # PIL.Image (RGBA)
        self.display_image = None
        self.photo = None
        self.mask = None         # PIL.Image (L, 0〜4)
        self.mask_draw = None

        # 表示オーバーレイ（クラス別）
        self.class_colors = {
            1: (0, 255, 255, 90),   # lIGA1: cyan
            2: (0, 255, 0, 90),     # lIGA2: green
            3: (255, 255, 0, 90),   # lIGA3: yellow
            4: (255, 0, 0, 90),     # lIGA4: red
        }

        # 表示ON/OFF状態
        self.visible_labels = {1: True, 2: True, 3: True, 4: True}

        # ツール状態
        self.is_erasing = False
        self.is_fill_mode = False
        self.brush_size = 20

        # lIGA 用クラスラベル（1〜4）, 0は背景
        self.current_label = 1
        self.label_buttons = {}

        # 元画像だけを表示するかどうか（マスク無しプレビュー）
        self.show_overlay = True

        # ドラッグ
        self.prev_ix = None
        self.prev_iy = None
        self.is_drawing = False

        # 履歴
        self.history = []
        self.redo_stack = []
        self.history_limit = 120

        # 移動モード
        self.move_mode = False

        # ズーム/パン状態
        self.view_x = 0.0
        self.view_y = 0.0
        self.view_scale = 1.0
        self.base_scale = 1.0
        self._hq_job = None

        self._panning = False
        self._pan_start = (0, 0)
        self._pan_view = (0.0, 0.0)

        # 低ズーム用ミップ
        self._mips = []
        self._mip_min_edge = 768

        # UI構築
        self.build_ui()
        self.bring_to_front()

        # 起動フロー
        if self.inputs:
            self.load_current_input()
        else:
            messagebox.showerror("エラー", "対象フォルダに画像がありません。")
            self.root.after(100, self.root.destroy)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------ UI ------------
    def build_ui(self):
        top = tk.Frame(self.root)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(8, 4))

        left_head = tk.Frame(top)
        left_head.pack(side=tk.LEFT, fill=tk.X, expand=True)

        right_head = tk.Frame(top)
        right_head.pack(side=tk.RIGHT)

        # 進捗ラベル
        self.lbl_info = tk.Label(left_head, text="画像未読込", anchor="w")
        self.lbl_info.pack(side=tk.LEFT, padx=(0, 10))

        # ===== 上段：保存ボタン群（右側） =====
        self.btn_save = tk.Button(
            right_head,
            text="保存（次へ）",
            command=self.save_mask,
            state=tk.DISABLED,
            bg="#d9fdd3",
            fg="black",
            activebackground="#b7f0a8",
            activeforeground="black",
            disabledforeground="black",
            highlightbackground="green",
            highlightcolor="green",
            highlightthickness=2,
            bd=3
        )
        self.btn_save_empty = tk.Button(right_head, text="皮疹なしで保存（次へ）", command=self.save_empty_mask)
        self.btn_skip = tk.Button(right_head, text="スキップ（次へ）", command=self.skip_current)
        self.btn_cancel = tk.Button(right_head, text="強制停止", command=self.force_quit)

        # 右から並べる（見た目の好みで順は変えてOK）
        self.btn_cancel.pack(side=tk.RIGHT, padx=6)
        self.btn_skip.pack(side=tk.RIGHT, padx=6)
        self.btn_save_empty.pack(side=tk.RIGHT, padx=6)
        self.btn_save.pack(side=tk.RIGHT, padx=6)

        # ツール行
        tools = tk.Frame(self.root)
        tools.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 8))

        tools_row1 = tk.Frame(tools)
        tools_row1.pack(side=tk.TOP, fill=tk.X)

        tools_row2 = tk.Frame(tools)
        tools_row2.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))

        tools_row3 = tk.Frame(tools)
        tools_row3.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))

        # Row1: ブラシ系
        self.brush_scale = tk.Scale(tools_row1, from_=5, to=100, orient=tk.HORIZONTAL, length=200,
                                    label="ブラシ:", command=self.on_scale_change)
        self.brush_scale.set(self.brush_size)
        self.brush_scale.bind("<ButtonPress-1>", self.on_brush_scale_press)
        self.brush_scale.bind("<B1-Motion>", self.on_brush_scale_drag)
        self.brush_scale.bind("<ButtonRelease-1>", self.on_brush_scale_release)
        self.brush_scale.pack(side=tk.LEFT, padx=6)

        self.btn_eraser = tk.Button(tools_row1, text=self.eraser_label(), command=self.toggle_eraser)
        self.btn_eraser.pack(side=tk.LEFT, padx=6)

        self.btn_fill = tk.Button(tools_row1, text=self.fill_label(), command=self.toggle_fill)
        self.btn_fill.pack(side=tk.LEFT, padx=6)

        self.btn_undo = tk.Button(tools_row1, text="１つ戻る", command=self.undo, state=tk.DISABLED)
        self.btn_undo.pack(side=tk.LEFT, padx=8)

        self.btn_redo = tk.Button(tools_row1, text="１つ進む", command=self.redo, state=tk.DISABLED)
        self.btn_redo.pack(side=tk.LEFT, padx=6)


                # ---- Row2 左: lIGA ボタン ----
        liga_frame = tk.Frame(tools_row2)
        liga_frame.pack(side=tk.LEFT, padx=(0, 10))

        for k, label in [
            (1, "lIGA1(わずか)"),
            (2, "lIGA2(軽度)"),
            (3, "lIGA3(中等度)"),
            (4, "lIGA4(重度)"),
        ]:
            btn = tk.Button(
                liga_frame,
                text=label,
                command=lambda v=k: self.set_label(v),
                width=12,
                bd=2,
                highlightthickness=2
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.label_buttons[k] = btn

        # 選択状態の反映
        self.update_label_buttons()

        # Row2: パン&ズーム
        self.var_move = tk.BooleanVar(value=False)
        self.chk_move = tk.Checkbutton(
            tools_row2, text="移動モード（ドラッグでパン）",
            variable=self.var_move, command=self.on_toggle_move
        )
        self.chk_move.pack(side=tk.LEFT, padx=(0, 10))

        zoom_wrap = tk.Frame(tools_row2)
        zoom_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.zoom_slider = tk.Scale(
            zoom_wrap,
            from_=100,
            to=500,
            orient=tk.HORIZONTAL,
            label="ズーム(%)",
            command=self.on_zoom_slider_change
        )
        self.zoom_slider.set(100)
        self.zoom_slider.pack(side=tk.TOP, fill=tk.X, expand=True)

        # ブラシプレビュー
        self.show_brush_preview = False
        self._slider_operating = False

        # ★ 元画像のみ表示トグルボタン
        self.btn_toggle_overlay = tk.Button(
            tools_row2,
            text="元画像のみ",  # 今はマスク表示中なので「押すと元画像だけ」の意味
            command=self.toggle_overlay
        )
        self.btn_toggle_overlay.pack(side=tk.RIGHT, padx=8)

        # Row3: 表示ON/OFF
        vis_frame = tk.LabelFrame(tools_row3, text="表示ON/OFF")
        vis_frame.pack(side=tk.LEFT, padx=(0, 10))

        self.var_show_1 = tk.BooleanVar(value=True)
        self.var_show_2 = tk.BooleanVar(value=True)
        self.var_show_3 = tk.BooleanVar(value=True)
        self.var_show_4 = tk.BooleanVar(value=True)

        tk.Checkbutton(
            vis_frame, text="lIGA1",
            variable=self.var_show_1,
            command=self.on_toggle_visibility
        ).pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(
            vis_frame, text="lIGA2",
            variable=self.var_show_2,
            command=self.on_toggle_visibility
        ).pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(
            vis_frame, text="lIGA3",
            variable=self.var_show_3,
            command=self.on_toggle_visibility
        ).pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(
            vis_frame, text="lIGA4",
            variable=self.var_show_4,
            command=self.on_toggle_visibility
        ).pack(side=tk.LEFT, padx=4)

        # キャンバス
        self.canvas_frame = tk.Frame(self.root, bd=1, relief=tk.SUNKEN)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#2f2f2f")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self.on_canvas_resize)
        for btn in (1, 2, 3):
            self.canvas.bind(f"<ButtonPress-{btn}>", self.on_press)
            self.canvas.bind(f"<B{btn}-Motion>", self.on_drag)
            self.canvas.bind(f"<ButtonRelease-{btn}>", self.on_release)

        self._bind_mousewheel(self.canvas, self.on_wheel)
        self.root.bind("<Key>", self.on_key)

        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)

    # ------------ lIGAボタン制御 ------------
    def set_label(self, label: int):
        self.current_label = int(label)
        self.update_label_buttons()
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass
        if self._should_show_brush_preview():
            self.draw_brush_preview()

    def update_label_buttons(self):
        for k, btn in self.label_buttons.items():
            color = self.get_label_color_rgb(k)

            if k == self.current_label:
                btn.config(
                    relief=tk.SUNKEN,
                    fg="black",
                    activeforeground="black",
                    highlightbackground=color,
                    highlightcolor=color,
                    highlightthickness=3,
                    bd=3
                )
            else:
                btn.config(
                    relief=tk.RAISED,
                    fg="black",
                    activeforeground="black",
                    highlightbackground=self.root.cget("bg"),
                    highlightcolor=self.root.cget("bg"),
                    highlightthickness=1,
                    bd=2
                )

    def get_label_color_rgb(self, label: int) -> str:
        rgba = self.class_colors.get(label, (0, 255, 0, 90))
        r, g, b = rgba[:3]
        return f"#{r:02x}{g:02x}{b:02x}"

    def toggle_overlay(self):
        self.show_overlay = not self.show_overlay
        if self.show_overlay:
            self.btn_toggle_overlay.config(text="元画像のみ")
        else:
            self.btn_toggle_overlay.config(text="マスク表示")
        self._render(mode="final")

    def on_toggle_visibility(self):
        self.visible_labels[1] = self.var_show_1.get()
        self.visible_labels[2] = self.var_show_2.get()
        self.visible_labels[3] = self.var_show_3.get()
        self.visible_labels[4] = self.var_show_4.get()
        self._render(mode="final")

    # ------------ キー処理 ------------
    def on_key(self, ev):
        k = (ev.keysym or "").lower()
        if k == "s":
            self.skip_current()
        elif k == "q":
            self.force_quit()

    def update_header(self):
        if self.image is None:
            self.lbl_info.config(text="画像未読込")
            return
        total = max(1, len(self.inputs))
        cur = min(self.cur_index + 1, total)
        name = getattr(self, "current_name", "（ダイアログ読込）")
        self.lbl_info.config(text=f"{cur}/{total}: {name}")

    def eraser_label(self):
        return "消しゴム：ON" if self.is_erasing else "消しゴム：OFF"

    def fill_label(self):
        return "塗りつぶし：ON" if self.is_fill_mode else "塗りつぶし：OFF"

    def force_quit(self):
        try:
            self.print_skip_summary()
            self.root.destroy()
        finally:
            sys.exit(130)

    def skip_current(self):
        name = getattr(self, "current_name", None)
        stem = self._infer_stem()

        src_image_path = self.current_input_path if self.current_input_path else find_image_path_by_stem(stem, PENDING_DIRNAME)

        if name:
            self.skipped.append(name)
            print(f"[SKIP] {name}")

        try:
            if src_image_path is not None and src_image_path.exists():
                dest_image_path = self._get_image_dest_path(src_image_path, SKIPPED_DIRNAME)
                shutil.move(str(src_image_path), str(dest_image_path))
                print(f"[MOVED TO SKIPPED] {dest_image_path}")
        except Exception as e:
            messagebox.showerror("スキップエラー", f"スキップ時の画像移動に失敗しました。\n{e}")
            return

        self._go_next_or_finish()

    # ------------ スタートダイアログ ------------
    def show_start_dialog(self):
        """起動時に『入力フォルダ』『出力フォルダ』をGUIで選択するダイアログ"""
        self.start_win = tk.Toplevel(self.root)
        self.start_win.title("入力フォルダと出力フォルダを選択")
        self.start_win.grab_set()

        frm = tk.Frame(self.start_win, padx=12, pady=12)
        frm.pack(fill=tk.BOTH, expand=True)

        # ===== 入力フォルダ =====
        tk.Label(frm, text="入力フォルダ（元画像）").grid(row=0, column=0, sticky="w")
        self.entry_in_dir = tk.Entry(frm, width=60)
        self.entry_in_dir.grid(row=1, column=0, columnspan=3, sticky="we", pady=(2, 8))

        def browse_in():
            d = filedialog.askdirectory(title="入力フォルダを選択")
            if d:
                self.entry_in_dir.delete(0, tk.END)
                self.entry_in_dir.insert(0, d)

        tk.Button(frm, text="参照", command=browse_in).grid(row=1, column=3, padx=6)

        # ===== 出力フォルダ =====
        tk.Label(frm, text="出力フォルダ（マスク保存先）").grid(row=2, column=0, sticky="w")
        self.entry_out_dir = tk.Entry(frm, width=60)
        self.entry_out_dir.grid(row=3, column=0, columnspan=3, sticky="we", pady=(2, 8))

        def browse_out():
            d = filedialog.askdirectory(title="出力フォルダを選択")
            if d:
                self.entry_out_dir.delete(0, tk.END)
                self.entry_out_dir.insert(0, d)

        tk.Button(frm, text="参照", command=browse_out).grid(row=3, column=3, padx=6)

        # ===== ボタン行 =====
        def go():
            in_dir = self.entry_in_dir.get().strip()
            out_dir = self.entry_out_dir.get().strip()

            if not in_dir:
                messagebox.showinfo("確認", "入力フォルダを選択してください。", parent=self.start_win)
                return
            if not out_dir:
                messagebox.showinfo("確認", "出力フォルダを選択してください。", parent=self.start_win)
                return

            in_path = Path(in_dir)
            if not in_path.exists() or not in_path.is_dir():
                messagebox.showerror("エラー", "入力フォルダが存在しません。", parent=self.start_win)
                return

            inputs = expand_inputs_from_dir(in_dir)
            if not inputs:
                messagebox.showerror("エラー", "入力フォルダ内に対応する画像ファイルがありません。", parent=self.start_win)
                return

            self.inputs = inputs
            self.cur_index = 0
            self.output_dir = Path(out_dir)
            self.chosen_output_dir = self.output_dir

            ok = self.load_image_from_path(self.inputs[0])
            if ok:
                self.current_name = Path(self.inputs[0]).name
                self.update_header()
                self.start_win.destroy()

        btn_frame = tk.Frame(frm)
        btn_frame.grid(row=4, column=0, columnspan=4, pady=(10, 0), sticky="w")

        tk.Button(btn_frame, text="開始", command=go).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_frame, text="キャンセル", command=self.start_win.destroy).pack(side=tk.LEFT)

        self.start_win.protocol("WM_DELETE_WINDOW", self.start_win.destroy)

    # ------------ 入力ロード ------------
    def load_current_input(self):
        if not (0 <= self.cur_index < len(self.inputs)):
            return
        path = self.inputs[self.cur_index]
        self.current_input_path = Path(path)
        ok = self.load_image_from_path(path)
        if ok:
            self.current_name = Path(path).name
            self.update_header()

    def _build_mipmaps(self):
        self._mips = [(1.0, self.image)]
        iw, ih = self.image.size
        scale = 1.0
        img = self.image
        while min(iw, ih) > self._mip_min_edge * 2:
            try:
                img = img.reduce(2)
            except Exception:
                img = img.resize((max(1, iw // 2), max(1, ih // 2)), Image.Resampling.BOX)
            scale *= 0.5
            iw, ih = img.size
            self._mips.append((scale, img))
        self._mips.sort(key=lambda t: t[0], reverse=True)

    def _choose_mip(self, z: float):
        if not self._mips:
            return self.image, 1.0
        best = self._mips[0]
        best_err = float('inf')
        for m, img in self._mips:
            ratio = z / m
            err = (ratio - 1.0) * (ratio - 1.0)
            if err < best_err:
                best_err = err
                best = (m, img)
        return best[1], best[0]

    def load_image_from_path(self, path):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DecompressionBombWarning)
                img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("読み込みエラー", f"画像を開けませんでした。\n{e}")
            return False

        self.image = img
        self._build_mipmaps()

        # ラベルマスク（L, 0で初期化）
        self.mask = Image.new("L", self.image.size, 0)
        self.mask_draw = ImageDraw.Draw(self.mask)

        self.history.clear()
        self.redo_stack.clear()
        self.push_history()
        self.update_buttons_state()

        self.view_scale = 1.0
        self.view_x = self.view_y = 0.0
        self.zoom_slider.set(100)
        self.root.after(100, self._fit_to_canvas)
        self.refresh_display()
        return True

    def _fit_to_canvas(self):
        if self.image is None:
            return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.image.size

        zoom = min(cw / iw, ch / ih)
        self.base_scale = max(1e-6, zoom)
        self.view_scale = self.base_scale

        new_w = iw * self.view_scale
        new_h = ih * self.view_scale
        self.view_x = (cw - new_w) / 2.0
        self.view_y = (ch - new_h) / 2.0

        self.zoom_slider.set(100)
        self.refresh_display()

    # ------------ 表示更新 ------------
    def on_canvas_resize(self, event):
        if self.image is not None:
            self._fit_to_canvas()
            self._render(mode="fast")
            self._schedule_hq()

    def refresh_display(self):
        self._render(mode="final")

    def _schedule_hq(self, delay_ms: int = 120):
        if self._hq_job is not None:
            try:
                self.root.after_cancel(self._hq_job)
            except Exception:
                pass
            self._hq_job = None
        self._hq_job = self.root.after(delay_ms, lambda: self._render(mode="final"))

    def _render(self, mode: str = "final"):
        if self.image is None:
            self.canvas.delete("all")
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.image.size
        z = max(1e-6, float(self.view_scale))

        x0 = self.view_x
        y0 = self.view_y
        x1 = x0 + iw * z
        y1 = y0 + ih * z

        vis_l = max(0, int(x0))
        vis_t = max(0, int(y0))
        vis_r = min(cw, int(x1))
        vis_b = min(ch, int(y1))

        if vis_r <= vis_l or vis_b <= vis_t:
            self.canvas.delete("all")
            return

        src_l = max(0, int((vis_l - x0) / z))
        src_t = max(0, int((vis_t - y0) / z))
        src_r = min(iw, int((vis_r - x0) / z))
        src_b = min(ih, int((vis_b - y0) / z))

        mip_img, m = self._choose_mip(z)
        m_l = int(src_l * m)
        m_t = int(src_t * m)
        m_r = int(src_r * m)
        m_b = int(src_b * m)
        mw, mh = mip_img.size
        m_l = max(0, min(mw, m_l))
        m_t = max(0, min(mh, m_t))
        m_r = max(0, min(mw, m_r))
        m_b = max(0, min(mh, m_b))
        if m_r <= m_l or m_b <= m_t:
            self.canvas.delete("all")
            return

        region_img = mip_img.crop((m_l, m_t, m_r, m_b))
        region_msk = self.mask.crop((src_l, src_t, src_r, src_b))

        dst_w = max(1, vis_r - vis_l)
        dst_h = max(1, vis_b - vis_t)

        interp_img = Image.Resampling.BILINEAR if mode == "fast" else Image.Resampling.LANCZOS
        interp_msk = Image.Resampling.NEAREST
        try:
            base = region_img.resize((dst_w, dst_h), interp_img, reducing_gap=3.0)
            labels_small = region_msk.resize((dst_w, dst_h), interp_msk, reducing_gap=3.0)
        except TypeError:
            base = region_img.resize((dst_w, dst_h), interp_img)
            labels_small = region_msk.resize((dst_w, dst_h), interp_msk)

        if self.show_overlay:
            overlay = Image.new("RGBA", (dst_w, dst_h), (0, 0, 0, 0))
            for cls, rgba in self.class_colors.items():
                if not self.visible_labels.get(cls, True):
                    continue
                cls_mask = labels_small.point(lambda v, c=cls: 255 if v == c else 0)
                if not cls_mask.getbbox():
                    continue
                tint = Image.new("RGBA", (dst_w, dst_h), rgba)
                overlay = Image.composite(tint, overlay, cls_mask)
            disp_partial = Image.alpha_composite(base.convert("RGBA"), overlay)
        else:
            disp_partial = base.convert("RGBA")

        canvas_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas_img.paste(disp_partial, (vis_l, vis_t))

        self.display_image = canvas_img
        if not IMAGETK_AVAILABLE:
            raise RuntimeError("ImageTk が利用できない環境です。")
        self.photo = PIL_ImageTk.PhotoImage(self.display_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        if (self._should_show_brush_preview() or self.show_brush_preview) and self.image is not None:
            self.draw_brush_preview()

    # ------------ 座標変換 ------------
    def canvas_to_image_xy(self, cx, cy):
        if self.image is None:
            return None, None
        ix = int((cx - self.view_x) / self.view_scale)
        iy = int((cy - self.view_y) / self.view_scale)
        iw, ih = self.image.size
        ix = max(0, min(iw - 1, ix))
        iy = max(0, min(ih - 1, iy))
        return ix, iy

    # ------------ プレビュー制御 ------------
    def _should_show_brush_preview(self) -> bool:
        return (not self.move_mode) and (not self.is_fill_mode)
    
    def _get_visible_class_set(self):
        visible = set()
        for cls in (1, 2, 3, 4):
            if self.visible_labels.get(cls, True):
                visible.add(cls)
        return visible
    
    def _erase_visible_labels_in_circle(self, cx, cy, radius):
        if self.mask is None:
            return

        visible = self._get_visible_class_set()
        if not visible:
            return

        px = self.mask.load()
        w, h = self.mask.size

        x0 = max(0, int(cx - radius))
        x1 = min(w - 1, int(cx + radius))
        y0 = max(0, int(cy - radius))
        y1 = min(h - 1, int(cy + radius))

        r2 = radius * radius

        for y in range(y0, y1 + 1):
            dy = y - cy
            for x in range(x0, x1 + 1):
                dx = x - cx
                if dx * dx + dy * dy <= r2:
                    if px[x, y] in visible:
                        px[x, y] = 0

    def _erase_visible_labels_along_line(self, x0, y0, x1, y1, radius):
        dist = max(abs(x1 - x0), abs(y1 - y0))
        steps = max(1, int(dist))

        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            self._erase_visible_labels_in_circle(x, y, radius)

    def on_mouse_move(self, event):
        if self.image is None:
            return
        if self._should_show_brush_preview():
            self.draw_brush_preview()

    def on_mouse_leave(self, event):
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass

    # ------------ マウスイベント ------------
    def on_press(self, event):
        if self.image is None:
            return
        if self.move_mode:
            self.on_pan_start(event)
            return

        ix, iy = self.canvas_to_image_xy(event.x, event.y)
        if ix is None:
            return

        if self.is_fill_mode:
            new_label = 0 if self.is_erasing else self.current_label
            try:
                ImageDraw.floodfill(self.mask, (ix, iy), int(new_label), border=None)
            except Exception:
                pass
            self.push_history()
            self.redo_stack.clear()
            self.update_buttons_state()
            self._render(mode="fast")
            self._schedule_hq()
            return

        w = int(self.brush_size / self.view_scale)

        if self.is_erasing:
            self._erase_visible_labels_in_circle(ix, iy, w // 2)
        else:
            value = self.current_label
            self.mask_draw.ellipse(
                (ix - w // 2, iy - w // 2, ix + w // 2, iy + w // 2),
                fill=int(value)
            )

        self.prev_ix, self.prev_iy = ix, iy
        self.is_drawing = True
        self._render(mode="fast")
        self._schedule_hq()

    def on_drag(self, event):
        if self.move_mode:
            self.on_pan_drag(event)
            return
        if self.image is None or self.is_fill_mode or not self.is_drawing:
            return

        ix2, iy2 = self.canvas_to_image_xy(event.x, event.y)
        if ix2 is None or self.prev_ix is None:
            return

        w = int(self.brush_size / self.view_scale)

        if self.is_erasing:
            self._erase_visible_labels_along_line(self.prev_ix, self.prev_iy, ix2, iy2, w // 2)
        else:
            value = self.current_label
            self.mask_draw.line(
                [(self.prev_ix, self.prev_iy), (ix2, iy2)],
                fill=int(value),
                width=w
            )
            self.mask_draw.ellipse(
                (ix2 - w // 2, iy2 - w // 2, ix2 + w // 2, iy2 + w // 2),
                fill=int(value)
            )

        self.prev_ix, self.prev_iy = ix2, iy2
        self._render(mode="fast")
        self._schedule_hq()

    def on_release(self, event):
        if self.move_mode:
            self.on_pan_end(event)
            return
        if self.image is None:
            return
        if not self.is_fill_mode and self.is_drawing:
            self.push_history()
            self.redo_stack.clear()
            self.update_buttons_state()
        self.is_drawing = False
        self.prev_ix, self.prev_iy = None, None

    # ------------ パン/ズーム ------------
    def on_pan_start(self, event):
        if self.image is None or not self.move_mode:
            return
        self._panning = True
        self._pan_start = (event.x, event.y)
        self._pan_view = (self.view_x, self.view_y)

    def on_pan_drag(self, event):
        if not self.move_mode:
            return
        if not self._panning or self.image is None:
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self.view_x = self._pan_view[0] + dx
        self.view_y = self._pan_view[1] + dy
        self._render(mode="fast")
        self._schedule_hq()

    def on_pan_end(self, event):
        if not self.move_mode:
            return
        self._panning = False
        self._render(mode="final")

    def on_wheel(self, event):
        if self.image is None:
            return

        delta = getattr(event, 'delta', 0) or 0
        if delta == 0 and getattr(event, 'num', None) in (4, 5):
            delta = 120 if event.num == 4 else -120
        if delta == 0:
            return

        old_z = self.view_scale
        zf = 1.2
        new_z = old_z * (zf if delta > 0 else 1.0 / zf)

        min_z = self.base_scale
        max_z = self.base_scale * 5.0
        new_z = max(min_z, min(max_z, new_z))

        cx, cy = event.x, event.y
        ox = (cx - self.view_x) / old_z
        oy = (cy - self.view_y) / old_z

        self.view_scale = new_z
        self.view_x = cx - ox * self.view_scale
        self.view_y = cy - oy * self.view_scale

        try:
            slider_percent = round((self.view_scale / self.base_scale) * 100)
            self.zoom_slider.set(int(max(100, min(500, slider_percent))))
        except Exception:
            pass

        self._render(mode="fast")
        self._schedule_hq()

    def on_toggle_move(self):
        self.move_mode = bool(self.var_move.get())
        try:
            self.canvas.config(cursor=("fleur" if self.move_mode else ""))
        except Exception:
            pass
        if self.move_mode:
            try:
                self.canvas.delete("brush_preview")
            except Exception:
                pass
        else:
            self.draw_brush_preview()

    def on_zoom_slider_change(self, value):
        if self.image is None:
            return
        try:
            percent = float(value)
        except Exception:
            return

        percent = max(100.0, min(500.0, percent))
        new_z = self.base_scale * (percent / 100.0)

        old_z = self.view_scale
        if abs(new_z - old_z) < 1e-6:
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        cx, cy = cw / 2.0, ch / 2.0

        ox = (cx - self.view_x) / old_z
        oy = (cy - self.view_y) / old_z

        self.view_scale = new_z
        self.view_x = cx - ox * self.view_scale
        self.view_y = cy - oy * self.view_scale

        self._render(mode="fast")
        self._schedule_hq()

    @staticmethod
    def _bind_mousewheel(widget, callback):
        widget.bind("<MouseWheel>", callback)
        widget.bind("<Button-4>", callback)
        widget.bind("<Button-5>", callback)

    # ------------ 履歴 ------------
    def push_history(self):
        if self.mask is None:
            return
        self.history.append(self.mask.copy())
        if len(self.history) > self.history_limit:
            self.history.pop(0)

    def undo(self):
        if len(self.history) <= 1:
            return
        current = self.history.pop()
        self.redo_stack.append(current)
        self.mask = self.history[-1].copy()
        self.mask_draw = ImageDraw.Draw(self.mask)
        self.refresh_display()
        self.update_buttons_state()

    def redo(self):
        if not self.redo_stack:
            return
        redo_img = self.redo_stack.pop()
        self.mask = redo_img.copy()
        self.mask_draw = ImageDraw.Draw(self.mask)
        self.history.append(self.mask.copy())
        self.refresh_display()
        self.update_buttons_state()

    def update_buttons_state(self):
        self.btn_undo.config(state=(tk.NORMAL if len(self.history) > 1 else tk.DISABLED))
        self.btn_redo.config(state=(tk.NORMAL if self.redo_stack else tk.DISABLED))
        # 通常保存は「塗ったときだけ」有効（空マスクは btn_save_empty を使う）
        enabled = tk.NORMAL if (self.mask and self.mask.getbbox()) else tk.DISABLED
        self.btn_save.config(state=enabled)

    # ------------ ツール切替/リセット ------------
    def reset_tools(self):
        self.is_erasing = False
        self.is_fill_mode = False
        self.btn_eraser.config(text=self.eraser_label())
        self.btn_fill.config(text=self.fill_label())

    def on_scale_change(self, value):
        try:
            v = int(float(value))
        except Exception:
            return
        self.brush_size = max(5, min(100, v))

    def on_brush_scale_press(self, event):
        self._slider_operating = True
        self.show_brush_preview = True
        self.refresh_display()

    def on_brush_scale_drag(self, event):
        self._slider_operating = True
        self.show_brush_preview = True
        self.refresh_display()
        self.draw_brush_preview()

    def on_brush_scale_release(self, event):
        self._slider_operating = False
        self.show_brush_preview = False
        self.refresh_display()
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass

    def draw_brush_preview(self):
        if self.image is None:
            return
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass

        brush_radius = self.brush_size / 2

        if self.is_erasing:
            outline_color = "red"
            fill_color = "red"
        else:
            col = self.get_label_color_rgb(self.current_label)
            outline_color = col
            fill_color = col

        if hasattr(self, '_slider_operating') and self._slider_operating:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            cx, cy = cw // 2, ch // 2
        else:
            try:
                mx, my = self.canvas.winfo_pointerxy()
                wx, wy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
                cx, cy = mx - wx, my - wy
            except Exception:
                return

        self.canvas.create_oval(
            cx - brush_radius, cy - brush_radius,
            cx + brush_radius, cy + brush_radius,
            outline=outline_color, width=2, tags="brush_preview"
        )
        self.canvas.create_oval(
            cx - 2, cy - 2,
            cx + 2, cy + 2,
            fill=fill_color, outline=fill_color, tags="brush_preview"
        )

    def toggle_eraser(self):
        self.is_erasing = not self.is_erasing
        if self.is_erasing:
            self.is_fill_mode = False
            self.btn_fill.config(text=self.fill_label())
        self.btn_eraser.config(text=self.eraser_label())
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass
        if self._should_show_brush_preview():
            self.draw_brush_preview()

    def toggle_fill(self):
        self.is_fill_mode = not self.is_fill_mode
        if self.is_fill_mode:
            self.is_erasing = False
            self.btn_eraser.config(text=self.eraser_label())
        self.btn_fill.config(text=self.fill_label())
        try:
            self.canvas.delete("brush_preview")
        except Exception:
            pass
        if self._should_show_brush_preview():
            self.draw_brush_preview()

    # ------------ 保存 ------------
    
    def _state_dir(self, base_dir: Path, state_dirname: str) -> Path:
        d = base_dir / state_dirname
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _get_save_paths(self, stem: str, state_dirname: str):
        mask_path = self._state_dir(MASKS_DIR, state_dirname) / f"{stem}_liga.png"
        overlay_path = self._state_dir(OVERLAYS_DIR, state_dirname) / f"{stem}_overlay.png"
        meta_path = self._state_dir(META_DIR, state_dirname) / f"{stem}_meta.json"
        return mask_path, overlay_path, meta_path

    def _get_image_dest_path(self, src_path: Path, state_dirname: str):
        return self._state_dir(IMAGES_DIR, state_dirname) / src_path.name

    def _infer_stem(self) -> str:
        in_path = Path(self.inputs[self.cur_index]) if self.inputs else None
        return in_path.stem if in_path else Path(getattr(self, "current_name", "output")).stem
    
    def _make_overlay_image_fullres(self, mask_img=None):
        if self.image is None:
            return None

        mask_img = mask_img if mask_img is not None else self.mask
        base = self.image.convert("RGBA")
        overlay = Image.new("RGBA", self.image.size, (0, 0, 0, 0))

        for cls, rgba in self.class_colors.items():
            cls_mask = mask_img.point(lambda v, c=cls: 255 if v == c else 0)
            if not cls_mask.getbbox():
                continue
            tint = Image.new("RGBA", self.image.size, rgba)
            overlay = Image.composite(tint, overlay, cls_mask)

        return Image.alpha_composite(base, overlay)
    
    def _save_meta(self, meta_path: Path, image_path: Path, mask_path: Path, overlay_path: Path, status: str):
        meta = {
            "image_name": image_path.name,
            "image_relpath": str(image_path),
            "mask_name": mask_path.name,
            "mask_relpath": str(mask_path),
            "overlay_name": overlay_path.name,
            "overlay_relpath": str(overlay_path),
            "status": status,
            "annotator": "",
            "reviewer": "",
            "comment": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    
    def _go_next_or_finish(self):
        if self.cur_index + 1 < len(self.inputs):
            self.cur_index += 1
            self.load_current_input()
            self.reset_tools()
        else:
            messagebox.showinfo("完了", f"全{len(self.inputs)}枚の処理が完了しました。")
            self.finish_and_exit()


    def save_mask(self):
        """塗った内容（0〜4ラベル）を保存し、overlay と meta も保存して次へ"""
        if self.image is None or self.mask is None:
            return
        if not self.mask.getbbox():
            messagebox.showinfo("保存", "塗られた領域がありません。\n皮疹なしなら『皮疹なしで保存（次へ）』を押してね。")
            return

        stem = self._infer_stem()
        src_image_path = self.current_input_path if self.current_input_path else find_image_path_by_stem(stem, PENDING_DIRNAME)
        if src_image_path is None or not src_image_path.exists():
            messagebox.showerror("保存エラー", f"元画像が見つかりませんでした。\n{stem}")
            return

        dest_image_path = self._get_image_dest_path(src_image_path, DONE_DIRNAME)
        mask_path, overlay_path, meta_path = self._get_save_paths(stem, DONE_DIRNAME)

        try:
            self.mask.save(mask_path)

            overlay_img = self._make_overlay_image_fullres(self.mask)
            overlay_img.save(overlay_path)

            shutil.move(str(src_image_path), str(dest_image_path))

            self._save_meta(
                meta_path=meta_path,
                image_path=dest_image_path,
                mask_path=mask_path,
                overlay_path=overlay_path,
                status="done",
            )

            print(f"[SAVED MASK] {mask_path}")

        except Exception as e:
            messagebox.showerror("保存エラー", f"保存に失敗しました。\n{e}")
            return

        self._go_next_or_finish()

 
    def save_empty_mask(self):
        """皮疹なし（全0）として保存し、overlay と meta も保存して次へ"""
        if self.image is None:
            return

        name = getattr(self, "current_name", "")
        ok = messagebox.askyesno(
            "確認",
            f"この画像を『皮疹なし（全て0）』として保存しますか？\n\n{name}"
        )
        if not ok:
            return

        stem = self._infer_stem()
        src_image_path = self.current_input_path if self.current_input_path else find_image_path_by_stem(stem, PENDING_DIRNAME)
        if src_image_path is None or not src_image_path.exists():
            messagebox.showerror("保存エラー", f"元画像が見つかりませんでした。\n{stem}")
            return

        class_mask = Image.new("L", self.image.size, 0)
        dest_image_path = self._get_image_dest_path(src_image_path, DONE_DIRNAME)
        mask_path, overlay_path, meta_path = self._get_save_paths(stem, DONE_DIRNAME)

        try:
            class_mask.save(mask_path)

            overlay_img = self._make_overlay_image_fullres(class_mask)
            overlay_img.save(overlay_path)

            shutil.move(str(src_image_path), str(dest_image_path))

            self._save_meta(
                meta_path=meta_path,
                image_path=dest_image_path,
                mask_path=mask_path,
                overlay_path=overlay_path,
                status="done",
            )

            print(f"[SAVED EMPTY MASK] {mask_path}")

        except Exception as e:
            messagebox.showerror("保存エラー", f"保存に失敗しました。\n{e}")
            return

        self._go_next_or_finish()

    # ------------ 終了処理 ------------
    def print_skip_summary(self):
        if self.skipped:
            print("=== Skipped images ===")
            for name in self.skipped:
                print(f"- {name}")
            print("======================")

    def finish_and_exit(self):
        try:
            self.print_skip_summary()
            self.root.destroy()
        finally:
            return

    def on_close(self):
        self.finish_and_exit()


# ---------- CLI ----------

def parse_args():
    parser = argparse.ArgumentParser(description="フリーペイント lIGAマスク作成アプリ（0〜4）")
    parser.add_argument("--input", "-i", nargs="+", help="入力画像パス（複数可・ワイルドカード可）")
    parser.add_argument("--input-dir", "-id", type=str, help="参照フォルダ（中の画像を一括）")
    parser.add_argument("--output-dir", "-od", type=str, default=None, help="マスク保存フォルダ（複数入力時推奨）")
    parser.add_argument("--win_x", type=int, default=0, help="ウィンドウ左上X座標")
    parser.add_argument("--win_y", type=int, default=0, help="ウィンドウ左上Y座標")
    parser.add_argument("--selftest", action="store_true", help="ユニットテストを実行して終了")
    parser.add_argument(
    "--source",
    choices=["pending", "skipped"],
    default="pending",
    help="作成対象フォルダ"
    )
    return parser.parse_args()


def _selftest():
    assert isinstance(TK_AVAILABLE, bool)
    assert expand_inputs([]) == []
    assert isinstance(expand_inputs_from_dir("__no_such_dir__"), list)
    assert Image.MAX_IMAGE_PIXELS is None
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True
    print("[SELFTEST] ok")


def main():
    args = parse_args()

    if not TK_AVAILABLE or not IMAGETK_AVAILABLE:
        if args.selftest:
            _selftest()
            return
        if not TK_AVAILABLE:
            print("tkinter が見つからないため GUI を起動できません。")
        else:
            print("Pillow の ImageTk が利用できないため GUI を起動できません。")
        return
    
    ensure_project_dirs()
    if args.source == "skipped":
        inputs = expand_inputs_from_dir("data/images/02_skipped")
    else:
        inputs = expand_inputs_from_dir("data/images/01_pending")

    root = tk.Tk()

    try:
        root.update_idletasks()
        root.geometry(f"+{args.win_x}+{args.win_y}")
        root.after(50, lambda: root.geometry(f"+{args.win_x}+{args.win_y}"))
    except Exception:
        pass

    try:
        root.attributes("-topmost", True)
        root.after(300, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    _ = FreePaintMaskApp(root, inputs=inputs, output_dir=args.output_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
