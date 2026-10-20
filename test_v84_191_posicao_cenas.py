"""v84_191: personagem centralizada no monitor = no render; a IA escolhe lado/tamanho; cenas sem texto e sem
personagem; o canal do espaço pode gerar as cenas no padrão de sempre (foto documental)."""
import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw

import canal_pod
import personagens_editor as pe
import video_assembler as va


def test_posicao_e_centro_encostada_embaixo():
    size = pe._tamanho(0.72, False)
    x, y = pe.posicao("esquerda", size, False, 2.0)
    alt = size / 100 * 1920 * 1.5 / 1080 * 100
    assert abs(x - (2 + size / 2)) < 0.01 and abs(y + alt / 2 - 100) < 0.01
    x2, _ = pe.posicao("direita", size, False, 2.0)
    assert abs(x2 - (100 - x)) < 0.01
    assert pe._tamanho(0.72, False, pe.TAMANHOS["grande"]) > size > pe._tamanho(0.72, False, pe.TAMANHOS["pequeno"])


def test_ia_lado_e_tamanho_no_montar():
    pers = [{"slug": "mira", "nome": "Mira", "poses": [{"arquivo": "a.png", "caminho": "/x/a.png", "boca": None, "descricao": ""}]}]
    b = {"id": 1, "slug": "mira", "start": 1.0, "end": 3.0, "texto": "Was?", "palavras": [[1.0, 1.5]], "tipo": "fala"}
    cfg = dict(pe.PADRAO, lados={"mira": "esquerda"})
    aps, _ = pe.montar([b], pers, cfg, 10.0, False, {1: {"pose": "a.png", "lado": "direita", "tamanho": "grande"}})
    a = aps[0]
    assert a["lado"] == "direita" and a["tamanho"] == "grande" and a["x_percent"] > 50 and a["y_percent"] < 100
    ov = pe.overlay_de(dict(a, caminho=__file__), "/tmp", cfg, "o1") if False else None
    job = {"overlays": [{"id": "o1", "origem": "personagem", "lado": "direita", "size_percent": a["size_percent"],
                         "vertical": False, "altura_base": 0.72}]}
    ov = pe.mudar(job, "o1", {"lado": "esquerda", "tamanho": "pequeno"})
    assert ov["x_percent"] < 50 and ov["size_percent"] < a["size_percent"] and ov["ancora"] == "centro"
    assert pe.para_render(ov)["ancora"] == "centro"


def test_cena_do_momento_vai_pra_ia():
    job = {"pending_segments": [{"start": 0, "end": 5, "visual": "a nebula on the left"}]}
    cands = [{"start": 1.0, "end": 2.0}]
    pe._cenas_nos_candidatos(job, cands)
    assert cands[0]["cena"] == "a nebula on the left"


