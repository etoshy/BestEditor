"""🎭 Multi voice: [slug] no texto troca a voz (Gerador de voz e Roteiro para Áudio)."""
import json
import os
import subprocess
import sys
import time

import pytest

import multivoz as mv


@pytest.fixture(autouse=True)
def arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "ARQUIVO", str(tmp_path / "vozes.json"))
    mv.salvar({"nome": "Ricardo", "motor": "piper", "config": {"voz": "pt_BR-faber-medium", "velocidade": 1.1}})
    mv.salvar({"nome": "Ana Clara", "motor": "kokoro", "config": {"voz": "pf_dora"}})
    yield


def _freq(motor, kwargs):
    return {"piper": 300, "kokoro": 600}.get(motor, 900) if not kwargs.get("voz") == "pm_alex" else 1200


def fake_gerar(chamadas):
    def g(motor, texto, saida, **kw):
        chamadas.append((motor, texto, kw.get("voz") or kw.get("nome_voz")))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f={_freq(motor, kw)}:d=0.5", "-ar", "22050", saida], check=True)
    return g


class TestTexto:
    def test_slug_e_cadastro(self):
        assert mv.slugify("Ana Clara") == "ana_clara" and mv.slugify("Joãozinho!") == "joaozinho"
        assert [v["slug"] for v in mv.listar()] == ["ricardo", "ana_clara"]
        with pytest.raises(mv.MultiVozError):
            mv.salvar({"nome": "Outro", "slug": "ricardo", "motor": "piper"})
        with pytest.raises(mv.MultiVozError):
            mv.salvar({"nome": "", "motor": "piper"})
        v = mv.salvar({"nome": "Ricardo Novo", "slug": "ricardo", "motor": "xtts", "config": {"vozPerfil": "meu"}}, slug_antigo="ricardo")
        assert v["motor"] == "xtts" and len(mv.listar()) == 2
        assert mv.kwargs_da_voz(v)[1]["voice_profile"] == "meu"
        assert mv.apagar("ana_clara") and not mv.apagar("ana_clara")

    def test_dividir(self):
        d = mv.dividir("Intro sem tag. [Ricardo] Oi, tudo bem? [ana clara]: Tudo! [RICARDO] Que bom. [ricardo] mesmo.")
        assert [(f["slug"], f["texto"]) for f in d["falas"]] == [
            (None, "Intro sem tag."), ("ricardo", "Oi, tudo bem?"), ("ana_clara", "Tudo!"), ("ricardo", "Que bom. mesmo.")]
        assert d["desconhecidas"] == [] and d["usadas"] == ["ricardo", "ana_clara"] and d["ultima"] == "ricardo"
        d = mv.dividir("[maria] Olá [laugh] haha [ricardo] oi")
        assert d["desconhecidas"] == ["maria"]
        assert "[laugh]" in d["falas"][0]["texto"]  # tag do Chatterbox Turbo continua no texto
        assert mv.dividir("continua", voz_inicial="ana_clara")["falas"][0]["slug"] == "ana_clara"
        assert "[ricardo]" in mv.instrucao_para_ia()

    def test_gerar_troca_vozes_e_nao_le_a_tag(self, tmp_path):
        ch = []
        r = mv.gerar("Abertura. [ricardo] Fala do Ricardo. [ana_clara] Fala da Ana.", str(tmp_path / "o.wav"), "piper", {"nome_voz": "pt_BR-x"},
                     fake_gerar(ch), lambda t, turbo: t)
        assert r == {"falas": 3, "vozes": ["ricardo", "ana_clara"]}
        assert [c[0] for c in ch] == ["piper", "piper", "kokoro"] and all("[" not in c[1] for c in ch)
        assert ch[1][2] == "pt_BR-faber-medium" and ch[2][2] == "pf_dora"
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(tmp_path / "o.wav")],
                                   capture_output=True, text=True).stdout)
        assert 2.0 < dur < 2.4  # 3 × 0,5 s + 2 pausas de troca
        with pytest.raises(mv.MultiVozError):
            mv.gerar("[maria] oi", str(tmp_path / "x.wav"), "piper", {}, fake_gerar([]), lambda t, turbo: t)


