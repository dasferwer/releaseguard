provider "kubernetes" {
  config_path = pathexpand(var.kubeconfig_path)
}

provider "helm" {
  kubernetes = {
    config_path = pathexpand(var.kubeconfig_path)
  }
}

resource "kubernetes_namespace_v1" "releaseguard" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/part-of" = "releaseguard"
    }
  }
}

resource "kubernetes_secret_v1" "releaseguard" {
  metadata {
    name      = "releaseguard-secrets"
    namespace = kubernetes_namespace_v1.releaseguard.metadata[0].name
  }
  data = {
    DATABASE_URL   = var.database_url
    WEBHOOK_SECRET = var.webhook_secret
  }
  type = "Opaque"
}

resource "helm_release" "releaseguard" {
  name       = "releaseguard"
  namespace  = kubernetes_namespace_v1.releaseguard.metadata[0].name
  chart      = "../../deploy/helm/releaseguard"
  atomic     = true
  timeout    = 300
  depends_on = [kubernetes_secret_v1.releaseguard]

  set = [
    {
      name  = "image.repository"
      value = var.image_repository
    },
    {
      name  = "image.tag"
      value = var.image_tag
    }
  ]
}

