"""v84_400: 🎯 juiz de áudio local (CLAP) + 🔊 checagem de volume/estouro + 📣 MyInstants como reserva."""
import json
import os
import subprocess

import numpy as np

import audio_juiz as AJ
import audio_qualidade as AQ
import myinstants_sons as MI
import sound_design as SD


def _gerar(caminho, filtro_src, extra=None, dur=3):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filtro_src.format(d=dur)] + (extra or [])
                   + ["-ar", "48000", "-ac", "1", caminho], check=True)
    return caminho


def test_estourado_e_normalizar(tmp_path):
    limpo = _gerar(str(tmp_path / "limpo.wav"), "sine=f=440:d={d}", ["-af", "volume=0.3"])
    estourado = _gerar(str(tmp_path / "meme.wav"), "sine=f=440:d={d}", ["-af", "volume=25"])  # saturado: onda cortada no teto
    q1, q2 = AQ.avaliar(limpo), AQ.avaliar(estourado)
    assert q1["ok"] and not q1["estourado"] and -40 < q1["lufs"] < 0
    assert q2["estourado"] and not q2["ok"] and "estourado" in q2["motivo"]
    out = AQ.normalizar(limpo, str(tmp_path / "n.m4a"))
    assert abs(AQ.loudness(out)["lufs"] - AQ.LUFS_REFERENCIA) < 2.5
    mudo = _gerar(str(tmp_path / "mudo.wav"), "anullsrc=d={d}")
    assert AQ.avaliar(mudo)["baixo"]


class _FalsoCLAP:
    """'Ouve' pela frequência dominante: grave = triste/drone, agudo = alegre (pra testar a lógica sem o modelo)."""
    nome, escala = "falso", 30.0
    VOC = {"sad": np.array([1, 0, 0, 0.0]), "happy": np.array([0, 1, 0, 0.0]), "drone": np.array([1, 0, 0.3, 0.0]),
           "speech": np.array([0, 0, 0, 1.0])}

    def codificar_audio(self, audios):
        out = []
        for x in audios:
            f = np.abs(np.fft.rfft(x[:48000]))
            pico = np.argmax(f) * (48000 / max(2, len(x[:48000])))
            v = np.array([1, 0, 0.2, 0.0]) if pico < 300 else np.array([0, 1, 0, 0.0])
            out.append(v / np.linalg.norm(v))
        return np.stack(out)

    def codificar_texto(self, textos):
        out = []
        for t in textos:
            v = sum((vec for k, vec in self.VOC.items() if k in t.lower()), np.zeros(4)) + 0.01
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def test_ouvido_da_nota_e_soa_como(tmp_path):
    grave = _gerar(str(tmp_path / "g.wav"), "sine=f=110:d={d}")
    agudo = _gerar(str(tmp_path / "a.wav"), "sine=f=1200:d={d}")
    o = AJ.Ouvido(_FalsoCLAP(), str(tmp_path / "cache.json"))
    n1 = o.nota(grave, "sad piano, sad melancholic music", ["happy upbeat cheerful playful music"])
    n2 = o.nota(agudo, "sad piano, sad melancholic music", ["happy upbeat cheerful playful music"])
    assert n1["nota"] > 80 and n2["nota"] < 20 and n2["vence"].startswith("happy")
    assert "sad melancholic music" in n1["soa_como"]
    o.salvar()
    assert json.load(open(tmp_path / "cache.json"))  # embeddings guardados (não ouve de novo)
    assert len(AJ.janelas(_gerar(str(tmp_path / "longa.wav"), "sine=f=200:d={d}", dur=40))) == 3


def test_escolher_com_juiz_recusa_o_desconexo(tmp_path):
    o = AJ.Ouvido(_FalsoCLAP())
    alegre = _gerar(str(tmp_path / "alegre.wav"), "sine=f=1200:d={d}", dur=25)
    triste = _gerar(str(tmp_path / "triste.wav"), "sine=f=110:d={d}", dur=25)
    sd = SD.vazio()
    sd["blocos"] = [SD.novo_bloco(0, 60, "tristeza", "rain light", "sad piano")]
    pd = next(p for p in SD.pedidos(sd) if p["tipo"] == "musica")
    cands = [{"id": "1", "arquivo_cortado": alegre, "dur": 25, "fonte": "pixabay", "curtidas": 999},  # mais curtido, mas alegre
             {"id": "2", "arquivo_cortado": triste, "dur": 25, "fonte": "pixabay", "curtidas": 1}]
    c = SD.escolher(pd, cands, o)
    assert c["id"] == "2" and c["nota"] >= SD.NOTA_MINIMA and not c["aviso"]
    c = SD.escolher(pd, cands[:1], o)  # só o alegre: entra, mas marcado ⚠
    assert c["id"] == "1" and c["aviso"] and c["nota"] < SD.NOTA_MINIMA


