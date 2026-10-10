"""
Teste offline de video_metadata.py: normalização de campos, sidecar
JSON/TXT, e embed via ffmpeg (quando disponível — se não estiver
instalado, esse pedaço é pulado, o resto do teste continua valendo).
"""
import json
import os
import shutil
import subprocess

from video_metadata import attach_metadata, embed_ffmpeg_metadata, metadata_from_video, write_sidecar


class FakePexelsVideo:
    def to_dict(self):
        return {
            "id": "12345",
            "title": "Lizard resting on a trunk",
            "description": "A lizard resting while sticking out its tongue on a trunk at nature.",
            "url": "https://www.pexels.com/video/lizard-resting-12345/",
            "author": "Fulano de Tal",
        }


class FakeMagnificVideo:
    """Magnific usa 'name' em vez de 'title' — precisa normalizar."""

    def to_dict(self):
        return {"id": "999", "name": "Cão correndo no parque", "url": "https://www.magnific.com/x_999"}


# --------------------------------------------------------------------- #
# 1) Normalização de campos entre provedores
# --------------------------------------------------------------------- #
meta_pexels = metadata_from_video(FakePexelsVideo(), provider="pexels")
assert meta_pexels["title"] == "Lizard resting on a trunk"
assert meta_pexels["description"].startswith("A lizard resting")
assert meta_pexels["provider"] == "pexels"
print("OK: metadata_from_video normaliza um vídeo com 'title'/'description'.")

meta_magnific = metadata_from_video(FakeMagnificVideo(), provider="magnific")
assert meta_magnific["title"] == "Cão correndo no parque", "deveria usar 'name' como title"
assert meta_magnific["description"] == ""
print("OK: metadata_from_video usa 'name' como fallback de 'title' (caso do Magnific).")

meta_unknown = metadata_from_video("uma string qualquer, sem to_dict nem dict")
assert meta_unknown["title"] == "" and meta_unknown["description"] == ""
print("OK: metadata_from_video não quebra com entrada inesperada.")

# --------------------------------------------------------------------- #
# 2) Sidecar (JSON + TXT) — sempre funciona, sem depender de nada externo
# --------------------------------------------------------------------- #
work_dir = "/tmp/_video_metadata_test"
if os.path.exists(work_dir):
    shutil.rmtree(work_dir)
os.makedirs(work_dir)

fake_video_path = os.path.join(work_dir, "exemplo.mp4")
with open(fake_video_path, "wb") as f:
    f.write(b"conteudo fake, nao e um mp4 de verdade")

written = write_sidecar(fake_video_path, meta_pexels)
assert len(written) == 2
assert os.path.exists(os.path.join(work_dir, "exemplo.json"))
assert os.path.exists(os.path.join(work_dir, "exemplo.txt"))

with open(os.path.join(work_dir, "exemplo.json"), encoding="utf-8") as f:
    saved = json.load(f)
assert saved["title"] == meta_pexels["title"]

with open(os.path.join(work_dir, "exemplo.txt"), encoding="utf-8") as f:
    txt = f.read()
assert "Título: Lizard resting on a trunk" in txt
assert "Descrição: A lizard resting" in txt
print("OK: write_sidecar grava .json e .txt corretos do lado do vídeo.")

# --------------------------------------------------------------------- #
# 3) attach_metadata com embed=True, mas SEM ffmpeg de verdade (arquivo
#    fake não é um mp4 válido) — deve degradar graciosamente: sidecar
#    funciona, embed volta False, e o "vídeo" não é corrompido/apagado.
# --------------------------------------------------------------------- #
before = open(fake_video_path, "rb").read()
result = attach_metadata(FakePexelsVideo(), fake_video_path, provider="pexels", embed=True)
after = open(fake_video_path, "rb").read()
assert result["sidecar_files"], "sidecar deveria ter sido gravado mesmo se o embed falhar"
assert result["embedded"] is False, "nao deveria conseguir embutir num arquivo que nao e mp4 de verdade"
assert before == after, "o arquivo original nao deveria ter sido alterado quando o embed falha"
print("OK: attach_metadata degrada graciosamente quando o embed via ffmpeg falha.")

# --------------------------------------------------------------------- #
# 4) Se o ffmpeg estiver disponível, testa o embed de verdade num mp4 real
# --------------------------------------------------------------------- #
if shutil.which("ffmpeg"):
    real_video_path = os.path.join(work_dir, "real.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=32x32:rate=5",
            "-f", "lavfi", "-i", "sine=duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", real_video_path,
        ],
        capture_output=True, timeout=30, check=True,
    )

    ok = embed_ffmpeg_metadata(real_video_path, title="Título de teste", description="Descrição de teste")
    assert ok is True, "deveria ter conseguido embutir metadados num mp4 valido"

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", real_video_path],
        capture_output=True, text=True, check=True,
    )
    tags = json.loads(probe.stdout)["format"].get("tags", {})
    assert tags.get("title") == "Título de teste"
    assert tags.get("description") == "Descrição de teste"
    print("OK: embed_ffmpeg_metadata realmente escreve title/description no container do mp4 (verificado via ffprobe).")
else:
    print("(ffmpeg não encontrado neste ambiente — pulando o teste de embed real; o sidecar já cobre a parte essencial.)")

shutil.rmtree(work_dir)
print("\nTodos os testes de video_metadata.py passaram.")
