"""
Teste da opção "evitar repetição de clipes" (site_config.py:
`evitar_repeticao_clipes`, ligada por padrão) — `UsedClipsTracker` já
existia pro caminho de VÍDEO (`_search_and_download_filling_duration`),
mas não tinha cobertura de teste nenhuma, e tinha uma lacuna real: o
caminho de FOTO (`_search_and_download_photo`, usado por segmentos
`media_type="image"` — inclusive Wikipedia) não recebia o tracker,
então fotos podiam repetir entre trechos mesmo com a opção ligada.
"""
import os
import shutil

import pytest

from video_assembler import (
    UsedClipsTracker,
    VideoAssemblyError,
    _download_image_segment_with_fallbacks,
    _search_and_download_photo,
)
from prompt_builder import VideoSegment


# --------------------------------------------------------------------------- #
# UsedClipsTracker — a estrutura de dados em si
# --------------------------------------------------------------------------- #

def test_try_claim_primeira_vez_funciona():
    tracker = UsedClipsTracker()
    assert tracker.try_claim("abc123") is True


def test_try_claim_segunda_vez_do_mesmo_id_falha():
    tracker = UsedClipsTracker()
    tracker.try_claim("abc123")
    assert tracker.try_claim("abc123") is False


def test_try_claim_ids_diferentes_funcionam_independente():
    tracker = UsedClipsTracker()
    assert tracker.try_claim("abc123") is True
    assert tracker.try_claim("outro-id") is True


def test_try_claim_converte_id_pra_string():
    """IDs podem vir como int (ex: Pexels) ou str (ex: Wikipedia,
    "File:Foo.jpg") -- o tracker trata os dois de forma equivalente."""
    tracker = UsedClipsTracker()
    assert tracker.try_claim(12345) is True
    assert tracker.try_claim("12345") is False  # mesmo id, tipos diferentes


def test_release_libera_o_id_pra_ser_reclamado_de_novo():
    tracker = UsedClipsTracker()
    tracker.try_claim("abc123")
    tracker.release("abc123")
    assert tracker.try_claim("abc123") is True


def test_release_de_id_nao_reservado_nao_quebra():
    tracker = UsedClipsTracker()
    tracker.release("nunca-foi-reservado")  # não deve levantar nada


# --------------------------------------------------------------------------- #
# _search_and_download_photo com used_tracker — a lacuna real que foi
# corrigida (antes não existia esse parâmetro nem esse comportamento
# pro caminho de foto).
# --------------------------------------------------------------------------- #

class _FakePhoto:
    def __init__(self, id_):
        self.id = id_


def _fake_photo_client(fotos_por_query, imagem_origem, falhas_no_download=frozenset()):
    """`fotos_por_query`: dict query -> lista de _FakePhoto.
    `falhas_no_download`: conjunto de ids que devem FALHAR ao baixar
    (simula um link quebrado) -- útil pra testar que a reserva é
    liberada quando o download não dá certo."""
    class FakePhotoClient:
        chamadas_download = []

        def search_photos_all(self, query=None, max_pages=1, **kw):
            return list(fotos_por_query.get(query, []))

        def download_photo(self, photo, output_dir, **kw):
            FakePhotoClient.chamadas_download.append(photo.id)
            if photo.id in falhas_no_download:
                raise RuntimeError(f"falha simulada ao baixar {photo.id}")
            os.makedirs(output_dir, exist_ok=True)
            dest = os.path.join(output_dir, f"{photo.id}.jpg")
            shutil.copy(imagem_origem, dest)
            return dest

    return FakePhotoClient()


@pytest.fixture
def imagem_valida(tmp_path):
    caminho = tmp_path / "fonte.jpg"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240", "-frames:v", "1", str(caminho)],
        capture_output=True, check=True,
    )
    return str(caminho)


def test_duas_buscas_com_mesmo_tracker_pegam_fotos_diferentes(tmp_path, imagem_valida):
    fotos = [_FakePhoto("p1"), _FakePhoto("p2"), _FakePhoto("p3")]
    client = _fake_photo_client({"gato": fotos}, imagem_valida)
    tracker = UsedClipsTracker()
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")

    caminho1 = _search_and_download_photo(seg, str(tmp_path / "d1"), client, used_tracker=tracker)
    caminho2 = _search_and_download_photo(seg, str(tmp_path / "d2"), client, used_tracker=tracker)

    assert os.path.basename(caminho1) != os.path.basename(caminho2)


def test_sem_tracker_pode_repetir_a_mesma_foto(tmp_path, imagem_valida):
    """Sanidade: SEM tracker (used_tracker=None, o padrão), o
    comportamento de sempre continua -- sempre pega o primeiro
    resultado, mesmo repetido."""
    fotos = [_FakePhoto("p1"), _FakePhoto("p2")]
    client = _fake_photo_client({"gato": fotos}, imagem_valida)
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")

    caminho1 = _search_and_download_photo(seg, str(tmp_path / "d1"), client)
    caminho2 = _search_and_download_photo(seg, str(tmp_path / "d2"), client)

    assert os.path.basename(caminho1) == os.path.basename(caminho2) == "p1.jpg"


