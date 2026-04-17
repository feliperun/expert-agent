# Changelog

## [0.1.2](https://github.com/feliperun/expert-agent/compare/v0.1.1...v0.1.2) (2026-04-17)


### Features

* Public launch — MIT license, brand block, governance, and multi-agent workspaces ([#4](https://github.com/feliperun/expert-agent/issues/4)) ([a35a034](https://github.com/feliperun/expert-agent/commit/a35a034caf48d4ae5c1048f00c65f3fff3b15cc6))


### Documentation

* Add agent-friendly E2E onboarding guide ([5ddb9ec](https://github.com/feliperun/expert-agent/commit/5ddb9ec55225514e74c26d259b395cfe7e3c7935))

## [0.1.1](https://github.com/feliperbroering/expert-agent/compare/v0.1.0...v0.1.1) (2026-04-17)


### Features

* **backend:** Fastapi core with gemini, context cache, docs sync, multi-layer memory ([d2bf364](https://github.com/feliperbroering/expert-agent/commit/d2bf36472e1f40cc3424612906812059e767c09f))
* **cli:** Typer cli with init, validate, count-tokens, sync, ask, sessions ([215b3bf](https://github.com/feliperbroering/expert-agent/commit/215b3bfc7c9d1de42690bd9ec41f473429b4a327))
* Cut agent latency and give the CLI a live typewriter UX ([c9f0e57](https://github.com/feliperbroering/expert-agent/commit/c9f0e57f0a7ab14d9c338169acace7baa6351d17))
* **deploy:** Production-ready GCS schema bootstrap, File API mirror, VPC routing ([457d2da](https://github.com/feliperbroering/expert-agent/commit/457d2da6e90396989bdc762fa57238c959447418))
* **infra:** Opentofu stacks for platform, chroma server, per-agent deploys ([8654752](https://github.com/feliperbroering/expert-agent/commit/8654752c63899181e3c2efc08bc3b457bbf61587))
* Initial project foundation ([2de3a19](https://github.com/feliperbroering/expert-agent/commit/2de3a19c2048ede33dfa9e80a5330f0f5076a14d))
* Rename CLI to `expert` + ship packaged Robot Framework E2E kit ([4dd922e](https://github.com/feliperbroering/expert-agent/commit/4dd922e3d051a87d8904b849983685c2041143e9))


### Bug Fixes

* **cli:** Align ask command with the real backend SSE/JSON contract ([f187efc](https://github.com/feliperbroering/expert-agent/commit/f187efc839f538e2f42a437201ae088008748ead))
* **mypy:** Ignore google.cloud.storage attr-defined (namespace package) ([043c587](https://github.com/feliperbroering/expert-agent/commit/043c58774f7aa5e78156d53f768249ef3fad3042))
* **tests,ci:** Unblock pytest + mypy on main ([66fcdd8](https://github.com/feliperbroering/expert-agent/commit/66fcdd82ea49aaddfec9f7a3233615cdf02cd947))
* Warm Gemini cache at startup + writable cache dir ([f13f863](https://github.com/feliperbroering/expert-agent/commit/f13f8631a5d1dffa60561a4120b1cc90b3254333))


### Documentation

* **readme:** Drop bogus subdirectory=cli from uv tool install ([9414da8](https://github.com/feliperbroering/expert-agent/commit/9414da80e5178018ecdd677431efeac9caf9a298))
* Ship full Apache-2.0 LICENSE and production-grade README ([5ed29c2](https://github.com/feliperbroering/expert-agent/commit/5ed29c28e562578d13b6372b5d925dacaceebbc9))
