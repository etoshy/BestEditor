# 15 · Biblioteca do Estúdio, miniaturas e kit

## 🖼️ Biblioteca (as galerias do DarkPlanner)

No Estúdio:

- a aba **🖼️ Biblioteca** mostra **Filtros** (a mesma foto com cada filtro), **Animações** (entradas e saídas,
  mais os movimentos de câmera, com prévia em vídeo) e **Overlays** (as atmosferas);
- a aba **💬 Destaques** mostra os estilos de texto com a miniatura de verdade e a animação ao passar o mouse.

Como usar:

- **clique** aplica no trecho selecionado (**Shift+clique** = saída);
- **arraste** até a timeline;
- o **filtro** vale para o vídeo todo.

As miniaturas ficam em `assets/darkplanner/galeria/`:

| Pasta | Arquivo |
|---|---|
| `destaques/` | `<id>.jpg` (com o texto de exemplo — `amostra`) |
| `filtros/` | `<id>.jpg` |
| `animacoes/` | `entrada_<id>.mp4` + `.jpg`, `camera_<id>.mp4` + `.jpg` |
| `overlays/` | `<id>.mp4` + `.jpg` |

**Criou algo nos extras?** Rode `python dp_guia.py miniaturas`. Ele gera **só as que faltam**, em segundos.
**Mudou** um item que já tinha miniatura? Rode `python dp_guia.py miniaturas --refazer meu_id` (pode passar vários
ids). Para regerar todas (demora): `python dp_galeria.py` ou `python dp_galeria.py destaques`.

A prévia animada de um destaque (`/dp-galeria/previa/<id>.mp4`) é gerada na 1ª vez que você passa o mouse, e fica
guardada em `outputs/previas_destaques/`. O `--refazer` também apaga essa prévia.

## ✓ Kit

O botão **✓ Marcar kit** (Biblioteca, Destaques, Transições) liga o modo de marcar. O que você marca:

- vira a direção **★ Minha direção** ([14](14-direcoes.md));
- faz o "✨ Sugerir automaticamente" dos destaques usar **só** os estilos marcados.

## Biblioteca de mídia (os seus arquivos)

É outra coisa: no Estúdio (e no editor de segmentos) dá para **enviar arquivos a qualquer momento** e arrastar o
cartão para:

- um trecho (vira a mídia dele);
- a área de overlays (vira um overlay de imagem/vídeo);
- uma sugestão de corte.

Remover da biblioteca não desfaz o que já foi usado. Não precisa criar nada: é só usar.