def test_com_tracker_esgotado_recorre_a_foto_ja_usada_em_vez_de_falhar(tmp_path, imagem_valida):
    """Só tem UMA foto disponível pra essa query -- com o tracker
    ligado, a segunda busca não pode simplesmente falhar (isso seria
    pior que repetir uma cena)."""
    fotos = [_FakePhoto("p1")]
    client = _fake_photo_client({"gato": fotos}, imagem_valida)
    tracker = UsedClipsTracker()
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")

    caminho1 = _search_and_download_photo(seg, str(tmp_path / "d1"), client, used_tracker=tracker)
    caminho2 = _search_and_download_photo(seg, str(tmp_path / "d2"), client, used_tracker=tracker)  # não deve levantar erro

    assert os.path.exists(caminho1) and os.path.exists(caminho2)


def test_download_com_falha_libera_a_reserva_pro_proximo_tentar(tmp_path, imagem_valida):
    """Se reservar uma foto mas o DOWNLOAD dela falhar (link quebrado
    etc), a reserva precisa ser liberada -- senão essa foto fica
    bloqueada pra sempre sem nunca ter aparecido no vídeo."""
    fotos = [_FakePhoto("quebrada"), _FakePhoto("boa")]
    client = _fake_photo_client({"gato": fotos}, imagem_valida, falhas_no_download={"quebrada"})
    tracker = UsedClipsTracker()
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")

    caminho = _search_and_download_photo(seg, str(tmp_path / "d1"), client, used_tracker=tracker)
    assert os.path.basename(caminho) == "boa.jpg"
    # "quebrada" nunca virou uso de verdade -- continua livre pra outro trecho tentar
    assert tracker.try_claim("quebrada") is True


def test_query_diferente_nao_compartilha_pool_mas_tracker_ainda_bloqueia_repeticao(tmp_path, imagem_valida):
    """Duas queries diferentes que por acaso trazem a MESMA foto (ex:
    "gato" e "gatinho fofo" resultando na mesma imagem de banco) --
    o tracker ainda bloqueia repetir ela na segunda busca."""
    foto_comum = _FakePhoto("comum")
    client = _fake_photo_client(
        {"gato": [foto_comum], "gatinho fofo": [foto_comum, _FakePhoto("outra")]}, imagem_valida,
    )
    tracker = UsedClipsTracker()

    seg1 = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")
    seg2 = VideoSegment(start=3.0, end=6.0, provider="pexels", query="gatinho fofo", media_type="image")

    caminho1 = _search_and_download_photo(seg1, str(tmp_path / "d1"), client, used_tracker=tracker)
    caminho2 = _search_and_download_photo(seg2, str(tmp_path / "d2"), client, used_tracker=tracker)

    assert os.path.basename(caminho1) == "comum.jpg"
    assert os.path.basename(caminho2) == "outra.jpg"  # não repetiu "comum"


# --------------------------------------------------------------------------- #
# _download_image_segment_with_fallbacks — confirma que o parâmetro
# used_tracker É REPASSADO pra dentro (a integração de verdade, não só
# a função de busca isolada)
# --------------------------------------------------------------------------- #

def test_download_image_segment_repassa_o_tracker(tmp_path, imagem_valida):
    fotos = [_FakePhoto("p1"), _FakePhoto("p2")]
    fake_client = _fake_photo_client({"gato": fotos}, imagem_valida)

    class FakeFactory:
        def get_photo_client(self, provider):
            return fake_client

    tracker = UsedClipsTracker()
    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")

    caminho1 = _download_image_segment_with_fallbacks(seg, str(tmp_path / "d1"), FakeFactory(), used_tracker=tracker)
    caminho2 = _download_image_segment_with_fallbacks(seg, str(tmp_path / "d2"), FakeFactory(), used_tracker=tracker)

    assert os.path.basename(caminho1) != os.path.basename(caminho2)


def test_download_image_segment_sem_tracker_funciona_normalmente(tmp_path, imagem_valida):
    """Compatibilidade: chamar sem `used_tracker` nenhum (parâmetro
    omitido) continua funcionando, sem quebrar nada pra quem já
    chamava essa função antes dela existir."""
    fotos = [_FakePhoto("p1")]
    fake_client = _fake_photo_client({"gato": fotos}, imagem_valida)

    class FakeFactory:
        def get_photo_client(self, provider):
            return fake_client

    seg = VideoSegment(start=0.0, end=3.0, provider="pexels", query="gato", media_type="image")
    caminho = _download_image_segment_with_fallbacks(seg, str(tmp_path / "d1"), FakeFactory())
    assert os.path.exists(caminho)
