"""v84_372: 🎭 Chatterbox pt-BR expressivo — tags em português montadas em pedaços."""
import os
import subprocess
import sys
import wave

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import expressivo as E  # noqa: E402
from tts import voice_generator as vg  # noqa: E402


def _tom(caminho, segundos=0.5, taxa=24000):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
                    "-ar", str(taxa), "-ac", "1", str(caminho)], check=True)
    return str(caminho)


def _dur(caminho):
    with wave.open(str(caminho), "rb") as w:
        return w.getnframes() / w.getframerate()


def test_classifica_tags_pt():
    assert E.classificar_tag("Soprosa")["estilo"] == "soprosa"
    assert E.classificar_tag("dramático")["estilo"] == "dramatica"
    assert E.classificar_tag("soprosa-dramatica")["estilo"] == "dramatica"
    assert E.classificar_tag("risada") == {"tipo": "som", "som": "laugh"}
    assert E.classificar_tag("pigarro")["som"] == "clear throat"
    assert E.classificar_tag("laugh")["som"] == "laugh"  # nome em inglês também vale
    assert E.classificar_tag("pausa 1,5")["s"] == 1.5
    assert E.classificar_tag("pausa longa")["s"] == 1.0
    assert E.classificar_tag("velocidade 3")["valor"] == 1.6  # limitado
    assert E.classificar_tag("respira")["tipo"] == "respira"
    assert E.classificar_tag("nota do editor") is None  # colchete comum: não é tag


def test_eventos_estilo_sons_pausas_e_paragrafo():
    ev = E.montar_eventos("[soprosa] Era uma vez um homem. [suspiro] Ele sumiu.\n\n[projetada] Compre já, compre agora!", sons="turbo")
    tipos = [e["tipo"] for e in ev]
    assert tipos == ["fala", "som", "fala", "pausa", "fala"]
    assert ev[0]["estilo"] == "soprosa" and ev[0]["emocao"] == E.ESTILOS["soprosa"][0]
    assert ev[1]["som"] == "sigh"
    assert ev[3]["s"] == E.PAUSA_PARAGRAFO
    assert ev[4]["estilo"] == "projetada" and ev[4]["velocidade"] > 1


def test_normal_volta_pro_que_esta_na_tela():
    ev = E.montar_eventos("[dramatica] Frase dramática aqui. [normal] Frase normal aqui.", emocao_base=0.62, cfg_base=0.41)
    assert ev[1]["emocao"] == 0.62 and ev[1]["cfg"] == 0.41


def test_enfase_nao_divide_a_frase():
    ev = E.montar_eventos("Ele chegou cedo. A partir de hoje, só *produtos orgânicos*. São caros.")
    assert [e["texto"] for e in ev] == ["Ele chegou cedo.", "A partir de hoje, só, produtos orgânicos.", "São caros."]
    assert ev[1]["emocao"] == pytest.approx(0.5 + E.EXTRA_EMOCAO_ENFASE) and ev[0]["emocao"] == 0.5
    ev = E.montar_eventos("E aquela noite... mudou *tudo*.")  # reticências não são fim de frase
    assert [e["texto"] for e in ev] == ["E aquela noite... mudou, tudo."]


def test_sons_falados_ficam_na_mesma_frase():
    ev = E.montar_eventos("Recebeu um sonoro não. [risada] Foi embora. [respira] Depois voltou.", sons="falado")
    assert ev[0]["texto"] == "Recebeu um sonoro não. Ha ha ha! Foi embora."
    assert [e["tipo"] for e in ev] == ["fala", "respira", "fala"]  # respiração continua pelo Turbo


