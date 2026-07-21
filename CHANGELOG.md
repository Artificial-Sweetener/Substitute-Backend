# [1.8.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.7.1...v1.8.0) (2026-07-21)


### Features

* **sugarcubes:** consume versioned host API ([31e403b](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/31e403b50757aa0fe127c161c73b40609acb996f))

## [1.7.1](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.7.0...v1.7.1) (2026-07-19)


### Bug Fixes

* **model-metadata:** target configured model refreshes ([b139183](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/b139183952a601374024af04843ae8dbeeeb3e18))

# [1.7.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.6.2...v1.7.0) (2026-07-16)


### Features

* **environment:** manage ComfyUI model roots ([94ef103](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/94ef103bb6ee899e41ba5b869ffa0a97c6e828b5))

## [1.6.2](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.6.1...v1.6.2) (2026-07-11)


### Bug Fixes

* **models:** invalidate caches before rescanning ([936927c](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/936927c9dd0559952c37b7022f98a4149d1fb645))
* **queue:** reject partial prompt validation ([807cbc6](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/807cbc6e70197932ef82847f9e095fb44554186d))

## [1.6.1](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.6.0...v1.6.1) (2026-07-08)


### Performance Improvements

* **startup:** reuse SugarCubes services and cache dependency scans ([5a96961](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/5a969612dee9b7f01747779deb73d3ff056ba0cf))

# [1.6.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.5.1...v1.6.0) (2026-06-17)


### Bug Fixes

* **deps:** require sugar-dsl 1.1.3 ([e525713](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/e5257131716e11762c4450f56906ec7f45fa876d))


### Features

* **model-metadata:** add catalog refresh route support ([1656ae5](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/1656ae5cb3039a685e9e86d8658353581d654faa))

## [1.5.1](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.5.0...v1.5.1) (2026-06-05)


### Bug Fixes

* **prompt-queue:** preserve graph boundaries during dedupe ([dd8814b](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/dd8814bfee905e41735d62ce825ed13d030b5d23))

# [1.5.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.4.0...v1.5.0) (2026-06-04)


### Features

* **capabilities:** expose sugar dsl version ([35909cd](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/35909cd9ebe0ca7112d9fb6b2ebd5026fe80b9f7))
* **cube-library:** expose SugarCubes sync capabilities ([d3a337a](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/d3a337a7fd81b4db852a26287f655599e22978dd))

# [1.4.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.3.0...v1.4.0) (2026-06-02)


### Features

* **visual-routing:** enrich Comfy image events ([7d11f33](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/7d11f33cc247759c31f8a4a62f9d54ca6233272e))

# [1.3.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.2.0...v1.3.0) (2026-05-27)


### Features

* **model-metadata:** publish model folder changes ([a7cb2fc](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/a7cb2fc9863f3fab5506c5c304cae22e90c05fa5))

# [1.2.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.1.0...v1.2.0) (2026-05-26)


### Features

* **prompt-queue:** optimize duplicate resource streams ([372df6d](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/372df6dc8183404e64236f073ae4c4b88f04bde4))

# [1.1.0](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.0.1...v1.1.0) (2026-05-26)


### Bug Fixes

* **ci:** require typed sugar-dsl release ([3d56832](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/3d5683271bdfff569b7372eeb14502e60e65f276))


### Features

* **backend:** add Sugar compile and dependency repair support ([f1b0d74](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/f1b0d74a2997925133d825c5c227ce9dff8f159d))

## [1.0.1](https://github.com/Artificial-Sweetener/Substitute-Backend/compare/v1.0.0...v1.0.1) (2026-05-22)


### Bug Fixes

* **cube-library:** remove backend sugar compilation ([0efb3e7](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/0efb3e71c06306f0c7f33ba187517ddc1f54377f))

# 1.0.0 (2026-05-21)


### Features

* initial release ([0202bce](https://github.com/Artificial-Sweetener/Substitute-Backend/commit/0202bcea1801cf8ddaf9658d639c7756dcba2501))

# Changelog

## v1.0.0 (2026-05-21)

### Features

- Initial release of Substitute BackEnd as a ComfyUI backend liaison for SugarSubstitute.
