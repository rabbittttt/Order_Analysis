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

  const labelWidth = text => Array.from(text).reduce(
    (width, char) => width + (char.codePointAt(0) > 127 ? 12 : 8), 0
  );

  function fitLabel(text, suffix, maxWidth) {
    if (labelWidth(text + suffix) <= maxWidth) return text + suffix;
    const end = "…" + suffix;
    let shown = "";
    let remaining = maxWidth - labelWidth(end);
    for (const char of text) {
      remaining -= labelWidth(char);
      if (remaining < 0) break;
      shown += char;
    }
    return shown + end;
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
    const cardHeight = 22;
    const laneEnds = [];
    const markers = [];
    const seen = new Set();
    periods.forEach((period, index) => {
      const key = periodKey(period, grain);
      const events = groups.get(key);
      if (!events || seen.has(key)) return;
      seen.add(key);
      events.sort((a, b) => a.date.localeCompare(b.date));
      const suffix = events.length > 1 ? " +" + (events.length - 1) : "";
      const text = fitLabel(events[0].text, suffix, Math.min(156, width - 20));
      const boxWidth = labelWidth(text) + 12;
      const x = left + (index + 0.5) * step;
      const boxX = Math.max(4, Math.min(x - boxWidth / 2, width - boxWidth - 4));
      let lane = laneEnds.findIndex(end => end + gap <= boxX);
      if (lane < 0) lane = laneEnds.length;
      laneEnds[lane] = boxX + boxWidth;
      const description = events.map(event => event.date + " " + event.text).join("\n");
      markers.push({ key, x, boxX, boxWidth, y: top + lane * (cardHeight + gap), text, description });
    });
    if (!markers.length) return { height: 0, markup: "" };

    const height = top + laneEnds.length * (cardHeight + gap) + 10;
    const stems = markers.map(({ x, y }) =>
      '<line class="trend-annotation-stem" x1="' + x + '" x2="' + x + '" y1="' + (y + cardHeight) + '" y2="' + (height + 22) + '"/>' +
      '<path class="trend-annotation-tip" d="M ' + (x - 4) + ' ' + (height + 22) + ' h 8 l -4 6 Z"/>'
    ).join("");
    const labels = markers.map(({ key, boxX, boxWidth, y, text, description }) => {
      const accessibleText = escapeMarkup(description);
      return '<g class="trend-annotation" data-annotation-period="' + key + '" tabindex="0" role="img" aria-label="' + accessibleText + '">' +
        '<title>' + accessibleText + '</title>' +
        '<rect class="trend-annotation-box" x="' + boxX + '" y="' + y + '" width="' + boxWidth + '" height="' + cardHeight + '" rx="5"/>' +
        '<text class="trend-annotation-label" x="' + (boxX + boxWidth / 2) + '" y="' + (y + cardHeight / 2) + '" text-anchor="middle" dominant-baseline="central">' +
        escapeMarkup(text) + '</text></g>';
    }).join("");
    return { height, markup: '<g aria-hidden="true">' + stems + '</g>' + labels };
  }

  window.TrendAnnotations = Object.freeze({ dateKey, render });
})();