def test_whisper_corta_ruido_antes_e_depois_da_frase(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(vg, "chatterbox_synthesize", lambda t, s, **k: _com_silencio(s, 1.0, 0.5, 1.0))
    monkeypatch.setattr(E, "limites_falados", lambda c, i="pt": (0.9, 1.3))  # palavras: 0,9 a 1,3 s
    saida = tmp_path / "o.wav"
    E.sintetizar(vg, "Uma frase qualquer aqui.", str(saida))
    assert len(E._carregar(str(saida))) / 24000 <= 0.15 + 0.4 + 0.3 + 0.01
    x = np.zeros(24000 * 3, np.float32)
    assert len(E.recortar(x, (1.0, 2.0))) == pytest.approx(1.45 * 24000, abs=2)
    assert len(E.recortar(x, None)) == len(x)


def test_texto_sem_tags_pra_legenda():
    t = "[soprosa] Olá [risada] mundo *lindo*. [nota] fica.\n\n[pausa 2] Fim."
    assert E.texto_sem_tags(t) == "Olá mundo lindo. [nota] fica.\n\nFim."
    assert E.tem_tags(t) and not E.tem_tags("texto [nota] normal")


def test_texto_de_teste_usa_tudo():
    ev = E.montar_eventos(E.TEXTO_TESTE, sons="turbo")
    assert {"fala", "som", "respira", "pausa"} <= {e["tipo"] for e in ev}
    assert len({e.get("estilo") for e in ev if e["tipo"] == "fala"}) >= 8
    assert "[" not in E.texto_sem_tags(E.TEXTO_TESTE)


def test_pt_pt_tags_ajuda_e_texto():
    assert E.classificar_tag("fungadela")["som"] == "sniff" and E.classificar_tag("chiu")["som"] == "shush"
    assert E.classificar_tag("irónica")["estilo"] == "ironica" and E.classificar_tag("projectada")["estilo"] == "projetada"
    assert E.classificar_tag("cúmplice")["estilo"] == "camarada" and E.classificar_tag("respirar")["tipo"] == "respira"
    for var in ("pt-BR", "pt-PT"):  # toda tag da ajuda é reconhecida
        for _, itens in E.AJUDA[var]:
            for tag, explicacao in itens:
                assert explicacao
                if tag.startswith("["):
                    assert E.classificar_tag(tag[1:-1]), (var, tag)
        ev = E.montar_eventos(E.TEXTOS_TESTE[var], sons="turbo")
        assert {"fala", "som", "respira", "pausa"} <= {e["tipo"] for e in ev}


def test_pt_pt_no_pod_usa_o_modelo_base(monkeypatch, tmp_path):
    import pod_studio
    pedido = {}
    monkeypatch.setattr(vg, "_no_pod", lambda motor: True)
    monkeypatch.setattr(pod_studio, "narrar", lambda *a, **k: pedido.update(k))
    vg.chatterbox_synthesize("Olá, isto é um teste.", str(tmp_path / "a.wav"), idioma="pt", variante="pt-PT")
    assert pedido["pacote_dedicado"] is False
    pedido.clear()
    vg.chatterbox_synthesize("Olá, isso é um teste.", str(tmp_path / "b.wav"), idioma="pt", variante="pt-BR")
    assert "pacote_dedicado" not in pedido  # pt-BR: o que estiver nas configurações


def test_sintetizar_monta_o_audio_com_turbo_e_referencia_do_estilo(tmp_path, monkeypatch):
    chamadas = []

    def falso_mtl(texto, saida, **kw):
        chamadas.append(("mtl", texto, kw))
        return _tom(saida, 0.5)

    def falso_turbo(texto, saida, **kw):
        chamadas.append(("turbo", texto, kw))
        return _tom(saida, 0.4, taxa=22050)  # taxa diferente: tem que ser convertida

    monkeypatch.setattr(vg, "chatterbox_synthesize", falso_mtl)
    monkeypatch.setattr(vg, "chatterbox_turbo_synthesize", falso_turbo)
    monkeypatch.setattr(vg, "listar_perfis_de_voz", lambda: ["minhavoz", "minhavoz_soprosa"])
    saida = tmp_path / "out.wav"
    E.sintetizar(vg, "[soprosa] Primeira frase bem longa aqui. [risada] [risada] [normal] Segunda frase normal. [pausa 1]"
                     " Terceira frase com [respira] respiração.", str(saida), voice_profile="minhavoz", sons="turbo")
    mtl = [c for c in chamadas if c[0] == "mtl"]
    turbo = [c for c in chamadas if c[0] == "turbo"]
    assert mtl[0][2]["voice_profile"] == "minhavoz_soprosa"  # estilo com perfil próprio
    assert mtl[1][2]["voice_profile"] == "minhavoz"
    assert [t[1] for t in turbo] == ["[laugh]", "[gasp]"]  # risada repetida usa o cache
    assert all(t[2]["voice_profile"] == "minhavoz" for t in turbo)
    with wave.open(str(saida), "rb") as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1
    assert _dur(saida) > 1.5 + 1.0  # 3 falas + pausa de 1 s + sons
    assert not list(tmp_path.glob("_expressivo_*"))  # temporários apagados


def test_sem_turbo_o_som_vira_pausa(tmp_path, monkeypatch):
    monkeypatch.setattr(vg, "chatterbox_synthesize", lambda t, s, **k: _tom(s, 0.5))

    def quebra(*a, **k):
        raise vg.VoiceGeneratorError("Turbo não instalado")
    monkeypatch.setattr(vg, "chatterbox_turbo_synthesize", quebra)
    avisos = []
    E.sintetizar(vg, "Frase de abertura do teste. [tosse] Frase final do teste.", str(tmp_path / "o.wav"), on_log=avisos.append,
                 sons="turbo")
    assert avisos and "virou pausa" in avisos[0]
    assert _dur(tmp_path / "o.wav") == pytest.approx(1.35, abs=0.05)


def test_chatterbox_synthesize_desvia_pro_expressivo(tmp_path, monkeypatch):
    usado = {}
    monkeypatch.setattr(E, "sintetizar", lambda vg_, texto, saida, **kw: usado.update(texto=texto, kw=kw) or saida)
    vg.chatterbox_synthesize("[soprosa] Olá *mundo*", str(tmp_path / "a.wav"), expressivo=True, exaggeration=0.7)
    assert usado["texto"] == "[soprosa] Olá *mundo*" and usado["kw"]["exaggeration"] == 0.7


def test_rota_gerar_voz_manda_expressivo_e_texto_cru(monkeypatch):
    import app as A
    recebido = {}

    def falso(engine, texto, saida, **kw):
        recebido.update(engine=engine, texto=texto, kw=kw)
        _tom(saida, 0.3)
        return saida
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", falso)
    monkeypatch.setattr(A, "transcribe_audio", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem whisper")), raising=False)
    c = A.app.test_client()
    pagina = c.get("/gerar-voz").get_data(as_text=True)
    assert "Modo expressivo" in pagina and "Português de Portugal" in pagina and "[fungadela]" in pagina
    assert "puxar o ar de susto" in pagina
    r = c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "[soprosa] Olá *mundo* [risada] tudo bem?",
                                         "chatterbox_idioma": "pt", "chatterbox_expressivo": "on", "chatterbox_variante": "pt-PT"})
    assert r.status_code == 200, r.get_data(as_text=True)
    import time
    for _ in range(100):
        if recebido:
            break
        time.sleep(0.05)
    assert recebido["engine"] == "chatterbox" and recebido["kw"].get("expressivo") is True
    assert recebido["kw"].get("variante") == "pt-PT"
    assert recebido["texto"] == "[soprosa] Olá *mundo* [risada] tudo bem?"  # sem a limpeza que tira colchetes


