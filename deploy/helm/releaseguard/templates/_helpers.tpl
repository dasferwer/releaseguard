{{- define "releaseguard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "releaseguard.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "releaseguard.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "releaseguard.labels" -}}
app.kubernetes.io/name: {{ include "releaseguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "releaseguard.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "releaseguard.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

