"""Simulação mínima do YouTube para testar o scraper em Chromium real, sem rede.

Reproduz o que a lógica de leitura de canal realmente usa:
  * aba /videos com cards no layout novo (yt-lockup-view-model), carregados em
    lotes de 30 conforme a rolagem;
  * chips "Mais recentes / Populares / Mais antigos" que reordenam a grade;
  * ordenação por parâmetro de URL (?sort=p / ?sort=da) quando não há chips;
  * canais que ignoram qualquer ordenação;
  * página do vídeo com views e data exatas;
  * cabeçalho do canal e aba Sobre.

NÃO é o YouTube: valida a lógica do scraper, não a estabilidade dos seletores
do site real.
"""
import json
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rel_texto(dias):
    """Mesmo arredondamento (para baixo) que o YouTube usa."""
    if dias < 1:
        return "há 5 horas"
    if dias < 7:
        return f"há {dias} dia" + ("s" if dias > 1 else "")
    if dias < 30:
        n = dias // 7
        return f"há {n} semana" + ("s" if n > 1 else "")
    if dias < 365:
        n = dias // 30
        return "há 1 mês" if n == 1 else f"há {n} meses"
    n = dias // 365
    return f"há {n} ano" + ("s" if n > 1 else "")


def data_pt(d):
    return f"{d.day} de {MESES[d.month - 1]}. de {d.year}"


class CanalFake:
    def __init__(self, handle, dias_atras, views=None, modo_ordenacao="chips",
                 inscritos_txt="12 mil inscritos", views_totais="1.234.567", pais="Brasil"):
        """dias_atras: idade de cada vídeo, do MAIS NOVO para o mais antigo."""
        self.handle = handle
        self.hoje = date.today()
        self.modo = modo_ordenacao  # 'chips' | 'url' | 'nenhum'
        self.inscritos_txt = inscritos_txt
        self.views_totais = views_totais
        self.pais = pais
        self.videos = []
        for i, d in enumerate(dias_atras):
            self.videos.append({
                "id": f"{handle[:4]:_<4}{i:07d}"[:11].replace(" ", "_"),
                "titulo": f"Vídeo {i} do canal {handle}",
                "dias": d,
                "views": (views[i] if views else 1000 + i * 10),
                "dur": "8:15",
            })
        assert len({v["id"] for v in self.videos}) == len(self.videos)
        self.por_id = {v["id"]: v for v in self.videos}

    @property
    def url(self):
        return f"https://www.youtube.com/@{self.handle}"

    def _card(self, v):
        vid, t = v["id"], v["titulo"]
        views = f"{v['views']:,}".replace(",", ".") + "\u00a0visualizações"
        return (
            '<ytd-rich-item-renderer><div id="content"><yt-lockup-view-model><div class="ytLockupViewModelHost">'
            f'<a href="/watch?v={vid}" class="ytLockupViewModelContentImage"><div class="ytBadgeShapeText">{v["dur"]}</div></a>'
            f'<h3 title="{t}"><a href="/watch?v={vid}" class="ytLockupMetadataViewModelTitle"><span role="text">{t}</span></a></h3>'
            '<yt-content-metadata-view-model><div role="group">'
            f'<span class="ytContentMetadataViewModelMetadataText" role="text">{views}</span>'
            f'<span class="ytContentMetadataViewModelMetadataText" role="text">{rel_texto(v["dias"])}</span>'
            '</div></yt-content-metadata-view-model></div></yt-lockup-view-model></div></ytd-rich-item-renderer>'
        )

    def html_videos(self, sort_param=""):
        itens = [{"id": v["id"], "dias": v["dias"], "views": v["views"], "html": self._card(v)} for v in self.videos]
        chips = ""
        if self.modo == "chips":
            chips = ('<div id="chips"><button aria-label="Mais recentes">Mais recentes</button>'
                     '<button aria-label="Populares">Populares</button>'
                     '<button aria-label="Mais antigos">Mais antigos</button></div>')
        inicial = "recentes"
        if self.modo == "url" and sort_param == "p":
            inicial = "populares"
        if self.modo == "url" and sort_param == "da":
            inicial = "antigos"
        return f"""<!doctype html><html><body style="margin:0">{chips}<div id="contents"></div>
<script>
const ITENS = {json.dumps(itens)};
let ordem = {json.dumps(inicial)}, lista = [], mostrados = 0;
function ordenar() {{
  const l = ITENS.slice();
  if (ordem === 'antigos') l.sort((a, b) => b.dias - a.dias);
  else if (ordem === 'populares') l.sort((a, b) => b.views - a.views);
  else l.sort((a, b) => a.dias - b.dias);
  return l;
}}
function mais() {{
  const grid = document.getElementById('contents');
  lista.slice(mostrados, mostrados + 30).forEach(i => grid.insertAdjacentHTML('beforeend', i.html));
  mostrados += 30;
}}
function render() {{ document.getElementById('contents').innerHTML = ''; mostrados = 0; lista = ordenar(); mais(); }}
document.querySelectorAll('#chips button').forEach(b => b.addEventListener('click', () => {{
  const t = b.getAttribute('aria-label');
  ordem = /antigos/i.test(t) ? 'antigos' : /popul/i.test(t) ? 'populares' : 'recentes';
  render();
}}));
window.addEventListener('scroll', () => {{
  if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 800 && mostrados < lista.length) mais();
}});
render();
</script></body></html>"""

    def html_watch(self, vid):
        v = self.por_id[vid]
        d = self.hoje - timedelta(days=v["dias"])
        views = f"{v['views']:,}".replace(",", ".")
        return (f'<!doctype html><html><head><meta itemprop="datePublished" content="{d.isoformat()}"></head><body>'
                f'<div id="info-container"><span id="tooltip">{views} visualizações • {data_pt(d)}</span></div></body></html>')

    def html_canal(self):
        return ('<!doctype html><html><body><yt-content-metadata-view-model>'
                f'<span role="text" aria-label="{self.inscritos_txt}">{self.inscritos_txt}</span>'
                f'<span role="text" aria-label="{len(self.videos)} vídeos">{len(self.videos)} vídeos</span>'
                '</yt-content-metadata-view-model></body></html>')

    def html_about(self):
        d = self.hoje - timedelta(days=max(v["dias"] for v in self.videos) + 5)
        return ('<!doctype html><html><body><div>Canal de testes sobre tecnologia.</div>'
                f'<div>Estatísticas</div><div>Inscreveu-se em {data_pt(d)}</div>'
                f'<div>{self.views_totais} visualizações</div><div>País</div><div>{self.pais}</div></body></html>')


