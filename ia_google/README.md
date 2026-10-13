# Pesquisa IA — chat + API local usando o Modo IA do Google

Você pergunta e o sistema pesquisa no **Modo IA do Google** por um navegador automatizado.
Toda resposta volta no mesmo formato:

- **Resposta objetiva**: direta, em 1 ou 2 frases
- **Resposta completa**: em Markdown
- **Fontes**: título, site, trecho e link

> **Dentro do BestEditor:** este app sobe sozinho pela aba **🔎 IA do Google** do site, na porta **8852**
> (mude em ⚙️ Configurações). O site usa a API dele no agente do YouTube e no "Checar fatos" do Roteiro do YouTube.
> Rodando sozinho (`iniciar.bat`), ele continua na porta 5000 — use `PORTA=8852` se o site também estiver aberto.

## Iniciar

**Windows:** clique duas vezes em `iniciar.bat`. Na 1ª vez ele instala tudo e depois abre o chat.
**Linux/Mac:** `./iniciar.sh`

**Manual:**
```bash
pip install -r requirements.txt
playwright install chromium
python app.py
```
Depois abra **http://127.0.0.1:5000**.

A janela do Chromium abre na primeira pergunta e fica aberta, para as próximas serem mais rápidas.
Se aparecer um captcha, resolva nessa janela que a pesquisa continua.

## Chat

- **Continuar conversa** ligado: as perguntas seguem a mesma conversa no Google (dá para fazer perguntas de acompanhamento).
  Desligado: cada pergunta abre uma conversa nova.
- **Histórico** na lateral: as conversas ficam salvas em `conversas/*.json`.
- Em cada resposta: copiar a objetiva, copiar o markdown, copiar o JSON ou ver o JSON.

## 🎬 Vídeos do YouTube

O Modo IA do Google consegue "assistir" a vídeos do YouTube. Na aba **🎬 Vídeo** do app você cola o link,
o vídeo aparece no player e você escolhe o que fazer. **Clique em qualquer tempo (▶ 1:05) para o player pular até ele.**

| Tarefa | O que faz |
|---|---|
| 📝 Resumo | resumo curto + completo, tópicos com início/fim, pontos-chave e conclusão |
| ❓ Perguntar | responde qualquer pergunta sobre o vídeo, mostrando os trechos que comprovam |
| ⏱️ Achar momentos | início e fim de **cada** momento em que algo acontece ("quando ele fala de X") |
| 📑 Capítulos | capítulos com tempo, já no formato para colar na descrição do YouTube |
| ✂️ Cortes p/ Shorts | melhores trechos para Shorts/Reels/TikTok, com início, fim, gancho e nota |
| 💬 Frases marcantes | citações exatas com o tempo e quem falou |
| 🔎 Checar fatos | lista as afirmações do vídeo e verifica cada uma com fontes |
| 🧭 Passo a passo | transforma tutoriais em etapas com o tempo de cada uma |
| 🏷️ Título, descrição e tags | sugestões de SEO para o vídeo |
| 🎓 Quiz | perguntas de múltipla escolha com o tempo da resposta |
| 📜 Transcrição | o que é falado, com tempo (pode vir resumida em vídeos longos) |
| 🌐 Resumo em outro idioma | resumo e pontos principais no idioma escolhido |
| ⚖️ Comparar 2 vídeos | semelhanças, diferenças e qual assistir |
| ✨ Pedido livre | qualquer pedido; a resposta vem com os momentos citados |

As perguntas sobre o **mesmo vídeo** continuam na mesma conversa (a IA já "assistiu"); um vídeo novo abre conversa nova.
No **chat**, colar só o link faz o resumo; link + texto faz uma pergunta sobre o vídeo.

**API:** `POST /api/video` com `{"url": "...", "tarefa": "momentos", "consulta": "quando fala do paradoxo de Simpson"}`.
Cada tempo vem também em segundos e com link direto: `inicio`, `inicio_seg`, `inicio_link` (`youtu.be/ID?t=65`).
`GET /api/video/tarefas` lista as tarefas.

**Em Python:**
```python
from ia_google import GoogleIA
from youtube import AnalisadorYouTube
with GoogleIA() as ia:
    yt = AnalisadorYouTube(ia)
    r = yt.executar("https://youtu.be/ZENXID79hHw", "momentos", "a frase sobre o presente")
    for m in r["dados"]["momentos"]:
        print(m["inicio"], m["fim"], m["descricao"], m["inicio_link"])
```