def test_render_centro_bate_com_monitor(tmp_path):
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2:r=25", "-f", "lavfi",
                    "-i", "anullsrc=r=24000:cl=mono", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", base], check=True)
    im = Image.new("RGBA", (200, 300), (255, 0, 0, 255))
    im.save(tmp_path / "p.png")
    ov = {"resolved_path": str(tmp_path / "p.png"), "media_type": "image", "start": 0.0, "end": 2.0, "size_percent": 20,
          "personagem": "mira", "x_percent": 50, "y_percent": 50, "ancora": "centro", "anim_in": "nenhuma",
          "anim_out": "nenhuma", "lado": "esquerda"}
    out = str(tmp_path / "out.mp4")
    va.apply_overlays(base, [ov], out, 640, 360)
    f = str(tmp_path / "f.png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "1", "-i", out, "-frames:v", "1", f], check=True)
    a = np.asarray(Image.open(f).convert("RGB")).astype(int)
    ys, xs = np.nonzero((a[..., 0] > 200) & (a[..., 1] < 80))
    assert abs(xs.mean() - 320) < 4 and abs(ys.mean() - 180) < 4  # centro da imagem no centro da tela


def test_canal_cenas_padrao(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    (d / "pacote.json").write_text(json.dumps({"producao_pod": {"cenas": "padrao", "pct": 100}}), encoding="utf-8")
    c = canal_pod.config({"dir": str(d), "guia": {}})
    assert c["cenas"] == "padrao"
    (d / "pacote.json").write_text(json.dumps({"producao_pod": {"cenas": "xx"}}), encoding="utf-8")
    assert canal_pod.config({"dir": str(d), "guia": {}})["cenas"] == "canal"


def test_pacote_astranebel_no_padrao():
    p = "/home/claude/x/astra/astranebel/pacote.json"
    if not os.path.isfile(p):
        return
    pp = json.load(open(p, encoding="utf-8"))["producao_pod"]
    assert pp["cenas"] == "padrao" and pp["personagens"] is False
    g = json.load(open(os.path.join(os.path.dirname(p), "brand_guide.json"), encoding="utf-8"))
    assert "observator" not in g["generation_system"]["style_lock_en"].lower()


def test_olhar_invertido_e_par_da_pose():
    """v84_192: personagem olhando pra fora → inverter_olhar usa a pose do outro lado; a escolha da IA é corrigida."""
    poses = [{"arquivo": f"mira_curiosa_{l}.png", "caminho": "/x", "boca": None, "lado": l, "aprovada": True,
              "grupo": "reacao", "texto": f"mira_curiosa_{l} curiosa", "descricao": ""} for l in ("esq", "dir")]
    assert pe.olhar_para("esquerda") == "dir" and pe.olhar_para("esquerda", True) == "esq"
    assert pe.escolher_pose(poses, "curiosa", "esquerda")["arquivo"].endswith("_dir.png")
    assert pe.escolher_pose(poses, "curiosa", "esquerda", inverter=True)["arquivo"].endswith("_esq.png")
    assert pe.par_da_pose(poses, poses[1], "esq") is poses[0]
    pers = [{"slug": "mira", "nome": "Mira", "poses": poses}]
    b = {"id": 1, "slug": "mira", "start": 1.0, "end": 3.0, "texto": "Was?", "palavras": [[1.0, 1.5]], "tipo": "fala"}
    cfg = dict(pe.PADRAO, lados={"mira": "esquerda"}, inverter_olhar=True)
    aps, _ = pe.montar([b], pers, cfg, 10.0, False, {1: {"pose": "mira_curiosa_dir.png"}})
    assert aps[0]["pose"] == "mira_curiosa_esq.png"  # a IA pediu a errada: vira a certa


def test_setas_numeros_so_no_canal_que_pede(tmp_path):
    """v84_199: "texto_na_imagem": "setas_numeros" (canal do espaço) libera setas/números; o resto: cena real, nada disso."""
    import cenas_lote as cl
    d = tmp_path / "m2"
    d.mkdir()
    (d / "pacote.json").write_text(json.dumps({"producao_pod": {"cenas": "padrao", "texto_na_imagem": "setas_numeros"}}), encoding="utf-8")
    assert canal_pod.config({"dir": str(d), "guia": {}})["texto_na_imagem"] == "setas_numeros"
    cenas = [{"start": 0.0, "end": 5.0, "fala": "a estrela"}]
    info = {1: {"prompt_imagem": "a star", "esquema": True}}
    com = cl.montar_json(cenas, info, {0}, setas=True)["segments"][0]["query"]
    normal = cl.montar_json(cenas, {1: {"prompt_imagem": "a star"}}, {0}, setas=True)["segments"][0]["query"]
    assert "no arrows" in normal  # cena comum do canal do espaço: nada de seta/número
    sem = cl.montar_json(cenas, info, {0})["segments"][0]["query"]
    assert "arrows, shapes" in com and "no arrows" in sem and "No words" in com
    assert "{REGRA_EXPLICACAO}" in cl._SYS


def test_ia_olha_pra_onde_a_pose_vira(tmp_path, monkeypatch):
    """v84_201: o nome _esq/_dir não bate com a imagem → a IA olha cada pose (uma vez) e o lado real é o que vale."""
    import ia_servico
    import personagens_pod as pp
    monkeypatch.setattr(pp, "pasta_raiz", lambda base=None: str(tmp_path / "pp"))
    poses = []
    for k, nome in enumerate(("mira_a_esq.png", "mira_a_dir.png")):
        im = Image.new("RGBA", (60, 90), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([10 + k * 20, 10, 40, 90], fill=(10 + k, 0, 0, 255))
        cam = tmp_path / nome
        im.save(cam)
        poses.append({"arquivo": nome, "caminho": str(cam), "lado": "esq" if "esq" in nome else "dir", "boca": None,
                      "aprovada": True, "grupo": "", "texto": nome, "descricao": ""})
    chamadas = []
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)

    def chamar(recurso, system, conteudo, schema=None, **kw):
        chamadas.append(recurso)
        return {"poses": [{"i": 1, "olhar": "direita"}, {"i": 2, "olhar": "esquerda"}]}  # os nomes estão trocados
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    pers = [{"slug": "mira", "poses": poses}]
    pe.normalizar_olhar(pers, "b", inverter=False)
    assert poses[0]["lado"] == "dir" and poses[1]["lado"] == "esq" and chamadas == ["personagens"]
    # na esquerda da tela ela tem que olhar pra direita (centro): a "_esq" do nome é a certa aqui
    assert pe.escolher_pose(poses, "", "esquerda")["arquivo"] == "mira_a_esq.png"
    assert pe.par_da_pose(poses, poses[0], "esq") is poses[1]
    pe.normalizar_olhar([{"slug": "mira", "poses": [dict(o, lado="x") for o in poses]}], "b", inverter=True)
    assert len(chamadas) == 1  # já olhou: usa o guardado


def test_personagem_nao_entra_em_trecho_com_texto_na_tela():
    """v84_206: o texto da cena é queimado na imagem — a personagem ficaria por cima dele."""
    job = {"pending_segments": [{"start": 0, "end": 5, "visual": "a", "on_screen_text": "1054"},
                                {"start": 5, "end": 10, "visual": "b"}]}
    cands = [{"start": 1.0, "end": 2.0}, {"start": 6.0, "end": 7.0}]
    pe._cenas_nos_candidatos(job, cands)
    assert cands[0]["texto_na_tela"] and not cands[1]["texto_na_tela"]


def test_espelhar_personagem(tmp_path):
    """v84_207: 🪞 espelhar a personagem — vai pro render como hflip."""
    job = {"overlays": [{"id": "o1", "origem": "personagem", "lado": "direita", "size_percent": 20, "vertical": False}]}
    ov = pe.mudar(job, "o1", {"espelhar": True})
    assert ov["espelhar"] and pe.para_render(ov)["espelhar"]
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1:r=25", "-f", "lavfi",
                    "-i", "anullsrc=r=24000:cl=mono", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", base], check=True)
    im = Image.new("RGBA", (100, 150), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([0, 0, 30, 150], fill=(255, 0, 0, 255))  # vermelho só na ESQUERDA da imagem
    im.save(tmp_path / "p.png")
    o = {"resolved_path": str(tmp_path / "p.png"), "media_type": "image", "start": 0.0, "end": 1.0, "size_percent": 50,
         "personagem": "m", "x_percent": 50, "y_percent": 50, "ancora": "centro", "anim_in": "nenhuma", "anim_out": "nenhuma",
         "lado": "esquerda", "espelhar": True}
    out = str(tmp_path / "o.mp4")
    va.apply_overlays(base, [o], out, 320, 180)
    f = str(tmp_path / "f.png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.5", "-i", out, "-frames:v", "1", f], check=True)
    a = np.asarray(Image.open(f).convert("RGB")).astype(int)
    ys, xs = np.nonzero((a[..., 0] > 200) & (a[..., 1] < 80))
    assert xs.mean() > 160 + 20  # espelhada: o vermelho foi pra direita


def test_suas_edicoes_viram_padrao(tmp_path):
    """v84_208: espelhar/tamanho/lado que você ajusta numa aparição ficam guardados no canal e valem nas próximas."""
    base = str(tmp_path)
    ov = {"personagem": "mira", "pose": "mira_a_dir.png", "lado": "esquerda"}
    pe.lembrar(base, "astra", ov, {"espelhar": True})
    pe.lembrar(base, "astra", ov, {"tamanho": "grande"})
    pr = pe.carregar_prefs(base, "astra")
    assert pr["espelhar"]["mira|mira_a_dir.png|esquerda"] is True and pr["tamanho"]["mira"] == "grande"
    pers = [{"slug": "mira", "nome": "Mira", "poses": [{"arquivo": "mira_a_dir.png", "caminho": "/x", "boca": None,
                                                         "lado": "dir", "aprovada": True, "grupo": "", "texto": "", "descricao": ""}]}]
    b = {"id": 1, "slug": "mira", "start": 1.0, "end": 3.0, "texto": "Was?", "palavras": [[1.0, 1.5]], "tipo": "fala"}
    aps, _ = pe.montar([b], pers, dict(pe.PADRAO, lados={"mira": "esquerda"}, _prefs=pr), 10.0)
    assert aps[0]["espelhar"] and aps[0]["tamanho"] == "grande"


def test_completa_efeitos_no_fim_do_video():
    """v84_208: a IA pôs efeito só no começo; a direção pede ~80% → o fim é completado (câmera só em foto)."""
    import prompt_edicao as pe2
    direcao = {"efeitos": {"pct": 80, "itens": [{"id": "zoom_respiro", "peso": 2}, {"id": "cosmos_estrelas", "peso": 1}]}}
    plano = {"trechos": [{"indice": i, "efeito": "zoom_respiro"} for i in range(25)], "avisos": []}
    n = pe2.completar_efeitos(plano, 90, direcao, foto=[True] * 90)
    com = {t["indice"] for t in plano["trechos"] if t.get("efeito")}
    assert n > 20 and any(i >= 60 for i in com) and plano["avisos"][0].startswith("🎬")
    assert sum(1 for i in com if i >= 60) >= 18


def test_animar_acha_imagem_do_pod(tmp_path, monkeypatch):
    """v84_208: cena gerada no pod (prévia "/runpod/midias/…" ou só o prompt no cache) vira o frame do Flow."""
    import animar_flow as af
    import runpod_gerador as rg
    (tmp_path / "midias").mkdir()
    Image.new("RGB", (64, 36), (9, 9, 9)).save(tmp_path / "midias" / "rp_ab.png")
    monkeypatch.setattr(rg, "pasta", lambda: str(tmp_path))
    monkeypatch.setattr(rg, "_cache", lambda: {"k": {"tipo": "imagem", "arquivo": "rp_ab.png", "descricao": "a star  in space"}})
    job = {"pending_segments": [{"start": 0, "end": 4, "provider": "runpod", "query": "a star in space", "media_type": "image"}],
           "segment_previews": [{"result_url": "/runpod/midias/rp_ab.png"}]}
    assert af.frame_do_trecho(job, 0, str(tmp_path)).endswith("rp_ab.png")
    job["segment_previews"] = [{}]
    assert af.frame_do_trecho(job, 0, str(tmp_path)).endswith("rp_ab.png")
