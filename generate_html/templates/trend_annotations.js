(() => {
  const DAY_MS = 86400000;
  const pad2 = value => String(value).padStart(2, "0");
  const padYear = value => String(value).padStart(4, "0");
  const escapeMarkup = value => value.replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  function dateKey(value, grain) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return "";
    const day = new Date(value + "T00:00:00Z");
    if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value) return "";
    if (grain === "day") return value;
    if (grain === "month") return value.slice(0, 7);
    if (grain !== "week") return "";

    // The Thursday belongs to the ISO week year, including weeks spanning New Year.
    day.setUTCDate(day.getUTCDate() + 4 - (day.getUTCDay() || 7));
    const year = day.getUTCFullYear();
    const firstDay = new Date(0);
    firstDay.setUTCFullYear(year, 0, 1);
    const week = Math.floor((day - firstDay) / (7 * DAY_MS)) + 1;
    return padYear(year) + "-WK" + pad2(week);
  }

  function periodKey(period, grain) {
    const value = String(period ?? "").trim();
    if (grain === "day") return dateKey(value, "day");
    if (grain === "week") {
      const match = /^(\d{2}|\d{4})-?WK(\d{1,2})$/i.exec(value);
      if (!match || +match[2] < 1 || +match[2] > 53) return "";
      return (match[1].length === 2 ? "20" : "") + match[1] + "-WK" + pad2(match[2]);
    }
    if (grain === "month") {
      const match = /^(\d{2}|\d{4})[-/.年](\d{1,2})月?$/.exec(value);
      if (!match || +match[2] < 1 || +match[2] > 12) return "";
      return (match[1].length === 2 ? "20" : "") + match[1] + "-" + pad2(match[2]);
    }
    return "";
  }

  let measurementContext;
  function labelMetrics() {
    const rootStyle = typeof document === "undefined" ? null : getComputedStyle(document.documentElement);
    const fontSize = parseFloat(rootStyle?.getPropertyValue("--font-caption")) || 12;
    if (rootStyle) {
      measurementContext ||= document.createElement("canvas").getContext("2d");
      if (measurementContext) {
        measurementContext.font = "650 " + fontSize + "px " + getComputedStyle(document.body).fontFamily;
      }
    }
    return {
      lineHeight: Math.ceil(fontSize * 4 / 3),
      measure: text => measurementContext
        ? Math.ceil(measurementContext.measureText(text).width)
        : Array.from(text).reduce((width, char) => width + (char.codePointAt(0) > 127 ? fontSize : fontSize * 2 / 3), 0)
    };
  }

  function wrapLabel(text, maxWidth, measure) {
    const lines = [];
    for (const paragraph of text.split(/\r?\n/)) {
      let line = "";
      for (const char of paragraph) {
        if (line && measure(line + char) > maxWidth) {
          lines.push(line);
          line = char;
        } else {
          line += char;
        }
      }
      lines.push(line);
    }
    return lines;
  }

  function render(notes, periods, grain, { left, step, width }) {
    const groups = new Map();
    for (const note of notes) {
      const key = dateKey(note?.date, grain);
      const text = typeof note?.text === "string" ? note.text.trim() : "";
      if (!key || !text) continue;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ date: note.date, text });
    }
    if (!groups.size) return { height: 0, markup: "" };

    const gap = 6;
    const top = 6;
    const paddingX = 6;
    const paddingY = 3;
    const { measure, lineHeight } = labelMetrics();
    const lanes = [];
    const markers = [];
    const seen = new Set();
    periods.forEach((period, index) => {
      const key = periodKey(period, grain);
      const events = groups.get(key);
      if (!events || seen.has(key)) return;
      seen.add(key);
      events.sort((a, b) => a.date.localeCompare(b.date));
      markers.push({
        key, events, x: left + (index + 0.5) * step,
        description: events.map(event => event.date + " " + event.text).join("\n")
      });
    });
    if (!markers.length) return { height: 0, markup: "" };

    markers.forEach((marker, index) => {
      const previous = markers[index - 1], next = markers[index + 1];
      const distance = Math.min(previous ? marker.x - previous.x : Infinity, next ? next.x - marker.x : Infinity);
      const maxWidth = Math.min(width - 8, Math.max(156, Math.min(320, distance - gap)));
      const lines = marker.events.flatMap(event => wrapLabel(event.text, maxWidth - paddingX * 2, measure));
      const boxWidth = Math.max(...lines.map(measure)) + paddingX * 2;
      const boxX = Math.max(4, Math.min(marker.x - boxWidth / 2, width - boxWidth - 4));
      const cardHeight = Math.max(22, lines.length * lineHeight + paddingY * 2);
      let lane = lanes.findIndex(row => row.end + gap <= boxX);
      if (lane < 0) {
        lane = lanes.length;
        lanes.push({ end: 0, height: 0, y: 0 });
      }
      lanes[lane].end = boxX + boxWidth;
      lanes[lane].height = Math.max(lanes[lane].height, cardHeight);
      Object.assign(marker, { lines, boxX, boxWidth, cardHeight, lane });
    });

    let height = top;
    for (const lane of lanes) {
      lane.y = height;
      height += lane.height + gap;
    }
    height += 10;
    const stems = markers.map(({ x, cardHeight, lane }) =>
      '<line class="trend-annotation-stem" x1="' + x + '" x2="' + x + '" y1="' + (lanes[lane].y + cardHeight) + '" y2="' + (height + 22) + '"/>' +
      '<path class="trend-annotation-tip" d="M ' + (x - 4) + ' ' + (height + 22) + ' h 8 l -4 6 Z"/>'
    ).join("");
    const labels = markers.map(({ key, boxX, boxWidth, cardHeight, lane, lines, description }) => {
      const accessibleText = escapeMarkup(description), y = lanes[lane].y, center = boxX + boxWidth / 2;
      return '<g class="trend-annotation" data-annotation-period="' + key + '" tabindex="0" role="img" aria-label="' + accessibleText + '">' +
        '<title>' + accessibleText + '</title>' +
        '<rect class="trend-annotation-box" x="' + boxX + '" y="' + y + '" width="' + boxWidth + '" height="' + cardHeight + '" rx="5"/>' +
        '<text class="trend-annotation-label" text-anchor="middle" dominant-baseline="central">' +
        lines.map((line, index) => '<tspan x="' + center + '" y="' + (y + paddingY + lineHeight * (index + 0.5)) + '">' + escapeMarkup(line) + '</tspan>').join("") +
        '</text></g>';
    }).join("");
    return { height, markup: '<g aria-hidden="true">' + stems + '</g>' + labels };
  }

  window.TrendAnnotations = Object.freeze({ dateKey, render });
})();
