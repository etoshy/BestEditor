"""v84_236: 🎭 React de personagens — transcrição limpa, elenco (sugestões + os seus), roteiro com expressões e
reações, linha do tempo de cada personagem, cenário em camadas, prévia e o projeto do editor com tudo posicionado."""
import base64
import io
import json
import os
import subprocess

import pytest
from PIL import Image, ImageDraw

import react_personagens as R


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_PERSONAGENS_DIR", str(tmp_path / "react"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    return str(tmp_path)


def _png(cor=(200, 50, 50), tam=(300, 450), fundo=None):
    im = Image.new("RGBA" if fundo is None else "RGB", tam, (0, 0, 0, 0) if fundo is None else fundo)
    ImageDraw.Draw(im).rectangle([40, 40, tam[0] - 40, tam[1] - 1], fill=cor)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _video(caminho, dur=8):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=10:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", caminho], check=True, capture_output=True)
    return caminho


# ------------------------------------------------------------------ transcrição
def test_transcricao_da_tela_repetida_vira_uma_frase_por_vez():
    zw = "​"
    txt = "\n".join([
        f"0:13 {zw}Almas que viram hollows são seres imundos{zw}",
        f"0:13 {zw}Almas que viram hollows são seres imundos{zw} {zw}Almas que viram hollows são seres imundos{zw}",
        "0:13 Yhwach - Lucas A.R.T Yhwach - Lucas A.R.T",
        "0:16 Almas que viram hollows são seres imundos Almas que viram hollows são seres imundos",
        "0:17 Almas que viram hollows são seres imundos Eles devem ser exterminados do mundo",
        "0:18 Eles devem ser exterminados do mundo Eles devem ser exterminados do mundo",
        "1:13 Kyoraku - Teaga",
        "1:16 Kyoraku - Teaga Se esse é o caso, vai cansar pra valer",
        "2:05 Bazz-B - Blaze",
    ])
    it = R.parse_transcricao(txt)
    falas = [e for e in it if e["tipo"] == "fala"]
    assert [e["texto"] for e in falas] == ["Almas que viram hollows são seres imundos", "Eles devem ser exterminados do mundo",
                                           "Se esse é o caso, vai cansar pra valer"]
    assert falas[0]["ini"] == 13 and falas[0]["fim"] <= 17
    assert {e["texto"] for e in it if e["tipo"] == "credito"} == {"Yhwach - Lucas A.R.T", "Kyoraku - Teaga", "Bazz-B - Blaze"}
    assert "(crédito na tela: Yhwach - Lucas A.R.T)" in R.transcricao_texto(it)


def test_transcricao_srt_youtube_e_sem_tempo():
    srt = "1\n00:00:01,000 --> 00:00:03,500\nOlá <i>mundo</i>\n\n2\n00:01:02,000 --> 00:01:04,000\nSegunda\n"
    it = R.parse_transcricao(srt)
    assert [(e["ini"], e["fim"], e["texto"]) for e in it] == [(1.0, 3.5, "Olá mundo"), (62.0, 64.0, "Segunda")]
    yt = "0:05\nprimeira frase\n1:10\nsegunda frase\n"
    assert [(e["ini"], e["texto"]) for e in R.parse_transcricao(yt)] == [(5.0, "primeira frase"), (70.0, "segunda frase")]
    assert [e["texto"] for e in R.parse_transcricao("[00:07] colchete\n00:09 - traço")] == ["colchete", "traço"]
    sem = R.parse_transcricao("linha sem tempo\noutra")
    assert [e["ini"] for e in sem] == [None, None] and sem[1]["texto"] == "outra"
    assert R.colapsar_repeticoes("a b a b a b c c") == "a b c"


# ------------------------------------------------------------------ elenco e roteiro
def _proj(base, n=3):
    p = R.criar("Teste", base)
    for nome in ["Itachi Uchiha", "Sasuke", "Naruto", "Gojo"][:n]:
        R.novo_personagem(p, nome, obra="Naruto")
    p["video"] = {"duracao": 120.0}
    return p


def test_sugestoes_mistura_e_troca_de_nome(base):
    p = _proj(base, 1)
    with pytest.raises(R.ReactErro):
        R.novo_personagem(p, "itachi uchiha")  # já está
    sug = {"obra": "Naruto", "estilo": "anime", "resumo_video": "rap",
           "personagens": [{"nome": n, "obra": "Naruto", "tipo": "da_obra", "motivo": "m", "personalidade": "p", "jeito_de_falar": "j",
                            "aparencia_en": "a", "busca_imagem": "b", "estilo": "anime"} for n in ("Madara", "Obito", "Itachi Uchiha")]}
    R.aplicar_sugestoes(p, sug)
    novos = R.usar_sugestoes(p, ["Madara", "Obito", "Itachi Uchiha"], {"Obito": {"nome": "Kakashi"}})
    assert [c["nome"] for c in novos] == ["Madara", "Kakashi"]
    assert novos[0]["personalidade"] == "p" and novos[0]["origem"] == "ia"
    assert novos[1]["personalidade"] == "" and novos[1]["origem"] == "manual"  # trocou o nome: a ficha era de outro
    assert len({c["cor"] for c in p["personagens"]}) == 3
    assert R.estilo_final(p) == "anime"


def test_roteiro_casa_nomes_e_garante_pedido_de_inscricao(base):
    p = _proj(base)
    r = {"resumo": "ok", "falas": [
        {"tempo": 30, "personagem": "Itachi", "texto": "Sasuke, você ainda é fraco.", "expressao": "debochado",
         "pedido_inscricao": False, "reacoes": [{"personagem": "sasuke", "expressao": "bravo"}, {"personagem": "Itachi", "expressao": "feliz"}]},
        {"tempo": "0:10", "personagem": "Naruto", "texto": "Dattebayo!", "expressao": "nao_existe", "pedido_inscricao": False, "reacoes": []},
        {"tempo": 500, "personagem": "Sasuke", "texto": "Hmpf.", "expressao": "bravo", "pedido_inscricao": False, "reacoes": []},
        {"tempo": 40, "personagem": "Ninguém", "texto": "x", "expressao": "feliz", "pedido_inscricao": False, "reacoes": []},
    ]}
    rot = R.aplicar_roteiro(p, r)
    falas = rot["falas"]
    assert rot["ignoradas"] == 1
    assert falas[0]["t"] == 10 and falas[0]["expressao"] == "neutro"
    itachi = next(f for f in falas if f["texto"].startswith("Sasuke"))
    assert [x["expressao"] for x in itachi["reacoes"]] == ["bravo"]  # quem fala não reage a si mesmo
    assert max(f["t"] for f in falas) <= 118.5  # depois do fim do vídeo → puxa pra dentro
    assert sum(f["cta"] for f in falas) == 1  # a IA esqueceu: entra um pedido de inscrição dito por um personagem


def test_falas_nao_se_sobrepoem_e_linha_do_tempo_dos_personagens(base):
    p = _proj(base, 2)
    a, b = p["personagens"]
    falas = [{"id": "1", "t": 10.0, "dur": 4.0, "cid": a["id"], "texto": "x", "expressao": "chocado", "reacoes": [{"cid": b["id"], "expressao": "feliz"}]},
             {"id": "2", "t": 12.0, "dur": 3.0, "cid": b["id"], "texto": "y", "expressao": "bravo", "reacoes": []},
             {"id": "3", "t": 12.5, "dur": 3.0, "cid": a["id"], "texto": "z", "expressao": "feliz", "reacoes": []}]
    aj = R.ajustar_falas(falas, 60)
    for f1, f2 in zip(aj, aj[1:]):
        assert f1["t"] + f1["dur"] <= f2["t"] + 1e-6
    linhas = R.linhas_personagens(p, aj, 60)
    for cid, ls in linhas.items():
        assert ls[0]["start"] == 0 and ls[-1]["end"] == 60  # cobre o vídeo inteiro, sem buraco
        for x, y in zip(ls, ls[1:]):
            assert abs(x["end"] - y["start"]) < 1e-6
    fa = [e for e in linhas[a["id"]] if e["falando"]]
    assert [e["expressao"] for e in fa] == ["chocado", "feliz"]
    assert any(e["expressao"] == "bravo" and e["falando"] for e in linhas[b["id"]])
    jan = R._boca_janelas(10, 14)
    assert jan[0][0] == 10 and jan[-1][1] <= 14


def test_poses_json_sentado_com_mestre_neutra(base):
    p = _proj(base, 1)
    p["expressoes"] = ["feliz", "bravo"]
    d = R.poses_json(p, p["personagens"][0])
    assert [x["arquivo"] for x in d["poses"]] == ["itachi_uchiha_neutro.png", "itachi_uchiha_feliz.png", "itachi_uchiha_bravo.png"]
    assert d["poses"][0]["mestre"] and d["boca_auto"] and "SITTING" in d["texto_fixo"]["regras"]
    import personagens_pod as pp
    pp.ler_json(json.dumps(d))  # o formato que a aba 🧍 Personagens aceita


def test_disposicoes_sem_personagem_atras_da_tv(base):
    p = _proj(base, 4)
    for lay in R.LAYOUTS:
        p["layout"] = lay
        d = R.disposicao(p, base, (1280, 720))
        tl = d["tela"]
        assert len(d["assentos"]) == 4
        for a in d["assentos"]:  # o rosto (meio da PNG) nunca fica dentro da tela da TV
            assert not (tl["cx"] - tl["w"] / 2 < a["cx"] < tl["cx"] + tl["w"] / 2 and a["cy"] - a["h"] / 4 < tl["cy"] + tl["h"] / 2)
        if lay != "cinema_frente":  # 🎬 de frente: a legenda fica em cima, do lado do quadro do filme
            assert d["legenda"]["topo"] > tl["cy"] + tl["h"] / 2
    p["layout"] = "dois_sofas"
    d = R.disposicao(p, base, (720, 1280))  # vídeo em pé: a TV fica mais estreita
    assert d["tela"]["h"] <= 0.46 * R.H + 1 and len(d["sofas"]) == 2 and d["assentos"][-1]["espelhar"]


def test_legenda_e_tv_desenhadas(tmp_path):
    cam, w, h = R.desenhar_legenda("Itachi", "uma fala bem comprida " * 8, "#ff0000", 600, str(tmp_path / "l.png"))
    assert w <= 600 and h > 60 and Image.open(cam).mode == "RGBA"
    tv, borda = R.desenhar_tv(640, 360, str(tmp_path / "tv.png"))
    im = Image.open(tv)
    assert im.width == 640 + 2 * borda - 0 or im.width > 640


def test_camada_verde_recortada(base):
    p = R.criar("x", base)
    im = Image.new("RGB", (800, 400), (0, 255, 0))
    ImageDraw.Draw(im).rectangle([100, 100, 700, 350], fill=(120, 80, 40))
    R.guardar_camada(p, "sofa", im, base, recortar=True)
    out = Image.open(R.camada_arquivo(p, "sofa", base))
    assert out.mode == "RGBA" and abs(out.width - 600) <= 6 and abs(out.height - 250) <= 6
    R.guardar_camada(p, "fundo", Image.new("RGB", (1000, 1000), (9, 9, 9)), base)
    assert Image.open(R.camada_arquivo(p, "fundo", base)).size == (1920, 1080)


