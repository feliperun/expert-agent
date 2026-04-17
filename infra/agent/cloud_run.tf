# Per-agent Cloud Run service.
#
# The agent is STATELESS — all durable state lives in:
#   - Firestore              (short-term chat history, cache metadata)
#   - the Chroma HTTP server (long-term vector memory)
#   - GCS docs/backups       (reference documents, snapshots)
#
# This means:
#   - min_instance_count can be 0 (scale-to-zero works)
#   - max_instance_count can be >1 safely (no single-writer contention)
#   - no FUSE volumes — the agent talks to Chroma over HTTPS.

locals {
  # MemPalace / Chroma HttpClient expects a bare host, not a URL.
  chroma_url  = data.terraform_remote_state.chroma.outputs.chroma_url
  chroma_host = replace(local.chroma_url, "https://", "")
}

resource "google_cloud_run_v2_service" "agent" {
  project      = var.project_id
  name         = var.agent_id
  location     = var.region
  ingress      = "INGRESS_TRAFFIC_ALL"
  launch_stage = "GA"

  # Flipping to `true` is the responsibility of the operator when the agent
  # goes to production. Keeping it disabled here means `tofu destroy` works
  # for MVP / teardown drills.
  deletion_protection = false

  template {
    service_account = google_service_account.agent.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # All egress routes through the VPC so Cloud Run-to-Cloud Run requests
    # with `ingress=INTERNAL_ONLY` (Chroma) stay private and are recognised
    # as intra-project traffic. `PRIVATE_RANGES_ONLY` is insufficient because
    # *.run.app resolves to public IPs.
    vpc_access {
      network_interfaces {
        network    = "default"
        subnetwork = "default"
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # Temporarily boosts CPU (up to 4x) while the container is starting up.
        # Eliminates most of the cold-start penalty on Python workloads with
        # heavy imports (google-genai, chromadb-client, etc.). Billed only
        # during the boost window, so it's essentially free in practice.
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      # Plain env vars consumed by backend/app/config.py.
      env {
        name  = "AGENT_ID"
        value = var.agent_id
      }
      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      # Load the agent schema + prompts from GCS so the container image stays
      # agent-agnostic. The path must match where `agent-cli sync` (or the
      # operator) uploaded the schema bundle.
      env {
        name  = "SCHEMA_PATH"
        value = "gs://${data.terraform_remote_state.platform.outputs.docs_bucket}/${var.agent_id}/schema/agent_schema.yaml"
      }
      env {
        name  = "DOCS_BUCKET"
        value = data.terraform_remote_state.platform.outputs.docs_bucket
      }
      env {
        name  = "BACKUPS_BUCKET"
        value = data.terraform_remote_state.platform.outputs.backups_bucket
      }
      env {
        name  = "MEMPALACE_CHROMA_HOST"
        value = local.chroma_host
      }
      env {
        name  = "MEMPALACE_CHROMA_PORT"
        value = "443"
      }
      env {
        name  = "MEMPALACE_CHROMA_SSL"
        value = "true"
      }
      env {
        name  = "MEMPALACE_CHROMA_COLLECTION"
        value = "agent_${var.agent_id}"
      }
      env {
        name  = "CACHE_TTL_SECONDS"
        value = tostring(var.cache_ttl_seconds)
      }

      # Secrets — always resolve to :latest so rotations propagate on the
      # next cold start.
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ADMIN_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_iam_member.agent_admin_key,
    google_secret_manager_secret_iam_member.agent_gemini_key,
    google_project_iam_member.agent_firestore,
    google_storage_bucket_iam_member.agent_docs,
    google_storage_bucket_iam_member.agent_backups,
  ]
}
