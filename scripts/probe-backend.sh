#!/usr/bin/env bash
#
# Зонд доступности бэкенда «Учёт трудозатрат».
#
# Зачем: сотрудники жалуются на 10–15 минут загрузки, но при входе администратора
# всё начинает работать. Нужно понять, деградирует ли сам бэкенд и совпадает ли
# это по времени с жалобами и с входом администратора.
#
# Что делает: раз в INTERVAL секунд дёргает /healthz (публичный, без авторизации)
# и пишет в CSV разложение времени ответа по фазам. Ключевая колонка — server_ms:
# время «раздумий» сервера уже ПОСЛЕ установки TLS-соединения. Если растёт она,
# а connect_ms и tls_ms стоят на месте — дело в приложении, а не в канале связи.
#
# Использование:
#   ./scripts/probe-backend.sh https://app.example.com
#   ./scripts/probe-backend.sh https://app.example.com 30 probe.csv
#
# Остановить: Ctrl+C. Файл дописывается, повторный запуск не затирает историю.

set -u

BASE_URL="${1:-}"
INTERVAL="${2:-60}"
OUT="${3:-backend-probe-$(date +%Y%m%d).csv}"

if [ -z "$BASE_URL" ]; then
  echo "Использование: $0 <https://домен-приложения> [интервал_сек] [файл.csv]" >&2
  exit 1
fi

URL="${BASE_URL%/}/healthz"

# curl отдаёт секунды с плавающей точкой; переводим в миллисекунды целыми.
FMT='%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}'

if [ ! -f "$OUT" ]; then
  echo "timestamp_local,http_code,dns_ms,connect_ms,tls_ms,server_ms,total_ms,note" > "$OUT"
fi

echo "Зонд запущен: $URL, интервал ${INTERVAL}с, файл $OUT"
echo "Оставьте окно открытым. Остановка — Ctrl+C."

while true; do
  TS="$(date '+%Y-%m-%d %H:%M:%S%z')"

  # --max-time 120: ответ дольше двух минут для healthz — это уже отказ,
  # незачем держать зонд в ожидании и пропускать следующие замеры.
  RAW="$(curl -sS -o /dev/null --max-time 120 -w "$FMT" "$URL" 2>/dev/null)"
  RC=$?

  if [ $RC -ne 0 ] || [ -z "$RAW" ]; then
    # Отдельная строка отказа: важнее любых таймингов — именно её мы будем
    # сопоставлять с жалобами сотрудников.
    echo "$TS,ERROR,,,,,,curl_exit_$RC" >> "$OUT"
    echo "$TS  ОТКАЗ (curl exit $RC)"
    sleep "$INTERVAL"
    continue
  fi

  read -r CODE T_DNS T_CONN T_TLS T_START T_TOTAL <<< "$RAW"

  ms() { awk -v v="$1" 'BEGIN { printf "%.0f", v * 1000 }'; }

  DNS_MS=$(ms "$T_DNS")
  # Фазы у curl кумулятивные — разворачиваем в длительности этапов.
  CONNECT_MS=$(awk -v a="$T_CONN" -v b="$T_DNS" 'BEGIN { printf "%.0f", (a - b) * 1000 }')
  TLS_MS=$(awk -v a="$T_TLS" -v b="$T_CONN" 'BEGIN { printf "%.0f", (a - b) * 1000 }')
  SERVER_MS=$(awk -v a="$T_START" -v b="$T_TLS" 'BEGIN { printf "%.0f", (a - b) * 1000 }')
  TOTAL_MS=$(ms "$T_TOTAL")

  NOTE=""
  if [ "$CODE" != "200" ]; then
    NOTE="http_$CODE"
  elif [ "$SERVER_MS" -gt 2000 ]; then
    NOTE="slow_server"
  fi

  echo "$TS,$CODE,$DNS_MS,$CONNECT_MS,$TLS_MS,$SERVER_MS,$TOTAL_MS,$NOTE" >> "$OUT"

  if [ -n "$NOTE" ]; then
    echo "$TS  code=$CODE server=${SERVER_MS}ms total=${TOTAL_MS}ms  <-- $NOTE"
  fi

  sleep "$INTERVAL"
done