# ------------------------------------------------------------------ rotas + editor
def test_fluxo_pelas_rotas_ate_o_editor(base, tmp_path, monkeypatch):
    import app as A
    import personagens_pod as pp
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 8)
    with open(video, "rb") as f:
        r = c.post("/react-personagens/novo", data={"titulo": "Rap", "video_arquivo": (f, "v.mp4"),
                                                     "transcricao": "0:01 começa\n0:04 meio"}, content_type="multipart/form-data")
    pid = r.headers["Location"].split("/")[-1]
    assert c.get(f"/react-personagens/{pid}").status_code == 200
    assert b"React de personagens" in c.get("/modelos-video").data
    e = c.get(f"/react-personagens/{pid}/estado").get_json()
    assert e["video_ok"] and len(e["transcricao"]) == 2
    for nome in ("Goku", "Vegeta"):
        assert c.post(f"/react-personagens/{pid}/personagem", json={"nome": nome}).get_json()["ok"]
    cids = [x["id"] for x in R.carregar(pid)["personagens"]]
    # 🧲 a foto chega pelo script das guias (a rota dos Modelos de vídeo, com o id do react)
    r = c.post(f"/modelos-video/{pid}/fotos-roteiro/link", data=json.dumps({"url": "https://x/a.png", "dados_b64": base64.b64encode(_png()).decode(),
                                                                            "elenco": {"t": "react", "n": cids[0]}}), content_type="text/plain")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
    assert R.carregar(pid)["personagens"][0]["refs"]
    assert "Responda SÓ com um JSON" in c.get(f"/react-personagens/{pid}/prompt/roteiro").get_json()["prompt"]
    rot = {"falas": [{"tempo": 1.5, "personagem": "Goku", "texto": "Que poder incrível!", "expressao": "empolgado", "pedido_inscricao": True,
                      "reacoes": [{"personagem": "Vegeta", "expressao": "bravo"}]},
                     {"tempo": 4.5, "personagem": "Vegeta", "texto": "Kakaroto!", "expressao": "bravo", "pedido_inscricao": False, "reacoes": []}]}
    assert c.post(f"/react-personagens/{pid}/colar/roteiro", json={"texto": "```json\n" + json.dumps(rot) + "\n```"}).get_json()["n"] == 2
    for q, im in (("fundo", _png((30, 30, 60), (640, 360), (10, 10, 10))), ("sofa", _png((80, 80, 90), (600, 300))), ("mesa", _png((120, 70, 40), (600, 200)))):
        assert c.post(f"/react-personagens/{pid}/cenario/{q}/arquivo", data={"arquivo": (io.BytesIO(im), "x.png")},
                      content_type="multipart/form-data").get_json()["ok"]
    # 🧍 as poses: o projeto é criado de verdade; o Flow não roda no teste
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    assert c.post(f"/react-personagens/{pid}/poses/gerar", json={"cids": [cids[0]]}).get_json()["ok"]
    ch = R.carregar(pid)["personagens"][0]
    proj = pp.carregar(ch["pod"]["pid"])
    for nome in ("goku_neutro.png", "goku_empolgado.png"):
        local = nome[:-4] + "_v1.png"
        with open(os.path.join(pp._pasta(proj["id"]), "imagens", local), "wb") as f:
            f.write(_png())
        proj["imagens"][nome].update(estado="pronta", versoes=[{"local": local}], atual=0)
    pp.salvar(proj)
    assert set(R.poses_do_personagem(ch)) == {"neutro", "empolgado"}
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=2").status_code == 200
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    assert d["ok"], d
    assert any("Vegeta" in a for a in d["avisos"])  # sem poses e sem referência: avisa
    job = A._JOBS[d["job_id"]]
    ovs = job["overlays"]
    camadas = [o.get("camada") for o in ovs]
    # a ordem das camadas: sofá → personagens → mesa → TV → legendas → o vídeo na tela
    assert camadas.index("sofa") < camadas.index("personagem") < camadas.index("mesa") < camadas.index("tv") < camadas.index("legenda")
    i = camadas.index("tela")  # o vídeo vai logo acima da moldura da TV (a legenda fica por cima)
    assert camadas[i - 1] == "tv" and ovs[i]["sincronizar"] and ovs[i]["media_type"] == "video"
    goku = [o for o in ovs if o.get("cid") == cids[0] and o["camada"] == "personagem"]
    assert goku[0]["start"] == 0 and abs(goku[-1]["end"] - job["total_duration"]) < 0.01
    assert any(o["expressao"] == "empolgado" and o["falando"] for o in goku)
    assert all(o["manual"] and o["ancora"] == "centro" for o in ovs if o["origem"] == "react")
    assert c.get(d["link"]).status_code == 200
    assert job["pending_segments"][0]["override_source"]["zoom_direction"] == "static"


def test_overlay_pelo_centro_e_grafo_longo_em_arquivo(tmp_path):
    """O render posiciona pelo centro (igual ao monitor) e, com muitas camadas, o grafo vai num arquivo."""
    import video_assembler as va
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=10:duration=2",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", base], check=True, capture_output=True)
    png = str(tmp_path / "q.png")
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(png)
    ovs = [{"resolved_path": png, "media_type": "image", "start": 0, "end": 2, "size_percent": 25, "x_percent": 50,
            "y_percent": 50, "ancora": "centro"}]
    ovs += [{"resolved_path": png, "media_type": "image", "start": 0, "end": 0.05 + k * 0.001, "size_percent": 1,
             "personagem": f"react_{k}", "x_percent": 1, "y_percent": 1, "ancora": "centro", "lado": "esquerda"} for k in range(40)]
    out = str(tmp_path / "out.mp4")
    va.apply_overlays(base, ovs, out, 320, 180)
    q = str(tmp_path / "q.jpg")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", out, "-frames:v", "1", q], check=True)
    im = Image.open(q).convert("RGB")
    r, g, b = im.getpixel((160, 90))
    assert r > 180 and g < 80  # o quadrado vermelho está no CENTRO
    assert im.getpixel((160 - 50, 90))[0] < 60
    assert not [n for n in os.listdir(tmp_path) if n.startswith("_overlays_")]  # o arquivo do grafo foi apagado


def test_personagem_que_ja_existe_e_reaproveitado(base, monkeypatch):
    """♻ O mesmo personagem num react novo: liga o projeto 🧍 que já tem as poses e copia a ficha e a referência."""
    import personagens_pod as pp
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    p1 = R.criar("primeiro", base)
    c1 = R.novo_personagem(p1, "Gojo Satoru", obra="Jujutsu Kaisen", personalidade="arrogante e brincalhão", aparencia_en="white hair, blindfold")
    R.guardar_ref(p1, c1, _png(), base)
    R.salvar(p1, base)
    R.criar_poses(p1["id"], c1["id"], base)
    c1 = R.carregar(p1["id"], base)["personagens"][0]
    proj = pp.carregar(c1["pod"]["pid"], base)
    local = "gojo_satoru_neutro_v1.png"
    with open(os.path.join(pp._pasta(proj["id"], base), "imagens", local), "wb") as f:
        f.write(_png())
    proj["imagens"]["gojo_satoru_neutro.png"].update(estado="pronta", versoes=[{"local": local}], atual=0)
    proj["mestre"] = {"arquivo": "gojo_satoru_neutro.png", "local": local}
    pp.salvar(proj, base)

    p2 = R.criar("segundo", base)
    p2["expressoes"] = ["neutro", "apaixonado"]  # uma expressão que o primeiro não tinha
    c2 = R.novo_personagem(p2, "gojo satoru")
    assert "ficha" in R.reaproveitar(p2, c2, base) and "pose" in c2["reaproveitado"]
    assert c2["personalidade"] == "arrogante e brincalhão" and c2["refs"] and c2["pod"]["pid"] == proj["id"]
    R.salvar(p2, base)
    R.criar_poses(p2["id"], c2["id"], base)  # não cria outro projeto: junta a expressão nova ao mesmo
    assert len(pp.listar(base)) == 1
    arqs = {x["arquivo"] for x in pp.carregar(proj["id"], base)["dados"]["poses"]}
    assert {"gojo_satoru_neutro.png", "gojo_satoru_feliz.png", "gojo_satoru_apaixonado.png"} <= arqs
    assert R.poses_do_personagem(R.carregar(p2["id"], base)["personagens"][0], base)["neutro"]["pose"]


def test_cronologia_e_verificador_de_fatos(base):
    p = _proj(base, 2)
    ita, sas = p["personagens"]
    ita["cronologia"] = "já morreu quando isso acontece"
    R.aplicar_roteiro(p, {"falas": [
        {"tempo": 5, "personagem": "Itachi Uchiha", "texto": "Eu lembro dessa luta com o Madara.", "expressao": "pensativo",
         "pedido_inscricao": True, "reacoes": [], "duvida": "não sei se o Itachi lutou com o Madara"},
        {"tempo": 9, "personagem": "Sasuke", "texto": "Hmpf.", "expressao": "bravo", "pedido_inscricao": False, "reacoes": [], "duvida": ""}]})
    rot = R.prompt_roteiro(p)
    assert "cronologia: já morreu" in rot and "CRONOLOGIA" in R.sys_roteiro(p)
    f1, f2 = p["roteiro"]["falas"]
    pr = R.prompt_checagem(p, "tudo", "confira o Madara")
    assert "⚠ DÚVIDA: não sei se o Itachi lutou" in pr and f1["id"] in pr and "confira o Madara" in pr
    assert f1["id"] not in R.prompt_checagem(p, "fichas")
    ch = R.aplicar_checagem(p, {"fichas": [{"personagem": "sasuke", "campo": "relacoes", "para": "irmão mais novo do Itachi",
                                            "problema": "faltou", "fonte": "https://naruto.fandom.com"}],
                                "falas": [{"id": f1["id"], "para": "Eu nunca lutei com o Madara... mas ouvi falar.", "expressao": "chocado",
                                           "problema": "Itachi nunca lutou com o Madara", "fonte": "x"},
                                          {"id": f2["id"], "para": "", "expressao": "", "problema": "fora de contexto", "fonte": ""},
                                          {"id": "naoexiste", "para": "x", "expressao": "", "problema": "", "fonte": ""}],
                                "conferidos": [{"item": "Itachi Uchiha", "nota": "ok"}], "resumo": "r"}, "teste")
    assert len(ch["itens"]) == 3 and ch["itens"][2]["apagar"]
    assert R.resolver_checagem(p, ch["itens"][0]["id"], "aplicar") == 1 and sas["relacoes"] == "irmão mais novo do Itachi"
    assert R.resolver_checagem(p, "*", "aplicar") == 2
    assert [f["texto"] for f in p["roteiro"]["falas"]] == ["Eu nunca lutei com o Madara... mas ouvi falar."]
    assert p["roteiro"]["falas"][0]["expressao"] == "chocado" and p["roteiro"]["falas"][0]["duvida"] == ""
    assert R.resolver_checagem(p, "*", "aplicar") == 0


def test_balao_sem_numeracao():
    assert R.limpar_texto_fala("Fala número 3: olha isso!") == "olha isso!"
    assert R.limpar_texto_fala("#12 - que isso") == "que isso"
    assert R.limpar_texto_fala("Itachi: \"Sasuke...\"", "Itachi") == "Sasuke..."
    assert R.limpar_texto_fala("3 pessoas morreram?") == "3 pessoas morreram?"  # número que é da fala fica


def test_cortes_mapeiam_tempo_transcricao_e_falas(base, tmp_path):
    p = R.criar("cortes", base)
    R.guardar_video(p, _video(str(tmp_path / "v.mp4"), 12), base)
    assert p["video"]["original"] == p["video"]["arquivo"] and p["cortes"]["meio"] == []
    R.definir_transcricao(p, "0:01 começo\n0:05 cena cortada\n0:09 depois do corte")
    R.novo_personagem(p, "Goku")
    p["escutar"] = False  # v84_245: aqui o teste é só dos cortes (o 👂 empurraria as falas pro fim das frases)
    R.aplicar_roteiro(p, {"falas": [{"tempo": t, "personagem": "Goku", "texto": f"fala em {t}", "expressao": "feliz",
                                     "pedido_inscricao": t == 9.5, "reacoes": [], "duvida": ""} for t in (1.5, 5.5, 9.5)]})
    R.salvar(p, base)
    rem_teste = [[0.0, 1.0], [4.0, 7.0]]
    assert R.mapear(0.5, rem_teste) is None and R.mapear(2.0, rem_teste) == 1.0 and R.mapear(8.0, rem_teste) == 4.0
    assert R.inverso(4.0, rem_teste) == 8.0 and R.inverso(1.0, rem_teste) == 2.0
    r = R.aplicar_cortes(p["id"], base, {"inicio": "0:01", "fim": None, "meio": [["0:04", "0:07"]]})
    p = R.carregar(p["id"], base)
    assert r["falas_sairam"] == 1 and abs(r["duracao"] - 8) < 0.4
    assert p["video"]["arquivo"] == "video_cortado.mp4" and R.video_original(p, base).endswith("video.mp4")
    assert [(e["ini"], e["texto"]) for e in p["transcricao"]] == [(0.0, "começo"), (5.0, "depois do corte")]
    assert [f["t"] for f in p["roteiro"]["falas"]] == [0.5, 5.5]
    # mudar os cortes de novo: as falas voltam pro tempo certo (passam pelo original)
    R.aplicar_cortes(p["id"], base, {"inicio": None, "fim": "0:11", "meio": []})
    p = R.carregar(p["id"], base)
    assert [f["t"] for f in p["roteiro"]["falas"]] == [1.5, 9.5] and abs(p["video"]["duracao"] - 11) < 0.4
    R.aplicar_cortes(p["id"], base, {"inicio": None, "fim": None, "meio": []})
    p = R.carregar(p["id"], base)
    assert p["video"]["arquivo"] == p["video"]["original"] and not os.path.exists(os.path.join(R.pasta(p["id"], base), "video_cortado.mp4"))
    with pytest.raises(R.ReactErro):
        R.aplicar_cortes(p["id"], base, {"inicio": "0:05", "fim": "0:04", "meio": []})


def test_transcricao_do_youtube_pelo_sistema_dos_roteiros(base, monkeypatch):
    import roteiros_yt as ry
    p = R.criar("", base)
    p["video"] = {"url": "https://youtu.be/abcdefghijk?si=x"}
    R.salvar(p, base)
    pedidos = []

    def falso(url, pasta, **kw):
        pedidos.append(url)
        return {"fonte": "legenda do vídeo", "titulo": "Rap do Itachi", "blocos": [{"inicio": 0, "texto": "junto"}],
                "linhas": [{"inicio": 3.2, "fim": 5, "texto": "Eu sou o Itachi"}, {"inicio": 65.0, "fim": 67, "texto": "Sharingan"}]}
    monkeypatch.setattr(ry, "extrair_transcricao", falso)
    assert R.transcrever_youtube(p["id"], base) == 2
    p = R.carregar(p["id"], base)
    assert [(e["ini"], e["texto"]) for e in p["transcricao"]] == [(3.2, "Eu sou o Itachi"), (65.0, "Sharingan")]
    assert p["titulo"] == "Rap do Itachi" and p["video"]["transcricao_fonte"] == "legenda do vídeo"
    p["video"]["url"] = "https://vimeo.com/1"
    R.salvar(p, base)
    with pytest.raises(R.ReactErro):
        R.transcrever_youtube(p["id"], base)


