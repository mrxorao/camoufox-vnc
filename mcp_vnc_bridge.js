#!/usr/bin/env node
/**
 * Camoufox Docker VNC MCP Bridge
 * Liga o AGY diretamente à sessão em direto do Camoufox no Docker (noVNC: http://localhost:5800).
 * Comunica através da API Stealth interna em http://127.0.0.1:9377
 */

import fs from "fs";
import path from "path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const CAMOUFOX_API_URL = process.env.CAMOUFOX_API_URL || "http://127.0.0.1:9377";

async function sendCmd(endpoint, data = null, method = "POST") {
  const url = `${CAMOUFOX_API_URL.replace(/\/$/, "")}${endpoint}`;
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (data !== null) {
    options.body = JSON.stringify(data);
  }

  try {
    const res = await fetch(url, options);
    const json = await res.json();
    return json;
  } catch (err) {
    return { error: `Erro ao comunicar com o contentor Camoufox (${CAMOUFOX_API_URL}): ${err.message}` };
  }
}

const server = new Server(
  {
    name: "camoufox",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "browse",
        description: "Navega para um URL no browser do Docker VNC. Visível em tempo real no noVNC (http://localhost:5800).",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL de destino (ex: 'https://pplware.sapo.pt')" },
          },
          required: ["url"],
        },
      },
      {
        name: "browse_navigate",
        description: "Navega para um URL específico dentro do browser no VNC.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL para onde navegar" },
          },
          required: ["url"],
        },
      },
      {
        name: "browse_snapshot",
        description: "Obtém o título, URL e texto legível da página atualmente aberta no Docker noVNC.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_click",
        description: "Clica num botão, link ou elemento interativo na página do browser (selector CSS).",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "Selector CSS do elemento a clicar" },
          },
          required: ["selector"],
        },
      },
      {
        name: "browse_type",
        description: "Escreve texto num campo de input ou pesquisa visível no browser do noVNC.",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "Selector CSS do campo" },
            text: { type: "string", description: "Texto a escrever" },
            clear_first: { type: "boolean", description: "Limpar campo antes de escrever" },
          },
          required: ["selector", "text"],
        },
      },
      {
        name: "browse_upload_file",
        description: "Faz upload de um ficheiro do teu computador Windows diretamente para um elemento de upload (<input type='file'>) no browser.",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "Selector CSS do elemento <input type='file'> (ex: 'input[type=file]')" },
            file_path: { type: "string", description: "Caminho absoluto do ficheiro no computador (ex: 'C:\\Users\\hugor\\ficheiro.pdf')" },
          },
          required: ["selector", "file_path"],
        },
      },
      {
        name: "browse_press_key",
        description: "Pressiona uma tecla no teclado do browser (ex: 'Enter', 'Tab', 'Escape').",
        inputSchema: {
          type: "object",
          properties: {
            key: { type: "string", description: "Nome da tecla (ex: 'Enter', 'Tab')" },
          },
          required: ["key"],
        },
      },
      {
        name: "browse_scroll",
        description: "Faz scroll na janela do browser para baixo ou para cima.",
        inputSchema: {
          type: "object",
          properties: {
            direction: { type: "string", enum: ["down", "up"], description: "Direção do scroll (padrão: 'down')" },
            amount: { type: "number", description: "Quantidade de pixels a rolar (padrão 500)" },
          },
        },
      },
      {
        name: "browse_screenshot",
        description: "Captura uma imagem (screenshot) da janela do browser aberta no Docker.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_evaluate",
        description: "Executa código JavaScript no contexto da página do browser.",
        inputSchema: {
          type: "object",
          properties: {
            script: { type: "string", description: "Código JavaScript a executar" },
          },
          required: ["script"],
        },
      },
      {
        name: "browse_new_tab",
        description: "Abre uma nova aba no browser do Docker VNC.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL da nova aba (ex: 'https://google.com')" },
          },
        },
      },
      {
        name: "browse_tabs",
        description: "Lista todas as abas abertas no browser do Docker VNC.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_switch_tab",
        description: "Muda a aba ativa pelo seu índice (0, 1, 2...).",
        inputSchema: {
          type: "object",
          properties: {
            index: { type: "number", description: "Índice numérico da aba" },
          },
          required: ["index"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    if (name === "browse" || name === "browse_navigate") {
      let targetUrl = args?.url || "";
      const res = await sendCmd("/navigate", { url: targetUrl });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao navegar: ${res.error}` }] };
      }
      
      const snap = await sendCmd("/snapshot");
      const pageText = snap.text || "";

      return {
        content: [
          {
            type: "text",
            text: `🌐 [Docker noVNC] Navegado com sucesso para: ${res.url}\nTítulo: ${res.title}\n\nResumo do Conteúdo:\n${pageText.slice(0, 4000)}`,
          },
        ],
      };
    }

    if (name === "browse_snapshot") {
      const res = await sendCmd("/snapshot");
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao obter snapshot: ${res.error}` }] };
      }
      return {
        content: [
          {
            type: "text",
            text: `URL Atual: ${res.url}\nTítulo: ${res.title}\n\nConteúdo Visível:\n${res.text}`,
          },
        ],
      };
    }

    if (name === "browse_click") {
      const res = await sendCmd("/click", { selector: args.selector });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao clicar: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `🖱️ Clicado com sucesso em '${args.selector}'. Página atual: ${res.url} (${res.title})` }],
      };
    }

    if (name === "browse_type") {
      const res = await sendCmd("/type", {
        selector: args.selector,
        text: args.text,
        clear: args.clear_first !== false,
      });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao escrever: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `⌨️ Texto escrito com sucesso no elemento '${args.selector}'.` }],
      };
    }

    if (name === "browse_upload_file") {
      const filePath = args.file_path;
      if (!fs.existsSync(filePath)) {
        return { isError: true, content: [{ type: "text", text: `Ficheiro não encontrado no sistema: ${filePath}` }] };
      }

      const fileBuffer = fs.readFileSync(filePath);
      const base64Data = fileBuffer.toString("base64");
      const filename = path.basename(filePath);

      const res = await sendCmd("/upload", {
        selector: args.selector,
        base64_data: base64Data,
        filename: filename,
      });

      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao fazer upload do ficheiro: ${res.error}` }] };
      }

      return {
        content: [{ type: "text", text: `📎 Ficheiro '${filename}' (${(fileBuffer.length / 1024).toFixed(1)} KB) carregado com sucesso para '${args.selector}'.` }],
      };
    }

    if (name === "browse_press_key") {
      const res = await sendCmd("/press_key", { key: args.key });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao pressionar tecla: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `⌨️ Tecla '${args.key}' pressionada com sucesso.` }],
      };
    }

    if (name === "browse_scroll") {
      const deltaY = args?.direction === "up" ? -(args?.amount || 500) : (args?.amount || 500);
      const res = await sendCmd("/scroll", { delta_y: deltaY });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao rolar: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `📜 Scroll efetuado (${args?.direction || "down"}, ${args?.amount || 500}px).` }],
      };
    }

    if (name === "browse_screenshot") {
      const res = await sendCmd("/screenshot");
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao capturar screenshot: ${res.error}` }] };
      }
      return {
        content: [
          {
            type: "image",
            data: res.image_base64,
            mimeType: "image/png",
          },
        ],
      };
    }

    if (name === "browse_evaluate") {
      const res = await sendCmd("/evaluate", { script: args.script });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao executar script: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `Resultado JS: ${JSON.stringify(res.result)}` }],
      };
    }

    if (name === "browse_new_tab") {
      const res = await sendCmd("/new_tab", { url: args?.url || "https://google.com" });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao abrir aba: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `📄 Nova aba aberta (Índice ${res.tab_index}): ${res.url}` }],
      };
    }

    if (name === "browse_tabs") {
      const res = await sendCmd("/tabs");
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao listar abas: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: JSON.stringify(res.tabs, null, 2) }],
      };
    }

    if (name === "browse_switch_tab") {
      const res = await sendCmd("/switch_tab", { index: args.index });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Erro ao alternar aba: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `Aba ativa alterada para o índice ${args.index}: ${res.url} (${res.title})` }],
      };
    }

    throw new Error(`Ferramenta desconhecida: ${name}`);
  } catch (err) {
    return {
      isError: true,
      content: [{ type: "text", text: `Erro ao processar ${name}: ${err.message}` }],
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
