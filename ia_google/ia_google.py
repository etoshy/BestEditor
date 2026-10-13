"""
Pesquisa no Modo IA do Google via Playwright (com conversa contínua).

Fluxo:
  1. abre google.com e clica no botão "Modo IA"
  2. escreve a pergunta e envia
  3. espera a IA terminar (botão "Parar" some + texto estabiliza)
  4. a pergunta vai com uma INSTRUCAO pedindo o formato abaixo, e o retorno é um JSON:
       - resposta objetiva (direta, 1-2 frases)
       - resposta completa em Markdown (como a IA mandou)
       - fontes que a IA usou (título, site, trecho, link)
  5. perguntas seguintes vão na caixa de chat "Pergunte o que quiser"

Instalar:
    pip install playwright
    playwright install chromium

Uso rápido:
    python ia_google.py                 # chat interativo no terminal
    from ia_google import GoogleIA
    with GoogleIA() as ia:
        r = ia.perguntar("qual o dólar hoje")
        print(r["resposta_objetiva"], r["fontes"])  # r é um dict pronto para JSON
        r2 = ia.perguntar("e o euro?")    # continua a mesma conversa
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PERFIL_DIR = Path("perfil_navegador")  # cookies/login persistem (menos captcha)
SAIDA_DIR = Path("resultados")
DEBUG_DIR = Path("debug")

# ---- seletores (tirados do HTML que você mandou) ----
SEL = {
    "botao_modo_ia": "button.plR5qb",                    # botão "Modo IA" na home
    "chat_input": 'textarea.ITIRGe, textarea[aria-label="Pergunte o que quiser"]',
    "busca_home": 'textarea[name="q"]',                  # caixa da home (fallback)
    "botao_enviar": 'button[aria-label="Enviar"]',
    "botao_parar": 'button[aria-label="Parar"]',
    "bloco_resposta": '[data-subtree="aimc"]',           # 1 por resposta da IA
    "texto_resposta": ".mZJni",
    "fonte_item": "li.Ioqnib",
    "nova_conversa": 'button[aria-label="Nova conversa"]',
    "captcha": "#captcha-form, form#captcha-form, iframe[src*='recaptcha']",
}
CLASSE_OCULTO = "Z3UdVc"  # o Google usa essa classe para esconder botões (Parar/Enviar)

URL_HOME = "https://www.google.com/?hl=pt-BR"
URL_MODO_IA = "https://www.google.com/search?q={q}&udm=50&hl=pt-BR"  # fallback direto

# Instrução enviada junto com a pergunta para a IA responder sempre no mesmo formato.
# ATENÇÃO: não coloque exemplos com "https://" aqui. O Google transforma qualquer coisa com cara de link
# em anexo ("guias"), tenta abrir e acaba respondendo "não há uma resposta disponível".
# O " \n\n— " no começo garante a separação mesmo quando o Google remove as quebras de linha.
INSTRUCAO = """{pergunta} \n\n— Instruções de formato: pesquise em fontes atuais e responda SOMENTE com um bloco de código JSON válido, sem nenhum texto antes ou depois, com estas chaves:
```json
{{
  "resposta_objetiva": "a resposta direta em 1 ou 2 frases",
  "resposta_completa": "a explicação completa e detalhada em markdown, com datas, números e contexto",
  "fontes": [{{"nome": "nome do site", "titulo": "título da página", "url": "endereço completo da página"}}],
  "midias": {{
    "videos": [{{"titulo": "título do vídeo", "url": "endereço completo do vídeo"}}],
    "imagens": [{{"titulo": "descrição", "url": "endereço direto da imagem", "pagina": "endereço da página de origem"}}]
  }}
}}
```
Regras: cada "url" deve ser o endereço real e completo (começando com http) da página de onde você tirou a informação, nunca do Google. Se a resposta tiver código ou tabela, coloque dentro de "resposta_completa" em markdown. Preencha "midias" só se a pergunta envolver vídeos ou imagens; senão deixe as listas vazias."""

# JS que roda na página: pega o ÚLTIMO bloco de resposta e devolve texto + fontes
JS_EXTRAIR = r"""
(sel) => {
  const blocos = document.querySelectorAll(sel.bloco_resposta);
  if (!blocos.length) return null;
  const bloco = blocos[blocos.length - 1];

  const area = bloco.querySelector(sel.texto_resposta) || bloco;
  const absoluto = (h) => { try { return new URL(h, location.href).href; } catch (e) { return h || ''; } };

  // Links no texto trazem a URL real no aria-label:
  // "X. Prévia do link. Site: YouTube. Título: Fulano - YouTube. URL: https://..."
  const lerAria = (a) => {
    const al = (a && a.getAttribute('aria-label')) || '';
    const url = (al.match(/URL:\s*(https?:\/\/\S+?)\.?\s*$/) || [])[1] || '';
    const site = (al.match(/Site:\s*(.+?)\.\s*Título:/) || [])[1] || '';
    const titulo = (al.match(/Título:\s*(.+?)\.\s*URL:/) || [])[1] || '';
    return {url, site, titulo};
  };

  // ---- imagens (galeria): tudo vem no atributo data-im ----
  const imagens = [];
  area.querySelectorAll('[data-im]').forEach(el => {
    try {
      const d = JSON.parse(el.getAttribute('data-im'));
      const extra = (d[4] && Object.values(d[4])[0]) || [];
      const img = el.querySelector('img');
      imagens.push({
        miniatura: (d[2] || [])[0] || '',
        imagem: (d[3] || [])[0] || '',
        largura: (d[3] || [])[2] || null, altura: (d[3] || [])[1] || null,
        pagina: extra[2] || '',
        titulo: (extra[3] || (img && img.alt) || '').replace(/<[^>]+>/g, ''),
        site: extra[17] || '',
      });
    } catch (e) {}
  });

  // ---- cartões (vídeos e links em destaque): o data-ignore-copy MAIS INTERNO com um único link ----
  // (os data-ignore-copy de fora são carrosséis e podem ter texto da resposta, que não pode sumir)
  const ehCartao = (c) => !c.querySelector('[data-ignore-copy], [data-im]') && c.querySelectorAll('a[href]').length === 1;
  const cartoes = [];
  area.querySelectorAll('[data-ignore-copy]').forEach(c => {
    if (!ehCartao(c)) return;
    const a = c.querySelector('a[href]');
    const linhas = [...c.querySelectorAll('*')].filter(e => !e.children.length && !/^(SCRIPT|STYLE|NOSCRIPT)$/.test(e.tagName))
      .map(e => (e.textContent || '').replace(/\u00a0/g, ' ').trim()).filter(Boolean);
    if (!linhas.length) return;
    const ehVideo = !!c.querySelector('video') || linhas.some(l => /visualiza|views/i.test(l));
    const duracao = linhas.find(l => /^(\d+:)?\d{1,2}:\d{2}$|^\d+\s?(s|m|min|h)$/.test(l)) || '';
    const visualizacoes = linhas.find(l => /visualiza|views/i.test(l)) || '';
    const textoCartao = (c.textContent || '').replace(/\u00a0/g, ' ');
    const quando = ((textoCartao.match(/há\s+\d+\s+(segundos?|minutos?|horas?|dias?|semanas?|mês|meses|anos?)|\d+\s+(dias?|meses|mês|anos?|horas?|semanas?)\s+atrás|\d+ (days?|months?|years?|weeks?|hours?) ago/i) || [])[0] || '');
    const canal = linhas.find(l => / · /.test(l) && !/^·/.test(l)) || '';
    const titulo = linhas.filter(l => ![duracao, visualizacoes, canal].includes(l) && !/^·/.test(l))
      .reduce((m, l) => l.length > m.length ? l : m, '');
    const v = c.querySelector('video');
    cartoes.push({tipo: ehVideo ? 'video' : 'link', titulo, canal, duracao, visualizacoes, quando,
                  href: absoluto(a.getAttribute('href')), url_aria: lerAria(a).url,
                  previa: v ? v.src : ''});
  });

  // ---- "Confira os principais resultados da Web": o Google NÃO gerou resposta de IA, só uma lista de links ----
  const cabWeb = [...area.querySelectorAll('[role="heading"], h2, h3, h4')]
    .find(h => /principais resultados da web|resultados da web para saber mais|top (web )?results/i.test(h.textContent));
  const resultados_web = [];
  if (cabWeb) {
    const vistos = new Set();
    area.querySelectorAll('a[href][aria-label]').forEach(a => {
      if ((a.textContent || '').trim()) return;           // os itens da lista têm link "vazio" com aria-label
      const item = a.parentElement;
      if (!item || vistos.has(item)) return;
      vistos.add(item);
      const linhas = [...item.querySelectorAll('*')].filter(e => !e.children.length && !/^(SCRIPT|STYLE)$/.test(e.tagName))
        .map(e => (e.textContent || '').replace(/\u00a0/g, ' ').trim()).filter(t => t && t !== '·');
      const exibida = linhas.find(l => /^https?:\/\//.test(l)) || '';
      const titulo = (a.getAttribute('aria-label') || '').trim();
      const site = linhas.find(l => l !== exibida && l !== titulo && l.length < 60) || '';
      const trecho = linhas.filter(l => l !== exibida && l !== titulo && l !== site)
        .reduce((m, l) => l.length > m.length ? l : m, '');
      resultados_web.push({titulo, site, exibida, trecho, href: absoluto(a.getAttribute('href'))});
    });
  }

  // ---- produtos (chips do Google Shopping) ----
  const ehProduto = (a) => /ibp=oshop|[?&]prds=/.test(a.getAttribute('href') || '');
  const nomeProduto = (a) => ((a.querySelector('span') || a).textContent || '').trim();
  const produtos = [...area.querySelectorAll('a[href]')].filter(ehProduto)
    .map(a => ({nome: nomeProduto(a), url: absoluto(a.getAttribute('href'))})).filter(p => p.nome);

  // fórmulas: o Google guarda o LaTeX em data-xpm-latex -> texto legível (15.6^{\prime\prime} -> 15.6″)
  const latex = (t) => (t || '')
    .replace(/\\prime/g, '′').replace(/\\times/g, '×').replace(/\\cdot/g, '·').replace(/\\circ/g, '°')
    .replace(/\\%/g, '%').replace(/\\pm/g, '±').replace(/\\leq?/g, '≤').replace(/\\geq?/g, '≥')
    .replace(/\\approx/g, '≈').replace(/\\neq/g, '≠').replace(/\\infty/g, '∞').replace(/\\to/g, '→')
    .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)').replace(/\\sqrt\{([^{}]*)\}/g, '√($1)')
    .replace(/\\(text|mathrm|mathbf|operatorname)\{([^{}]*)\}/g, '$2')
    .replace(/\^\{\s*((?:′\s*)+)\}/g, (m, a) => a.replace(/\s/g, ''))
    .replace(/\^\{([^{}]*)\}/g, '^$1').replace(/_\{([^{}]*)\}/g, '_$1')
    .replace(/\\[a-zA-Z]+/g, '').replace(/[{}]/g, '').replace(/\s+/g, ' ').trim();

  // ---- texto da resposta ----
  const clone = area.cloneNode(true);
  clone.querySelectorAll('[data-xpm-copy-root]').forEach(m => {
    const img = m.querySelector('[data-xpm-latex]');
    const ann = m.querySelector('annotation');
    const txt = img ? latex(img.getAttribute('data-xpm-latex')) : (ann ? ann.textContent : m.textContent);
    m.replaceWith(document.createTextNode(txt));
  });
  clone.querySelectorAll('math').forEach(m => m.remove());
  // chips de produto: fica só o nome
  clone.querySelectorAll('a[href]').forEach(a => { if (ehProduto(a)) a.replaceWith(document.createTextNode(nomeProduto(a))); });
  clone.querySelectorAll('[id^="pvlink-desc"]').forEach(e => e.remove());
  // cartões e galerias saem do texto (vão separados em "midias")
  clone.querySelectorAll('[data-ignore-copy]').forEach(e => { if (e.parentNode && ehCartao(e)) e.remove(); });
  clone.querySelectorAll('[data-im]').forEach(e => e.remove());
  // remove chips de citação ("Wise +1"), ícones, gráficos e botões
  clone.querySelectorAll('button, svg, img, video, style, script, [aria-hidden="true"]')
       .forEach(e => e.remove());
  // remove avisos e a área de feedback/compartilhar/rodapé do Google
  const LIXO = /^(As respostas da IA podem conter erros|Acesse a caixa de diálogo de visualização|A IA pode cometer erros|Mostrar tudo$|Mostrar menos$|Copiado para a área de transferência|Use o código com cuidado|Compartilhar link público|Boa resposta)/;
  clone.querySelectorAll('div, span').forEach(d => {
    if (d.parentNode && LIXO.test(d.textContent.trim())) d.remove();
  });
  // converte o HTML da resposta em Markdown (títulos, listas, negrito, parágrafos)
  const WIDGET = 'fMjZBb';
  const PRE = (n) => {
    const t = n.textContent.replace(/\n+$/, '');
    return '\n\n```' + (/^\s*[\[{]/.test(t) ? 'json' : '') + '\n' + t + '\n```\n\n';
  };
  const BLOCOS = new Set(['DIV','P','SECTION','ARTICLE','TABLE','TR','BLOCKQUOTE']);
  const md = (n) => {
    if (n.nodeType === 3) return n.textContent.replace(/\s+/g, ' ');
    if (n.nodeType !== 1) return '';
    const filhos = () => [...n.childNodes].map(md).join('');
    const tag = n.tagName;
    const nivel = /^H[1-6]$/.test(tag) ? +tag[1] : (n.getAttribute('role') === 'heading' ? 3 : 0);
    if (nivel) return `\n\n${'#'.repeat(Math.max(nivel, 3))} ${filhos().trim()}\n\n`;
    if (tag === 'BR') return '\n';
    if (tag === 'PRE') return PRE(n);
    if (tag === 'A') {
      const t = filhos().trim(), real = lerAria(n).url, href = real || n.getAttribute('href') || '';
      if (/^\/search\?/.test(href)) return t;  // link para outra pesquisa do Google: só o texto
      return t && /^(https?:|\/)/.test(href) ? `[${t}](${href})` : t;
    }
    // widgets (cotação, gráfico etc.): vira uma linha de citação com o essencial
    if (n.classList.contains(WIDGET) && !n.querySelector('.n6owBd, ul, ol, pre, table, p')) {
      const t = [...n.querySelectorAll('*')].filter(e => !e.children.length)
        .map(e => e.textContent.trim()).filter(Boolean).slice(0, 3);
      return t.length ? '\n\n> ' + t.join(' ') + '\n\n' : '';
    }
    if (tag === 'STRONG' || tag === 'B') { const t = filhos().replace(/\s+/g, ' ').trim(); return t ? ` **${t}** ` : ''; }
    if (tag === 'EM' || tag === 'I') { const t = filhos().replace(/\s+/g, ' ').trim(); return t ? ` *${t}* ` : ''; }
    if (tag === 'UL' || tag === 'OL') {
      const itens = [...n.children].filter(c => c.tagName === 'LI');
      const linhas = itens.map(li => md(li).replace(/\n{2,}/g, '\n').trim().replace(/\n/g, '\n  '))
                          .filter(t => t);
      return '\n\n' + linhas.map((t, i) => (tag === 'OL' ? `${i + 1}. ` : '- ') + t).join('\n') + '\n\n';
    }
    if (tag === 'TD' || tag === 'TH') return ' | ' + filhos().trim();
    if (BLOCOS.has(tag)) return '\n\n' + filhos() + '\n\n';
    return filhos();
  };
  let markdown = md(clone)
    .replace(/ /g, ' ')
    .replace(/ +([,.;:!?)])/g, '$1')
    .replace(/\*\* +\*\*/g, ' ')
    .replace(/[ \t]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  // innerText só funciona bem em nó anexado ao DOM
  clone.style.position = 'fixed'; clone.style.left = '-99999px';
  document.body.appendChild(clone);
  let texto = clone.innerText;
  clone.remove();
  texto = texto.replace(/ /g, ' ')
               .replace(/[ \t]+\n/g, '\n')
               .replace(/\n{3,}/g, '\n\n')
               .trim();

  // ---- blocos de código (a resposta em JSON vem aqui) ----
  const codigos = [...area.querySelectorAll('pre')].map(p => p.textContent);

  // ---- links citados dentro do texto ----
  const citados = [...area.querySelectorAll('a[href]')]
    .filter(a => !a.closest('[data-ignore-copy], [data-im]') && !ehProduto(a) && !/^\/search\?/.test(a.getAttribute('href') || ''))
    .map(a => { const ar = lerAria(a);
      return {texto: (a.textContent || '').trim(), href: absoluto(a.getAttribute('href')),
              url_aria: ar.url, site: ar.site, titulo: ar.titulo}; })
    .filter(a => { if (!a.texto) return false; if (a.url_aria || a.href.includes('/goto?')) return true;
                   try { return !/\.google\./.test(new URL(a.href).host); } catch (e) { return false; } });

  // ---- lista de fontes ----
  const fontes = [...bloco.querySelectorAll(sel.fonte_item)].map(li => {
    const a = li.querySelector('a[href]');
    const titulo = ((a && a.getAttribute('aria-label')) || '')
                     .replace(/\.?\s*Abre em uma nova guia\.?$/i, '')
                     .replace(/,\s*vídeo,\s*abrir em um site externo$/i, '').trim();
    const site = (li.querySelector('.jdxGff') || {}).textContent || '';
    // trecho/resumo: o texto "folha" mais longo do card que não seja título nem site
    // (textContent funciona mesmo nos cards escondidos atrás de "Mostrar tudo")
    const folhas = [...li.querySelectorAll('span, div')]
      .filter(e => !e.querySelector('span, div') && !e.closest('button'))
      .map(e => (e.textContent || '').trim())
      .filter(t => t && t !== titulo && t !== site.trim() && !titulo.startsWith(t));
    const trecho = folhas.reduce((m, t) => t.length > m.length ? t : m, '');
    // domínio vem do favicon (faviconV2?url=https://dominio)
    let dominio = '';
    const img = li.querySelector('img[src*="faviconV2"]');
    if (img) { try { dominio = new URL(img.src).searchParams.get('url') || ''; } catch(e){} }
    return {titulo, site: site.trim(), trecho, dominio, href: a ? a.href : ''};
  });

  return {texto, markdown, fontes, citados, codigos, imagens, cartoes, produtos, resultados_web,
          so_links: !!cabWeb, total_blocos: blocos.length};
}
"""


class ErroIA(Exception):
    """Erro com código, mensagem amigável e dica de como resolver."""

    def __init__(self, codigo, mensagem, dica="", detalhe=""):
        super().__init__(mensagem)
        self.codigo, self.mensagem, self.dica, self.detalhe = codigo, mensagem, dica, detalhe

    def to_dict(self):
        return {"codigo": self.codigo, "mensagem": self.mensagem, "dica": self.dica, "detalhe": self.detalhe}


def classificar_erro(e):
    """Transforma qualquer exceção num ErroIA com explicação em português."""
    if isinstance(e, ErroIA):
        return e
    t = f"{type(e).__name__}: {e}"
    regras = [
        ("Executable doesn't exist", "NAVEGADOR_NAO_INSTALADO", "O Chromium do Playwright não está instalado.",
         "Rode no terminal: playwright install chromium"),
        ("net::ERR_INTERNET_DISCONNECTED", "SEM_INTERNET", "Sem conexão com a internet.",
         "Verifique sua conexão e tente de novo."),
        ("net::ERR_", "ERRO_DE_REDE", "Não foi possível carregar o Google.",
         "Verifique a internet, o proxy ou o firewall."),
        ("has been closed", "NAVEGADOR_FECHADO", "A janela do navegador foi fechada durante a pesquisa.",
         "Tente de novo; o navegador reabre sozinho."),
        ("Target page", "NAVEGADOR_FECHADO", "A janela do navegador foi fechada durante a pesquisa.",
         "Tente de novo; o navegador reabre sozinho."),
        ("ProcessSingleton", "PERFIL_EM_USO", "O perfil do navegador já está em uso por outra janela.",
         "Feche outras execuções do programa (ou outra janela do Chromium) e tente de novo."),
        ("user data directory is already in use", "PERFIL_EM_USO", "O perfil do navegador já está em uso.",
         "Feche outras execuções do programa e tente de novo."),
        ("Timeout", "TEMPO_ESGOTADO", "Uma etapa demorou demais.",
         "Aumente o tempo limite nas configurações ou deixe o navegador visível para ver o que aconteceu."),
    ]
    for trecho, cod, msg, dica in regras:
        if trecho in t:
            return ErroIA(cod, msg, dica, t)
    return ErroIA("ERRO_DESCONHECIDO", "Ocorreu um erro inesperado.",
                  "Veja os detalhes técnicos e o print da tela. Se repetir, rode /debug e mande o HTML.", t)


# Nas perguntas seguintes da MESMA conversa basta um lembrete curto (menos texto = menos recusa e captcha).
INSTRUCAO_CURTA = ("{pergunta} \n\n— Responda no mesmo formato JSON combinado antes: resposta_objetiva, "
                   "resposta_completa, fontes (com o endereço real e completo de cada página) e midias.")


class CaptchaResolvido(Exception):
    """Interno: o captcha apareceu e foi resolvido no meio da pergunta; ela precisa ser reenviada."""


# frases que o Google mostra quando NÃO gera resposta (aí vale tentar de novo)
FALHAS_GOOGLE = re.compile(
    r"não há uma resposta disponível|tente pedir outra coisa|something went wrong|response wasn.t generated|"
    r"algo deu errado|não foi possível gerar|an ai (overview|response) is( not|n.t) available|try asking something else|"
    r"não é possível responder|isn.t available for this search",
    re.I)

JS_TEXTO_BLOCO = r"""
(sel) => {
  const b = document.querySelectorAll(sel.bloco_resposta);
  if (!b.length) return '';
  const ultimo = b[b.length - 1];
  const area = ultimo.querySelector(sel.texto_resposta);
  // texto do bloco sem o eco da pergunta (h3 "Resposta do Modo IA para ...")
  const c = ultimo.cloneNode(true);
  c.querySelectorAll('h3, [role="heading"]').forEach(h => { if (/^Resposta do Modo IA/.test(h.textContent)) h.remove(); });
  // a mensagem de erro às vezes fica num parágrafo vizinho do bloco (ex.: "Something went wrong…").
  // Junta só os textos curtos ao redor (o eco da pergunta é longo e fica de fora).
  let anc = ultimo;
  for (let i = 0; i < 3 && anc.parentElement; i++) anc = anc.parentElement;
  const curtos = [];
  const w = document.createTreeWalker(anc, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode, t = n.textContent.trim();
    if (!t || t.length > 300) continue;
    const pai = n.parentElement;
    if (!pai || pai.closest('script, style, [data-subtree="aimc"], textarea')) continue;
    curtos.push(t);
  }
  const viz = curtos.join(' ');
  return {pedacos: curtos.slice(0, 200), bloco: c.textContent.slice(0, 2000) + ' ' + viz.slice(0, 3000), area: area ? area.textContent.slice(0, 2000) : ''};
}
"""


class GoogleIA:
    def __init__(self, headless=False, resolver_links=True, timeout_resposta=120,
                 perfil_dir=PERFIL_DIR, log=None, interativo=True, espera_captcha=0,
                 max_perguntas_conversa=25):
        self.headless = headless
        self.resolver_links = resolver_links
        self.timeout_resposta = timeout_resposta
        self.perfil_dir = Path(perfil_dir)
        self.interativo = interativo          # True: captcha pede Enter no terminal
        self.espera_captcha = espera_captcha  # segundos esperando o captcha; 0 = sem limite (fica monitorando)
        self.max_perguntas_conversa = max_perguntas_conversa  # depois disso abre conversa nova (0 = nunca)
        self.perguntas_na_conversa = 0
        self.instrucao_enviada = False   # a instrução completa já foi enviada nesta conversa?
        # captcha com o navegador OCULTO: reabre VISÍVEL na mesma página e espera você resolver (em vez de dar erro)
        self.desocultar_no_captcha = True
        self.esperando_captcha = False   # /api/status mostra isso (o site avisa no 🔔)
        self.log = log or (lambda msg, nivel="info": print(f"[{nivel}] {msg}"))
        self._pw = self.ctx = self.page = None
        self.em_conversa = False
        self.historico = []

    # ---------- ciclo de vida ----------
    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *exc):
        self.fechar()

    def abrir(self):
        self.log(f"Abrindo navegador ({'invisível' if self.headless else 'visível'})…")
        self._pw = sync_playwright().start()
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(
                self.perfil_dir,
                headless=self.headless,
                locale="pt-BR",
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            self._pw.stop()
            self._pw = None
            raise classificar_erro(e)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.log("Navegador aberto.", "ok")

    def esta_aberto(self):
        try:
            return bool(self.page) and not self.page.is_closed()
        except Exception:
            return False

    def salvar_print(self, caminho_base):
        """Salva print + HTML da página (útil quando dá erro). Devolve os caminhos."""
        caminho_base = Path(caminho_base)
        caminho_base.parent.mkdir(parents=True, exist_ok=True)
        saida = {}
        try:
            png = caminho_base.with_suffix(".png")
            self.page.screenshot(path=str(png), full_page=False)
            saida["print"] = str(png)
        except Exception:
            pass
        try:
            html = caminho_base.with_suffix(".html")
            html.write_text(self.page.content(), encoding="utf-8")
            saida["html"] = str(html)
        except Exception:
            pass
        return saida

    def fechar(self):
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._pw = self.ctx = self.page = None
            self.em_conversa = False
            self.perguntas_na_conversa = 0
            self.instrucao_enviada = False

    # ---------- utilidades ----------
    def _tem_captcha(self):
        try:
            p = self.page
            if "/sorry/" in p.url or p.locator(SEL["captcha"]).count() > 0:
                return True
            return bool(p.evaluate("""() => /tráfego incomum|unusual traffic|não é um robô|not a robot/i
                                         .test((document.body && document.body.innerText || '').slice(0, 3000))"""))
        except Exception:
            return False

    def _checar_captcha(self):
        """Se houver captcha, fica monitorando até ele ser resolvido. Devolve True se teve captcha."""
        if not self._tem_captcha():
            return False
        if self.headless:
            if not (self.desocultar_no_captcha and not self.interativo):
                raise ErroIA("CAPTCHA", "O Google pediu um captcha (verificação de robô).",
                             "Nas configurações, deixe o navegador VISÍVEL, faça a pergunta de novo e resolva o captcha na janela.")
            self._reabrir_visivel()
            if not self._tem_captcha():  # reabriu e o Google já liberou
                return True
        if self.interativo:
            print("\a⚠️  Captcha detectado — resolva na janela do navegador e aperte Enter aqui.")
            input()
            return True
        limite_txt = f" (até {self.espera_captcha}s)" if self.espera_captcha else ""
        self.log(f"🔒 CAPTCHA detectado! Resolva na janela do navegador. Fico monitorando e continuo sozinho "
                 f"quando você resolver{limite_txt}.", "aviso")
        inicio, ultimo_aviso = time.time(), time.time()
        self.esperando_captcha = True
        try:
            while self._tem_captcha():
                time.sleep(1)
                esperando = time.time() - inicio
                if self.espera_captcha and esperando > self.espera_captcha:
                    raise ErroIA("CAPTCHA", "O captcha do Google não foi resolvido a tempo.",
                                 "Resolva o captcha na janela do navegador e tente de novo "
                                 "(ou deixe 'Esperar captcha' = 0 nas configurações para esperar sem limite).")
                if time.time() - ultimo_aviso >= 15:
                    ultimo_aviso = time.time()
                    self.log(f"Ainda aguardando o captcha… ({esperando:.0f}s)", "aviso")
        finally:
            self.esperando_captcha = False
        self.log(f"✅ Captcha resolvido ({time.time() - inicio:.0f}s). Continuando…", "ok")
        time.sleep(2)  # deixa a página carregar depois do captcha
        return True

    def _reabrir_visivel(self):
        """O navegador estava OCULTO e apareceu captcha: fecha e reabre VISÍVEL (o perfil/cookies são os mesmos)
        na mesma página, pra você resolver. Na próxima pergunta o app volta a esconder (se a config pedir)."""
        url = ""
        try:
            url = self.page.url
        except Exception:
            pass
        self.log("🔒 CAPTCHA com o navegador oculto — reabrindo o navegador VISÍVEL pra você resolver…", "aviso")
        self.esperando_captcha = True
        self.fechar()
        self.headless = False
        self.abrir()
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        if url.startswith("http"):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

    def _qtd_respostas(self):
        return self.page.locator(SEL["bloco_resposta"]).count()

    def _gerando(self):
        """True enquanto o botão 'Parar' estiver visível."""
        return self.page.evaluate(
            """([s, oculto]) => [...document.querySelectorAll(s)]
                 .some(b => !b.classList.contains(oculto) && b.offsetParent !== null)""",
            [SEL["botao_parar"], CLASSE_OCULTO],
        )

    def _esperar_resposta(self, qtd_antes):
        p, inicio = self.page, time.time()
        limite = inicio + self.timeout_resposta

        # 1) espera aparecer um bloco novo de resposta
        self.log("Aguardando a IA começar a responder…")
        while self._qtd_respostas() <= qtd_antes:
            if time.time() > limite:
                raise ErroIA("SEM_RESPOSTA", f"A resposta da IA não apareceu em {self.timeout_resposta}s.",
                             "Pode ser captcha, lentidão ou mudança no layout do Google. Deixe o navegador visível "
                             "para ver o que acontece, ou aumente o tempo limite.")
            if self._checar_captcha():
                raise CaptchaResolvido()
            time.sleep(0.4)
        self.log("A IA está escrevendo a resposta…")

        # 2) espera parar de gerar e o texto estabilizar
        ultimo, desde = None, time.time()
        while time.time() < limite:
            if self._checar_captcha():
                raise CaptchaResolvido()
            falha = self._falha_google()
            if falha:
                raise ErroIA("GOOGLE_SEM_RESPOSTA", f"O Google não gerou resposta: \"{falha}\"",
                             "Acontece às vezes. O sistema já tenta de novo sozinho; se continuar, reformule a pergunta "
                             "ou espere alguns minutos.")
            dados = p.evaluate(JS_EXTRAIR, SEL) or {}
            # resposta pode ser só mídia (cartão de vídeo / galeria), sem texto
            tam = (len(dados.get("texto", "")) + len(dados.get("fontes", []))
                   + 50 * (len(dados.get("cartoes", [])) + len(dados.get("imagens", []))))
            if tam != ultimo:
                ultimo, desde = tam, time.time()
            elif not self._gerando() and time.time() - desde >= 2.5 and tam > 0:
                self.log("Resposta concluída.", "ok")
                return True
            time.sleep(0.5)
        self.log("Tempo limite atingido; usando a resposta parcial.", "aviso")
        return False

    def _falha_google(self):
        """Devolve a frase de erro do Google, se a resposta for uma recusa/falha (e não uma resposta de verdade)."""
        try:
            t = self.page.evaluate(JS_TEXTO_BLOCO, SEL) or {}
        except Exception:
            return None
        rodape = re.compile(r"As respostas da IA podem|A IA pode cometer erros|Copiado para a área|Boa resposta|"
                            r"Use o código com cuidado|Compartilhar link público")
        area = rodape.split(t.get("area") or "")[0]
        if len(area.strip()) > 400:
            return None  # tem resposta de verdade
        if not FALHAS_GOOGLE.search(t.get("bloco") or ""):
            return None
        # devolve a frase exata da mensagem do Google
        for pedaco in (t.get("pedacos") or []) + re.split(r"(?<=[.!?])\s*", t.get("bloco") or ""):
            if FALHAS_GOOGLE.search(pedaco):
                return " ".join(pedaco.split())[:160]
        return "resposta não gerada"

    def _resolver_url(self, href):
        """Os links do Google são /goto?url=... — segue o redirecionamento para o link real."""
        if href and href.startswith("/"):
            href = urljoin("https://www.google.com", href)
        if not href or "google." not in urlparse(href).netloc:
            return href
        qs = parse_qs(urlparse(href).query)
        for k in ("q", "url"):
            if k in qs and qs[k][0].startswith("http"):
                return qs[k][0]
        try:
            r = self.ctx.request.get(href, max_redirects=0, timeout=10000)
            loc = r.headers.get("location")
            if loc and loc.startswith("http"):
                return loc
            r = self.ctx.request.get(href, timeout=10000)
            if "google." not in urlparse(r.url).netloc:
                return r.url
        except Exception:
            pass
        return None

    def _digitar_e_enviar(self, campo, texto):
        campo.click()
        campo.fill(texto)
        time.sleep(0.3)
        enviar = self.page.locator(SEL["botao_enviar"]).filter(visible=True)
        try:
            if enviar.count() and enviar.first.is_enabled():
                enviar.first.click(timeout=3000)
                return
        except Exception:
            pass
        campo.press("Enter")  # botão ausente, desativado ou não clicável

    # ---------- fluxo principal ----------
    def _iniciar_conversa(self, pergunta):
        p = self.page
        self.log("Abrindo google.com…")
        try:
            p.goto(URL_HOME, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            raise classificar_erro(e)
        if self._checar_captcha():
            p = self.page  # pode ter reaberto o navegador (visível) pro captcha
            p.goto(URL_HOME, wait_until="domcontentloaded", timeout=30000)
        try:
            self.log("Clicando em \"Modo IA\"…")
            p.locator(SEL["botao_modo_ia"]).filter(has_text="Modo IA").first.click(timeout=8000)
            campo = p.locator(f'{SEL["chat_input"]}, {SEL["busca_home"]}').filter(visible=True).first
            campo.wait_for(timeout=10000)
            self.log("Enviando a pergunta…")
            self._digitar_e_enviar(campo, pergunta)
        except PWTimeout:
            # botão mudou/não apareceu: vai direto pela URL do Modo IA
            self.log("Botão \"Modo IA\" não encontrado; abrindo o Modo IA direto pela URL.", "aviso")
            try:
                p.goto(URL_MODO_IA.format(q=quote_plus(pergunta)), wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                raise classificar_erro(e)
        self.em_conversa = True

    def perguntar(self, pergunta, usar_instrucao=True, tentativas=4, texto_personalizado=None):
        """Envia a pergunta e devolve um dict/JSON: {pergunta, resposta_objetiva, resposta_completa, fontes, ...}.

        Conversa única: todas as perguntas vão na MESMA conversa (menos captcha). A instrução completa só vai
        na 1ª pergunta; as seguintes levam um lembrete curto. A cada `max_perguntas_conversa` abre uma nova.

        Se o Google recusar ("não há uma resposta disponível", "Something went wrong"):
          2ª tentativa: conversa nova com a instrução completa
          3ª tentativa: pergunta pura, sem instrução
        Se aparecer captcha, espera você resolver e reenvia a pergunta (não conta como tentativa)."""
        if self.max_perguntas_conversa and self.perguntas_na_conversa >= self.max_perguntas_conversa:
            self.log(f"A conversa chegou a {self.perguntas_na_conversa} perguntas; abrindo uma nova.")
            self.nova_conversa()
        # cada passo: (com_instrucao, forçar instrução completa, conversa nova)
        plano = [(usar_instrucao, False, False)]
        if texto_personalizado:
            # texto próprio (ex.: análise de vídeo): repete o mesmo texto; na 3ª vez numa conversa nova
            plano = [(True, False, False), (True, False, False), (True, False, True)]
        elif usar_instrucao:
            plano += [(True, True, False), (True, True, True), (False, False, False)]
        else:
            plano += [(False, False, True)]
        plano = plano[:max(1, tentativas)]
        ultimo_erro, parcial, n, reenvios_captcha = None, None, 0, 0
        while n < len(plano):
            com_instrucao, completa_forcada, conversa_nova = plano[n]
            n += 1
            if n > 1:
                desc = ("conversa nova, " if conversa_nova else "mesma conversa, ") + (
                    "instrução completa" if completa_forcada else ("com instrução" if com_instrucao else "sem instrução"))
                self.log(f"Tentativa {n}/{len(plano)} ({desc})…", "aviso")
                if conversa_nova:
                    self.nova_conversa()
                time.sleep(3)
            try:
                if completa_forcada:
                    self.instrucao_enviada = False  # força a instrução completa
                r = self._perguntar_uma_vez(pergunta, com_instrucao, texto_personalizado)
                r["tentativas"] = n
                if n > 1 and usar_instrucao and not com_instrucao and not texto_personalizado:
                    r["aviso"] = "O Google recusou a pergunta com a instrução de formato; esta resposta veio sem ela."
                return r
            except CaptchaResolvido:
                reenvios_captcha += 1
                if reenvios_captcha > 3:
                    raise ErroIA("CAPTCHA", "O Google pediu captcha várias vezes seguidas.",
                                 "Espere alguns minutos antes de continuar.")
                self.log("Reenviando a pergunta depois do captcha…")
                self.nova_conversa()
                n -= 1  # captcha não conta como tentativa
            except ErroIA as e:
                if e.codigo not in ("GOOGLE_SEM_RESPOSTA", "GOOGLE_SO_LINKS"):
                    raise
                self.log(e.mensagem, "aviso")
                ultimo_erro = e
                if getattr(e, "resultado_parcial", None):
                    parcial = e.resultado_parcial
        if parcial:
            parcial["tentativas"] = n
            parcial["aviso"] = ("A IA do Google não gerou resposta para esta pergunta (mostrou só resultados da web). "
                                "A resposta foi montada com esses resultados.")
            self.historico.append(parcial)
            return parcial
        raise ultimo_erro

    def _perguntar_uma_vez(self, pergunta, usar_instrucao=True, texto_personalizado=None):
        if texto_personalizado:
            texto_envio = texto_personalizado
        elif not usar_instrucao:
            texto_envio = pergunta
        elif self.em_conversa and self.instrucao_enviada:
            texto_envio = INSTRUCAO_CURTA.format(pergunta=pergunta)
        else:
            texto_envio = INSTRUCAO.format(pergunta=pergunta)
        qtd_antes = self._qtd_respostas() if self.em_conversa else 0
        if not self.em_conversa:
            self._iniciar_conversa(texto_envio)
        else:
            campo = self.page.locator(SEL["chat_input"]).filter(visible=True).first
            try:
                campo.wait_for(timeout=15000)
            except PWTimeout:
                raise ErroIA("CAMPO_NAO_ENCONTRADO",
                             "Não encontrei a caixa \"Pergunte o que quiser\" para continuar a conversa.",
                             "Comece uma nova conversa. Se continuar, o layout do Google mudou: salve o HTML (/debug) "
                             "e ajuste o seletor chat_input em SEL.")
            self.log("Enviando pergunta de acompanhamento…")
            self._digitar_e_enviar(campo, texto_envio)

        self.perguntas_na_conversa += 1
        if usar_instrucao and not texto_personalizado:
            self.instrucao_enviada = True
        completa = self._esperar_resposta(qtd_antes)
        dados = self.page.evaluate(JS_EXTRAIR, SEL) or {"texto": "", "markdown": "", "fontes": [], "citados": []}
        markdown = dados.get("markdown") or dados.get("texto", "")
        falha = self._falha_google()
        if falha:
            raise ErroIA("GOOGLE_SEM_RESPOSTA", f"O Google não gerou resposta: \"{falha}\"",
                         "Acontece às vezes. Tente de novo ou reformule a pergunta.")
        json_bruto = extrair_json_bruto(dados.get("codigos") or [], markdown, dados.get("texto", ""))
        if dados.get("so_links") and not json_bruto:
            erro = ErroIA("GOOGLE_SO_LINKS", "O Google não gerou resposta de IA; mostrou só uma lista de resultados da web.",
                          "Acontece às vezes. O sistema tenta de novo sozinho.")
            erro.resultado_parcial = self._resultado_de_links(pergunta, dados)
            raise erro
        if not markdown.strip() and not dados.get("imagens") and not dados.get("cartoes"):
            raise ErroIA("RESPOSTA_VAZIA", "A página carregou, mas não consegui ler o texto da resposta.",
                         "O layout do Google pode ter mudado. Veja o print e ajuste os seletores bloco_resposta/texto_resposta em SEL.")
        if self.resolver_links:
            self.log(f"Resolvendo links de {len(dados['fontes'])} fontes…")

        # resolve links /goto?... do Google para o link real (cache evita repetir)
        cache = {}
        def resolver(h):
            if h not in cache:
                cache[h] = self._resolver_url(h) if self.resolver_links else None
            return cache[h]

        def troca_link(m):
            url = m.group(2)
            if url.startswith("/"):
                url = urljoin("https://www.google.com", url)
            if "google." in urlparse(url).netloc:
                url = resolver(url) or url
            return f"[{m.group(1)}]({url})"
        markdown = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", troca_link, markdown)

        fontes = []
        for f in dados["fontes"]:
            href = urljoin("https://www.google.com", f["href"]) if f["href"] else ""
            if urlparse(href).path.startswith(("/goto", "/url")):
                url = resolver(href) or f.get("dominio") or href
            else:
                url = href  # já é o link final
            fontes.append({"titulo": f["titulo"], "site": f["site"], "url": url,
                           "trecho": f["trecho"], "origem": "painel_google"})

        # links citados no meio do texto (a URL real vem do aria-label; senão, resolve o /goto)
        links_texto = []
        for c in dados.get("citados", []):
            url = c.get("url_aria") or ""
            if not url:
                href = urljoin("https://www.google.com", c["href"])
                url = (resolver(href) or href) if urlparse(href).path.startswith(("/goto", "/url")) else href
            if url:
                links_texto.append({"titulo": c.get("titulo") or c["texto"], "site": c.get("site") or urlparse(url).netloc,
                                    "url": url, "trecho": c["texto"], "origem": "link_no_texto"})

        # cartões: vídeos e links em destaque
        videos, destaques = [], []
        for c in dados.get("cartoes", []):
            href = urljoin("https://www.google.com", c["href"]) if c["href"] else ""
            url = c.get("url_aria") or resolver(href) or href
            item = {"titulo": c["titulo"], "url": url, "canal": c["canal"], "duracao": c["duracao"],
                    "visualizacoes": c["visualizacoes"], "quando": c["quando"]}
            yt = re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})", url or "")
            item["miniatura"] = f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg" if yt else ""
            (videos if c["tipo"] == "video" else destaques).append(item)

        imagens = [{k: im[k] for k in ("titulo", "site", "pagina", "imagem", "miniatura", "largura", "altura")}
                   for im in dados.get("imagens", [])]

        # 1º tenta ler a resposta em JSON (bloco de código); se não houver, separa por seções
        dados_json = extrair_json_resposta(dados.get("codigos") or [], markdown, dados.get("texto", ""))
        if dados_json:
            self.log("Resposta em JSON lida com sucesso.", "ok")
            secoes = {"objetiva": dados_json["resposta_objetiva"], "completa": dados_json["resposta_completa"],
                      "formato_respeitado": True}
            fontes_ia = dados_json["fontes"]
            urls_v = {v["url"] for v in videos}
            for v in dados_json["midias"]["videos"]:
                if v["url"] not in urls_v:
                    yt = re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})", v["url"])
                    videos.append({"titulo": v["titulo"], "url": v["url"], "canal": "", "duracao": "",
                                   "visualizacoes": "", "quando": "",
                                   "miniatura": f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg" if yt else ""})
            urls_i = {i["imagem"] for i in imagens}
            for im in dados_json["midias"]["imagens"]:
                if im["url"] not in urls_i:
                    imagens.append({"titulo": im["titulo"], "site": urlparse(im.get("pagina") or im["url"]).netloc,
                                    "pagina": im.get("pagina", ""), "imagem": im["url"], "miniatura": im["url"],
                                    "largura": None, "altura": None})
        else:
            if usar_instrucao:
                self.log("A IA não respondeu em JSON; separando a resposta pelo texto.", "aviso")
            secoes = separar_secoes(markdown)
            fontes_ia = extrair_fontes_texto(secoes["fontes"])

        # junta as fontes da IA com as do painel do Google (sem repetir e sem links do próprio Google)
        todas, vistos = [], set()
        extras = links_texto + [{"titulo": v["titulo"], "site": v["canal"] or urlparse(v["url"]).netloc,
                                 "url": v["url"], "trecho": "", "origem": "video"} for v in videos + destaques]
        for f in [{**f, "origem": "citada_pela_ia"} for f in fontes_ia] + fontes + extras:
            chave = f["url"].rstrip("/").lower()
            if not f["url"].startswith("http") or link_do_google(f["url"]) or chave in vistos:
                continue
            vistos.add(chave)
            todas.append({"titulo": f.get("titulo") or f.get("site") or "", "site": f.get("site") or urlparse(f["url"]).netloc,
                          "url": f["url"], "trecho": f.get("trecho", ""), "origem": f["origem"]})

        if not secoes["objetiva"].strip():
            if videos:
                secoes["objetiva"] = "Vídeo encontrado: " + (videos[0]["titulo"] or videos[0]["url"])
            elif imagens:
                secoes["objetiva"] = f"{len(imagens)} imagem(ns) encontrada(s)."
        resultado = {
            "pergunta": pergunta,
            "resposta_objetiva": secoes["objetiva"],
            "resposta_completa": secoes["completa"],
            "fontes": todas,
            "midias": {"videos": videos, "imagens": imagens, "links_destaque": destaques,
                       "produtos": [{"nome": p["nome"], "url": urljoin("https://www.google.com", p["url"])}
                                    for p in dados.get("produtos", [])]},
            "formato_respeitado": secoes["formato_respeitado"],
            "completa": completa,
            "data": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resposta_bruta_md": markdown,
            "json": json_bruto,   # o JSON da IA exatamente como veio (útil para formatos próprios, ex.: vídeo)
        }
        self.historico.append(resultado)
        return resultado

    def _resultado_de_links(self, pergunta, dados):
        """Monta uma resposta a partir da lista "principais resultados da Web" (quando a IA não respondeu)."""
        fontes, vistos = [], set()
        for it in dados.get("resultados_web", []):
            href = it["href"]
            url = (self._resolver_url(href) if self.resolver_links else None) or it.get("exibida") or href
            if url in vistos:
                continue
            vistos.add(url)
            fontes.append({"titulo": it["titulo"], "site": it["site"] or urlparse(url).netloc, "url": url,
                           "trecho": it["trecho"], "origem": "resultado_web"})
        primeiro = fontes[0] if fontes else None
        objetiva = ("A IA do Google não respondeu esta pergunta; segundo o principal resultado da web "
                    f"({primeiro['site']}): {primeiro['trecho']}" if primeiro and primeiro["trecho"]
                    else "A IA do Google não respondeu esta pergunta; veja os resultados da web nas fontes.")
        completa = "**A IA do Google não gerou uma resposta. Principais resultados da web:**\n\n" + "\n".join(
            f"- **[{f['titulo']}]({f['url']})** — {f['site']}\n  {f['trecho']}" for f in fontes)
        return {"pergunta": pergunta, "resposta_objetiva": objetiva, "resposta_completa": completa,
                "fontes": fontes, "midias": {"videos": [], "imagens": [], "links_destaque": [], "produtos": []},
                "formato_respeitado": False, "completa": True, "so_resultados_web": True,
                "data": time.strftime("%Y-%m-%dT%H:%M:%S"), "resposta_bruta_md": dados.get("markdown", "")}

    def perguntar_json(self, pergunta, **kw):
        return json.dumps(self.perguntar(pergunta, **kw), ensure_ascii=False, indent=2)

    def nova_conversa(self):
        """A próxima pergunta abre uma conversa nova."""
        self.em_conversa = False
        self.perguntas_na_conversa = 0
        self.instrucao_enviada = False

    def salvar_debug(self, nome=None):
        DEBUG_DIR.mkdir(exist_ok=True)
        nome = nome or time.strftime("%Y%m%d-%H%M%S")
        (DEBUG_DIR / f"pagina_{nome}.html").write_text(self.page.content(), encoding="utf-8")
        self.page.screenshot(path=str(DEBUG_DIR / f"tela_{nome}.png"), full_page=True)

    def salvar_resposta(self, r):
        """Salva uma resposta em resultados/ (.json e .md)."""
        SAIDA_DIR.mkdir(exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", r["pergunta"].lower())[:50].strip("-") or "pergunta"
        base = SAIDA_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}"
        base.with_suffix(".json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        base.with_suffix(".md").write_text(formatar_md(r), encoding="utf-8")
        return base.with_suffix(".json")

    def salvar_historico(self, nome=None):
        SAIDA_DIR.mkdir(exist_ok=True)
        nome = nome or time.strftime("%Y%m%d-%H%M%S")
        caminho_json = SAIDA_DIR / f"conversa_{nome}.json"
        caminho_json.write_text(json.dumps(self.historico, ensure_ascii=False, indent=2), encoding="utf-8")
        caminho_md = SAIDA_DIR / f"conversa_{nome}.md"
        caminho_md.write_text("\n\n---\n\n".join(formatar_md(r) for r in self.historico), encoding="utf-8")
        return caminho_json, caminho_md


# domínios do Google que NÃO são fonte (rodapé, políticas, suporte, login…)
_GOOGLE_NAO_FONTE = re.compile(r"(^|\.)(google\.[a-z.]+|gstatic\.com|googleusercontent\.com|policies\.google\.com|"
                               r"support\.google\.com|accounts\.google\.com)$")


def link_do_google(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    if urlparse(url).path.startswith(("/goto", "/url")):
        return False  # redirecionamento do Google para o site real: mantém como fonte
    # Google Finance/Notícias às vezes são fontes legítimas
    if host.endswith("google.com") and urlparse(url).path.startswith(("/finance", "/news")) \
            and not host.startswith(("policies.", "support.", "accounts.")):
        return False
    return bool(_GOOGLE_NAO_FONTE.search(host))


def _sem_acento(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _chave(d, *nomes):
    """Busca uma chave do dict ignorando maiúsculas, acentos, espaços e _ (ex.: 'Resposta Objetiva')."""
    norm = {re.sub(r"[\s_\-]", "", _sem_acento(str(k)).lower()): v for k, v in d.items()}
    for n in nomes:
        v = norm.get(re.sub(r"[\s_\-]", "", n))
        if v not in (None, ""):
            return v
    return None


def _carregar_json(texto):
    """Lê o JSON da IA de forma tolerante: com ou sem bloco de código, com quebras de linha
    dentro das strings, vírgula sobrando, links em markdown etc."""
    texto = (texto or "").strip()
    texto = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", texto)
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini < 0 or fim <= ini:
        return None
    bruto = texto[ini:fim + 1]
    # links que o conversor transformou em markdown: "[https://x](https://x)" -> "https://x"
    sem_md = re.sub(r"\[(https?://[^\]\s]+)\]\(\1\)", r"\1", bruto)
    for tentativa in (bruto, sem_md, re.sub(r",\s*([}\]])", r"\1", sem_md)):
        try:
            d = json.loads(tentativa, strict=False)  # strict=False aceita quebra de linha dentro de string
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            continue
    return _json_por_regex(sem_md)


def _json_por_regex(t):
    """Último recurso: JSON quebrado/cortado. Pega as chaves principais por expressão regular."""
    def campo(nome):
        m = re.search(r'"' + nome + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', t, re.S)
        if not m:
            return None
        try:
            return json.loads('"' + m.group(1) + '"', strict=False)
        except json.JSONDecodeError:
            return m.group(1).replace('\\n', '\n').replace('\\"', '"')
    obj, comp = campo("resposta_objetiva"), campo("resposta_completa")
    if obj is None and comp is None:
        return None
    fontes = []
    for bloco in re.findall(r"\{[^{}]*\"url\"[^{}]*\}", t):
        try:
            fontes.append(json.loads(bloco, strict=False))
        except json.JSONDecodeError:
            u = re.search(r'"url"\s*:\s*"([^"]+)"', bloco)
            n = re.search(r'"(?:nome|titulo)"\s*:\s*"([^"]+)"', bloco)
            if u:
                fontes.append({"url": u.group(1), "nome": n.group(1) if n else ""})
    return {"resposta_objetiva": obj or "", "resposta_completa": comp or "", "fontes": fontes}


def _url_limpa(u):
    """'[https://x](https://x)' -> 'https://x';  'bcb.gov.br' -> 'https://bcb.gov.br'"""
    u = str(u or "").strip()
    m = re.search(r"https?://[^\s\])>\"']+", u)
    if m:
        return m.group(0).rstrip(".,;")
    if re.fullmatch(r"(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", u, re.I):
        return "https://" + u
    return ""


def _para_markdown(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "\n".join(f"- {_para_markdown(x)}" for x in v)
    if isinstance(v, dict):
        return "\n".join(f"- **{k}:** {_para_markdown(x)}" for k, x in v.items())
    return "" if v is None else str(v)


def extrair_json_bruto(codigos, markdown="", texto=""):
    """Primeiro objeto JSON que a IA mandou (bloco de código ou texto solto), sem exigir chaves específicas."""
    candidatos = list(codigos) + re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", markdown or "", re.S)
    candidatos += [t for t in (texto, markdown) if t and "{" in t]
    for c in candidatos:
        d = _carregar_json(c)
        if d:
            return d
    return None


def extrair_json_resposta(codigos, markdown="", texto=""):
    """Procura a resposta em JSON (bloco de código da IA) e normaliza para
    {resposta_objetiva, resposta_completa, fontes:[{titulo, site, url}]}."""
    candidatos = list(codigos) + re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", markdown or "", re.S)
    # a IA às vezes manda o JSON como texto solto (sem bloco de código)
    for t in (texto, markdown):
        if t and '"resposta_' in t:
            candidatos.append(t)
    for c in candidatos:
        d = _carregar_json(c)
        if not d:
            continue
        objetiva = _chave(d, "respostaobjetiva", "objetiva", "resumo", "respostacurta", "resposta")
        completa = _chave(d, "respostacompleta", "completa", "detalhes", "explicacao", "respostadetalhada")
        if objetiva is None and completa is None:
            continue
        fontes_brutas = _chave(d, "fontes", "links", "referencias", "sources", "fonte") or []
        if isinstance(fontes_brutas, (str, dict)):
            fontes_brutas = [fontes_brutas]
        fontes = []
        for f in fontes_brutas:
            if isinstance(f, str):
                m = re.search(r"https?://\S+", f)
                if m:
                    url = m.group(0).rstrip(".,;)")
                    nome = f.replace(m.group(0), "").strip(" :-—–()") or urlparse(url).netloc
                    fontes.append({"titulo": nome, "site": urlparse(url).netloc, "url": url})
            elif isinstance(f, dict):
                url = _url_limpa(_chave(f, "url", "link", "href", "endereco"))
                if not url:
                    continue
                nome = _chave(f, "nome", "site", "fonte", "veiculo") or urlparse(url).netloc
                titulo = _chave(f, "titulo", "title", "pagina", "materia") or nome
                fontes.append({"titulo": str(titulo), "site": str(nome), "url": str(url)})
        midias = {"videos": [], "imagens": []}
        bloco_midias = _chave(d, "midias", "media", "midia") or {}
        if isinstance(bloco_midias, dict):
            for tipo, nomes in (("videos", ("videos", "video")), ("imagens", ("imagens", "imagem", "images", "fotos"))):
                lista = _chave(bloco_midias, *nomes) or []
                for m in lista if isinstance(lista, list) else [lista]:
                    if isinstance(m, str):
                        m = {"url": m}
                    if not isinstance(m, dict):
                        continue
                    url = _url_limpa(_chave(m, "url", "link", "src"))
                    if not url:
                        continue
                    item = {"titulo": str(_chave(m, "titulo", "title", "nome", "descricao") or ""), "url": url}
                    if tipo == "imagens":
                        item["pagina"] = _url_limpa(_chave(m, "pagina", "origem", "fonte", "page"))
                    midias[tipo].append(item)
        objetiva = " ".join(_sem_markdown(_para_markdown(objetiva or "")).split())
        completa = _para_markdown(completa or "")
        if not objetiva:
            objetiva = resposta_objetiva(completa)
        return {"resposta_objetiva": objetiva, "resposta_completa": completa or objetiva, "fontes": fontes,
                "midias": midias}
    return None


def _sem_markdown(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", t)
    return re.sub(r"^[#>\-\s]+", "", t).strip()


RE_TITULO = re.compile(
    r"(?:^|\n)[ \t#>*_]*(RESPOSTA\s+OBJETIVA|RESPOSTA\s+COMPLETA|FONTES(?:\s+(?:UTILIZADAS|USADAS|CONSULTADAS))?)"
    r"[ \t*_]*:?[ \t*_]*",
    re.I,
)


def separar_secoes(markdown):
    """Divide a resposta da IA nas seções RESPOSTA OBJETIVA / RESPOSTA COMPLETA / FONTES.
    Se a IA não seguir o formato, usa o 1º parágrafo como objetiva e o resto como completa."""
    partes = {}
    achados = list(RE_TITULO.finditer(markdown or ""))
    for i, m in enumerate(achados):
        nome = m.group(1).upper()
        chave = "objetiva" if "OBJETIVA" in nome else "completa" if "COMPLETA" in nome else "fontes"
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(markdown)
        trecho = markdown[m.end():fim].strip().strip("*_").strip()
        if chave not in partes:
            partes[chave] = trecho
    ok = "objetiva" in partes and "completa" in partes
    if not ok:
        partes.setdefault("completa", (markdown or "").strip())
        partes.setdefault("objetiva", resposta_objetiva(partes["completa"]))
    # a objetiva fica em texto puro, 1 linha
    partes["objetiva"] = " ".join(_sem_markdown(l) for l in partes["objetiva"].splitlines() if l.strip())
    return {"objetiva": partes["objetiva"], "completa": partes["completa"],
            "fontes": partes.get("fontes", ""), "formato_respeitado": ok}


def extrair_fontes_texto(texto):
    """Pega links da seção FONTES escrita pela IA: [nome](url), 'Nome: url' ou url solta."""
    fontes, vistos = [], set()
    for linha in (texto or "").splitlines():
        for nome, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", linha):
            if url not in vistos:
                vistos.add(url)
                fontes.append({"titulo": nome.strip(), "site": urlparse(url).netloc, "url": url})
        for url in re.findall(r"(?<![(\[])\bhttps?://[^\s)\]]+", linha):
            url = url.rstrip(".,;")
            if url not in vistos:
                vistos.add(url)
                nome = re.sub(r"^\d+[.)]\s*", "", _sem_markdown(linha.split(url)[0])).strip(" :—-–") \
                       or urlparse(url).netloc
                fontes.append({"titulo": nome, "site": urlparse(url).netloc, "url": url})
    return fontes


def resposta_objetiva(markdown, max_frases=2, max_chars=400):
    """Fallback: 1º parágrafo de texto da resposta, limitado a ~2 frases."""
    for bloco in re.split(r"\n\s*\n", markdown or ""):
        b = bloco.strip()
        if not b or b.startswith(("#", ">", "- ", "|")) or re.match(r"^\d+\. ", b):
            continue
        texto = _sem_markdown(" ".join(b.split()))
        frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9])", texto)
        curto = " ".join(frases[:max_frases])
        if len(curto) > max_chars:
            curto = curto[:max_chars].rsplit(" ", 1)[0] + "…"
        return curto
    return _sem_markdown((markdown or "").strip().split("\n")[0])


def formatar_md(r):
    """Versão legível (markdown) do JSON: objetiva, completa e fontes."""
    linhas = [f"# {r['pergunta']}", "", "## Resposta objetiva", "", f"> {r['resposta_objetiva']}", "",
              "## Resposta completa", "", r["resposta_completa"] or "_(sem resposta)_", "", "## Fontes", ""]
    for i, f in enumerate(r["fontes"], 1):
        linhas.append(f"{i}. **[{f['titulo'] or f['site'] or f['url']}]({f['url']})** — {f['site']}")
        if f.get("trecho"):
            linhas.append(f"   > {f['trecho']}")
    if not r["fontes"]:
        linhas.append("_Nenhuma fonte encontrada._")
    return "\n".join(linhas) + "\n"


if __name__ == "__main__":
    import sys

    # modo 1: python ia_google.py "sua pergunta"  -> imprime só o JSON
    if len(sys.argv) > 1:
        with GoogleIA(headless=False) as ia:
            try:
                r = ia.perguntar(" ".join(sys.argv[1:]))
            except Exception as e:
                print(json.dumps({"erro": classificar_erro(e).to_dict()}, ensure_ascii=False, indent=2))
                sys.exit(1)
            ia.salvar_resposta(r)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0)

    # modo 2: chat no terminal (cada resposta sai em JSON)
    print("Modo IA do Google — digite sua pergunta (resposta em JSON).")
    print("Comandos: /nova (nova conversa), /debug (salva HTML), /sair\n")
    with GoogleIA(headless=False) as ia:
        try:
            while True:
                q = input("Você: ").strip()
                if not q:
                    continue
                if q == "/sair":
                    break
                if q == "/nova":
                    ia.nova_conversa()
                    print("(nova conversa)\n")
                    continue
                if q == "/debug":
                    ia.salvar_debug()
                    print("(HTML salvo em debug/)\n")
                    continue
                try:
                    r = ia.perguntar(q)
                except Exception as e:
                    erro = classificar_erro(e)
                    print(f"\n❌ [{erro.codigo}] {erro.mensagem}")
                    if erro.dica:
                        print(f"   Como resolver: {erro.dica}")
                    print(f"   (print salvo em {ia.salvar_print(DEBUG_DIR / ('erro_' + time.strftime('%H%M%S')))})\n")
                    ia.nova_conversa()
                    continue
                print(json.dumps({k: v for k, v in r.items() if k != "resposta_bruta_md"},
                                 ensure_ascii=False, indent=2))
                print(f"(salvo em {ia.salvar_resposta(r)})\n")
        finally:
            if ia.historico:
                j, m = ia.salvar_historico()
                print(f"Conversa salva em {j} e {m}")
