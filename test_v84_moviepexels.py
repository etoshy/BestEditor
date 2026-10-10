"""
v84 — 🎬 "moviepexels": o catálogo de FILMES E SÉRIES do anime-pexels-local
(mesmo servidor, rotas em /movie/api/...), com filtro de obra (anime, filme,
série) e de personagem/ator nos dois acervos — pro vídeo inteiro ou por trecho.

Um servidor falso imita a API dos dois catálogos (como o app.py real: um
Blueprint registrado em "/" e em "/movie").
"""
import json
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

from animepexels.animepexels_client import AnimePexelsClient, MoviePexelsClient  # noqa: E402

CLIPES = {
    "anime": [
        {"id": "a1", "human_caption": "ninja runs through forest", "anime_name": "Naruto", "characters": ["Naruto"]},
        {"id": "a2", "human_caption": "detective writes in notebook", "anime_name": "Death Note", "characters": ["Light"]},
    ],
    "movie": [
        {"id": "m1", "human_caption": "man cooking in lab", "anime_name": "Breaking Bad", "characters": ["Walter White (Bryan Cranston)"]},
        {"id": "m2", "human_caption": "two men arguing in RV", "anime_name": "Breaking Bad", "characters": ["Jesse Pinkman (Aaron Paul)", "Walter White (Bryan Cranston)"]},
        {"id": "m3", "human_caption": "woman with sword in hotel", "anime_name": "Kill Bill", "characters": ["The Bride (Uma Thurman)"]},
    ],
}
PEDIDOS = []


def _app_falso(clip_path):
    from flask import Blueprint, Flask, jsonify, request, send_file
    app = Flask("fake_ap")
    bp = Blueprint("site", __name__)

    def cat():
        return "movie" if request.blueprint == "movie" else "anime"

    def _u(c, x):
        return ("/movie" if c == "movie" else "") + x

    def _fmt(c, cl):
        return dict(cl, clip_url=_u(c, f"/storage/clips/{cl['id']}.mp4"), thumbnail_url=_u(c, f"/storage/thumbs/{cl['id']}.jpg"),
                    duration_seconds=6.0, orientation="horizontal", description=cl["human_caption"])

    def _filtrar(c):
        PEDIDOS.append((c, request.path, dict(request.args)))
        q = (request.args.get("q") or "").lower()
        obra = request.args.get("anime") or request.args.get("work")
        pers = (request.args.get("character") or "").lower()
        res = [cl for cl in CLIPES[c]
               if (not obra or cl["anime_name"] == obra)
               and (not pers or any(pers in p.lower() for p in cl["characters"]))
               and (not q or all(w in cl["human_caption"] for w in q.split()))]
        return jsonify({"results": [_fmt(c, x) for x in res], "total": len(res), "has_more": False})

    bp.add_url_rule("/api/search", "search", lambda: _filtrar(cat()))
    bp.add_url_rule("/api/gallery", "gallery", lambda: _filtrar(cat()))
    bp.add_url_rule("/api/animes", "animes", lambda: jsonify({"animes": [{"anime_name": n, "genres": []} for n in sorted({c["anime_name"] for c in CLIPES[cat()]})]}))

    def _personagens():
        obra = request.args.get("anime")
        nomes = {}
        for cl in CLIPES[cat()]:
            if obra and cl["anime_name"] != obra:
                continue
            for p in cl["characters"]:
                nomes[(p, cl["anime_name"])] = nomes.get((p, cl["anime_name"]), 0) + 1
        return jsonify({"characters": [{"id": f"c{k}", "name": n, "anime_name": o, "clip_count": v, "photo_url": _u(cat(), f"/api/characters/c{k}/photo")}
                                       for k, ((n, o), v) in enumerate(sorted(nomes.items(), key=lambda x: -x[1]))]})
    bp.add_url_rule("/api/characters", "chars", _personagens)

    def _clip(cid):
        cl = next((x for x in CLIPES[cat()] if x["id"] == cid), None)
        return (jsonify(_fmt(cat(), cl)), 200) if cl else (jsonify({"error": "x"}), 404)
    bp.add_url_rule("/api/clips/<cid>", "clip", _clip)
    bp.add_url_rule("/storage/clips/<nome>", "arq", lambda nome: send_file(clip_path, mimetype="video/mp4"))
    app.register_blueprint(bp, name="anime")
    app.register_blueprint(bp, url_prefix="/movie", name="movie")
    return app