**Testar a precisão dos tempos:** `python testar_video.py` (ou `testar_video.bat`). Ele analisa os vídeos de teste e
compara os tempos que a IA deu com as transcrições reais da pasta `transcricoes/`: confere se os momentos
encontrados estão no lugar certo, se as respostas estão corretas e se cada frase citada está mesmo no tempo indicado.
No fim mostra um **placar de precisão** e, se algo falhar, gera o `falhas_video_*.zip` para enviar.
Para testar outros vídeos, coloque a transcrição deles em `transcricoes/` (linhas no formato `m:ss texto`) e rode
`python testar_video.py --url LINK`.

## Configurações (⚙️ na barra lateral)

- **Navegador visível / invisível**: visível mostra a janela do Chromium e deixa você resolver captchas
  (recomendado). Invisível roda escondido, mas o Google pede captcha com mais frequência.
  Ao trocar, o navegador é reaberto no novo modo na próxima pesquisa (ou na hora, com **Reiniciar**).
- **Testar navegador**: abre o Google e mostra, passo a passo, o que está ok e o que falhou.
- **Reiniciar / Fechar navegador**
- Tempo limite da resposta, tempo de espera do captcha, descobrir o link real das fontes,
  enviar a instrução de formato, salvar print quando der erro e fechar o navegador sem uso.

As configurações ficam salvas em `config.json`.

## Quando dá erro

O erro aparece no chat como um cartão vermelho com:
- **o que aconteceu**, em português, e um **código** (ex.: `CAPTCHA`, `SEM_RESPOSTA`, `SEM_INTERNET`,
  `NAVEGADOR_NAO_INSTALADO`, `GOOGLE_SEM_RESPOSTA`, `CAMPO_NAO_ENCONTRADO`, `RESPOSTA_VAZIA`, `PERFIL_EM_USO`, `NAVEGADOR_FECHADO`)
- **como resolver**
- **print da tela** e **HTML da página** no momento do erro (salvos em `erros/`)
- **detalhes técnicos** (erro original e traceback)
- botão **Tentar de novo**

Além disso:
- A bolinha no canto inferior esquerdo fica vermelha e o item **📋 Registro** ganha a marca "erro".
- No **Registro** está o último erro (com o print) e o passo a passo de tudo o que o sistema fez
  (abrindo navegador, enviando pergunta, aguardando a IA…), atualizado ao vivo.
- Enquanto pesquisa, o chat mostra a etapa atual (ex.: "Aguardando a IA começar a responder… 12s").
- **Captcha:** com o navegador visível, o sistema detecta o captcha (inclusive a página de "tráfego incomum"),
  fica monitorando e, assim que você resolve na janela, **continua sozinho** (reenviando a pergunta se
  preciso). Por padrão espera sem limite (`Esperar captcha` = 0 nas configurações).

## Conversa única (menos captcha)

Todas as perguntas vão para a **mesma conversa** do Modo IA, o que gera bem menos captcha do que abrir uma conversa
a cada pergunta. A instrução de formato completa só vai na 1ª pergunta; as seguintes levam um lembrete curto.
Depois de 25 perguntas (ajustável em **Perguntas por conversa**) abre-se uma conversa nova, para a página
não ficar pesada. O botão **Nova conversa** do chat também começa uma conversa nova no Google.

## API local (as mesmas rotas que o chat usa)

| Método | Rota | O que faz |
|---|---|---|
| POST | `/api/pesquisar` | `{"pergunta": "...", "nova_conversa": true}` e devolve o JSON |
| GET | `/api/pesquisar?q=...&nova=1` | o mesmo, direto pela barra do navegador |
| POST | `/api/nova` | começa uma conversa nova |
| GET | `/api/conversas` | lista o histórico |
| GET | `/api/conversas/<id>` | uma conversa inteira |
| GET | `/api/status` | navegador aberto/ocupado, etapa atual e último erro |
| GET/POST | `/api/config` | ler/alterar configurações (`{"navegador_visivel": false}`) |
| POST | `/api/navegador/testar` | testa o navegador passo a passo |
| POST | `/api/navegador/reiniciar` | fecha e reabre o navegador |
| POST | `/api/navegador/fechar` | fecha o navegador |
| GET | `/api/logs` | registro de eventos |

```python
import requests
r = requests.post("http://127.0.0.1:5000/api/pesquisar",
                  json={"pergunta": "notícias de IA hoje", "nova_conversa": True},
                  timeout=300).json()
print(r["resposta_objetiva"])
```

