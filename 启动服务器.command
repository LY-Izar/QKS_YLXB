#!/bin/bash
# 医路相伴 · 一键启动本地服务器
cd "$(dirname "$0")"
PORT=8080

# 获取本机局域网 IP
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

echo ""
echo "=============================================="
echo "    医路相伴 · 本地服务器已启动"
echo "=============================================="
echo ""
echo "  【本机浏览器打开】(定位可用)"
echo "    http://localhost:$PORT/index.html"
echo ""
if [ -n "$IP" ]; then
  echo "  【手机打开】(需与本机连同一 WiFi / 热点)"
  echo "    http://$IP:$PORT/index.html"
  echo ""
fi
echo "  提示：手机端因非 HTTPS，定位可能被浏览器拦截，"
echo "        可在地图上手动点选位置。"
echo ""
echo "  按 Ctrl+C 停止服务器"
echo "=============================================="
echo ""

# 启动 HTTP 服务器，绑定所有网卡（0.0.0.0），供局域网设备访问
python3 -m http.server $PORT --bind 0.0.0.0