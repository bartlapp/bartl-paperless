{{/* Validate only the dynamically selected interface, using the shipped JSON schema. */}}
{{- define "paperless.validate" -}}
{{- $schema := .schema -}}
{{- if hasKey $schema "$ref" -}}
  {{- $schema = index .definitions (trimPrefix "#/definitions/" (index $schema "$ref")) -}}
{{- end -}}
{{- $value := .value -}}
{{- $path := .path -}}
{{- $type := $schema.type -}}
{{- $valid := false -}}
{{- if eq $type "object" -}}
  {{- $valid = kindIs "map" $value -}}
{{- else if eq $type "array" -}}
  {{- $valid = kindIs "slice" $value -}}
{{- else if eq $type "string" -}}
  {{- $valid = kindIs "string" $value -}}
{{- else if eq $type "boolean" -}}
  {{- $valid = kindIs "bool" $value -}}
{{- else if eq $type "integer" -}}
  {{- if or (kindIs "float64" $value) (kindIs "int" $value) (kindIs "int64" $value) -}}
    {{- $valid = eq (float64 $value) (floor (float64 $value)) -}}
  {{- end -}}
{{- end -}}
{{- if not $valid -}}{{- fail (printf "%s must be %s" $path $type) -}}{{- end -}}
{{- if and (hasKey $schema "enum") (not (has $value $schema.enum)) -}}{{- fail (printf "%s has an unsupported value" $path) -}}{{- end -}}
{{- if eq $type "object" -}}
  {{- range $schema.required -}}
    {{- if not (hasKey $value .) -}}{{- fail (printf "%s.%s is required" $path .) -}}{{- end -}}
  {{- end -}}
  {{- if and (hasKey $schema "minProperties") (lt (len $value) (int $schema.minProperties)) -}}{{- fail (printf "%s has too few entries" $path) -}}{{- end -}}
  {{- if and (hasKey $schema "maxProperties") (gt (len $value) (int $schema.maxProperties)) -}}{{- fail (printf "%s has too many entries" $path) -}}{{- end -}}
  {{- $properties := $schema.properties | default dict -}}
  {{- range $key, $item := $value -}}
    {{- $child := dict -}}
    {{- if hasKey $properties $key -}}
      {{- $child = index $properties $key -}}
    {{- else if kindIs "map" $schema.additionalProperties -}}
      {{- $child = $schema.additionalProperties -}}
    {{- else if and (hasKey $schema "additionalProperties") (eq (toString $schema.additionalProperties) "false") -}}
      {{- fail (printf "%s.%s is unknown" $path $key) -}}
    {{- end -}}
    {{- if $child -}}
      {{- include "paperless.validate" (dict "schema" $child "definitions" $.definitions "value" $item "path" (printf "%s.%s" $path $key)) -}}
    {{- end -}}
  {{- end -}}
{{- else if eq $type "array" -}}
  {{- if and (hasKey $schema "maxItems") (gt (len $value) (int $schema.maxItems)) -}}{{- fail (printf "%s has too many entries" $path) -}}{{- end -}}
  {{- if and $schema.uniqueItems (ne (len $value) (len (uniq $value))) -}}{{- fail (printf "%s must contain unique entries" $path) -}}{{- end -}}
  {{- range $index, $item := $value -}}
    {{- include "paperless.validate" (dict "schema" $schema.items "definitions" $.definitions "value" $item "path" (printf "%s[%d]" $path $index)) -}}
  {{- end -}}
{{- else if eq $type "string" -}}
  {{- if and (hasKey $schema "minLength") (lt (len $value) (int $schema.minLength)) -}}{{- fail (printf "%s is too short" $path) -}}{{- end -}}
  {{- if and (hasKey $schema "maxLength") (gt (len $value) (int $schema.maxLength)) -}}{{- fail (printf "%s is too long" $path) -}}{{- end -}}
  {{- if and $schema.pattern (not (regexMatch $schema.pattern $value)) -}}{{- fail (printf "%s has an unsupported format" $path) -}}{{- end -}}
{{- else if eq $type "integer" -}}
  {{- if and (hasKey $schema "minimum") (lt (float64 $value) (float64 $schema.minimum)) -}}{{- fail (printf "%s is below its minimum" $path) -}}{{- end -}}
  {{- if and (hasKey $schema "maximum") (gt (float64 $value) (float64 $schema.maximum)) -}}{{- fail (printf "%s exceeds its maximum" $path) -}}{{- end -}}
{{- end -}}
{{- end -}}