Resposta:
```json
{
  "conversa_id": "20261013-084000-ab12",
  "pergunta": "qual o dólar hoje",
  "resposta_objetiva": "O dólar comercial está cotado a R$ 4,99 hoje.",
  "resposta_completa": "markdown...",
  "fontes": [{"titulo": "...", "site": "UOL Economia", "url": "https://...", "trecho": "...", "origem": "painel_google"}],
  "midias": {
    "videos":  [{"titulo": "...", "url": "https://youtube.com/...", "canal": "...", "duracao": "58s", "visualizacoes": "...", "miniatura": "..."}],
    "imagens": [{"titulo": "...", "site": "pt.wikipedia.org", "pagina": "https://...", "imagem": "https://...jpg", "miniatura": "...", "largura": 250, "altura": 334}],
    "links_destaque": [],
    "produtos": [{"nome": "Lenovo IdeaPad Slim", "url": "https://www.google.com/search?ibp=oshop..."}]
  },
  "formato_respeitado": true,
  "completa": true,
  "data": "2026-10-13T08:40:00",
  "tempo_segundos": 14.2
}
```
`origem` pode ser:
- `citada_pela_ia`: link que a IA colocou no JSON/seção FONTES
- `painel_google`: painel de fontes do Google
- `link_no_texto`: link no meio do texto da resposta (a URL real é lida da página)
- `video`: cartão de vídeo/link em destaque
Em caso de erro a API devolve status 500 com `{"erro": "...", "detalhes_erro": {"codigo", "mensagem", "dica", "print", ...}}`.
### Como as fontes são obtidas

Junto com a sua pergunta, o sistema envia uma instrução pedindo que a IA responda **só com um bloco JSON**
(`resposta_objetiva`, `resposta_completa`, `fontes: [{nome, titulo, url}]`) usando os links reais das páginas.
O sistema lê esse bloco direto da página, junta com o painel de fontes do Google (quando aparece) e
descarta links do próprio Google (Privacidade, Termos, Suporte…).

Às vezes o Google recusa ("Parece que não há uma resposta disponível…", "Something went wrong…").
O sistema reconhece isso na hora e tenta de novo sozinho: 2ª vez numa conversa nova e 3ª vez sem a
instrução de formato. Nesse último caso a resposta vem com o campo `aviso` e `tentativas: 3`.

Não coloque exemplos com `https://` no texto da instrução: o Google transforma em anexo e se confunde.

`formato_respeitado: false` quer dizer que a IA não respondeu em JSON. Nesse caso o sistema separa a resposta
pelo texto, e a objetiva vira o 1º parágrafo. O texto da instrução fica em `INSTRUCAO`, no `ia_google.py`.

Várias requisições ao mesmo tempo entram numa fila e são atendidas uma por vez, porque o navegador é um só.

## Sem interface (terminal)

```bash
python ia_google.py "sua pergunta"   # imprime só o JSON
python ia_google.py                  # chat no terminal
```

## Testes automáticos (`testar.py`)

Faz dezenas de perguntas reais (números, notícias, tabelas, passo a passo, vídeos, imagens, código,
conversa contínua…) e confere se cada resposta veio no formato esperado.

```bash
python testar.py                    # todos os testes (Windows: clique duas vezes em testar.bat)
python testar.py --sem-instrucao    # também testa sem a instrução de JSON
python testar.py --categorias video,imagem,tabela
python testar.py --limite 5         # teste rápido
python testar.py --arquivo minhas_perguntas.txt
python testar.py --conversas-separadas   # uma conversa por teste (padrão: tudo numa conversa só)
```

- **Se tudo der certo**, ele só avisa e não gera nada.
- **Se algo vier num formato inesperado**, ele cria `falhas_AAAAMMDD-HHMM/` com o HTML, o print e o JSON de cada
  teste que falhou, mais um `RELATORIO.txt` dizendo o que deu errado em cada um e quais arquivos são dele.
  No final gera **`falhas_AAAAMMDD-HHMM.zip`**: é só me mandar esse arquivo.
- Feche o `app.py` antes de rodar, porque os dois usam o mesmo perfil do navegador.
- Entre uma pergunta e outra ele espera alguns segundos (`--pausa`) para não irritar o Google. Se aparecer
  captcha, resolva na janela do navegador.

O que ele verifica: se a IA respondeu em JSON, se a objetiva e a completa vieram preenchidas, se sobrou lixo da
página, se as fontes têm links reais (não do Google), se vídeos, imagens, tabelas e código apareceram quando
pedidos, e se algum conteúdo visível na página ficou de fora do resultado.

## Ajudar a melhorar o extrator

Cada resposta salva o HTML da página em `debug/` e tem o botão **📄 HTML da página**.
Se alguma resposta sair errada, baixe esse HTML e mande junto com o que deveria ter saído.
O `TESTES.md` tem uma lista de perguntas que cobre vários tipos de resposta.

## Ajustes

- `PORTA=8000`: muda a porta
- O texto da instrução enviada ao Google fica em `INSTRUCAO` e os seletores da página em `SEL`, ambos no `ia_google.py`.
- Se o Google mudar o layout: rode `python ia_google.py`, faça uma pergunta, use `/debug` e ajuste os seletores pelo HTML salvo.