def test_roteiro_em_partes_cobre_o_video_inteiro(base, monkeypatch):
    """Vídeo de 10 min: o roteiro sai em partes de ~2,5 min (num pedido só a IA parava nos 2 min)."""
    import re as _re
    import ia_servico
    p = _proj(base, 3)
    p["video"] = {"duracao": 600.0}
    R.definir_transcricao(p, "\n".join(f"{m}:{s:02d} frase {m}-{s}" for m in range(10) for s in (5, 35)))
    R.salvar(p, base)
    pedidos = []

    def ia_falsa(recurso, system, conteudo, **kw):
        txt = conteudo[0]["text"]
        m = _re.search(r"PARTE (\d+) DE (\d+): do \S+ \((\d+) s\) ao \S+ \((\d+) s\)", txt)
        a, b = int(m.group(3)), int(m.group(4))
        pedidos.append((int(m.group(1)), "coloque NESTA parte" in txt, "LOGO ANTES" in txt))
        if "PARTE 3 DE" in txt and len(pedidos) <= 4:
            return None  # uma parte falha: as outras ficam, e o 🤖 Completar faz só ela
        return {"resumo": "r", "falas": [{"tempo": t, "personagem": "Sasuke" if t % 20 else "Naruto", "texto": f"olha isso aos {t} segundos",
                                          "expressao": "feliz", "pedido_inscricao": False, "reacoes": [], "duvida": ""}
                                         for t in range(a + 3, b, 12)]}
    monkeypatch.setattr(ia_servico, "chamar", ia_falsa)
    monkeypatch.setattr(R, "blocos_do_video", lambda *a, **k: [])
    assert [x["fim"] for x in R.estado_partes(p)] == [150, 300, 450, 600]
    r = R.gerar_roteiro(p["id"], base)
    assert r["feitas"] == 3 and r["erros"] == ["5:00–7:30"]
    assert [x[0] for x in pedidos] == [1, 2, 3, 3, 4] and pedidos[1][1] and not pedidos[0][1]  # o pedido de inscrição vai na parte de ~25%
    assert pedidos[1][2]  # a parte 2 recebe as falas da parte 1 pra continuar a conversa
    p = R.carregar(p["id"], base)
    assert [x["vazia"] for x in R.estado_partes(p)] == [False, False, True, False]
    r = R.gerar_roteiro(p["id"], base, so_vazias=True)
    p = R.carregar(p["id"], base)
    falas = p["roteiro"]["falas"]
    assert r["feitas"] == 1 and not any(x["vazia"] for x in R.estado_partes(p))
    assert max(f["t"] for f in falas) > 580 and sum(f["cta"] for f in falas) == 1
    assert len({f["id"] for f in falas}) == len(falas)
    # colar a resposta de outra IA numa parte só troca as falas daquele trecho
    antes = [f for f in falas if f["t"] >= 150]
    R.aplicar_roteiro(p, {"falas": [{"tempo": 10, "personagem": "Naruto", "texto": "nova", "expressao": "feliz",
                                     "pedido_inscricao": False, "reacoes": [], "duvida": ""}]}, janela=[0, 150])
    assert [f["texto"] for f in p["roteiro"]["falas"] if f["t"] < 150] == ["nova"]
    assert [f["id"] for f in p["roteiro"]["falas"] if f["t"] >= 150] == [f["id"] for f in antes]
    assert "PARTE 2 DE 4" in R.prompt_copiar(p, "roteiro", 1)


def test_abrir_todos_os_personagens_em_guias(base, monkeypatch):
    import app as A
    import navegador_imagens as nav
    abertas = {}
    monkeypatch.setattr(nav, "abrir", lambda b, urls, cfg=None, chaves=None, pid="": abertas.update(urls=urls, chaves=chaves) or
                        {"ok": True, "guias": len(urls), "navegador": "Brave", "confirmadas": list(range(len(urls)))})
    monkeypatch.setattr(nav, "fechar_terminadas", lambda *a, **k: {"fechadas": [], "mantidas": []})
    c = A.app.test_client()
    p = _proj(base, 3)
    R.guardar_ref(p, p["personagens"][0], _png(), base)  # um já tem imagem: no "abrir todos" ele vem também
    R.salvar(p, base)
    todos = [x["id"] for x in p["personagens"]]
    d = c.post(f"/react-personagens/{p['id']}/brave", json={"cids": todos}).get_json()
    assert d["guias"] == 3 and abertas["chaves"] == ["el:" + x for x in todos]
    assert all("udm=2" in u and "#bes=" in u for u in abertas["urls"])
    d = c.post(f"/react-personagens/{p['id']}/brave", json={}).get_json()  # só quem está sem imagem
    assert d["guias"] == 2


def test_letra_boa_e_edicao_forte_entram_no_roteiro(base, tmp_path):
    """⭐ versos marcados (obrigatórios) e 🎬 momentos de edição forte (muitos cortes seguidos) vão pra parte certa."""
    import subprocess as sp
    cores = ["red", "blue", "green", "yellow", "white", "purple", "orange", "cyan", "pink", "gray", "black", "brown"]
    lista = tmp_path / "l.txt"
    pedacos = []
    for k, (cor, d) in enumerate([("navy", 12)] + [(c, 0.5) for c in cores] + [("navy", 12)]):
        arq = tmp_path / f"p{k}.mp4"
        sp.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={cor}:size=320x180:rate=10:duration={d}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(arq)], check=True)
        pedacos.append(f"file '{arq}'")
    lista.write_text("\n".join(pedacos))
    video = tmp_path / "v.mp4"
    sp.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(video)], check=True)
    p = _proj(base, 2)
    R.guardar_video(p, str(video), base)
    R.definir_transcricao(p, "0:03 mil anos de espera\n0:14 isso é uma declaração de guerra\n0:25 fim")
    ed = R.analisar_edicao(p, base)
    assert len(ed["cortes"]) >= 8 and len(ed["momentos"]) == 1 and 11 <= ed["momentos"][0]["ini"] <= 13
    assert R.analisar_edicao(p, base) is ed or R.analisar_edicao(p, base)["chave"] == ed["chave"]  # não refaz
    assert R.marcar_destaque(p, "isso é uma declaração de guerra", 14.0) == 1
    assert R.marcar_destaque(p, "mil anos de espera", 3.0) == 2 and R.marcar_destaque(p, "mil anos de espera", 3.0, False) == 1
    pr = R.prompt_roteiro_parte(p, 0)
    assert "⭐ VERSOS MARCADOS" in pr and "“isso é uma declaração de guerra”" in pr and "mil anos" not in pr.split("⭐")[1][:200]
    assert "🎬 MOMENTOS DE EDIÇÃO FORTE" in pr and "LETRA BOA E EDIÇÃO DIFERENTE" in R.sys_roteiro(p)
    blocos = R.blocos_do_video(p, base, 9, 0, R.duracao_total(p))
    assert len(blocos) == 2  # 9 quadros do trecho + 3 do momento de edição = 2 mosaicos 3×3
    R.aplicar_roteiro(p, {"falas": [{"tempo": 15, "personagem": "Sasuke", "texto": "“declaração de guerra”... que verso", "expressao": "empolgado",
                                     "pedido_inscricao": True, "reacoes": [], "duvida": "", "destaque": "letra"}]})
    assert p["roteiro"]["falas"][0]["destaque"] == "letra"


def test_poses_por_lado_reaproveita_e_gera_o_outro_lado(base, monkeypatch):
    """♻ Mesma expressão e mesmo lado: reaproveita. Nos 2 sofás, quem senta no da direita olha pra esquerda: gera as poses
    desse lado (sem perder as prontas); até ficarem prontas, o editor espelha as do outro lado e avisa."""
    import personagens_pod as pp
    enviadas = []
    monkeypatch.setattr(pp, "enviar", lambda pid, arqs, *a, **k: enviadas.append(list(arqs)) or {"ok": True})
    p = _proj(base, 2)
    p["expressoes"] = ["neutro", "feliz"]
    R.salvar(p, base)
    ita, sas = p["personagens"]
    R.criar_poses(p["id"], sas["id"], base)
    sas = R.carregar(p["id"], base)["personagens"][1]
    proj = pp.carregar(sas["pod"]["pid"], base)
    assert sorted(x["arquivo"] for x in proj["dados"]["poses"]) == ["sasuke_feliz.png", "sasuke_neutro.png"]
    for nome in ("sasuke_feliz.png", "sasuke_neutro.png"):
        with open(os.path.join(pp._pasta(proj["id"], base), "imagens", nome), "wb") as f:
            f.write(_png())
        proj["imagens"][nome].update(estado="pronta", versoes=[{"local": nome}], atual=0)
    proj["mestre"] = {"arquivo": "sasuke_neutro.png", "local": "sasuke_neutro.png"}
    pp.salvar(proj, base)
    # 2 sofás: o Sasuke (2º) senta no sofá da direita → olha pra esquerda
    p = R.carregar(p["id"], base)
    p["layout"] = "dois_sofas"
    R.salvar(p, base)
    assert R.lados_precisos(p, sas["id"], base) == ["esq"] and R.lados_precisos(p, ita["id"], base) == ["dir"]
    poses = R.poses_do_personagem(sas, base, "esq")
    assert poses["feliz"]["espelhar"] and poses["neutro"]["espelhar"]  # por enquanto: o outro lado espelhado
    R.criar_poses(p["id"], sas["id"], base)  # 🔁 Gerar o que falta
    proj = pp.carregar(sas["pod"]["pid"], base)
    assert {"sasuke_feliz.png", "sasuke_neutro.png", "sasuke_feliz_esq.png", "sasuke_neutro_esq.png"} <= {x["arquivo"] for x in proj["dados"]["poses"]}
    assert proj["imagens"]["sasuke_feliz.png"]["estado"] == "pronta"  # as prontas ficam
    assert set(enviadas[-1]) == {"sasuke_feliz_esq.png", "sasuke_neutro_esq.png"}  # só o lado novo vai pro Flow
    esq = next(x for x in proj["dados"]["poses"] if x["arquivo"] == "sasuke_feliz_esq.png")
    assert "LEFT" in esq["prompt"]
    with open(os.path.join(pp._pasta(proj["id"], base), "imagens", "e.png"), "wb") as f:
        f.write(_png())
    proj["imagens"]["sasuke_feliz_esq.png"].update(estado="pronta", versoes=[{"local": "e.png"}], atual=0)
    pp.salvar(proj, base)
    poses = R.poses_do_personagem(sas, base, "esq")
    assert not poses["feliz"]["espelhar"] and poses["neutro"]["espelhar"]
    assert R.estado_poses(sas, base)["por_lado"] == {"dir": {"prontas": 2, "total": 2}, "esq": {"prontas": 1, "total": 2}}


def test_cenario_reaproveitado_de_outro_react(base):
    p1 = R.criar("um", base)
    im = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([20, 20, 380, 180], fill=(90, 90, 100, 255))
    R.guardar_camada(p1, "sofa", im, base, recortar=False)
    R.salvar(p1, base)
    p2 = R.criar("dois", base)
    outros = R.camadas_de_outros(p2, "sofa", base)
    assert len(outros) == 1 and outros[0]["projeto"] == p1["id"] and outros[0]["atual"]
    R.usar_camada_de_outro(p2, "sofa", p1["id"], outros[0]["arquivo"], base)
    out = Image.open(R.camada_arquivo(p2, "sofa", base))
    assert out.size == (361, 161) and p2["cenario"]["camadas"]["sofa"]["origem"] == "♻ outro react"
    assert R.camadas_de_outros(p2, "mesa", base) == []
    with pytest.raises(R.ReactErro):
        R.usar_camada_de_outro(p2, "sofa", p1["id"], "../x.png", base)


def test_posicoes_ajustadas_na_mao_vao_pro_editor(base, tmp_path):
    """🎛 Arrastar / mudar tamanho / virar cada peça na prévia: fica salvo por disposição e vale pra prévia e pro editor."""
    import app as A
    p = _proj(base, 3)
    R.salvar(p, base)
    pid = p["id"]
    auto = R.disposicao(p, base, (1280, 720))
    cid = p["personagens"][1]["id"]
    c = A.app.test_client()
    pe = c.get(f"/react-personagens/{pid}/pecas").get_json()
    chaves = [x["chave"] for x in pe["pecas"]]
    assert {"tela", "legenda", "mesa", "sofa0", f"p:{cid}"} <= set(chaves) and pe["layout"] == "sofa_tv"
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": "tela", "cx": 1500, "cy": 300, "w": auto["tela"]["w"] * 1.2}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": f"p:{cid}", "cx": 777, "lado": "esq"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": "legenda", "topo": 950}).get_json()["ok"]
    assert not c.post(f"/react-personagens/{pid}/posicao", json={"chave": "nada", "cx": 1}).get_json()["ok"]
    p = R.carregar(pid, base)
    d = R.disposicao(p, base, (1280, 720))
    assert d["tela"]["cx"] == 1500 and d["tela"]["cy"] == 300
    assert abs(d["tela"]["h"] - auto["tela"]["h"] * 1.2) < 1  # o tamanho mantém a proporção
    a = next(x for x in d["assentos"] if x["cid"] == cid)
    assert a["cx"] == 777 and a["espelhar"] and a["cy"] == next(x for x in auto["assentos"] if x["cid"] == cid)["cy"]
    assert R.lados_precisos(p, cid, base) == ["esq"]  # as poses desse lado passam a ser pedidas
    assert d["legenda"]["topo"] == 950
    # a outra disposição tem os seus próprios ajustes
    p["layout"] = "dois_sofas"
    assert R.disposicao(p, base, (1280, 720))["tela"]["cx"] == R.disposicao(dict(p, posicoes={}), base, (1280, 720))["tela"]["cx"]
    p["layout"] = "sofa_tv"
    R.salvar(p, base)
    c.post(f"/react-personagens/{pid}/posicao", json={"chave": "tela", "limpar": True})
    assert R.disposicao(R.carregar(pid, base), base, (1280, 720))["tela"]["cx"] == auto["tela"]["cx"]
    c.post(f"/react-personagens/{pid}/posicao", json={"limpar_tudo": True})
    assert R.carregar(pid, base)["posicoes"]["sofa_tv"] == {}
    assert "🗂 Camadas" in c.get(f"/react-personagens/{pid}").get_data(as_text=True)


