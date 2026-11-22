"""Testes do campo, do relógio das rotas e da janela sem mostrar o quadro."""

from __future__ import annotations

import os
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["QUADRO_HEADLESS"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nucleo
import main
from nucleo import FIELD_W, Route, Shape, defense_spots, offense_players, route_ending, route_from_raw, route_kind_for


class TestBanco(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.previous = nucleo.PASTA.data
        nucleo.close_store()
        nucleo.PASTA.data = self.tmp

    def tearDown(self) -> None:
        nucleo.close_store()
        nucleo.PASTA.data = self.previous
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_entra_no_banco_sem_substituir_a_jogada_salva(self) -> None:
        (self.tmp / ".categorias.json").write_text(
            '["long", "1st", "1st"]',
            encoding="utf-8",
        )
        (self.tmp / "Play 01.json").write_text(
            '{"id": 7, "nome": "Play 01", "notas": "olho", "categorias": ["1st", "longa"], "shapes": [], "routes": [], "base": "pistol"}',
            encoding="utf-8",
        )
        (self.tmp / ".ultima").write_text("Play 01.json", encoding="utf-8")
        nucleo.open_store()
        self.assertEqual(nucleo.category_catalog(), ["long", "1st", "corrida", "passe"])
        play = nucleo.stored_play(7)
        self.assertEqual(play["nome"], "Play 01")
        self.assertEqual(play["notas"], "olho")
        self.assertEqual(play["categorias"], ["1st"])
        self.assertEqual(play["base"], "pistol")
        self.assertEqual(nucleo.remembered_play(), 7)
        (self.tmp / "Play 02.json").write_text(
            '{"nome": "Play 02", "shapes": [], "routes": []}',
            encoding="utf-8",
        )
        (self.tmp / "Play 01.json").write_text(
            '{"id": 7, "nome": "Play 01", "notas": "mudou no arquivo", "shapes": [], "routes": []}',
            encoding="utf-8",
        )
        nucleo.close_store()
        nucleo.open_store()
        self.assertIsNotNone(nucleo.play_id_for_name("Play 02"))
        self.assertEqual(nucleo.stored_play(7)["notas"], "olho")

    def test_set_da_formacao_fica_na_jogada(self) -> None:
        play_id = nucleo.store_play(
            {"nome": "Pistol Strong", "base": "pistol", "set": "strong", "shapes": [], "routes": []}
        )
        saved = nucleo.stored_play(play_id)
        self.assertEqual(saved["base"], "pistol")
        self.assertEqual(saved["set"], "strong")
        self.assertEqual(nucleo.formation_label("pistol", "strong"), "Pistol · Strong")
        self.assertEqual(nucleo.formation_label("i", None), "I-Formation")

    def test_folha_mostra_nome_e_observacao(self) -> None:
        from PIL import Image

        card = Image.new("RGB", (200, 120), "white")
        pages = nucleo.compose_sheets([(card, "01 Z na go", "O Y faz o out e o Z sobe reto na go.")])
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].size, (nucleo.SHEET_W, nucleo.SHEET_H))
        crop = pages[0].crop((40, 28, 760, 140))
        dark = 0
        for count, color in crop.getcolors(crop.size[0] * crop.size[1]) or []:
            if color[0] < 40:
                dark += count
        self.assertGreater(dark, 80)

    def test_catalogo_de_formacao_fica_no_banco(self) -> None:
        bases, sets = nucleo.formation_menu("offense")
        names = [name for name, _key in bases]
        keys = [key for _name, key in bases]
        self.assertEqual(
            names[:7],
            ["I-Formation", "T-Formation", "Splitback", "Pistol", "Goal Line", "Wishbone", "Flexbone"],
        )
        self.assertIn("shotgun", keys)
        self.assertIn("singleback", keys)
        self.assertNotIn("trips", keys)
        self.assertIn("trips", [key for _name, key in sets["pistol"]])
        self.assertIn("trips", [key for _name, key in sets["shotgun"]])
        self.assertIn("trips", [key for _name, key in sets["singleback"]])
        self.assertNotIn("trips", [key for _name, key in sets["t"]])
        self.assertNotIn("trips", [key for _name, key in sets["wishbone"]])
        self.assertNotIn("trips", [key for _name, key in sets["flexbone"]])
        nucleo.close_store()
        nucleo.open_store()
        again, _sets = nucleo.formation_menu("offense")
        self.assertEqual([key for _name, key in again], keys)