@pytest.fixture(scope="session")
def servidor(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("fakeap")
    clip = str(pasta / "c.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=320x180:rate=25:duration=6", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, _app_falso(clip))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


# ------------------------------------------------------------------ cliente
class TestVarias:
    """Mais de uma obra e/ou personagem (separados por " | ")."""
    def test_duas_obras_misturam_as_cenas(self, servidor):
        cli = MoviePexelsClient(base_url=servidor)
        res = cli.search_all(obra="Breaking Bad | Kill Bill")
        assert {v.id for v in res} == {"m1", "m2", "m3"} and res[1].id == "m3"  # intercalado: 1º de cada obra
        assert len(res) == len({v.id for v in res})

    def test_dois_personagens(self, servidor):
        cli = MoviePexelsClient(base_url=servidor)
        res = cli.search_all(personagem="jesse | the bride")
        assert {v.id for v in res} == {"m2", "m3"}

    def test_personagens_de_varias_obras(self, servidor):
        cli = MoviePexelsClient(base_url=servidor)
        nomes = {c["nome"] for c in cli.list_characters(obra="Breaking Bad | Kill Bill")}
        assert "The Bride (Uma Thurman)" in nomes and any(n.startswith("Walter") for n in nomes)

    def test_sem_resultado_com_personagem_cai_pras_obras(self, servidor):
        cli = MoviePexelsClient(base_url=servidor)
        res = cli.search_all(query="sword", obra="Breaking Bad | Kill Bill", personagem="walter | jesse")
        assert [v.id for v in res] == ["m3"]  # nenhum dos dois tem "sword": fica dentro das obras

    def test_prompt_e_formulario(self):
        import app as A
        import prompt_builder as pb
        assert A._juntar_varios(" Naruto |Death Note| Naruto ") == "Naruto | Death Note"
        p = pb.build_animepexels_prompt([{"start": 0, "end": 5, "text": "x"}],
                                        bibliotecas={"animepexels": {"obra": "Naruto | Death Note", "personagem": "Naruto | Light"}})
        assert '2 obras: **"Naruto"**; **"Death Note"**' in p and '**"Naruto"**, **"Light"**' in p


class TestCliente:
    def test_filmes_usa_o_catalogo_movie_e_os_filtros(self, servidor):
        PEDIDOS.clear()
        cli = MoviePexelsClient(base_url=servidor)
        res = cli.search_all(query="cooking", obra="Breaking Bad", personagem="walter")
        assert [v.id for v in res] == ["m1"] and res[0].url == "moviepexels://clip/m1"
        assert res[0].clip_url == servidor + "/movie/storage/clips/m1.mp4"
        assert PEDIDOS[0][0] == "movie" and PEDIDOS[0][1] == "/movie/api/search"
        assert PEDIDOS[0][2]["anime"] == "Breaking Bad" and PEDIDOS[0][2]["character"] == "walter"

    def test_afrouxa_dentro_da_obra(self, servidor):
        cli = MoviePexelsClient(base_url=servidor)
        # Jesse não "cozinha": sem o personagem, acha a cena da obra
        assert [v.id for v in cli.search_all(query="cooking", obra="Breaking Bad", personagem="jesse")] == ["m1"]
        # nada com esse texto na obra: cai pra galeria da obra (com o personagem primeiro)
        assert [v.id for v in cli.search_all(query="spaceship", obra="Breaking Bad", personagem="jesse")] == ["m2"]
        # sem filtro nenhum não inventa nada
        assert cli.search_all(query="spaceship") == []
        assert cli.search_all(query="spaceship", obra="Breaking Bad", relaxar=False) == []

    def test_anime_continua_igual(self, servidor):
        PEDIDOS.clear()
        cli = AnimePexelsClient(base_url=servidor)
        res = cli.search_all(query="ninja", obra="Naruto")
        assert [v.id for v in res] == ["a1"] and res[0].url == "animepexels://clip/a1" and PEDIDOS[0][1] == "/api/search"

    def test_listas_e_resolver_link_e_baixar(self, servidor, tmp_path):
        cli = MoviePexelsClient(base_url=servidor)
        assert [w["nome"] for w in cli.list_works()] == ["Breaking Bad", "Kill Bill"]
        pers = cli.list_characters(obra="Breaking Bad")
        assert pers[0]["nome"] == "Walter White (Bryan Cranston)" and pers[0]["clipes"] == 2 and pers[0]["foto"].startswith(servidor + "/movie/api/")
        v = cli.get_video_by_url("moviepexels://clip/m3")
        assert v.anime_name == "Kill Bill"
        caminho = cli.download_video(v, str(tmp_path))
        assert os.path.getsize(caminho) > 1000


# ------------------------------------------------------------------ montagem
class TestMontagem:
    def test_fabrica_e_filtros_so_nos_acervos(self, servidor):
        import video_assembler as va
        from prompt_builder import VideoSegment
        cli = va.ClientFactory({"animepexels_base_url": servidor}).get_client("moviepexels")
        assert isinstance(cli, MoviePexelsClient) and cli.base_url == servidor
        seg = VideoSegment(start=0, end=4, provider="moviepexels", query="x", obra="Kill Bill", personagem="Bride")
        assert va._weight_filter_kwargs(seg) == {"obra": "Kill Bill", "personagem": "Bride"}
        from dataclasses import replace
        assert va._weight_filter_kwargs(replace(seg, provider="pexels")) == {}
        assert "moviepexels" in va._PROVIDERS_WITH_URL_RESOLUTION

    def test_busca_do_editor_com_obra_e_personagem(self, servidor):
        import video_assembler as va
        c = va.search_candidates("moviepexels", "sword", site_cfg={"animepexels_base_url": servidor}, obra="Kill Bill", personagem="uma")
        assert len(c) == 1 and c[0]["url"] == "moviepexels://clip/m3" and c[0]["video_preview_url"].endswith("/movie/storage/clips/m3.mp4")

    def test_segmento_e_baixado_do_acervo_de_filmes(self, servidor, tmp_path):
        import video_assembler as va
        from prompt_builder import VideoSegment
        f = va.ClientFactory({"animepexels_base_url": servidor})
        seg = VideoSegment(start=0, end=4, provider="moviepexels", query="arguing", obra="Breaking Bad", personagem="Jesse")
        caminhos = va._download_segment_with_fallbacks(seg, str(tmp_path), f, ["moviepexels"], "16:9")
        assert caminhos and os.path.exists(caminhos[0])


# ------------------------------------------------------------------ prompt e leitura
class TestPrompt:
    def test_regra_com_obra_fixa_e_lista_de_personagens(self):
        import prompt_builder as pb
        b = {"moviepexels": {"obra": "Breaking Bad", "personagens": [{"nome": "Walter White (Bryan Cranston)", "clipes": 2}]}}
        p = pb.build_prompt([{"start": 0, "end": 5, "text": "x"}], providers=["pexels", "moviepexels"], bibliotecas=b)
        assert 'O provedor "moviepexels" é DIFERENTE' in p and '**"Breaking Bad"**' in p and "   - Walter White (Bryan Cranston) (2 clipes)" in p
        assert '"Personagem (Ator)"' in p
        sem = pb.build_prompt([{"start": 0, "end": 5, "text": "x"}], providers=["pexels"])
        assert "moviepexels" not in sem

    def test_obra_escolhida_lista_os_personagens_mesmo_com_um_fixado(self):
        import prompt_builder as pb
        b = {"animepexels": {"obra": "Violet Evergarden", "personagem": "Violet",
                             "personagens": [{"nome": "Violet", "clipes": 40}, {"nome": "Gilbert", "clipes": 9}]}}
        p = pb.build_animepexels_prompt([{"start": 0, "end": 5, "text": "x"}], bibliotecas=b)
        assert 'Personagens de "Violet Evergarden" que existem no acervo (2):' in p
        assert "   - Violet (40 clipes)" in p and "   - Gilbert (9 clipes)" in p
        assert "OUTRO personagem da lista" in p

    def test_lista_de_obras_quando_nao_tem_obra_fixa(self):
        import prompt_builder as pb
        p = pb.build_prompt([{"start": 0, "end": 5, "text": "x"}], providers=["animepexels"], bibliotecas={"animepexels": {"obras": ["Naruto", "Death Note"]}})
        assert 'nome EXATO de uma destas obras que existem no acervo: "Naruto"; "Death Note"' in p

    def test_prompt_dedicado_de_filmes(self):
        import prompt_builder as pb
        p = pb.build_animepexels_prompt([{"start": 0, "end": 5, "text": "x"}], provider="moviepexels",
                                        bibliotecas={"moviepexels": {"obra": "Kill Bill"}})
        assert "clipes de filmes e séries" in p and '"provider": "moviepexels"' in p and "Naruto" not in p and '"Kill Bill"' in p
        a = pb.build_animepexels_prompt([{"start": 0, "end": 5, "text": "x"}])
        assert "clipes de anime" in a and '"provider": "animepexels"' in a

    def test_leitura_da_obra_e_personagem(self):
        import prompt_builder as pb
        r = pb.parse_ai_response(json.dumps({"segments": [
            {"start": 0, "end": 4, "provider": "moviepexels", "query": "man cooking", "obra": "Breaking Bad", "personagem": "Walter White"},
            {"start": 4, "end": 8, "provider": "pexels", "query": "city", "obra": "não vale aqui"}]}), total_duration=8)
        a, b = r.segments
        assert (a.obra, a.personagem) == ("Breaking Bad", "Walter White") and b.obra is None
        assert a.to_dict()["personagem"] == "Walter White" and "obra" not in b.to_dict()


# ------------------------------------------------------------------ site
@pytest.fixture
def A(servidor, monkeypatch):
    import app as _app
    _app.app.config["TESTING"] = True
    cfg = _app.load_site_config()
    monkeypatch.setattr(_app, "load_site_config", lambda: dict(cfg, animepexels_base_url=servidor))
    return _app


class TestSite:
    def test_rotas_das_listas(self, A):
        c = A.app.test_client()
        assert [o["nome"] for o in c.get("/biblioteca-local/moviepexels/obras").get_json()["obras"]] == ["Breaking Bad", "Kill Bill"]
        assert [o["nome"] for o in c.get("/biblioteca-local/animepexels/obras").get_json()["obras"]] == ["Death Note", "Naruto"]
        nomes = [p["nome"] for p in c.get("/biblioteca-local/moviepexels/personagens?obra=Kill+Bill").get_json()["personagens"]]
        assert nomes == ["The Bride (Uma Thurman)"]
        assert c.get("/biblioteca-local/xpto/obras").status_code == 404

    def test_copiar_lista_inteira_pra_ia(self, A):
        """📋 Copiar todas as obras / todos os personagens (com um pedido pra IA, ex.: quais são vilões)."""
        c = A.app.test_client()
        d = c.get("/biblioteca-local/moviepexels/copiar?o=obras").get_json()
        assert d["quantos"] == 2 and d["texto"].splitlines()[0].startswith("Breaking Bad")
        d = c.get("/biblioteca-local/moviepexels/copiar?o=personagens&obra=Kill Bill&pedido=viloes").get_json()
        assert d["texto"].startswith("Diga quais desses personagens são VILÕES")
        assert "## Kill Bill (1)\n- The Bride (Uma Thurman)" in d["texto"]
        todos = c.get("/biblioteca-local/moviepexels/copiar?o=personagens").get_json()
        assert todos["quantos"] >= 1 and "## Kill Bill" in todos["texto"] and "acervo inteiro" in todos["titulo"]
        livre = c.get("/biblioteca-local/moviepexels/copiar?o=obras&pedido=quais são de terror?").get_json()
        assert livre["texto"].startswith("quais são de terror?")
        html = c.get("/").get_data(as_text=True)
        assert "bib-copiar-btn" in html and "quais são vilões" in html

    def test_servidor_fora_do_ar_nao_quebra(self, A, monkeypatch):
        cfg = A.load_site_config()
        monkeypatch.setattr(A, "load_site_config", lambda: dict(cfg, animepexels_base_url="http://127.0.0.1:9"))
        assert A.app.test_client().get("/biblioteca-local/moviepexels/obras").status_code == 502
        A._JOBS["bib-off"] = {"job_id": "bib-off", "providers": ["moviepexels"], "bibliotecas": {"moviepexels": {"obra": "X"}}}
        assert A._bibliotecas_prompt("bib-off") == {"moviepexels": {"obra": "X"}}

    def test_prompt_le_as_listas_do_acervo(self, A):
        A._JOBS["bib-p"] = {"job_id": "bib-p", "providers": ["pexels", "moviepexels"], "bibliotecas": {"moviepexels": {"obra": "Breaking Bad", "personagem": ""}}}
        b = A._bibliotecas_prompt("bib-p")
        assert b["moviepexels"]["obra"] == "Breaking Bad" and b["moviepexels"]["personagens"][0]["nome"].startswith("Walter")
        assert "obras" not in b["moviepexels"]  # obra fixa: não precisa da lista
        assert A._JOBS["bib-p"]["bibliotecas_info"]["moviepexels"]["personagens"][0].startswith("Walter")

    def test_personagem_fixado_ainda_lista_os_da_obra_e_pagina_mostra(self, A):
        A._JOBS["bib-q"] = {"job_id": "bib-q", "providers": ["moviepexels"], "prompt": "x", "language": "pt", "total_duration": 10.0, "interval_seconds": 5, "segments": [], "extra_instructions": "",
                            "bibliotecas": {"moviepexels": {"obra": "Breaking Bad", "personagem": "Jesse"}}}
        b = A._bibliotecas_prompt("bib-q")
        assert b["moviepexels"]["personagens"]
        html = A.app.test_client().get("/job/bib-q/prompt").get_data(as_text=True)
        assert "listados no prompt pra IA" in html and "Walter" in html

    def test_padrao_do_video_entra_nos_trechos_e_editor_salva(self, A, monkeypatch):
        jid = "bib-job"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "status": "aguardando_json", "created_at": 1.0, "providers": ["pexels", "moviepexels"],
                        "total_duration": 8.0, "pending_segments": [],
                        "bibliotecas": A._bibliotecas_do_form({"bib_moviepexels_obra": "Breaking Bad", "bib_moviepexels_personagem": "",
                                                               "bib_animepexels_obra": "Naruto"}, ["pexels", "moviepexels"])}
        assert A._JOBS[jid]["bibliotecas"] == {"moviepexels": {"obra": "Breaking Bad", "personagem": ""}}  # anime não marcado: fora
        monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
        c = A.app.test_client()
        c.post(f"/job/{jid}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0, "end": 4, "provider": "moviepexels", "query": "man cooking"},
            {"start": 4, "end": 8, "provider": "moviepexels", "query": "sword fight", "obra": "Kill Bill"}]})})
        s0, s1 = A._JOBS[jid]["pending_segments"]
        assert s0["obra"] == "Breaking Bad" and s1["obra"] == "Kill Bill"  # o da IA vale mais
        A._JOBS[jid]["status"] = "pronto_para_editar"
        c.post(f"/job/{jid}/confirm-segments", data={"acao": "salvar", "seg_0_obra": "Breaking Bad", "seg_0_personagem": "Jesse Pinkman (Aaron Paul)"})
        s0, s1 = A._JOBS[jid]["pending_segments"]
        assert s0["personagem"] == "Jesse Pinkman (Aaron Paul)" and s1["obra"] == "Kill Bill"
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert "moviepexels" in html and 'id="bObra"' in html

    def test_paginas_tem_os_campos(self, A):
        c = A.app.test_client()
        html = c.get("/").get_data(as_text=True)
        assert 'value="moviepexels"' in html and 'name="bib_moviepexels_obra"' in html and 'name="bib_animepexels_personagem_reuse"' in html