def test_intrigas_briga_vira_imagem_e_quem_sai_some(base, tmp_path, monkeypatch):
    """⚡ Provocação → briga (imagem da luta na sala, por cima de tudo menos a legenda); quem sai some do sofá até voltar."""
    import app as A
    import flow_lote
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 20)
    with open(video, "rb") as f:
        r = c.post("/react-personagens/novo", data={"titulo": "Briga", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                   content_type="multipart/form-data")
    pid = r.headers["Location"].split("/")[-1]
    for nome in ("Naruto", "Sasuke", "Sakura"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": nome})
    p = R.carregar(pid)
    for ch, cor in zip(p["personagens"], ((250, 140, 0), (40, 40, 120), (240, 120, 180))):
        R.guardar_ref(p, ch, _png(cor), "a.png")
    R.salvar(p)
    assert c.post(f"/react-personagens/{pid}/dados", json={"intriga": "caos"}).get_json()["ok"]
    p = R.carregar(pid)
    assert "BRIGA" in R.sys_roteiro(p) and "eventos" in R._schema_roteiro(["neutro"])["required"]
    rot = {"resumo": "", "falas": [
        {"tempo": 2, "personagem": "Sasuke", "texto": "Você nunca vai ser Hokage, perdedor.", "expressao": "debochado", "pedido_inscricao": True, "reacoes": [], "duvida": "", "destaque": ""},
        {"tempo": 5, "personagem": "Naruto", "texto": "REPETE ISSO!", "expressao": "bravo", "pedido_inscricao": False, "reacoes": [], "duvida": "", "destaque": ""},
        {"tempo": 12, "personagem": "Sakura", "texto": "Eu vou buscar gelo...", "expressao": "triste", "pedido_inscricao": False, "reacoes": [], "duvida": "", "destaque": ""}],
        "eventos": [
        {"tempo": 7, "tipo": "briga", "personagens": ["Naruto", "Sasuke"], "descricao": "Naruto soca o Sasuke", "imagem_en": "Naruto punches Sasuke in the face", "duracao": 4},
        {"tempo": 13, "tipo": "sai", "personagens": ["Sakura"], "descricao": "foi buscar gelo", "imagem_en": "", "duracao": 0},
        {"tempo": 17, "tipo": "volta", "personagens": ["Sakura"], "descricao": "", "imagem_en": "", "duracao": 0},
        {"tempo": 9, "tipo": "briga", "personagens": ["Ninguém"], "descricao": "x", "imagem_en": "x", "duracao": 4}]}
    assert c.post(f"/react-personagens/{pid}/colar/roteiro", json={"texto": json.dumps(rot)}).get_json()["ok"]
    p = R.carregar(pid)
    evs = R.eventos(p)
    assert [e["tipo"] for e in evs] == ["briga", "sai", "volta"]  # o de nome desconhecido sai
    briga = evs[0]
    sakura = R.achar_por_nome(p, "Sakura")["id"]
    assert R.ausencias(p, 20) == {sakura: [[13.0, 17.0]]}
    # 🚀 a imagem da briga vai pro Flow com a sala + os 2 personagens numa colagem de referência
    visto = {}

    class Lote:
        trava = __import__("threading").Lock()
        fila, rodando = [], False

        def adicionar(self, itens, proporcao, quantidade):
            visto["itens"] = itens
            return [{"id": "j1"}]

        def iniciar(self):
            pass
    monkeypatch.setattr(flow_lote, "lote", lambda: Lote())
    assert c.post(f"/react-personagens/{pid}/eventos/gerar", json={}).get_json()["enviadas"] == 1
    it = visto["itens"][0]
    assert "Naruto punches Sasuke" in it["prompt"] and "Sakura" in it["prompt"] and os.path.isfile(it["referencia_arquivo"])
    assert R.evento(R.carregar(pid), briga["id"])["cena"]["estado"] == "fila"
    # sem imagem ainda: o editor avisa e deixa de fora
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    assert any("sem imagem" in a for a in d["avisos"])
    # 📤 imagem enviada por você
    im = io.BytesIO(_png((200, 0, 0), (1280, 720), (90, 10, 10)))
    assert c.post(f"/react-personagens/{pid}/eventos/{briga['id']}/arquivo", data={"arquivo": (im, "b.png")}, content_type="multipart/form-data").get_json()["ok"]
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    ovs = A._JOBS[d["job_id"]]["overlays"]
    cg = next(o for o in ovs if o.get("camada") == "cena")
    assert (cg["start"], cg["end"], cg["size_percent"]) == (7.0, 11.0, 100.0)
    camadas = [o.get("camada") for o in ovs]
    assert camadas.index("cena") > camadas.index("tela") and camadas.index("cena") < camadas.index("legenda")
    for o in ovs:  # 🚪 a Sakura não aparece entre 13 e 17
        if o.get("cid") == sakura and o.get("camada") == "personagem":
            assert o["end"] <= 13.0 or o["start"] >= 17.0
    assert any(o.get("cid") == sakura and o.get("camada") == "personagem" and o["start"] >= 17.0 for o in ovs)
    # o palco mostra a cena e quem está fora
    pe = c.get(f"/react-personagens/{pid}/pecas?t=8").get_json()
    assert pe["cena"]["img"] and "Briga" in pe["cena"]["tipo"]
    pe = c.get(f"/react-personagens/{pid}/pecas?t=14").get_json()
    assert next(x for x in pe["pecas"] if x["chave"] == f"p:{sakura}")["fora"] and not pe["cena"]
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=8").status_code == 200
    # ✏ editar na página mantém a imagem
    p = R.carregar(pid)
    lista = [dict(e, descricao="soco voador") if e["id"] == briga["id"] else e for e in R.eventos(p)][:2]
    assert c.post(f"/react-personagens/{pid}/eventos", json={"eventos": lista}).get_json()["eventos"] == 2
    p = R.carregar(pid)
    assert R.arquivo_cena(p, R.evento(p, briga["id"])) and R.evento(p, briga["id"])["descricao"] == "soco voador"
    assert R.ausencias(p, 20) == {sakura: [[13.0, 20]]}  # sem o "volta": fica fora até o fim
    assert "⚡ Intrigas" in c.get(f"/react-personagens/{pid}").get_data(as_text=True)


def test_render_junta_camadas_em_trilhas_sem_linha_de_comando_gigante(tmp_path, monkeypatch):
    """WinError 206: centenas de "-i pose.png" passavam do limite do Windows. As camadas do react no mesmo lugar viram
    uma trilha (concat) — a troca de pose fica contínua (sem piscar) e a boca alterna igual."""
    import video_assembler as V
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=25:duration=6",
                    "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", base], check=True)
    cores = {"a": (255, 0, 0, 255), "b": (0, 0, 255, 255), "m": (0, 255, 0, 255)}
    for n, c in cores.items():
        Image.new("RGBA", (100, 150), c).save(str(tmp_path / f"{n}.png"))
    ovs = []
    for k in range(120):  # 120 camadas de 0,04 s alternando + uma com boca
        ovs.append({"personagem": "react_personagem", "media_type": "image", "resolved_path": str(tmp_path / ("a.png" if k % 2 else "b.png")),
                    "start": k * 0.02, "end": (k + 1) * 0.02, "size_percent": 30, "x_percent": 50, "y_percent": 50, "ancora": "centro"})
    ovs.append({"personagem": "react_personagem", "media_type": "image", "resolved_path": str(tmp_path / "a.png"), "start": 2.4, "end": 5,
                "size_percent": 30, "x_percent": 50, "y_percent": 50, "ancora": "centro",
                "boca_path": str(tmp_path / "m.png"), "boca_janelas": [[3, 4]]})
    visto = {}
    real = V._run_ffmpeg

    def espia(args, **kw):
        visto["n_i"] = args.count("-i")
        return real(args, **kw)
    monkeypatch.setattr(V, "_run_ffmpeg", espia)
    out = str(tmp_path / "out.mp4")
    V.apply_overlays(base, ovs, out, 320, 180)
    assert visto["n_i"] == 2  # o vídeo base + UMA trilha
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vf", "select='between(t,2.9,3.3)',crop=2:2:160:90,scale=1:1",
                        "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    px = ["G" if r[i + 1] > 200 else "R" if r[i] > 200 else "?" for i in range(0, len(r), 3)]
    assert px[:2] == ["R", "R"] and "G" in px and px.count("G") >= 3  # a boca abre e fecha nas janelas
    assert not [f for f in os.listdir(tmp_path) if f.startswith("_trilha_") and f.endswith(".txt")]


def test_cara_fica_ate_a_proxima_fala_e_muda_no_meio(base):
    p = _proj(base, 2)
    a, b = p["personagens"]
    falas = [{"id": "1", "t": 10.0, "dur": 4.0, "cid": a["id"], "texto": "x", "expressao": "debochado", "expressao_depois": "chocado", "reacoes": [{"cid": b["id"], "expressao": "bravo"}]},
             {"id": "2", "t": 30.0, "dur": 3.0, "cid": a["id"], "texto": "y", "expressao": "feliz", "reacoes": []}]
    ls = R.linhas_personagens(p, falas, 60)
    la = ls[a["id"]]
    assert [e["expressao"] for e in la] == ["neutro", "debochado", "chocado", "feliz"]  # sem voltar pro neutro entre as falas
    assert la[2]["end"] == la[3]["start"] and la[2]["start"] < 14  # o 'chocado' começa no meio da fala e fica até a próxima
    assert la[-1]["end"] == 60 and la[1]["bocas"] and la[2]["bocas"]
    assert [e["expressao"] for e in ls[b["id"]]] == ["neutro", "bravo"]  # a reação fica
    # 📐 a pose deslocada se encaixa no lugar da neutra
    from PIL import Image as I
    n = I.new("RGBA", (300, 450), (0, 0, 0, 0))
    n.paste((255, 0, 0, 255), (100, 100, 200, 450))
    x = I.new("RGBA", (300, 450), (0, 0, 0, 0))
    x.paste((0, 0, 255, 255), (130, 80, 230, 430))
    cn, cx = os.path.join(base, "n.png"), os.path.join(base, "x.png")
    n.save(cn)
    x.save(cx)
    ref = (n.size, R._ancora_alfa(n))
    feito = R.alinhar_pose(cx, ref, os.path.join(base, "x_al.png"))
    assert R._ancora_alfa(I.open(feito)) == R._ancora_alfa(n)


