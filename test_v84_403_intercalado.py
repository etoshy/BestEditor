"""v84_403: 🎙 narração intercalada com o som original · 🎵 drop no clímax · 📊 estilo dos concorrentes · 👉 seta · 🔍 nitidez."""
import json
import os
import subprocess
from types import SimpleNamespace

import curtos as CT
import curtos_comentario as CC
import estilo_concorrentes as EC
from test_v84_345_personalidade import _p


def _clipe(base, p, nome="M1.mp4", dur=3, tam="320x240", som=True):
    cam = os.path.join(CT.pasta(base, p["id"]), nome)
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={tam}:rate=25:duration={dur}"]
    if som:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:a", "aac"]
    subprocess.run(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", cam], check=True, capture_output=True)
    return cam


def test_intercalado_prompt_schema_e_ler(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "Inter", "")
    p = _p(base, c["id"])
    assert not CC.intercalado(p) and "momentos_originais" not in CC.roteiro_schema(p)["properties"]
    p["config"]["som_original"] = "intercalado"
    assert CC.intercalado(p)
    sc = CC.roteiro_schema(p)
    assert "momentos_originais" in sc["properties"] and "momentos_originais" in sc["required"]
    assert "momentos_originais" in CC.sistema(p)
    rev = dict(p, config=dict(p["config"], estilo_roteiro="reverso"))
    assert not CC.intercalado(rev)  # não junta com o reverse rage
    p["midias"] = [{"id": "M1", "tipo": "video"}]
    f = list(CT.FUNCOES_BLOCO)[0]
    resp = {"blocos": [{"funcao": f, "fala_en": "Watch this guy.", "fala_pt": "", "cenas": [], "sfx": []},
                       {"funcao": f, "fala_en": "And then this happened.", "fala_pt": "", "cenas": [], "sfx": []}],
            "momentos_originais": [{"material": "M1", "de": 5, "ate": 30, "depois_do_bloco": 2, "por_que": "a risada"},
                                   {"material": "M1", "de": 1, "ate": 3, "depois_do_bloco": 1, "por_que": "o grito"},
                                   {"material": "M1", "de": 1, "ate": 1.2, "depois_do_bloco": 1},   # curto demais
                                   {"material": "M9", "de": 1, "ate": 3, "depois_do_bloco": 1},     # mídia que não existe
                                   {"material": "M1", "de": 1, "ate": 3, "depois_do_bloco": 7}]}    # bloco que não existe
    r = CC.ler_roteiro(resp, p, "en")
    assert r["momentos_originais"] == [
        {"material": "M1", "de": 1.0, "ate": 3.0, "depois_do_bloco": 1, "por_que": "o grito"},
        {"material": "M1", "de": 5.0, "ate": 15.0, "depois_do_bloco": 2, "por_que": "a risada"}]  # no máximo 10 s


def test_varios_cortes_com_som_original():
    p = {"config": {"som_original": "intercalado"},
         "roteiro": {"momentos_originais": [{"material": "M1", "de": 1, "ate": 3, "depois_do_bloco": 1, "por_que": "grito"},
                                            {"material": "M2", "de": 4, "ate": 6.5, "depois_do_bloco": 2, "por_que": "risada"},
                                            {"material": "M1", "de": 1, "ate": 2, "depois_do_bloco": 9}]},
         "gravacao": {"dur": 8.0, "alinhamento": [{"end": 2.0}, {"end": 5.0}, {"end": 8.0}]}}
    cs = CT.cortes_com_som_original(p)
    assert [(c["insertion_point"], c["midia"], c["inicio"], c["fim"]) for c in cs] == [
        (2.15, "M1", "1.00", "3.00"), (5.15, "M2", "4.00", "6.50")]
    assert all(c["audio_mode"] == "pause" for c in cs)


def test_bip_no_som_original(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "Bip", "")
    p = _p(base, c["id"])
    _clipe(base, p)
    p["midias"] = [{"id": "M1", "tipo": "video", "arquivo": "M1.mp4"}]
    CT.salvar(base, p)
    chamadas = []

    def whisper(wav, **k):
        chamadas.append(k)
        return [{"text": "what the fuck man", "words": [{"word": "what", "start": 0.1, "end": 0.3},
                                                        {"word": " fuck", "start": 1.0, "end": 1.4},
                                                        {"word": " man", "start": 1.5, "end": 1.7}]}]
    assert CC.bip_no_clipe(base, p["id"], "M1", whisper) == 1
    assert chamadas and chamadas[0]["word_timestamps"]
    q = CT.carregar(base, p["id"])
    assert q["midias"][0]["bip_feito"]
    assert CC.bip_no_clipe(base, p["id"], "M1", whisper) == 0 and len(chamadas) == 1  # uma vez só
    cam = CT.caminho_midia(base, q, q["midias"][0])
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", cam], capture_output=True, text=True)
    assert "video" in r.stdout and "audio" in r.stdout


def test_nitidez(tmp_path):
    base = str(tmp_path)
    cam = str(tmp_path / "a.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", cam], check=True, capture_output=True)
    assert not CC.nitidez_no_arquivo(cam, "")
    assert CC.nitidez_no_arquivo(cam, "leve")
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", cam],
                       capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(","))
    assert h == 1080 and w == 1920


