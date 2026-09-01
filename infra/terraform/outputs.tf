output "namespace" {
  value = kubernetes_namespace_v1.releaseguard.metadata[0].name
}

output "release_name" {
  value = helm_release.releaseguard.name
}

