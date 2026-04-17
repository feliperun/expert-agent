variable "project_id" {
  description = "GCP project ID (must match the platform + chroma stacks)."
  type        = string
}

variable "region" {
  description = "GCP region (must match the platform + chroma stacks)."
  type        = string
  default     = "southamerica-east1"
}

variable "agent_id" {
  description = "Unique agent identifier (becomes part of service name, SA id, secret name, bucket prefix). Lowercase kebab-case, ≤63 chars."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.agent_id)) && length(var.agent_id) <= 63
    error_message = "agent_id must match ^[a-z][a-z0-9-]*$ and be at most 63 characters."
  }
}

variable "image" {
  description = "Fully-qualified container image reference for this agent (e.g. southamerica-east1-docker.pkg.dev/PROJECT/expert-agent/backend:v0.1.0)."
  type        = string
}

variable "min_instances" {
  description = "Cloud Run min instances. Keep at 0 for scale-to-zero (agent is stateless — all state lives in Chroma/Firestore)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Cloud Run max instances."
  type        = number
  default     = 10
}

variable "cpu" {
  description = "vCPU per instance (Cloud Run v2 string format: \"1\", \"2\", \"4\")."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory per instance (e.g. \"512Mi\", \"1Gi\", \"2Gi\")."
  type        = string
  default     = "1Gi"
}

variable "cache_ttl_seconds" {
  description = <<-EOT
    Context Cache TTL passed to the app as CACHE_TTL_SECONDS.

    Trade-off: Gemini charges cache storage per (tokens * hour). With a large
    corpus (e.g. 800k tokens) a 1h TTL is cheap but cold users pay a ~30s
    "recreate cache" penalty. A 6h TTL costs a few cents/day and keeps the
    cache alive across typical idle gaps. 24h is viable for heavy use.

    Must also be <= the value used when the app calls create_cache; see
    schema.spec.context_cache.ttl_seconds.
  EOT
  type        = number
  default     = 21600 # 6 hours
}

variable "admin_key_secret_name" {
  description = "Name of the per-agent admin API key secret. Default = admin-key-<agent_id>."
  type        = string
  default     = ""
}

locals {
  admin_key_secret_name = var.admin_key_secret_name != "" ? var.admin_key_secret_name : "admin-key-${var.agent_id}"
}
