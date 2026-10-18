"""v84_180 — 🏭 Produção no pod com VÁRIAS vozes: [narrador]/[mira|curiosa]/[vanta] viram UM texto pro pod com
{{perfil=…, emocao=…, cfg=…}} antes de cada fala (o pod troca a voz e a emoção e devolve um áudio só, transcrito);
os perfis vão pro pod uma vez por lote; a legenda é o roteiro sem as tags (com as chamadas)."""
import math
import os
import struct
import wave

import pytest

import multivoz as mv
import perfis_info
import perfis_limpeza as pl
import producao_pod as pp


def _wav(c):
    with wave.open(c, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(k / 9))) for k in range(22050)))
    return c


@pytest.fixture
def vozes(tmp_path, monkeypatch):
    vg = pl._vg()
    monkeypatch.setattr(vg, "VOICE_PROFILES_DIR", str(tmp_path / "perfis"))
    monkeypatch.setattr(perfis_info, "ARQUIVO", str(tmp_path / "pi.json"))
    monkeypatch.setattr(mv, "ARQUIVO", str(tmp_path / "vm.json"))
    for n in ("Narr", "Mariana"):
        vg.salvar_perfil_de_voz(n, [_wav(str(tmp_path / f"{n}.wav"))])
    mv.salvar({"nome": "N", "slug": "narr", "motor": "chatterbox", "config": {"vozPerfil": "Narr", "chatterboxExaggeration": 0.4}})
    mv.salvar({"nome": "Mira", "slug": "mira_v", "motor": "chatterbox", "config": {"vozPerfil": "Mariana"}})
    mv.salvar({"nome": "Piper", "slug": "pip", "motor": "piper", "config": {"voz": "x"}})
    return vg


IT = {"idioma": "de", "motor": "chatterbox", "perfil": "", "exaggeration": 0.5, "cfg_weight": 0.5}


def test_texto_do_pod(vozes):
    t = "[narr] Im Jahr 1054 erschien ein Gaststern.\n\n[[INSCREVA]]\n\n[mira_v|exag=0.6|cfg=0.45] Wie geht das?\n[narr] So."
    m = pp.multivoz_para_pod(t, IT)
    assert m["perfis"] == ["Narr", "Mariana"]
    assert m["texto"].startswith("{{perfil=Narr, emocao=0.40, cfg=0.50}} Im Jahr 1054")
    assert "{{perfil=Mariana, emocao=0.60, cfg=0.45}} Wie geht das?" in m["texto"]
    assert "[[INSCREVA]]" in m["legenda"] and "[narr]" not in m["legenda"] and "[mira_v" not in m["legenda"]
    assert pp.multivoz_para_pod("Ein Text ohne Tags, nur eine Stimme.", IT) is None
    with pytest.raises(pp.ProducaoErro, match="só roda Chatterbox"):
        pp.multivoz_para_pod("[pip] Hallo du da draußen.", IT)


def test_perfis_uma_vez_por_lote(vozes, monkeypatch):
    import pod_studio
    mandados = []
    monkeypatch.setattr(pod_studio, "importar_perfis", lambda z, cfg=None: mandados.append(len(z)))
    pp._PERFIS_ENVIADOS.pop("Lx", None)
    pp._mandar_perfis(["Narr", "Mariana"], {}, "Lx")
    pp._mandar_perfis(["Narr"], {}, "Lx")
    pp._mandar_perfis(["Narr", "Mariana"], {}, "Lx")
    assert len(mandados) == 1


def test_enviar_narracao_multivoz(vozes, monkeypatch):
    import pod_studio
    pedidos = []
    monkeypatch.setattr(pod_studio, "importar_perfis", lambda z, cfg=None: None)
    monkeypatch.setattr(pod_studio, "enviar_narracao", lambda texto, **k: pedidos.append((texto, k)) or "job1")
    mudou = {}
    monkeypatch.setattr(pp, "_mudar", lambda lid, iid, **m: mudou.update(m))
    it = dict(IT, id="i1", origem="texto", texto="[narr] Eins zwei drei vier fünf. [mira_v] Sechs sieben acht neun?")
    pp._enviar_narracao({"id": "L2"}, it, {})
    texto, k = pedidos[0]
    assert k["marcacoes"] is True and k["referencia"] is None and texto.count("{{perfil=") == 2
    assert mudou["pod_voz"] == "job1" and "[narr]" not in mudou["texto_legenda"]
