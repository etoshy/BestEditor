"""
🌐 Anime Pexels ONLINE: duas fontes novas ("animepexels_online" e
"moviepexels_online") — o mesmo projeto em modo servidor, com chave de API.
Não substituem as locais. Um servidor falso imita o modo servidor: toda a
API e os vídeos pedem a chave (header Authorization: Bearer / X-API-Key, ou
?api_key= na URL, que é como <video>/<img> mandam).
"""
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

from animepexels.animepexels_client import (AnimePexelsClientError, AnimePexelsOnlineClient,  # noqa: E402
                                            MoviePexelsOnlineClient)
from test_v84_moviepexels import _app_falso  # noqa: E402

CHAVE = "apx_teste_123"
VISTOS = []


@pytest.fixture(scope="module")
def online(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("fakeonline")
    clip = str(pasta / "c.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x180:rate=25:duration=4", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-loglevel", "error", clip], check=True)
    app = _app_falso(clip)
    from flask import jsonify, request

    @app.before_request
    def _chave():
        auth = request.headers.get("Authorization", "")
        raw = auth[7:] if auth.lower().startswith("bearer ") else (request.headers.get("X-API-Key") or request.args.get("api_key") or "")
        VISTOS.append((request.path, raw))
        if not raw:
            return jsonify({"error": "Precisa de chave de API"}), 401
        if raw != CHAVE:
            return jsonify({"error": "Chave de API inválida"}), 401
        return None

    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


class TestCliente:
    def test_manda_a_chave_e_poe_na_url_dos_videos(self, online, tmp_path):
        cli = MoviePexelsOnlineClient(base_url=online, api_key=CHAVE)
        res = cli.search_all(query="cooking", obra="Breaking Bad")
        assert [v.id for v in res] == ["m1"]
        assert res[0].url == "moviepexels_online://clip/m1"  # não confunde com o acervo local
        assert res[0].clip_url == f"{online}/movie/storage/clips/m1.mp4?api_key={CHAVE}"
        assert cli.get_video_by_url(res[0].url).id == "m1"
        arq = cli.download_video(res[0], output_dir=str(tmp_path))
        assert os.path.getsize(arq) > 1000

    def test_sem_chave_ou_chave_errada_explica(self, online):
        with pytest.raises(AnimePexelsClientError, match="401.*Precisa de chave.*confira a chave"):
            AnimePexelsOnlineClient(base_url=online).list_works()
        with pytest.raises(AnimePexelsClientError, match="Chave de API inválida"):
            AnimePexelsOnlineClient(base_url=online, api_key="errada").list_works()

    def test_fora_do_ar_fala_do_servidor_online(self):
        with pytest.raises(AnimePexelsClientError, match="servidor online"):
            AnimePexelsOnlineClient(base_url="http://127.0.0.1:9", api_key=CHAVE, timeout=2).list_works()


# ------------------------------------------------------------------ site
@pytest.fixture
def A(online, monkeypatch, tmp_path):
    import app as _app
    import site_config
    _app.app.config["TESTING"] = True
    cfg_path = str(tmp_path / "site_config.json")
    monkeypatch.setattr(site_config, "CONFIG_PATH", cfg_path)
    site_config.save_site_config({"animepexels_online_url": online, "animepexels_base_url": "http://127.0.0.1:9"}, cfg_path)
    return _app


class TestSite:
    def test_salvar_chave_testar_e_listar(self, A):
        c = A.app.test_client()
        d = c.get("/acervo-online/config").get_json()
        assert d["tem_chave"] is False
        assert c.post("/acervo-online/config", json={"chave": "com espaço"}).status_code == 400
        d = c.post("/acervo-online/config", json={"chave": CHAVE}).get_json()
        assert d["tem_chave"] and d["chave_inicio"] == CHAVE[:8] + "…" and CHAVE not in str(d)  # a chave inteira não volta
        t = c.get("/acervo-online/testar").get_json()
        assert t["catalogos"]["animepexels_online"] == {"ok": True, "obras": 2}
        assert t["catalogos"]["moviepexels_online"]["obras"] == 2
        assert [o["nome"] for o in c.get("/biblioteca-local/moviepexels_online/obras").get_json()["obras"]] == ["Breaking Bad", "Kill Bill"]
        nomes = [p["nome"] for p in c.get("/biblioteca-local/moviepexels_online/personagens?obra=Kill+Bill").get_json()["personagens"]]
        assert nomes == ["The Bride (Uma Thurman)"]
        # salvar só o endereço não apaga a chave
        c.post("/acervo-online/config", json={"url": A.load_site_config()["animepexels_online_url"]})
        assert c.get("/acervo-online/config").get_json()["tem_chave"]
        # a local continua sendo a local (fora do ar aqui) — a online não substitui
        assert c.get("/biblioteca-local/moviepexels/obras").status_code == 502

    def test_montagem_busca_e_baixa_pelo_servidor_online(self, A, tmp_path):
        import video_assembler as V
        from prompt_builder import VideoSegment
        A.save_site_config({"animepexels_online_api_key": CHAVE})
        cfg = A.load_site_config()
        cands = V.search_candidates("moviepexels_online", "cooking", site_cfg=cfg, obra="Breaking Bad")
        assert cands and cands[0]["video_preview_url"].endswith(f"api_key={CHAVE}")
        fab = V.ClientFactory(cfg)
        cli = fab.get_client("moviepexels_online")
        assert isinstance(cli, MoviePexelsOnlineClient) and cli.api_key == CHAVE
        assert VideoSegment(start=0, end=4, provider="animepexels_online", query="ninja").provider == "animepexels_online"

    def test_prompt_e_pagina(self, A):
        import prompt_builder as pb
        p = pb.build_animepexels_prompt([{"start": 0, "end": 5, "text": "x"}], provider="moviepexels_online",
                                        bibliotecas={"moviepexels_online": {"obra": "Kill Bill"}})
        assert '"provider": "moviepexels_online"' in p and "acervo online" in p and '"Kill Bill"' in p
        g = pb.build_prompt([{"start": 0, "end": 5, "text": "x"}], providers=["pexels", "animepexels_online"])
        assert 'Escreva o provider exatamente "animepexels_online"' in g
        r = pb.parse_ai_response('{"segments": [{"start": 0, "end": 5, "provider": "animepexels_online", "query": "ninja", "obra": "Naruto"}]}',
                                 total_duration=5)
        assert r.segments[0].obra == "Naruto"
        html = A.app.test_client().get("/").get_data(as_text=True)
        assert 'value="animepexels_online"' in html and "bib-chave-salvar" in html and "Anime Pexels online" in html
        import acervos
        assert acervos.so_acervo(["moviepexels_online"]) and not acervos.so_acervo(["pexels", "moviepexels_online"])
