"""
Busca de imagens por navegador (Bing/Brave/Yandex/Startpage) usando a
"Busca de Imagens Unificada" (toolkit/unified_images): UM navegador por
buscador, todos os termos na mesma aba, 1ª imagem baixada, e o termo que um
buscador não achou (ou não baixou) vai pro próximo buscador.

Nada aqui abre navegador nem acessa a rede: a busca e o download são
substituídos por funções falsas (ou pelo `run` do adaptador / `fetch_url`
do downloader, nos testes da ponte com o pacote unificado).
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import buscador_imagens_unificado as bu  # noqa: E402
from buscador_imagens_unificado import ImagemBuscador  # noqa: E402
from prompt_builder import VideoSegment  # noqa: E402
import video_assembler as va  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def _fake_buscador(acervo, chamadas, atraso=0.0, ativos=None, pico=None):
    """acervo: {engine: {termo: [url, ...]}}. Registra cada chamada
    (engine, termos) — cada chamada = 1 navegador aberto."""
    lock = threading.Lock()

    def buscar(engine, termos):
        with lock:
            chamadas.append((engine, list(termos)))
            if ativos is not None:
                ativos.add(engine)
                pico[0] = max(pico[0], len(ativos))
        if atraso:
            time.sleep(atraso)
        por_termo = {}
        for t in termos:
            urls = (acervo.get(engine) or {}).get(t) or []
            por_termo[t] = [ImagemBuscador(title=f"{t} ({engine})", original_url=u, query=t, engine=engine) for u in urls]
        with lock:
            if ativos is not None:
                ativos.discard(engine)
        return {"por_termo": por_termo, "erros": {}, "erro_geral": None}

    return buscar


def _fake_baixar(falhar_urls=()):
    def baixar(img, pasta, stem):
        if img.original_url in falhar_urls:
            raise RuntimeError("HTTP 403")
        os.makedirs(pasta, exist_ok=True)
        path = os.path.join(pasta, stem + ".jpg")
        with open(path, "wb") as f:
            f.write(JPEG)
        return path
    return baixar


# --------------------------------------------------------------------------- #
# buscar_e_baixar_primeira: lote + fallback entre buscadores
# --------------------------------------------------------------------------- #

class TestLoteComFallback:
    def test_um_navegador_por_buscador_e_fallback_pro_proximo(self, tmp_path):
        chamadas = []
        acervo = {
            "bing": {"gojo": ["https://a/gojo.jpg"], "sukuna": ["https://a/sukuna.jpg"]},
            "brave": {"geto": ["https://b/geto.jpg"]},
        }
        res = bu.buscar_e_baixar_primeira(
            ["gojo", "geto", "sukuna"], str(tmp_path), headless=True, paralelo=False,
            buscar_fn=_fake_buscador(acervo, chamadas), baixar_fn=_fake_baixar(),
        )
        # o Bing recebeu os 3 termos NUMA chamada só (1 navegador); o Brave só o que faltou
        assert chamadas == [("bing", ["gojo", "geto", "sukuna"]), ("brave", ["geto"])]
        assert res["gojo"]["ok"] and res["gojo"]["engine"] == "bing"
        assert res["geto"]["ok"] and res["geto"]["engine"] == "brave"
        assert [t["engine"] for t in res["geto"]["tentativas"]] == ["bing", "brave"]
        assert os.path.exists(res["sukuna"]["path"])

    def test_pega_so_a_primeira_imagem(self, tmp_path):
        chamadas = []
        acervo = {"bing": {"gojo": ["https://a/1.jpg", "https://a/2.jpg"]}}
        res = bu.buscar_e_baixar_primeira(
            ["gojo"], str(tmp_path), buscar_fn=_fake_buscador(acervo, chamadas), baixar_fn=_fake_baixar(),
        )
        assert res["gojo"]["original_url"] == "https://a/1.jpg"

    def test_download_que_falha_manda_o_termo_pro_proximo_buscador(self, tmp_path):
        chamadas = []
        acervo = {"bing": {"gojo": ["https://a/bloqueada.jpg"]}, "brave": {"gojo": ["https://b/ok.jpg"]}}
        res = bu.buscar_e_baixar_primeira(
            ["gojo"], str(tmp_path), paralelo=False,
            buscar_fn=_fake_buscador(acervo, chamadas), baixar_fn=_fake_baixar({"https://a/bloqueada.jpg"}),
        )
        assert res["gojo"]["ok"] and res["gojo"]["engine"] == "brave"
        assert "download falhou" in res["gojo"]["tentativas"][0]["erro"]

    def test_nenhum_buscador_acha_devolve_erro_com_as_4_tentativas(self, tmp_path):
        chamadas = []
        res = bu.buscar_e_baixar_primeira(
            ["inexistente"], str(tmp_path), paralelo=False,
            buscar_fn=_fake_buscador({}, chamadas), baixar_fn=_fake_baixar(),
        )
        assert res["inexistente"]["ok"] is False
        assert [c[0] for c in chamadas] == ["bing", "brave", "yandex", "startpage"]
        assert "nenhum buscador conseguiu" in res["inexistente"]["erro"]

    def test_buscador_preferido_da_ia_vem_primeiro(self, tmp_path):
        chamadas = []
        acervo = {"yandex": {"gojo": ["https://y/g.jpg"]}, "bing": {"geto": ["https://a/g.jpg"]}}
        res = bu.buscar_e_baixar_primeira(
            [{"query": "gojo", "engine": "yandex"}, {"query": "geto", "engine": "bing"}], str(tmp_path),
            paralelo=False, buscar_fn=_fake_buscador(acervo, chamadas), baixar_fn=_fake_baixar(),
        )
        assert sorted(chamadas) == [("bing", ["geto"]), ("yandex", ["gojo"])]
        assert res["gojo"]["engine"] == "yandex" and res["geto"]["engine"] == "bing"

    def test_termos_repetidos_sao_pesquisados_uma_vez(self, tmp_path):
        chamadas = []
        acervo = {"bing": {"gojo": ["https://a/g.jpg"]}}
        bu.buscar_e_baixar_primeira(
            ["gojo", " gojo ", "gojo"], str(tmp_path), buscar_fn=_fake_buscador(acervo, chamadas), baixar_fn=_fake_baixar(),
        )
        assert chamadas == [("bing", ["gojo"])]

    def test_paralelo_no_maximo_um_navegador_por_buscador(self, tmp_path):
        chamadas, ativos, pico = [], set(), [0]
        acervo = {e: {} for e in bu.ENGINES}
        acervo["startpage"] = {t: [f"https://s/{t}.jpg"] for t in "abcd"}
        pedidos = [{"query": t, "engine": e} for t, e in zip("abcd", bu.ENGINES)]
        res = bu.buscar_e_baixar_primeira(
            pedidos, str(tmp_path), paralelo=True,
            buscar_fn=_fake_buscador(acervo, chamadas, atraso=0.05, ativos=ativos, pico=pico),
            baixar_fn=_fake_baixar(),
        )
        assert all(r["ok"] for r in res.values())
        # cada rodada: cada buscador aparece no máximo 1 vez (1 navegador)
        assert pico[0] <= len(bu.ENGINES)
        for engine in bu.ENGINES:
            termos_por_chamada = [ts for e, ts in chamadas if e == engine]
            assert all(len(set(ts)) == len(ts) for ts in termos_por_chamada)

    def test_sequencial_nunca_tem_dois_navegadores_ao_mesmo_tempo(self, tmp_path):
        chamadas, ativos, pico = [], set(), [0]
        pedidos = [{"query": t, "engine": e} for t, e in zip("abcd", bu.ENGINES)]
        bu.buscar_e_baixar_primeira(
            pedidos, str(tmp_path), paralelo=False,
            buscar_fn=_fake_buscador({}, chamadas, atraso=0.02, ativos=ativos, pico=pico), baixar_fn=_fake_baixar(),
        )
        assert pico[0] == 1

    def test_on_result_avisa_cada_termo(self, tmp_path):
        avisos = []
        acervo = {"bing": {"a": ["https://a/a.jpg"]}}
        bu.buscar_e_baixar_primeira(
            ["a", "b"], str(tmp_path), paralelo=False, on_result=lambda t, r: avisos.append((t, r["ok"])),
            buscar_fn=_fake_buscador(acervo, []), baixar_fn=_fake_baixar(),
        )
        assert sorted(avisos) == [("a", True), ("b", False)]

    def test_buscador_que_estoura_nao_derruba_os_outros(self, tmp_path):
        def buscar(engine, termos):
            if engine == "bing":
                raise RuntimeError("captcha")
            return {"por_termo": {t: [ImagemBuscador(original_url="https://b/x.jpg", query=t)] for t in termos},
                    "erros": {}, "erro_geral": None}
        res = bu.buscar_e_baixar_primeira(["x"], str(tmp_path), paralelo=False, buscar_fn=buscar, baixar_fn=_fake_baixar())
        assert res["x"]["ok"] and res["x"]["engine"] == "brave"
        assert "captcha" in res["x"]["tentativas"][0]["erro"]


# --------------------------------------------------------------------------- #
# Ponte com o pacote unificado: buscar_lote / baixar_imagem / clientes
# --------------------------------------------------------------------------- #

class TestPonteComPacoteUnificado:
    def test_buscar_lote_chama_o_motor_uma_vez_com_todos_os_termos(self, monkeypatch):
        from unified_images.adapters import ADAPTERS, EngineRun, normalize_result

        recebidos = []

        async def fake_run(spec, raw_dir):
            recebidos.append([q["q"] for q in spec.queries])
            run = EngineRun(engine="brave", ok=True)
            for n, q in enumerate(spec.queries, 1):
                run.searches.append({"query": q["q"], "ok": True})
                if q["q"] != "nada":
                    run.results.append(normalize_result("brave", q["q"], {
                        "original_url": f"https://img/{n}.jpg", "thumbnail_url": f"https://t/{n}.jpg",
                        "source_page": "https://site/p", "title": q["q"]}, 1))
            return run

        monkeypatch.setattr(ADAPTERS["brave"], "run", fake_run)
        res = bu.buscar_lote("brave", ["gojo", "geto", "nada", "gojo"], limit=1)
        assert recebidos == [["gojo", "geto", "nada"]]  # 1 chamada = 1 navegador, sem repetir termo
        assert res["por_termo"]["gojo"][0].original_url == "https://img/1.jpg"
        assert res["por_termo"]["gojo"][0].fallback_urls == ["https://t/1.jpg"]
        assert res["por_termo"]["nada"] == []
        assert res["erros"]["nada"] == "nenhuma imagem encontrada"

    def test_buscar_lote_motor_quebrado_vira_erro_em_cada_termo(self, monkeypatch):
        from unified_images.adapters import ADAPTERS

        async def quebra(spec, raw_dir):
            raise RuntimeError("playwright ausente")

        monkeypatch.setattr(ADAPTERS["yandex"], "run", quebra)
        res = bu.buscar_lote("yandex", ["a", "b"])
        assert "playwright ausente" in res["erro_geral"]
        assert set(res["erros"]) == {"a", "b"}

    def test_baixar_imagem_cai_pra_thumbnail_quando_original_nao_e_imagem(self, monkeypatch, tmp_path):
        import unified_images.downloader as dl

        def fake_fetch(url, referer="", timeout=45, allow_private_hosts=False, max_bytes=0):
            if "original" in url:
                return b"<!doctype html><html>bloqueado</html>", "text/html"
            return JPEG, "image/jpeg"

        monkeypatch.setattr(dl, "fetch_url", fake_fetch)
        img = ImagemBuscador(original_url="https://x/original.jpg", thumbnail_url="https://x/thumb.jpg",
                             query="gojo", engine="bing")
        path = bu.baixar_imagem(img, str(tmp_path))
        assert path.endswith(".jpg") and open(path, "rb").read() == JPEG

    def test_baixar_imagem_sem_nada_que_preste_levanta_erro(self, monkeypatch, tmp_path):
        import unified_images.downloader as dl

        monkeypatch.setattr(dl, "fetch_url", lambda *a, **k: (b"<html></html>", "text/html"))
        with pytest.raises(bu.BuscadorImagensError):
            bu.baixar_imagem(ImagemBuscador(original_url="https://x/a.jpg", engine="bing"), str(tmp_path))

    def test_clientes_mantem_a_interface_antiga(self, monkeypatch):
        import bing_api_client
        import brave_api_client
        import startpage_api_client
        import yandex_api_client

        for mod, cls, eng in (
            (bing_api_client, "BingAPIClient", "bing"), (brave_api_client, "BraveAPIClient", "brave"),
            (yandex_api_client, "YandexAPIClient", "yandex"), (startpage_api_client, "StartpageAPIClient", "startpage"),
        ):
            client = getattr(mod, cls)(headless=False)
            assert client.engine == eng and client.headless is False
            monkeypatch.setattr(bu, "buscar_lote", lambda engine, qs, **k: {
                "por_termo": {q: [ImagemBuscador(original_url="https://i/1.jpg", thumbnail_url="https://t/1.jpg",
                                                 source_page="https://p", title="T", query=q, engine=engine)] for q in qs},
                "erros": {}, "erro_geral": None})
            fotos = client.search_photos_all("gojo")
            assert fotos[0].id == "https://i/1.jpg"
            assert fotos[0].sizes["tiny"] == "https://t/1.jpg"
            assert fotos[0].url == "https://p"
            lote = client.search_photos_batch(["a", "b"])
            assert set(lote) == {"a", "b"}

    def test_cliente_erro_geral_sem_resultado_levanta_erro_do_cliente(self, monkeypatch):
        import bing_api_client

        monkeypatch.setattr(bu, "buscar_lote", lambda engine, qs, **k: {
            "por_termo": {q: [] for q in qs}, "erros": {}, "erro_geral": "captcha"})
        with pytest.raises(bing_api_client.BingAPIClientError):
            bing_api_client.BingAPIClient().search_photos_all("gojo")


# --------------------------------------------------------------------------- #
# video_assembler.prefetch_browser_images: cache + termo simplificado
# --------------------------------------------------------------------------- #

def _seg(provider, query, start=0.0, end=3.0):
    return VideoSegment(start=start, end=end, provider=provider, query=query, media_type="image")


class TestPrefetchNaMontagem:
    def test_um_lote_so_pra_todos_os_trechos_e_cache_preenchido(self, tmp_path):
        chamadas = []

        def lote(pedidos, pasta, **kw):
            pedidos = list(pedidos)
            chamadas.append(pedidos)
            out = {}
            for p in pedidos:
                path = os.path.join(pasta, p["query"] + ".jpg")
                os.makedirs(pasta, exist_ok=True)
                open(path, "wb").write(JPEG)
                r = {"ok": True, "path": path, "engine": p["engine"], "query": p["query"], "erro": None}
                kw["on_result"](p["query"], r)
                out[p["query"]] = r
            return out

        cache = {}
        items = [(0, _seg("bing", "gojo")), (1, _seg("brave", "geto")), (2, _seg("yandex", "gojo"))]
        res = va.prefetch_browser_images(items, str(tmp_path), {"browser_visible": False}, cache=cache, lote_fn=lote)
        assert len(chamadas) == 1
        assert [p["query"] for p in chamadas[0]] == ["gojo", "geto"]  # "gojo" repetido: 1 busca só
        assert res[0]["path"] == res[2]["path"]
        assert set(cache) == {"gojo", "geto"}

        # 2ª vez (montagem depois da prévia): tudo do cache, nenhum navegador
        res2 = va.prefetch_browser_images(items, str(tmp_path), {}, cache=cache, lote_fn=lote)
        assert len(chamadas) == 1
        assert res2[1]["path"] == res[1]["path"]

    def test_cache_com_arquivo_apagado_busca_de_novo(self, tmp_path):
        chamadas = []

        def lote(pedidos, pasta, **kw):
            pedidos = list(pedidos)
            chamadas.append(pedidos)
            for p in pedidos:
                kw["on_result"](p["query"], {"ok": False, "erro": "x"})

        cache = {"gojo": {"ok": True, "path": str(tmp_path / "sumiu.jpg")}}
        va.prefetch_browser_images([(0, _seg("bing", "gojo"))], str(tmp_path), {}, cache=cache, lote_fn=lote)
        assert len(chamadas) >= 1

    def test_termo_que_ninguem_acha_tenta_versao_simplificada(self, tmp_path):
        chamadas = []

        def lote(pedidos, pasta, **kw):
            pedidos = list(pedidos)
            chamadas.append([p["query"] for p in pedidos])
            for p in pedidos:
                if p["query"] == "satoru":
                    path = os.path.join(pasta, "satoru.jpg")
                    os.makedirs(pasta, exist_ok=True)
                    open(path, "wb").write(JPEG)
                    kw["on_result"](p["query"], {"ok": True, "path": path, "engine": "bing", "query": "satoru"})
                else:
                    kw["on_result"](p["query"], {"ok": False, "path": None, "erro": "nada"})

        cache = {}
        res = va.prefetch_browser_images(
            [(0, _seg("bing", "gojo satoru")), (1, _seg("bing", "zzz"))], str(tmp_path), {}, cache=cache, lote_fn=lote,
        )
        assert chamadas == [["gojo satoru", "zzz"], ["satoru"]]
        assert res[0]["ok"] and res[0]["query_usada"] == "satoru"
        assert res[1]["ok"] is False
        assert "zzz" not in cache  # falha não fica no cache: a próxima tentativa pesquisa de novo

    def test_usa_config_de_navegador_oculto_e_paralelo(self, tmp_path):
        recebido = {}

        def lote(pedidos, pasta, **kw):
            recebido.update(kw)
            for p in pedidos:
                kw["on_result"](p["query"], {"ok": False, "erro": "x"})

        va.prefetch_browser_images(
            [(0, _seg("bing", "a"))], str(tmp_path),
            {"browser_visible": True, "buscadores_imagem_paralelo": False}, lote_fn=lote,
        )
        assert recebido["headless"] is False and recebido["paralelo"] is False
        assert recebido["engines"] == ["bing", "brave", "yandex", "startpage"]


class TestAssembleVideoUsaOLote:
    def test_trecho_sem_imagem_em_nenhum_buscador_da_erro_claro(self, monkeypatch, tmp_path, synthetic_audio):
        monkeypatch.setattr(va, "prefetch_browser_images", lambda items, *a, **k: {
            i: {"ok": False, "path": None, "erro": "nenhum buscador conseguiu"} for i, _ in items})
        with pytest.raises(va.VideoAssemblyError) as exc:
            va.assemble_video(
                [_seg("bing", "termo impossivel", 0.0, 9.469)], synthetic_audio,
                str(tmp_path / "out.mp4"), str(tmp_path / "work"),
                site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 1},
            )
        assert "Trecho 1" in str(exc.value) and "termo impossivel" in str(exc.value)

    def test_trechos_de_buscador_viram_imagem_no_video(self, monkeypatch, tmp_path, synthetic_audio):
        import subprocess

        img = tmp_path / "foto.jpg"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=320x240", "-frames:v", "1",
                        "-loglevel", "error", str(img)], check=True)
        chamadas = []

        def fake_prefetch(items, downloads_dir, cfg, cache=None, **k):
            chamadas.append([i for i, _ in items])
            return {i: {"ok": True, "path": str(img), "engine": "bing"} for i, _ in items}

        monkeypatch.setattr(va, "prefetch_browser_images", fake_prefetch)
        out = va.assemble_video(
            [_seg("bing", "a", 0.0, 4.0), _seg("startpage", "b", 4.0, 9.469)], synthetic_audio,
            str(tmp_path / "out.mp4"), str(tmp_path / "work"),
            site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 2},
            image_search_cache={},
        )
        assert os.path.exists(out)
        assert chamadas == [[0, 1]]  # os dois trechos num lote só


class TestBlocosEDependencias:
    def test_termos_sao_entregues_em_blocos_sem_esperar_o_lote_inteiro(self, tmp_path):
        chamadas, avisos = [], []
        acervo = {"bing": {t: [f"https://a/{t}.jpg"] for t in "abcdefg"}}

        def buscar(engine, termos):
            # quando o 2º bloco começa, o 1º já tem que ter sido entregue
            chamadas.append((engine, list(termos), len(avisos)))
            return _fake_buscador(acervo, [])(engine, termos)

        bu.buscar_e_baixar_primeira(
            list("abcdefg"), str(tmp_path), paralelo=False, termos_por_navegador=3,
            on_result=lambda t, r: avisos.append(t), buscar_fn=buscar, baixar_fn=_fake_baixar(),
        )
        assert [c[1] for c in chamadas] == [["a", "b", "c"], ["d", "e", "f"], ["g"]]
        assert [c[2] for c in chamadas] == [0, 3, 6]

    def test_buscador_que_cai_inteiro_nao_reabre_pros_proximos_blocos(self, tmp_path):
        chamadas = []

        def buscar(engine, termos):
            chamadas.append((engine, list(termos)))
            if engine == "bing":
                return {"por_termo": {}, "erros": {t: "sem internet" for t in termos}, "erro_geral": "sem internet"}
            return {"por_termo": {t: [ImagemBuscador(original_url=f"https://b/{t}.jpg", query=t)] for t in termos},
                    "erros": {}, "erro_geral": None}

        res = bu.buscar_e_baixar_primeira(list("abcdef"), str(tmp_path), paralelo=False, termos_por_navegador=2,
                                          buscar_fn=buscar, baixar_fn=_fake_baixar())
        assert [c for c in chamadas if c[0] == "bing"] == [("bing", ["a", "b"])]
        assert all(r["ok"] and r["engine"] == "brave" for r in res.values())

    def test_motores_importam_mesmo_sem_fastapi_pydantic_uvicorn(self):
        import subprocess
        codigo = r'''
import sys, importlib.abc
class Bloqueia(importlib.abc.MetaPathFinder):
    def find_spec(self, nome, path=None, target=None):
        if nome.split(".")[0] in ("fastapi", "pydantic", "uvicorn"):
            raise ModuleNotFoundError(nome)
sys.meta_path.insert(0, Bloqueia())
sys.path.insert(0, "toolkit")
from unified_images._compat import garantir_imports_dos_motores
print(sorted(garantir_imports_dos_motores()))
from unified_images.adapters import ADAPTERS
for a in ADAPTERS.values():
    m = a.load_module()
    assert callable(m.search_images_batch)
print("ok")
'''
        out = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
        assert out.returncode == 0, out.stderr[-1500:]
        assert "['fastapi', 'pydantic', 'uvicorn']" in out.stdout and "ok" in out.stdout
