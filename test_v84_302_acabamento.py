"""🎨 v84_302: bordas pretas fixas fora, acabamento padrão (@ + legenda) em todos os shorts, sons do Pixabay, destaque no Moondream."""
import json
import os
import subprocess

import curtos as CT


def _video(cam, pad="pad=720:1280:0:190:black", d=4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=720x900:r=25:d={d}", "-f", "lavfi", "-i", f"sine=d={d}",
                    "-vf", pad, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-shortest", cam], check=True)


def _tam(cam):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", cam],
                       capture_output=True, text=True)
    return tuple(int(v) for v in r.stdout.strip().split(","))


def test_bordas_pretas_fixas_saem_ao_entrar_no_curto(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    v = str(tmp_path / "post.mp4")
    _video(v)
    assert CT.bordas_pretas(v) == (720, 900, 0, 190)
    p = CT.criar(base, "", "t", modelo="comentario")
    m = CT.adicionar_midia(base, p, v, "video", "clipe", "M")
    assert _tam(CT.caminho_midia(base, p, m)) == (720, 900) and "bordas pretas cortadas" in m["descricao"]
    limpo = str(tmp_path / "limpo.mp4")
    _video(limpo, "null")
    assert CT.bordas_pretas(limpo) is None  # sem borda: não mexe


def test_borda_que_aparece_so_numa_parte_nao_e_cortada(tmp_path):
    """Uma cena com faixa preta e outra sem: a faixa não é do vídeo todo → não corta (perderia imagem da outra cena)."""
    a, b, junto = str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4"), str(tmp_path / "j.mp4")
    _video(a, "pad=720:1280:0:190:black", 2)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=720x1280:r=25:d=2", "-f", "lavfi", "-i", "sine=d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-shortest", b], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][s]",
                    "-map", "[v]", "-map", "[s]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", junto], check=True)
    assert CT.bordas_pretas(junto) is None


def test_acabamento_padrao_vale_pros_shorts_novos(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    p = CT.criar(base, "", "t", modelo="comentario")
    assert p["config"]["legenda"]["tamanho"] == 0.05 and "marca" not in p["config"]  # padrão: legenda média, sem @
    assert "estilo" not in p["config"]["legenda"]  # o estilo continua o do canal
    CT.salvar_acabamento(base, {"arroba": "meucanal", "legenda_estilo": "caixa", "legenda_tamanho": "0.04", "legenda_maiusculas": False})
    q = CT.criar(base, "", "t", modelo="explicativo")
    assert q["config"]["marca"]["texto"] == "@meucanal"
    assert q["config"]["legenda"] == {"estilo": "caixa", "tamanho": 0.04, "posicao": "terco", "maiusculas": False, "max_palavras": 3,
                                      "altura": None, "margem": 0.1}
    n = CT.criar(base, "", "t", modelo="noticia")  # notícia: só o @ (a legenda é a do canal modelado), a não ser que marque
    assert n["config"]["marca"]["texto"] == "@meucanal" and "legenda" not in n["config"]
    CT.salvar_acabamento(base, {"aplicar_noticia": True})
    assert CT.criar(base, "", "t", modelo="noticia")["config"]["legenda"]["estilo"] == "caixa"
    assert CT.marca_do(base, q)["texto"] == "@meucanal"


def test_sons_do_pixabay_entram_nas_deixas(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("CURTOS_PIXABAY_DIR", str(tmp_path / "px"))
    import curtos_rotas as CR
    from flask import Flask
    base = str(tmp_path)
    buscas = []

    def pixabay_falso(args):
        buscas.append(args.termo)
        os.makedirs(args.pasta, exist_ok=True)
        f = os.path.join(args.pasta, "s.m4a")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", f], check=True)
        cat = os.path.join(args.pasta, "catalogo.json")
        itens = json.load(open(cat)) if os.path.isfile(cat) else []
        itens.append({"id": str(100 + len(itens)), "busca": args.termo, "arquivo_cortado": f, "titulo": args.termo})
        json.dump(itens, open(cat, "w"))
        return 0
    monkeypatch.setattr(CR, "importar_pixabay", lambda b, sid, pasta=None: f"pixabay/{sid}")
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, base, rodar_pixabay=pixabay_falso)
    cl = app.test_client()
    assert cl.post("/curtos/acabamento", json={"sons_pixabay": True}).get_json()["acabamento"]["sons_pixabay"] is True
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"blocos": [{"id": "B1", "fala": "a", "cenas": [], "sfx": [{"tipo": "impacto", "busca": "basketball net swish"},
                                                                         {"tipo": "whoosh", "busca": "basketball net swish"}]},
                               {"id": "B2", "fala": "b", "cenas": [], "sfx": [{"tipo": "pop", "busca": "crowd cheer", "som": "meu/som"}]}]}
    CT.salvar(base, p)
    assert CR.CB["sons_pixabay"](p["id"], lambda m: None) == 2
    assert buscas == ["basketball net swish"]  # 1 busca pras 2 deixas iguais; a que já tinha som escolhido não busca
    q = CT.carregar(base, p["id"])
    assert [s.get("som") for s in q["roteiro"]["blocos"][0]["sfx"]] == ["pixabay/100", "pixabay/100"]
    assert q["roteiro"]["blocos"][1]["sfx"][0]["som"] == "meu/som"
    assert CR.CB["sons_pixabay"](p["id"], lambda m: None) == 0 and buscas == ["basketball net swish"]  # já tem: não busca de novo