class TestCampo(unittest.TestCase):
    def test_toda_formacao_fecha_onze(self) -> None:
        for base, styles in nucleo.OFFENSE_SETS.items():
            for _name, style in styles:
                players = offense_players(base, style)
                labels = [label for _kind, label, _x, _y, _size in players]
                self.assertEqual(len(players), 11, (base, style))
                self.assertEqual(len(labels), len(set(labels)), (base, style))
        for base, styles in nucleo.DEFENSE_SETS.items():
            for _name, style in styles:
                self.assertEqual(len(defense_spots(base, style)), 11, (base, style))

    def test_t_e_osso_e_flex_tem_o_backfield_da_base(self) -> None:
        def spots(base: str, style: str) -> dict[str, tuple[float, float]]:
            return {label: (x, y) for _kind, label, x, y, _size in offense_players(base, style)}

        tight = spots("t", "tight")
        self.assertEqual(tight["A"][1], tight["FB"][1])
        self.assertEqual(tight["H"][1], tight["FB"][1])
        self.assertLess(tight["A"][0], tight["FB"][0])
        self.assertGreater(tight["H"][0], tight["FB"][0])
        self.assertIn("U", tight)
        pro = spots("t", "pro")
        self.assertIn("X", pro)
        self.assertNotIn("U", pro)

        bone = spots("wishbone", "pro")
        self.assertLess(bone["FB"][1], bone["A"][1])
        self.assertEqual(bone["A"][1], bone["H"][1])
        self.assertLess(bone["A"][0], bone["FB"][0])
        self.assertGreater(bone["H"][0], bone["FB"][0])

        flex = spots("flexbone", "pro")
        self.assertLess(flex["A"][1], flex["FB"][1])
        self.assertLess(flex["H"][1], flex["FB"][1])
        self.assertIn("X", flex)
        closed = spots("flexbone", "tight")
        self.assertIn("U", closed)
        self.assertNotIn("X", closed)

    def test_pistol_strong_poe_o_fullback_ao_lado_do_quarterback(self) -> None:
        spots = {label: (x, y) for _kind, label, x, y, _size in offense_players("pistol", "strong")}
        self.assertEqual(spots["FB"][1], spots["QB"][1])
        self.assertGreater(spots["FB"][0], spots["QB"][0])
        self.assertLess(spots["FB"][0] - spots["QB"][0], 2 * nucleo.SKILL_SIZE)
        self.assertEqual(spots["H"][0], spots["QB"][0])
        self.assertGreater(spots["H"][1], spots["QB"][1])
        self.assertNotIn("weak", [key for _name, key in nucleo.OFFENSE_SETS["pistol"]])

    def test_ponta_e_o_tipo_da_rota(self) -> None:
        self.assertEqual(route_ending("blockpass"), "bar")
        self.assertEqual(route_ending("passe"), "arrow")
        self.assertEqual(route_ending("motion"), "open")
        self.assertEqual(route_ending("motion", "arrow"), "open")
        self.assertEqual(route_ending("passe", "ring"), "ring")
        self.assertEqual(route_ending("blockpass", "arrow"), "arrow")
        self.assertEqual(route_kind_for("snag"), "snag")
        self.assertEqual(route_kind_for("sit"), "snag")
        self.assertEqual(route_kind_for("rbrun"), "rbrun")
        self.assertEqual(route_kind_for("slant"), "passe")
        run = nucleo.route_preset("rbrun", 400, nucleo.LOS_Y + 7 * nucleo.YARD)
        self.assertEqual(run[0][0], run[1][0])
        self.assertLess(run[1][1], nucleo.LOS_Y)
        self.assertEqual(nucleo.route_ink("rbrun", "verde"), nucleo.ROUTE_COLOR["rbrun"])
        self.assertEqual(nucleo.route_ink("release", "laranja"), nucleo.ROUTE_COLOR["release"])
        self.assertEqual(nucleo.route_ink("passe", "laranja"), nucleo.ROUTE_INK["laranja"])
        self.assertEqual(nucleo.player_mark("ataque", "square", "C"), "square")
        self.assertEqual(nucleo.player_mark("ataque", "square", "LT"), "circle")
        self.assertEqual(nucleo.player_mark("ataque", "circle", "QB"), "circle")
        self.assertEqual(nucleo.player_mark("ataque", "circle", "Z"), "cross")
        self.assertEqual(nucleo.player_mark("ataque", "circle", "FB"), "cross")
        self.assertEqual(nucleo.player_mark("defesa", "x", "E"), "square")
        self.assertEqual(nucleo.player_mark("defesa", "x", "M"), "circle")
        self.assertEqual(nucleo.player_mark("defesa", "x", "S"), "circle")
        self.assertEqual(nucleo.player_mark("defesa", "x", "C"), "cross")
        self.assertEqual(nucleo.player_mark("defesa", "x", "SS"), "cross")
        self.assertEqual(nucleo.player_mark("defesa", "x", "N", nucleo.LOS_Y - 10), "square")
        self.assertEqual(nucleo.player_mark("defesa", "x", "N", nucleo.LOS_Y - 4 * nucleo.YARD), "cross")
        self.assertEqual(nucleo.yards_per_sec("rbrun"), nucleo.yards_per_sec("blockrun"))
        self.assertIn("triangle", nucleo.SHAPE_TOOLS)
        self.assertIn("rectangle", nucleo.SHAPE_TOOLS)

    def test_rb_espera_antes_de_sair(self) -> None:
        run_route = nucleo.Route("rb", "rbrun", [[100.0, 200.0], [100.0, 158.0]])
        hold = nucleo.run_hold(run_route)
        self.assertGreater(hold, 0)
        self.assertEqual(nucleo.run_hold(nucleo.Route("bk", "blockrun", [[0.0, 0.0], [0.0, -20.0]])), 0.0)
        self.assertEqual(nucleo.dot_position(run_route, hold * 0.5, 0, set()), (100.0, 200.0))
        self.assertLess(nucleo.dot_position(run_route, hold + nucleo.YARD, 0, set())[1], 200.0)
        self.assertAlmostEqual(
            nucleo.clock_length(run_route),
            hold + nucleo.clock_for(42.0, nucleo.yards_per_sec("rbrun")),
        )

    def test_wheel_termina_antes_da_linha_de_10(self) -> None:
        ten = nucleo.LOS_Y - 10 * nucleo.YARD
        wide = nucleo.route_for_player("wheel", "Z", 650, nucleo.LOS_Y + 8, 1)
        back = nucleo.route_for_player("wheel", "H", 400, nucleo.LOS_Y + 7 * nucleo.YARD, 1)
        for points in (wide, back):
            end_y = points[-1][1]
            self.assertGreater(end_y, ten)
            self.assertLess(end_y, nucleo.LOS_Y)

    def test_pa_pass_segura_a_rota_ate_o_fake_acabar(self) -> None:
        fake = nucleo.Route("p", "papass", [[0.0, 0.0], [0.0, -30.0]])
        route = nucleo.Route("r", "passe", [[0.0, -30.0], [0.0, -90.0]], follow="p", color="laranja")
        routes = [fake, route]
        wait = nucleo.clock_length(fake)
        self.assertGreater(wait, 0)
        self.assertEqual(nucleo.yards_per_sec("papass"), nucleo.RUN_BLOCK_YARDS_PER_SEC)
        self.assertIsNone(nucleo.dot_position(route, wait * 0.5, 0, {"p"}, routes))
        moved = nucleo.dot_position(route, wait + nucleo.YARD, 0, {"p"}, routes)
        self.assertIsNotNone(moved)
        self.assertLess(moved[1], -30.0)
        self.assertIsNone(nucleo.dot_position(fake, wait + 1, 0, {"p"}, routes))
        self.assertGreaterEqual(nucleo.play_distance(routes), wait + nucleo.clock_length(route))
        motion = nucleo.Route("m", "motion", [[0.0, 0.0], [40.0, 0.0]])
        follower = nucleo.Route("f", "passe", [[40.0, 0.0], [40.0, -40.0]], follow="m")
        snap = nucleo.snap_distance([motion, follower])
        self.assertIsNone(nucleo.dot_position(follower, snap * 0.5, snap, {"m"}, [motion, follower]))

    def test_snag_e_anel_sobrevivem_no_arquivo(self) -> None:
        route = route_from_raw(
            {"id": "abc", "kind": "sit", "points": [[1, 2], [3, 4]], "ending": "ring"}
        )
        self.assertEqual(route.kind, "snag")
        self.assertEqual(route.ending, "ring")
        self.assertEqual(route.lean, 0)

    def test_inclinacao_anda_45_e_volta_pelo_meio(self) -> None:
        self.assertEqual(nucleo.step_lean(0, 1), 1)
        self.assertEqual(nucleo.step_lean(1, 1), 2)
        self.assertEqual(nucleo.step_lean(3, 1), 4)
        self.assertEqual(nucleo.step_lean(1, -1), 0)
        self.assertEqual(nucleo.step_lean(0, -1), -1)
        self.assertEqual(nucleo.step_lean(-3, -1), -4)
        self.assertEqual(nucleo.step_lean(-1, 1), 0)
        lap = nucleo.Route("z", "blockrun", [[100.0, 200.0], [100.0, 170.0]], lean=24)
        back = nucleo.route_path(lap)
        self.assertAlmostEqual(back[1][0], 100, places=3)
        self.assertAlmostEqual(back[1][1], 170, places=3)
        box = nucleo.painted_box(100, 200, 22, 22, "circle")
        self.assertAlmostEqual(box[0] + box[2] / 2, 111)
        self.assertAlmostEqual(box[1] + box[3] / 2, 211)
        self.assertLess(box[2], 22)
        self.assertEqual(nucleo.painted_box(0, 0, 40, 40, "zone"), (0, 0, 40, 40))
        up = nucleo.Route("a", "blockrun", [[100.0, 200.0], [100.0, 170.0]], lean=3)
        path = nucleo.route_path(up)
        dx = path[1][0] - path[0][0]
        dy = path[1][1] - path[0][1]
        self.assertGreater(dx, 0)
        self.assertAlmostEqual(abs(dx), abs(dy), places=3)
        self.assertAlmostEqual(math.hypot(dx, dy), 30, places=3)
        down = nucleo.Route("b", "blockpass", [[100.0, 200.0], [100.0, 230.0]], lean=3)
        tipped = nucleo.route_path(down)
        self.assertGreater(tipped[1][0], 100)
        self.assertGreater(tipped[1][1], 200)
        slant = nucleo.route_preset("slant", 400, nucleo.LOS_Y + 20)
        visual = nucleo.route_path(nucleo.Route("c", "passe", slant, lean=3))
        self.assertAlmostEqual(nucleo.route_length(visual), nucleo.route_length(slant), places=3)
        stored = route_from_raw({"id": "d", "kind": "passe", "points": [[0, 0], [0, -10]], "lean": -1})
        self.assertEqual(stored.lean, -1)
        motion = nucleo.Route("m", "motion", [[0.0, 0.0], [40.0, 0.0]], lean=1)
        turned = nucleo.route_path(motion)
        follow = nucleo.Route("f", "rbrun", [[40.0, 0.0], [40.0, -30.0]], follow="m", lean=-1)
        shifted = nucleo.route_path(follow, [motion, follow])
        self.assertAlmostEqual(shifted[0][0], turned[1][0], places=3)
        self.assertAlmostEqual(shifted[0][1], turned[1][1], places=3)
        self.assertLess(shifted[1][0], shifted[0][0])


