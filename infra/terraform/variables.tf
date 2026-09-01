variable "kubeconfig_path" {
  description = "Path to a kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "namespace" {
  description = "Namespace for ReleaseGuard"
  type        = string
  default     = "releaseguard"
}

variable "image_repository" {
  description = "OCI repository for the application image"
  type        = string
}

variable "image_tag" {
  description = "Immutable application image tag"
  type        = string
}

variable "database_url" {
  description = "Async PostgreSQL connection URL"
  type        = string
  sensitive   = true
}

variable "webhook_secret" {
  description = "HMAC secret for CI events"
  type        = string
  sensitive   = true
}

