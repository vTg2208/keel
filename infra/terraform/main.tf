terraform {
  required_version = ">= 1.6.0"
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.38" }
  }
}

variable "kubeconfig_path" {
  type        = string
  description = "Absolute path to PayOps .local/kubeconfig"
}

provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = "kind-payops"
}

# Separate ownership: ops.py never manages these objects or this namespace.
resource "kubernetes_namespace_v1" "practice" {
  metadata { name = "payops-practice" }
}

resource "kubernetes_resource_quota_v1" "practice" {
  metadata {
    name      = "practice-budget"
    namespace = kubernetes_namespace_v1.practice.metadata[0].name
  }
  spec {
    hard = {
      "requests.cpu"    = "1"
      "requests.memory" = "512Mi"
      "limits.cpu"      = "2"
      "limits.memory"   = "1Gi"
      "pods"            = "5"
    }
  }
}