def test_momentos_especiais_e_leitura_do_video(base, tmp_path, monkeypatch):
    import app as A
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 20)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "AMV", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    for nome in ("Gojo", "Sukuna"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": nome})
    p = R.carregar(pid)
    gojo, sukuna = [x["id"] for x in p["personagens"]]
    # 👁 a IA "assiste" (quadros + transcrição) e o roteiro recebe o que ela leu
    import ia_servico
    chamadas = []

    def falsa(recurso, system, conteudo, **kw):
        chamadas.append(system)
        if "QUADROS" in system:
            return {"momentos": [{"tempo": 3, "o_que_acontece": "Sukuna corta o prédio ao meio", "texto_na_tela": "Fukuma Mizushi",
                                  "quem_aparece": "Sukuna", "clima": "épico"}]}
        return None
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    r = R.ler_video(pid)
    assert r["feitos"] == 1 and "QUADROS" in chamadas[0]
    pr = R.prompt_roteiro_parte(R.carregar(pid), 0)
    assert "Fukuma Mizushi" in pr and "Sukuna corta o prédio" in pr
    assert R.ler_video(pid)["feitos"] == 0  # já lido: não gasta de novo
    assert "estilo_arte" in R._schema_roteiro(["neutro"])["properties"]["eventos"]["items"]["required"]
    p = R.carregar(pid)
    assert "interacao" in R.sys_roteiro(p) and "QUEBRA DE EXPECTATIVA" in R.sys_roteiro(p)
    # 🤝 interação (tela) · 🖼 foto (quadro) · 🎨 desenhado diferente (no lugar)
    p["roteiro"]["falas"] = [{"id": "f1", "t": 1.0, "dur": 2.0, "cid": gojo, "texto": "Relaxa.", "expressao": "debochado", "reacoes": [], "cta": True}]
    R.salvar_eventos(p, [{"tipo": "interacao", "t": 2, "dur": 3, "cids": [gojo, sukuna], "descricao": "abraço"},
                         {"tipo": "foto", "t": 8, "dur": 3, "cids": [gojo], "descricao": "Gojo de terno", "imagem_en": "Gojo in a suit"},
                         {"tipo": "estilo", "t": 13, "dur": 3, "cids": [sukuna, gojo], "descricao": "pintura", "estilo_arte": "pintura_antiga"}])
    R.salvar(p)
    evs = R.eventos(R.carregar(pid))
    assert evs[2]["cids"] == [sukuna] and evs[2]["estilo_arte"] == "pintura_antiga"
    assert "Renaissance" in R.prompt_cena(p, evs[2]) and "chroma-key green" in R.prompt_cena(p, evs[2])
    assert "visual example" in R.prompt_cena(p, evs[1])
    for e, im in ((evs[0], _png((0, 200, 0), (1280, 720), (0, 90, 0))), (evs[1], _png((0, 0, 200), (800, 600), (0, 0, 90))),
                  (evs[2], _png((200, 200, 0), (300, 450), (0, 255, 0)))):
        assert c.post(f"/react-personagens/{pid}/eventos/{e['id']}/arquivo", data={"arquivo": (io.BytesIO(im), "x.png")},
                      content_type="multipart/form-data").get_json()["ok"]
    pe = c.get(f"/react-personagens/{pid}/pecas?t=9").get_json()
    foto = next(x for x in pe["pecas"] if x["chave"] == "foto")
    assert foto["img"] and foto["ativa"] and "foto" in pe["pilha"]["ordem"]
    pe = c.get(f"/react-personagens/{pid}/pecas?t=14").get_json()
    assert next(x for x in pe["pecas"] if x["chave"] == f"p:{sukuna}")["estilo"]
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": "foto", "cx": 300, "cy": 250, "w": 500}).get_json()["ok"]
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    ovs = A._JOBS[d["job_id"]]["overlays"]
    fo = next(o for o in ovs if o.get("camada") == "foto")
    assert (fo["start"], fo["end"], round(fo["x_percent"], 2)) == (8.0, 11.0, round(300 / 1920 * 100, 2))
    assert any(o.get("camada") == "cena" and o["start"] == 2.0 for o in ovs)
    est = [o for o in ovs if o.get("expressao") == "estilo"]
    assert len(est) == 1 and (est[0]["start"], est[0]["end"]) == (13.0, 16.0)
    for o in ovs:  # o Sukuna normal some enquanto está "pintado"
        if o.get("cid") == sukuna and o.get("camada") == "personagem" and o.get("expressao") != "estilo":
            assert o["end"] <= 13.0 or o["start"] >= 16.0
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=9").status_code == 200
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=14").status_code == 200


def test_duplicar_mesa_tv_e_personagem(base, tmp_path):
    """⧉ Duplicar qualquer camada: a cópia nasce ao lado, mexe sozinha, entra na pilha acima da original e vai pro editor."""
    import app as A
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 10)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "Dup", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    c.post(f"/react-personagens/{pid}/personagem", json={"nome": "Goku"})
    p = R.carregar(pid)
    goku = p["personagens"][0]["id"]
    R.guardar_ref(p, p["personagens"][0], _png(), "a.png")
    p["roteiro"]["falas"] = [{"id": "f1", "t": 1.0, "dur": 2.0, "cid": goku, "texto": "Oi!", "expressao": "feliz", "reacoes": [], "cta": True}]
    R.salvar(p)
    for q, im in (("fundo", _png((30, 30, 60), (640, 360), (10, 10, 10))), ("sofa", _png((80, 80, 90), (600, 300))), ("mesa", _png((120, 70, 40), (600, 200)))):
        c.post(f"/react-personagens/{pid}/cenario/{q}/arquivo", data={"arquivo": (io.BytesIO(im), "x.png")}, content_type="multipart/form-data")
    mesa2 = c.post(f"/react-personagens/{pid}/duplicar", json={"chave": "mesa"}).get_json()["chave"]
    tv2 = c.post(f"/react-personagens/{pid}/duplicar", json={"chave": "tela"}).get_json()["chave"]
    clone = c.post(f"/react-personagens/{pid}/duplicar", json={"chave": f"p:{goku}"}).get_json()["chave"]
    mesa3 = c.post(f"/react-personagens/{pid}/duplicar", json={"chave": mesa2}).get_json()["chave"]
    assert not c.post(f"/react-personagens/{pid}/duplicar", json={"chave": "legenda"}).get_json()["ok"]
    p = R.carregar(pid)
    lay = R.disposicao(p)
    m2 = next(x for x in lay["copias"] if x["chave"] == mesa2)
    assert m2["cx"] == lay["mesa"]["cx"] + 0.05 * 1920 and m2["w"] == lay["mesa"]["w"]
    m3 = next(x for x in lay["copias"] if x["chave"] == mesa3)
    assert m3["cx"] > m2["cx"] and m3["de"] == "mesa"  # cópia da cópia nasce ao lado dela
    ordem = R.pilha(p, lay)["ordem"]
    assert ordem.index(mesa2) == ordem.index("mesa") + 1 or ordem.index(mesa3) == ordem.index("mesa") + 1
    # mexe na cópia: muda só ela, e vira (a mesa espelhada)
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": mesa2, "cx": 300, "cy": 900, "w": 500, "lado": "esq"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": clone, "cx": 1500, "cy": 700, "w": 300, "lado": "esq"}).get_json()["ok"]
    pe = c.get(f"/react-personagens/{pid}/pecas?t=1.5").get_json()
    pc = {x["chave"]: x for x in pe["pecas"]}
    assert pc[mesa2]["cx"] == 300 and pc[mesa2]["copia"] and pc["mesa"]["cx"] != 300
    assert pc[clone]["personagem"] and pc[clone]["expressao"] == "feliz" and pc[clone]["lado"] == "esq"
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=1.5").status_code == 200
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    ovs = A._JOBS[d["job_id"]]["overlays"]
    om = [o for o in ovs if o.get("copia") == mesa2]
    assert len(om) == 1 and round(om[0]["x_percent"], 2) == round(300 / 1920 * 100, 2) and om[0]["espelhar"]
    ov_tv = [o for o in ovs if o.get("copia") == tv2]
    assert any(o.get("media_type") == "video" and o.get("sincronizar") for o in ov_tv)  # a TV duplicada passa o vídeo também
    oc = [o for o in ovs if o.get("copia") == clone]
    assert oc and all(o["trilha"].endswith(clone[2:]) for o in oc) and all(round(o["x_percent"], 1) == round(1500 / 19.2, 1) for o in oc)
    # apagar a cópia; a original não se apaga
    assert c.post(f"/react-personagens/{pid}/duplicar", json={"apagar": mesa2}).get_json()["ok"]
    assert not c.post(f"/react-personagens/{pid}/duplicar", json={"apagar": "mesa"}).get_json()["ok"]
    assert mesa2 not in R.pilha(R.carregar(pid), R.disposicao(R.carregar(pid)))["ordem"]
    assert "⧉ Duplicar" in c.get(f"/react-personagens/{pid}").get_data(as_text=True)


def test_espelhar_qualquer_camada_e_refazer_pose(base, tmp_path, monkeypatch):
    import app as A
    import personagens_pod as pp
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 8)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "Esp", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    c.post(f"/react-personagens/{pid}/personagem", json={"nome": "Kenpachi"})
    p = R.carregar(pid)
    ken = p["personagens"][0]["id"]
    R.guardar_ref(p, p["personagens"][0], _png(), "a.png")
    p["roteiro"]["falas"] = [{"id": "f1", "t": 1.0, "dur": 2.0, "cid": ken, "texto": "Luta!", "expressao": "feliz", "reacoes": [], "cta": True}]
    R.salvar(p)
    for q, im in (("fundo", _png((30, 30, 60), (640, 360), (10, 10, 10))), ("mesa", _png((120, 70, 40), (600, 200)))):
        c.post(f"/react-personagens/{pid}/cenario/{q}/arquivo", data={"arquivo": (io.BytesIO(im), "x.png")}, content_type="multipart/form-data")
    for chave in ("mesa", "tela", "foto", "fundo"):
        assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": chave, "lado": "esq"}).get_json()["ok"]
    lay = R.disposicao(R.carregar(pid))
    assert lay["mesa"]["espelhar"] and lay["tela"]["espelhar"] and lay["foto"]["espelhar"] and lay["fundo"]["espelhar"]
    pe = c.get(f"/react-personagens/{pid}/pecas").get_json()
    assert pe["fundo_espelhar"] and next(x for x in pe["pecas"] if x["chave"] == "mesa")["espelhar"]
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=1.5").status_code == 200
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    job = A._JOBS[d["job_id"]]
    ovs = job["overlays"]
    assert next(o for o in ovs if o.get("camada") == "mesa")["espelhar"]
    assert next(o for o in ovs if o.get("origem") == "react_tela")["espelhar"]
    # o fundo do editor sai espelhado
    from PIL import Image as I
    fundo_job = job["pending_segments"][0]["override_source"]["value"]
    orig = I.open(R.camada_arquivo(R.carregar(pid), "fundo")).convert("RGB").resize((1920, 1080))
    assert I.open(fundo_job).convert("RGB").getpixel((60, 300)) == orig.getpixel((1859, 300))
    # 🔁 refazer UMA pose (vai junto a boca dela)
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    assert c.post(f"/react-personagens/{pid}/poses/gerar", json={"cids": [ken]}).get_json()["ok"]
    visto = {}
    monkeypatch.setattr(pp, "enviar", lambda ppid, arquivos, extra="", base=None, **k: visto.update(arq=arquivos, extra=extra) or {"ok": True})
    proj = pp.carregar(R.personagem(R.carregar(pid), ken)["pod"]["pid"])
    pose = next(x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose" and "feliz" in x["arquivo"])
    r = c.post(f"/react-personagens/{pid}/pose/{ken}/refazer", json={"arquivo": pose, "pedido": "sem o tapa-olho"}).get_json()
    assert r["ok"] and visto["arq"][0] == pose and visto["extra"] == "sem o tapa-olho"
    assert not c.post(f"/react-personagens/{pid}/pose/{ken}/refazer", json={"arquivo": "nada.png"}).get_json()["ok"]


def test_poses_viradas_pro_lado_errado_sao_espelhadas(base, monkeypatch):
    """🧭 O Flow às vezes desenha a pose virada pro outro lado: a IA confere (ou você marca ↔) e o react espelha só
    aquela pose — virar o personagem continua funcionando mesmo quando as poses do outro lado vieram erradas."""
    import personagens_pod as pp
    import ia_servico
    p = _proj(base, 2)
    p["expressoes"] = ["neutro", "feliz"]
    R.salvar(p, base)
    ch = p["personagens"][1]
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    R.criar_poses(p["id"], ch["id"], base)
    p = R.carregar(p["id"], base)
    p["layout"] = "dois_sofas"
    R.salvar(p, base)
    R.criar_poses(p["id"], ch["id"], base)  # + as do lado esquerdo
    p = R.carregar(p["id"], base)
    ch = R.personagem(p, ch["id"])
    proj = pp.carregar(ch["pod"]["pid"], base)
    assert any("_esq" in x["arquivo"] for x in proj["dados"]["poses"])
    for x in proj["dados"]["poses"]:
        local = x["arquivo"][:-4] + "_v1.png"
        Image.new("RGBA", (300, 450), (0, 0, 200, 255)).save(os.path.join(pp._pasta(proj["id"], base), "imagens", local))
        proj["imagens"][x["arquivo"]].update(estado="pronta", versoes=[{"local": local}], atual=0)
    pp.salvar(proj, base)
    poses = R.poses_do_personagem(ch, base, "dir")
    assert not poses["neutro"]["espelhar"] and poses["neutro"]["virada"] == "dir"
    # a IA diz que a 'feliz' veio virada pra esquerda
    nomes = [x["arquivo"] for x in proj["dados"]["poses"] if x.get("tipo") == "pose"]

    def falsa(recurso, system, conteudo, **kw):
        assert conteudo[1]["type"] == "image"
        n = int(conteudo[0]["text"].split()[0])
        return {"figuras": [{"n": k + 1, "lado": "direita"} for k in range(n)]}
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    r = R.conferir_lados(p["id"], ch["id"], base)
    assert r["conferidas"] == len([n for n in nomes if "_boca" not in n])
    p = R.carregar(p["id"], base)
    feliz = next(n for n in nomes if "feliz" in n and "_esq" not in n)
    assert R.marcar_virada(p, ch["id"], feliz, base) == "esq"  # ↔ você corrige uma
    R.salvar(p, base)
    ch = R.personagem(R.carregar(p["id"], base), ch["id"])
    pd = R.poses_do_personagem(ch, base, "dir")
    assert not pd["neutro"]["espelhar"]
    # pra 'feliz' olhando pra direita: a do arquivo da direita está virada errada → usa outra que olha pra direita
    assert pd["feliz"]["virada"] == "dir" and not pd["feliz"]["espelhar"]
    # olhando pra esquerda: as _esq vieram viradas pra DIREITA (a IA disse) → são espelhadas
    pe = R.poses_do_personagem(ch, base, "esq")
    assert pe["neutro"]["espelhar"] and pe["feliz"]["virada"] == "esq" and not pe["feliz"]["espelhar"]


def test_imagem_parada_entra_como_um_quadro_e_aparece_so_na_janela(tmp_path, monkeypatch):
    """'Cannot allocate memory' num vídeo de 10 min: cada camada parada com -loop 1 virava 25 quadros/s. Agora entra
    UM quadro (o overlay repete) — e continua aparecendo só na janela dela, com a boca alternando."""
    import video_assembler as V
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=25:duration=6",
                    "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", base], check=True)
    for n, cor in (("a", (255, 0, 0, 255)), ("m", (0, 255, 0, 255)), ("f", (0, 0, 255, 255))):
        Image.new("RGBA", (100, 150), cor).save(str(tmp_path / f"{n}.png"))
    ovs = [{"personagem": "react_personagem", "media_type": "image", "resolved_path": str(tmp_path / "a.png"), "start": 2, "end": 4.5,
            "size_percent": 30, "x_percent": 30, "y_percent": 50, "ancora": "centro",
            "boca_path": str(tmp_path / "m.png"), "boca_janelas": [[3, 4]]},
           {"media_type": "image", "resolved_path": str(tmp_path / "f.png"), "start": 1, "end": 2, "size_percent": 20,
            "x_percent": 80, "y_percent": 50, "ancora": "centro"}]
    visto = {}
    real = V._run_ffmpeg

    def espia(args, **kw):
        visto["loop"] = args.count("-loop")
        return real(args, **kw)
    monkeypatch.setattr(V, "_run_ffmpeg", espia)
    out = str(tmp_path / "out.mp4")
    V.apply_overlays(base, ovs, out, 320, 180)
    assert visto["loop"] == 0

    def px(t, x):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", out, "-frames:v", "1", "-vf", f"crop=2:2:{x}:90",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return tuple(r[:3])
    assert px(1.0, 96)[0] < 200 and px(2.5, 96)[0] > 200 and px(5.0, 96)[0] < 200  # o personagem só na janela
    assert px(1.5, 256)[2] > 200 and px(3.0, 256)[2] < 200  # a imagem comum também
    assert px(3.04, 96)[1] > 200 or px(3.2, 96)[1] > 200  # a boca abre


