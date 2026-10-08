#!/usr/bin/env bash
set -e

# Garantir diretórios necessários para perfil e downloads
mkdir -p /data/downloads /var/log/supervisor /tmp/.X11-unix /root/profile
rm -rf /root/Downloads
ln -sf /data/downloads /root/Downloads

# Limpar locks antigos do X11 e do perfil do Firefox/Camoufox
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
rm -f /root/profile/.parentlock /root/profile/lock /root/profile/.startup-incomplete

# Auto-Update no arranque: se AUTO_UPDATE=true, atualiza o Camoufox e os binários C++
if [ "${AUTO_UPDATE:-true}" = "true" ]; then
    echo "============================================================"
    echo "  🔄 [Auto-Update] A verificar versão mais recente do Camoufox..."
    (
        /opt/venv/bin/pip install --upgrade --no-cache-dir "camoufox[geoip]" && \
        /opt/venv/bin/python3 -m camoufox fetch
    ) || echo "  ⚠️ [Auto-Update] Aviso: Sem ligação à internet para atualizar, a iniciar com a versão existente."
    echo "  ✅ [Auto-Update] Camoufox atualizado!"
    echo "============================================================"
fi

# Configurar motor de pesquisa padrão (DuckDuckGo) no policies.json de todas as versões do Camoufox
python3 -c '
import glob, json
for p in glob.glob("/root/.cache/camoufox/browsers/**/distribution/policies.json", recursive=True):
    try:
        with open(p, "r") as f: d = json.load(f)
        d.setdefault("policies", {})["SearchEngines"] = {
            "PreventInstalls": False,
            "Default": "DuckDuckGo",
            "Add": [{
                "Name": "DuckDuckGo",
                "Description": "DuckDuckGo Search",
                "Alias": "@ddg",
                "Method": "GET",
                "URLTemplate": "https://duckduckgo.com/?q={searchTerms}"
            }]
        }
        with open(p, "w") as f: json.dump(d, f, indent=2)
    except Exception: pass
'

echo "============================================================"
echo "  🚀 Camoufox VNC Stealth Browser Server"
echo "  🌐 Interface Web noVNC: http://localhost:${PORT_WEB:-5800}"
echo "  🖥️  Acesso VNC direto: localhost:${PORT_VNC:-5900}"
echo "  🔌 API de Controlo MCP: http://localhost:${PORT_API:-9377}"
echo "  ⚙️  Resolução: ${RESOLUTION_WIDTH:-1366}x${RESOLUTION_HEIGHT:-768}"
echo "  🛡️  Emulação Stealth SO: ${OS_SPOOF:-windows}"
echo "============================================================"

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
