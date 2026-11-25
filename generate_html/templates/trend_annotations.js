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

  function compactLabel(events, available, measure) {
    const text = events[0].text.trim();
    let candidates;
    if (events.length > 1) {
      candidates = [events.length + "条", String(events.length)];
    } else if (text.endsWith("首销结束")) {
      candidates = ["首销结束", "结束"];
    } else if (text.endsWith("小订开始") || text.endsWith("大定开始")) {
      candidates = [text.slice(-4, -2)];
    } else {
      candidates = [text.replace(/\s+/g, " "), "批注"];
    }
    return candidates.find(label => measure(label) <= available) || "·";
  }

  function render(notes, periods, grain, { left, step, width, anchorYs }) {
    const groups = new Map();
    for (const note of notes) {
      const key = dateKey(note?.date, grain);
      const text = typeof note?.text === "string" ? note.text.trim() : "";
      if (!key || !text) continue;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ date: note.date, text });
    }
    if (!groups.size) return { height: 0, markup: "" };

    const top = 4;
    const gap = 6;
    const paddingX = 4;
    const markerHeight = 20;
    const stemLength = 4;
    const markerGap = 6;
    const { measure } = labelMetrics();
    const markers = [];
    const seen = new Set();
    periods.forEach((period, index) => {
      const key = periodKey(period, grain);
      const events = groups.get(key);
      if (!events || seen.has(key)) return;
      seen.add(key);
      events.sort((a, b) => a.date.localeCompare(b.date));
      markers.push({
        key, events, index, x: left + (index + 0.5) * step,
        anchorY: Number.isFinite(anchorYs?.[index]) ? Number(anchorYs[index]) : 44,
        description: events.map(event => event.date + " " + event.text).join("\n")
      });
    });
    if (!markers.length) return { height: 0, markup: "" };

    markers.forEach((marker, index) => {
      const previous = markers[index - 1], next = markers[index + 1];
      const distance = Math.min(previous ? marker.x - previous.x : Infinity, next ? next.x - marker.x : Infinity);
      const spacingWidth = Number.isFinite(distance) ? distance - gap : Infinity;
      const edgeWidth = 2 * Math.min(marker.x - 4, width - 4 - marker.x);
      const maxWidth = Math.max(14, Math.min(120, edgeWidth, spacingWidth));
      const label = compactLabel(marker.events, maxWidth - 2 * paddingX, measure);
      const boxWidth = Math.max(14, Math.min(maxWidth, measure(label) + paddingX * 2));
      const boxX = Math.max(4, Math.min(marker.x - boxWidth / 2, width - boxWidth - 4));
      const boxY = Math.max(top, marker.anchorY - markerGap - stemLength - markerHeight);
      const stemStart = boxY + markerHeight;
      const stemEnd = Math.max(stemStart, marker.anchorY - markerGap);
      Object.assign(marker, { label, boxX, boxWidth, boxY, stemStart, stemEnd });
    });

    const stems = markers.map(({ x, stemStart, stemEnd }) => {
      const tip = stemEnd + 3;
      return '<line class="trend-annotation-stem" x1="' + x + '" x2="' + x + '" y1="' + stemStart + '" y2="' + stemEnd + '"/>' +
        '<path class="trend-annotation-tip" d="M ' + (x - 3) + ' ' + tip + ' h 6 l -3 3 Z"/>';
    }).join("");
    const labels = markers.map(({ key, boxX, boxWidth, boxY, label, description }) => {
      const accessibleText = escapeMarkup(description), center = boxX + boxWidth / 2;
      return '<g class="trend-annotation" data-annotation-period="' + key + '" tabindex="0" role="img" aria-label="' + accessibleText + '">' +
        '<title>' + accessibleText + '</title>' +
        '<rect class="trend-annotation-box" x="' + boxX + '" y="' + boxY + '" width="' + boxWidth + '" height="' + markerHeight + '" rx="10"/>' +
        '<text class="trend-annotation-label" x="' + center + '" y="' + (boxY + markerHeight / 2) + '" text-anchor="middle" dominant-baseline="central">' +
        escapeMarkup(label) +
        '</text></g>';
    }).join("");
    const height = Math.max(...markers.map(marker => marker.boxY + markerHeight), 0);
    return { height, markup: '<g aria-hidden="true">' + stems + '</g>' + labels };
  }

  window.TrendAnnotations = Object.freeze({ dateKey, render });
})();
