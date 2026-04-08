#!/bin/zsh

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LC_ALL="C"

usage_color() {
  local value="$1"

  if (( value >= 90 )); then
    printf '#d7263d'
  elif (( value >= 75 )); then
    printf '#ff7f11'
  elif (( value >= 50 )); then
    printf '#ffb703'
  else
    printf '#2a9d8f'
  fi
}

human_from_mib() {
  awk -v mib="$1" 'BEGIN {
    if (mib >= 1048576) {
      printf "%.1fTB", mib / 1048576
    } else if (mib >= 1024) {
      printf "%.1fGB", mib / 1024
    } else {
      printf "%.0fMB", mib
    }
  }'
}

print_top_cpu() {
  local rows

  rows="$(
    ps -Aceo pid=,%cpu=,rss=,comm=,args= 2>/dev/null \
      | sort -nrk2 \
      | head -n 5 \
      | awk '
          function human_kib(kib) {
            if (kib >= 1048576) {
              return sprintf("%.1fGB", kib / 1048576)
            } else if (kib >= 1024) {
              return sprintf("%.0fMB", kib / 1024)
            }

            return sprintf("%dKB", kib)
          }

          function pretty_name(comm, args,    parts, count, project, display, wait_pid) {
            if (args ~ /codex_supervisor\.py/) {
              count = split(args, parts, " ")
              project = parts[count]
              if (project != "") {
                return sprintf("codex-supervisor[%s]", project)
              }
              return "codex-supervisor"
            }

            if (args ~ /^codex exec /) {
              project = args
              if (sub(/^.*-C /, "", project)) {
                sub(/ .*/, "", project)
                sub(/^.*\//, "", project)
                if (project != "") {
                  return sprintf("codex-worker[%s]", project)
                }
              }
              return "codex-worker"
            }

            if (args ~ /^caffeinate /) {
              wait_pid = args
              if (sub(/^.*-w /, "", wait_pid)) {
                sub(/ .*/, "", wait_pid)
                if (wait_pid != "") {
                  return sprintf("caffeinate[pid %s]", wait_pid)
                }
              }
            }

            display = comm
            sub(/^.*\//, "", display)
            return display
          }

          {
            pid = $1
            cpu = $2
            rss = $3
            comm = $4
            $1 = ""
            $2 = ""
            $3 = ""
            $4 = ""
            sub(/^ +/, "", $0)
            printf "%s %.1f%% (%s, pid %s)\n", pretty_name(comm, $0), cpu, human_kib(rss), pid
          }
        '
  )"

  if [[ -n "$rows" ]]; then
    printf '%s\n' "$rows"
  else
    printf 'Process list unavailable\n'
  fi
}

print_top_memory() {
  local rows

  rows="$(
    ps -Aceo pid=,rss=,%mem=,comm=,args= 2>/dev/null \
      | sort -nrk2 \
      | head -n 5 \
      | awk '
          function human_kib(kib) {
            if (kib >= 1048576) {
              return sprintf("%.1fGB", kib / 1048576)
            } else if (kib >= 1024) {
              return sprintf("%.0fMB", kib / 1024)
            }

            return sprintf("%dKB", kib)
          }

          function pretty_name(comm, args,    parts, count, project, display, wait_pid) {
            if (args ~ /codex_supervisor\.py/) {
              count = split(args, parts, " ")
              project = parts[count]
              if (project != "") {
                return sprintf("codex-supervisor[%s]", project)
              }
              return "codex-supervisor"
            }

            if (args ~ /^codex exec /) {
              project = args
              if (sub(/^.*-C /, "", project)) {
                sub(/ .*/, "", project)
                sub(/^.*\//, "", project)
                if (project != "") {
                  return sprintf("codex-worker[%s]", project)
                }
              }
              return "codex-worker"
            }

            if (args ~ /^caffeinate /) {
              wait_pid = args
              if (sub(/^.*-w /, "", wait_pid)) {
                sub(/ .*/, "", wait_pid)
                if (wait_pid != "") {
                  return sprintf("caffeinate[pid %s]", wait_pid)
                }
              }
            }

            display = comm
            sub(/^.*\//, "", display)
            return display
          }

          {
            pid = $1
            rss = $2
            pmem = $3
            comm = $4
            $1 = ""
            $2 = ""
            $3 = ""
            $4 = ""
            sub(/^ +/, "", $0)
            printf "%s %s (%s%%, pid %s)\n", pretty_name(comm, $0), human_kib(rss), pmem, pid
          }
        '
  )"

  if [[ -n "$rows" ]]; then
    printf '%s\n' "$rows"
  else
    printf 'Process list unavailable\n'
  fi
}

top_output="$(top -l 1 -n 0 2>/dev/null)"
vm_stat_output="$(vm_stat 2>/dev/null)"
memsize_bytes="$(sysctl -n hw.memsize 2>/dev/null)"

if [[ -z "$memsize_bytes" ]]; then
  memsize_bytes="$(
    memory_pressure 2>/dev/null | awk '
      /^The system has / {
        gsub(/[^0-9]/, "", $4)
        print $4
        exit
      }
    '
  )"
fi

if [[ -z "$top_output" ]]; then
  printf 'CPU -- MEM --\n'
  printf -- '---\n'
  printf 'Live system metrics are unavailable.\n'
  printf 'Refresh | refresh=true\n'
  exit 0
fi

cpu_metrics="$(
  printf '%s\n' "$top_output" | awk '
    /^CPU usage:/ {
      line = $0
      sub(/^CPU usage: /, "", line)
      gsub(/%/, "", line)
      gsub(/, /, "\t", line)
      split(line, fields, "\t")
      split(fields[1], user_parts, " ")
      split(fields[2], sys_parts, " ")
      split(fields[3], idle_parts, " ")
      used = user_parts[1] + sys_parts[1]
      printf "%.0f\t%.1f\t%.1f\t%.1f\n", used, user_parts[1], sys_parts[1], idle_parts[1]
      exit
    }
  '
)"

