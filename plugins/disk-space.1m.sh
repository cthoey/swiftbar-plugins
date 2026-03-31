#!/bin/zsh

# <swiftbar.title>Disk Space</swiftbar.title>
# <swiftbar.version>v1.0.0</swiftbar.version>
# <swiftbar.desc>Disk space monitor for macOS local volumes.</swiftbar.desc>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LC_ALL="C"

usage_color() {
  local value="$1"

  if (( value >= 90 )); then
    printf '#d7263d'
  elif (( value >= 80 )); then
    printf '#ff7f11'
  elif (( value >= 70 )); then
    printf '#ffb703'
  else
    printf '#2a9d8f'
  fi
}

human_from_kib() {
  awk -v kib="$1" 'BEGIN {
    if (kib >= 1073741824) {
      printf "%.1fTB", kib / 1073741824
    } else if (kib >= 1048576) {
      printf "%.1fGB", kib / 1048576
    } else if (kib >= 1024) {
      printf "%.0fMB", kib / 1024
    } else {
      printf "%.0fKB", kib
    }
  }'
}

human_from_bytes() {
  awk -v bytes="$1" 'BEGIN {
    kib = bytes / 1024

    if (kib >= 1073741824) {
      printf "%.1fTB", kib / 1073741824
    } else if (kib >= 1048576) {
      printf "%.1fGB", kib / 1048576
    } else if (kib >= 1024) {
      printf "%.0fMB", kib / 1024
    } else if (bytes >= 1024) {
      printf "%.0fKB", kib
    } else {
      printf "%.0fB", bytes
    }
  }'
}

percent_used_from_bytes() {
  awk -v used="$1" -v total="$2" 'BEGIN {
    if (total <= 0) {
      printf "0"
    } else {
      printf "%.0f", (used * 100) / total
    }
  }'
}