def test_thumbnail_do_react_vira_capa_da_publicacao(base, tmp_path, monkeypatch):
    """🖼 Capa no padrão dos reacts: os escolhidos de um lado (com a cara escolhida), o quadro do vídeo do outro — entra
    nas capas da 📣 publicação do react (texto, versões, Flow)."""
    import app as A
    import flow_lote
    import publicacao as PB
    monkeypatch.setattr(PB, "RAIZ", "publicacoes_teste_" + os.path.basename(str(tmp_path)))
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 8)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "Bleach TYBW", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    for nome in ("Ichigo", "Kenpachi", "Gojo"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": nome})
    p = R.carregar(pid)
    for ch, cor in zip(p["personagens"], ((250, 140, 0), (30, 30, 30), (240, 240, 250))):
        R.guardar_ref(p, ch, _png(cor), "a.png")
    R.salvar(p)
    try:
        html = c.get(f"/react-personagens/{pid}").get_data(as_text=True)
        assert "🖼 Thumbnail e publicação" in html and f"/publicacoes/{pid}/api" in html
        cids = [x["id"] for x in p["personagens"]]
        e = c.post(f"/react-personagens/{pid}/capa/estado", json={"cids": cids, "t": 3, "lado": "direita", "seta": True}).get_json()
        chaves = [x["chave"] for x in e["pecas"]]
        assert chaves[0] == "quadro" and chaves[-1] == "seta" and chaves[-2] == f"p:{cids[0]}"  # o 1º na frente dos outros
        figs = {x["chave"]: x for x in e["pecas"] if x["chave"].startswith("p:")}
        # lado a lado: cada um cobre no máximo ~30% do vizinho
        a, b = figs[f"p:{cids[0]}"], figs[f"p:{cids[1]}"]
        sobre = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
        assert sobre <= 0.32 * min(a["w"], b["w"])
        assert c.get(e["pecas"][0]["img"]).status_code == 200
        # 📤 uma imagem sua (PNG transparente entra recortado) e mexer nela
        e = c.post(f"/react-personagens/{pid}/capa/imagem", data={"arquivo": (io.BytesIO(_png((0, 200, 0))), "x.png")},
                   content_type="multipart/form-data").get_json()
        assert "imagem" in [x["chave"] for x in e["pecas"]]
        e = c.post(f"/react-personagens/{pid}/capa/estado", json={"pos": {"imagem": {"x": 50, "y": 40, "w": 300}}}).get_json()
        im_p = next(x for x in e["pecas"] if x["chave"] == "imagem")
        assert (im_p["x"], im_p["y"], im_p["w"]) == (50, 40, 300) and im_p["ajustada"]
        e = c.post(f"/react-personagens/{pid}/capa/estado", json={"quadro_off": True}).get_json()
        assert "quadro" not in [x["chave"] for x in e["pecas"]] and e["cfg"]["quadro_off"]
        e = c.post(f"/react-personagens/{pid}/capa/estado", json={"quadro_off": False, "ocultas": ["seta"]}).get_json()
        assert next(x for x in e["pecas"] if x["chave"] == "seta")["oculta"]
        r = c.get(f"/react-personagens/{pid}/capa/previa.jpg")
        assert r.status_code == 200
        im = Image.open(io.BytesIO(r.data))
        assert im.size == (1280, 720)
        assert im.convert("RGB").getpixel((200, 190))[1] > 150  # a imagem enviada (verde) onde você pôs
        d = c.post(f"/react-personagens/{pid}/capa", json={"cids": cids[:2], "exprs": {cids[0]: "chocado"}, "t": 3, "lado": "direita",
                                                          "texto": "ELES SURTARAM"}).get_json()
        assert d["ok"] and d["n"] == 1
        pub = c.get(f"/publicacoes/{pid}/api").get_json()
        capa = next(x for x in pub["capas"] if x["n"] == 1)
        assert capa["status"] == "pronta" and capa["texto"] == "ELES SURTARAM"
        assert c.get(f"/publicacoes/{pid}/api/capa/1/final").status_code == 200
        # personagens do react no contexto da publicação (pras ideias de capa da IA)
        assert [x["nome"] for x in PB.carregar_ctx(PB.pdir_de(R._BASE if False else A.BASE_DIR, pid))["ctx"]["personagens"]] == ["Ichigo", "Kenpachi", "Gojo"]
        # 🎨 Flow: o rascunho vai de referência
        visto = {}

        class Lote:
            trava = __import__("threading").Lock()
            fila, rodando = [], False

            def adicionar(self, itens, **k):
                visto["it"] = itens[0]
                return [{"id": "jcapa"}]

            def iniciar(self):
                pass
        monkeypatch.setattr(flow_lote, "lote", lambda: Lote())
        d = c.post(f"/react-personagens/{pid}/capa", json={"cids": [cids[2]], "t": 2, "lado": "esquerda", "modo": "flow",
                                                          "pedido": "raios atrás"}).get_json()
        assert d["ok"] and "REACTION" in visto["it"]["prompt"] and "raios atrás" in visto["it"]["prompt"]
        assert os.path.isfile(visto["it"]["referencia_arquivo"])
        assert c.post(f"/react-personagens/{pid}/capa/imagem", json={"apagar": True}).get_json()["ok"]
        assert not c.post(f"/react-personagens/{pid}/capa", json={"cids": []}).get_json()["ok"]
    finally:
        import shutil
        shutil.rmtree(os.path.join(A.BASE_DIR, PB.RAIZ), ignore_errors=True)


def test_biblia_da_obra_e_do_personagem_guiam_a_ia(base, monkeypatch):
    """📖 Obra pouco conhecida: o material colado (episódios do ANN, personalidade de cada um) vira a FONTE PRINCIPAL
    das sugestões, fichas, roteiro, verificador e leitura do vídeo — e a IA pode organizar e completar as fichas."""
    import app as A
    import ia_servico
    c = A.app.test_client()
    pid = c.post("/react-personagens/novo", data={"titulo": "Dark Summoner OP", "transcricao": "0:01 a\n0:30 b"},
                 content_type="multipart/form-data").headers["Location"].split("/")[-1]
    for nome in ("Amona", "Roni"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": nome})
    texto = ("Amona is a demi-human dark summoner who joins the party of the righteous cleric Roni. Episode 1: they bicker "
             "and end up together at the inn. Episode 2: trapped in a dungeon room; Imp offers help. Eury is the sane one.")
    assert c.post(f"/react-personagens/{pid}/dados", json={"biblia": texto}).get_json()["ok"]
    p = R.carregar(pid)
    roni = R.achar_por_nome(p, "Roni")["id"]
    assert c.post(f"/react-personagens/{pid}/personagem/{roni}", json={"biblia": "certinho e religioso; fica vermelho e nega tudo"}).get_json()["ok"]
    p = R.carregar(pid)
    pr = R.prompt_roteiro_parte(p, 0)
    assert "📖 BÍBLIA DA OBRA" in pr and "righteous cleric" in pr and "fica vermelho e nega tudo" in pr
    assert "BÍBLIA" in R.sys_roteiro(p)
    assert "righteous cleric" in R.prompt_sugestoes(p) and "righteous cleric" in R.prompt_fichas(p, [roni])
    assert "Bíblia" in R.prompt_checagem(p, "fichas") and "fica vermelho" in R.prompt_checagem(p, "fichas")
    # o estado não carrega o texto inteiro a cada atualização; a página mostra
    e = c.get(f"/react-personagens/{pid}/estado").get_json()
    assert "biblia" not in e and e["biblia_info"]["chars"] == len(texto)
    assert "righteous cleric" in c.get(f"/react-personagens/{pid}").get_data(as_text=True)
    # 🤖 organizar: episódios, personagens, e as fichas vazias se completam
    def falsa(recurso, system, conteudo, **kw):
        assert "BÍBLIA" in system
        return {"obra": "I'm Dating a Dark Summoner", "sinopse": "s", "tom": "comédia romântica adulta",
                "episodios": [{"ep": "1", "o_que_acontece": "brigam e acabam juntos"}],
                "personagens": [{"nome": "Amona", "quem_e": "invocadora sombria", "personalidade": "sarcástica e provocadora",
                                 "jeito_de_falar": "debochada", "relacoes": "briga e se envolve com Roni"},
                                {"nome": "Roni", "quem_e": "clérigo", "personalidade": "certinho", "jeito_de_falar": "formal",
                                 "relacoes": "Amona"}],
                "piadas_recorrentes": ["o Imp fala tudo errado"]}
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    r = R.resumir_biblia(pid)
    assert r["fichas"] == 2
    p = R.carregar(pid)
    amona = R.achar_por_nome(p, "Amona")
    assert amona["personalidade"] == "sarcástica e provocadora" and p["obra"] == "I'm Dating a Dark Summoner"
    assert "o Imp fala tudo errado" in R.biblia_bloco(p)
    # mudou o texto depois de organizar: avisa
    c.post(f"/react-personagens/{pid}/dados", json={"biblia": texto + " Episode 3: more."})
    assert c.get(f"/react-personagens/{pid}/estado").get_json()["biblia_info"]["desatualizado"]
    r = c.post(f"/react-personagens/{pid}/biblia/arquivo", data={"arquivo": (io.BytesIO("Episódio 4: praia.".encode()), "b.txt")},
               content_type="multipart/form-data").get_json()
    assert r["ok"] and r["texto"].endswith("Episódio 4: praia.")


def test_itens_da_mesa_mesa_por_sofa_mapa_e_poderes(base, tmp_path, monkeypatch):
    """🍿 v84_238i: itens da mesa (camadas em cima da mesa escolhida), uma mesa por sofá nos dois sofás, o mapa da sala
    e os ⚡ poderes no roteiro e nas imagens; a imagem da briga leva o QUADRO ATUAL do react como referência."""
    import app as A
    import flow_lote
    import react_objetos as RO
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 10)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "Mesa", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    for n in ("Tatsumaki", "Luffy", "Saitama", "Genos"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": n})
    p = R.carregar(pid)
    tats, luffy = p["personagens"][0], p["personagens"][1]
    tats.update(poderes="telecinese", poderes_en="psychic telekinesis with a green glow, levitates objects")
    luffy.update(poderes="corpo de borracha", poderes_en="rubber body, stretches his arms across the room, toon face")
    p["layout"] = "dois_sofas"
    for x in p["personagens"]:
        R.guardar_ref(p, x, _png(), "a.png")
    p["roteiro"]["falas"] = [{"id": "f1", "t": 1.0, "dur": 2.0, "cid": tats["id"], "texto": "Oi!", "expressao": "feliz", "reacoes": [], "cta": True}]
    R.salvar(p)
    for q, im in (("fundo", _png((30, 30, 60), (640, 360), (10, 10, 10))), ("sofa", _png((80, 80, 90), (600, 300))), ("mesa", _png((120, 70, 40), (600, 200)))):
        c.post(f"/react-personagens/{pid}/cenario/{q}/arquivo", data={"arquivo": (io.BytesIO(im), "x.png")}, content_type="multipart/form-data")
    lay = R.disposicao(R.carregar(pid))
    m2 = next(x for x in lay["copias"] if x["chave"] == "c:mesa2")
    assert lay["mesa"]["cx"] < 960 < m2["cx"] and m2["espelhar"]  # uma mesa na frente de cada sofá
    # itens: um em cada mesa
    assert c.post(f"/react-personagens/{pid}/objetos", json={"acao": "novo", "nome": "Pipoca", "en": "a bowl of popcorn", "mesa": "mesa"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/objetos", json={"acao": "novo", "nome": "Refrigerante", "en": "two soda cans", "mesa": "c:mesa2"}).get_json()["ok"]
    pedidos = []

    class Lote:
        def adicionar(self, itens, **kw):
            pedidos.extend(itens)
            return [{"id": f"j{i}"} for i in range(len(itens))]

        def iniciar(self):
            pass
    monkeypatch.setattr(flow_lote, "lote", lambda: Lote())
    assert c.post(f"/react-personagens/{pid}/objetos/gerar", json={}).get_json()["enviadas"] == 2
    assert "chroma-key green" in pedidos[0]["prompt"] and "popcorn" in pedidos[0]["prompt"]
    assert "EMPTY top" in R.prompt_camada(R.carregar(pid), "mesa")
    for o in R.carregar(pid)["objetos"]:
        c.post(f"/react-personagens/{pid}/objetos/{o['id']}/arquivo", data={"arquivo": (io.BytesIO(_png((250, 220, 90), (200, 160))), "o.png")},
               content_type="multipart/form-data")
    p = R.carregar(pid)
    lay = R.disposicao(p)
    obs = {o["nome"]: o for o in lay["objetos"]}
    assert abs(obs["Pipoca"]["cx"] - lay["mesa"]["cx"]) < lay["mesa"]["w"] / 2 and abs(obs["Refrigerante"]["cx"] - m2["cx"]) < m2["w"] / 2
    assert obs["Pipoca"]["cy"] < lay["mesa"]["cy"]  # em cima do tampo
    ordem = R.pilha(p, lay)["ordem"]
    assert ordem.index(obs["Pipoca"]["chave"]) > ordem.index("mesa")
    # arrastar um item
    assert c.post(f"/react-personagens/{pid}/posicao", json={"chave": obs["Pipoca"]["chave"], "cx": 500, "cy": 800, "w": 120}).get_json()["ok"]
    pe = {x["chave"]: x for x in c.get(f"/react-personagens/{pid}/pecas?t=1.5").get_json()["pecas"]}
    assert pe[obs["Pipoca"]["chave"]]["cx"] == 500 and "c:mesa2" in pe
    assert c.get(f"/react-personagens/{pid}/previa.jpg?t=1.5").status_code == 200
    d = c.post(f"/react-personagens/{pid}/editor", json={}).get_json()
    ovs = A._JOBS[d["job_id"]]["overlays"]
    assert sum(1 for o in ovs if o.get("camada") == "objeto") == 2
    # o mapa e os poderes vão pro roteiro e pra imagem; a referência é o quadro atual
    mapa = RO.mapa(p, lay)
    assert "Tatsumaki" in mapa and "popcorn" in mapa and "TV" in mapa
    assert "MAPA DA SALA" in R.prompt_roteiro_parte(p, 0) and "poderes/jeito: telecinese" in R.prompt_roteiro_parte(p, 0)
    assert "OBJETOS E PODERES" in R.sys_roteiro(dict(p, intriga="media"))
    e = R.novo_evento("interacao", 2.0, [tats["id"], luffy["id"]], "ela levita a pipoca", "Tatsumaki levitates the popcorn to Luffy")
    pr = R.prompt_cena(p, e)
    assert "SCENE LAYOUT" in pr and "green glow" in pr and "rubber body" in pr and "CURRENT FRAME" in pr
    ref = R.colagem_referencia(p, e, str(tmp_path / "ref.png"), R._BASE)
    assert ref and os.path.isfile(ref)
    # desligar a mesa por sofá
    assert c.post(f"/react-personagens/{pid}/objetos", json={"mesa_por_sofa": False}).get_json()["ok"]
    assert not any(x["chave"] == "c:mesa2" for x in R.disposicao(R.carregar(pid))["copias"])


def test_marcacoes_no_tempo_viram_ordem_pro_roteiro(base, tmp_path):
    """📌 v84_238k: marcar um segundo com observação (vídeo / quem fala / quem aparece) ou uma fala pra um personagem;
    vai pro pedido da parte certa do roteiro e a fala EXATA entra mesmo se a IA esquecer."""
    import app as A
    c = A.app.test_client()
    video = _video(str(tmp_path / "v.mp4"), 10)
    with open(video, "rb") as f:
        pid = c.post("/react-personagens/novo", data={"titulo": "Notas", "video_arquivo": (f, "v.mp4"), "transcricao": "0:01 a"},
                     content_type="multipart/form-data").headers["Location"].split("/")[-1]
    for n in ("Naruto", "Sasuke"):
        c.post(f"/react-personagens/{pid}/personagem", json={"nome": n})
    p = R.carregar(pid)
    nar, sas = p["personagens"][0]["id"], p["personagens"][1]["id"]
    assert c.post(f"/react-personagens/{pid}/notas", json={"t": "0:03", "tipo": "aparece", "texto": "o Itachi de criança"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/notas", json={"t": "0:05", "tipo": "quem_fala", "texto": "quem canta é o Gojo"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/notas", json={"t": "6", "tipo": "fala", "texto": "Eu falei que ele ia voltar!", "cids": [nar], "exata": True}).get_json()["ok"]
    assert not c.post(f"/react-personagens/{pid}/notas", json={"t": "7", "tipo": "fala", "texto": "x"}).get_json()["ok"]  # fala sem quem
    p = R.carregar(pid)
    assert [n["tipo"] for n in p["notas"]] == ["aparece", "quem_fala", "fala"]
    pr = R.prompt_roteiro_parte(p, 0)
    assert "MARCAÇÕES DO AUTOR" in pr and "Naruto DIZ EXATAMENTE: “Eu falei que ele ia voltar!”" in pr and "Itachi de criança" in pr
    assert "MARCAÇÕES DO AUTOR (se vierem" in R.sys_roteiro(p)
    # a IA esqueceu a fala exata → entra sozinha no segundo marcado
    R.aplicar_roteiro(p, {"falas": [{"personagem": "Sasuke", "tempo": 2, "texto": "Hm.", "expressao": "debochado"}]}, [0.0, 10.0])
    fs = p["roteiro"]["falas"]
    assert any(f["cid"] == nar and f["texto"] == "Eu falei que ele ia voltar!" and f["t"] == 6.0 for f in fs)
    # apagar
    nid = p["notas"][0]["id"]
    R.salvar(p)
    assert c.post(f"/react-personagens/{pid}/notas", json={"acao": "apagar", "id": nid}).get_json()["ok"]
    assert len(R.carregar(pid)["notas"]) == 2 and "Marcações num segundo" in c.get(f"/react-personagens/{pid}").get_data(as_text=True)


def test_quem_senta_onde_imagens_desligadas_e_maximo(base, tmp_path):
    """🛋 v84_238l: escolher a ordem e o sofá de cada um (os ajustes à mão dos personagens voltam pro automático);
    🖼 desligar as imagens de destaque; máximo de personagens."""
    p = _proj(base, 4)
    ids = [c["id"] for c in p["personagens"]]
    p["layout"] = "dois_sofas"
    assert R.sofas_de(p, "dois_sofas") == [ids[:2], ids[2:]]
    p.setdefault("posicoes", {})["dois_sofas"] = {f"p:{ids[0]}": {"cx": 100}, "mesa": {"cx": 300}}
    R.guardar_assentos(p, [[ids[3], ids[0]], [ids[1]]])  # o 3º (ids[2]) não foi mandado → entra no sofá mais vazio
    assert R.sofas_de(p, "dois_sofas") == [[ids[3], ids[0]], [ids[1], ids[2]]]
    assert f"p:{ids[0]}" not in p["posicoes"]["dois_sofas"] and "mesa" in p["posicoes"]["dois_sofas"]
    lay = R.disposicao(p)
    xs = {a["cid"]: a["cx"] for a in lay["assentos"]}
    assert xs[ids[3]] < xs[ids[0]] < 960 < xs[ids[1]] < xs[ids[2]]
    # num sofá só: junta na mesma ordem
    p["layout"] = "sofa_tv"
    p["assentos"]["sofa_tv"] = [[ids[2], ids[1], ids[0], ids[3]]]
    xs = {a["cid"]: a["cx"] for a in R.disposicao(p)["assentos"]}
    assert xs[ids[2]] < xs[ids[1]] < xs[ids[0]] < xs[ids[3]]
    # 🖼 imagens desligadas
    p["imagens_destaque"] = False
    evs = R.ler_eventos(p, [{"tipo": "briga", "tempo": 5, "personagens": [p["personagens"][0]["nome"], p["personagens"][1]["nome"]]},
                            {"tipo": "sai", "tempo": 9, "personagens": [p["personagens"][0]["nome"]]}])
    assert [e["tipo"] for e in evs] == ["sai"] and "SEM IMAGEM" in R._regra_intriga(dict(p, intriga="media"))
    p["roteiro"] = {"eventos": [R.novo_evento("briga", 2.0, ids[:2])]}
    assert R.cena_ativa(p, 3.0) is None
    # máximo
    for k in range(R.MAXIMO_LAYOUT[R.layout_de(p)] - len(p["personagens"])):
        R.novo_personagem(p, f"Extra {k}")
    with pytest.raises(R.ReactErro):
        R.novo_personagem(p, "Um a mais")


def test_cinema_de_costas_e_de_frente_abertura_e_encerramento(base, tmp_path):
    """🎬 v84_238m: cinema com até 3 fileiras de 6 (de costas: a poltrona NA FRENTE de quem senta e só o corpo reage;
    de frente: fileiras em degraus), poses de costas, itens de cinema com quem segura, regras no roteiro; 🚪👋 abertura
    e encerramento (desligados por padrão)."""
    p = _proj(base, 4)
    for k in range(10):
        R.novo_personagem(p, f"Extra {k}") if len(p["personagens"]) < R.MAXIMO_LAYOUT["sofa_tv"] else None
    p["layout"] = "cinema_costas"
    while len(p["personagens"]) < 11:
        R.novo_personagem(p, f"Mais {len(p['personagens'])}")
    lay = R.disposicao(p, base)
    filas = R.sofas_de(p, "cinema_costas")
    assert len(filas) == 2 and all(len(f) <= R.POR_FILEIRA for f in filas) and sum(map(len, filas)) == 11 and [len(f) for f in filas] == [6, 5]
    a0 = [a for a in lay["assentos"] if a["fila"] == 0]
    a2 = [a for a in lay["assentos"] if a["fila"] == 1]
    assert a0[0]["h"] > a2[0]["h"] and a0[0]["cy"] > a2[0]["cy"] and all(a["lado"] == "costas" for a in lay["assentos"])
    ordem = R.pilha(p, lay)["ordem"]
    assert ordem.index(f"p:{a0[0]['cid']}") < ordem.index("sofa0")  # de costas: a poltrona cobre quem senta
    assert ordem.index("sofa1") < ordem.index(f"p:{a0[0]['cid']}") and "mesa" not in ordem
    assert R.lados_precisos(p, a0[0]["cid"]) == ["costas"]
    pj = R.poses_json(p, p["personagens"][0], ["costas"])
    arqs = [x["arquivo"] for x in pj["poses"]]
    assert any(a.endswith("_falando_costas.png") for a in arqs) and "seen from BEHIND" in pj["poses"][0]["prompt"]
    assert R.lado_da_pose("itachi_uchiha", "itachi_uchiha_feliz_costas.png") == ("feliz", "costas")
    assert R.expr_lado("empolgado", "costas") == "feliz" and R.expr_lado("bravo", "costas", True) == "falando"
    assert R.camadas_do_layout(p) == ("cine_costas_fundo", "cine_costas_fileira")
    assert "seen from BEHIND" in R.prompt_camada(p, "cine_costas_fileira") and "screen" in R.prompt_camada(p, "cine_costas_fundo")
    assert "Shhh" in R.sys_roteiro(p) and "cinema" in R.prompt_cena(p, R.novo_evento("briga", 3.0, [a0[0]["cid"]], "x", "x"))
    # de frente: fileiras em degraus, poltrona atrás
    p["layout"] = "cinema_frente"
    lay = R.disposicao(p, base)
    a0 = [a for a in lay["assentos"] if a["fila"] == 0][0]
    ordem = R.pilha(p, lay)["ordem"]
    assert ordem.index("sofa0") < ordem.index(f"p:{a0['cid']}") and a0["lado"] == "frente"
    # itens de cinema ficam com quem segura
    import react_objetos as RO
    o = RO.novo(p, "Balde de pipoca", "a popcorn bucket", f"p:{a0['cid']}")
    d = tmp_path / "o.png"
    Image.new("RGBA", (100, 120), (250, 200, 50, 255)).save(d)
    RO.guardar(p, o, Image.open(d), base)
    lay = R.disposicao(p, base)
    ob = lay["objetos"][0]
    assert abs(ob["cx"] - a0["cx"]) < a0["w"] and "holding" in RO.mapa(p, lay)
    # 🚪👋 abertura/encerramento: desligados por padrão; ligados, chegam e saem um por um
    assert not p["abertura"] and not p["encerramento"] and R.ausencias(p, 60) == {}
    p.update(abertura=True, encerramento=True)
    aus = R.ausencias(p, 60)
    ch = sorted(v[0][1] for v in aus.values())
    assert len(aus) == len(p["personagens"]) and ch[0] < ch[-1] <= R.ABERTURA_S
    assert all(any(x[1] == 60 and x[0] >= 60 - R.ENCERRAMENTO_S for x in v) for v in aus.values())
    assert "ABERTURA" in R.regra_lugar(p, 0, 150) and "ENCERRAMENTO" in R.regra_lugar(dict(p, video={"duracao": 60}), 0, 60)


def test_cinema_video_grande_e_nenhuma_cabeca_em_cima(base):
    """🎬 v84_238n: o vídeo do cinema é grande e a plateia fica TODA abaixo dele (nenhuma cabeça por cima)."""
    p = _proj(base, 4)
    for lay_nome, larg_min in (("cinema_costas", 0.53), ("cinema_frente", 0.42)):
        p["layout"] = lay_nome
        p["personagens"] = p["personagens"][:4]
        p.pop("assentos", None)
        while len(p["personagens"]) < R.MAXIMO_LAYOUT[lay_nome]:
            R.novo_personagem(p, f"Extra {len(p['personagens'])}")
        with pytest.raises(R.ReactErro):
            R.novo_personagem(p, "Um a mais")
        lay = R.disposicao(p, base)
        t = lay["tela"]
        assert t["w"] >= larg_min * R.W
        for a in lay["assentos"]:
            assert a["cy"] - a["h"] / 2 >= t["cy"] + t["h"] / 2, (lay_nome, a)
        assert lay["legenda"]["topo"] > 0.8 * R.H  # a legenda embaixo nos dois
        g0 = sorted(a["cx"] for a in lay["assentos"] if a["fila"] == 0)
        g1 = sorted(a["cx"] for a in lay["assentos"] if a["fila"] == 1)
        assert all(g0[j] < g1[j] < g0[j + 1] for j in range(min(len(g1), len(g0) - 1)))  # intercaladas nos dois
    # de frente: 2 fileiras, a de trás nos vãos da da frente
    f0 = sorted(a["cx"] for a in lay["assentos"] if a["fila"] == 0)
    f1 = sorted(a["cx"] for a in lay["assentos"] if a["fila"] == 1)
    assert len(lay["sofas"]) == 2 and len(f0) == 6 and len(f1) == 5
    assert all(f0[j] < f1[j] < f0[j + 1] for j in range(5))


def test_referencia_do_cenario_recriar_ou_virar_anime(base, monkeypatch):
    """🖼 v84_238q: uma imagem de REFERÊNCIA por camada — o Flow recria o lugar (🏠 ambiente, no visual da foto) ou
    redesenha no traço dos personagens (🎨 anime); a 📁 Minha imagem continua usando a imagem como está."""
    import app as A
    import flow_lote
    p = _proj(base, 2)
    R.salvar(p, base)
    pid = p["id"]
    c = A.app.test_client()
    pedidos = []

    class Lote:
        def adicionar(self, itens, **kw):
            pedidos.extend(itens)
            return [{"id": f"j{i}"} for i in range(len(itens))]

        def iniciar(self):
            pass
    monkeypatch.setattr(flow_lote, "lote", lambda: Lote())
    foto = _png((90, 120, 160), (640, 360), fundo=(200, 180, 150))
    r = c.post(f"/react-personagens/{pid}/cenario/fundo/referencia", data={"arquivo": (io.BytesIO(foto), "sala.png"), "modo": "anime", "gerar": "1"},
               content_type="multipart/form-data").get_json()
    assert r["ok"] and r["enviadas"] == 1
    it = pedidos[-1]
    assert os.path.isfile(it["referencia_arquivo"]) and "REDRAW this SAME place as an ANIME" in it["prompt"] and "NOT a photo" in it["prompt"]
    assert "photorealistic" not in it["prompt"]
    # trocar o modo e gerar de novo (o botão de gerar normal também usa a referência)
    assert c.post(f"/react-personagens/{pid}/cenario/fundo/referencia", json={"modo": "ambiente"}).get_json()["ok"]
    assert c.post(f"/react-personagens/{pid}/cenario/gerar", json={"quais": ["fundo"]}).get_json()["enviadas"] == 1
    assert "RECREATE this SAME place faithfully" in pedidos[-1]["prompt"] and pedidos[-1].get("referencia_arquivo")
    # o sofá sem referência continua como sempre
    c.post(f"/react-personagens/{pid}/cenario/gerar", json={"quais": ["sofa"]})
    assert "referencia_arquivo" not in pedidos[-1] and "REFERENCE" not in pedidos[-1]["prompt"]
    # tirar a referência
    assert c.post(f"/react-personagens/{pid}/cenario/fundo/referencia", json={"apagar": True}).get_json()["ok"]
    assert R.arquivo_referencia(R.carregar(pid, base), "fundo", base) is None
    assert c.post(f"/react-personagens/{pid}/cenario/fundo/referencia", data={"modo": "anime"}, content_type="multipart/form-data").status_code == 400


def test_cinema_de_perto_gestos_atrasado_e_quem_passa(base, tmp_path, monkeypatch):
    """🎬 v84_238r: cinema de perto (o jeito do encerramento de anime) — a fileira grande, a de trás pequena nos vãos, os
    encostos no primeiro plano, o vídeo em cima sem cabeça por cima; 🍿 gestos naturais (pose no lugar, virada pro
    vizinho), ⏰ chegou atrasado / 🚪 sai andando pela fileira, 🌑 alguém passa na frente (silhueta)."""
    p = _proj(base, 4)
    p["layout"] = "cinema_plateia"
    p["movimentos"] = True
    while len(p["personagens"]) < 9:
        R.novo_personagem(p, f"Extra {len(p['personagens'])}")
    with pytest.raises(R.ReactErro):
        for k in range(5):
            R.novo_personagem(p, f"Demais {k}")
    p["personagens"] = p["personagens"][:9]
    assert R.camadas_do_layout(p) == ("cine_plateia_fundo", "cine_frente_fileira", "cine_costas_fileira", "cine_passante")
    assert "projector" in R.prompt_camada(p, "cine_plateia_fundo") and "chroma-key" in R.prompt_camada(p, "cine_passante")
    lay = R.disposicao(p, base)
    t = lay["tela"]
    f0 = sorted((a for a in lay["assentos"] if a["fila"] == 0), key=lambda a: a["cx"])
    f1 = sorted((a for a in lay["assentos"] if a["fila"] == 1), key=lambda a: a["cx"])
    assert len(f0) + len(f1) == 9 and len(f1) <= 5 and f1[0]["h"] < f0[0]["h"]
    for a in lay["assentos"]:
        assert a["cy"] - a["h"] / 2 + 0.05 * a["h"] >= t["cy"] + t["h"] / 2  # nenhuma cabeça em cima do vídeo
    assert lay["sofas"][1]["plano"] and lay["sofas"][1]["camada"] == "cine_costas_fileira"
    ordem = R.pilha(p, lay)["ordem"]
    assert ordem.index(f"p:{f1[0]['cid']}") < ordem.index("sofa0") < ordem.index(f"p:{f0[0]['cid']}") < ordem.index("sofa1") < ordem.index("tela")
    assert R.lados_precisos(p, f0[0]["cid"]) == ["frente"]
    arqs = [x["arquivo"] for x in R.poses_json(p, p["personagens"][0], ["frente"])["poses"]]
    assert any(a.endswith("_pega_pipoca_frente.png") for a in arqs) and any(a.endswith("_andando_frente.png") for a in arqs)
    # poses de mentira (frente + gestos + andando)
    d = tmp_path / "poses"
    d.mkdir()

    def poses(c, base_=None):
        out = {"dir": {}, "esq": {}, "costas": {}, "frente": {}}
        for e in ("neutro", "feliz", "pega_pipoca", "olha_tras", "andando"):
            cam = d / f"{c['id']}_{e}.png"
            if not cam.exists():
                Image.new("RGBA", (120, 180), (200, 80, 80, 255)).save(cam)
            out["frente"][e] = {"pose": str(cam), "boca": None, "arquivo": cam.name}
        return out
    monkeypatch.setattr(R, "_poses_por_lado", poses)
    # eventos: a IA manda gesto/passa/atrasado
    nomes = {a["cid"]: R.personagem(p, a["cid"])["nome"] for a in lay["assentos"]}
    ev = R.ler_eventos(p, [
        {"tempo": 10, "tipo": "gesto", "personagens": [nomes[f0[1]["cid"]], nomes[f0[0]["cid"]]], "gesto": "pega_pipoca", "duracao": 3},
        {"tempo": 20, "tipo": "passa", "personagens": [], "gesto": "silhueta", "duracao": 3.5},
        {"tempo": 30, "tipo": "volta", "personagens": [nomes[f0[-1]["cid"]]]},
        {"tempo": 40, "tipo": "sai", "personagens": [nomes[f0[2]["cid"]]]},
    ], 120)
    assert [e["tipo"] for e in ev] == ["gesto", "passa", "volta", "sai"] and ev[1]["cids"] == []
    p.setdefault("roteiro", {})["eventos"] = ev
    aus = R.ausencias(p, 120)
    assert aus[f0[-1]["cid"]] == [[0.0, 30.0]]  # ⏰ chegou atrasado: fora desde o começo
    g, faltam = R.gestos_no_lugar(p, lay, base)
    ini, fim, _cam, esp, nome_g = g[f0[1]["cid"]][0]
    assert (ini, fim, nome_g) == (10.0, 13.0, "pega_pipoca") and esp  # o vizinho está à esquerda → espelhada
    anda, _av = R.andantes(p, lay, 120, base)
    chega = next(w for w in anda if w["cid"] == f0[-1]["cid"])
    assert chega["b"] == 30.0 and chega["a"] < 30.0 and chega["para"] == 0 and chega["de"] > 0  # vem da ponta da direita
    sai = next(w for w in anda if w["cid"] == f0[2]["cid"])
    assert sai["a"] == 40.0 and sai["de"] == 0
    passa = next(w for w in anda if not w["cid"])
    assert os.path.isfile(passa["cam"]) and "silhueta" in os.path.basename(passa["cam"]) and abs(passa["de"]) > 0.5
    # outra disposição: gesto/passa da IA são ignorados
    q = dict(p, layout="sofa_tv")
    assert [e["tipo"] for e in R.ler_eventos(q, [{"tempo": 5, "tipo": "passa", "personagens": [], "gesto": "silhueta"}], 60)] == []
    assert "CINEMA DE PERTO" in R.sys_roteiro(p) and "'pega_pipoca'" in R.sys_roteiro(p)
    # 🍿 os movimentos são OPCIONAIS (desligados por padrão): sem eles, nada de gesto/passa/andar
    sem = dict(p, movimentos=False)
    assert R.ler_eventos(sem, [{"tempo": 5, "tipo": "gesto", "personagens": [nomes[f0[0]["cid"]]], "gesto": "olha_tras"}], 60) == []
    assert R.gestos_no_lugar(sem, lay, base)[0] == {} and R.andantes(sem, lay, 120, base)[0] == []
    assert "'pega_pipoca'" not in R.sys_roteiro(sem) and not any("pega_pipoca" in x["arquivo"] for x in R.poses_json(sem, p["personagens"][0], ["frente"])["poses"])
    assert R.criar("x", base)["movimentos"] is False
    # 🎬 no editor: o gesto no lugar, quem anda com mov (de/para + passinhos) antes dos encostos da frente
    import shutil
    vid = _video(str(tmp_path / "v.mp4"), 60)
    os.makedirs(R.pasta(p["id"], base), exist_ok=True)
    shutil.copy(vid, os.path.join(R.pasta(p["id"], base), "video.mp4"))
    p["video"] = {"duracao": 60.0, "arquivo": "video.mp4"}
    p["roteiro"]["eventos"] = [e for e in ev if e["t"] < 50]
    R.aplicar_roteiro(p, {"resumo": "x", "eventos": [], "falas": [{"tempo": 11, "personagem": nomes[f0[0]["cid"]], "texto": "Ei, a pipoca é minha!",
                                                                   "expressao": "bravo", "pedido_inscricao": False, "reacoes": []}]})
    p["roteiro"]["eventos"] = [e for e in ev if e["t"] < 50]
    for q_ in ("cine_plateia_fundo", "cine_frente_fileira", "cine_costas_fileira"):
        R.guardar_camada(p, q_, Image.new("RGBA", (1200, 300), (120, 20, 30, 255)), base, recortar=False, origem="upload")
    R.salvar(p, base)
    m = R.montar_editor(p, base, str(tmp_path / "job"))
    ovs = m["overlays"]
    ids = [o["id"] for o in ovs]
    andam = [o for o in ovs if o["id"].startswith("randa")]
    assert len(andam) == 3 and all(any("de" in x for x in o["mov"]) and any("pulo" in x for x in o["mov"]) for o in andam)
    assert all(ids.index(o["id"]) < ids.index("rsofa1") for o in andam)
    gest = next(o for o in ovs if "_gesto" in o["id"])
    assert gest["start"] == 10.0 and gest["espelhar"]
    normal = [o for o in ovs if o.get("cid") == f0[1]["cid"] and "_gesto" not in o["id"] and o["start"] < 13 and o["end"] > 10]
    assert all(o["end"] <= 10.0 or o["start"] >= 13.0 for o in normal)  # a pose normal some durante o gesto
    assert R.previa(p, base, str(tmp_path / "pv.jpg"), t=20.5)