def test_seta_na_abertura(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "Seta", "")
    p = _p(base, c["id"])
    assert CC.REGRA_SETA_ABERTURA not in CC.sistema(p)
    p["config"]["seta_abertura"] = True
    assert CC.REGRA_SETA_ABERTURA in CC.sistema(p)


# ---------------------------------------------------------------- 📊 estilo dos concorrentes
def test_url_shorts():
    assert EC.url_shorts("https://www.youtube.com/@canal/videos?x=1") == "https://www.youtube.com/@canal/shorts"
    assert EC.url_shorts("https://youtube.com/@canal/") == "https://youtube.com/@canal/shorts"
    try:
        EC.url_shorts("https://tiktok.com/@x")
        assert False
    except ValueError:
        pass


def test_texto_do_vtt_sem_repeticao():
    vtt = ("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:01.000\nThis guy\n\n"
           "00:00:01.000 --> 00:00:02.000\nThis guy\n<00:00:01.500><c> made a mistake</c>\n\n"
           "00:00:02.000 --> 00:00:03.000\nThis guy made a mistake\n")
    t = EC.texto_do_vtt(vtt)
    assert t.count("This guy") == 1 and "made a mistake" in t


def test_aprender_e_entra_no_roteiro(tmp_path, monkeypatch):
    lista = {"entries": [{"id": f"v{k}", "title": f"Short {k}", "view_count": k * 1000} for k in range(1, 6)]}

    def rodar(args, timeout=0):
        if "--flat-playlist" in args:
            assert args[-1].endswith("/shorts")
            return SimpleNamespace(stdout=json.dumps(lista))
        if "--write-subs" in args:
            pasta = os.path.dirname(args[args.index("-o") + 1])
            vid = args[-1].rsplit("/", 1)[-1]
            with open(os.path.join(pasta, f"{vid}.en.vtt"), "w") as f:
                f.write(f"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nThis man did something wild in video {vid}, look closely\n")
        return SimpleNamespace(stdout="")
    vistos = {}

    def chamar(rec, sis, cont, **k):
        vistos["cont"] = cont
        return {"manual": "ABERTURA: 'Este <pessoa> fez <ação>'."}
    r = EC.aprender(["https://www.youtube.com/@a", "https://www.youtube.com/@a"], str(tmp_path), n=3, rodar=rodar, chamar=chamar)
    assert r["canais"] == ["https://www.youtube.com/@a"] and r["n_transcricoes"] == 3
    assert r["exemplos"][0]["titulo"] == "Short 5"  # o mais visto primeiro
    assert "Short 1" not in vistos["cont"]  # só os 3 mais vistos
    # entra no prompt do roteiro do canal
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "Conc", "")
    c["estilo_concorrentes"] = r
    CT.salvar_canal(base, c)
    p = _p(base, c["id"])
    assert "WRITING STYLE THAT WORKS" in CC.conteudo_roteiro(base, p) and "Este <pessoa>" in CC.conteudo_roteiro(base, p)
    c["estilo_concorrentes"]["desligado"] = True
    CT.salvar_canal(base, c)
    assert "WRITING STYLE THAT WORKS" not in CC.conteudo_roteiro(base, p)


def test_poucas_transcricoes_da_erro():
    try:
        EC.analisar([{"texto": "x" * 50}], chamar=lambda *a, **k: {"manual": "m"})
        assert False
    except ValueError:
        pass


def test_rota_concorrentes(tmp_path, monkeypatch):
    from test_v84_320_lote_por_etapa import _app
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    c = CT.criar_canal(base, "Rota", "")
    url = f"/curtos/canais/{c['id']}/concorrentes"
    assert cl.get(url).get_json()["concorrentes"]["manual"] == ""
    assert cl.post(url, json={"canais": ["https://tiktok.com/@x"]}).status_code == 400
    cl.post(url, json={"manual": "meu manual", "desligado": True})
    j = cl.get(url).get_json()["concorrentes"]
    assert j["manual"] == "meu manual" and j["desligado"]
    assert 'id="concBox"' in cl.get("/curtos/link").get_data(as_text=True)
    canais = cl.get("/curtos/canais-link").get_json()["canais"]
    assert next(x for x in canais if x["id"] == c["id"])["concorrentes"]["manual"] == "meu manual"