class TestQuadro(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.previous = nucleo.PASTA.data
        nucleo.PASTA.data = cls.tmp
        cls.app = main.QuadroTatico()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.destroy()
        nucleo.close_store()
        nucleo.PASTA.data = cls.previous
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        app = self.app
        app.shapes = []
        app.routes = []
        app.draft = []
        app.selection = None
        app.loaded_id = None
        app.play_id = None
        nucleo.clear_stored_plays()
        app.undo_stack.clear()
        app.redo_stack.clear()
        app.offense_base = None
        app.offense_set = None
        app.route_tip = None
        app.tool = "select"
        app.block_kind = None
        app.block_anchor = None
        app.mouse = None
        app._suspend = True
        app.name_var.set("")
        app.label_var.set("")
        app.play_categories = []
        app.notes.delete("1.0", "end")
        app._suspend = False
        app._paint_categories()
        app._paint_route_tip()
        app.focus_set()
        app.mark_clean()

    def test_nome_marca_alteracao_e_desfazer_volta_ao_salvo(self) -> None:
        app = self.app
        app.on_name_focus_in()
        app.name_var.set("Alpha")
        self.assertTrue(app.dirty)
        app.on_name_focus_out()
        app.undo()
        self.assertEqual(app.name_var.get(), "")
        self.assertFalse(app.dirty)

    def test_observacao_e_categoria_entram_no_desfazer(self) -> None:
        app = self.app
        app.on_notes_focus_in()
        app.notes.insert("1.0", "olho no safety")
        app.on_notes_edit()
        app.on_notes_focus_out()
        self.assertTrue(app.dirty)
        app.toggle_category("1st")
        self.assertIn("1st", app.play_categories)
        app.undo()
        self.assertEqual(app.play_categories, [])
        self.assertEqual(app.notes_text(), "olho no safety")
        app.undo()
        self.assertEqual(app.notes_text(), "")
        self.assertFalse(app.dirty)

    def test_corrida_e_passe_nao_ficam_juntos(self) -> None:
        app = self.app
        app.toggle_category("corrida")
        app.toggle_category("passe")
        self.assertEqual(app.play_categories, ["passe"])
        app.toggle_category("1st")
        self.assertEqual(app.play_categories, ["passe", "1st"])

    def test_mover_jogador_leva_a_rota_e_a_cobertura_nao(self) -> None:
        app = self.app
        player = Shape("p", "circle", 100, 200, 22, 22, "Z", "ataque")
        zone = Shape("z", "zone", 0, 0, 400, 400, "", "zona", "amarelo")
        motion = Route("m", "motion", [[111, 211], [200, 211]])
        follow = Route("f", "passe", [[200, 211], [200, 100]], follow="m", color="laranja")
        app.shapes = [player, zone]
        app.routes = [motion, follow]
        app._shift_with_player(player, 10, 0)
        self.assertEqual(player.x, 110)
        self.assertEqual(motion.points[0][0], 121)
        self.assertEqual(follow.points[0][0], 210)
        app._shift_with_player(zone, 30, 0)
        self.assertEqual(zone.x, 30)
        self.assertEqual(motion.points[0][0], 121)

    def test_snag_novo_grava_o_tipo(self) -> None:
        app = self.app
        player = Shape("s", "circle", 100, 100, 22, 22, "X", "ataque")
        app.shapes.append(player)
        app.select("shape", player.id)
        app.add_player_route("snag")
        self.assertEqual(app.routes[-1].kind, "snag")

    def test_pa_pass_recebe_a_rota_da_arvore(self) -> None:
        app = self.app
        player = Shape("s", "circle", 100, 100, 22, 22, "Z", "ataque")
        app.shapes.append(player)
        app.select("shape", player.id)
        app.add_player_route("papass")
        fake = app.routes[-1]
        self.assertEqual(fake.kind, "papass")
        self.assertEqual(route_ending(fake.kind, fake.ending), "open")
        app.add_player_route("slant")
        route = app.routes[-1]
        self.assertEqual(route.follow, fake.id)
        self.assertEqual(route.points[0], fake.points[-1])
        self.assertEqual([item.kind for item in app.routes], ["papass", "passe"])
        app.add_player_route("go")
        self.assertEqual([item.kind for item in app.routes], ["papass", "passe"])
        self.assertEqual(app.routes[1].follow, fake.id)
        app.selection = ("route", fake.id)
        app.delete_selected()
        self.assertEqual(app.routes, [])

    def test_anel_fica_na_rota_selecionada(self) -> None:
        app = self.app
        route = Route("r", "passe", [[0, 0], [20, 0]], color="laranja")
        app.routes.append(route)
        app.mark_clean()
        app.selection = ("route", route.id)
        app.set_route_tip("ring")
        self.assertEqual(app.routes[0].ending, "ring")
        self.assertTrue(app.dirty)
        app.focus_set()
        app.undo()
        self.assertIsNone(app.routes[0].ending)
        self.assertFalse(app.dirty)

    def test_seta_inclina_bloqueio_e_passe(self) -> None:
        app = self.app
        block = Route("b", "blockrun", [[100.0, 300.0], [100.0, 270.0]])
        app.routes.append(block)
        app.selection = ("route", block.id)
        app.tool = "select"
        app.focus_set()
        right = type("E", (), {"keysym": "Right", "state": 0})()
        left = type("E", (), {"keysym": "Left", "state": 0})()
        app.on_arrow(right)
        app.on_arrow_release(right)
        self.assertEqual(block.lean, 1)
        self.assertGreater(nucleo.route_path(block)[1][0], 100)
        app.undo()
        block = app.routes[0]
        self.assertEqual(block.lean, 0)
        app.on_arrow(left)
        app.on_arrow(left)
        app.on_arrow(left)
        self.assertEqual(block.lean, -3)
        self.assertLess(nucleo.route_path(block)[1][0], 100)
        app.on_arrow(left)
        self.assertEqual(block.lean, -4)
        app.on_arrow(right)
        app.on_arrow(right)
        app.on_arrow(right)
        app.on_arrow(right)
        self.assertEqual(block.lean, 0)
        app.on_arrow(right)
        self.assertEqual(block.lean, 1)
        self.assertGreater(nucleo.route_path(block)[1][0], 100)

    def test_bloqueio_livre_nasce_no_jogador(self) -> None:
        app = self.app
        player = Shape("p", "square", 90, 200, 22, 22, "LG", "ataque")
        old = Route("old", "passe", [[101, 211], [101, 150]])
        app.shapes.append(player)
        app.routes.append(old)
        app.selection = ("shape", player.id)
        app.begin_block_path("blockpass")
        self.assertEqual(app.draft, [[101, 211]])
        app.draft.append([130, 211])
        app.draft.append([130, 160])
        app.finish_route()
        self.assertEqual(app.tool, "select")
        self.assertEqual(len(app.routes), 1)
        drawn = app.routes[0]
        self.assertEqual(drawn.kind, "blockpass")
        self.assertEqual(len(drawn.points), 3)
        self.assertTrue(app._starts_on(drawn, player))

    def test_rb_path_nasce_no_jogador_e_a_ponta_estica(self) -> None:
        app = self.app
        player = Shape("p", "circle", 100, 200, 22, 22, "H", "ataque")
        app.shapes.append(player)
        self.assertEqual(app._piece_center(105, 206), (111, 211))
        self.assertEqual(app._piece_center(10, 10), (10, 10))
        app.selection = ("shape", player.id)
        app.begin_block_path("rbrun")
        self.assertEqual(app.draft, [[111, 211]])
        app.draft.append([111, 140])
        app.draft.append([140, 120])
        app.finish_route()
        drawn = app.routes[0]
        self.assertEqual(drawn.kind, "rbrun")
        self.assertEqual(len(drawn.points), 3)
        arrow = Route("run", "rbrun", [[111.0, 211.0], [111.0, 151.0]])
        app.routes.append(arrow)
        app._move_run_tip(arrow, 111, 100, 0)
        self.assertEqual(arrow.points[0], [111.0, 211.0])
        self.assertEqual(arrow.points[1], [111, 100])

    def test_lista_nao_cria_jogada_e_o_id_entra_ao_salvar(self) -> None:
        self.assertEqual(nucleo.stored_plays(), [])
        self.app.refresh_list()
        self.assertEqual(nucleo.stored_plays(), [])
        play_id = nucleo.store_play({"nome": "Sem id", "shapes": [], "routes": []})
        self.assertEqual(play_id, 1)
        saved = nucleo.stored_play(play_id)
        self.assertEqual(saved["id"], 1)
        self.assertEqual(nucleo.store_play(saved), 1)
        self.assertEqual([item["id"] for item in nucleo.stored_plays()], [1])

    def test_categoria_fica_na_tabela(self) -> None:
        play_id = nucleo.store_play(
            {
                "nome": "Alpha",
                "shapes": [],
                "routes": [],
                "categorias": ["long", "1st", "inexistente"],
            }
        )
        self.assertEqual(nucleo.stored_play(play_id)["categorias"], ["1st", "long"])
        self.assertEqual(
            nucleo.category_catalog(),
            ["1st", "2nd", "3rd", "4th", "short", "long", "corrida", "passe"],
        )

    def test_pdf_usa_a_tela_e_nao_mexe_na_jogada_aberta(self) -> None:
        from PIL import Image

        app = self.app
        original_board = app.render_board
        original_document = app.render_document
        kept = Shape("keep", "circle", 10, 10, 22, 22, "QB", "ataque")
        app.shapes = [kept]
        app.name_var.set("Tela")
        app.notes.insert("1.0", "na tela")
        image = app.render_document(
            {
                "nome": "Disco",
                "notas": "no arquivo",
                "shapes": [
                    {"id": "d", "kind": "square", "x": 1, "y": 2, "w": 22, "h": 22, "text": "C"}
                ],
                "routes": [],
            },
            "Disco",
        )
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(app.shapes[0].text, "QB")
        self.assertEqual(app.name_var.get(), "Tela")
        self.assertEqual(app.notes_text(), "na tela")

        calls: list[str] = []

        def board(*_args, **_kwargs):
            calls.append("tela")
            return Image.new("RGB", (40, 30), "white")

        def document(data, _fallback, **_kwargs):
            calls.append(str(data.get("nome")))
            return Image.new("RGB", (40, 30), "white")

        try:
            app.render_board = board
            app.render_document = document
            disk = nucleo.store_play({"nome": "Disco", "shapes": [], "routes": []})
            other = nucleo.store_play({"nome": "Outra", "shapes": [], "routes": []})
            app.loaded_id = disk
            app.play_id = disk
            count, _sheets = app.write_pdf(self.tmp / "jogadas.pdf", [other, disk])
            self.assertEqual(count, 2)
            self.assertEqual(calls, ["Outra", "tela"])

            calls.clear()
            app.loaded_id = None
            app.play_id = None
            app.name_var.set("Solta")
            count, _sheets = app.write_pdf(self.tmp / "so-tela.pdf", [])
            self.assertEqual(count, 1)
            self.assertEqual(calls, ["tela"])
        finally:
            app.render_board = original_board
            app.render_document = original_document
