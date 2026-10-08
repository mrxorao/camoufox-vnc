# 🦊 Camoufox VNC Docker & MCP Bridge (Anti-Detect & Stealth Automation)

Ambiente Docker autónomo e ultra-otimizado para executar o **Camoufox** (fork do Firefox com motor C++ stealth anti-deteção), com visualização Web em tempo real via **noVNC** (porta `5800`), **VNC direto** (porta `5900`) e controlo total por **Model Context Protocol (MCP)** para agentes de IA (AGY, OpenCode, Cursor, Claude Desktop, etc.).

---

## ✨ Características Principais

* 🛡️ **Anti-Deteção de Nível Máximo (Score 0–3):** `navigator.webdriver = false`, emulação realista de hardware (WebGL, Canvas, Áudio, GPU, fontes do Windows).
* 🌐 **Interface Web noVNC em Direto:** Vê em tempo real cada clique, pesquisa e scroll feito por ti ou pelo agente de IA ([http://localhost:5800](http://localhost:5800)).
* 🔌 **Bridge MCP Integrada:** Controla o browser com mais de 12 ferramentas (navegação, cliques, digitação, capturas de ecrã, gestão de abas, upload de ficheiros e execução JS).
* 📎 **Suporte a Upload & Download de Ficheiros:** Faz upload de ficheiros do teu PC diretamente para elementos `<input type='file'>` e guarda downloads na pasta `./data/downloads`.
* 🔄 **Auto-Update no Arranque:** A cada arranque do contentor, o Camoufox e os modelos C++ atualizam-se automaticamente para a versão mais recente do GitHub/PyPI.
* 💾 **Persistência de Sessões & Logins:** Volume Docker dedicado (`camoufox_profile`) que preserva cookies, logins, histórico e extensões mesmo ao reiniciar ou recriar a imagem.
* 🚀 **Pronto para VPS:** Pode ser executado em qualquer servidor remoto com visualização no browser e controlo via MCP remoto.

---

## 🚀 Como Executar Localmente

### 1. Iniciar o Contentor
```bash
docker compose up -d
```

### 2. Aceder à Interface Visual
* **Navegador Web (noVNC):** [http://localhost:5800](http://localhost:5800)
* **Cliente VNC Direto:** `localhost:5900`

### 3. Parar o Contentor
```bash
docker compose down
```

---

## ☁️ Como Fazer Deploy numa VPS (1 Ficheiro)

Numa VPS remota (Ubuntu, Debian, etc.), não precisas de clonar todo o repositório nem compilar nada! Basta usar a imagem pré-construída:

1. Cria uma pasta na VPS:
   ```bash
   mkdir -p ~/camoufox && cd ~/camoufox
   ```
2. Copia o ficheiro [`docker-compose.vps.example.yml`](file:///D:/Projetos/camoufox-vnc/docker-compose.vps.example.yml) para a VPS como `docker-compose.yml`.
3. Inicia o serviço:
   ```bash
   docker compose up -d
   ```
4. Acede no teu browser a `http://IP_DA_TUA_VPS:5800`.

---

## 🔌 Configuração MCP (AGY, OpenCode, Cursor, Claude Desktop)

Adiciona ao teu ficheiro de configuração MCP (`mcp_config.json` ou `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "node",
      "args": [
        "D:\\Projetos\\camoufox-vnc\\mcp_vnc_bridge.js"
      ],
      "env": {
        "CAMOUFOX_API_URL": "http://127.0.0.1:9377"
      }
    }
  }
}
```

> **Se o Docker estiver a correr numa VPS remota:**
> Substitui `http://127.0.0.1:9377` por `http://IP_DA_TUA_VPS:9377`.

---

## 🛠️ Ferramentas MCP Disponíveis

| Ferramenta | Descrição |
|---|---|
| `browse(url)` | Navega para um URL e extrai o resumo do conteúdo da página. |
| `browse_navigate(url)` | Navegação direta para um URL específico. |
| `browse_snapshot()` | Obtém o texto visível da página atual sem recarregar. |
| `browse_click(selector)` | Clica num botão, link ou elemento interativo via seletor CSS. |
| `browse_type(selector, text)` | Escreve texto em campos de formulário e inputs. |
| `browse_upload_file(selector, file_path)` | Faz upload de ficheiros do teu PC Windows para a página web. |
| `browse_press_key(key)` | Pressiona teclas do teclado (`Enter`, `Tab`, `Escape`, etc.). |
| `browse_scroll(direction, amount)` | Rola a página para baixo ou para cima. |
| `browse_screenshot()` | Captura uma imagem PNG em alta resolução do ecrã do browser. |
| `browse_new_tab(url)` | Abre uma nova aba no browser. |
| `browse_tabs()` | Lista todas as abas abertas. |
| `browse_switch_tab(index)` | Alterna entre abas abertas pelo seu índice. |
| `browse_evaluate(script)` | Executa código JavaScript diretamente no contexto da página. |

---

## ⚙️ Configurações de Ambiente (`.env`)

| Variável | Descrição | Valor Padrão |
|---|---|---|
| `PORT_WEB` | Porta da interface Web noVNC | `5800` |
| `PORT_VNC` | Porta para o cliente VNC direto | `5900` |
| `PORT_API` | Porta da API HTTP / MCP Bridge | `9377` |
| `RESOLUTION_WIDTH` | Largura da resolução do ecrã virtual | `1366` |
| `RESOLUTION_HEIGHT` | Altura da resolução do ecrã virtual | `768` |
| `TZ` | Fuso horário do sistema | `Europe/Lisbon` |
| `OS_SPOOF` | Sistema Operativo emulado (`windows`, `macos`, `linux`) | `windows` |
| `AUTO_UPDATE` | Atualização automática do Camoufox no arranque | `true` |
| `START_URL` | Página aberta ao iniciar | `https://duckduckgo.com` |
| `VNC_PASSWORD` | Palavra-passe de acesso ao VNC (opcional) | *(vazio)* |

---

## 📁 Estrutura do Projeto

```text
D:\Projetos\camoufox-vnc\
├── data/
│   └── downloads/                  # Ficheiros descarregados pelo browser
├── .env                            # Variáveis de ambiente ativas
├── .env.example                    # Exemplo de variáveis de ambiente
├── .gitignore                      # Regras de exclusão do Git
├── docker-compose.yml              # Compose para desenvolvimento local
├── docker-compose.vps.example.yml  # Compose pronto para deploy em VPS
├── Dockerfile                      # Imagem Docker com motor Camoufox
├── entrypoint.sh                   # Arranque e rotina de auto-update
├── launch-camoufox.py              # Motor Stealth C++ e API HTTP
├── launch-x11vnc.sh                # Servidor VNC
├── mcp_vnc_bridge.js               # Bridge MCP universal
├── openbox-rc.xml                  # Configuração do gestor de janelas
├── package.json                    # Dependências MCP SDK
├── README.md                       # Documentação completa
└── supervisord.conf                # Gestão de processos internos
```
