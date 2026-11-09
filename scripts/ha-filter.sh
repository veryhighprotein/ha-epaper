#!/usr/bin/env bash
set -euo pipefail

: "${HA_URL:?Set HA_URL}"
: "${HA_TOKEN:?Set HA_TOKEN}"

case "${1:-}" in
  "") keep_unavailable=false ;;
  --include-unavailable) keep_unavailable=true ;;
  *) echo "Usage: $0 [--include-unavailable]" >&2; exit 2 ;;
esac

printf '%-50s %-50s %s\n' "ENTITY_ID" "NAME" "STATE"

curl --fail --silent --show-error \
  --header "Authorization: Bearer $HA_TOKEN" \
  "${HA_URL%/}/api/states" |
jq -r --arg keep "$keep_unavailable" '
  .[]
  | select(.entity_id | test("^(sensor|binary_sensor|weather|calendar|sun|light|switch)\\."))
  | select($keep == "true" or (.state != "unknown" and .state != "unavailable"))
  | [.entity_id, (.attributes.friendly_name // .entity_id), .state]
  | @tsv
' |
while IFS=$'\t' read -r entity_id name state; do
  printf '%-50s %-50s %s\n' "$entity_id" "$name" "$state"
done
