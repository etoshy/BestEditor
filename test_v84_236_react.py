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
    assert camadas[-1] == "tela" and ovs[-1]["sincronizar"] and ovs[-1]["media_type"] == "video"
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
