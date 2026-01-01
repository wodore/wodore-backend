<!-- Auto generated. Run 'inv release' in order to update -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.10] - 2026-01-01

#### 🏗️ Breaking changes
- Add availability tables, commands and admin views. Uddate get_booking api endpoint. ([#36](https://github.com/wodore/wodore-backend/pull/36))

#### 🚀 Features
- Update oidc header for auth calls. Extend session login time to 7 days. ([#38](https://github.com/wodore/wodore-backend/pull/38))
- Add internal oidc url with external url as header (optional) ([#37](https://github.com/wodore/wodore-backend/pull/37))
- No error on missing images, add S3 storage ([#30](https://github.com/wodore/wodore-backend/pull/30))

#### 🐛 Fixes
- Improve parameter updates during oidc flow ([#40](https://github.com/wodore/wodore-backend/pull/40))
- Fix oidc issues ([#39](https://github.com/wodore/wodore-backend/pull/39))
- Follow redirects. Improve imagor hashes. ([#32](https://github.com/wodore/wodore-backend/pull/32))
- Fix imagor signing issue and redirect urls ([#29](https://github.com/wodore/wodore-backend/pull/29))

#### 🏭 Refactor
- Fix hrs booking, use default request_intervall parameter ([#33](https://github.com/wodore/wodore-backend/pull/33))
- Replace wodore.com with wodo.re ([#28](https://github.com/wodore/wodore-backend/pull/28))

#### 📝 Documentation
- Add informations (links) to documentation: https://wodore.github.io/wodore-backend/infos/ ([#31](https://github.com/wodore/wodore-backend/pull/31))
- Add OpenApi documentation ([#27](https://github.com/wodore/wodore-backend/pull/27))

[0.1.10]: https://github.com/wodore/wodore-backend/compare/v0.1.9..v0.1.10

## [0.1.9] - 2025-08-21

Initial release.

#### 🚀 Features
- Ignore connection error oicd ([#16](https://github.com/wodore/wodore-backend/pull/16))
- Open monthly formfield and green for empty huts ([#10](https://github.com/wodore/wodore-backend/pull/10))

#### 🐛 Fixes
- Fix frontend hut link ([#11](https://github.com/wodore/wodore-backend/pull/11))
- Fix hut location field missing ([#8](https://github.com/wodore/wodore-backend/pull/8))

#### 🧪 Dependencies
- Update python packages ([#12](https://github.com/wodore/wodore-backend/pull/12), [#13](https://github.com/wodore/wodore-backend/pull/13), [#18](https://github.com/wodore/wodore-backend/pull/18))

#### 🌀 Others
- Include git hash in docker build ([#19](https://github.com/wodore/wodore-backend/pull/19))
- Use `READ_DOCKER_TOKEN` and `READ_DOCKER_USER` for private repo access during docker build. ([#5](https://github.com/wodore/wodore-backend/pull/5))
- Add docker invoke scripts ([#4](https://github.com/wodore/wodore-backend/pull/4))
- Switch from `poetry` to [`uv`](https://docs.astral.sh/uv/) ([#1](https://github.com/wodore/wodore-backend/pull/1))

[0.1.9]: https://github.com/wodore/wodore-backend/releases/tag/v0.1.9
