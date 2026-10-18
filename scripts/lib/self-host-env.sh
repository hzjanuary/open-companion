#!/usr/bin/env bash
# Source-only raw file support; shared by the doctor and explicit Compose wrapper.
# No values are evaluated, sourced, displayed or expanded.

self_host_error() {
  printf 'Self-host configuration blocked: %s\n' "$1" >&2
  return 1
}

self_host_read_config() {
  local repository="$1" requested="$2" permissions known line name value existing
  [[ -f "$requested" && ! -L "$requested" ]] || {
    self_host_error 'Copy the example to a regular private configuration file (no symlink).'
    return 1
  }
  self_host_config="$(cd "$(dirname "$requested")" && pwd)/$(basename "$requested")"
  [[ "$(wc -c < "$self_host_config")" -le 65536 ]] || {
    self_host_error 'Configuration exceeds the bounded file size.'
    return 1
  }
  if permissions="$(stat -c %a "$self_host_config" 2>/dev/null)"; then
    :
  elif permissions="$(stat -f %Lp "$self_host_config" 2>/dev/null)"; then
    :
  else
    self_host_error 'Cannot verify private-file permissions on this platform.'
    return 1
  fi
  [[ "$permissions" == 600 || "$permissions" == 400 ]] || {
    self_host_error 'Restrict configuration access: chmod 600 on the private file.'
    return 1
  }
  # Nonempty sentinels also avoid empty-array/nounset differences in older Bash.
  self_host_keys=(__empty__)
  self_host_values=('')
  known=$'\n'"$(awk -F= '/^JANUARY_[A-Z0-9_]+=/ {print $1}' "$repository/.env.example")"$'\n'
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -n "$line" && "$line" != \#* ]]; then
      [[ "$line" != *$'\r'* && "$line" =~ ^JANUARY_[A-Z0-9_]+= ]] || {
        self_host_error 'Use LF raw JANUARY_NAME=value assignments, not shell code.'
        return 1
      }
      name="${line%%=*}"
      value="${line#*=}"
      [[ ! "$value" =~ ^[[:space:]] && ! "$value" =~ [[:space:]]$ && "$value" != \"* && "$value" != \'* ]] || {
        self_host_error 'Raw values must be unquoted without surrounding whitespace.'
        return 1
      }
      case "$name" in
        JANUARY_HOST_PORT|JANUARY_BACKEND_IMAGE|JANUARY_SELF_HOST_ENV_FILE) ;;
        *) [[ "$known" == *$'\n'"$name"$'\n'* ]] || {
          self_host_error 'Unknown configuration name; use the Settings inventory.'
          return 1
        } ;;
      esac
      for existing in "${self_host_keys[@]}"; do
        [[ "$existing" != "$name" ]] || {
          self_host_error 'Duplicate configuration assignment.'
          return 1
        }
      done
      self_host_keys+=("$name")
      self_host_values+=("$value")
    fi
  done < "$self_host_config"
}

self_host_value() {
  local index
  for ((index=1; index<${#self_host_keys[@]}; index++)); do
    if [[ "${self_host_keys[$index]}" == "$1" ]]; then
      printf '%s' "${self_host_values[$index]}"
      return 0
    fi
  done
}

self_host_compose() (
  local inherited name index
  for inherited in $(compgen -e); do
    case "$inherited" in JANUARY_*) unset "$inherited" ;; esac
  done
  # Compose interpolates its .env input even when application env_file is raw.
  # Export only actual interpolation fields literally; all other application
  # values enter through the raw env_file. /dev/null avoids secondary expansion.
  for name in JANUARY_DATABASE_NAME JANUARY_DATABASE_USER JANUARY_DATABASE_PASSWORD \
    JANUARY_HOST_PORT JANUARY_BACKEND_IMAGE; do
    for ((index=1; index<${#self_host_keys[@]}; index++)); do
      if [[ "${self_host_keys[$index]}" == "$name" ]]; then
        export "$name=${self_host_values[$index]}"
      fi
    done
  done
  export JANUARY_SELF_HOST_ENV_FILE="$self_host_config"
  docker compose --env-file /dev/null -f "$root/compose.self-host.yaml" "$@"
)
