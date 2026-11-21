"""Campo, formações, rotas e o banco das jogadas.

A janela fica em main.py. Aqui não se abre interface.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class PastaDados:
    """Pasta do quadro. Trocar data aponta o banco para outro diretório."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "dados"

    @property
    def database(self) -> Path:
        return self.data / "quadro.db"

    @property
    def last(self) -> Path:
        return self.data / ".ultima"


PASTA = PastaDados(app_dir())
DEFAULT_CATEGORIES = ["1st", "2nd", "3rd", "4th", "short", "long"]


def clean_category(name: str) -> str:
    return " ".join(name.split())[:24]


def normalize_categories(raw) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return names
    for item in raw:
        if not isinstance(item, str):
            continue
        name = clean_category(item)
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _ordered_categories(raw, catalog: list[str]) -> list[str]:
    allowed = {name.casefold(): name for name in catalog}
    chosen: list[str] = []
    for name in normalize_categories(raw):
        kept = allowed.get(name.casefold())
        if kept and kept not in chosen:
            chosen.append(kept)
    return [name for name in catalog if name in chosen]


def category_text(categorias) -> str:
    return ", ".join(_ordered_categories(categorias, category_catalog()))


def play_caption(nome: str, categorias) -> str:
    chosen = _ordered_categories(categorias, category_catalog())
    if not chosen:
        return nome
    return f"{nome} ({', '.join(chosen)})"