label_for_mount() {
  local mount="$1"

  if [[ "$mount" == "/" ]]; then
    printf 'Root'
  elif [[ "$mount" == /Volumes/* ]]; then
    printf '%s' "${mount#/Volumes/}"
  else
    printf '%s' "$mount"
  fi
}

plist_extract() {
  local file="$1"
  local key="$2"

  plutil -extract "$key" raw -o - "$file" 2>/dev/null
}

internal_tmp="$(mktemp "${TMPDIR:-/tmp}/swiftbar-disk-space.XXXXXX")"

cleanup() {
  rm -f "$internal_tmp"
}

trap cleanup EXIT

internal_name=""
internal_total_bytes=""
internal_free_bytes=""
internal_used_bytes=""
internal_used_pct=""
internal_smart_status=""
internal_ssd_wear=""
internal_is_ssd=""

if diskutil info -plist /System/Volumes/Data >"$internal_tmp" 2>/dev/null; then
  internal_name="$(plist_extract "$internal_tmp" "VolumeName")"
  internal_total_bytes="$(plist_extract "$internal_tmp" "APFSContainerSize")"
  internal_free_bytes="$(plist_extract "$internal_tmp" "APFSContainerFree")"
  internal_smart_status="$(plist_extract "$internal_tmp" "SMARTStatus")"
  internal_ssd_wear="$(plist_extract "$internal_tmp" "SMARTDeviceSpecificKeysMayVaryNotGuaranteed.PERCENTAGE_USED")"
  internal_is_ssd="$(plist_extract "$internal_tmp" "SolidState")"

  if [[ -n "$internal_name" && "$internal_name" == *" - Data" ]]; then
    internal_name="${internal_name% - Data}"
  fi

  if [[ -n "$internal_total_bytes" && -n "$internal_free_bytes" ]]; then
    internal_used_bytes="$(( internal_total_bytes - internal_free_bytes ))"
    internal_used_pct="$(percent_used_from_bytes "$internal_used_bytes" "$internal_total_bytes")"
  fi
fi

df_rows="$(
  df -Pk -l 2>/dev/null | awk '
    NR > 1 {
      mount = $6
      for (i = 7; i <= NF; i++) {
        mount = mount " " $i
      }

      used_pct = $5
      gsub(/%/, "", used_pct)

      printf "%s\t%s\t%s\t%s\t%s\t%s\n", mount, $2, $3, $4, used_pct, $1
    }
  '
)"

external_rows=""
fallback_mount=""
fallback_total_kib=""
fallback_used_kib=""
fallback_avail_kib=""
fallback_used_pct=""
volume_count=0
alert_count=0
alerts_section=""

if [[ -n "$internal_total_bytes" && -n "$internal_free_bytes" && -n "$internal_used_pct" ]]; then
  volume_count=$(( volume_count + 1 ))

  if (( internal_used_pct >= 85 )); then
    alert_count=$(( alert_count + 1 ))
    alerts_section+="--${internal_name:-Internal SSD}: ${internal_used_pct}% used ($(human_from_bytes "$internal_free_bytes") free) | color=$(usage_color "$internal_used_pct")"$'\n'
  fi
fi

while IFS=$'\t' read -r mount total_kib used_kib avail_kib used_pct filesystem; do
  [[ -z "$mount" ]] && continue

  case "$mount" in
    /System/Volumes/Data)
      if [[ -z "$fallback_mount" ]]; then
        fallback_mount="$mount"
        fallback_total_kib="$total_kib"
        fallback_used_kib="$used_kib"
        fallback_avail_kib="$avail_kib"
        fallback_used_pct="$used_pct"
      fi
      continue
      ;;
    /)
      if [[ -z "$fallback_mount" ]]; then
        fallback_mount="$mount"
        fallback_total_kib="$total_kib"
        fallback_used_kib="$used_kib"
        fallback_avail_kib="$avail_kib"
        fallback_used_pct="$used_pct"
      fi
      continue
      ;;
    /Volumes/*)
      volume_count=$(( volume_count + 1 ))
      external_rows+="${mount}"$'\t'"${total_kib}"$'\t'"${used_kib}"$'\t'"${avail_kib}"$'\t'"${used_pct}"$'\t'"${filesystem}"$'\n'

      if (( used_pct >= 85 )); then
        alert_count=$(( alert_count + 1 ))
        alerts_section+="--$(label_for_mount "$mount"): ${used_pct}% used ($(human_from_kib "$avail_kib") free) | color=$(usage_color "$used_pct")"$'\n'
      fi
      ;;
  esac
done <<< "$df_rows"

if [[ -z "$internal_used_pct" && -n "$fallback_mount" ]]; then
  if [[ "$fallback_mount" == "/System/Volumes/Data" ]]; then
    internal_name="Internal SSD"
  else
    internal_name="$(label_for_mount "$fallback_mount")"
  fi
  internal_total_bytes="$(( fallback_total_kib * 1024 ))"
  internal_free_bytes="$(( fallback_avail_kib * 1024 ))"
  internal_used_bytes="$(( fallback_used_kib * 1024 ))"
  internal_used_pct="$fallback_used_pct"
  volume_count=$(( volume_count + 1 ))

  if (( internal_used_pct >= 85 )); then
    alert_count=$(( alert_count + 1 ))
    alerts_section+="--${internal_name}: ${internal_used_pct}% used ($(human_from_bytes "$internal_free_bytes") free) | color=$(usage_color "$internal_used_pct")"$'\n'
  fi
fi

if [[ -z "$internal_used_pct" && -z "$external_rows" ]]; then
  printf 'Disk --\n'
  printf -- '---\n'
  printf 'Disk metrics are unavailable.\n'
  printf 'Refresh Now | refresh=true\n'
  exit 0
fi

header_used_pct="${internal_used_pct:-0}"
header_color="$(usage_color "$header_used_pct")"

printf 'Disk %s%% | color=%s\n' "$header_used_pct" "$header_color"
printf -- '---\n'

if [[ -n "$internal_used_pct" ]]; then
  printf 'Internal: %s free / %s (%s%% used) | color=%s\n' \
    "$(human_from_bytes "$internal_free_bytes")" \
    "$(human_from_bytes "$internal_total_bytes")" \
    "$internal_used_pct" \
    "$header_color"
  printf 'Used: %s\n' "$(human_from_bytes "$internal_used_bytes")"

  if [[ -n "$internal_name" ]]; then
    if [[ "$internal_is_ssd" == "true" ]]; then
      printf 'Drive: %s (SSD)\n' "$internal_name"
    else
      printf 'Drive: %s\n' "$internal_name"
    fi
  fi

  if [[ -n "$internal_smart_status" ]]; then
    printf 'SMART: %s\n' "$internal_smart_status"
  fi

  if [[ -n "$internal_ssd_wear" ]]; then
    printf 'SSD Wear: %s%% lifetime used\n' "$internal_ssd_wear"
  fi
fi

printf 'Tracked Volumes: %s\n' "$volume_count"

if (( alert_count > 0 )); then
  printf 'Alerts: %s volume(s) above 85%% used | color=#d7263d\n' "$alert_count"
else
  printf 'Status: Healthy | color=#2a9d8f\n'
fi

printf -- '---\n'
printf 'Volumes\n'

if [[ -n "$internal_used_pct" ]]; then
  printf -- '--%s: %s free / %s (%s%% used) | color=%s\n' \
    "${internal_name:-Internal SSD}" \
    "$(human_from_bytes "$internal_free_bytes")" \
    "$(human_from_bytes "$internal_total_bytes")" \
    "$internal_used_pct" \
    "$(usage_color "$internal_used_pct")"
fi

if [[ -n "$external_rows" ]]; then
  while IFS=$'\t' read -r mount total_kib used_kib avail_kib used_pct filesystem; do
    [[ -z "$mount" ]] && continue

    printf -- '--%s (%s): %s free / %s (%s%% used) | color=%s\n' \
      "$(label_for_mount "$mount")" \
      "$mount" \
      "$(human_from_kib "$avail_kib")" \
      "$(human_from_kib "$total_kib")" \
      "$used_pct" \
      "$(usage_color "$used_pct")"
  done <<< "$external_rows"
else
  printf -- '--No external local volumes mounted\n'
fi

if (( alert_count > 0 )); then
  printf -- '---\n'
  printf 'Low Space Alerts\n'
  printf '%b' "$alerts_section"
fi

printf -- '---\n'
printf "Open Disk Utility | bash='open' param1='-a' param2='Disk Utility' terminal=false\n"
printf "Open /Volumes in Finder | bash='open' param1='/Volumes' terminal=false\n"
printf 'Refresh Now | refresh=true\n'