@pytest.fixture
def A(monkeypatch):
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


class TestApp:
    def test_rotas(self, A, monkeypatch):
        c = A.app.test_client()
        r = c.post("/gerar-voz/vozes", data={"engine": "kokoro", "kokoro_voz": "pm_alex", "velocidade": "0.9", "mv_nome": "Narrador"}).get_json()
        assert r["ok"] and r["voz"]["slug"] == "narrador" and r["voz"]["config"]["voz"] == "pm_alex" and r["voz"]["config"]["velocidade"] == 0.9
        assert "[narrador]" in r["instrucao_ia"]
        assert c.post("/gerar-voz/vozes", data={"engine": "piper", "mv_nome": ""}).status_code == 400
        conf = c.post("/gerar-voz/vozes/conferir", json={"texto": "[narrador] Era uma vez. [ricardo] Oi! [zé] e aí"}).get_json()
        assert [f["nome"] for f in conf["falas"]] == ["Narrador", "Ricardo"] and conf["desconhecidas"] == ["zé"]
        assert "mv-ativo" in c.get("/gerar-voz").get_data(as_text=True)
        # gerar com tag desconhecida: recusa antes de começar
        assert c.post("/gerar-voz/gerar", data={"texto": "[zé] oi", "engine": "piper", "multivoz": "on"}).status_code == 400
        ch = []
        monkeypatch.setattr(A, "tts_gerar_audio_isolado", fake_gerar(ch))
        monkeypatch.setattr(A, "transcribe_audio", lambda *a, **k: [])
        j = c.post("/gerar-voz/gerar", data={"texto": "Sem tag. [narrador] Era uma vez. [ricardo] Oi!", "engine": "piper", "piper_voz": "pt_BR-y", "multivoz": "on"}).get_json()
        for _ in range(100):
            st = c.get(f"/gerar-voz/status/{j['job_id']}").get_json()
            if not st["running"]:
                break
            time.sleep(0.1)
        assert st["resultado"] and not st["erro"], st
        assert [x[2] for x in ch] == ["pt_BR-y", "pm_alex", "pt_BR-faber-medium"]
        # sem o modo, o texto vai inteiro (com as tags limpas como pontuação) pra uma voz só
        ch.clear()
        j = c.post("/gerar-voz/gerar", data={"texto": "[ricardo] Oi!", "engine": "piper"}).get_json()
        for _ in range(100):
            if not c.get(f"/gerar-voz/status/{j['job_id']}").get_json()["running"]:
                break
            time.sleep(0.1)
        assert len(ch) == 1
        assert c.post("/gerar-voz/vozes/narrador/excluir").get_json()["ok"]

    def test_roteiro_para_audio_multivoz(self, A, monkeypatch, tmp_path):
        import narracoes as na
        sys.modules.setdefault("tts", __import__("tts"))
        ch = []
        import tts.voice_generator as vg
        monkeypatch.setattr(vg, "gerar_audio_isolado", fake_gerar(ch))
        p = na.criar_projeto(str(tmp_path), "teste")
        pid = p["projetoId"]
        na.importar_roteiro(str(tmp_path), pid, "[ricardo] Primeira fala.\nContinua o Ricardo.\n[ana_clara] Agora a Ana. [ricardo] E ele de novo.")
        na.salvar_config(str(tmp_path), pid, motor="piper", voz="pt_BR-z", multi_voz=True)
        g = na.gerar_audio_projeto(str(tmp_path), pid)
        assert [c[2] for c in ch] == ["pt_BR-faber-medium", "pt_BR-faber-medium", "pf_dora", "pt_BR-faber-medium"]
        assert all("[" not in c[1] for c in ch) and g
        na.importar_roteiro(str(tmp_path), pid, "[desconhecido] oi")
        with pytest.raises(na.NarracaoError):
            na.gerar_audio_projeto(str(tmp_path), pid)