{{- define "paperless.defaults" -}}
{{- .Files.Get "defaults.yaml" -}}
{{- end -}}

{{- define "paperless.service" -}}
{{- $selected := get .Values.services .Values.instance | default dict -}}
{{- if hasKey .Values.services .Values.instance -}}{{- $selected = index .Values.services .Values.instance -}}{{- end -}}
{{- $definitions := (mustFromJson (.Files.Get "interface.schema.json")).definitions -}}
{{- include "paperless.validate" (dict "schema" $definitions.service "definitions" $definitions "value" $selected "path" (printf "services.%s" .Values.instance)) -}}
{{- if and (hasKey $selected "release") (ne $selected.release .Chart.Version) -}}{{- fail (printf "services.%s.release selects %s but this chart is %s" .Values.instance $selected.release .Chart.Version) -}}{{- end -}}
{{- $service := mergeOverwrite (include "paperless.defaults" . | fromYaml) (deepCopy $selected) -}}
{{- if not (hasKey $service "hostname") -}}
  {{- $domain := required "dns.root is required when the selected Paperless service has no hostname" (get (get .Values "dns" | default dict) "root") -}}
  {{- $_ := set $service "hostname" (printf "paperless.%s" $domain) -}}
{{- end -}}
{{- if not (hasKey $service.oidc "clientId") -}}{{- $_ := set $service.oidc "clientId" .Values.instance -}}{{- end -}}
{{- include "paperless.validate" (dict "schema" $definitions.service "definitions" $definitions "value" $service "path" (printf "services.%s" .Values.instance)) -}}
{{- if and (hasKey $service.backup "endpoint") (hasKey $service.backup "repository") -}}{{- fail "Paperless backup must select endpoint or repository, not both" -}}{{- end -}}
{{- if and (or $service.ingress.enabled $service.tls.managed) (not $service.ingress.tlsSecret) -}}{{- fail "Paperless ingress.tlsSecret is required for ingress or managed TLS" -}}{{- end -}}
{{- if ne (len (uniq (values $service.claims))) 4 -}}{{- fail "Paperless claims must identify four distinct PVCs" -}}{{- end -}}
{{- if and (hasKey $selected "oidc") (not (hasKey $service "identityProvider")) (not (hasKey $service.oidc "issuer")) -}}{{- fail "Standalone Paperless oidc requires issuer" -}}{{- end -}}
{{- if and (hasKey $service "identityProvider") (hasKey $service.oidc "issuer") -}}{{- fail "Select identityProvider with a resolved binding or standalone oidc.issuer, not both" -}}{{- end -}}
{{- toYaml $service -}}
{{- end -}}

{{/* Validate only the selected OIDC binding; never read protected client material. */}}
{{- define "paperless.oidc" -}}
{{- $service := .service -}}
{{- $root := .root -}}
{{- $oidc := deepCopy $service.oidc -}}
{{- if hasKey $service "identityProvider" -}}
  {{- $resolved := get $root.Values "resolved" | default dict -}}
  {{- if not (kindIs "map" $resolved) -}}{{- fail "resolved must be an object" -}}{{- end -}}
  {{- $oidcResolved := get $resolved "oidc" | default dict -}}
  {{- if not (kindIs "map" $oidcResolved) -}}{{- fail "resolved.oidc must be an object" -}}{{- end -}}
  {{- $bindings := get $oidcResolved "bindings" | default dict -}}
  {{- if not (kindIs "map" $bindings) -}}{{- fail "resolved.oidc.bindings must be an object" -}}{{- end -}}
  {{- if not (hasKey $bindings $root.Values.instance) -}}{{- fail (printf "services.%s.identityProvider requires resolved.oidc.bindings.%s from the selected provider" $root.Values.instance $root.Values.instance) -}}{{- end -}}
  {{- $binding := index $bindings $root.Values.instance -}}
  {{- $definitions := (mustFromJson ($root.Files.Get "interface.schema.json")).definitions -}}
  {{- include "paperless.validate" (dict "schema" $definitions.oidcBinding "definitions" $definitions "value" $binding "path" (printf "resolved.oidc.bindings.%s" $root.Values.instance)) -}}
  {{- if ne $binding.provider $service.identityProvider -}}{{- fail "Paperless OIDC binding provider must match identityProvider" -}}{{- end -}}
  {{- $bindingClient := $root.Values.instance -}}
  {{- if hasKey $binding "clientId" -}}{{- $bindingClient = $binding.clientId -}}{{- end -}}
  {{- if ne $bindingClient $oidc.clientId -}}{{- fail "Paperless OIDC binding clientId must match the selected clientId" -}}{{- end -}}
  {{- $_ := set $oidc "issuer" $binding.issuer -}}
{{- end -}}
{{- $_ := set $oidc "enabled" (hasKey $oidc "issuer") -}}
{{- toYaml $oidc -}}
{{- end -}}