def test_reserva_myinstants_so_pra_efeito_e_sem_estourado(tmp_path):
    pasta_p, pasta_m, pasta_job = (str(tmp_path / x) for x in ("pix", "mi", "job"))
    for p in (pasta_p, pasta_m):
        os.makedirs(p)
    sd = SD.vazio()
    sd["blocos"] = [SD.novo_bloco(0, 60, "tensao", "dark drone", "suspense dark")]
    sd["momentos"] = [SD.novo_momento(30, "impacto", 1)]
    sd["camadas"]["juiz"] = False

    def rodar_pix(args):  # o Pixabay só tem a música
        if args.tipo == "music":
            arq = _gerar(os.path.join(pasta_p, "m.wav"), "sine=f=200:d={d}", dur=25)
            json.dump([{"id": "p1", "busca": "suspense dark", "tipo": "musica", "arquivo_cortado": arq, "dur": 25}],
                      open(os.path.join(pasta_p, "catalogo.json"), "w"))
        return 0
    chamados = []

    def rodar_mi(termos, pasta, limite, prog):
        chamados.append(list(termos))
        cat = []
        for k, t in enumerate(termos):
            ok = _gerar(os.path.join(pasta, f"ok{k}.wav"), "sine=f=600:d={d}", ["-af", "volume=0.3"], dur=1)
            ruim = _gerar(os.path.join(pasta, f"ruim{k}.wav"), "sine=f=600:d={d}", ["-af", "volume=25"], dur=1)
            cat += [{"id": f"mi_ruim{k}", "busca": t, "tipo": "efeitos", "fonte": "myinstants", "arquivo_cortado": ruim, "dur": 1,
                     "qualidade": AQ.avaliar(ruim)},
                    {"id": f"mi_ok{k}", "busca": t, "tipo": "efeitos", "fonte": "myinstants", "arquivo_cortado": ok, "dur": 1,
                     "qualidade": AQ.avaliar(ok)}]
        json.dump(cat, open(os.path.join(pasta, "catalogo.json"), "w"))
        return len(termos)
    r = SD.buscar_audios(sd, pasta_p, pasta_job, rodar=rodar_pix, pasta_memes=pasta_m, rodar_memes=rodar_mi)
    assert chamados and "suspense dark" not in chamados[0] and "dark drone" in chamados[0]   # música nunca vai pro MyInstants
    a = sd["audios"]
    assert a["musica:suspense dark"]["fonte"] == "pixabay"
    assert a["efeitos:dark drone"]["fonte"] == "myinstants" and a["efeitos:dark drone"]["id"].startswith("mi_ok")  # o estourado não
    assert r["faltando"] == []
    # 🔁 trocar: esquece e não escolhe o mesmo de novo
    SD.trocar(sd, "efeitos:dark drone")
    assert "efeitos:dark drone" not in sd["audios"] and sd["recusados"]["efeitos:dark drone"]
    # reserva desligada: não chama o MyInstants
    sd2 = SD.vazio()
    sd2["blocos"] = [SD.novo_bloco(0, 60, "tensao", "wind heavy", "")]
    sd2["camadas"].update(juiz=False, memes=False)
    chamados.clear()
    SD.buscar_audios(sd2, pasta_p, pasta_job, rodar=lambda a: 0, pasta_memes=pasta_m, rodar_memes=rodar_mi)
    assert chamados == []


def test_myinstants_le_os_cards():
    html = '''<div class="instant"><div class="circle small-circle" style="background-color:#F44336"></div>
      <button class="small-button" onclick="play('/media/sounds/wasted.mp3', 'loader-1', 'wasted-1')" title="Tocar"></button>
      <a href="/pt/instant/wasted-gta-1/" class="instant-link link-secondary">Wasted GTA</a></div>
      <div class="instant"><button class="small-button" onclick="play(&#x27;/media/sounds/vine-boom.mp3&#x27;, 'x', 'y')"></button>
      <a class="instant-link" href="/pt/instant/vine-boom/">Vine &amp; Boom</a></div>
      <div class="instant"><button class="small-button" onclick="play('/media/sounds/wasted.mp3', 'l', 'w')"></button></div>'''
    cards = MI.ler_cards(html)
    assert [c["mp3"] for c in cards] == ["/media/sounds/wasted.mp3", "/media/sounds/vine-boom.mp3"]
    assert cards[0]["titulo"] == "Wasted GTA" and cards[1]["titulo"] == "Vine & Boom"
    assert cards[0]["pagina"].endswith("/pt/instant/wasted-gta-1/")
    assert MI.url_busca("cinematic boom") == "https://www.myinstants.com/pt/search/?name=cinematic+boom"


def test_juiz_sem_transformers_nao_quebra(monkeypatch):
    monkeypatch.setattr(AJ, "disponivel", lambda: "falta o pacote transformers (pip install transformers)")
    assert AJ.juiz() is None and AJ.ouvido() is None
    import app as A
    jid = "sdjuiz01"
    monkeypatch.setitem(A._JOBS, jid, {"job_id": jid, "segments": [{"start": 0, "end": 30, "text": "x"}], "total_duration": 30})
    e = A.app.test_client().get(f"/job/{jid}/sound-design/estado").get_json()
    assert "transformers" in e["juiz_falta"]
