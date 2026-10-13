"""v84_82 — 🐟 Fish Audio S2 como motor de voz (clonagem + tags de emoção), testado contra um servidor Fish SIMULADO."""
import os
import sys
import time
import wave

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import fish_simulado as fs  # noqa: E402
from tts import voice_generator as vg  # noqa: E402


@pytest.fixture
def servidor():
    url, pedidos, parar = fs.iniciar()
    yield url, pedidos
    parar()


def _dur(p):
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()


def test_gera_em_pedacos_com_tags_referencia_e_mesma_seed(servidor, tmp_path):
    url, pedidos = servidor
    ref = tmp_path / "ref.wav"
    ref.write_bytes(fs._wav(4))
    (tmp_path / "ref.wav.txt").write_text("Olá, essa é a minha voz.", encoding="utf-8")
    texto = "[excited] Você não vai acreditar no que aconteceu! " * 12 + "[whisper] É segredo."
    out = str(tmp_path / "o.wav")
    vg.gerar_audio("fish_s2", texto, out, speaker_wav=str(ref), modo="local", url=url)
    assert len(pedidos) >= 2 and all(len(p["corpo"]["text"]) <= vg.FISH_LIMITE_CARACTERES_POR_CHAMADA for p in pedidos)
    assert "[excited]" in pedidos[0]["corpo"]["text"] and "[whisper]" in pedidos[-1]["corpo"]["text"]
    assert pedidos[0]["tipo"] == "application/msgpack" and pedidos[0]["modelo"] is None  # local: sem cabeçalho "model"
    r = pedidos[0]["corpo"]["references"][0]
    assert r["text"] == "Olá, essa é a minha voz." and len(r["audio"]) > 1000
    assert len({p["corpo"]["seed"] for p in pedidos}) == 1  # a mesma voz do começo ao fim
    assert _dur(out) > 1


def test_velocidade_local_no_ffmpeg_e_nuvem_com_chave_modelo_e_prosody(tmp_path):
    url, pedidos, parar = fs.iniciar(chave="segredo123")
    try:
        lento = str(tmp_path / "l.wav")
        normal = str(tmp_path / "n.wav")
        vg.fish_s2_synthesize("Um texto curto pra medir.", normal, modo="local", url=url, api_key="segredo123")
        vg.fish_s2_synthesize("Um texto curto pra medir.", lento, modo="local", url=url, api_key="segredo123", velocidade=0.5)
        assert _dur(lento) > _dur(normal) * 1.7
        vg.fish_s2_synthesize("Oi [laughing] tudo bem?", str(tmp_path / "c.wav"), modo="nuvem", url=url,
                              api_key="segredo123", modelo="s2.1-pro", velocidade=1.3, reference_id="abc123")
        p = pedidos[-1]
        assert p["modelo"] == "s2.1-pro" and p["corpo"]["prosody"]["speed"] == 1.3 and p["corpo"]["reference_id"] == "abc123"
        with pytest.raises(vg.VoiceGeneratorError, match="401"):
            vg.fish_s2_synthesize("x y", str(tmp_path / "e.wav"), modo="local", url=url, api_key="errada")
    finally:
        parar()


def test_servidor_fora_do_ar_explica_como_subir(tmp_path):
    with pytest.raises(vg.VoiceGeneratorError, match="api_server.py"):
        vg.fish_s2_synthesize("Olá", str(tmp_path / "o.wav"), modo="local", url="http://127.0.0.1:9")
    st = vg.fish_status(modo="local", url="http://127.0.0.1:9", timeout=1)
    assert st["ok"] is False and "fish-speech" in st["msg"]
    assert vg.fish_status(modo="nuvem", api_key="")["ok"] is False


def test_perfil_de_voz_transcreve_uma_vez_e_guarda(servidor, tmp_path, monkeypatch):
    url, pedidos = servidor
    clipe = tmp_path / "c1.wav"
    clipe.write_bytes(fs._wav(3))
    monkeypatch.setattr(vg, "caminho_perfil_de_voz", lambda nome: [str(clipe)])
    chamadas = []
    import types
    falso = types.ModuleType("whisper_transcribe")
    falso.transcribe_audio = lambda a, language=None: chamadas.append(a) or [{"text": " Bom dia "}, {"text": "a todos."}]
    monkeypatch.setitem(sys.modules, "whisper_transcribe", falso)
    for _ in range(2):
        vg.fish_s2_synthesize("Teste.", str(tmp_path / "o.wav"), voice_profile="joao", modo="local", url=url)
    assert pedidos[-1]["corpo"]["references"][0]["text"] == "Bom dia a todos." and len(chamadas) == 1
    assert (tmp_path / "c1.wav.txt").read_text(encoding="utf-8") == "Bom dia a todos."