# `top` counts cached file pages as "used", which does not line up with
# Activity Monitor's Memory Used. Derive usage from `vm_stat` instead.
if [[ -n "$vm_stat_output" && -n "$memsize_bytes" ]]; then
  mem_metrics="$(
    printf '%s\n' "$vm_stat_output" | awk -v memsize_bytes="$memsize_bytes" '
      BEGIN {
        page_size = 4096
      }

      /page size of/ {
        line = $0
        sub(/^.*page size of /, "", line)
        sub(/ bytes.*$/, "", line)
        page_size = line + 0
      }

      /^Pages free:/ {
        gsub(/\./, "", $3)
        free_pages = $3
      }

      /^Pages purgeable:/ {
        gsub(/\./, "", $3)
        purgeable_pages = $3
      }

      /^File-backed pages:/ {
        gsub(/\./, "", $3)
        file_backed_pages = $3
      }

      END {
        total_mib = memsize_bytes / 1048576
        free_mib = free_pages * page_size / 1048576
        cached_mib = (file_backed_pages + purgeable_pages) * page_size / 1048576
        used_mib = total_mib - free_mib - cached_mib

        if (used_mib < 0) {
          used_mib = 0
        }

        used_pct = total_mib > 0 ? (used_mib * 100 / total_mib) : 0
        printf "%.0f\t%.2f\t%.2f\t%.2f\t%.2f\n", used_pct, used_mib, free_mib, cached_mib, total_mib
      }
    '
  )"
else
  mem_metrics="$(
    printf '%s\n' "$top_output" | awk '
      function to_mib(token, value, unit) {
        value = token
        unit = substr(token, length(token), 1)
        sub(/[KMGTP]$/, "", value)
        value += 0

        if (unit == "K") {
          return value / 1024
        } else if (unit == "M") {
          return value
        } else if (unit == "G") {
          return value * 1024
        } else if (unit == "T") {
          return value * 1024 * 1024
        } else if (unit == "P") {
          return value * 1024 * 1024 * 1024
        }

        return value
      }

      /^PhysMem:/ {
        line = $0
        sub(/^PhysMem: /, "", line)
        split(line, fields, ", ")
        split(fields[1], used_parts, " ")
        split(fields[length(fields)], free_parts, " ")
        used_mib = to_mib(used_parts[1])
        free_mib = to_mib(free_parts[1])
        total_mib = used_mib + free_mib
        used_pct = total_mib > 0 ? (used_mib * 100 / total_mib) : 0
        printf "%.0f\t%.2f\t%.2f\t0\t%.2f\n", used_pct, used_mib, free_mib, total_mib
        exit
      }
    '
  )"
fi

load_avg="$(uptime | awk -F'load averages: ' 'NF > 1 {print $2}')"

IFS=$'\t' read -r cpu_used cpu_user cpu_sys cpu_idle <<< "$cpu_metrics"
IFS=$'\t' read -r mem_used_pct mem_used_mib mem_free_mib mem_cached_mib mem_total_mib <<< "$mem_metrics"

if [[ -z "$cpu_used" || -z "$mem_used_pct" ]]; then
  printf 'CPU -- MEM --\n'
  printf -- '---\n'
  printf 'Unable to parse current system metrics.\n'
  printf 'Refresh | refresh=true\n'
  exit 0
fi

header_color="$(usage_color $(( cpu_used > mem_used_pct ? cpu_used : mem_used_pct )))"
cpu_color="$(usage_color ${cpu_used%.*})"
mem_color="$(usage_color ${mem_used_pct%.*})"

printf ':cpu: %s%%   :memorychip: %s%% | color=%s sfcolor=%s sfcolor2=%s\n' \
  "$cpu_used" \
  "$mem_used_pct" \
  "$header_color" \
  "$cpu_color" \
  "$mem_color"
printf -- '---\n'
printf 'CPU: %s%% used (%s%% user, %s%% sys, %s%% idle) | color=%s\n' "$cpu_used" "$cpu_user" "$cpu_sys" "$cpu_idle" "$cpu_color"
printf 'Load Avg: %s\n' "$load_avg"
printf 'Memory: %s / %s (%s%%) | color=%s\n' "$(human_from_mib "$mem_used_mib")" "$(human_from_mib "$mem_total_mib")" "$mem_used_pct" "$mem_color"
if [[ "$mem_cached_mib" != "0" && "$mem_cached_mib" != "0.00" ]]; then
  printf 'Cached Files: %s\n' "$(human_from_mib "$mem_cached_mib")"
fi
printf 'Free: %s\n' "$(human_from_mib "$mem_free_mib")"
printf -- '---\n'
printf 'Top CPU\n'
print_top_cpu
printf -- '---\n'
printf 'Top Memory\n'
print_top_memory
printf -- '---\n'
printf "Open Activity Monitor | bash='open' param1='-a' param2='Activity Monitor' terminal=false\n"
printf 'Refresh Now | refresh=true\n'
