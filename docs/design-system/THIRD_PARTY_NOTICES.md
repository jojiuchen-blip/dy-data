# Third-party chart notices

## Lieflat Charts

- Project: [Lieflat Charts](https://github.com/larashero3-dotcom/lieflat-charts)
- Integrated sources: `templates/lupi-gallery.html`, `templates/basics-gallery.html`, and `templates/glance-gallery.html`
- Integrated chart structures: the searchable design-system Gallery plus the runtime-selected `G8 Rainfall Dual Area` and `G15 Jitter Strip`
- License: [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)
- dy-data adaptations: business data, Chinese labels, accessibility copy, Gallery search bridge, and colors resolved from dy-data semantic chart tokens. Gallery geometry, interaction, and animation remain the provided implementation.

The license permits noncommercial purposes. Commercial use is not granted by these terms and requires separate authorization from the licensor. Keep this notice and the license URL with any distributed copy that contains the integrated template code.

## Apache ECharts

- Project: [Apache ECharts](https://github.com/apache/echarts)
- Version: `6.1.0`
- License: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Runtime use: modular ECharts package in the React application; the static chart-gallery pages load the vendored browser build in `docs/design-system/vendor/echarts.min.js` for executable offline previews.

Apache ECharts remains governed by its own license and is not covered by the Lieflat Charts license.
