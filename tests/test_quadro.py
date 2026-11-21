"""Testes do campo, do relógio das rotas e da janela sem mostrar o quadro."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["QUADRO_HEADLESS"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nucleo
import main
from nucleo import FIELD_W, Route, Shape, offense_players, route_ending, route_from_raw, route_kind_for


class TestCampo(unittest.TestCase):
    def test_pistol_weak_fica_no_lado_oposto_ao_tight_end(self) -> None:
        strong = {label: x for _kind, label, x, _y, _size in offense_players("pistol", "strong")}
        weak = {label: x for _kind, label, x, _y, _size in offense_players("pistol", "weak")}
        self.assertGreater(strong["FB"], FIELD_W / 2)
        self.assertLess(weak["FB"], FIELD_W / 2)
        self.assertNotEqual(strong["FB"], weak["FB"])
        self.assertEqual(strong["Y"], weak["Y"])

    def test_ponta_e_o_tipo_da_rota(self) -> None:
        self.assertEqual(route_ending("blockpass"), "bar")
        self.assertEqual(route_ending("passe"), "arrow")
        self.assertEqual(route_ending("passe", "ring"), "ring")
        self.assertEqual(route_ending("blockpass", "arrow"), "arrow")
        self.assertEqual(route_kind_for("sit"), "sit")
        self.assertEqual(route_kind_for("slant"), "passe")
        self.assertIn("triangle", nucleo.SHAPE_TOOLS)
        self.assertIn("rectangle", nucleo.SHAPE_TOOLS)

    def test_sit_e_anel_sobrevivem_no_arquivo(self) -> None:
        route = route_from_raw(
            {"id": "abc", "kind": "sit", "points": [[1, 2], [3, 4]], "ending": "ring"}
        )
        self.assertEqual(route.kind, "sit")
        self.assertEqual(route.ending, "ring")


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
        nucleo.PASTA.data = cls.previous
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        app = self.app
        app.shapes = []
        app.routes = []
        app.draft = []
        app.selection = None
        app.loaded_path = None
        app.undo_stack.clear()
        app.redo_stack.clear()
        app.offense_base = None
        app.route_tip = None
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

    def test_sit_novo_grava_o_tipo(self) -> None:
        app = self.app
        player = Shape("s", "circle", 100, 100, 22, 22, "X", "ataque")
        app.shapes.append(player)
        app.select("shape", player.id)
        app.add_player_route("sit")
        self.assertEqual(app.routes[-1].kind, "sit")

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

    def test_lista_nao_grava_e_o_id_so_entra_quando_falta(self) -> None:
        path = self.tmp / "Sem id.json"
        original = json.dumps({"nome": "Sem id", "shapes": [], "routes": []}, ensure_ascii=False)
        path.write_text(original, encoding="utf-8")
        self.app.refresh_list()
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        nucleo.assign_missing_ids()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["id"], 1)
        saved = path.read_text(encoding="utf-8")
        nucleo.assign_missing_ids()
        self.assertEqual(path.read_text(encoding="utf-8"), saved)

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

        def document(data, _fallback):
            calls.append(str(data.get("nome")))
            return Image.new("RGB", (40, 30), "white")

        try:
            app.render_board = board
            app.render_document = document
            disk = self.tmp / "Disco.json"
            other = self.tmp / "Outra.json"
            disk.write_text(json.dumps({"nome": "Disco", "shapes": [], "routes": []}), encoding="utf-8")
            other.write_text(json.dumps({"nome": "Outra", "shapes": [], "routes": []}), encoding="utf-8")
            app.loaded_path = disk
            count, _sheets = app.write_pdf(self.tmp / "jogadas.pdf", [other, disk])
            self.assertEqual(count, 2)
            self.assertEqual(calls, ["Outra", "tela"])

            calls.clear()
            app.loaded_path = None
            app.name_var.set("Solta")
            count, _sheets = app.write_pdf(self.tmp / "so-tela.pdf", [])
            self.assertEqual(count, 1)
            self.assertEqual(calls, ["tela"])
        finally:
            app.render_board = original_board
            app.render_document = original_document