{{/* Resolve deployment-only backup inputs; declarations never read resolved data. */}}
{{- define "paperless.backup" -}}
{{- $root := .root -}}
{{- $service := .service -}}
{{- $desired := $service.backup -}}
{{- $explicit := (index $root.Values.services $root.Values.instance | default dict).backup | default dict -}}
{{- if and (hasKey $desired "enabled") (not $desired.enabled) -}}
  {{- toYaml (dict "enabled" false) -}}
{{- else -}}
  {{- $binding := dict -}}
  {{- if hasKey $root.Values "resolved" -}}
    {{- $resolved := $root.Values.resolved -}}
    {{- if not (kindIs "map" $resolved) -}}{{- fail "resolved must be an object" -}}{{- end -}}
    {{- if hasKey $resolved "backup" -}}
      {{- if not (kindIs "map" $resolved.backup) -}}{{- fail "resolved.backup must be an object" -}}{{- end -}}
      {{- if hasKey $resolved.backup "bindings" -}}
        {{- if not (kindIs "map" $resolved.backup.bindings) -}}{{- fail "resolved.backup.bindings must be an object" -}}{{- end -}}
        {{- if hasKey $resolved.backup.bindings $root.Values.instance -}}
          {{- $binding = index $resolved.backup.bindings $root.Values.instance -}}
          {{- $definitions := (mustFromJson ($root.Files.Get "interface.schema.json")).definitions -}}
          {{- include "paperless.validate" (dict "schema" $definitions.binding "definitions" $definitions "value" $binding "path" (printf "resolved.backup.bindings.%s" $root.Values.instance)) -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
  {{- if hasKey $desired "endpoint" -}}
    {{- if or (not (hasKey $binding "endpoint")) (ne $desired.endpoint $binding.endpoint) -}}
      {{- fail (printf "services.%s.backup.endpoint requires a matching resolved.backup.bindings.%s.endpoint" $root.Values.instance $root.Values.instance) -}}
    {{- end -}}
    {{- if not (hasKey $binding "repository") -}}{{- fail "The selected backup endpoint binding must supply repository" -}}{{- end -}}
  {{- end -}}
  {{- range $key := list "endpoint" "repository" "enabled" -}}
    {{- if and (hasKey $explicit $key) (hasKey $binding $key) (ne (index $explicit $key) (index $binding $key)) -}}
      {{- fail (printf "services.%s.backup.%s conflicts with its resolved backup binding" $root.Values.instance $key) -}}
    {{- end -}}
  {{- end -}}
  {{- if and (hasKey $binding "enabled") (not $binding.enabled) -}}
    {{- if or (hasKey $desired "endpoint") (hasKey $desired "repository") -}}{{- fail "A disabled resolved backup binding conflicts with the requested destination" -}}{{- end -}}
    {{- toYaml (dict "enabled" false) -}}
  {{- else -}}
    {{- $effective := deepCopy $desired -}}
    {{- range $key := list "repository" "readerSecret" "writerSecret" -}}
      {{- if and (hasKey $binding $key) (not (hasKey $explicit $key)) -}}
        {{- $_ := set $effective $key (index $binding $key) -}}
      {{- end -}}
    {{- end -}}
    {{- $enabled := hasKey $effective "repository" -}}
    {{- if and (or $desired.enabled $binding.enabled (hasKey $binding "endpoint")) (not $enabled) -}}{{- fail "Enabled Paperless backup requires a repository or a resolved endpoint binding" -}}{{- end -}}
    {{- $_ := set $effective "enabled" $enabled -}}
    {{- toYaml $effective -}}
  {{- end -}}
{{- end -}}
{{- end -}}