def test_limpeza_mantem_tags_livres_so_no_fish():
    import narracoes as na
    t = '[excited] Olá, "pessoal"! [whisper in small voice] É segredo [3].'
    fish = na.limpar_texto_para_tts(t, motor="fish_s2")
    assert "[excited]" in fish and "[whisper in small voice]" in fish and "[3]" not in fish and '"' not in fish
    piper = na.limpar_texto_para_tts(t, motor="piper")
    assert "[" not in piper
    assert na.motor_aceita_tags("fish_s2") and na.motor_aceita_tags("chatterbox_turbo") and not na.motor_aceita_tags("kokoro")


def test_multivoz_nao_confunde_tag_de_emocao_com_voz():
    import multivoz as mv
    vozes = {"ricardo": {"slug": "ricardo", "nome": "Ricardo", "motor": "fish_s2", "config": {}}}
    d = mv.dividir("[ricardo] [excited] Olá! [rindo baixinho] Que bom. [fulano] tchau", vozes)
    assert d["desconhecidas"] == ["fulano"]
    assert "[excited]" in d["falas"][0]["texto"] and "[rindo baixinho]" in d["falas"][0]["texto"]


def test_config_do_projeto_e_da_conversa_viram_kwargs():
    import conversa
    import narracoes as na
    kw = na._kwargs_motor(dict(na.CONFIG_PADRAO, motor="fish_s2", vozPerfil="joao", fishTemperatura=0.6, velocidade=1.1))
    assert kw == {"idioma": "pt", "velocidade": 1.1, "temperatura": 0.6, "voice_profile": "joao"}
    kw = na._kwargs_motor(dict(na.CONFIG_PADRAO, motor="fish_s2", fishReferenceId="abc"))
    assert kw["reference_id"] == "abc" and "voice_profile" not in kw
    assert "fish_s2" in na.MOTORES_VALIDOS and "fish_s2" in conversa.MOTORES_VALIDOS


@pytest.fixture
def A(tmp_path, monkeypatch):
    import app as _app
    import site_config
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    monkeypatch.setattr(_app, "VOZES_DIR", str(tmp_path))
    return _app


def test_tela_status_e_geracao_pelo_site(A, servidor, tmp_path, monkeypatch):
    url, pedidos = servidor
    import site_config
    site_config.save_site_config({"fish_url": url, "fish_api_key": "chave-secreta-9999"})
    c = A.app.test_client()
    html = c.get("/gerar-voz").get_data(as_text=True)
    assert 'id="opcoes-fish_s2"' in html and "[excited]" in html and "Fish Audio S2" in html
    st = c.get("/gerar-voz/fish/status").get_json()
    assert st["ok"] and st["modo"] == "local" and "chave-secreta" not in str(st)
    assert "chave-secreta-9999" not in c.get("/settings").get_data(as_text=True)
    # gera de verdade (no mesmo processo, contra o servidor simulado)
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", lambda motor, texto, out, **kw: vg.gerar_audio(motor, texto, out, **kw))
    r = c.post("/gerar-voz/gerar", data={"texto": "[excited] Olá, pessoal! Tudo bem?", "engine": "fish_s2",
                                         "fish_idioma": "pt", "fish_temperatura": "0.65", "fish_reference_id": "voz<script>1"})
    jid = r.get_json()["job_id"]
    for _ in range(300):
        d = c.get(f"/gerar-voz/status/{jid}").get_json()
        if d["pronto"]:
            break
        time.sleep(0.1)
    assert d["erro"] is None, d["log"]
    p = pedidos[-1]["corpo"]
    assert p["text"].startswith("[excited] Olá") and p["temperature"] == 0.65 and p["reference_id"] == "vozscript1"
