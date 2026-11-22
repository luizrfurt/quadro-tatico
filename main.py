"""Quadro tático de ataque para futebol americano.

Aplicativo desktop para desenhar jogadas: peças, texto e rotas.
Abra o Quadro tatico.exe nesta pasta. As jogadas ficam em dados/quadro.db.
"""

from __future__ import annotations

import copy
import math
import os
import sqlite3
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from nucleo import *  # noqa: F403


class QuadroTatico(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._headless = os.environ.get("QUADRO_HEADLESS") == "1"
        if self._headless:
            self.withdraw()
        open_store()
        self.title("Quadro tático — ataque")
        self.geometry("1360x860")
        self.minsize(1200, 780)
        if self._headless:
            self.withdraw()
        else:
            self.state("zoomed")
        self.configure(bg="#e7e5e4")

        self.shapes: list[Shape] = []
        self.routes: list[Route] = []
        self.draft: list[list[float]] = []
        self.draft_follow: str | None = None
        self.selection: tuple[str, str] | None = None
        self.tool = "select"
        self.drag: dict | None = None
        self._before = None
        self._text_before = None
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._suspend = False
        self.dirty = False
        self.loaded_id: int | None = None
        self.mouse: tuple[float, float] | None = None
        self._last_click_at = 0.0
        self._last_click_pos = (0.0, 0.0)
        self.scale = 1.0
        self.ox = 0.0
        self.oy = 0.0

        self.name_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.category_names = category_catalog()
        self.play_categories: list[str] = []
        self.play_id: int | None = None
        self.snap_var = tk.BooleanVar(value=True)
        self.defense_back = tk.BooleanVar(value=True)
        self.offense_base: str | None = None
        self.offense_set: str | None = None
        self.tool_canvases: list[tk.Canvas] = []
        self.route_tip: str | None = None
        self.block_kind: str | None = None
        self.block_anchor: str | None = None
        self.tip_buttons: dict = {}
        self._name_before = None
        self._notes_before = None
        self._clean = None
        self._ready = False
        self.label_var.trace_add("write", self.on_label_write)

        self.tool_buttons: dict[str, tk.Button] = {}
        self.route_color = "laranja"
        self.color_buttons: dict[str, tk.Button] = {}
        self._build()
        self.set_tool("select")
        self.refresh_list()
        self.restore_last()
        self.mark_clean()
        self._ready = True
        self.name_var.trace_add("write", self.on_name_write)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<Delete>", self.on_delete_key)
        self.bind_all("<BackSpace>", self.on_backspace)
        self.bind_all("<Escape>", self.on_escape)
        self.bind_all("<Return>", self.on_return)
        self.bind_all("<Control-s>", self.on_save_key)
        self.bind_all("<Control-z>", self.on_undo_key)
        self.bind_all("<Control-y>", self.on_redo_key)
        self.bind_all("<Control-n>", self.on_new_key)
        for key in ("Left", "Right", "Up", "Down"):
            self.bind_all(f"<{key}>", self.on_arrow)
            self.bind_all(f"<KeyRelease-{key}>", self.on_arrow_release)
        self._nudge_before = None
        self._zone_photos: list = []
        self.playing = False
        self.play_elapsed = 0.0
        self._play_job = None
        self._play_last = 0.0
        self.after(60, self.redraw)

    def _build(self) -> None:
        header = tk.Frame(self, bg="#1c1917")
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        tk.Label(
            header,
            text="CAMPO",
            bg="#14532d",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left", padx=(12, 8), pady=10)
        tk.Label(
            header,
            text="Quadro tático",
            bg="#1c1917",
            fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", pady=10)
        tk.Label(header, text="Jogada", bg="#1c1917", fg="#d6d3d1", font=("Segoe UI", 10)).pack(
            side="left", padx=(18, 6)
        )
        name = tk.Entry(header, textvariable=self.name_var, font=("Segoe UI", 12), width=22, relief="flat")
        name.pack(side="left", pady=10, ipady=4)
        self.name_entry = name
        self.name_entry.bind("<FocusIn>", self.on_name_focus_in)
        self.name_entry.bind("<FocusOut>", self.on_name_focus_out)
        self._header_button(header, "Nova", self.new_play).pack(side="left", padx=(16, 4))
        self._header_button(header, "Salvar", self.save_play, primary=True).pack(side="left", padx=4)
        self._header_button(header, "Desfazer", self.undo).pack(side="left", padx=4)
        self._header_button(header, "Refazer", self.redo).pack(side="left", padx=4)
        self._header_button(header, "Duplicar", self.duplicate_play).pack(side="right", padx=(4, 12))
        self._header_button(header, "Imagem", self.export_image).pack(side="right", padx=4)
        self._header_button(header, "GIF", self.export_gif).pack(side="right", padx=4)
        self._header_button(header, "PDF", self.export_pdf).pack(side="right", padx=4)

        tools_wrap = tk.Frame(self, bg="#fafaf9")
        tools_wrap.grid(row=1, column=0, sticky="nsew")
        self.grid_columnconfigure(0, minsize=360)
        book = ttk.Notebook(tools_wrap)
        book.pack(fill="both", expand=True)
        tab_play = tk.Frame(book, bg="#fafaf9")
        tab_more = tk.Frame(book, bg="#fafaf9")
        book.add(tab_play, text="Jogada")
        book.add(tab_more, text="Ajuste")
        tools = self._scroll_panel(tab_play)
        extra = self._scroll_panel(tab_more)
        self.bind_all("<MouseWheel>", self._wheel_tools)
        tk.Label(
            tools,
            text="Formação",
            bg="#fafaf9",
            fg="#1c1917",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 2))
        offense_bases, offense_sets = formation_menu("offense")
        defense_bases, defense_sets = formation_menu("defense")
        self._formation_pair(tools, "Ataque", offense_bases, offense_sets, self.insert_formation, first=True)
        self._formation_pair(tools, "Defesa", defense_bases, defense_sets, self.insert_defense)
        self.show_offense_formation()
        tk.Checkbutton(
            tools,
            text="Defesa atrás das rotas",
            variable=self.defense_back,
            command=self.redraw,
            bg="#fafaf9",
            activebackground="#fafaf9",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))
        self._side_button(tools, "Apagar defesa", self.clear_defense).pack(fill="x", pady=(2, 1))
        self._tool_button(tools, "select")
        self._side_button(tools, "Espelhar formação", self.mirror_play).pack(fill="x", pady=(4, 1))

        self._rule(tools)
        self.play_button = tk.Button(
            tools,
            text="Play",
            command=self.toggle_play,
            bg="#111111",
            fg="white",
            activebackground="#292524",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            pady=4,
        )
        self.play_button.pack(fill="x", pady=(4, 2))

        self._rule(tools)
        tk.Label(tools, text="Rota do jogador", bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 2)
        )
        color_row = tk.Frame(tools, bg="#fafaf9")
        color_row.pack(fill="x", pady=(0, 4))
        for key, label, bg in (("laranja", "Laranja", "#ea580c"), ("verde", "Verde", "#15803d")):
            button = tk.Button(
                color_row,
                text=label,
                command=lambda name=key: self.set_route_color(name),
                bg=bg,
                fg="white",
                activebackground=bg,
                activeforeground="white",
                relief="flat",
                bd=0,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", expand=True, fill="x", padx=1)
            self.color_buttons[key] = button
        self._paint_route_color()
        split = tk.Frame(tools, bg="#fafaf9")
        split.pack(fill="x", pady=(0, 2))
        split.columnconfigure(0, weight=1, uniform="routes")
        split.columnconfigure(2, weight=1, uniform="routes")
        specials = tk.Frame(split, bg="#fafaf9")
        normals = tk.Frame(split, bg="#fafaf9")
        specials.grid(row=0, column=0, sticky="nsew")
        tk.Frame(split, bg="#111111", width=2).grid(row=0, column=1, sticky="ns", padx=5)
        normals.grid(row=0, column=2, sticky="nsew")
        for frame in (specials, normals):
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
        special_actions = (
            ("Motion", "motion"),
            ("Release", "release"),
            ("PA route", "paroute"),
            ("PA block", "pablock"),
            ("PA pass", "papass"),
            ("Block run", "blockrun"),
            ("Block pass", "blockpass"),
            ("Run path", "runpath"),
            ("Pass path", "passpath"),
            ("OL run", "olrun"),
            ("OL pass", "olpass"),
            ("Dropback", "dropback"),
            ("RB run", "rbrun"),
            ("RB path", "rbpath"),
        )
        for index, (label, kind) in enumerate(special_actions):
            self._side_button(specials, label, lambda kind=kind: self._player_action(kind), compact=True).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=1, pady=1
            )
        presets = (
            ("Chair", "chair"),
            ("Comeback", "comeback"),
            ("Corner", "corner"),
            ("Crossing", "crossing"),
            ("Curl", "curl"),
            ("Dig", "dig"),
            ("Dog", "dog"),
            ("Drag", "drag"),
            ("Fade", "fade"),
            ("Flat", "flat"),
            ("Go", "go"),
            ("Hitch", "hitch"),
            ("In", "in"),
            ("Out", "out"),
            ("Post", "post"),
            ("Screen", "screen"),
            ("Seam", "seam"),
            ("Sit", "sit"),
            ("Slant", "slant"),
            ("Stick", "stick"),
            ("Swing", "swing"),
            ("Texas", "texas"),
            ("Wheel", "wheel"),
            ("Whip", "whip"),
        )
        for index, (label, kind) in enumerate(presets):
            self._side_button(normals, label, lambda kind=kind: self.add_player_route(kind), compact=True).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=1, pady=1
            )
        self._side_button(tools, "Espelhar rota", self.mirror_route).pack(fill="x", pady=(6, 1))

        self._rule(extra)
        tk.Label(extra, text="Cobertura", bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(6, 2)
        )
        zone_grid = tk.Frame(extra, bg="#fafaf9")
        zone_grid.pack(fill="x")
        zone_grid.columnconfigure(0, weight=1)
        zone_grid.columnconfigure(1, weight=1)
        self.zone_buttons: dict[str, tk.Button] = {}
        for index, (tone, (_rgb, label, bg, fg)) in enumerate(ZONE_TONES.items()):
            button = tk.Button(
                zone_grid,
                text=label,
                command=lambda name=tone: self.set_tool(f"zone:{name}"),
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                relief="flat",
                bd=0,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
            )
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=1, pady=1)
            self.zone_buttons[tone] = button

        self._rule(extra)
        tk.Label(extra, text="Ajuste", bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 2)
        )
        tk.Label(extra, text="Texto da peça", bg="#fafaf9", fg="#44403c", font=("Segoe UI", 9)).pack(anchor="w")
        self.label_entry = tk.Entry(extra, textvariable=self.label_var, font=("Segoe UI", 12), relief="solid", bd=1)
        self.label_entry.pack(fill="x", pady=(2, 6), ipady=3)
        self.label_entry.bind("<FocusOut>", self.on_label_focus_out)
        tk.Checkbutton(
            extra,
            text="Encaixar na grade",
            variable=self.snap_var,
            bg="#fafaf9",
            activebackground="#fafaf9",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 4))
        for tool in SHAPE_TOOLS:
            self._tool_button(extra, tool)
        tk.Label(extra, text="Ponta da rota", bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(8, 2)
        )
        tip_row = tk.Frame(extra, bg="#fafaf9")
        tip_row.pack(fill="x", pady=(0, 4))
        for key, label in ((None, "Auto"), ("arrow", "Seta"), ("bar", "Trave"), ("ring", "Anel")):
            button = tk.Button(
                tip_row,
                text=label,
                command=lambda name=key: self.set_route_tip(name),
                bg="white",
                fg="#1c1917",
                activebackground="#e7e5e4",
                activeforeground="#1c1917",
                relief="flat",
                bd=0,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", expand=True, fill="x", padx=1)
            self.tip_buttons[key] = button
        self._paint_route_tip()
        for tool in ROUTE_TOOLS:
            self._tool_button(extra, tool)
        route_actions = tk.Frame(extra, bg="#fafaf9")
        route_actions.pack(fill="x", pady=(6, 0))
        self.finish_button = tk.Button(
            route_actions,
            text="Concluir rota",
            command=self.finish_route,
            bg="white",
            fg="#1c1917",
            relief="flat",
            state="disabled",
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        self.finish_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.cancel_button = tk.Button(
            route_actions,
            text="Cancelar",
            command=self.cancel_draft,
            bg="white",
            fg="#1c1917",
            relief="flat",
            state="disabled",
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        self.cancel_button.pack(side="left", expand=True, fill="x")
        self._side_button(extra, "Excluir seleção", self.delete_selected).pack(fill="x", pady=(8, 2))
        self._rule(extra)
        self.legend_label = tk.Label(
            extra,
            text=(
                "Rotas: laranja ou verde. Laranja é a principal.\n"
                "RB run: linha laranja da corrida, no ritmo do bloqueio. Puxe a ponta para o tamanho.\n"
                "RB run e RB path esperam um instante antes da bolinha sair, para o RB chegar no bloqueio.\n"
                "RB path desenha a corrida: o clique no jogador gruda a linha e o direito conclui.\n"
                "Dropback: azul claro. O tamanho muda com a base\n"
                "e para a no máximo 5 jardas atrás da linha.\n"
                "Na shotgun, o quarterback já está fundo: o passo é para o lado.\n"
                "Bloqueio, corrida e passe: trave dourada.\n"
                "Run path e Pass path desenham o bloqueio: o clique no jogador gruda a linha.\n"
                "Rota selecionada: setas inclinam qualquer traço 45° à esquerda ou à direita.\n"
                "Release: dourado no bloqueio, espera, depois a rota.\n"
                "Play action: roxo. Seta se sai para rota, trave se bloqueia.\n"
                "PA pass: tracejado roxo. A rota da árvore sai quando ele acaba.\n"
                "Motion: linha azul-escura ondulada.\n"
                "Auto, seta, trave ou anel escolhem a ponta. Auto mantém a de cada tipo.\n\n"
                "Selecione um atacante e use a rota pronta.\n"
                "No Ajuste, o primeiro clique numa peça sai do centro dela.\n"
                "Play percorre cada traço no ritmo da ação e mostra o tempo.\n"
                "Laranja conta o tempo da rota principal, até esse jogador terminar.\n"
                "Flat, wheel e texas de quem não é X, F, Z ou Y chegam na linha em 45°, por fora da OL.\n"
                "Setas movem o jogador clicado e a rota que sai dele. Shift anda uma jarda.\n"
                "Cobertura fica atrás, translúcida.\n"
                "Defesa atrás das rotas deixa os marcadores translúcidos,\n"
                "com o desenho da rota por cima. Apagar defesa tira os jogadores.\n"
                "Espelhar inverte a jogada. Espelhar rota inverte só a rota clicada.\n"
                "Ctrl+S salva · Ctrl+Z desfaz"
            ),
            bg="#fafaf9",
            fg="#57534e",
            justify="left",
            wraplength=190,
            font=("Segoe UI", 8),
        )
        self.legend_label.pack(anchor="w", fill="x")

        self.canvas = tk.Canvas(self, bg="#d6d3d1", highlightthickness=0, takefocus=True)
        self.canvas.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<ButtonPress-3>", self.on_right)
        self.canvas.bind("<Double-Button-1>", self.on_double)

        side = tk.Frame(self, bg="#fafaf9", padx=8, pady=8)
        side.grid(row=1, column=2, sticky="nsew")
        self.grid_columnconfigure(2, minsize=300)
        tk.Label(side, text="Jogadas salvas", bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        list_wrap = tk.Frame(side, bg="#fafaf9")
        list_wrap.pack(fill="both", expand=True, pady=8)
        scroll = tk.Scrollbar(list_wrap)
        scroll.pack(side="right", fill="y")
        style = ttk.Style(self)
        style.configure("Plays.Treeview", font=("Segoe UI", 9), rowheight=22)
        style.configure("Plays.Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.plays = ttk.Treeview(
            list_wrap,
            columns=("id", "nome", "categoria"),
            show="headings",
            selectmode="browse",
            style="Plays.Treeview",
            yscrollcommand=scroll.set,
        )
        self.plays.heading("id", text="id")
        self.plays.heading("nome", text="nome")
        self.plays.heading("categoria", text="categoria")
        self.plays.column("id", width=36, minwidth=36, stretch=False, anchor="center")
        self.plays.column("nome", width=88, minwidth=60, stretch=True, anchor="w")
        self.plays.column("categoria", width=140, minwidth=80, stretch=True, anchor="w")
        self.plays.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.plays.yview)
        self.plays.bind("<Double-Button-1>", lambda _event: self.open_selected())
        self._side_button(side, "Abrir", self.open_selected).pack(fill="x", pady=2)
        self._side_button(side, "Excluir jogada", self.delete_saved_play).pack(fill="x", pady=2)

        usage = tk.Frame(self, bg="#f5f5f4", padx=8, pady=4)
        usage.grid(row=2, column=1, sticky="ew", padx=8, pady=(0, 6))
        tk.Label(usage, text="Uso", bg="#f5f5f4", fg="#1c1917", font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(0, 6)
        )
        self.category_chips = tk.Frame(usage, bg="#f5f5f4")
        self.category_chips.pack(side="left", fill="x", expand=True)
        self.category_chips.bind("<Configure>", self._flow_categories)
        self._paint_categories()

        note_row = tk.Frame(self, bg="#f5f5f4", padx=8, pady=4)
        note_row.grid(row=3, column=1, sticky="ew", padx=8, pady=(0, 6))
        tk.Label(note_row, text="Observação", bg="#f5f5f4", fg="#1c1917", font=("Segoe UI", 9, "bold")).pack(
            side="left", anchor="n", padx=(0, 6), pady=2
        )
        self.notes = tk.Text(
            note_row,
            height=2,
            font=("Segoe UI", 9),
            wrap="word",
            relief="solid",
            bd=1,
            highlightthickness=0,
        )
        self.notes.pack(side="left", fill="x", expand=True)
        self.notes.bind("<KeyRelease>", self.on_notes_edit)
        self.notes.bind("<FocusIn>", self.on_notes_focus_in)
        self.notes.bind("<FocusOut>", self.on_notes_focus_out)

        self.status_var = tk.StringVar()
        status = tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            bg="#1c1917",
            fg="#e7e5e4",
            font=("Segoe UI", 9),
            padx=12,
            pady=6,
        )
        status.grid(row=4, column=0, columnspan=3, sticky="ew")

    def _scroll_panel(self, parent: tk.Frame) -> tk.Frame:
        canvas = tk.Canvas(parent, bg="#fafaf9", highlightthickness=0, width=230)
        scroll = tk.Scrollbar(parent, command=canvas.yview)
        frame = tk.Frame(canvas, bg="#fafaf9", padx=10, pady=8)
        window = canvas.create_window((0, 0), window=frame, anchor="nw")

        def sync(_event=None, board=canvas, inner=frame, item=window) -> None:
            width = board.winfo_width()
            if width < 2:
                return
            if int(float(board.itemcget(item, "width") or 0)) != width:
                board.itemconfigure(item, width=width)
                return
            legend = getattr(self, "legend_label", None)
            if legend is not None and legend.master is inner:
                wrap = max(120, width - 20)
                if int(legend.cget("wraplength")) != wrap:
                    legend.configure(wraplength=wrap)
                    return
            height = inner.winfo_reqheight()
            board.configure(scrollregion=(0, 0, width, height))
            if height <= board.winfo_height() + 1:
                board.yview_moveto(0)

        frame.bind("<Configure>", sync)
        canvas.bind("<Configure>", sync)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scroll.set)
        self.tool_canvases.append(canvas)
        return frame

    def _header_button(self, parent: tk.Frame, text: str, command, primary: bool = False) -> tk.Button:
        bg = "#15803d" if primary else "#44403c"
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg="white",
            activebackground="#166534",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            font=("Segoe UI", 10),
            cursor="hand2",
        )

    def _formation_pair(self, parent: tk.Frame, title: str, bases, sets_for, command, first: bool = False) -> None:
        tk.Label(parent, text=title, bg="#fafaf9", fg="#1c1917", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(2 if first else 8, 2)
        )
        base_labels = [label for label, _key in bases]
        base_keys = {label: key for label, key in bases}
        row = tk.Frame(parent, bg="#fafaf9")
        row.pack(fill="x")
        row.columnconfigure(0, weight=4)
        row.columnconfigure(1, weight=8)
        base_box = tk.Frame(row, bg="#fafaf9")
        set_box = tk.Frame(row, bg="#fafaf9")
        base_box.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        set_box.grid(row=0, column=1, sticky="ew")
        tk.Label(base_box, text="Base", bg="#fafaf9", fg="#44403c", font=("Segoe UI", 8)).pack(anchor="w")
        base_combo = ttk.Combobox(base_box, values=base_labels, state="readonly", font=("Segoe UI", 9), width=12)
        base_combo.current(0)
        base_combo.pack(fill="x")
        tk.Label(set_box, text="Set", bg="#fafaf9", fg="#44403c", font=("Segoe UI", 8)).pack(anchor="w")
        line = tk.Frame(set_box, bg="#fafaf9")
        line.pack(fill="x")
        set_combo = ttk.Combobox(line, state="readonly", font=("Segoe UI", 9), width=8)

        def apply_sets(_event=None) -> None:
            options = sets_for[base_keys[base_combo.get()]]
            set_combo["values"] = [label for label, _key in options]
            set_combo.current(0)

        def confirm() -> None:
            options = sets_for[base_keys[base_combo.get()]]
            styles = {label: key for label, key in options}
            command(base_keys[base_combo.get()], styles[set_combo.get()])

        apply_sets()
        base_combo.bind("<<ComboboxSelected>>", apply_sets)
        if first:
            self._offense_base_combo = base_combo
            self._offense_set_combo = set_combo
            self._offense_sets_for = sets_for
            self._offense_base_labels = {key: label for label, key in bases}
        tk.Button(
            line,
            text="+",
            command=confirm,
            bg="#15803d",
            fg="white",
            activebackground="#166534",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=8,
            pady=0,
            font=("Segoe UI", 13, "bold"),
            cursor="hand2",
        ).pack(side="right", padx=(4, 0))
        set_combo.pack(side="left", fill="x", expand=True)

    def _side_button(self, parent: tk.Frame, text: str, command, compact: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="white",
            fg="#1c1917",
            activebackground="#e7e5e4",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#d6d3d1",
            padx=6,
            pady=2 if compact else 4,
            font=("Segoe UI", 9 if compact else 10),
            cursor="hand2",
        )

    def _wheel_tools(self, event) -> str | None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget in self.tool_canvases:
                top, bottom = widget.yview()
                if bottom - top >= 0.999:
                    return "break"
                widget.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _tool_button(self, parent: tk.Frame, tool: str) -> None:
        button = tk.Button(
            parent,
            text=SHAPE_LABEL[tool],
            command=lambda name=tool: self.set_tool(name),
            anchor="w",
            bg="white",
            fg="#1c1917",
            activebackground="#14532d",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        button.pack(fill="x", pady=2)
        self.tool_buttons[tool] = button

    def _rule(self, parent: tk.Frame) -> None:
        tk.Frame(parent, bg="#d6d3d1", height=1).pack(fill="x", pady=8)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _paint_route_color(self) -> None:
        for key, button in self.color_buttons.items():
            active = key == self.route_color
            button.configure(relief="solid" if active else "flat", bd=2 if active else 0)

    def _paint_route_tip(self) -> None:
        for key, button in self.tip_buttons.items():
            active = key == self.route_tip
            button.configure(relief="solid" if active else "flat", bd=2 if active else 0)

    def set_route_tip(self, tip: str | None) -> None:
        if tip not in (None, "arrow", "bar", "ring"):
            return
        self.route_tip = tip
        route = self.selected_route()
        if route is not None and route.ending != tip:
            before = self.snapshot()
            route.ending = tip
            self.commit_undo(before)
        self._paint_route_tip()
        self.redraw()
        names = {None: "automática", "arrow": "seta", "bar": "trave", "ring": "anel"}
        self.set_status(f"Ponta {names[tip]}. Vale para a rota selecionada e para a próxima.")

    def set_route_color(self, color: str) -> None:
        if color not in ROUTE_INK:
            return
        route = self.selected_route()
        if route is not None and route.kind in ("passe", "release", "sit"):
            before = self.snapshot()
            route.color = color
            self.route_color = color
            self.commit_undo(before)
            self._paint_route_color()
            self.redraw()
            self.set_status("Rota em laranja." if color == "laranja" else "Rota em verde.")
            return
        self.route_color = color
        self._paint_route_color()
        if self.draft and self.tool == "passe":
            self.redraw()
        self.set_status("Próxima rota em laranja." if color == "laranja" else "Próxima rota em verde.")

    def _sketching(self, tool: str | None = None) -> bool:
        name = self.tool if tool is None else tool
        return name in ROUTE_TOOLS or name == "blockpath"

    def set_tool(self, tool: str) -> None:
        if tool != self.tool and self._sketching() and not self._sketching(tool) and self.draft:
            self.draft = []
            self.draft_follow = None
            self.block_anchor = None
            self.set_status("Desenho da rota cancelado.")
        self.tool = tool
        for name, button in self.tool_buttons.items():
            if name == tool:
                button.configure(bg="#14532d", fg="white")
            else:
                button.configure(bg="white", fg="#1c1917")
        for tone, button in self.zone_buttons.items():
            _rgb, _label, bg, fg = ZONE_TONES[tone]
            active = tool == f"zone:{tone}"
            button.configure(bg=bg, fg=fg, relief="solid" if active else "flat", bd=2 if active else 0)
        self.sync_route_buttons()
        self.redraw()
        self.set_status(HINTS[tool])

    def sync_route_buttons(self) -> None:
        self.finish_button.configure(state="normal" if len(self.draft) >= 2 else "disabled")
        self.cancel_button.configure(state="normal" if self.draft else "disabled")

    def typing(self) -> bool:
        widget = self.focus_get()
        return isinstance(widget, (tk.Entry, tk.Listbox, tk.Text, ttk.Treeview))

    def layout_field(self) -> None:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        pad = 18
        self.scale = max(0.05, min((width - 2 * pad) / FIELD_W, (height - 2 * pad) / FIELD_H))
        self.ox = (width - FIELD_W * self.scale) / 2
        self.oy = (height - FIELD_H * self.scale) / 2

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.scale, self.oy + (y - FIELD_TOP) * self.scale

    def to_logical(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) / self.scale, (y - self.oy) / self.scale + FIELD_TOP

    def snap(self, value: float) -> float:
        step = YARD / 2
        return round(value / step) * step

    def pointer(self, event, angle: bool = False) -> tuple[float, float]:
        self.layout_field()
        x, y = self.to_logical(event.x, event.y)
        if angle and self.draft and (event.state & 0x0001):
            origin = self.draft[-1]
            dx, dy = x - origin[0], y - origin[1]
            dist = math.hypot(dx, dy)
            if dist > 0:
                turned = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
                x = origin[0] + dist * math.cos(turned)
                y = origin[1] + dist * math.sin(turned)
            return x, y
        if self.snap_var.get():
            x, y = self.snap(x), self.snap(y)
        return x, y

    def redraw(self) -> None:
        self.layout_field()
        if self.canvas.winfo_width() < 20 or self.canvas.winfo_height() < 20:
            return
        self.canvas.delete("all")
        self._zone_photos = []
        self._player_photos = []
        self.draw_field()
        self.draw_zones()
        under = self.defense_back.get()
        if under:
            for shape in self.shapes:
                if shape.side == "defesa" and shape.kind != "zone":
                    self.draw_shape(shape, self.selection == ("shape", shape.id), faded=True)
        for route in self.routes:
            selected = self.selection == ("route", route.id)
            self.draw_route(route.kind, route_path(route, self.routes), selected, route.split, route.color, route.ending)
            if selected:
                self.draw_route_handles(route_path(route, self.routes))
        for shape in self.shapes:
            if shape.kind == "zone":
                continue
            if under and shape.side == "defesa":
                continue
            self.draw_shape(shape, self.selection == ("shape", shape.id))
        if self.selection and self.selection[0] == "shape" and self.tool == "select":
            shape = self.selected_shape()
            if shape:
                self.draw_handles(shape)
        self.draw_draft()
        self.draw_play()
        self.sync_route_buttons()

    def draw_field(self) -> None:
        x0, y0 = self.to_screen(0, FIELD_TOP)
        x1, y1 = self.to_screen(FIELD_W, FIELD_BOTTOM)
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="white", outline="#111111", width=2)
        for relative in range(FRONT_YARDS, -BACK_YARDS - 1, -1):
            y = LOS_Y - relative * YARD
            sx0, sy = self.to_screen(0, y)
            sx1, _sy = self.to_screen(FIELD_W, y)
            if relative == 0:
                self.canvas.create_line(sx0, sy, sx1, sy, fill="#111111", width=3)
                continue
            if relative % 5 == 0:
                width = 2 if relative % 10 == 0 else 1
                self.canvas.create_line(sx0, sy, sx1, sy, fill="#111111", width=width)
            else:
                self._hash(y)
            if relative in (10, 20, 30, 40):
                label_y = y + 12 if relative == FRONT_YARDS else y
                self.canvas.create_text(
                    *self.to_screen(36, label_y),
                    text=str(relative),
                    fill="#111111",
                    font=("Segoe UI", 11, "bold"),
                )
                self.canvas.create_text(
                    *self.to_screen(FIELD_W - 36, label_y),
                    text=str(relative),
                    fill="#111111",
                    font=("Segoe UI", 11, "bold"),
                )
        ball = self.to_screen(FIELD_W / 2, LOS_Y)
        self.canvas.create_oval(ball[0] - 8, ball[1] - 5, ball[0] + 8, ball[1] + 5, fill="#111111", outline="#111111")
        self.canvas.create_text(
            *self.to_screen(58, LOS_Y - 16),
            text="LOS",
            fill="#111111",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        formation = self.formation_caption()
        if formation:
            self.canvas.create_text(
                *self.to_screen(FIELD_W / 2, FIELD_TOP + 22),
                text=formation,
                fill="#1c1917",
                font=("Segoe UI", 13, "bold"),
            )

    def draw_zones(self) -> None:
        from PIL import Image, ImageDraw, ImageTk

        for shape in self.shapes:
            if shape.kind != "zone":
                continue
            x0, y0 = self.to_screen(shape.x, shape.y)
            x1, y1 = self.to_screen(shape.x + shape.w, shape.y + shape.h)
            left, top = int(min(x0, x1)), int(min(y0, y1))
            width, height = max(2, int(abs(x1 - x0))), max(2, int(abs(y1 - y0)))
            rgb = ZONE_TONES.get(shape.tone, ZONE_TONES["amarelo"])[0]
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((0, 0, width - 1, height - 1), fill=(*rgb, ZONE_ALPHA))
            if self.selection == ("shape", shape.id):
                draw.ellipse((2, 2, width - 3, height - 3), outline=(*rgb, 230), width=3)
            photo = ImageTk.PhotoImage(image)
            self._zone_photos.append(photo)
            self.canvas.create_image(left, top, image=photo, anchor="nw")

    def _hash(self, y: float) -> None:
        left = HASH_X
        right = FIELD_W - left
        for hx in (left, right):
            x, y0 = self.to_screen(hx, y - 4)
            _x, y1 = self.to_screen(hx, y + 4)
            self.canvas.create_line(x, y0, x, y1, fill="#111111", width=2)

    def draw_shape(self, shape: Shape, selected: bool, faded: bool = False) -> None:
        x0, y0 = self.to_screen(shape.x, shape.y)
        x1, y1 = self.to_screen(shape.x + shape.w, shape.y + shape.h)
        if faded:
            self._draw_faded_player(shape, x0, y0, x1, y1, selected)
            return
        outline = "#ea580c" if selected else "#111111"
        width = 3 if selected else 2
        if shape.kind == "x":
            self.canvas.create_polygon(defense_triangle(x0, y0, x1, y1), fill=DEFENSE_FILL, outline=outline, width=width)
            if shape.text:
                self.canvas.create_text(
                    (x0 + x1) / 2,
                    (y0 * 2 + y1) / 3,
                    text=shape.text,
                    fill="#111111",
                    font=self.font_for(shape),
                )
            return
        if shape.kind == "circle":
            self.canvas.create_oval(x0, y0, x1, y1, fill="#111111", outline=outline, width=width)
        elif shape.kind == "triangle":
            points = (x0 + (x1 - x0) / 2, y0, x1, y1, x0, y1)
            self.canvas.create_polygon(points, fill="#111111", outline=outline, width=width)
        else:
            self.canvas.create_rectangle(x0, y0, x1, y1, fill="#111111", outline=outline, width=width)
        if shape.text:
            if shape.kind == "triangle":
                cy = y0 * 0.42 + y1 * 0.58
            else:
                cy = (y0 + y1) / 2
            self.canvas.create_text(
                (x0 + x1) / 2,
                cy,
                text=shape.text,
                fill="white",
                font=self.font_for(shape),
            )

    def _draw_faded_player(self, shape: Shape, x0: float, y0: float, x1: float, y1: float, selected: bool) -> None:
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        pad = 4
        left, top = int(min(x0, x1)) - pad, int(min(y0, y1)) - pad
        right, bottom = int(max(x0, x1)) + pad, int(max(y0, y1)) + pad
        image = Image.new("RGBA", (max(2, right - left), max(2, bottom - top)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        points = defense_triangle(x0, y0, x1, y1)
        polygon = [(points[index] - left, points[index + 1] - top) for index in range(0, 6, 2)]
        outline = (234, 88, 12, 230) if selected else (17, 17, 17, 200)
        draw.polygon(polygon, fill=(212, 212, 212, DEFENSE_ALPHA), outline=outline)
        if shape.text:
            _family, size, *_rest = self.font_for(shape)
            try:
                font = ImageFont.truetype("segoeuib.ttf", size)
            except OSError:
                font = ImageFont.load_default()
            draw.text(
                ((x0 + x1) / 2 - left, (y0 * 2 + y1) / 3 - top),
                shape.text,
                fill=(17, 17, 17, 220),
                font=font,
                anchor="mm",
            )
        photo = ImageTk.PhotoImage(image)
        self._player_photos.append(photo)
        self.canvas.create_image(left, top, image=photo, anchor="nw")

    def font_for(self, shape: Shape) -> tuple:
        size = max(7, min(13, int(min(shape.w, shape.h) * self.scale * 0.46)))
        text = shape.text or ""
        while size > 7 and len(text) * size * 0.58 > shape.w * self.scale - 4:
            size -= 1
        return ("Segoe UI", size, "bold")

    def draw_route(
        self,
        kind: str,
        points: list,
        selected: bool,
        split: int | None = None,
        color: str | None = None,
        tip: str | None = None,
    ) -> None:
        if kind == "release" and isinstance(split, int) and 0 < split < len(points) - 1:
            self._stroke(points[: split + 1], "bloqueio", selected, "open", color)
            self._stroke(points[split:], "passe", selected, route_ending("passe", tip), color)
            return
        if kind in ("paroute", "pablock") and isinstance(split, int) and 0 < split < len(points) - 1:
            self._stroke(points[: split + 1], "playaction", selected, "open", None)
            final = "bloqueio" if kind == "pablock" else "passe"
            self._stroke(points[split:], "playaction", selected, route_ending(final, tip), None, dashed=False)
            return
        if kind == "papass":
            self._stroke(points, "playaction", selected, "open", None)
            return
        self._stroke(points, kind, selected, route_ending(kind, tip), color)

    def _stroke(self, points: list, kind: str, selected: bool, ending: str, color: str | None = None, dashed: bool | None = None) -> None:
        screen = straighten_axis([self.to_screen(p[0], p[1]) for p in points])
        color = route_ink("bloqueio" if kind in BLOCK_KINDS else kind, color)
        if len(screen) == 1:
            x, y = screen[0]
            self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
            return
        if len(screen) < 2:
            return
        width = 4 if selected else 3
        dash = (9, 6) if (kind == "playaction" and dashed is not False) else None
        end = screen[-1]
        prev = screen[-2]
        vector = direction(prev, end)
        line = list(screen)
        if vector and ending == "arrow":
            dist = math.hypot(end[0] - prev[0], end[1] - prev[1])
            cut = min(12, dist * 0.45)
            line[-1] = (end[0] - vector[0] * cut, end[1] - vector[1] * cut)
        elif vector and ending == "ring":
            dist = math.hypot(end[0] - prev[0], end[1] - prev[1])
            cut = min(5, dist * 0.4)
            line[-1] = (end[0] - vector[0] * cut, end[1] - vector[1] * cut)
        if kind == "motion":
            line = wavy_line(line, amplitude=4.5)
            dash = None
        flat = [value for point in line for value in point]
        self.canvas.create_line(*flat, fill=color, width=width, dash=dash, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        if not vector or ending == "open":
            return
        if ending == "bar":
            self.draw_bar(end, vector, color, width)
        elif ending == "ring":
            self.draw_ring(end, color, width)
        else:
            self.draw_arrow(end, vector, color)

    def draw_ring(self, tip: tuple[float, float], color: str, _width: int) -> None:
        radius = 4
        self.canvas.create_oval(
            tip[0] - radius,
            tip[1] - radius,
            tip[0] + radius,
            tip[1] + radius,
            outline=color,
            width=2,
        )

    def draw_arrow(self, tip: tuple[float, float], vector: tuple[float, float], color: str) -> None:
        ux, uy = vector
        px, py = -uy, ux
        size = 13
        left = (tip[0] - ux * size + px * size * 0.55, tip[1] - uy * size + py * size * 0.55)
        right = (tip[0] - ux * size - px * size * 0.55, tip[1] - uy * size - py * size * 0.55)
        self.canvas.create_polygon(tip[0], tip[1], left[0], left[1], right[0], right[1], fill=color, outline=color)

    def draw_bar(self, tip: tuple[float, float], vector: tuple[float, float], color: str, width: int) -> None:
        _ux, _uy = vector
        px, py = -vector[1], vector[0]
        length = 12
        self.canvas.create_line(
            tip[0] - px * length,
            tip[1] - py * length,
            tip[0] + px * length,
            tip[1] + py * length,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
        )

    def draw_route_handles(self, points: list) -> None:
        for point in points:
            x, y = self.to_screen(point[0], point[1])
            self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="white", outline="#0f172a", width=2)

    def draw_handles(self, shape: Shape) -> None:
        for _name, (x, y) in self.handle_positions(shape).items():
            self.canvas.create_rectangle(x - 5, y - 5, x + 5, y + 5, fill="white", outline="#111111", width=2)

    def draw_draft(self) -> None:
        if not self.draft or not self._sketching():
            return
        points = [p[:] for p in self.draft]
        if self.mouse is not None:
            points.append([self.mouse[0], self.mouse[1]])
        kind = self.block_kind if self.tool == "blockpath" and self.block_kind else self.tool
        color = route_ink(kind, self.route_color)
        screen = [self.to_screen(p[0], p[1]) for p in self.draft]
        for x, y in screen:
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="#0f172a")
        if self.mouse is None or len(points) < 2:
            return
        rubber = straighten_axis([self.to_screen(p[0], p[1]) for p in points])
        if self.tool == "motion":
            rubber = wavy_line(rubber, amplitude=4)
        flat = [value for point in rubber for value in point]
        self.canvas.create_line(*flat, fill=color, width=2, dash=(5, 4), capstyle=tk.ROUND, joinstyle=tk.ROUND)

    def handle_positions(self, shape: Shape) -> dict[str, tuple[float, float]]:
        x0, y0 = self.to_screen(shape.x, shape.y)
        x1, y1 = self.to_screen(shape.x + shape.w, shape.y + shape.h)
        return {"nw": (x0, y0), "ne": (x1, y0), "sw": (x0, y1), "se": (x1, y1)}

    def hit_handle(self, event) -> str | None:
        shape = self.selected_shape()
        if not shape or self.tool != "select":
            return None
        self.layout_field()
        for name, (x, y) in self.handle_positions(shape).items():
            if math.hypot(event.x - x, event.y - y) <= 10:
                return name
        return None

    def shape_polygon(self, shape: Shape) -> list[tuple[float, float]]:
        if shape.kind == "triangle":
            return [
                (shape.x + shape.w / 2, shape.y),
                (shape.x + shape.w, shape.y + shape.h),
                (shape.x, shape.y + shape.h),
            ]
        if shape.kind == "x":
            return [
                (shape.x, shape.y),
                (shape.x + shape.w, shape.y),
                (shape.x + shape.w / 2, shape.y + shape.h),
            ]
        return [
            (shape.x, shape.y),
            (shape.x + shape.w, shape.y),
            (shape.x + shape.w, shape.y + shape.h),
            (shape.x, shape.y + shape.h),
        ]

    def shape_contains(self, shape: Shape, x: float, y: float) -> bool:
        if shape.kind in ("circle", "zone"):
            cx, cy = shape.x + shape.w / 2, shape.y + shape.h / 2
            rx, ry = shape.w / 2, shape.h / 2
            return rx > 0 and ry > 0 and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1
        return point_in_poly(x, y, self.shape_polygon(shape))

    def hit_shape(self, x: float, y: float) -> Shape | None:
        for shape in reversed(self.shapes):
            if shape.kind == "zone":
                continue
            if self.shape_contains(shape, x, y):
                return shape
        return None

    def hit_zone(self, x: float, y: float) -> Shape | None:
        for shape in reversed(self.shapes):
            if shape.kind == "zone" and self.shape_contains(shape, x, y):
                return shape
        return None

    def hit_route(self, x: float, y: float) -> Route | None:
        tolerance = 8 / self.scale
        for route in reversed(self.routes):
            points = route_path(route, self.routes)
            for index in range(len(points) - 1):
                if dist_to_segment(x, y, points[index], points[index + 1]) <= tolerance:
                    return route
        return None

    def hit_route_point(self, route: Route, event) -> int | None:
        self.layout_field()
        tolerance = 10 / self.scale
        x, y = self.to_logical(event.x, event.y)
        for index, point in enumerate(route_path(route, self.routes)):
            if math.hypot(x - point[0], y - point[1]) <= tolerance:
                return index
        return None

    def selected_shape(self) -> Shape | None:
        if not self.selection or self.selection[0] != "shape":
            return None
        return next((shape for shape in self.shapes if shape.id == self.selection[1]), None)

    def selected_route(self) -> Route | None:
        if not self.selection or self.selection[0] != "route":
            return None
        return next((route for route in self.routes if route.id == self.selection[1]), None)

    def _note_lean(self, route: Route) -> None:
        if len(route.points) < 2:
            return
        place = {-1: "inclinada à esquerda", 0: "no meio", 1: "inclinada à direita"}.get(route.lean, "no meio")
        self.set_status(f"Rota {place}. Seta esquerda e seta direita mudam a inclinação em 45°.")

    def _is_run_arrow(self, route: Route) -> bool:
        return route.kind == "rbrun" and len(route.points) == 2

    def _path_label(self) -> str:
        return {"blockrun": "Block run", "blockpass": "Block pass", "rbrun": "RB run"}.get(self.block_kind or "", "Linha")

    def _piece_center(self, x: float, y: float) -> tuple[float, float]:
        shape = self.hit_shape(x, y)
        if shape is None:
            return x, y
        return shape.x + shape.w / 2, shape.y + shape.h / 2

    def _move_run_tip(self, route: Route, x: float, y: float, angle: float) -> None:
        shift_x, shift_y = follow_shift(route, self.routes)
        route.points[-1] = unwind_point(route.points[0], angle, x - shift_x, y - shift_y)

    def select(self, kind: str | None, item_id: str | None = None) -> None:
        self.selection = None if kind is None else (kind, item_id or "")
        route = self.selected_route()
        if route is not None and route.color in ROUTE_INK:
            self.route_color = route.color
            self._paint_route_color()
        self.reload_label()
        self.redraw()

    def reload_label(self) -> None:
        self._suspend = True
        shape = self.selected_shape()
        self.label_var.set(shape.text if shape else "")
        self._suspend = False

    def on_label_write(self, *_args) -> None:
        if self._suspend:
            return
        shape = self.selected_shape()
        if not shape:
            return
        if self._text_before is None:
            self._text_before = self.snapshot()
        shape.text = self.label_var.get()
        self.dirty = True
        self.redraw()

    def on_label_focus_out(self, _event=None) -> None:
        if self._text_before is None:
            return
        before = self._text_before
        self._text_before = None
        if self.snapshot() != before:
            self.commit_undo(before)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop_play()
            return
        if not any(len(route.points) >= 2 for route in self.routes):
            self.set_status("Não há rotas para o timer. Desenhe uma rota e clique em Play.")
            return
        self.playing = True
        self.play_elapsed = 0.0
        self._play_last = time.monotonic()
        self.play_button.configure(text="Parar")
        if snap_distance(self.routes) > 0:
            self.set_status("Motion primeiro. As outras rotas saem quando ele termina.")
        else:
            self.set_status("Timer em curso. O ponto anda igual em todas as rotas.")
        self._tick_play()

    def stop_play(self, quiet: bool = False) -> None:
        self.playing = False
        if self._play_job is not None:
            self.after_cancel(self._play_job)
            self._play_job = None
        if hasattr(self, "play_button"):
            self.play_button.configure(text="Play")
        if quiet:
            return
        self.redraw()
        self.set_status("Animação parada.")

    def _tick_play(self) -> None:
        if not self.playing or not self.winfo_exists():
            return
        now = time.monotonic()
        self.play_elapsed += now - self._play_last
        self._play_last = now
        duration = play_distance(self.routes) / (PLAY_YARDS_PER_SEC * YARD)
        if self.play_elapsed > duration + 0.45:
            self.play_elapsed = 0.0
        self.redraw()
        self.set_status(
            f"Timer {self.play_elapsed:.1f} s · jogada {jogada_seconds(self.play_elapsed, self.routes):.1f} s · {alvo_label(self.play_elapsed, self.routes)}"
        )
        self._play_job = self.after(40, self._tick_play)

    def draw_play(self) -> None:
        if not self.playing:
            return
        traveled = self.play_elapsed * PLAY_YARDS_PER_SEC * YARD
        snap = snap_distance(self.routes)
        continued = {route.follow for route in self.routes if route.follow}
        for route in self.routes:
            found = dot_position(route, traveled, snap, continued, self.routes)
            if found is None:
                continue
            x, y = found
            if any(self._hides_dot(shape, x, y) for shape in self.shapes):
                continue
            sx, sy = self.to_screen(x, y)
            self.canvas.create_oval(sx - 7, sy - 7, sx + 7, sy + 7, fill=moving_ink(route), outline="#111111", width=2)
        self.canvas.create_text(
            *self.to_screen(FIELD_W - 28, FIELD_TOP + 36),
            text=f"{self.play_elapsed:.1f} s",
            fill="#111111",
            font=("Segoe UI", 16, "bold"),
            anchor="e",
        )
        self.canvas.create_text(
            *self.to_screen(FIELD_W - 28, FIELD_TOP + 58),
            text=f"jogada {jogada_seconds(self.play_elapsed, self.routes):.1f} s",
            fill="#111111",
            font=("Segoe UI", 12, "bold"),
            anchor="e",
        )
        self.canvas.create_text(
            *self.to_screen(FIELD_W - 28, FIELD_TOP + 78),
            text=alvo_label(self.play_elapsed, self.routes),
            fill="#111111",
            font=("Segoe UI", 12, "bold"),
            anchor="e",
        )

    def on_down(self, event) -> None:
        if self.playing:
            self.stop_play(quiet=True)
        self.canvas.focus_set()
        x, y = self.pointer(event, angle=self._sketching())

        self._before = None
        self.drag = None

        if self._sketching():
            now = time.monotonic()
            if (
                self.draft
                and now - self._last_click_at < 0.3
            and math.hypot(event.x - self._last_click_pos[0], event.y - self._last_click_pos[1]) < 14
        ):
                self.finish_route()
                self._last_click_at = now
                return
            if self.tool == "blockpath" and not self.draft:
                shape = self.hit_shape(x, y)
                if shape is None or shape.side == "defesa" or shape.kind in ("x", "zone"):
                    self.set_status("Clique um jogador do ataque. O bloqueio nasce nele.")
                    return
                self.select("shape", shape.id)
                self._anchor_block(shape)
                self._last_click_at = now
                self._last_click_pos = (event.x, event.y)
                return
            if not self.draft and self.tool not in ("motion", "blockpath"):
                lead = self._active_lead()
                if lead is not None and lead.points:
                    self.draft = [lead.points[-1][:]]
                    self.draft_follow = lead.id
            if not self.draft:
                self.layout_field()
                hx, hy = self.to_logical(event.x, event.y)
                x, y = self._piece_center(hx, hy)
            if not self.draft or math.hypot(x - self.draft[-1][0], y - self.draft[-1][1]) >= 4:
                self.draft.append([x, y])
            self._last_click_at = now
            self._last_click_pos = (event.x, event.y)
            self.mouse = (x, y)
            self.redraw()
            count = len(self.draft)
            if self.tool == "blockpath":
                label = self._path_label()
                self.set_status(f"{label} com {count} ponto(s). O clique esquerdo continua. O direito conclui.")
            else:
                self.set_status(f"Rota com {count} ponto(s). Enter conclui, Backspace volta um ponto.")
            return

        if self.tool in SHAPE_TOOLS:
            self.place_shape(self.tool, x, y)
            return

        if self.tool.startswith("zone:"):
            self.place_zone(self.tool.split(":", 1)[1], x, y)
            return

        handle = self.hit_handle(event)
        if handle:
            shape = self.selected_shape()
            self._before = self.snapshot()
            self.drag = {"mode": "resize", "handle": handle, "box": (shape.x, shape.y, shape.w, shape.h)}
            return

        route = self.selected_route()
        if route:
            index = self.hit_route_point(route, event)
            last = len(route.points) - 1
            if self._is_run_arrow(route) and index != 0 and (index == last or self.hit_route(x, y) is route):
                self._before = self.snapshot()
                self.drag = {"mode": "stretch", "angle": lean_angle(route.points, route.lean)}
                self.set_status("Puxe a ponta para mudar o tamanho. As setas giram em 45°.")
                return
            if index is not None:
                self._before = self.snapshot()
                self.drag = {
                    "mode": "point",
                    "index": index,
                    "angle": lean_angle(route.points, route.lean) if len(route.points) >= 2 else 0.0,
                }
                self._note_lean(route)
                return

        shape = self.hit_shape(x, y)
        if shape:
            self.select("shape", shape.id)
            self._before = self.snapshot()
            attached = [(route, copy.deepcopy(route.points)) for route in self._routes_moving_with(shape)]
            self.drag = {"mode": "move", "ox": shape.x, "oy": shape.y, "mx": x, "my": y, "routes": attached}
            return

        found = self.hit_route(x, y)
        if found:
            self.select("route", found.id)
            self._before = self.snapshot()
            if self._is_run_arrow(found):
                self.drag = {"mode": "stretch", "angle": lean_angle(found.points, found.lean)}
                self.set_status("Puxe a ponta para mudar o tamanho. As setas giram em 45°.")
            else:
                self.drag = {"mode": "move-route", "orig": copy.deepcopy(found.points), "mx": x, "my": y}
                self._note_lean(found)
            return

        zone = self.hit_zone(x, y)
        if zone:
            self.select("shape", zone.id)
            self._before = self.snapshot()
            self.drag = {"mode": "move", "ox": zone.x, "oy": zone.y, "mx": x, "my": y, "routes": []}
            return

        self.select(None)

    def on_drag(self, event) -> None:
        if not self.drag:
            return
        x, y = self.pointer(event)
        mode = self.drag["mode"]
        if mode == "move":
            shape = self.selected_shape()
            if not shape:
                return
            shape.x = self.drag["ox"] + (x - self.drag["mx"])
            shape.y = self.drag["oy"] + (y - self.drag["my"])
            if self.snap_var.get():
                shape.x, shape.y = self.snap(shape.x), self.snap(shape.y)
            dx = shape.x - self.drag["ox"]
            dy = shape.y - self.drag["oy"]
            for route, orig in self.drag.get("routes", ()):
                route.points = [[px + dx, py + dy] for px, py in orig]
        elif mode == "resize":
            shape = self.selected_shape()
            if shape:
                self.apply_resize(shape, self.drag["handle"], x, y, self.drag["box"])
        elif mode == "point":
            route = self.selected_route()
            if route:
                index = self.drag["index"]
                shift_x, shift_y = follow_shift(route, self.routes)
                if index == 0:
                    route.points[0] = [x - shift_x, y - shift_y]
                else:
                    route.points[index] = unwind_point(
                        route.points[0],
                        self.drag.get("angle", 0.0),
                        x - shift_x,
                        y - shift_y,
                    )
        elif mode == "stretch":
            route = self.selected_route()
            if route and len(route.points) >= 2:
                self._move_run_tip(route, x, y, self.drag.get("angle", 0.0))
        elif mode == "move-route":
            route = self.selected_route()
            if route:
                dx, dy = x - self.drag["mx"], y - self.drag["my"]
                origin = self.drag["orig"][0]
                if self.snap_var.get():
                    dx = self.snap(origin[0] + dx) - origin[0]
                    dy = self.snap(origin[1] + dy) - origin[1]
                route.points = [[px + dx, py + dy] for px, py in self.drag["orig"]]
                if route.kind in ("motion", "papass"):
                    self._glue_followers(route)
        if mode == "point":
            route = self.selected_route()
            if route and route.kind in ("motion", "papass"):
                self._glue_followers(route)
        self.redraw()

    def apply_resize(self, shape: Shape, handle: str, x: float, y: float, box: tuple[float, float, float, float]) -> None:
        ox, oy, ow, oh = box
        anchors = {
            "se": (ox, oy, x, y),
            "nw": (ox + ow, oy + oh, x, y),
            "ne": (ox, oy + oh, x, y),
            "sw": (ox + ow, oy, x, y),
        }
        ax, ay, nx, ny = anchors[handle]
        left, right = sorted((ax, nx))
        top, bottom = sorted((ay, ny))
        if right - left < MIN_SIZE:
            if nx >= ax:
                right = left + MIN_SIZE
            else:
                left = right - MIN_SIZE
        if bottom - top < MIN_SIZE:
            if ny >= ay:
                bottom = top + MIN_SIZE
            else:
                top = bottom - MIN_SIZE
        shape.x, shape.y = left, top
        shape.w, shape.h = right - left, bottom - top

    def on_up(self, _event) -> None:
        if self.drag and self._before is not None and self.snapshot() != self._before:
            self.commit_undo(self._before)
        self.drag = None
        self._before = None

    def on_motion(self, event) -> None:
        if self._sketching() and self.draft:
            self.mouse = self.pointer(event, angle=True)
            self.canvas.configure(cursor="crosshair")
            self.redraw()
            return
        self.mouse = None
        if self.tool != "select":
            self.canvas.configure(cursor="crosshair")
            return
        if self.hit_handle(event):
            self.canvas.configure(cursor="sizing")
            return
        x, y = self.pointer(event)
        if self.hit_shape(x, y) or self.hit_route(x, y) or self.hit_zone(x, y):
            self.canvas.configure(cursor="hand2")
        else:
            self.canvas.configure(cursor="arrow")

    def on_right(self, event) -> None:
        if self._sketching() and self.draft:
            self.finish_route()
            return
        route = self.selected_route()
        if not route or self.tool != "select":
            return
        index = self.hit_route_point(route, event)
        if index is None or len(route.points) <= 2:
            return
        before = self.snapshot()
        route.points.pop(index)
        self.commit_undo(before)
        self.redraw()

    def on_double(self, event) -> None:
        if self.tool != "select":
            return
        x, y = self.pointer(event)
        shape = self.hit_shape(x, y)
        if not shape:
            return
        self.select("shape", shape.id)
        self.label_entry.focus_set()
        self.label_entry.selection_range(0, tk.END)

    def place_shape(self, kind: str, x: float, y: float) -> None:
        before = self.snapshot()
        if kind == "rectangle":
            w, h = 64, 28
        elif kind == "triangle":
            w, h = 26, 24
        elif kind == "square":
            w, h = OL_SIZE, OL_SIZE
        elif kind == "x":
            w, h = DEF_SIZE, DEF_SIZE
        else:
            w, h = SKILL_SIZE, SKILL_SIZE
        if self.snap_var.get():
            x, y = self.snap(x), self.snap(y)
        shape = Shape(
            new_id(),
            kind,
            x - w / 2,
            y - h / 2,
            w,
            h,
            "",
            "defesa" if kind == "x" else "ataque",
        )
        self.shapes.append(shape)
        self.selection = ("shape", shape.id)
        self.commit_undo(before)
        self.reload_label()
        self.set_tool("select")
        self.set_status("Peça selecionada. Arraste para mover. Cada canto muda largura e altura por conta.")

    def place_zone(self, tone: str, x: float, y: float) -> None:
        if tone not in ZONE_TONES:
            return
        before = self.snapshot()
        size = 8 * YARD
        if self.snap_var.get():
            x, y = self.snap(x), self.snap(y)
        shape = Shape(new_id(), "zone", x - size / 2, y - size / 2, size, size, "", "zona", tone)
        self.shapes.append(shape)
        self.selection = ("shape", shape.id)
        self.commit_undo(before)
        self.reload_label()
        self.set_tool("select")
        self.set_status(f"Área {ZONE_TONES[tone][1].lower()} selecionada. Arraste, use as setas, ou puxe um canto.")

    def finish_route(self) -> None:
        if len(self.draft) < 2:
            self.set_status("A rota precisa de pelo menos dois pontos.")
            return
        before = self.snapshot()
        if self.tool == "blockpath":
            kind = self.block_kind if self.block_kind in ("blockrun", "blockpass", "rbrun") else "blockrun"
            self._clear_anchor_routes()
            follow = None
        else:
            kind = self.tool if self.tool in ROUTE_TOOLS else "passe"
            follow = self.draft_follow if kind not in ("motion", "papass") else None
            if follow and not any(item.kind in ("motion", "papass") and item.id == follow for item in self.routes):
                follow = None
        route = Route(
            new_id(),
            kind,
            [p[:] for p in self.draft],
            color=self.route_color if kind == "passe" else None,
            follow=follow,
            ending=self.route_tip,
        )
        self.routes.append(route)
        anchor = next((shape for shape in self.shapes if shape.id == self.block_anchor), None)
        self.draft = []
        self.draft_follow = None
        self.mouse = None
        self.block_anchor = None
        self.block_kind = None
        self.selection = ("route", route.id)
        self.commit_undo(before)
        self.reload_label()
        self.set_tool("select")
        if kind in ("blockrun", "blockpass", "rbrun"):
            label = {"blockrun": "Block run", "blockpass": "Block pass", "rbrun": "RB run"}[kind]
            who = anchor.text if anchor is not None and anchor.text else "o jogador"
            self.set_status(f"{label} de {who}. A linha sai dele.")
            return
        self.set_status("Rota selecionada. Arraste para mover ou puxe um ponto para ajustar.")

    def begin_block_path(self, kind: str) -> None:
        self.block_kind = kind
        self.block_anchor = None
        self.draft = []
        self.draft_follow = None
        self.mouse = None
        self.set_tool("blockpath")
        shape = self.selected_shape()
        if shape is not None and shape.side != "defesa" and shape.kind not in ("x", "zone"):
            self._anchor_block(shape)

    def _anchor_block(self, shape: Shape) -> None:
        self.block_anchor = shape.id
        self.draft = [[shape.x + shape.w / 2, shape.y + shape.h / 2]]
        self.draft_follow = None
        self.mouse = tuple(self.draft[0])
        self.sync_route_buttons()
        self.redraw()
        who = shape.text or "o jogador"
        label = {"blockrun": "Block run", "blockpass": "Block pass", "rbrun": "RB run"}.get(self.block_kind, "Linha")
        self.set_status(f"{label} de {who}. A linha está nele. Clique o percurso. Botão direito conclui.")

    def _clear_anchor_routes(self) -> None:
        shape = next((item for item in self.shapes if item.id == self.block_anchor), None)
        if shape is None:
            return
        removed: set[str] = set()
        for route in self.routes:
            if self._starts_on(route, shape):
                removed.update(self._chain_from(route.id))
        self.routes = [route for route in self.routes if route.id not in removed]

    def cancel_draft(self) -> None:
        self.draft = []
        self.draft_follow = None
        self.mouse = None
        self.block_anchor = None
        self.redraw()
        if self.tool == "blockpath":
            self.set_status(HINTS["blockpath"])
            return
        self.set_status("Rota cancelada.")

    def clear_defense(self) -> None:
        if not any(shape.side == "defesa" for shape in self.shapes):
            self.set_status("Não há jogadores de defesa.")
            return
        if not messagebox.askyesno(
            "Defesa",
            "Apagar todos os jogadores da defesa? A cobertura permanece.",
            parent=self,
        ):
            return
        before = self.snapshot()
        self.shapes = [shape for shape in self.shapes if shape.side != "defesa"]
        if self.selection and self.selection[0] == "shape":
            if not any(shape.id == self.selection[1] for shape in self.shapes):
                self.selection = None
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        self.set_status("Defesa apagada.")

    def _hides_dot(self, shape: Shape, x: float, y: float) -> bool:
        if shape.kind == "zone" or not self.shape_contains(shape, x, y):
            return False
        return not (self.defense_back.get() and shape.side == "defesa")

    def delete_selected(self) -> None:
        if self.typing():
            widget = self.focus_get()
            if isinstance(widget, tk.Entry):
                return
        if not self.selection:
            self.set_status("Nada selecionado.")
            return
        before = self.snapshot()
        kind, item_id = self.selection
        if kind == "shape":
            self.shapes = [shape for shape in self.shapes if shape.id != item_id]
        else:
            removed = next((route for route in self.routes if route.id == item_id), None)
            gone = set(self._chain_from(item_id)) if removed and removed.kind in ("motion", "papass") else {item_id}
            self.routes = [route for route in self.routes if route.id not in gone]
        self.selection = None
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        self.set_status("Seleção removida.")

    def insert_formation(self, base: str, style: str) -> None:
        title = formation_title("offense", base, style)
        attack = [shape for shape in self.shapes if shape.side != "defesa" and shape.kind != "zone"]
        if attack or self.routes:
            if not messagebox.askyesno(
                "Formação ofensiva",
                f"Isso substitui o ataque e as rotas por {title}. A defesa permanece.",
                parent=self,
            ):
                return
        before = self.snapshot()
        self.shapes = [shape for shape in self.shapes if shape.side == "defesa" or shape.kind == "zone"]
        self.routes = []
        self.draft = []
        self.selection = None
        for shape_kind, label, cx, cy, size in offense_players(base, style):
            self._add_player(shape_kind, cx, cy, size, label)
        self.offense_base = base
        self.offense_set = style
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        detail = formation_detail("offense", base, style)
        self.show_offense_formation()
        self.set_status(f"{title}: {detail}" if detail else title)

    def formation_caption(self) -> str:
        return formation_label(self.offense_base, self.offense_set)

    def show_offense_formation(self) -> None:
        """Os campos Base e Set mostram a formação gravada na jogada."""
        combo = getattr(self, "_offense_base_combo", None)
        if combo is None or not self.offense_base:
            return
        label = self._offense_base_labels.get(self.offense_base)
        if not label:
            return
        combo.set(label)
        options = self._offense_sets_for.get(self.offense_base, ())
        set_combo = self._offense_set_combo
        set_combo["values"] = [name for name, _key in options]
        wanted = dict((key, name) for name, key in options).get(self.offense_set or "")
        if wanted:
            set_combo.set(wanted)
        elif options:
            set_combo.current(0)

    def insert_defense(self, base: str, style: str) -> None:
        title = formation_title("defense", base, style)
        if any(shape.side == "defesa" for shape in self.shapes):
            if not messagebox.askyesno(
                "Defesa",
                f"Isso substitui a defesa por {title}. O ataque e as rotas permanecem.",
                parent=self,
            ):
                return
        before = self.snapshot()
        self.shapes = [shape for shape in self.shapes if shape.side != "defesa"]
        self.draft = []
        if self.selection and self.selection[0] == "shape":
            if not any(shape.id == self.selection[1] for shape in self.shapes):
                self.selection = None
        for label, cx, cy in defense_spots(base, style):
            self._add_player("x", cx, cy, DEF_SIZE, label, "defesa")
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        detail = formation_detail("defense", base, style)
        self.set_status(f"Defesa {title}: {detail}" if detail else f"Defesa {title}")

    def _add_player(self, kind: str, cx: float, cy: float, size: float, text: str, side: str = "ataque") -> None:
        self.shapes.append(Shape(new_id(), kind, cx - size / 2, cy - size / 2, size, size, text, side))

    def mirror_play(self) -> None:
        if not self.shapes and not self.routes and not self.draft:
            self.set_status("Nada para espelhar.")
            return
        before = self.snapshot()
        for shape in self.shapes:
            shape.x = FIELD_W - (shape.x + shape.w)
            shape.text = MIRROR_TEXT.get(shape.text, shape.text)
        for left, right in (("F", "A"), ("Y", "U")):
            texts = [shape.text for shape in self.shapes]
            if texts.count(left) == 1 and texts.count(right) == 1:
                for shape in self.shapes:
                    if shape.text == left:
                        shape.text = right
                    elif shape.text == right:
                        shape.text = left
        for route in self.routes:
            for point in route.points:
                point[0] = FIELD_W - point[0]
            if route.lean in (-1, 1):
                route.lean = -route.lean
        for point in self.draft:
            point[0] = FIELD_W - point[0]
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        self.set_status("Jogada espelhada. LT e RT, X e Z, Will e Sam trocam de lado.")

    def mirror_route(self) -> None:
        route = self.selected_route()
        if route is None or len(route.points) < 2:
            self.set_status("Clique na rota e use Espelhar rota. O jogador não se move.")
            return
        before = self.snapshot()
        origin = route.points[0][0]
        for point in route.points:
            point[0] = origin * 2 - point[0]
        if route.lean in (-1, 1):
            route.lean = -route.lean
        if route.kind in ("motion", "papass"):
            for follower_id in self._chain_from(route.id):
                if follower_id == route.id:
                    continue
                follower = next(item for item in self.routes if item.id == follower_id)
                for point in follower.points:
                    point[0] = origin * 2 - point[0]
                if follower.lean in (-1, 1):
                    follower.lean = -follower.lean
        self.commit_undo(before)
        self.redraw()
        self.set_status("Rota espelhada em torno do jogador.")

    def _starts_on(self, route: Route, shape: Shape) -> bool:
        if not route.points or route.kind not in ("passe", "sit", "motion", "playaction", "paroute", "pablock", "papass", "dropback", "release", "rbrun", *BLOCK_KINDS):
            return False
        x, y = route.points[0]
        return shape.x - 8 <= x <= shape.x + shape.w + 8 and shape.y - 8 <= y <= shape.y + shape.h + 8

    def _routes_moving_with(self, shape: Shape) -> list[Route]:
        """Rotas que saem desta peça. Cobertura não leva rota, mesmo grande."""
        if shape.kind == "zone":
            return []
        chosen: list[Route] = []
        seen: set[str] = set()
        for route in self.routes:
            if route.id in seen or not self._starts_on(route, shape):
                continue
            for item_id in self._chain_from(route.id):
                if item_id in seen:
                    continue
                chosen.append(next(item for item in self.routes if item.id == item_id))
                seen.add(item_id)
        return chosen

    def _shift_with_player(self, shape: Shape, dx: float, dy: float) -> None:
        routes = self._routes_moving_with(shape)
        shape.x += dx
        shape.y += dy
        if dx == 0 and dy == 0:
            return
        for route in routes:
            for point in route.points:
                point[0] += dx
                point[1] += dy

    def _chain_from(self, route_id: str) -> list[str]:
        ordered = [route_id]
        index = 0
        while index < len(ordered):
            current = ordered[index]
            index += 1
            for route in self.routes:
                if route.follow == current and route.id not in ordered:
                    ordered.append(route.id)
        return ordered

    def _motion_from(self, shape: Shape) -> Route | None:
        found = None
        for route in self.routes:
            if route.kind == "motion" and self._starts_on(route, shape):
                found = route
        return found

    def _papass_from(self, shape: Shape) -> Route | None:
        found = None
        for route in self.routes:
            if route.kind == "papass" and self._starts_on(route, shape):
                found = route
        if found is not None:
            return found
        motion = self._motion_from(shape)
        if motion is None:
            return None
        for route in self.routes:
            if route.kind == "papass" and route.follow == motion.id:
                return route
        return None

    def _active_lead(self) -> Route | None:
        route = self.selected_route()
        if route is not None and route.kind in ("papass", "motion") and route.points:
            return route
        shape = self.selected_shape()
        if shape is None:
            return None
        return self._papass_from(shape) or self._motion_from(shape)

    def _player_of(self, route: Route) -> Shape | None:
        seen: set[str] = set()
        current: Route | None = route
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.points:
                shape = self._player_at(current.points[0][0], current.points[0][1])
                if shape is not None:
                    return shape
            current = next((item for item in self.routes if item.id == current.follow), None) if current.follow else None
        return None

    def _glue_followers(self, lead: Route, seen: set[str] | None = None) -> None:
        if seen is None:
            seen = set()
        if lead.id in seen or not lead.points:
            return
        seen.add(lead.id)
        end_x, end_y = lead.points[-1]
        for route in self.routes:
            if route.follow != lead.id or not route.points or route.id in seen:
                continue
            dx = end_x - route.points[0][0]
            dy = end_y - route.points[0][1]
            if abs(dx) >= 1e-9 or abs(dy) >= 1e-9:
                for point in route.points:
                    point[0] += dx
                    point[1] += dy
            self._glue_followers(route, seen)

    def add_player_route(self, name: str) -> None:
        if self.tool == "blockpath":
            self.set_tool("select")
        shape = self.selected_shape()
        if shape is None or shape.side == "defesa" or shape.kind == "x":
            lead = self.selected_route()
            if lead is not None and lead.kind in ("motion", "papass") and lead.points:
                shape = self._player_of(lead)
            if shape is None or shape.side == "defesa" or shape.kind == "x":
                self.set_status("Selecione um jogador do ataque para lançar a rota.")
                return
        before = self.snapshot()
        cx = shape.x + shape.w / 2
        cy = shape.y + shape.h / 2
        motion = None if name == "motion" else self._motion_from(shape)
        papass = None if name in ("motion", "papass") else self._papass_from(shape)
        keep: set[str] = set()
        if papass is not None:
            keep.add(papass.id)
            if motion is not None and papass.follow == motion.id:
                keep.add(motion.id)
        elif motion is not None:
            keep.add(motion.id)
        removed: set[str] = {route.id for route in self.routes if self._starts_on(route, shape) and route.id not in keep}
        if papass is not None:
            for route in self.routes:
                if route.follow == papass.id:
                    removed.update(self._chain_from(route.id))
        elif motion is not None:
            for route in self.routes:
                if route.follow == motion.id:
                    removed.update(self._chain_from(route.id))
        else:
            for route in self.routes:
                if route.kind in ("motion", "papass") and self._starts_on(route, shape):
                    removed.update(self._chain_from(route.id))
        self.routes = [route for route in self.routes if route.id not in removed]
        kind = route_kind_for(name)
        if papass is not None and papass.points:
            origin_x, origin_y = papass.points[-1]
            follow_id = papass.id
        elif motion is not None and motion.points:
            origin_x, origin_y = motion.points[-1]
            follow_id = motion.id
        else:
            origin_x, origin_y = cx, cy
            follow_id = None
        if name == "dropback":
            points = dropback_points(origin_x, origin_y, self.offense_base, self._drop_backs(shape))
        else:
            points = route_for_player(name, shape.text, origin_x, origin_y, self._strong_sign())
        route = Route(
            new_id(),
            kind,
            points,
            1 if name in ("release", "paroute", "pablock") else None,
            self.route_color if kind in ("passe", "release", "sit") else None,
            follow_id,
            self.route_tip,
        )
        self.routes.append(route)
        self.selection = ("shape", shape.id)
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        labels = {
            "motion": "Motion",
            "playaction": "Play action",
            "paroute": "PA route",
            "pablock": "PA block",
            "papass": "PA pass",
            "blockrun": "Block run",
            "blockpass": "Block pass",
            "release": "Release",
            "dropback": "Dropback",
            "rbrun": "RB run",
        }
        label = labels.get(name, name.capitalize())
        who = shape.text or "o jogador"
        if name == "motion":
            self.set_status(f"Motion de {who}, antes do snap. Agora escolha a rota: ela começa no fim.")
        elif name == "paroute":
            self.set_status(f"Play action de {who}: o tracejado é o fake, a seta é a rota.")
        elif name == "pablock":
            self.set_status(f"Play action de {who}: o tracejado é o fake, a trave é o bloqueio.")
        elif name == "papass":
            self.set_status(f"Play action de {who}. Agora escolha a rota da árvore: ela começa quando o play action acaba.")
        elif papass is not None:
            self.set_status(f"{label} começa no fim do play action. Ela sai quando o play action acaba.")
        elif name == "chair":
            self.set_status(f"Chair de {who}: cinco jardas, 90° para fora e sobe de novo.")
        elif name == "sit":
            self.set_status(f"Sit de {who}: entra como a slant e a seta volta para o QB.")
        elif name == "wheel":
            self.set_status(f"Wheel de {who}: sai como a flat até perto da lateral e sobe em balão na go.")
        elif name == "whip":
            self.set_status(f"Whip de {who}: cinco jardas, ameaça para dentro e sai reto para fora.")
        elif name == "rbrun":
            self.set_status(f"Corrida de {who}, em laranja, no ritmo do bloqueio.")
        elif name == "dropback":
            yards = abs(route.points[-1][1] - route.points[0][1]) / YARD
            if abs(route.points[-1][0] - route.points[0][0]) > abs(route.points[-1][1] - route.points[0][1]):
                yards = abs(route.points[-1][0] - route.points[0][0]) / YARD
            formed = DROP_TITLE.get(self.offense_base or "", "formação")
            self.set_status(f"Dropback da {formed}, {yards:.1f} jarda(s). A ponta não passa de 5 jardas atrás da linha.")
        elif motion is not None:
            self.set_status(f"{label} começa no fim do motion. Os outros só saem quando o motion acaba.")
        else:
            self.set_status(f"{label} saindo de {who}.")

    def _strong_sign(self) -> int:
        for label in ("Y", "U"):
            for shape in self.shapes:
                if shape.text != label or shape.side == "defesa" or shape.kind in ("x", "zone"):
                    continue
                return 1 if shape.x + shape.w / 2 >= FIELD_W / 2 else -1
        return 1

    def _drop_backs(self, quarterback: Shape) -> list[tuple[float, float, float]]:
        backs = []
        for shape in self.shapes:
            if shape is quarterback or shape.text not in ("H", "FB"):
                continue
            if shape.side == "defesa" or shape.kind in ("x", "zone"):
                continue
            backs.append((shape.x + shape.w / 2, shape.y + shape.h / 2, max(shape.w, shape.h) / 2))
        return backs

    def _player_action(self, name: str) -> None:
        if name == "olrun":
            self.assign_line("blockrun")
        elif name == "olpass":
            self.assign_line("blockpass")
        elif name == "runpath":
            self.begin_block_path("blockrun")
        elif name == "passpath":
            self.begin_block_path("blockpass")
        elif name == "rbpath":
            self.begin_block_path("rbrun")
        else:
            self.add_player_route(name)

    def assign_line(self, name: str) -> None:
        if self.tool == "blockpath":
            self.set_tool("select")
        linemen = [
            shape
            for shape in self.shapes
            if shape.text in ("LT", "LG", "C", "RG", "RT") and shape.side != "defesa" and shape.kind != "zone"
        ]
        if not linemen:
            self.set_status("Não há linha ofensiva. Monte a formação: LT, LG, C, RG e RT.")
            return
        before = self.snapshot()
        removed: set[str] = set()
        for shape in linemen:
            for route in self.routes:
                if self._starts_on(route, shape):
                    removed.update(self._chain_from(route.id))
        self.routes = [route for route in self.routes if route.id not in removed]
        for shape in linemen:
            cx = shape.x + shape.w / 2
            cy = shape.y + shape.h / 2
            self.routes.append(Route(new_id(), name, route_preset(name, cx, cy), ending=self.route_tip))
        self.selection = None
        self.commit_undo(before)
        self.reload_label()
        self.redraw()
        label = "Block run" if name == "blockrun" else "Block pass"
        self.set_status(f"{label} em {len(linemen)} da linha: {', '.join(shape.text for shape in linemen)}.")

    def _player_at(self, x: float, y: float) -> Shape | None:
        for shape in self.shapes:
            if shape.side == "defesa" or shape.kind in ("x", "zone"):
                continue
            if shape.x - 8 <= x <= shape.x + shape.w + 8 and shape.y - 8 <= y <= shape.y + shape.h + 8:
                return shape
        return None

    def duplicate_play(self) -> None:
        current = self.name_var.get().strip()
        suggestion = f"{current} cópia" if current else "Cópia"
        name = simpledialog.askstring("Duplicar jogada", "Nome da cópia:", initialvalue=suggestion, parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            self.set_status("A cópia precisa de um nome.")
            return
        owner = play_id_for_name(name)
        if owner is not None:
            if not messagebox.askyesno("Duplicar jogada", f'Já existe "{name}". Substituir?', parent=self):
                return
        document = self.play_document()
        document["nome"] = name
        document["id"] = owner
        self.play_id = store_play(document)
        self._suspend = True
        self.name_var.set(name)
        self._suspend = False
        self.loaded_id = self.play_id
        self.mark_clean()
        self.remember_open()
        self.refresh_list()
        self.set_status(f"Cópia salva: {name}. Você está editando a nova jogada.")

    def export_image(self) -> None:
        name = self.name_var.get().strip() or "jogada"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar imagem",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile=filename_for(name).removesuffix(".json") + ".png",
        )
        if not path:
            return
        try:
            self.write_png(Path(path))
        except Exception as exc:
            messagebox.showerror("Exportar imagem", f"Não foi possível gerar a imagem.\n{exc}", parent=self)
            return
        self.set_status(f"Imagem exportada: {path}")

    def write_png(self, path: Path) -> None:
        image = self.render_board()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)

    def play_duration(self) -> float:
        distance = play_distance(self.routes)
        if distance <= 0:
            return 0.0
        return distance / (PLAY_YARDS_PER_SEC * YARD)

    def export_gif(self) -> None:
        motion = self.play_duration()
        if motion <= 0:
            self.set_status("Não há rotas para exportar. Desenhe a jogada e use GIF.")
            return
        name = self.name_var.get().strip() or "jogada"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar animação",
            defaultextension=".gif",
            filetypes=[("GIF", "*.gif")],
            initialfile=filename_for(name).removesuffix(".json") + ".gif",
        )
        if not path:
            return
        self.set_status("Gerando o GIF da jogada...")
        self.update_idletasks()
        try:
            self.write_gif(Path(path), motion)
        except Exception as exc:
            messagebox.showerror("Exportar animação", f"Não foi possível gerar o GIF.\n{exc}", parent=self)
            return
        self.set_status(f"GIF pronto para o WhatsApp: {path}")

    def write_gif(self, path: Path, motion: float) -> None:
        from PIL import Image

        fps = 10
        hold = 0.5
        count = max(2, int(round((motion + hold) * fps)))
        frames = []
        for index in range(count):
            elapsed = min(motion, index / fps)
            frames.append(self.render_board(scale=1, elapsed=elapsed, with_notes=False))
        palette = frames[0].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
        converted = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
        path.parent.mkdir(parents=True, exist_ok=True)
        converted[0].save(
            path,
            save_all=True,
            append_images=converted[1:],
            duration=int(1000 / fps),
            loop=0,
            optimize=True,
            disposal=2,
        )

    def saved_play_ids(self) -> list[int]:
        rows = sorted(stored_plays(), key=lambda row: str(row.get("nome") or "").casefold())
        return [int(row["id"]) for row in rows]

    def export_pdf(self) -> None:
        play_ids = self.saved_play_ids()
        if not play_ids and not self._play_on_screen():
            self.set_status("Não há jogadas salvas para o PDF. Salve a jogada e use PDF.")
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="jogadas.pdf",
        )
        if not path:
            return
        self.set_status("Gerando o PDF das jogadas...")
        self.update_idletasks()
        try:
            count, sheets = self.write_pdf(Path(path), play_ids)
        except Exception as exc:
            messagebox.showerror("Exportar PDF", f"Não foi possível gerar o PDF.\n{exc}", parent=self)
            return
        screen = self.dirty and (self.loaded_id is not None or self._play_on_screen())
        extra = " A jogada aberta entrou como está na tela." if screen else ""
        self.set_status(f"PDF com {count} jogadas em {sheets} folha(s): {path}.{extra}")

    def _play_on_screen(self) -> bool:
        if self.name_var.get().strip() or self.notes_text():
            return True
        return bool(self.shapes or self.routes)

    def write_pdf(self, path: Path, play_ids: list[int]) -> tuple[int, int]:
        cards = []
        seen_open = False
        for play_id in play_ids:
            if self.loaded_id is not None and play_id == self.loaded_id:
                cards.append((
                    self.render_board(scale=2, caption=False),
                    self.name_var.get().strip() or "Jogada",
                    self.notes_text(),
                    self.formation_caption(),
                ))
                seen_open = True
                continue
            data = stored_play(play_id)
            if data is None:
                continue
            title = str(data.get("nome") or "Jogada")
            cards.append((
                self.render_document(data, title, caption=False),
                title,
                str(data.get("notas") or ""),
                formation_label(data.get("base"), data.get("set")),
            ))
        if not seen_open and self._play_on_screen():
            cards.append((
                self.render_board(scale=2, caption=False),
                self.name_var.get().strip() or "Jogada",
                self.notes_text(),
                self.formation_caption(),
            ))
        pages = compose_sheets(cards)
        if not pages:
            raise RuntimeError("Nenhuma jogada entrou na folha.")
        path.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(path, "PDF", resolution=SHEET_DPI, save_all=True, append_images=pages[1:])
        return len(cards), len(pages)

    def render_document(self, data: dict, fallback: str, caption: bool = True):
        shapes = [shape_from_raw(raw) for raw in data.get("shapes", [])]
        routes = [route_from_raw(raw) for raw in data.get("routes", [])]
        title = str(data.get("nome") or fallback or "Jogada")
        notes = str(data.get("notas") or "") if caption else ""
        return self.render_board(
            scale=2,
            with_notes=caption,
            shapes=shapes,
            routes=routes,
            title=title,
            notes=notes,
            caption=caption,
        )

    def render_board(
        self,
        scale: int = 2,
        elapsed: float | None = None,
        with_notes: bool = True,
        shapes: list | None = None,
        routes: list | None = None,
        title: str | None = None,
        notes: str | None = None,
        caption: bool = True,
    ):
        from PIL import Image, ImageDraw, ImageFont

        def font(size: int, bold: bool = False):
            filename = "segoeuib.ttf" if bold else "segoeui.ttf"
            try:
                return ImageFont.truetype(filename, size)
            except OSError:
                return ImageFont.load_default()

        margin = 28
        if shapes is None:
            shapes = self.shapes
        if routes is None:
            routes = self.routes
        if title is None:
            title = self.name_var.get().strip() or "Jogada"
        if not caption:
            notes = ""
        elif notes is None:
            notes = self.notes_text() if with_notes else ""
        elif not with_notes:
            notes = ""
        formation = self.formation_caption() if caption and shapes is self.shapes else ""
        if not caption:
            header = 0
        elif formation and notes:
            header = 86
        elif formation or notes:
            header = 64
        else:
            header = 46
        width = int(FIELD_W * scale + margin * 2)
        height = int(FIELD_H * scale + margin * 2 + header)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        if caption:
            draw.text((margin, 10), title, fill="#111111", font=font(22, True))
            note_y = 36
            if formation:
                draw.text((margin, 36), formation, fill="#1c1917", font=font(16, True))
                note_y = 58
            if notes:
                draw.text((margin, note_y), notes.replace("\n", " ")[:170], fill="#44403c", font=font(14))

        def px(x: float, y: float) -> tuple[float, float]:
            return margin + x * scale, header + margin + (y - FIELD_TOP) * scale

        x0, y0 = px(0, FIELD_TOP)
        x1, y1 = px(FIELD_W, FIELD_BOTTOM)
        draw.rectangle((x0, y0, x1, y1), fill="white", outline="#111111", width=3)
        number_font = font(18, True)
        for relative in range(FRONT_YARDS, -BACK_YARDS - 1, -1):
            y = LOS_Y - relative * YARD
            left, sy = px(0, y)
            right, _sy = px(FIELD_W, y)
            if relative == 0:
                draw.line((left, sy, right, sy), fill="#111111", width=4)
            elif relative % 5 == 0:
                draw.line((left, sy, right, sy), fill="#111111", width=3 if relative % 10 == 0 else 2)
            else:
                for hx in (HASH_X, FIELD_W - HASH_X):
                    hx0, hy0 = px(hx, y - 4)
                    _hx, hy1 = px(hx, y + 4)
                    draw.line((hx0, hy0, hx0, hy1), fill="#111111", width=2)
            if relative in (10, 20, 30, 40):
                label_y = y + 14 if relative == FRONT_YARDS else y
                draw.text(px(36, label_y), str(relative), fill="#111111", font=number_font, anchor="mm")
                draw.text(px(FIELD_W - 36, label_y), str(relative), fill="#111111", font=number_font, anchor="mm")
        ball = px(FIELD_W / 2, LOS_Y)
        draw.ellipse((ball[0] - 10, ball[1] - 6, ball[0] + 10, ball[1] + 6), fill="#111111")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for shape in shapes:
            if shape.kind != "zone":
                continue
            rgb = ZONE_TONES.get(shape.tone, ZONE_TONES["amarelo"])[0]
            ax, ay = px(shape.x, shape.y)
            bx, by = px(shape.x + shape.w, shape.y + shape.h)
            overlay_draw.ellipse((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)), fill=(*rgb, ZONE_ALPHA))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(image)

        def paint_route(screen: list[tuple[float, float]], kind: str, ending: str, ink: str | None, dashed: bool | None = None) -> None:
            screen = straighten_axis(screen)
            if len(screen) < 2:
                return
            color = route_ink("bloqueio" if kind in BLOCK_KINDS else kind, ink)
            end = screen[-1]
            prev = screen[-2]
            vector = direction(prev, end)
            line = list(screen)
            if vector and ending == "arrow":
                dist = math.hypot(end[0] - prev[0], end[1] - prev[1])
                cut = min(18, dist * 0.4)
                line[-1] = (end[0] - vector[0] * cut, end[1] - vector[1] * cut)
            elif vector and ending == "ring":
                dist = math.hypot(end[0] - prev[0], end[1] - prev[1])
                cut = min(6, dist * 0.3)
                line[-1] = (end[0] - vector[0] * cut, end[1] - vector[1] * cut)
            if kind == "motion":
                line = wavy_line(line, amplitude=7)
            if kind == "playaction" and dashed is not False:
                self._draw_dashed(draw, line, color, 5)
            else:
                draw.line(line, fill=color, width=5, joint="curve")
            if not vector or ending == "open":
                return
            if ending == "bar":
                pxv, pyv = -vector[1], vector[0]
                length = 16
                draw.line(
                    (end[0] - pxv * length, end[1] - pyv * length, end[0] + pxv * length, end[1] + pyv * length),
                    fill=color,
                    width=5,
                )
                return
            if ending == "ring":
                radius = 5
                draw.ellipse(
                    (end[0] - radius, end[1] - radius, end[0] + radius, end[1] + radius),
                    outline=color,
                    width=4,
                )
                return
            ux, uy = vector
            nx, ny = -uy, ux
            size = 16
            left = (end[0] - ux * size + nx * size * 0.55, end[1] - uy * size + ny * size * 0.55)
            right = (end[0] - ux * size - nx * size * 0.55, end[1] - uy * size - ny * size * 0.55)
            draw.polygon([end, left, right], fill=color)

        under = self.defense_back.get()
        if under:
            ghost = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ghost_draw = ImageDraw.Draw(ghost)
            for shape in shapes:
                if shape.side != "defesa" or shape.kind == "zone":
                    continue
                ax, ay = px(shape.x, shape.y)
                bx, by = px(shape.x + shape.w, shape.y + shape.h)
                label_font = font(max(11, int(min(shape.w, shape.h) * scale * 0.42)), True)
                tx0, ty0, tx1, ty1, tx2, ty2 = defense_triangle(ax, ay, bx, by)
                ghost_draw.polygon(
                    [(tx0, ty0), (tx1, ty1), (tx2, ty2)],
                    fill=(212, 212, 212, DEFENSE_ALPHA),
                    outline=(17, 17, 17, 200),
                )
                if shape.text:
                    ghost_draw.text(
                        ((ax + bx) / 2, (ay * 2 + by) / 3),
                        shape.text,
                        fill=(17, 17, 17, 220),
                        font=label_font,
                        anchor="mm",
                    )
            image = Image.alpha_composite(image.convert("RGBA"), ghost).convert("RGB")
            draw = ImageDraw.Draw(image)

        for route in routes:
            screen = [px(point[0], point[1]) for point in route_path(route, routes)]
            if route.kind == "release" and isinstance(route.split, int) and 0 < route.split < len(screen) - 1:
                paint_route(screen[: route.split + 1], "bloqueio", "open", route.color)
                paint_route(screen[route.split :], "passe", route_ending("passe", route.ending), route.color)
            elif route.kind in ("paroute", "pablock") and isinstance(route.split, int) and 0 < route.split < len(screen) - 1:
                paint_route(screen[: route.split + 1], "playaction", "open", None)
                final = "bloqueio" if route.kind == "pablock" else "passe"
                paint_route(screen[route.split :], "playaction", route_ending(final, route.ending), None, dashed=False)
            elif route.kind == "papass":
                paint_route(screen, "playaction", "open", None)
            else:
                paint_route(screen, route.kind, route_ending(route.kind, route.ending), route.color)
        for shape in shapes:
            if shape.kind == "zone" or (under and shape.side == "defesa"):
                continue
            ax, ay = px(shape.x, shape.y)
            bx, by = px(shape.x + shape.w, shape.y + shape.h)
            label_font = font(max(11, int(min(shape.w, shape.h) * scale * 0.42)), True)
            if shape.kind == "x":
                tx0, ty0, tx1, ty1, tx2, ty2 = defense_triangle(ax, ay, bx, by)
                draw.polygon([(tx0, ty0), (tx1, ty1), (tx2, ty2)], fill=DEFENSE_FILL, outline="#111111")
                if shape.text:
                    draw.text(((ax + bx) / 2, (ay * 2 + by) / 3), shape.text, fill="#111111", font=label_font, anchor="mm")
            elif shape.kind == "circle":
                draw.ellipse((ax, ay, bx, by), fill="#111111", outline="#111111", width=3)
                if shape.text:
                    draw.text(((ax + bx) / 2, (ay + by) / 2), shape.text, fill="white", font=label_font, anchor="mm")
            elif shape.kind == "triangle":
                draw.polygon([(ax + (bx - ax) / 2, ay), (bx, by), (ax, by)], fill="#111111", outline="#111111")
                if shape.text:
                    draw.text(((ax + bx) / 2, ay * 0.42 + by * 0.58), shape.text, fill="white", font=label_font, anchor="mm")
            else:
                draw.rectangle((ax, ay, bx, by), fill="#111111", outline="#111111", width=3)
                if shape.text:
                    draw.text(((ax + bx) / 2, (ay + by) / 2), shape.text, fill="white", font=label_font, anchor="mm")
        if elapsed is not None:
            traveled = elapsed * PLAY_YARDS_PER_SEC * YARD
            snap = snap_distance(routes)
            continued = {item.follow for item in routes if item.follow}
            dot = max(6, int(7 * scale))
            for route in routes:
                found = dot_position(route, traveled, snap, continued, self.routes)
                if found is None:
                    continue
                x, y = found
                if any(self._hides_dot(shape, x, y) for shape in shapes):
                    continue
                sx, sy = px(x, y)
                draw.ellipse((sx - dot, sy - dot, sx + dot, sy + dot), fill=moving_ink(route), outline="#111111", width=2)
            clock = font(max(16, 14 * scale), True)
            small = font(max(13, 11 * scale), True)
            draw.text(px(FIELD_W - 28, FIELD_TOP + 36), f"{elapsed:.1f} s", fill="#111111", font=clock, anchor="rm")
            draw.text(
                px(FIELD_W - 28, FIELD_TOP + 58),
                f"jogada {jogada_seconds(elapsed, routes):.1f} s",
                fill="#111111",
                font=small,
                anchor="rm",
            )
            draw.text(
                px(FIELD_W - 28, FIELD_TOP + 78),
                alvo_label(elapsed, routes),
                fill="#111111",
                font=small,
                anchor="rm",
            )
        return image

    def _draw_dashed(self, draw, points, color: str, width: int) -> None:
        dash, gap = 14, 8
        for start, end in zip(points, points[1:]):
            sx, sy = start
            ex, ey = end
            seg = math.hypot(ex - sx, ey - sy)
            if seg < 1:
                continue
            ux, uy = (ex - sx) / seg, (ey - sy) / seg
            dist = 0.0
            drawing = True
            while dist < seg:
                step = dash if drawing else gap
                nxt = min(seg, dist + step)
                if drawing:
                    draw.line((sx + ux * dist, sy + uy * dist, sx + ux * nxt, sy + uy * nxt), fill=color, width=width)
                dist = nxt
                drawing = not drawing

    def notes_text(self) -> str:
        return self.notes.get("1.0", "end-1c").strip()

    def on_notes_edit(self, _event=None) -> None:
        if self._suspend or not self._ready:
            return
        self.sync_dirty()

    def on_name_write(self, *_args) -> None:
        if self._suspend or not self._ready:
            return
        self.sync_dirty()

    def on_name_focus_in(self, _event=None) -> None:
        self._name_before = self.snapshot()

    def on_name_focus_out(self, _event=None) -> None:
        before = self._name_before
        self._name_before = None
        if before is None or self._suspend or not self.winfo_exists():
            return
        if self.snapshot() != before:
            self.commit_undo(before)
        else:
            self.sync_dirty()

    def on_notes_focus_in(self, _event=None) -> None:
        self._notes_before = self.snapshot()

    def on_notes_focus_out(self, _event=None) -> None:
        before = self._notes_before
        self._notes_before = None
        if before is None or self._suspend or not self.winfo_exists():
            return
        if self.snapshot() != before:
            self.commit_undo(before)
        else:
            self.sync_dirty()

    def _categories_from(self, raw) -> list[str]:
        allowed = {name.casefold(): name for name in self.category_names}
        chosen: list[str] = []
        for name in normalize_categories(raw):
            kept = allowed.get(name.casefold())
            if kept and kept not in chosen:
                chosen.append(kept)
        return [name for name in self.category_names if name in chosen]

    def _paint_categories(self) -> None:
        host = getattr(self, "category_chips", None)
        if host is None:
            return
        for child in host.winfo_children():
            child.destroy()
        chosen = set(self.play_categories)
        for name in self.category_names:
            on = name in chosen
            button = tk.Button(
                host,
                text=name,
                command=lambda item=name: self.toggle_category(item),
                bg="#15803d" if on else "white",
                fg="white" if on else "#1c1917",
                activebackground="#166534" if on else "#f5f5f4",
                activeforeground="white" if on else "#1c1917",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#15803d" if on else "#d6d3d1",
                padx=6,
                pady=1,
                font=("Segoe UI", 9),
                cursor="hand2",
            )
        self._cat_width = None
        self._flow_categories()

    def _flow_categories(self, _event=None) -> None:
        host = self.category_chips
        width = host.winfo_width()
        measured = width >= 40
        if not measured:
            width = 900
        if measured and width == getattr(self, "_cat_width", None):
            return
        if measured:
            self._cat_width = width
        x = 0
        row = 0
        col = 0
        for child in host.winfo_children():
            need = child.winfo_reqwidth() + 4
            if col and x + need > width:
                row += 1
                col = 0
                x = 0
            child.grid(row=row, column=col, sticky="w", padx=(0, 4), pady=1)
            col += 1
            x += need

    def toggle_category(self, name: str) -> None:
        before = self.snapshot()
        if name in self.play_categories:
            self.play_categories = [item for item in self.play_categories if item != name]
        else:
            if name in ("corrida", "passe"):
                self.play_categories = [item for item in self.play_categories if item not in ("corrida", "passe")]
            self.play_categories.append(name)
        self._paint_categories()
        self.commit_undo(before)
        nome = self.name_var.get().strip() or "jogada"
        self.set_status(play_caption(nome, self.play_categories))

    def snapshot(self):
        notes = self.notes_text() if hasattr(self, "notes") else ""
        return copy.deepcopy(
            {
                "shapes": self.shapes,
                "routes": self.routes,
                "base": self.offense_base,
                "set": self.offense_set,
                "name": self.name_var.get(),
                "notes": notes,
                "categories": list(self.play_categories),
            }
        )

    def mark_clean(self) -> None:
        self._clean = self.snapshot()
        self.dirty = False

    def sync_dirty(self) -> None:
        if self._clean is None:
            self.dirty = True
            return
        self.dirty = self.snapshot() != self._clean

    def commit_undo(self, before) -> None:
        self.undo_stack.append(before)
        if len(self.undo_stack) > 100:
            del self.undo_stack[0]
        self.redo_stack.clear()
        self.sync_dirty()

    def restore(self, state) -> None:
        self.shapes = state["shapes"]
        self.routes = state["routes"]
        if "base" in state:
            self.offense_base = state["base"]
        if "set" in state:
            self.offense_set = state["set"]
            self.show_offense_formation()
        self.draft = []
        self.drag = None
        self._text_before = None
        self._suspend = True
        if "name" in state:
            self.name_var.set(state["name"])
        if "notes" in state and hasattr(self, "notes"):
            self.notes.delete("1.0", "end")
            self.notes.insert("1.0", state["notes"])
        if "categories" in state:
            self.play_categories = list(state["categories"])
            self._paint_categories()
        self._suspend = False
        if self.selection:
            kind, item_id = self.selection
            pool = self.shapes if kind == "shape" else self.routes
            if not any(item.id == item_id for item in pool):
                self.selection = None
        self.reload_label()
        self.redraw()

    def editing_text(self) -> bool:
        return isinstance(self.focus_get(), (tk.Entry, tk.Text))

    def undo(self) -> None:
        if self.editing_text():
            return
        if not self.undo_stack:
            self.set_status("Nada para desfazer.")
            return
        self.redo_stack.append(self.snapshot())
        self.restore(self.undo_stack.pop())
        self.sync_dirty()
        self.set_status("Desfeito.")

    def redo(self) -> None:
        if self.editing_text():
            return
        if not self.redo_stack:
            self.set_status("Nada para refazer.")
            return
        self.undo_stack.append(self.snapshot())
        self.restore(self.redo_stack.pop())
        self.sync_dirty()
        self.set_status("Refeito.")

    def play_document(self) -> dict:
        return {
            "versao": 1,
            "id": self.play_id,
            "nome": self.name_var.get().strip(),
            "lado": "ataque",
            "notas": self.notes_text(),
            "categorias": [name for name in self.category_names if name in self.play_categories],
            "shapes": [asdict(shape) for shape in self.shapes],
            "routes": [asdict(route) for route in self.routes],
            "base": self.offense_base,
            "set": self.offense_set,
        }

    def save_play(self) -> bool:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Nome da jogada", "Dê um nome para a jogada antes de salvar.", parent=self)
            return False
        owner = play_id_for_name(name)
        if owner is not None and owner != self.loaded_id:
            if not messagebox.askyesno("Substituir jogada", f'Já existe "{name}". Substituir?', parent=self):
                return False
        document = self.play_document()
        if self.loaded_id is None:
            document["id"] = owner
        else:
            document["id"] = self.loaded_id
            if owner is not None and owner != self.loaded_id:
                remove_play(owner)
        try:
            self.play_id = store_play(document)
        except sqlite3.Error as exc:
            messagebox.showerror("Salvar jogada", f"Não foi possível salvar.\n{exc}", parent=self)
            return False
        self.loaded_id = self.play_id
        self.mark_clean()
        self.remember_open()
        self.refresh_list()
        self.set_status(f"Jogada salva: {name}")
        return True

    def remember_open(self) -> None:
        if self.loaded_id is None:
            return
        remember_play(self.loaded_id)

    def restore_last(self) -> None:
        play_id = remembered_play()
        if play_id is not None:
            self.load_saved(play_id)

    def refresh_list(self) -> None:
        self.plays.delete(*self.plays.get_children())
        for data in stored_plays():
            play_id = int(data["id"])
            nome = str(data.get("nome") or "")
            self.plays.insert(
                "",
                "end",
                iid=str(play_id),
                values=(str(play_id), nome, category_text(data.get("categorias"))),
            )
        if self.loaded_id is not None and self.plays.exists(str(self.loaded_id)):
            self.plays.selection_set(str(self.loaded_id))
            self.plays.see(str(self.loaded_id))

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Jogada sem salvar",
            "Salvar a jogada atual antes de continuar?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save_play()
        return True

    def new_play(self) -> None:
        if not self.confirm_discard():
            return
        self.shapes = []
        self.routes = []
        self.draft = []
        self.selection = None
        self.loaded_id = None
        self.play_id = None
        self.offense_base = None
        self.offense_set = None
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._suspend = True
        self.name_var.set("")
        self.label_var.set("")
        self.play_categories = []
        self.notes.delete("1.0", "end")
        self._suspend = False
        self._paint_categories()
        selected = self.plays.selection()
        if selected:
            self.plays.selection_remove(selected)
        self.redraw()
        self.mark_clean()
        self.set_status("Nova jogada. Dê um nome e monte o desenho.")

    def open_selected(self) -> None:
        selected = self.plays.selection()
        if not selected:
            self.set_status("Escolha uma jogada na lista.")
            return
        if not self.confirm_discard():
            return
        self.load_saved(int(selected[0]))

    def load_saved(self, play_id: int) -> None:
        data = stored_play(play_id)
        if data is None:
            messagebox.showerror("Abrir jogada", "Não foi possível ler essa jogada.", parent=self)
            return
        self.shapes = []
        for raw in data.get("shapes", []):
            try:
                self.shapes.append(shape_from_raw(raw))
            except (KeyError, TypeError, ValueError):
                continue
        self.routes = []
        for raw in data.get("routes", []):
            try:
                self.routes.append(route_from_raw(raw))
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        self.draft = []
        self.selection = None
        base = data.get("base")
        self.offense_base = str(base) if base in DROP_TRAVEL else None
        style = data.get("set")
        self.offense_set = str(style) if style else None
        self.show_offense_formation()
        self.loaded_id = play_id
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._suspend = True
        self.name_var.set(str(data.get("nome", "")))
        self.label_var.set("")
        self.play_id = play_number(data)
        self.play_categories = self._categories_from(data.get("categorias"))
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", str(data.get("notas", "")))
        self._suspend = False
        self._paint_categories()
        self.refresh_list()
        self.remember_open()
        self.redraw()
        self.mark_clean()
        self.set_status(f"Jogada aberta: {self.name_var.get()}")

    def delete_saved_play(self) -> None:
        selected = self.plays.selection()
        if not selected:
            self.set_status("Escolha uma jogada na lista.")
            return
        play_id = int(selected[0])
        values = self.plays.item(selected[0], "values")
        nome = values[1] if len(values) > 1 else selected[0]
        if not messagebox.askyesno("Excluir jogada", f'Excluir "{nome}"?', parent=self):
            return
        try:
            remove_play(play_id)
        except sqlite3.Error:
            messagebox.showerror("Excluir jogada", "Não foi possível apagar a jogada.", parent=self)
            return
        if play_id == self.loaded_id:
            self.loaded_id = None
            self.dirty = True
        self.refresh_list()
        self.set_status(f"Jogada excluída: {nome}")

    def on_arrow(self, event):
        if self.typing() or self.tool != "select":
            return None
        route = self.selected_route()
        if route is not None:
            if event.keysym in ("Left", "Right") and len(route.points) >= 2:
                if self._nudge_before is None:
                    self._nudge_before = self.snapshot()
                toward = -1 if event.keysym == "Left" else 1
                route.lean = step_lean(route.lean, toward)
                self.dirty = True
                self.redraw()
                self._note_lean(route)
            return "break"
        shape = self.selected_shape()
        if shape is None:
            return "break"
        if self._nudge_before is None:
            self._nudge_before = self.snapshot()
        step = YARD if event.state & 0x0001 else 4
        dx = {"Left": -step, "Right": step}.get(event.keysym, 0)
        dy = {"Up": -step, "Down": step}.get(event.keysym, 0)
        self._shift_with_player(shape, dx, dy)
        self.dirty = True
        self.redraw()
        return "break"

    def on_arrow_release(self, _event):
        if self._nudge_before is None:
            return None
        before = self._nudge_before
        self._nudge_before = None
        if self.snapshot() != before:
            self.commit_undo(before)
        return "break"

    def on_delete_key(self, _event):
        if self.typing():
            return None
        self.delete_selected()
        return "break"

    def on_backspace(self, _event):
        if self.typing():
            return None
        if self.draft:
            if self.tool == "blockpath" and len(self.draft) == 1:
                self.set_status("A linha continua no jogador. Escape cancela.")
                return "break"
            self.draft.pop()
            self.redraw()
            self.set_status("Último ponto removido." if self.draft else "Rota vazia.")
            return "break"
        self.delete_selected()
        return "break"

    def on_escape(self, _event):
        if self.playing:
            self.stop_play()
            return "break"
        if isinstance(self.focus_get(), tk.Entry):
            self.canvas.focus_set()
            return "break"
        if self.draft:
            self.cancel_draft()
            return "break"
        if self.drag and self._before is not None:
            self.restore(self._before)
            self._before = None
            self.drag = None
            return "break"
        self.select(None)
        self.set_status(HINTS[self.tool])
        return "break"

    def on_return(self, _event):
        if self.typing():
            return None
        if self.draft:
            self.finish_route()
            return "break"
        return None

    def on_save_key(self, _event):
        if isinstance(self.focus_get(), tk.Text):
            return None
        self.save_play()
        return "break"

    def on_undo_key(self, event):
        if self.editing_text():
            return None
        self.undo()
        return "break"

    def on_redo_key(self, _event):
        if self.editing_text():
            return None
        self.redo()
        return "break"

    def on_new_key(self, _event):
        if self.editing_text():
            return None
        self.new_play()
        return "break"

    def on_close(self) -> None:
        self.stop_play(quiet=True)
        if self.dirty and self.name_var.get().strip():
            if not self.save_play():
                return
        elif not self.confirm_discard():
            return
        self.remember_open()
        self.destroy()


def main() -> None:
    enable_dpi()
    QuadroTatico().mainloop()


if __name__ == "__main__":
    main()
