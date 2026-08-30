#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
贴吧取关助手 - 可视化面板（可打包为 exe）
功能：查看关注列表、搜索、批量取消关注（含已关闭的贴吧）。
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import aiohttp.connector
import aiotieba

# aiohttp 3.14 ALPN 修复（否则贴吧 HTTP 握手会超时）
_orig_make = aiohttp.connector._make_ssl_context


def _no_alpn(verified: bool):
    ctx = _orig_make(verified)
    try:
        ctx.set_alpn_protocols([])
    except Exception:
        pass
    return ctx


aiohttp.connector._SSL_CONTEXT_VERIFIED = _no_alpn(True)
aiohttp.connector._SSL_CONTEXT_UNVERIFIED = _no_alpn(False)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

COLORS = {
    "bg": "#0f1f3b",
    "panel": "#0b172a",
    "fg": "#e8f0ff",
    "dim": "#8fa3c8",
    "accent": "#1f6feb",
    "ok": "#5cd98a",
    "err": "#ff6b6b",
    "entry": "#122441",
}


def resource_path(name: str) -> Path:
    """打包后从临时目录取资源，源码运行时从脚本目录取。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    return Path(__file__).resolve().parent / name


async def fetch_followed(client) -> list:
    user = await client.get_self_info()
    if not getattr(user, "user_id", 0):
        raise RuntimeError("登录失败：BDUSS 可能无效")
    forums = []
    pn = 1
    while True:
        page = await client.get_follow_forums(user.user_id, pn, rn=200)
        forums.extend(page.objs)
        if not page.has_more:
            break
        pn += 1
    return forums


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.forums: list = []
        root.title("贴吧取关助手")
        root.geometry("860x640")
        root.configure(bg=COLORS["bg"])
        root.minsize(720, 520)
        self._build_style()
        self._build_ui()
        self._load_bduss()
        self._poll_queue()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TButton", background=COLORS["accent"], foreground="#ffffff", borderwidth=0,
            focusthickness=0, padding=(12, 7), font=("Microsoft YaHei UI", 10),
        )
        style.map("TButton", background=[("active", "#2f7ff0"), ("disabled", "#3a4f77")])
        style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["fg"],
                        font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", COLORS["bg"])])
        style.configure("TProgressbar", background=COLORS["accent"], troughcolor=COLORS["entry"], borderwidth=0)
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"],
                        foreground=COLORS["fg"], rowheight=24)
        style.map("Treeview", background=[("selected", COLORS["accent"])])
        style.configure("Treeview.Heading", background=COLORS["entry"], foreground=COLORS["fg"],
                        font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="贴吧取关助手", bg=COLORS["panel"], fg=COLORS["fg"],
                 font=("Microsoft YaHei UI", 14, "bold"), pady=10).pack(side="left", padx=14)
        self.status = tk.Label(header, text="待机", bg=COLORS["panel"], fg=COLORS["dim"],
                               font=("Microsoft YaHei UI", 10))
        self.status.pack(side="right", padx=14)

        bduss_frame = tk.Frame(self.root, bg=COLORS["bg"])
        bduss_frame.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(bduss_frame, text="BDUSS:", bg=COLORS["bg"], fg=COLORS["fg"]).pack(side="left")
        self.bduss_var = tk.StringVar()
        self.bduss_entry = tk.Entry(bduss_frame, textvariable=self.bduss_var, show="•",
                                    bg=COLORS["entry"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
                                    relief="flat", font=("Microsoft YaHei UI", 10))
        self.bduss_entry.pack(side="left", fill="x", expand=True, padx=6, ipady=4)
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bduss_frame, text="显示", variable=self.show_var,
                        command=self._toggle_bduss).pack(side="left")

        toolbar = tk.Frame(self.root, bg=COLORS["bg"])
        toolbar.pack(fill="x", padx=12, pady=(0, 6))
        self.refresh_btn = ttk.Button(toolbar, text="刷新关注列表", command=self.refresh_list)
        self.refresh_btn.pack(side="left")
        self.unfollow_btn = ttk.Button(toolbar, text="取消关注选中", command=self.unfollow_selected)
        self.unfollow_btn.pack(side="left", padx=8)
        self.select_all_btn = ttk.Button(toolbar, text="全选", command=self.select_all)
        self.select_all_btn.pack(side="left")
        tk.Label(toolbar, text="搜索:", bg=COLORS["bg"], fg=COLORS["fg"]).pack(side="left", padx=(16, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        self.search_entry = tk.Entry(toolbar, textvariable=self.search_var, bg=COLORS["entry"],
                                     fg=COLORS["fg"], insertbackground=COLORS["fg"], relief="flat",
                                     font=("Microsoft YaHei UI", 10))
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=4)

        list_frame = tk.Frame(self.root, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=12, pady=4)
        self.tree = ttk.Treeview(list_frame, columns=("fid", "info"), show="headings",
                                 selectmode="extended")
        self.tree.heading("fid", text="fid")
        self.tree.heading("info", text="吧名")
        self.tree.column("fid", width=100, anchor="w")
        self.tree.column("info", width=560, anchor="w")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.count_label = tk.Label(self.root, text="", bg=COLORS["bg"], fg=COLORS["dim"],
                                    font=("Microsoft YaHei UI", 9), anchor="w")
        self.count_label.pack(fill="x", padx=14, pady=(0, 2))

        log_frame = tk.Frame(self.root, bg=COLORS["bg"])
        log_frame.pack(fill="x", padx=12, pady=4)
        self.log = scrolledtext.ScrolledText(log_frame, height=8, bg=COLORS["panel"], fg=COLORS["fg"],
                                             insertbackground=COLORS["fg"], relief="flat",
                                             font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(0, 10))

    def _toggle_bduss(self) -> None:
        self.bduss_entry.config(show="" if self.show_var.get() else "•")

    def _load_bduss(self) -> None:
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            self.bduss_var.set(str(cfg.get("bduss", "")))
        except Exception:
            pass

    def _save_bduss(self) -> None:
        val = self.bduss_var.get().strip()
        if not val:
            return
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        except Exception:
            cfg = {}
        cfg["bduss"] = val
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _append(self, text: str, color: str = None) -> None:
        if color in ("ok", "err", "warn"):
            color = {"ok": COLORS["ok"], "err": COLORS["err"], "warn": "#e8c15c"}.get(color)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        if color:
            start = self.log.index("end-1c linestart")
            end = self.log.index("end-1c")
            self.log.tag_add("colored", start, end)
            try:
                self.log.tag_config("colored", foreground=color)
            except tk.TclError:
                pass
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str, color: str = None) -> None:
        self.status.config(text=text, fg=color or COLORS["dim"])

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.refresh_btn.config(state=state)
        self.unfollow_btn.config(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.config(value=0)

    def _apply_filter(self) -> None:
        kw = self.search_var.get().strip()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for f in self.forums:
            if kw and kw not in f.fname and kw not in str(f.fid):
                continue
            self.tree.insert("", "end", values=(f.fid, f.fname))
            shown += 1
        self.count_label.config(text=f"共 {len(self.forums)} 个关注吧，显示 {shown} 个")

    def select_all(self) -> None:
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def refresh_list(self) -> None:
        if self.busy:
            return
        bduss = self.bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "请先填写 BDUSS")
            return
        self._save_bduss()
        self._set_busy(True)
        self._set_status("正在获取关注列表...", COLORS["accent"])
        threading.Thread(target=self._run_async, args=(self._fetch_task(bduss),), daemon=True).start()

    async def _fetch_task(self, bduss: str) -> None:
        try:
            async with aiotieba.Client(bduss) as client:
                forums = await fetch_followed(client)
            self.q.put(("list", forums))
            self.q.put(("log", f"获取关注列表成功：{len(forums)} 个贴吧"))
        except Exception as exc:
            self.q.put(("log", f"获取关注列表失败：{exc}"))

    def unfollow_selected(self) -> None:
        if self.busy:
            return
        bduss = self.bduss_var.get().strip()
        if not bduss:
            messagebox.showwarning("提示", "请先填写 BDUSS")
            return
        items = self.tree.selection()
        if not items:
            messagebox.showwarning("提示", "请先在列表中选择要取关的贴吧")
            return
        targets = []
        for item in items:
            fid, fname = self.tree.item(item, "values")
            targets.append((int(fid), fname))
        if not messagebox.askyesno("确认", f"确定取消关注选中的 {len(targets)} 个贴吧吗？"):
            return
        self._save_bduss()
        self._set_busy(True)
        self._set_status(f"正在取关 {len(targets)} 个贴吧...", COLORS["accent"])
        threading.Thread(target=self._run_async, args=(self._unfollow_task(bduss, targets),), daemon=True).start()

    async def _unfollow_task(self, bduss: str, targets: list) -> None:
        try:
            async with aiotieba.Client(bduss) as client:
                user = await client.get_self_info()
                if not getattr(user, "user_id", 0):
                    raise RuntimeError("登录失败：BDUSS 可能无效")
                ok = 0
                fail = 0
                for fid, fname in targets:
                    try:
                        resp = await client.unfollow_forum(fid)
                        if resp:
                            ok += 1
                            self.q.put(("log", f"✓ 已取关：{fname} (fid={fid})", COLORS["ok"]))
                        else:
                            fail += 1
                            self.q.put(
                                ("log", f"✗ 取关失败：{fname} -> {getattr(resp, 'err', None)}", COLORS["err"])
                            )
                    except Exception as exc:
                        fail += 1
                        self.q.put(("log", f"✗ 取关异常：{fname} -> {exc}", COLORS["err"]))
                    await asyncio.sleep(1)
                self.q.put(("log", f"取关完成：成功 {ok}，失败 {fail}"))
        except Exception as exc:
            self.q.put(("log", f"取关失败：{exc}", COLORS["err"]))

    def _run_async(self, coro) -> None:
        try:
            asyncio.run(coro)
        except Exception:
            self.q.put(("log", "后台任务异常", COLORS["err"]))
        finally:
            # 无论成功失败，都确保界面收到"完成"信号，进度条停止
            self.q.put(("done", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                try:
                    kind = item[0]
                    if kind == "list":
                        self.forums = item[1]
                        self._apply_filter()
                    elif kind == "log":
                        self._append(item[1], item[2] if len(item) > 2 else None)
                    elif kind == "done":
                        self._set_busy(False)
                        self._set_status("完成")
                except Exception as exc:
                    try:
                        self._append(f"界面处理异常：{exc}")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            self.root.after(80, self._poll_queue)


def main() -> int:
    root = tk.Tk()
    try:
        root.iconbitmap(str(resource_path("icon.ico")))
    except Exception:
        pass
    App(root)
    if "--selftest" in sys.argv:
        root.after(1500, lambda: (print("SELFTEST OK"), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
