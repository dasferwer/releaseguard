variable "kubeconfig_path" {
  description = "Путь к файлу kubeconfig"
  type        = string
  default     = "~/.kube/config"
}

variable "namespace" {
  description = "Пространство имён ReleaseGuard"
  type        = string
  default     = "releaseguard"
}

variable "image_repository" {
  description = "OCI-репозиторий образа приложения"
  type        = string
}

variable "image_tag" {
  description = "Неизменяемый тег образа приложения"
  type        = string
}

variable "database_url" {
  description = "Адрес асинхронного подключения к PostgreSQL"
  type        = string
  sensitive   = true
}

variable "webhook_secret" {
  description = "Секрет HMAC для событий CI"
  type        = string
  sensitive   = true
}

variable "api_clients" {
  description = "JSON с именами клиентов API, ролями и секретными ключами"
  type        = string
  sensitive   = true
}
