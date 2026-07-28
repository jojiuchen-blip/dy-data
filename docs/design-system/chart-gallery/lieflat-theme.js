(function initializeDesignConsultantLieflatTheme(global) {
  "use strict";

  const COLOR_KEYS = [
  "1C1C1A",
  "2A2925",
  "2E2D29",
  "32312D",
  "33322D",
  "3A3934",
  "3F3E38",
  "4A4840",
  "4A4944",
  "55534B",
  "55544E",
  "55554F",
  "6A6963",
  "7C7A72",
  "8F8E88",
  "9C9A91",
  "A5A39A",
  "A5A49E",
  "A8A7A0",
  "B0AFA9",
  "B3B0A4",
  "C0BFB8",
  "C6C5BF",
  "C8C7C1",
  "C9C7BD",
  "C9C8C1",
  "CDCCC5",
  "CFCEC7",
  "D3D2CA",
  "D8D6CE",
  "D8D7D1",
  "DCDAD2",
  "DEDDD6",
  "E3E2DB",
  "E4E3DC",
  "E4E3DD",
  "F0EFEB",
  "F2F1ED"
];
  const root = document.documentElement;
  const params = new URLSearchParams(global.location?.search || "");
  const palette = params.get("palette") === "coral" ? "coral" : "harbor";
  const mode = params.get("theme") === "dark" ? "dark" : "light";
  root.dataset.palette = palette;
  root.dataset.theme = mode;
  root.dataset.embedded = String(global.self !== global.top);
  const computed = getComputedStyle(root);
  const token = (name, fallback) => computed.getPropertyValue(name).trim() || fallback;
  const semantic = Object.freeze({
    bg: token("--bg", "#F3F6F9"),
    surface: token("--surface", "#FFFFFF"),
    surfaceMuted: token("--surface-muted", "#EDF2F7"),
    surfaceRaised: token("--surface-raised", "#FFFFFF"),
    surfaceInverse: token("--surface-inverse", "#0B1F33"),
    surfaceInverseMuted: token("--surface-inverse-muted", "#1E2D45"),
    text: token("--text", "#14213D"),
    textMuted: token("--text-muted", "#526273"),
    textSoft: token("--text-soft", "#5C6B7A"),
    textInverse: token("--text-inverse", "#F5F9FF"),
    border: token("--border", "#D4DEE8"),
    borderStrong: token("--border-strong", "#AAB8C6"),
    reference: token("--viz-reference", token("--text-muted", "#526273")),
    grid: token("--viz-grid", token("--border", "#D4DEE8")),
    accentStrong: token("--viz-accent-strong", "#0958D9"),
    primary: token("--viz-accent", token("--primary", "#0F6CDD")),
    accentMid: token("--viz-accent-mid", "#5A9BE6"),
    accentSoft: token("--viz-accent-soft", "#A8CDF3"),
    accentSubtle: token("--viz-accent-subtle", "#D6E8FA"),
    accentArea: token("--viz-accent-area", "#E8F2FC"),
    accentOnDarkStrong: token("--viz-accent-on-dark-strong", "#D4E9FF"),
    accentOnDark: token("--viz-accent-on-dark", "#69B1FF"),
    accentOnDarkMid: token("--viz-accent-on-dark-mid", "#438CD5"),
    accentOnDarkSoft: token("--viz-accent-on-dark-soft", "#2A6299"),
    accentOnDarkSubtle: token("--viz-accent-on-dark-subtle", "#1C4269"),
    accentOnDarkArea: token("--viz-accent-on-dark-area", "#14334F"),
  });
  const colors = {};
  const sourcePositions = Object.create(null);

  function mixHex(from, to, amount) {
    const parse = (value) => [1, 3, 5].map((index) => Number.parseInt(value.slice(index, index + 2), 16));
    if (!/^#[0-9a-f]{6}$/i.test(from) || !/^#[0-9a-f]{6}$/i.test(to)) return from;
    const left = parse(from);
    const right = parse(to);
    const channels = left.map((value, index) => Math.round(value + (right[index] - value) * amount));
    return `#${channels.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
  }

  function normalizeColor(value) {
    if (typeof value !== "string") return value;
    const normalized = value.trim().toLowerCase();
    const rgb = normalized.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    if (!rgb) return normalized;
    return "#" + rgb.slice(1, 4)
      .map((channel) => Number(channel).toString(16).padStart(2, "0"))
      .join("");
  }

  for (const key of COLOR_KEYS) {
    const sourceTone = [0, 2, 4].reduce((total, index) => total + Number.parseInt(key.slice(index, index + 2), 16), 0) / 3;
    const position = Math.max(0, Math.min(1, (sourceTone - 28) / (242 - 28)));
    sourcePositions[key] = position;
    colors[key] = mixHex(semantic.text, mode === "dark" ? semantic.surface : semantic.bg, position);
  }

  colors["1C1C1A"] = semantic.text;
  colors["8F8E88"] = semantic.textMuted;
  colors.C6C5BF = mode === "dark" ? semantic.textSoft : semantic.borderStrong;
  colors.DEDDD6 = semantic.grid;
  colors.F0EFEB = mode === "dark" ? semantic.textInverse : semantic.bg;
  colors.F2F1ED = semantic.surface;

  const sourcePositionByValue = new Map();
  for (const key of COLOR_KEYS) {
    const normalized = normalizeColor(colors[key]);
    const existing = sourcePositionByValue.get(normalized) || [];
    existing.push(sourcePositions[key]);
    sourcePositionByValue.set(normalized, existing);
  }

  root.style.setProperty("--bg", semantic.bg);
  root.style.setProperty("--paper", colors.F0EFEB);
  root.style.setProperty("--dark", semantic.surfaceInverse);
  root.style.setProperty("--ink", semantic.text);
  root.style.setProperty("--muted", semantic.textMuted);
  root.style.setProperty("--faint", semantic.textSoft);
  root.style.setProperty("--grid", semantic.grid);
  root.style.setProperty("--reference", semantic.reference);

  const normalDataRamp = Object.freeze([
    semantic.accentStrong,
    semantic.primary,
    mixHex(semantic.primary, semantic.accentMid, 0.5),
    semantic.accentMid,
    semantic.accentSoft,
    semantic.accentSubtle,
  ]);
  const inverseDataRamp = Object.freeze([
    semantic.accentOnDarkStrong,
    semantic.accentOnDark,
    mixHex(semantic.accentOnDark, semantic.accentOnDarkMid, 0.5),
    semantic.accentOnDarkMid,
    semantic.accentOnDarkSoft,
    semantic.accentOnDarkSubtle,
  ]);
  const lightSourceRamp = normalDataRamp;
  const inverseSourceRamp = Object.freeze([...inverseDataRamp].reverse());
  const ladder = Object.freeze([...(mode === "dark" ? inverseDataRamp : normalDataRamp)]);
  const ladderCompact = Object.freeze([ladder[0], ladder[1], ladder[3], ladder[4], ladder[5]]);

  const matchesInk = (value, darkContext) => {
    const normalized = normalizeColor(value);
    return normalized === normalizeColor(semantic.text)
      || (darkContext && normalized === normalizeColor(colors.F0EFEB));
  };

  function sourcePosition(value) {
    if (typeof value !== "string") return null;
    const variable = value.match(/--viz-editorial-c-([0-9a-f]{6})/i);
    if (variable) return sourcePositions[variable[1].toUpperCase()] ?? null;
    const positions = sourcePositionByValue.get(normalizeColor(value));
    if (!positions?.length) return null;
    return positions.reduce((total, position) => total + position, 0) / positions.length;
  }

  function rampIndex(value, ramp) {
    const normalized = normalizeColor(value);
    return ramp.findIndex((candidate) => normalizeColor(candidate) === normalized);
  }

  function sampleRamp(ramp, position) {
    const scaled = Math.max(0, Math.min(1, position)) * (ramp.length - 1);
    const left = Math.floor(scaled);
    const right = Math.min(ramp.length - 1, left + 1);
    return mixHex(ramp[left], ramp[right], scaled - left);
  }

  function mapMarkColor(value, darkContext) {
    if (Array.isArray(value)) return value.map((item) => mapMarkColor(item, darkContext));
    if (typeof value !== "string" || value === "transparent" || value === "none") return value;

    const normalIndex = rampIndex(value, normalDataRamp);
    if (darkContext && normalIndex >= 0) return inverseDataRamp[normalIndex];
    const inverseIndex = rampIndex(value, inverseDataRamp);
    if (!darkContext && inverseIndex >= 0) return normalDataRamp[inverseIndex];

    const position = sourcePosition(value);
    if (position != null) {
      return sampleRamp(darkContext ? inverseSourceRamp : lightSourceRamp, position);
    }
    if (matchesInk(value, darkContext)) return darkContext ? semantic.accentOnDark : semantic.primary;
    return value;
  }

  function mapLineColor(value, darkContext) {
    if (Array.isArray(value)) return value.map((item) => mapLineColor(item, darkContext));
    if (typeof value !== "string" || value === "transparent" || value === "none") return value;

    const normalIndex = rampIndex(value, normalDataRamp);
    if (darkContext && normalIndex >= 0) return inverseDataRamp[normalIndex];
    const inverseIndex = rampIndex(value, inverseDataRamp);
    if (!darkContext && inverseIndex >= 0) return normalDataRamp[inverseIndex];

    const position = sourcePosition(value);
    if (position != null) {
      return sampleRamp(darkContext ? inverseDataRamp : normalDataRamp, position);
    }
    if (matchesInk(value, darkContext)) return darkContext ? semantic.accentOnDark : semantic.primary;
    return value;
  }

  function mapSvgDataColor(value, darkContext) {
    if (Array.isArray(value)) return value.map((item) => mapSvgDataColor(item, darkContext));
    if (typeof value !== "string" || value === "transparent" || value === "none") return value;

    const normalIndex = rampIndex(value, normalDataRamp);
    if (darkContext && normalIndex >= 0) return inverseDataRamp[normalIndex];
    const inverseIndex = rampIndex(value, inverseDataRamp);
    if (!darkContext && inverseIndex >= 0) return normalDataRamp[inverseIndex];
    return matchesInk(value, darkContext)
      ? darkContext ? semantic.accentOnDark : semantic.primary
      : value;
  }

  const areaColor = (darkContext) => darkContext ? semantic.accentOnDarkArea : semantic.accentArea;
  const keylineColor = (darkContext) => darkContext ? semantic.surfaceInverse : semantic.accentStrong;

  function accentEChartsOption(option, darkContext) {
    if (!option || typeof option !== "object") return option;
    const palette = darkContext ? inverseDataRamp : normalDataRamp;
    option.color = Array.isArray(option.color)
      ? option.color.map((_, index) => palette[index % palette.length])
      : [...palette];
    const blockedKeys = new Set(["label", "endLabel", "axisLabel", "textStyle", "title", "tooltip"]);
    const styleKeys = new Set(["itemStyle", "lineStyle", "areaStyle"]);

    function visit(value, styleContext = null, blocked = false) {
      if (!value || typeof value !== "object") return;
      if (Array.isArray(value)) {
        value.forEach((item) => visit(item, styleContext, blocked));
        return;
      }
      for (const [key, child] of Object.entries(value)) {
        const nextBlocked = blocked || blockedKeys.has(key);
        const nextStyleContext = styleKeys.has(key) ? key : styleContext;
        if (!nextBlocked && nextStyleContext && key === "color") {
          value[key] = nextStyleContext === "areaStyle"
            ? areaColor(darkContext)
            : nextStyleContext === "lineStyle"
              ? mapLineColor(child, darkContext)
              : mapMarkColor(child, darkContext);
        } else if (!nextBlocked && nextStyleContext && key === "borderColor") {
          value[key] = nextStyleContext === "itemStyle"
            ? keylineColor(darkContext)
            : mapMarkColor(child, darkContext);
        } else {
          visit(child, nextStyleContext, nextBlocked);
        }
      }
    }

    const series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : [];
    series.forEach((item) => visit(item));
    return option;
  }

  function accentChartConfig(config, darkContext) {
    const datasets = config?.data?.datasets;
    if (!Array.isArray(datasets)) return config;
    for (const dataset of datasets) {
      const chartType = dataset.type || config.type;
      const isFilledLine = chartType === "line" && dataset.fill !== false;
      if ("backgroundColor" in dataset) {
        dataset.backgroundColor = isFilledLine
          ? areaColor(darkContext)
          : mapMarkColor(dataset.backgroundColor, darkContext);
      }
      if ("borderColor" in dataset) dataset.borderColor = mapLineColor(dataset.borderColor, darkContext);
      if ("pointBackgroundColor" in dataset) dataset.pointBackgroundColor = mapMarkColor(dataset.pointBackgroundColor, darkContext);
      if ("pointBorderColor" in dataset) dataset.pointBorderColor = mapLineColor(dataset.pointBorderColor, darkContext);
    }
    return config;
  }

  function accentSvgShape(shape) {
    if (!(shape instanceof Element) || !["circle", "ellipse", "line", "path", "polygon", "polyline", "rect"].includes(shape.localName)) return;
    if (shape.matches(".hit,[data-no-accent]") || shape.closest("defs,clipPath,mask")) return;
    const darkContext = mode === "dark" || Boolean(shape.closest(".card.dark"));
    const opacity = Number.parseFloat(shape.getAttribute("opacity") || "1");
    const fillOpacity = Number.parseFloat(shape.getAttribute("fill-opacity") || "1");
    const strokeOpacity = Number.parseFloat(shape.getAttribute("stroke-opacity") || "1");
    const computedStyle = getComputedStyle(shape);
    const fill = shape.getAttribute("fill") || computedStyle.fill;
    const stroke = shape.getAttribute("stroke") || computedStyle.stroke;
    const mappedFill = mapSvgDataColor(fill, darkContext);
    const mappedStroke = mapSvgDataColor(stroke, darkContext);
    const hasVisibleFill = fill && !["none", "transparent"].includes(fill) && fillOpacity > 0.05;
    if (opacity > 0.05 && hasVisibleFill && mappedFill !== fill) shape.setAttribute("fill", mappedFill);
    if (opacity > 0.05 && strokeOpacity > 0.05 && mappedStroke !== stroke) {
      shape.setAttribute("stroke", mappedFill !== fill ? keylineColor(darkContext) : mappedStroke);
    }
  }

  function scanSvg(rootNode) {
    if (!(rootNode instanceof Element || rootNode instanceof Document)) return;
    if (rootNode instanceof Element) accentSvgShape(rootNode);
    rootNode.querySelectorAll?.("svg circle,svg ellipse,svg line,svg path,svg polygon,svg polyline,svg rect").forEach(accentSvgShape);
  }

  let svgAdapterInstalled = false;
  function installSvgAdapter() {
    if (svgAdapterInstalled || !document.body) return;
    svgAdapterInstalled = true;
    scanSvg(document);
    new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach(scanSvg);
      }
    }).observe(document.body, {
      subtree: true,
      childList: true,
    });
  }

  function installAdapters() {
    installSvgAdapter();

    if (global.echarts && !global.echarts.__dcSemanticAccent) {
      const originalInit = global.echarts.init.bind(global.echarts);
      global.echarts.init = function initializeWithSemanticAccent(dom, ...args) {
        const chart = originalInit(dom, ...args);
        if (!chart.__dcSemanticAccent) {
          const originalSetOption = chart.setOption.bind(chart);
          const darkContext = mode === "dark" || Boolean(dom?.closest?.(".card.dark"));
          chart.setOption = (option, ...setOptionArgs) => originalSetOption(
            accentEChartsOption(option, darkContext),
            ...setOptionArgs
          );
          chart.__dcSemanticAccent = true;
        }
        return chart;
      };
      global.echarts.__dcSemanticAccent = true;
    }

    if (global.Chart && !global.Chart.__dcSemanticAccent) {
      const NativeChart = global.Chart;
      const WrappedChart = new Proxy(NativeChart, {
        construct(Target, args) {
          const canvas = args[0]?.canvas || args[0];
          const darkContext = mode === "dark" || Boolean(canvas?.closest?.(".card.dark"));
          if (args[1]) accentChartConfig(args[1], darkContext);
          return Reflect.construct(Target, args);
        },
      });
      WrappedChart.__dcSemanticAccent = true;
      global.Chart = WrappedChart;
    }
  }

  global.DC_LIEFLAT_COLORS = Object.freeze(colors);
  global.DC_LIEFLAT_THEME = Object.freeze({
    name: "design-consultant-editorial-utility",
    palette,
    mode,
    accent: semantic.primary,
    accentStrong: semantic.accentStrong,
    accentMid: semantic.accentMid,
    accentSoft: semantic.accentSoft,
    accentSubtle: semantic.accentSubtle,
    accentArea: semantic.accentArea,
    accentOnDark: semantic.accentOnDark,
    accentOnDarkStrong: semantic.accentOnDarkStrong,
    accentOnDarkMid: semantic.accentOnDarkMid,
    accentOnDarkSoft: semantic.accentOnDarkSoft,
    accentOnDarkSubtle: semantic.accentOnDarkSubtle,
    accentOnDarkArea: semantic.accentOnDarkArea,
    accentRamp: normalDataRamp,
    accentRampOnDark: inverseDataRamp,
    ink: colors["1C1C1A"],
    paper: colors.F0EFEB,
    muted: colors["8F8E88"],
    faint: colors.C6C5BF,
    grid: colors.DEDDD6,
    ladder,
    ladderCompact,
    installAdapters,
  });
})(typeof window !== "undefined" ? window : globalThis);