def _com_silencio(caminho, antes=0.8, tom=0.5, depois=0.9, volume=1.0):
    """Tom com silêncio nas pontas, como o Chatterbox devolve."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={antes}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={tom}", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={depois}",
                    "-filter_complex", f"[1]volume={volume}[t];[0][t][2]concat=n=3:v=0:a=1", "-ar", "24000", "-ac", "1", str(caminho)], check=True)
    return str(caminho)


def test_apara_pontas_nivela_sons_e_nao_clipa(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(vg, "chatterbox_synthesize", lambda t, s, **k: _com_silencio(s, volume=1.6))  # passa de 0 dBFS
    monkeypatch.setattr(vg, "chatterbox_turbo_synthesize", lambda t, s, **k: _com_silencio(s, 0.3, 0.4, 0.5, volume=0.05))
    monkeypatch.setattr(E, "parece_chiado", lambda x: False)  # o tom de teste é contínuo de propósito
    saida = tmp_path / "o.wav"
    E.sintetizar(vg, "Primeira frase do teste aqui. [pausa curta] Segunda frase do teste aqui. [risada]", str(saida), sons="turbo")
    x = E._carregar(str(saida))
    # 2 falas de 0,5 s + pausa 0,25 + som 0,4 + margens (fala 0,16; som 0,24 + 0,2 de folga) — sem os ~1,7 s de
    # silêncio que cada pedaço trazia
    assert len(x) / 24000 == pytest.approx(2 * 0.66 + 0.25 + 0.08 + 0.64 + 0.12, abs=0.08)
    assert 20 * np.log10(np.abs(x).max()) <= -1.4  # sem clip
    pausa = x[int(24000 * 0.70):int(24000 * 0.88)]
    assert 0 < np.sqrt(np.mean(pausa ** 2)) < 10 ** (-60 / 20)  # pausa tem "ar" bem baixinho, não zero digital
    fala, som = E.nivel_voz(x[: 24000 // 2]), E.nivel_voz(x[-int(24000 * 0.5):])
    assert 20 * np.log10(fala / som) == pytest.approx(E.SOM_DB_ABAIXO_DA_FALA, abs=2.0)  # som nivelado pela fala


def test_aparar_limiar_relativo_nao_come_som_baixo():
    import numpy as np
    t = np.arange(int(24000 * 0.5)) / 24000
    baixo = (0.003 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)  # ~ -53 dBFS: o limiar fixo de -42 dB apagava
    x = np.concatenate([np.zeros(12000, np.float32), baixo, np.zeros(12000, np.float32)])
    y = E.aparar(x, abaixo_do_pico_db=45, piso_db=-65)
    assert 0.5 <= len(y) / 24000 <= 0.75


def test_turbo_chiado_tenta_de_novo_e_depois_vira_pausa(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(vg, "chatterbox_synthesize", lambda t, s, **k: _tom(s, 0.5))
    tentativas = []

    def chiado(t, s, **k):  # ruído contínuo de 1,5 s, como a [risadinha] do teste real
        tentativas.append(t)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=1.5:a=0.03:r=24000", "-ac", "1", s], check=True)
        return s
    monkeypatch.setattr(vg, "chatterbox_turbo_synthesize", chiado)
    avisos = []
    E.sintetizar(vg, "Frase de abertura do teste. [risadinha] Frase final do teste.", str(tmp_path / "o.wav"),
                 sons="turbo", on_log=avisos.append)
    assert len(tentativas) == 2 and "chiado" in avisos[0]
    t = np.arange(24000) / 24000
    rajadas = (np.sin(2 * np.pi * 300 * t) * (np.sin(2 * np.pi * 4 * t) > 0)).astype(np.float32) * 0.3
    assert E.parece_chiado(rajadas) is False


def test_padrao_e_sons_falados():
    assert E.montar_eventos("Recebeu um não. [risada]")[0]["texto"] == "Recebeu um não. Ha ha ha!"


def test_normaliza_pra_16_lufs_sem_passar_do_pico():
    import numpy as np
    t = np.arange(24000 * 4) / 24000
    voz = (0.06 * np.sin(2 * np.pi * 220 * t) * (1 + np.sin(2 * np.pi * 3 * t))).astype(np.float32)  # baixa (~-26 LUFS)
    y = E.normalizar(voz)
    assert E.medir_lufs(y) == pytest.approx(E.LOUDNESS_ALVO, abs=1.0)
    assert 20 * np.log10(np.abs(y).max()) <= E.PICO_MAX_DB + 0.1 and len(y) == len(voz)
    assert E.ESTILOS["camarada"][2] < 1.0