def instalar(page, canais):
    """Intercepta o tráfego do YouTube e responde com as páginas simuladas."""
    por_handle = {c.handle: c for c in canais}
    por_video = {v["id"]: c for c in canais for v in c.videos}
    visitas = []

    def handler(route):
        req = route.request
        u = urlparse(req.url)
        if "youtube.com" not in u.netloc:
            return route.abort()
        visitas.append(req.url)
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [""])[0]
            c = por_video.get(vid)
            if c:
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=c.html_watch(vid))
            return route.fulfill(status=404, body="")
        partes = [p for p in u.path.split("/") if p]
        if partes and partes[0].startswith("@") and partes[0][1:] in por_handle:
            c = por_handle[partes[0][1:]]
            sub = partes[1] if len(partes) > 1 else ""
            if sub == "videos":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                     body=c.html_videos(parse_qs(u.query).get("sort", [""])[0]))
            if sub == "about":
                return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=c.html_about())
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=c.html_canal())
        return route.fulfill(status=404, body="")

    page.route("**/*", handler)
    return visitas


class PaginaRapida:
    """Encurta as esperas fixas do scraper (só nos testes); o resto é delegado."""

    def __init__(self, page, fator=12):
        self._page, self._fator = page, fator

    def wait_for_timeout(self, ms):
        self._page.wait_for_timeout(max(30, ms / self._fator))

    def __getattr__(self, nome):
        return getattr(self._page, nome)