def read_play(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def play_number(data: dict) -> int | None:
    raw = data.get("id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None
_store_ready = False


def _connect() -> sqlite3.Connection:
    global _conn, _conn_path, _store_ready
    path = PASTA.database
    if _conn is not None and _conn_path == path:
        return _conn
    if _conn is not None:
        _conn.close()
    _store_ready = False
    PASTA.data.mkdir(exist_ok=True)
    _conn = sqlite3.connect(path)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn_path = path
    return _conn


def _setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO setting (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _create_store(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            position INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS play (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            side TEXT NOT NULL DEFAULT 'ataque',
            notes TEXT NOT NULL DEFAULT '',
            base TEXT,
            shapes TEXT NOT NULL DEFAULT '[]',
            routes TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS play_category (
            play_id INTEGER NOT NULL REFERENCES play(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
            PRIMARY KEY (play_id, category_id)
        );
        CREATE TABLE IF NOT EXISTS setting (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS formation_base (
            id INTEGER PRIMARY KEY,
            side TEXT NOT NULL,
            name TEXT NOT NULL,
            key TEXT NOT NULL,
            position INTEGER NOT NULL,
            UNIQUE (side, key)
        );
        CREATE TABLE IF NOT EXISTS formation_set (
            id INTEGER PRIMARY KEY,
            base_id INTEGER NOT NULL REFERENCES formation_base(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            key TEXT NOT NULL,
            position INTEGER NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            UNIQUE (base_id, key)
        );
        """
    )


def _seed_categories(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS n FROM category").fetchone()["n"]
    if count:
        return
    names = list(DEFAULT_CATEGORIES)
    path = PASTA.data / ".categorias.json"
    try:
        parsed = normalize_categories(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        parsed = []
    if parsed:
        names = parsed
    conn.executemany(
        "INSERT INTO category (name, position) VALUES (?, ?)",
        [(name, index) for index, name in enumerate(names)],
    )


def _json_list(raw: str) -> list:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _play_dict(row: sqlite3.Row, categorias: list[str]) -> dict:
    base = row["base"]
    return {
        "versao": 1,
        "id": int(row["id"]),
        "nome": str(row["name"]),
        "lado": str(row["side"]),
        "notas": str(row["notes"]),
        "categorias": list(categorias),
        "shapes": _json_list(str(row["shapes"])),
        "routes": _json_list(str(row["routes"])),
        "base": str(base) if base else None,
    }


def _catalog(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM category ORDER BY position, id").fetchall()
    return [str(row["name"]) for row in rows]


def _categories_of(conn: sqlite3.Connection, play_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT category.name AS name
        FROM play_category
        JOIN category ON category.id = play_category.category_id
        WHERE play_category.play_id = ?
        ORDER BY category.position, category.id
        """,
        (play_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _write_play(conn: sqlite3.Connection, data: dict) -> int:
    name = str(data.get("nome") or "").strip()
    if not name:
        raise ValueError("A jogada precisa de um nome.")
    notes = str(data.get("notas") or "")
    side = str(data.get("lado") or "ataque") or "ataque"
    raw_base = data.get("base")
    base = str(raw_base) if raw_base else None
    shapes = json.dumps(data.get("shapes") or [], ensure_ascii=False)
    routes = json.dumps(data.get("routes") or [], ensure_ascii=False)
    play_id = play_number(data)
    chosen = _ordered_categories(data.get("categorias"), _catalog(conn))
    exists = play_id is not None and conn.execute("SELECT 1 FROM play WHERE id = ?", (play_id,)).fetchone()
    if exists:
        conn.execute(
            """
            UPDATE play
            SET name = ?, side = ?, notes = ?, base = ?, shapes = ?, routes = ?
            WHERE id = ?
            """,
            (name, side, notes, base, shapes, routes, play_id),
        )
    elif play_id is not None:
        conn.execute(
            """
            INSERT INTO play (id, name, side, notes, base, shapes, routes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (play_id, name, side, notes, base, shapes, routes),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO play (name, side, notes, base, shapes, routes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, side, notes, base, shapes, routes),
        )
        play_id = int(cursor.lastrowid)
    conn.execute("DELETE FROM play_category WHERE play_id = ?", (play_id,))
    conn.executemany(
        """
        INSERT INTO play_category (play_id, category_id)
        SELECT ?, id FROM category WHERE name = ? COLLATE NOCASE
        """,
        [(play_id, item) for item in chosen],
    )
    return int(play_id)


def _import_json(conn: sqlite3.Connection) -> None:
    """Copia cada JSON cujo nome ainda não está no banco. O arquivo pode sair depois."""
    for path in sorted(PASTA.data.glob("*.json"), key=lambda item: item.name.casefold()):
        if path.name.startswith("."):
            continue
        data = read_play(path)
        if data is None:
            continue
        if not str(data.get("nome") or "").strip():
            data["nome"] = path.stem
        if conn.execute(
            "SELECT 1 FROM play WHERE name = ? COLLATE NOCASE",
            (str(data["nome"]).strip(),),
        ).fetchone():
            continue
        try:
            conn.execute("SAVEPOINT play_import")
            _write_play(conn, data)
            conn.execute("RELEASE play_import")
        except (sqlite3.Error, ValueError):
            conn.execute("ROLLBACK TO play_import")
            conn.execute("RELEASE play_import")
    if _setting(conn, "last_play") is not None:
        return
    try:
        last_name = Path(PASTA.last.read_text(encoding="utf-8").strip()).stem
    except OSError:
        return
    if not last_name:
        return
    row = conn.execute("SELECT id FROM play WHERE name = ? COLLATE NOCASE", (last_name,)).fetchone()
    if row is not None:
        _put_setting(conn, "last_play", str(row["id"]))


def open_store() -> None:
    """Abre o banco, cria as tabelas e copia jogadas JSON que ainda não existem."""
    global _store_ready
    conn = _connect()
    if _store_ready:
        return
    with conn:
        _create_store(conn)
        _seed_categories(conn)
        _seed_formations(conn)
        _import_json(conn)
    _store_ready = True


def category_catalog() -> list[str]:
    open_store()
    return _catalog(_connect())


def stored_plays() -> list[dict]:
    open_store()
    conn = _connect()
    rows = conn.execute("SELECT * FROM play ORDER BY id").fetchall()
    grouped: dict[int, list[str]] = {}
    links = conn.execute(
        """
        SELECT play_category.play_id AS play_id, category.name AS name
        FROM play_category
        JOIN category ON category.id = play_category.category_id
        ORDER BY category.position, category.id
        """
    ).fetchall()
    for link in links:
        grouped.setdefault(int(link["play_id"]), []).append(str(link["name"]))
    return [_play_dict(row, grouped.get(int(row["id"]), [])) for row in rows]


def stored_play(play_id: int) -> dict | None:
    open_store()
    conn = _connect()
    row = conn.execute("SELECT * FROM play WHERE id = ?", (play_id,)).fetchone()
    if row is None:
        return None
    return _play_dict(row, _categories_of(conn, play_id))


def store_play(data: dict) -> int:
    open_store()
    conn = _connect()
    with conn:
        return _write_play(conn, data)


def remove_play(play_id: int) -> None:
    open_store()
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM play WHERE id = ?", (play_id,))
        if _setting(conn, "last_play") == str(play_id):
            conn.execute("DELETE FROM setting WHERE key = 'last_play'")


def play_id_for_name(name: str) -> int | None:
    open_store()
    row = _connect().execute(
        "SELECT id FROM play WHERE name = ? COLLATE NOCASE",
        (name.strip(),),
    ).fetchone()
    return None if row is None else int(row["id"])


def remember_play(play_id: int) -> None:
    open_store()
    conn = _connect()
    with conn:
        _put_setting(conn, "last_play", str(play_id))


def remembered_play() -> int | None:
    open_store()
    conn = _connect()
    raw = _setting(conn, "last_play")
    if raw is None or not raw.isdigit():
        return None
    play_id = int(raw)
    found = conn.execute("SELECT 1 FROM play WHERE id = ?", (play_id,)).fetchone()
    return play_id if found else None


def clear_stored_plays() -> None:
    open_store()
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM play")
        conn.execute("DELETE FROM setting WHERE key = 'last_play'")


def close_store() -> None:
    global _conn, _conn_path, _store_ready
    if _conn is not None:
        _conn.close()
    _conn = None
    _conn_path = None
    _store_ready = False


YARD = 15
FIELD_W = 800
# A linha fica onde as jogadas já salvas estão. O gramado só mostra 20 à frente e 10 atrás.
LOS_Y = YARD * 30
FRONT_YARDS = 20
BACK_YARDS = 10
FIELD_TOP = LOS_Y - FRONT_YARDS * YARD
FIELD_BOTTOM = LOS_Y + BACK_YARDS * YARD
FIELD_H = FIELD_BOTTOM - FIELD_TOP
# Folha A4 deitada, 150 dpi: 297 mm por 210 mm. Quatro jogadas, duas colunas e duas linhas.
SHEET_COLUMNS = 2
SHEET_ROWS = 2
SHEET_DPI = 150
SHEET_W = 1754
SHEET_H = 1240
SHEET_MARGIN_X = 28
SHEET_MARGIN_TOP = 24
SHEET_MARGIN_BOTTOM = 32
SHEET_GAP = 14
MIN_SIZE = 14
OL_SIZE = 22
SKILL_SIZE = 22
DEF_SIZE = 18
OL_GAP = 28

SHAPE_TOOLS = ("circle", "square", "triangle", "rectangle", "x")
ROUTE_TOOLS = ("passe", "bloqueio", "playaction", "motion")


def route_kind_for(name: str) -> str:
    """Tipo gravado na rota pronta. Sit continua sit. O restante de passe fica passe."""
    special = {
        "motion": "motion",
        "playaction": "playaction",
        "paroute": "paroute",
        "pablock": "pablock",
        "blockrun": "blockrun",
        "blockpass": "blockpass",
        "release": "release",
        "dropback": "dropback",
        "rbrun": "rbrun",
        "sit": "sit",
    }
    return special.get(name, "passe")

SHAPE_LABEL = {
    "select": "Selecionar",
    "circle": "Círculo",
    "square": "Quadrado",
    "triangle": "Triângulo",
    "rectangle": "Retângulo",
    "x": "Defesa",
    "passe": "Rota de passe",
    "bloqueio": "Bloqueio",
    "playaction": "Play action",
    "motion": "Motion",
}

ROUTE_COLOR = {
    "passe": "#ea580c",
    "bloqueio": "#ca8a04",
    "blockrun": "#ca8a04",
    "blockpass": "#ca8a04",
    "playaction": "#7c3aed",
    "paroute": "#7c3aed",
    "pablock": "#7c3aed",
    "motion": "#1e3a8a",
    "dropback": "#38bdf8",
    "rbrun": "#ea580c",
}
ROUTE_INK = {"laranja": "#ea580c", "verde": "#15803d"}
ZONE_ALPHA = 88
ZONE_TONES = {
    "amarelo": ((234, 179, 8), "Amarelo", "#eab308", "#1c1917"),
    "azul": ((30, 58, 138), "Azul escuro", "#1e3a8a", "white"),
    "celeste": ((56, 189, 248), "Azul claro", "#38bdf8", "#0f172a"),
    "roxo": ((88, 28, 135), "Roxo escuro", "#581c87", "white"),
}
HASH_X = (70 + 9 / 12) / 160 * FIELD_W
# Ritmo da bolinha, em jardas por segundo. O relógio usa a rota como unidade.
# Rota: recebedor em equipamento, já com o corte no traço. 10 jardas levam cerca de 1,4 s.
PLAY_YARDS_PER_SEC = 7
# Motion: trote antes do snap, rápido o bastante para cruzar e lento o bastante para frear.
MOTION_YARDS_PER_SEC = 5.5
# Bloqueio de corrida: primeiro passo do drive, ou um pull curto.
RUN_BLOCK_YARDS_PER_SEC = 4.2
# Bloqueio de passe: kick-slide. O dropback é o recuo do quarterback, um pouco mais rápido que o kick.
PASS_BLOCK_YARDS_PER_SEC = 3.2
DROP_YARDS_PER_SEC = 4.0
BLOCK_REACH = 1.5
RELEASE_HOLD = 1.0
# O RB espera esse tempo no lugar, para chegar no bloqueio, e só então a bolinha sai.
RUN_HOLD = 0.6

BLOCK_KINDS = {"bloqueio", "blockrun", "blockpass"}
# Jarda que o quarterback recua, a partir de onde está. A ponta nunca passa de 5 jardas atrás da linha.
DROP_TRAVEL = {
    "shotgun": 0.5,
    "pistol": 1.6,
    "singleback": 3.2,
    "i": 1.6,
    "t": 1.6,
    "split": 3.0,
    "wishbone": 1.6,
    "flexbone": 1.6,
    "goalline": 1.5,
}
DROP_TITLE = {
    "shotgun": "shotgun",
    "pistol": "pistol",
    "singleback": "singleback",
    "i": "I-formation",
    "t": "T",
    "split": "splitback",
    "wishbone": "wishbone",
    "flexbone": "flexbone",
    "goalline": "goal line",
}

MIRROR_TEXT = {
    "LT": "RT",
    "RT": "LT",
    "LG": "RG",
    "RG": "LG",
    "X": "Z",
    "Z": "X",
    "W": "S",
    "S": "W",
}

HINTS = {
    "select": "Arraste a peça ou a rota. A rota que sai do jogador vai junto. As setas movem o jogador clicado. Com a rota selecionada, elas inclinam o traço em 45°. Puxe os cantos para redimensionar. Duplo clique escreve dentro. Delete remove.",
    "circle": "Clique no campo para colocar um círculo. O texto fica dentro da peça.",
    "square": "Clique no campo para colocar um quadrado. O texto fica dentro da peça.",
    "triangle": "Clique no campo para colocar um triângulo. O texto fica dentro da peça.",
    "rectangle": "Clique no campo para colocar um retângulo. O texto fica dentro da peça.",
    "x": "Clique no campo para colocar um defensor. A letra fica no triângulo de ponta para baixo.",
    "passe": "Clique os pontos da rota. Se um motion estiver selecionado, ela começa no fim dele. Enter conclui.",
    "bloqueio": "Clique os pontos do bloqueio. A ponta ganha uma trave. Enter, botão direito ou Concluir fecha.",
    "playaction": "Tracejado livre do play action. Para o fake com saída, use PA route ou PA block no jogador.",
    "motion": "Desenhe o motion, antes do snap. Depois selecione o jogador e escolha a rota: ela começa no fim.",
    "blockpath": "Clique o jogador: a linha nasce nele. Cada clique esquerdo continua o traço. Botão direito conclui.",
    "zone:amarelo": "Clique no campo para marcar uma área amarela. Ela fica atrás de tudo, translúcida.",
    "zone:azul": "Clique no campo para marcar uma área azul escura. Ela fica atrás de tudo, translúcida.",
    "zone:celeste": "Clique no campo para marcar uma área azul clara. Ela fica atrás de tudo, translúcida.",
    "zone:roxo": "Clique no campo para marcar uma área roxa. Ela fica atrás de tudo, translúcida.",
}


def enable_dpi() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def new_id() -> str:
    return uuid4().hex[:8]


def point_in_poly(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            denom = (yj - yi) or 1e-9
            if px < (xj - xi) * (py - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def dist_to_segment(px: float, py: float, a: list[float], b: list[float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def direction(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return None
    return dx / length, dy / length


def straighten_axis(points: list, tolerance: float = 1.25) -> list:
    """Um traço quase reto fica de fato reto. O desvio de um pixel vira degrau na linha fina."""
    if len(points) < 2:
        return [tuple(point) for point in points]
    output = [tuple(points[0])]
    for raw in points[1:]:
        previous = output[-1]
        nxt = (raw[0], raw[1])
        dx = nxt[0] - previous[0]
        dy = nxt[1] - previous[1]
        if abs(dy) <= tolerance and abs(dx) > tolerance:
            nxt = (nxt[0], previous[1])
        elif abs(dx) <= tolerance and abs(dy) > tolerance:
            nxt = (previous[0], nxt[1])
        output.append(nxt)
    return output


def lean_angle(points: list, lean: int) -> float:
    """Giro da rota, em radianos. A direita leva o primeiro passo para o lado direito do campo."""
    if lean not in (-1, 1) or len(points) < 2:
        return 0.0
    dx = points[1][0] - points[0][0]
    dy = points[1][1] - points[0][1]
    toward_right = -1.0 if dy > abs(dx) else 1.0
    return math.radians(45) * lean * toward_right


def rotate_points(points: list, angle: float) -> list:
    if abs(angle) < 1e-9 or len(points) < 2:
        return [list(point) for point in points]
    sx, sy = float(points[0][0]), float(points[0][1])
    cosine, sine = math.cos(angle), math.sin(angle)
    output = [[sx, sy]]
    for point in points[1:]:
        vx, vy = float(point[0]) - sx, float(point[1]) - sy
        output.append([sx + vx * cosine - vy * sine, sy + vx * sine + vy * cosine])
    return output


def unwind_point(origin: list, angle: float, x: float, y: float) -> list[float]:
    """O ponto visto na tela volta para o desenho sem inclinação."""
    if abs(angle) < 1e-9:
        return [x, y]
    cosine, sine = math.cos(-angle), math.sin(-angle)
    vx, vy = x - origin[0], y - origin[1]
    return [origin[0] + vx * cosine - vy * sine, origin[1] + vx * sine + vy * cosine]


def follow_shift(route, routes) -> tuple[float, float]:
    follow = getattr(route, "follow", None)
    if not follow or not routes:
        return 0.0, 0.0
    motion = next((item for item in routes if item.id == follow and len(item.points) >= 2), None)
    if motion is None:
        return 0.0, 0.0
    visual = route_path(motion)
    return visual[-1][0] - motion.points[-1][0], visual[-1][1] - motion.points[-1][1]


def route_path(route, routes=None) -> list:
    points = route.points
    lean = getattr(route, "lean", 0) or 0
    if lean in (-1, 1) and len(points) >= 2:
        points = rotate_points(points, lean_angle(points, lean))
    dx, dy = follow_shift(route, routes)
    if dx or dy:
        points = [[point[0] + dx, point[1] + dy] for point in points]
    return points


def step_lean(current: int, toward: int) -> int:
    """Um passo: esquerda, meio, direita. Para na extremidade."""
    if current not in (-1, 0, 1):
        current = 0
    if toward not in (-1, 1):
        return current
    return max(-1, min(1, current + toward))


def route_length(points: list) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += math.hypot(end[0] - start[0], end[1] - start[1])
    return total


def yards_per_sec(kind: str) -> float:
    if kind == "motion":
        return MOTION_YARDS_PER_SEC
    if kind in ("blockrun", "rbrun"):
        return RUN_BLOCK_YARDS_PER_SEC
    if kind in ("bloqueio", "blockpass"):
        return PASS_BLOCK_YARDS_PER_SEC
    if kind == "dropback":
        return DROP_YARDS_PER_SEC
    return PLAY_YARDS_PER_SEC


def clock_for(field_px: float, speed: float) -> float:
    """Converte jardas percorridas no relógio da jogada, que conta na velocidade da rota."""
    return field_px * PLAY_YARDS_PER_SEC / speed


def snap_distance(routes: list) -> float:
    """Distância no relógio até o motion acabar."""
    lengths = [
        clock_for(route_length(route_path(route)), MOTION_YARDS_PER_SEC)
        for route in routes
        if route.kind == "motion" and len(route.points) >= 2
    ]
    return max(lengths) if lengths else 0.0


def _split_at(route, kinds: set[str]) -> int | None:
    split = getattr(route, "split", None)
    if getattr(route, "kind", None) not in kinds or not isinstance(split, int):
        return None
    points = route.points
    if not (0 < split < len(points) - 1):
        return None
    return split


def release_block(route) -> float:
    split = _split_at(route, {"release"})
    if split is None:
        return 0.0
    return route_length(route_path(route)[: split + 1])


def release_hold(route) -> float:
    if release_block(route) <= 0:
        return 0.0
    return RELEASE_HOLD * PLAY_YARDS_PER_SEC * YARD


def run_hold(route) -> float:
    """Pausa no começo do RB run e do RB path, em distância de relógio."""
    if getattr(route, "kind", None) != "rbrun":
        return 0.0
    return RUN_HOLD * PLAY_YARDS_PER_SEC * YARD


def clock_length(route) -> float:
    """Quanto o traço ocupa no relógio, cada trecho na velocidade da sua ação."""
    points = route_path(route)
    length = route_length(points)
    block = release_block(route)
    if block:
        return clock_for(block, PASS_BLOCK_YARDS_PER_SEC) + release_hold(route) + clock_for(length - block, PLAY_YARDS_PER_SEC)
    split = _split_at(route, {"paroute", "pablock"})
    if split is not None:
        fake = route_length(points[: split + 1])
        rest_speed = PLAY_YARDS_PER_SEC if route.kind == "paroute" else PASS_BLOCK_YARDS_PER_SEC
        return clock_for(fake, RUN_BLOCK_YARDS_PER_SEC) + clock_for(length - fake, rest_speed)
    hold = run_hold(route)
    if hold:
        return hold + clock_for(length, yards_per_sec(route.kind))
    return clock_for(length, yards_per_sec(route.kind))


def play_distance(routes: list) -> float:
    snap = snap_distance(routes)
    longest = 0.0
    for route in routes:
        if route.kind == "motion" or len(route.points) < 2:
            continue
        longest = max(longest, clock_length(route))
    return snap + longest


def jogada_seconds(elapsed: float, routes: list) -> float:
    snap = snap_distance(routes) / (PLAY_YARDS_PER_SEC * YARD)
    return max(0.0, elapsed - snap)


def principal_seconds(routes: list) -> float | None:
    """Tempo da jogada em que a rota laranja acaba. Verde, dropback e bloqueio ficam de fora."""
    times = [
        clock_length(route) / (PLAY_YARDS_PER_SEC * YARD)
        for route in routes
        if len(route.points) >= 2 and route_ink(route.kind, getattr(route, "color", None)) == ROUTE_INK["laranja"]
    ]
    if not times:
        return None
    return min(times)


def alvo_seconds(elapsed: float, routes: list) -> float | None:
    cap = principal_seconds(routes)
    if cap is None:
        return None
    return min(jogada_seconds(elapsed, routes), cap)


def alvo_label(elapsed: float, routes: list) -> str:
    value = alvo_seconds(elapsed, routes)
    if value is None:
        return "laranja —"
    return f"laranja {value:.1f} s"


def dot_position(route, traveled: float, snap: float, continued: set[str], routes=None) -> tuple[float, float] | None:
    points = route_path(route, routes)
    if len(points) < 2:
        return None
    if route.kind == "motion":
        length = route_length(points)
        clock = clock_for(length, MOTION_YARDS_PER_SEC)
        if traveled < clock:
            return point_along(points, traveled * MOTION_YARDS_PER_SEC / PLAY_YARDS_PER_SEC)
        if route.id in continued and traveled >= snap:
            return None
        return point_along(points, length)
    if route.follow and traveled < snap:
        return None
    if traveled < snap:
        return point_along(points, 0)
    along = traveled - snap
    block = release_block(route)
    if block:
        block_clock = clock_for(block, PASS_BLOCK_YARDS_PER_SEC)
        hold = release_hold(route)
        if along <= block_clock:
            return point_along(points, along * PASS_BLOCK_YARDS_PER_SEC / PLAY_YARDS_PER_SEC)
        if along <= block_clock + hold:
            return point_along(points, block)
        covered = block + (along - block_clock - hold)
        return point_along(points, covered)
    split = _split_at(route, {"paroute", "pablock"})
    if split is not None:
        fake = route_length(points[: split + 1])
        fake_clock = clock_for(fake, RUN_BLOCK_YARDS_PER_SEC)
        if along <= fake_clock:
            return point_along(points, along * RUN_BLOCK_YARDS_PER_SEC / PLAY_YARDS_PER_SEC)
        rest_speed = PLAY_YARDS_PER_SEC if route.kind == "paroute" else PASS_BLOCK_YARDS_PER_SEC
        return point_along(points, fake + (along - fake_clock) * rest_speed / PLAY_YARDS_PER_SEC)
    hold = run_hold(route)
    if hold and along < hold:
        return point_along(points, 0)
    if hold:
        along -= hold
    return point_along(points, along * yards_per_sec(route.kind) / PLAY_YARDS_PER_SEC)


def point_along(points: list, distance: float) -> tuple[float, float]:
    if not points:
        return (0.0, 0.0)
    if len(points) == 1 or distance <= 0:
        return (float(points[0][0]), float(points[0][1]))
    remaining = distance
    for start, end in zip(points, points[1:]):
        seg = math.hypot(end[0] - start[0], end[1] - start[1])
        if seg < 1e-6:
            continue
        if remaining <= seg:
            t = remaining / seg
            return (
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
            )
        remaining -= seg
    return (float(points[-1][0]), float(points[-1][1]))


def route_ink(kind: str, color: str | None) -> str:
    if kind in ("passe", "release") or kind not in ROUTE_COLOR:
        return ROUTE_INK.get(color or "laranja", ROUTE_INK["laranja"])
    return ROUTE_COLOR[kind]


def moving_ink(route) -> str:
    if route.kind in ("playaction", "paroute", "pablock"):
        return route_ink("playaction", None)
    if route.kind in BLOCK_KINDS:
        return route_ink("bloqueio", None)
    if route.kind in ("passe", "release", "sit"):
        return route_ink("passe", route.color)
    return route_ink(route.kind, route.color)


def filename_for(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in name)
    cleaned = " ".join(cleaned.split())
    return (cleaned[:80] or "jogada") + ".json"


def _set(name: str, key: str, detail: str) -> tuple[str, str, str]:
    return (name, key, detail)


_ONE_BACK = (
    _set("Spread", "spread", "3 recebedores, 1 tight end e 1 running back. Na linha: X e Y."),
    _set("Trips", "trips", "trips à direita, tight end do lado oposto. Na linha: Z e Y."),
    _set("Bunch", "bunch", "bunch à direita: Z no meio, na linha; A e F atrás. Tight end do lado oposto."),
    _set("Ace", "ace", "2 recebedores, 2 tight ends e 1 running back. Na linha: os dois tight ends."),
    _set("Doubles", "doubles", "4 recebedores, dois de cada lado, e o running back na proteção. Na linha: X e Z."),
    _set("Trey", "trey", "4 recebedores em trips e o running back na proteção. Na linha: X e Z."),
    _set("Wide Bunch", "widebunch", "4 recebedores, bunch à direita, e o running back na proteção. Z no meio, na linha."),
)
_TWO_BACK = (
    _set("Pro", "pro", "2 recebedores, 1 tight end, fullback e halfback. Na linha: X e Y."),
    _set("Twins", "twins", "dois recebedores do mesmo lado e 1 tight end. Na linha: X e Y."),
    _set("Tight", "tight", "1 recebedor e 2 tight ends, fullback e halfback. Na linha: os dois tight ends."),
)
_FORMATION_SEED = (
    {
        "side": "offense",
        "name": "I-Formation",
        "key": "i",
        "sets": _TWO_BACK
        + (_set("Offset", "ioff", "I com o fullback no lado do tight end e o halfback atrás."),),
    },
    {
        "side": "offense",
        "name": "T-Formation",
        "key": "t",
        "sets": (
            _set("Tight", "tight", "T fechado: dois tight ends na linha e os três backs lado a lado."),
            _set("Pro", "pro", "T com o X aberto e o Y na linha. Os três backs continuam lado a lado."),
        ),
    },
    {
        "side": "offense",
        "name": "Splitback",
        "key": "split",
        "sets": _TWO_BACK
        + (_set("Near", "near", "split: fullback mais perto da linha, no lado forte; halfback mais fundo."),),
    },
    {
        "side": "offense",
        "name": "Pistol",
        "key": "pistol",
        "sets": _ONE_BACK
        + (
            _set("Strong", "strong", "pistol: fullback à direita, ao lado do quarterback, e o halfback atrás."),
            _set("Jumbo", "pjumbo", "pistol: 1 recebedor (X), 3 tight ends e 1 running back. Na linha: X e Y. U e A recuados."),
        ),
    },
    {
        "side": "offense",
        "name": "Goal Line",
        "key": "goalline",
        "sets": (
            _set("Power", "power", "1 recebedor, 2 tight ends, fullback e halfback. Na linha: os dois tight ends."),
            _set("Jumbo", "jumbo", "1 recebedor, 3 tight ends e 1 running back. Na linha: U e Y. A é o tight end recuado."),
            _set("Deuce", "gldeuce", "goal line com os dois backs lado a lado. 1 recebedor e 2 tight ends."),
        ),
    },
    {
        "side": "offense",
        "name": "Wishbone",
        "key": "wishbone",
        "sets": (
            _set("Tight", "tight", "Wishbone fechado: dois tight ends, fullback atrás do quarterback e os halfbacks mais fundos."),
            _set("Pro", "pro", "Wishbone com o X aberto e o Y na linha. O fullback fica na frente dos dois halfbacks."),
        ),
    },
    {
        "side": "offense",
        "name": "Flexbone",
        "key": "flexbone",
        "sets": (
            _set("Pro", "pro", "Flexbone: X aberto, Y na linha, dois wings fora da linha e o fullback atrás do quarterback."),
            _set("Tight", "tight", "Flexbone fechado: dois tight ends, wings por fora e o fullback atrás do quarterback."),
        ),
    },
    {
        "side": "offense",
        "name": "Shotgun",
        "key": "shotgun",
        "sets": _ONE_BACK
        + (
            _set("Deuce", "deuce", "shotgun: fullback e halfback, um de cada lado do quarterback."),
            _set("Offset", "gunoff", "shotgun: halfback ao lado do quarterback, fullback no lado forte."),
        ),
    },
    {
        "side": "offense",
        "name": "Singleback",
        "key": "singleback",
        "sets": _ONE_BACK
        + (_set("Offset", "dot", "singleback com o running back deslocado para o lado do tight end."),),
    },
    {
        "side": "defense",
        "name": "4-3",
        "key": "43",
        "sets": (
            _set("Base", "base", "contra o Ace, dois recebedores"),
            _set("Nickel", "nickel", "contra o Spread, três recebedores"),
            _set("Trips", "trips", "nickel e safety em cima do trips"),
            _set("Bunch", "bunch", "secundário fechado em cima do bunch"),
            _set("Dime", "dime", "contra 4 recebedores, seis no secundário"),
        ),
    },
    {
        "side": "defense",
        "name": "3-4",
        "key": "34",
        "sets": (
            _set("Base", "base", "contra o Ace, dois recebedores"),
            _set("Nickel", "nickel", "contra o Spread, três recebedores"),
            _set("Trips", "trips", "nickel e safety em cima do trips"),
            _set("Bunch", "bunch", "secundário fechado em cima do bunch"),
            _set("Dime", "dime", "contra 4 recebedores, seis no secundário"),
        ),
    },
    {
        "side": "defense",
        "name": "Goal line",
        "key": "goalline",
        "sets": (
            _set("Heavy", "heavy", "contra 1 recebedor, box carregado"),
            _set("Ace", "ace", "contra 2 recebedores, dois corners"),
        ),
    },
)


def _seed_formations(conn: sqlite3.Connection) -> None:
    """Grava base e set que ainda não existem. Linha já salva permanece."""
    for index, base in enumerate(_FORMATION_SEED):
        row = conn.execute(
            "SELECT id FROM formation_base WHERE side = ? AND key = ?",
            (base["side"], base["key"]),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO formation_base (side, name, key, position) VALUES (?, ?, ?, ?)",
                (base["side"], base["name"], base["key"], index),
            )
            base_id = int(cursor.lastrowid)
        else:
            base_id = int(row["id"])
        for set_index, (name, key, detail) in enumerate(base["sets"]):
            found = conn.execute(
                "SELECT 1 FROM formation_set WHERE base_id = ? AND key = ?",
                (base_id, key),
            ).fetchone()
            if found:
                continue
            conn.execute(
                """
                INSERT INTO formation_set (base_id, name, key, position, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (base_id, name, key, set_index, detail),
            )


def formation_menu(side: str) -> tuple[list[tuple[str, str]], dict[str, tuple[tuple[str, str], ...]]]:
    """Nomes que a janela mostra. A ordem e o texto vêm do banco."""
    open_store()
    conn = _connect()
    bases = conn.execute(
        "SELECT id, name, key FROM formation_base WHERE side = ? ORDER BY position, id",
        (side,),
    ).fetchall()
    menu: list[tuple[str, str]] = []
    sets: dict[str, tuple[tuple[str, str], ...]] = {}
    for base in bases:
        menu.append((str(base["name"]), str(base["key"])))
        rows = conn.execute(
            "SELECT name, key FROM formation_set WHERE base_id = ? ORDER BY position, id",
            (base["id"],),
        ).fetchall()
        sets[str(base["key"])] = tuple((str(row["name"]), str(row["key"])) for row in rows)
    return menu, sets


def formation_detail(side: str, base_key: str, set_key: str) -> str:
    open_store()
    row = _connect().execute(
        """
        SELECT formation_set.detail AS detail
        FROM formation_set
        JOIN formation_base ON formation_base.id = formation_set.base_id
        WHERE formation_base.side = ? AND formation_base.key = ? AND formation_set.key = ?
        """,
        (side, base_key, set_key),
    ).fetchone()
    return "" if row is None else str(row["detail"])


def formation_title(side: str, base_key: str, set_key: str) -> str:
    bases, sets = formation_menu(side)
    base_label = dict((key, label) for label, key in bases)[base_key]
    set_label = dict((key, label) for label, key in sets[base_key])[set_key]
    return f"{base_label} · {set_label}"


def _menu_from_seed(side: str) -> tuple[tuple[tuple[str, str], ...], dict[str, tuple[tuple[str, str], ...]]]:
    bases = []
    sets: dict[str, tuple[tuple[str, str], ...]] = {}
    for item in _FORMATION_SEED:
        if item["side"] != side:
            continue
        bases.append((item["name"], item["key"]))
        sets[item["key"]] = tuple((name, key) for name, key, _detail in item["sets"])
    return tuple(bases), sets


OFFENSE_BASES, OFFENSE_SETS = _menu_from_seed("offense")
DEFENSE_BASES, DEFENSE_SETS = _menu_from_seed("defense")


def offense_anchors() -> tuple[float, list[float], float, dict[str, float]]:
    line_y = LOS_Y + 8
    ol_x = [FIELD_W / 2 + (index - 2) * OL_GAP for index in range(5)]
    te_x = ol_x[-1] + (OL_SIZE + SKILL_SIZE) / 2 + 5
    receivers = {"X": 150.0, "F": 225.0, "Z": FIELD_W - 150.0}
    return line_y, ol_x, te_x, receivers


def wing_x(ol_x: list[float]) -> tuple[float, float]:
    wing = (OL_SIZE + SKILL_SIZE) / 2 + 5
    return ol_x[0] - wing, ol_x[-1] + wing


def trips_x(_ol_x: list[float]) -> tuple[float, float, float]:
    outside = FIELD_W - 150.0
    step = 32.0
    return outside - 2 * step, outside - step, outside


def bunch_x(ol_x: list[float]) -> tuple[float, float, float]:
    inside = ol_x[-1] + 2 * YARD
    wing = 30.0
    return inside, inside + wing, inside + 2 * wing


def offense_players(base: str, style: str) -> list[tuple[str, str, float, float, float]]:
    """On the line of scrimmage: the five offensive linemen plus two eligibles."""
    line_y, ol_x, _te_x, receivers = offense_anchors()
    left_te, right_te = wing_x(ol_x)
    center_x = FIELD_W / 2
    wide_l = receivers["X"]
    wide_r = receivers["Z"]
    slot_l = receivers["F"]
    on = line_y
    off = line_y + YARD
    trips_inner, trips_slot, trips_point = trips_x(ol_x)
    bunch_in, bunch_mid, bunch_out = bunch_x(ol_x)
    players: list[tuple[str, str, float, float, float]] = [
        ("square", label, cx, line_y, OL_SIZE) for label, cx in zip(("LT", "LG", "C", "RG", "RT"), ol_x)
    ]

    def add(label: str, cx: float, cy: float) -> None:
        players.append(("circle", label, cx, cy, SKILL_SIZE))

    if base in ("t", "wishbone", "flexbone"):
        lt, lg, _center, rg, rt = ol_x
        quarterback_y = LOS_Y + 28
        if base == "flexbone":
            if style == "tight":
                add("U", left_te, on)
                add("Y", right_te, on)
                add("A", left_te - 2 * YARD, off)
                add("H", right_te + 2 * YARD, off)
            else:
                add("X", wide_l, on)
                add("Y", right_te, on)
                add("A", left_te, off)
                add("H", right_te + 2 * YARD, off)
            add("QB", center_x, quarterback_y)
            add("FB", center_x, LOS_Y + 4.6 * YARD)
            return players
        if style == "pro":
            add("X", wide_l, on)
            add("Y", right_te, on)
        else:
            add("U", left_te, on)
            add("Y", right_te, on)
        add("QB", center_x, quarterback_y)
        if base == "wishbone":
            add("FB", center_x, LOS_Y + 4 * YARD)
            add("A", lt, LOS_Y + 6.5 * YARD)
            add("H", rt, LOS_Y + 6.5 * YARD)
        else:
            depth = LOS_Y + 4 * YARD
            add("A", lg, depth)
            add("FB", center_x, depth)
            add("H", rg, depth)
        return players

    backs = "h"
    if style == "spread":
        add("X", wide_l, on)
        add("F", slot_l, off)
        add("Z", wide_r, off)
        add("Y", right_te, on)
    elif style == "trips":
        add("Y", left_te, on)
        add("A", trips_inner, off)
        add("F", trips_slot, off)
        add("Z", trips_point, on)
    elif style == "bunch":
        add("Y", left_te, on)
        add("A", bunch_in, off)
        add("Z", bunch_mid, on)
        add("F", bunch_out, off)
    elif style == "ace":
        add("X", wide_l, off)
        add("U", left_te, on)
        add("Y", right_te, on)
        add("Z", wide_r, off)
    elif style == "doubles":
        add("X", wide_l, on)
        add("F", slot_l, off)
        add("A", FIELD_W - slot_l, off)
        add("Z", wide_r, on)
    elif style == "trey":
        add("X", wide_l, on)
        add("A", trips_inner, off)
        add("F", trips_slot, off)
        add("Z", trips_point, on)
    elif style == "widebunch":
        add("X", wide_l, on)
        add("A", bunch_in, off)
        add("Z", bunch_mid, on)
        add("F", bunch_out, off)
    elif style == "gldeuce":
        add("X", left_te - 8 * YARD, off)
        add("U", left_te, on)
        add("Y", right_te, on)
        backs = "pair"
    elif style in ("strong", "weak", "deuce", "gunoff", "ioff", "near"):
        add("X", wide_l, on)
        add("Y", right_te, on)
        add("Z", wide_r, off)
        backs = "pair"
    elif style == "dot":
        add("X", wide_l, on)
        add("F", slot_l, off)
        add("Z", wide_r, off)
        add("Y", right_te, on)
        backs = "dot"
    elif style == "pro":
        add("X", wide_l, on)
        add("Y", right_te, on)
        add("Z", wide_r, off)
        backs = "fb"
    elif style == "twins":
        add("X", wide_l, on)
        add("F", slot_l, off)
        add("Y", right_te, on)
        backs = "fb"
    elif style == "tight":
        add("X", wide_l, off)
        add("U", left_te, on)
        add("Y", right_te, on)
        backs = "fb"
    elif style == "pjumbo":
        add("X", wide_l, on)
        add("U", left_te, off)
        add("Y", right_te, on)
        add("A", right_te + 2 * YARD, off)
        backs = "h"
    elif style == "power":
        add("X", left_te - 8 * YARD, off)
        add("U", left_te, on)
        add("Y", right_te, on)
        backs = "fb"
    else:
        add("X", left_te - 6 * YARD, off)
        add("U", left_te, on)
        add("Y", right_te, on)
        add("A", right_te + 2 * YARD, off)
        backs = "h"

    _lt, lg, _center, rg, rt = ol_x
    gun_y = LOS_Y + YARD * 5
    if base == "shotgun" and style == "deuce":
        add("QB", center_x, gun_y)
        add("H", center_x - 48, gun_y)
        add("FB", center_x + 48, gun_y)
    elif base == "shotgun" and style == "gunoff":
        add("QB", center_x, gun_y)
        add("H", center_x - 40, gun_y)
        add("FB", (rg + rt) / 2, LOS_Y + 6.2 * YARD)
    elif base == "shotgun":
        add("QB", center_x, gun_y)
        if backs == "h":
            add("H", center_x + 30, gun_y)
    elif base == "pistol" and style == "strong":
        qb_y = LOS_Y + YARD * 4
        add("QB", center_x, qb_y)
        add("H", center_x, LOS_Y + YARD * 7)
        add("FB", center_x + SKILL_SIZE + 4, qb_y)
    elif base == "pistol":
        add("QB", center_x, LOS_Y + YARD * 4)
        if backs == "h":
            add("H", center_x, LOS_Y + YARD * 7)
    elif base == "split" and style == "near":
        add("QB", center_x, LOS_Y + 28)
        add("FB", rg, LOS_Y + 4 * YARD)
        add("H", lg, LOS_Y + 6.5 * YARD)
    elif base == "split":
        depth = LOS_Y + 5 * YARD
        add("QB", center_x, LOS_Y + 28)
        add("H", lg, depth)
        add("FB", rg, depth)
    elif style == "ioff":
        add("QB", center_x, LOS_Y + 28)
        add("FB", rg, LOS_Y + 4.6 * YARD)
        add("H", center_x, LOS_Y + 7.4 * YARD)
    elif style == "gldeuce":
        depth = LOS_Y + 5 * YARD
        add("QB", center_x, LOS_Y + 28)
        add("H", lg, depth)
        add("FB", rg, depth)
    elif backs == "fb":
        add("QB", center_x, LOS_Y + 28)
        add("FB", center_x, LOS_Y + 4.6 * YARD)
        add("H", center_x, LOS_Y + 7.4 * YARD)
    elif style == "dot":
        add("QB", center_x, LOS_Y + 28)
        add("H", rg, LOS_Y + YARD * 6.2)
    else:
        add("QB", center_x, LOS_Y + 28)
        if backs == "h":
            add("H", center_x, LOS_Y + YARD * 6.2)
    return players


def defense_spots(base: str, style: str) -> list[tuple[str, float, float]]:
    _line_y, ol_x, te_x, receivers = offense_anchors()
    lt, lg, center, rg, rt = ol_x
    left_te, right_te = wing_x(ol_x)
    wide_l = receivers["X"]
    wide_r = receivers["Z"]
    slot = receivers["F"]
    trips_inner, trips_slot, trips_point = trips_x(ol_x)
    bunch_in, bunch_mid, bunch_out = bunch_x(ol_x)
    dl_y = LOS_Y - 18
    lb_y = LOS_Y - 4 * YARD
    cb_y = LOS_Y - 4 * YARD
    walk_y = LOS_Y - 5 * YARD
    ss_x = center + 136
    fs_x = center - 136
    ss_y = LOS_Y - 8 * YARD
    fs_y = LOS_Y - 10 * YARD
    deep = [("SS", ss_x, ss_y), ("FS", fs_x, fs_y)]
    apex = LOS_Y - 3 * YARD

    def four(left_end: float, right_end: float) -> list[tuple[str, float, float]]:
        return [
            ("E", left_end, dl_y),
            ("T", (lt + lg) / 2, dl_y),
            ("T", (rg + rt) / 2, dl_y),
            ("E", right_end, dl_y),
        ]

    def three(left_end: float, right_end: float) -> list[tuple[str, float, float]]:
        return [("E", left_end, dl_y), ("N", center, dl_y), ("E", right_end, dl_y)]

    slot_r = FIELD_W - slot
    spread_four = four(lt - 26, te_x + 18)
    ace_four = four(left_te - 26, right_te + 26)
    trips_four = four(left_te - 26, rt + 26)
    open_four = four(lt - 26, rt + 26)
    spread_three = three(lt - 20, te_x + 16)
    ace_three = three(left_te - 28, te_x + 16)
    trips_three = three(left_te - 28, rt + 26)
    open_three = three(lt - 26, rt + 26)

    if base == "goalline":
        box_y = LOS_Y - 3.4 * YARD
        safety_y = LOS_Y - 5.8 * YARD
        front = [
            ("E", left_te, dl_y),
            ("T", lt, dl_y),
            ("N", center, dl_y),
            ("T", rt, dl_y),
            ("E", right_te, dl_y),
        ]
        safeties = [("FS", center - 80, safety_y), ("SS", center + 80, safety_y)]
        if style == "ace":
            return front + [
                ("W", lg, box_y),
                ("S", rg, box_y),
                ("C", wide_l, cb_y),
                ("C", wide_r, cb_y),
                *safeties,
            ]
        return front + [
            ("W", lg, box_y),
            ("M", center, box_y),
            ("S", rg, box_y),
            ("C", left_te - 8 * YARD, LOS_Y - 2.5 * YARD),
            *safeties,
        ]

    if base == "34":
        if style == "base":
            return ace_three + [
                ("W", left_te - 40, apex),
                ("M", lg, lb_y),
                ("M", rg, lb_y),
                ("S", te_x + 28, apex),
                ("C", wide_l, cb_y),
                ("C", wide_r, cb_y),
                *deep,
            ]
        if style == "nickel":
            return spread_three + [
                ("M", lg, lb_y),
                ("M", rg, lb_y),
                ("S", te_x + 28, apex),
                ("C", wide_l, cb_y),
                ("C", wide_r, cb_y),
                ("N", slot, cb_y),
                *deep,
            ]
        if style == "dime":
            return open_three + [
                ("M", lg, lb_y),
                ("M", rg, lb_y),
                ("C", wide_l, cb_y),
                ("N", slot, cb_y),
                ("N", slot_r, cb_y),
                ("C", wide_r, cb_y),
                *deep,
            ]
        inner, slot_x, point = (bunch_in, bunch_out, bunch_mid) if style == "bunch" else (trips_inner, trips_slot, trips_point)
        return trips_three + [
            ("M", lg, lb_y),
            ("M", rg, lb_y),
            ("S", left_te, apex),
            ("C", point, cb_y),
            ("N", slot_x, cb_y),
            ("SS", inner, walk_y),
            ("C", wide_l, cb_y),
            ("FS", center - 40, fs_y),
        ]

    if style == "base":
        return ace_four + [
            ("W", left_te, lb_y),
            ("M", center, lb_y),
            ("S", right_te, lb_y),
            ("C", wide_l, cb_y),
            ("C", wide_r, cb_y),
            *deep,
        ]
    if style == "nickel":
        return spread_four + [
            ("M", center, lb_y),
            ("W", lt - 8, lb_y),
            ("C", wide_l, cb_y),
            ("C", wide_r, cb_y),
            ("N", slot, cb_y),
            *deep,
        ]
    if style == "dime":
        return open_four + [
            ("M", center, lb_y),
            ("C", wide_l, cb_y),
            ("N", slot, cb_y),
            ("N", slot_r, cb_y),
            ("C", wide_r, cb_y),
            *deep,
        ]
    inner, slot_x, point = (bunch_in, bunch_out, bunch_mid) if style == "bunch" else (trips_inner, trips_slot, trips_point)
    return trips_four + [
        ("W", left_te, lb_y),
        ("M", center, lb_y),
        ("C", point, cb_y),
        ("N", slot_x, cb_y),
        ("SS", inner, walk_y),
        ("C", wide_l, cb_y),
        ("FS", center - 40, fs_y),
    ]


def balloon_points(cx: float, cy: float, depth: float, across: float, inside: int) -> list[list[float]]:
    end_x = min(FIELD_W - 10, max(10, cx + across * inside * YARD))
    crest = cy - depth * YARD
    anchors = ((cx, cy), (cx, crest), (cx + (end_x - cx) * 0.45, crest), (end_x, crest))
    points: list[list[float]] = []
    steps = 12
    for step in range(steps + 1):
        t = step / steps
        u = 1 - t
        weights = (u**3, 3 * u**2 * t, 3 * u * t**2, t**3)
        x = sum(weight * anchor[0] for weight, anchor in zip(weights, anchors))
        y = sum(weight * anchor[1] for weight, anchor in zip(weights, anchors))
        points.append([x, y])
    return points


def bow_points(start: list[float], control: list[float], end: list[float], steps: int = 12) -> list[list[float]]:
    """Curva contínua. O ponto do meio puxa o arco e não vira quina."""
    points: list[list[float]] = []
    for step in range(steps + 1):
        t = step / steps
        weight = 1 - t
        points.append([
            weight * weight * start[0] + 2 * weight * t * control[0] + t * t * end[0],
            weight * weight * start[1] + 2 * weight * t * control[1] + t * t * end[1],
        ])
    return points


def route_preset(name: str, cx: float, cy: float, strong: int = 1, screen_yards: float = 3.2) -> list[list[float]]:
    inside = 1 if cx <= FIELD_W / 2 else -1
    outside = -inside

    def at(dx: float, up: float) -> list[float]:
        return [cx + dx * inside * YARD, cy - up * YARD]

    if name == "slant":
        points = [at(0, 0), at(0, 2), at(6, 8)]
    elif name == "out":
        points = [at(0, 0), at(0, 6), [cx + 5 * outside * YARD, cy - 6 * YARD]]
    elif name == "dig":
        points = [at(0, 0), at(0, 10), at(6, 10)]
    elif name == "post":
        points = [at(0, 0), at(0, 10), at(3.5, 14)]
    elif name == "corner":
        points = [at(0, 0), at(0, 10), [cx + 3.5 * outside * YARD, cy - 14 * YARD]]
    elif name == "go":
        points = [at(0, 0), at(0, 15)]
    elif name == "flat":
        points = balloon_points(cx, cy, 2, 6, outside)
    elif name == "wheel":
        points = wheel_points(cx, cy)
    elif name == "drag":
        points = balloon_points(cx, cy, 3, 12, inside)
    elif name == "screen":
        back = 0.55 if screen_yards <= 4 else 0.95
        points = [
            at(0, 0),
            [cx + min(1.4, screen_yards * 0.35) * inside * YARD, cy + 0.35 * YARD],
            [cx + screen_yards * inside * YARD, cy + back * YARD],
        ]
    elif name == "crossing":
        points = balloon_points(cx, cy, 8, 12, inside)
    elif name == "blockrun":
        points = [at(0, 0), at(0, BLOCK_REACH)]
    elif name == "blockpass":
        points = [at(0, 0), at(0, -BLOCK_REACH)]
    elif name == "release":
        points = [at(0, 0), at(0, 1.5), [cx + 5 * outside * YARD, cy - 3 * YARD]]
    elif name == "curl":
        points = [at(0, 0), at(0, 12), at(1.0, 10.8)]
    elif name == "hitch":
        points = [at(0, 0), at(0, 6), at(0.7, 5.1)]
    elif name == "comeback":
        points = [at(0, 0), at(0, 12), [cx + 1.6 * outside * YARD, cy - 10.7 * YARD]]
    elif name == "stick":
        points = [at(0, 0), at(0, 6), [cx + 1.6 * outside * YARD, cy - 4.7 * YARD]]
    elif name == "in":
        points = [at(0, 0), at(0, 6), at(6, 6)]
    elif name == "dog":
        points = [at(0, 0), at(0, 10), [cx + 5 * outside * YARD, cy - 10 * YARD]]
    elif name == "seam":
        points = [at(0, 0), at(0.7, 6), at(2.2, 15)]
    elif name == "fade":
        points = [
            at(0, 0),
            [cx + 0.7 * outside * YARD, cy - 6 * YARD],
            [cx + 2.2 * outside * YARD, cy - 15 * YARD],
        ]
    elif name == "swing":
        start = [cx, cy]
        stem = [cx + 6 * outside * YARD, cy]
        end = [cx + 8.0 * outside * YARD, cy - 0.9 * YARD]
        anchors = (
            stem,
            [stem[0] + 0.9 * outside * YARD, cy],
            [end[0] - 0.75 * outside * YARD, end[1] + 0.38 * YARD],
            end,
        )
        curve: list[list[float]] = []
        steps = 7
        for step in range(steps + 1):
            t = step / steps
            u = 1 - t
            weights = (u**3, 3 * u * u * t, 3 * u * t * t, t**3)
            curve.append([
                sum(weight * anchor[0] for weight, anchor in zip(weights, anchors)),
                sum(weight * anchor[1] for weight, anchor in zip(weights, anchors)),
            ])
        points = [start, *curve]
    elif name == "texas":
        points = [
            at(0, 0),
            [cx + 4 * outside * YARD, cy - 4 * YARD],
            [cx - 1 * outside * YARD, cy - 9 * YARD],
        ]
    elif name == "sit":
        points = [at(0, 0), at(0, 2), at(4, 6), at(4.7, 5.1)]
    elif name == "chair":
        points = [
            at(0, 0),
            [cx, cy - 5 * YARD],
            [cx + 3 * outside * YARD, cy - 5 * YARD],
            [cx + 3 * outside * YARD, cy - 13 * YARD],
        ]
    elif name == "whip":
        points = [
            at(0, 0),
            [cx, cy - 5 * YARD],
            [cx + 1 * inside * YARD, cy - 5 * YARD],
            [cx + 6 * outside * YARD, cy - 5 * YARD],
        ]
    elif name == "paroute":
        points = [at(0, 0), at(1.2, 2.2), [cx + 6 * outside * YARD, cy - 4 * YARD]]
    elif name == "pablock":
        points = [at(0, 0), at(1.2, 2.2), at(1.2, 3.6)]
    elif name == "playaction":
        points = [at(0, 0), at(1, 3), [cx + 5 * outside * YARD, cy - YARD]]
    elif name == "rbrun":
        end_y = LOS_Y - 4 * YARD
        if cy <= end_y + YARD:
            end_y = cy - 4 * YARD
        points = [[cx, cy], [cx, end_y]]
    elif name == "motion":
        points = [at(0, 0), [cx + 8 * inside * YARD, cy]]
    else:
        points = [at(0, 0), [cx + 8 * inside * YARD, cy + 0.4 * YARD]]
    for point in points[1:]:
        point[0] = min(FIELD_W - 10, max(10, point[0]))
        point[1] = min(FIELD_BOTTOM - 10, max(FIELD_TOP + 10, point[1]))
    return points


LOS_RELEASES = {"drag"}
LINE_RECEIVERS = {"X", "F", "Z", "Y"}


def line_release(cx: float, cy: float) -> tuple[float, int]:
    """Ponto na linha, em 45° e por fora dos tackles."""
    outside = -1 if cx <= FIELD_W / 2 else 1
    land_x = cx + (cy - LOS_Y) * outside
    tackle = 2 * OL_GAP
    center = FIELD_W / 2
    if outside < 0:
        land_x = min(land_x, center - tackle - 12)
    else:
        land_x = max(land_x, center + tackle + 12)
    return min(FIELD_W - 10, max(10, land_x)), outside


def wheel_points(cx: float, cy: float) -> list[list[float]]:
    """Flat em direção à lateral, parando antes da linha, e um balão que sobe na go."""
    outside = -1 if cx <= FIELD_W / 2 else 1
    edge = 6 * YARD if outside < 0 else FIELD_W - 6 * YARD
    rail = edge
    room = (rail - cx) * outside
    turn = min(2.2 * YARD, max(12.0, room * 0.45))
    if room < turn + 8:
        turn = max(8.0, room * 0.55)
    flat_end = rail - outside * turn
    span = max(0.0, (flat_end - cx) * outside)
    flat_yd = min(6.0, span / YARD)
    if flat_yd >= 0.4:
        points = balloon_points(cx, cy, 2, flat_yd, outside)
    else:
        points = [[cx, cy]]
    if abs(flat_end - points[-1][0]) > 3:
        points.append([flat_end, points[-1][1]])
    origin = points[-1]
    top = [rail, origin[1] - turn]
    controls = (
        origin,
        [origin[0] + outside * turn * 0.55, origin[1]],
        [top[0], top[1] + turn * 0.55],
        top,
    )
    steps = 14
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        weights = (u**3, 3 * u * u * t, 3 * u * t * t, t**3)
        points.append([
            sum(weight * anchor[0] for weight, anchor in zip(weights, controls)),
            sum(weight * anchor[1] for weight, anchor in zip(weights, controls)),
        ])
    go_y = max(FIELD_TOP + 10, cy - 15 * YARD)
    if go_y < points[-1][1] - 4:
        points.append([points[-1][0], go_y])
    return points


def flat_to_line(cx: float, cy: float, strong: int = 1) -> list[list[float]]:
    """Sai em 45° e chega na linha por fora da linha ofensiva."""
    land_x, _outside = line_release(cx, cy)
    curve = route_preset("flat", land_x, LOS_Y, strong)
    return [[cx, cy], *curve]


def texas_outside(cx: float, cy: float) -> list[list[float]]:
    """O running back chega por fora da linha e quebra 45° para dentro."""
    land_x, outside = line_release(cx, cy)
    end_x = min(FIELD_W - 10, max(10, land_x - 5 * outside * YARD))
    end_y = max(FIELD_TOP + 10, LOS_Y - 5 * YARD)
    return [[cx, cy], [land_x, LOS_Y], [end_x, end_y]]


def route_for_player(name: str, label: str, cx: float, cy: float, strong: int = 1) -> list[list[float]]:
    """X, F, Z e Y saem de onde estão. O H alonga a screen. A flat do restante chega na linha em 45°."""
    if name == "screen":
        return route_preset(name, cx, cy, strong, 6.0 if label == "H" else 3.2)
    if name == "flat" and label not in LINE_RECEIVERS and cy > LOS_Y + 6:
        return flat_to_line(cx, cy, strong)
    if name == "wheel" and label not in LINE_RECEIVERS and cy > LOS_Y + 6:
        land_x, _outside = line_release(cx, cy)
        return [[cx, cy], *wheel_points(land_x, LOS_Y)]
    if name == "texas" and label not in LINE_RECEIVERS and cy > LOS_Y + 6:
        return texas_outside(cx, cy)
    stem = name in LOS_RELEASES and label not in LINE_RECEIVERS and cy > LOS_Y + 6
    points = route_preset(name, cx, LOS_Y if stem else cy, strong)
    if stem:
        return [[cx, cy], *points]
    return points


def route_ending(kind: str, ending: str | None = None) -> str:
    """A seta é da rota. O motion fica na linha ondulada, sem ponta."""
    if kind == "motion":
        return "open"
    if ending in ("arrow", "bar", "ring", "open"):
        return ending
    if kind in BLOCK_KINDS:
        return "bar"
    return "arrow"


def stored_tip(raw) -> str | None:
    if raw in ("arrow", "bar", "ring", "open"):
        return raw
    return None


def dropback_points(cx: float, cy: float, base: str | None, backs: list[tuple[float, float, float]]) -> list[list[float]]:
    cap = LOS_Y + 8 + 5 * YARD
    if base in DROP_TRAVEL:
        travel = DROP_TRAVEL[base]
    else:
        depth = (cy - LOS_Y) / YARD
        if depth >= 4.6:
            travel = DROP_TRAVEL["shotgun"]
        elif depth >= 3.4:
            travel = DROP_TRAVEL["pistol"]
        else:
            travel = DROP_TRAVEL["singleback"]
    tip = min(cy + travel * YARD, cap)
    for bx, by, radius in backs:
        if abs(bx - cx) > 22:
            continue
        front = by - radius
        if front > cy + 4:
            tip = min(tip, front - 8)
    tip = min(tip, cap)
    if tip >= cy + 18:
        return [[cx, cy], [cx, min(FIELD_BOTTOM - 10, tip)]]
    room_left = cx - 10
    room_right = FIELD_W - 10 - cx
    for bx, _by, radius in backs:
        if bx < cx:
            room_left = min(room_left, cx - bx - radius)
        elif bx > cx:
            room_right = min(room_right, bx - radius - cx)
    sign = -1 if room_left >= room_right else 1
    tip_x = min(FIELD_W - 10, max(10, cx + sign * 22))
    return [[cx, cy], [tip_x, min(cy, cap)]]


def wavy_line(points: list[tuple[float, float]], amplitude: float = 4.5) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    output: list[tuple[float, float]] = []
    traveled = 0.0
    for start, end in zip(points, points[1:]):
        sx, sy = start
        ex, ey = end
        seg = math.hypot(ex - sx, ey - sy)
        if seg < 1:
            continue
        px, py = -(ey - sy) / seg, (ex - sx) / seg
        steps = max(2, int(seg / 4))
        for step in range(steps):
            dist = traveled + seg * step / steps
            offset = math.sin(dist / 14 * math.tau) * amplitude
            t = step / steps
            output.append((sx + (ex - sx) * t + px * offset, sy + (ey - sy) * t + py * offset))
        traveled += seg
    output.append(points[-1])
    return output


DEFENSE_FILL = "#d4d4d4"
DEFENSE_ALPHA = 150


def defense_triangle(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float, float, float]:
    return (x0, y0, x1, y0, (x0 + x1) / 2, y1)


@dataclass
class Shape:
    id: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    text: str = ""
    side: str = "ataque"
    tone: str = ""


@dataclass
class Route:
    id: str
    kind: str
    points: list
    split: int | None = None
    color: str | None = None
    follow: str | None = None
    ending: str | None = None
    lean: int = 0


def shape_from_raw(raw: dict) -> Shape:
    return Shape(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        x=float(raw["x"]),
        y=float(raw["y"]),
        w=float(raw["w"]),
        h=float(raw["h"]),
        text=str(raw.get("text", "")),
        side=str(raw.get("side", "ataque")),
        tone=str(raw.get("tone", "")),
    )


def route_from_raw(raw: dict) -> Route:
    points = [[float(point[0]), float(point[1])] for point in raw["points"]]
    raw_split = raw.get("split")
    split = int(raw_split) if raw_split is not None else None
    raw_color = raw.get("color")
    color = raw_color if raw_color in ROUTE_INK else None
    follow = raw.get("follow")
    try:
        lean = int(raw.get("lean", 0) or 0)
    except (TypeError, ValueError):
        lean = 0
    if lean not in (-1, 0, 1):
        lean = 0
    return Route(
        str(raw["id"]),
        str(raw["kind"]),
        points,
        split,
        color,
        str(follow) if follow else None,
        stored_tip(raw.get("ending")),
        lean,
    )


def compose_sheets(cards: list) -> list:
    """Monta folhas deitadas com quatro jogadas: duas colunas e duas linhas."""
    from PIL import Image, ImageDraw, ImageFont

    per_page = SHEET_COLUMNS * SHEET_ROWS
    if not cards:
        return []
    cell_w = (SHEET_W - 2 * SHEET_MARGIN_X - (SHEET_COLUMNS - 1) * SHEET_GAP) // SHEET_COLUMNS
    cell_h = (SHEET_H - SHEET_MARGIN_TOP - SHEET_MARGIN_BOTTOM - (SHEET_ROWS - 1) * SHEET_GAP) // SHEET_ROWS
    try:
        font = ImageFont.truetype("segoeui.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    pages = []
    total = math.ceil(len(cards) / per_page)
    for page_index in range(total):
        page = Image.new("RGB", (SHEET_W, SHEET_H), "white")
        draw = ImageDraw.Draw(page)
        chunk = cards[page_index * per_page : (page_index + 1) * per_page]
        for slot in range(per_page):
            col = slot % SHEET_COLUMNS
            row = slot // SHEET_COLUMNS
            x0 = SHEET_MARGIN_X + col * (cell_w + SHEET_GAP)
            y0 = SHEET_MARGIN_TOP + row * (cell_h + SHEET_GAP)
            draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + cell_h - 1), outline="#d6d3d1", width=2)
            if slot >= len(chunk):
                continue
            card = chunk[slot].convert("RGB")
            inset = 8
            scale = min((cell_w - 2 * inset) / card.width, (cell_h - 2 * inset) / card.height)
            resized = card.resize(
                (max(1, int(card.width * scale)), max(1, int(card.height * scale))),
                Image.Resampling.LANCZOS,
            )
            page.paste(resized, (x0 + (cell_w - resized.width) // 2, y0 + (cell_h - resized.height) // 2))
        draw.text((SHEET_W / 2, SHEET_H - 16), f"{page_index + 1} / {total}", fill="#78716c", font=font, anchor="mm")
        pages.append(page)
    return pages

