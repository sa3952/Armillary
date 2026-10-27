(function attachHouseSphere(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  const api = factory(commonJs ? require("./house-sphere-core.js") : root.HouseSphereCore);
  if (commonJs) module.exports = api;
  if (root) root.HouseSphere = api;
  if (!commonJs && root && root.document) api.mountAll(root.document);
})(typeof globalThis !== "undefined" ? globalThis : this, function buildHouseSphere(Core) {
  "use strict";

  // 〈宮位制〉文章的天球示意圖。兩個繪製端讀同一份場景（scene）：  - 文章裡每一種宮位制的靜態 SVG，由
  // scripts/frontend/figures/house_sphere.py 在建置時     經 Node 呼叫 toMarkup(scene(...)) 產生，沒有 JavaScript 或列
  // 印時看的就是它；  - 頁面上可以轉的那一張，由 mount() 以 createElementNS＋setAttribute＋textContent 建立。顏色、線寬
  // 與字級只用 class（article.css 的 --hs-* 自訂屬性）；沒有 innerHTML、沒有 style 屬性（CSP 的 style-src 'self' 與
  // trusted-types 'none'）。輸入只有緯度與地方恆星時，不收任何出生資料。

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SIGNS = ["牡羊", "金牛", "雙子", "巨蟹", "獅子", "處女", "天秤", "天蠍", "射手", "摩羯", "水瓶", "雙魚"];
  const NAMES = Object.freeze({ W: "整宮", E: "等分宮", O: "Porphyry", B: "Alcabitius", C: "Campanus", R: "Regiomontanus", P: "Placidus" });
  const CAPTIONS = Object.freeze({
    W: ["不切天空，只數星座",
      "上升點（此刻東方地平線上的那一點黃道）落在哪個星座，那整個星座就是第一宮，之後一個星座一宮。圖上的分隔線就是星座交界；把它們畫成經過北黃極（黃道的「北極」）的半圓，只是為了在球上看得見。"],
    E: ["從上升點起，沿黃道每 30 度一宮",
      "和整宮一樣只在黃道（太陽一年在天上走的路）上量，每宮都是 30 度；差別是宮界跟著上升點的度數走，不在星座交界上。中天通常不在第十宮頭上。"],
    O: ["四個軸點之間，沿黃道三等分",
      "上升、中天、下降、天底四點把黃道切成長短不一的四段，每段再沿黃道直接三等分。它仍只在黃道上量，但四段不等長，所以宮的大小不一。"],
    B: ["把上升點自己這一天走的路，按時間三等分",
      "細虛線小圓是上升點的周日圈（它跟著天球一天轉一圈走的圓）。上升點從東方地平升到中天的那一段（半日弧）按天球轉過的角度三等分，從天底升到地平的那一段（半夜弧）也三等分；每個分點沿通過天極的大圓（時圈）落到黃道上，就是中間的宮頭。"],
    C: ["把卯酉圈每 30 度切一刀",
      "卯酉圈是通過天頂與正東、正西兩點的大圓。從天頂起每 30 度取一點，與地平正北、正南兩點連成大圓，這些大圓和黃道的交點就是宮頭。它和 Regiomontanus 只差在切哪一個圓。"],
    R: ["把天赤道每 30 度切一刀",
      "天赤道是地球赤道投到天上的大圓。從子午圈起每 30 度取一點，與地平正北、正南兩點連成大圓，交黃道得宮頭。在赤道上它和 Campanus 相同，緯度越高差得越多。"],
    P: ["每個宮頭只看自己的半弧",
      "黃道上每一點從東方地平升到中天轉過的角度叫半日弧。第十二宮頭是「這段路只走了三分之一」的那一點，第十一宮頭是「走了三分之二」的那一點；地平線下用從天底升到地平的半夜弧同樣分。每個宮頭各用自己的半弧，所以宮界在球上是彎的，不是大圓。"],
  });
  const WARNINGS = Object.freeze({
    placidus_no_semiarc:
      "這個緯度在極區帶內（超過 90 度減黃赤交角，約 66.56 度）：有些黃道度數整天不升或不落，沒有半弧，Placidus 的構造在這裡沒有解。本站在整個極區帶不算 Placidus。圖上交叉排線的粗帶是整天不升或不落的黃道段。",
    mc_below_horizon_rejected:
      "中天此刻沉到地平線下（只會在極圈內發生）。這種宮位制先用上升點與中天把天空分成四段；中天沉下去之後，這四段就不再是這個方法設想的樣子。宮頭在數學上仍算得出，圖上照畫，但本站在這種情形不提供這種宮位制，可以改用整宮或等分宮。",
    degenerate_cusp_cycle_rejected:
      "中天此刻沉到地平線下（只會在極圈內發生）。照 Swiss Ephemeris 的定義，第十宮頭改用地平線上方子午圈的那一點，十二個宮頭於是反向排列（圖上照畫）。本站拒收這種排列，可以改用整宮或等分宮；這是本站的選擇，不是數學上算不出來。",
    quadrant_high_latitude_sensitivity: "緯度 60 度以上：四分宮制的宮頭對時刻與緯度的微小變動非常敏感，本站的結果會標「不穩定」。",
    polar_band_geometry: "在極區帶內：本站照常計算，但標為「可用，但屬極區幾何」。",
  });
  const FLAG = "教學示意・不是你的命盤";
  const DEFAULT_VIEW = Object.freeze({ yaw: 165, pitch: 22 });
  // 文章裡靜態圖與表 1 的那一片天空：緯度 25.05 度、地方恆星時 21 時 00 分。
  const START = Object.freeze({ lat: 25.05, armc: 315 });

  const fmtLon = (lon) => {
    const total = Math.round(lon * 60) % (360 * 60);
    const sign = Math.floor(total / 1800);
    const rest = total - sign * 1800;
    const degree = Math.floor(rest / 60);
    return `${SIGNS[sign]} ${degree}°${String(rest - degree * 60).padStart(2, "0")}′`;
  };
  const fmtLat = (lat) => `${lat >= 0 ? "北緯" : "南緯"} ${Math.abs(lat).toFixed(2)}°`;
  const fmtLst = (armc) => {
    const minutes = Math.round(Core.mod360(armc) * 4) % 1440;
    return `${Math.floor(minutes / 60)} 時 ${String(minutes % 60).padStart(2, "0")} 分`;
  };

  function evaluate(state) {
    const eps = Core.OBLIQUITY;
    const result = Core.cusps(state.sys, state.lat, state.armc, eps);
    const status = Core.siteStatus(state.sys, state.lat, state.armc, eps);
    const sizes = result.cusps ? result.cusps.map((c, i) => Core.mod360(result.cusps[(i + 1) % 12] - c)) : null;
    return { result, status, sizes, refused: status.state === "unavailable" };
  }

  function describe(state, evaluated) {
    const head = `${NAMES[state.sys]}，${fmtLat(state.lat)}，地方恆星時 ${fmtLst(state.armc)}`;
    const { result, sizes, refused, status } = evaluated;
    if (!result.cusps) return `${head}：這種構造在這裡沒有解，本站不算。`;
    const list = result.cusps.map((c, i) => `第 ${i + 1} 宮 ${fmtLon(c)}`).join("、");
    const verdict = refused
      ? `本站在這種情形不算這種宮位制（${status.reason === "mc_below_horizon_rejected" ? "中天沉到地平線下" : "宮頭反向排列"}）。` : "";
    return `${head}。十二個宮頭依序是：${list}。${sizeSentence(sizes)}${verdict}`;
  }

  /** 宮的大小：最小到最大；十二宮一樣大時只說一個數。宮頭反向排列時順向相減的弧加起來
   *  不是一圈，那些數不是宮的大小，所以不念。 */
  function sizeSentence(sizes) {
    const total = sizes.reduce((sum, size) => sum + size, 0);
    if (Math.abs(total - 360) > 1e-6) return "";
    const low = Math.min(...sizes).toFixed(1);
    const high = Math.max(...sizes).toFixed(1);
    return low === high ? `每一宮都是 ${low} 度。` : `宮的大小從 ${low} 度到 ${high} 度。`;
  }

  const SIZE = 640;
  // 球在圖上的位置與大小。頁面上可以轉的那一張用 LIVE；文章圖版（寬版與手機直版）的靜態圖由
  // house_sphere.py 傳入自己的 frame（plate: true），字改用圖版元件的字級 class。
  const LIVE = Object.freeze({ cx: 320, cy: 350, radius: 236, lift: 7, signs: true, plate: false });
  // 頁面上那張的字級（viewBox 單位）：桌機的 --hs-font 與 .hs-t-sign。標題區在球頂以上能用的高度。
  const BASE_FONT = 20;
  const SIGN_FONT = 18;
  const TITLE_ROOM = 92;
  // 互相壓到時誰留在原位：數字小的先放，後放的讓開。
  const RANK = Object.freeze({ 上升: 0, 中天: 0, 天頂: 1, 北: 2, 東: 2, 南: 2, 西: 2, 下降: 3, 天底: 3, 北黃極: 5, 北天極: 5 });

  /** 估字寬：漢字與全形符號一個字級寬，數字與拉丁字母約六成。 */
  function textWidth(text, font) {
    let width = 0;
    for (const ch of String(text)) width += ch.codePointAt(0) >= 0x2e80 ? font : 0.6 * font;
    return width;
  }

  /**
   * 把互相壓到的字推開。依 rank 先後放：每個字先試原位，再由近而遠試幾個位置（沿自己往外、往內、
   * 左右兩側，每步 0.3 個字高，最遠 3 個字高），取第一個不壓到已放的字、也不出 viewBox 的位置；
   * 都不行就取壓到面積最小的那個。字框含描邊的留白。
   */
  function declutter(items, font, fmt, obstacles, top) {
    const placed = obstacles.slice();
    const pad = 3;
    const boxAt = (item, x, y) => {
      const size = item.size || font;
      const width = textWidth(item.node.text, size);
      const left = item.anchor === "end" ? x - width : x - width / 2;
      return { left: left - pad, right: left + width + pad, top: y - 0.88 * size - pad, bottom: y + 0.12 * size + pad };
    };
    const overlap = (box) => placed.reduce((sum, other) => {
      const w = Math.min(box.right, other.right) - Math.max(box.left, other.left);
      const h = Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top);
      return w > 0 && h > 0 ? sum + w * h : sum;
    }, 0);
    const fits = (box) => box.left >= 0 && box.right <= SIZE && box.top >= top && box.bottom <= SIZE + 40;
    for (const item of [...items].sort((a, b) => a.rank - b.rank)) {
      const ways = [[item.ux, item.uy], [-item.ux, -item.uy], [-item.uy, item.ux], [item.uy, -item.ux]];
      let best = null;
      for (let k = 0; k <= 10 && !(best && best.cost === 0); k += 1) {
        for (const [wx, wy] of k ? ways : ways.slice(0, 1)) {
          const x = item.x + wx * k * 0.3 * font;
          const y = item.y + wy * k * 0.3 * font;
          const box = boxAt(item, x, y);
          if (!fits(box)) continue;
          const cost = overlap(box);
          if (!best || cost < best.cost) best = { x, y, box, cost };
          if (cost === 0) break;
        }
      }
      if (!best) best = { x: item.x, y: item.y, box: boxAt(item, item.x, item.y) };
      if (best.x !== item.x || best.y !== item.y) { item.node.attrs.x = fmt(best.x); item.node.attrs.y = fmt(best.y); }
      placed.push(best.box);
    }
  }

  const node = (tag, attrs, content) => ({
    tag, attrs: attrs || {}, children: Array.isArray(content) ? content : [], text: typeof content === "string" ? content : null,
  });
  const f1 = (x) => (Math.round(x * 10) / 10).toFixed(1);

  /** 視角：從外面看時東方在右（像看地球儀）；從裡面看時左右相反，東方在左，和星盤一樣。 */
  function camera(F, state, frame) {
    const y = state.yaw * Core.D;
    const p = state.pitch * Core.D;
    const d = Core.add(
      Core.scale(Core.add(Core.scale(F.N, Math.cos(y)), Core.scale(F.E, Math.sin(y))), Math.cos(p)), Core.scale(F.Z, Math.sin(p)),
    );
    const forward = Core.neg(d);
    const right = Core.norm(Core.cross(forward, F.Z));
    const up = Core.cross(right, forward);
    const mirror = state.inside ? -1 : 1;
    return (v) => [frame.cx + mirror * frame.radius * Core.dot(v, right), frame.cy - frame.radius * Core.dot(v, up), Core.dot(v, d)];
  }

  function plateText(cls) {
    const parts = cls.split(" ").filter((name) => name !== "hs-t");
    const dim = parts.some((name) => name === "hs-t-dim" || name === "hs-t-back" || name === "hs-t-sign");
    const roles = parts.map((name) => name.replace(/^hs-t-/, "hs-tx-"));
    return ["hs-tx", "fx-t", dim ? "fx-small fx-dim" : null, ...roles].filter(Boolean).join(" ");
  }

  function sphere(state, frame) {
    const eps = Core.OBLIQUITY;
    const evaluated = evaluate(state);
    const { result } = evaluated;
    const F = result.frame;
    const proj = camera(F, state, frame);
    const CX = frame.cx;
    const CY = frame.cy;
    const zoom = frame.radius / LIVE.radius;
    const tc = (cls) => (frame.plate ? plateText(cls) : cls);
    // 靜態圖版的座標取整數：誤差不到半個像素，九張圖、兩種版面加起來頁面小很多。
    // 點的半徑仍照舊（寬版取一位小數），免得小點被捨入得忽大忽小。
    const whole = (x) => String(Math.round(x));
    const fmt = frame.plate ? whole : f1;
    const fmtR = frame.plate && frame.radius < 150 ? whole : f1;
    const layers = { base: [], back: [], front: [], top: [], labels: [] };
    // 每個字的位置與「往外」的方向，給頁面上那張避開重疊用（declutter）；圖版不用。
    const tagged = [];
    function poly(points, cls) {
      let run = [];
      let front = null;
      const flush = () => {
        if (run.length > 1) {
          const drawn = run.map((q) => `${fmt(q[0])},${fmt(q[1])}`).join(" ");
          (front ? layers.front : layers.back).push(node("polyline", { class: front ? cls : `${cls} hs-back`, points: drawn }));
        }
      };
      for (const v of points) {
        const q = proj(v);
        const isFront = q[2] >= 0;
        if (front === null) front = isFront;
        if (isFront !== front) { run.push(q); flush(); run = [q]; front = isFront; } else run.push(q);
      }
      flush();
    }
    function greatCircle(u, v, from, to, step) {
      const out = [];
      for (let t = from; t <= to + 1e-9; t += step) {
        const a = t * Core.D;
        out.push(Core.add(Core.scale(u, Math.cos(a)), Core.scale(v, Math.sin(a))));
      }
      return out;
    }
    const full = (u, v) => greatCircle(u, v, 0, 360, 3);
    const perp = (u, v) => Core.norm(Core.sub(v, Core.scale(u, Core.dot(u, v))));
    const halfThrough = (pole, point) => greatCircle(pole, perp(pole, point), 0, 180, 4);
    const mirrored = (points) => points.map(Core.neg);
    const both = (points, cls) => { poly(points, cls); poly(mirrored(points), cls); };
    function dot3(v, cls) {
      const q = proj(v);
      const front = q[2] >= 0;
      (front ? layers.top : layers.back).push(node("circle", {
        class: front ? cls : `${cls} hs-back`, cx: fmt(q[0]), cy: fmt(q[1]), r: fmtR((cls.includes("hs-pt-big") ? 5 : 3.5) * Math.max(zoom, 0.7)),
      }));
    }
    function label(v, text, cls, distance) {
      const q = proj(v);
      const offset = distance * zoom;
      let dx = q[0] - CX;
      let dy = q[1] - CY;
      const length = Math.hypot(dx, dy) || 1;
      dx = (dx / length) * offset;
      dy = (dy / length) * offset;
      if (length < 8) { dx = 0; dy = -offset; }
      const x = q[0] + dx;
      const y = q[1] + dy + frame.lift;
      const labelText = node("text", { class: tc(q[2] >= 0 ? cls : `${cls} hs-t-back`), x: fmt(x), y: fmt(y) }, text);
      layers.labels.push(labelText);
      const unit = Math.hypot(dx, dy) || 1;
      tagged.push({ node: labelText, x, y, ux: dx / unit, uy: dy / unit, anchor: "middle", rank: RANK[text] ?? 4 });
    }
    const sys = state.sys;
    layers.base.push(node("circle", { class: "hs-ball", cx: CX, cy: CY, r: frame.radius }));
    const horizon = greatCircle(F.N, F.E, 0, 360, 4).map(proj);
    layers.base.push(node("polygon", { class: "hs-ground", points: horizon.map((q) => `${fmt(q[0])},${fmt(q[1])}`).join(" ") }));
    poly(full(F.N, F.E), "hs-hor");
    poly(full(F.N, F.Z), "hs-mer");
    poly(full(F.Meq, F.E), sys === "R" ? "hs-equ hs-strong" : "hs-equ");
    poly(full(F.Z, F.E), sys === "C" ? "hs-pv hs-strong" : "hs-pv");
    if (result.cusps && (sys === "W" || sys === "E" || sys === "O")) {
      result.cusps.forEach((c) => poly(halfThrough(F.K, Core.eclVec(c, eps)), "hs-cut hs-cut-faint"));
      dot3(F.K, "hs-pt hs-pt-dim");
      label(F.K, "北黃極", "hs-t hs-t-dim", 18);
    }
    if (sys === "R" || sys === "C") {
      const divided = sys === "R" ? F.Meq : F.Z;
      const pointClass = sys === "R" ? "hs-pt hs-pt-equ" : "hs-pt hs-pt-pv";
      for (const house of Core.EASTERN_CUSPS) {
        const a = Core.ALPHA[house] * Core.D;
        const point = Core.add(Core.scale(divided, Math.cos(a)), Core.scale(F.E, Math.sin(a)));
        if (house !== 10 && house !== 1) both(halfThrough(F.N, point), "hs-cut");
        dot3(point, pointClass);
        dot3(Core.neg(point), pointClass);
      }
    }
    if (sys === "B" && result.cusps) {
      const dec = Core.decOfLon(result.asc, eps);
      const arc = Core.semiArc(dec, state.lat);
      const circle = [];
      for (let t = 0; t <= 360; t += 4) circle.push(Core.raDecVec(t, dec));
      poly(circle, "hs-day");
      const upper = [];
      for (let k = 0; k <= 30; k += 1) upper.push(Core.raDecVec(state.armc + (arc * k) / 30, dec));
      poly(upper, "hs-arc");
      const angles = [0, -arc / 3, (-2 * arc) / 3, -arc, -arc - (180 - arc) / 3, -arc - (2 * (180 - arc)) / 3];
      angles.forEach((h, i) => {
        if (i !== 0 && i !== 3) both(halfThrough(F.P, Core.raDecVec(state.armc - h, 0)), "hs-cut");
        dot3(Core.raDecVec(state.armc - h, dec), "hs-pt hs-pt-acc");
      });
      dot3(F.P, "hs-pt hs-pt-dim");
      label(F.P, "北天極", "hs-t hs-t-dim", 18);
    }
    if (sys === "P") {
      if (result.cusps) {
        const limit = 90 - Math.abs(state.lat) - 0.02;
        for (const house of [11, 12, 2, 3]) {
          const curve = [];
          for (let k = 0; k <= 72; k += 1) {
            const sampleDec = -limit + (2 * limit * k) / 72;
            const sampleArc = Core.semiArc(sampleDec, state.lat);
            if (sampleArc !== null) curve.push(Core.raDecVec(state.armc - Core.placidusHourAngle(house, sampleArc), sampleDec));
          }
          both(curve, "hs-cut");
          const dec = Core.decOfLon(result.cusps[house - 1], eps);
          const arc = Core.semiArc(dec, state.lat);
          const marks = house === 11 || house === 12 ? [0, -arc / 3, (-2 * arc) / 3, -arc]
            : [180, 180 + (180 - arc) / 3, 180 + (2 * (180 - arc)) / 3, 360 - arc];
          const piece = [];
          for (let k = 0; k <= 30; k += 1) piece.push(Core.raDecVec(state.armc - (marks[0] + ((marks[3] - marks[0]) * k) / 30), dec));
          poly(piece, "hs-arc hs-arc-thin");
          marks.forEach((h) => dot3(Core.raDecVec(state.armc - h, dec), "hs-pt hs-pt-acc"));
        }
      } else {
        // 極區帶：整天不升或不落的黃道段
        let run = [];
        for (let lon = 0; lon <= 360; lon += 1) {
          if (Core.semiArc(Core.decOfLon(lon, eps), state.lat) === null) run.push(Core.eclVec(lon, eps));
          else { if (run.length > 1) poly(run, "hs-none"); run = []; }
        }
        if (run.length > 1) poly(run, "hs-none");
      }
      dot3(F.P, "hs-pt hs-pt-dim");
      label(F.P, "北天極", "hs-t hs-t-dim", 18);
    }
    if (result.cusps) {
      for (let i = 0; i < 12; i += 1) {
        const start = result.cusps[i];
        const span = Core.mod360(result.cusps[(i + 1) % 12] - start);
        const steps = Math.max(2, Math.ceil(span / 3));
        const piece = [];
        for (let k = 0; k <= steps; k += 1) piece.push(Core.eclVec(start + (span * k) / steps, eps));
        poly(piece, i % 2 ? "hs-ecl hs-ecl-b" : "hs-ecl hs-ecl-a");
        label(Core.eclVec(start + span / 2, eps), String(i + 1), "hs-t hs-t-num", 20);
      }
      result.cusps.forEach((c, i) => dot3(Core.eclVec(c, eps), i % 3 === 0 ? "hs-pt hs-pt-ink hs-pt-big" : "hs-pt hs-pt-ink"));
    } else { poly(full(Core.eclVec(0, eps), Core.eclVec(90, eps)), "hs-ecl hs-ecl-plain"); }
    for (let s = 0; s < 12; s += 1) {
      const v = Core.eclVec(s * 30, eps);
      const q = proj(v);
      const outer = proj(Core.scale(v, 1.04));
      if (q[2] >= 0) {
        layers.top.push(node("line", { class: "hs-tick", x1: fmt(q[0]), y1: fmt(q[1]), x2: fmt(outer[0]), y2: fmt(outer[1]) }));
      }
      const middle = proj(Core.eclVec(s * 30 + 15, eps));
      if (frame.signs && middle[2] >= 0.25) {
        const dx = CX - middle[0];
        const dy = CY - middle[1];
        const length = Math.hypot(dx, dy) || 1;
        const x = middle[0] + (dx / length) * 22 * zoom;
        const y = middle[1] + (dy / length) * 22 * zoom + frame.lift - 1;
        const sign = node("text", { class: tc("hs-t hs-t-sign"), x: fmt(x), y: fmt(y) }, SIGNS[s]);
        layers.labels.push(sign);
        tagged.push({ node: sign, x, y, ux: dx / length, uy: dy / length, anchor: "middle", rank: 6, size: SIGN_FONT });
      }
    }
    const ascVector = Core.eclVec(result.asc, eps);
    const mcVector = Core.eclVec(result.mc, eps);
    label(ascVector, "上升", "hs-t hs-t-axis", 40);
    label(mcVector, "中天", "hs-t hs-t-axis", 40);
    label(Core.neg(ascVector), "下降", "hs-t hs-t-dim", 40);
    label(Core.neg(mcVector), "天底", "hs-t hs-t-dim", 40);
    for (const [v, text] of [[F.N, "北"], [F.E, "東"], [Core.neg(F.N), "南"], [Core.neg(F.E), "西"]]) {
      dot3(v, "hs-pt hs-pt-hor");
      label(v, text, "hs-t hs-t-hor", 16);
    }
    dot3(F.Z, "hs-pt hs-pt-ink");
    // 天頂的字放在點的左上，避開常在附近的中天。
    const zenith = proj(F.Z);
    const zenithText = node("text", {
      class: tc(zenith[2] >= 0 ? "hs-t hs-t-end" : "hs-t hs-t-end hs-t-back"), x: fmt(zenith[0] - 10 * zoom), y: fmt(zenith[1] - 10 * zoom),
    }, "天頂");
    layers.labels.push(zenithText);
    tagged.push({ node: zenithText, x: zenith[0] - 10 * zoom, y: zenith[1] - 10 * zoom, ux: -Math.SQRT1_2, uy: -Math.SQRT1_2, anchor: "end", rank: RANK["天頂"] });
    const group = (name) => node("g", { class: `hs-layer-${name}` }, layers[name]);
    return { evaluated, tagged, fmt, layers: [group("base"), group("back"), group("front"), group("top"), group("labels")] };
  }

  /**
   * 頁面上可以轉的那一張。view 是頁面量到的字級（article.css 的 --hs-font，以 viewBox 單位計）：  · 沒給 view 時就是桌
   * 機的 20，標題兩行在原位；  · 窄螢幕字放大（compact）：不畫星座名（窄螢幕本來就藏起來）、副標太長就拆兩行，    標題
   * 區放不下時把 viewBox 往上延伸，而不是把球縮小。頁面上那張（有 view）會把互相壓到的字沿各自「往外」的方向推開
   * （declutter）。
   */
  function scene(state, view) {
    const font = (view && view.font) || BASE_FONT;
    const compact = Boolean(view && view.compact);
    const { evaluated, layers, tagged, fmt } = sphere(state, compact ? { ...LIVE, signs: false } : LIVE);
    const sys = state.sys;
    const dim = "hs-t hs-t-dim";
    const flag = "hs-t hs-t-flag";
    const inside = state.inside ? "｜從裡面看" : "";
    const subtitle = `${NAMES[sys]}｜${fmtLat(state.lat)}｜恆星時 ${fmtLst(state.armc)}${inside}`;
    const lines = [[FLAG, flag]];
    if (compact && textWidth(subtitle, font) > SIZE - 24) {
      lines.push([`${NAMES[sys]}｜${fmtLat(state.lat)}`, dim], [`恆星時 ${fmtLst(state.armc)}${inside}`, dim]);
    } else lines.push([subtitle, dim]);
    if (evaluated.refused) lines.push(["本站在這種情形不算這種宮位制", flag]);
    const baselines = lines.map((_line, i) => Math.round(font * (1.5 + 1.4 * i)));
    const extra = Math.max(0, Math.ceil(baselines[baselines.length - 1] + 0.3 * font - TITLE_ROOM));
    const title = lines.map(([text, cls], i) => node("text", { class: cls, x: 12, y: baselines[i] - extra }, text));
    const obstacles = lines.map(([text], i) => ({ left: 12, right: 12 + textWidth(text, font), top: baselines[i] - extra - 0.88 * font, bottom: baselines[i] - extra + 0.12 * font }));
    // 文章裡用同一個場景產生的靜態圖（不給 view）維持原樣，只有頁面上那張推開字。
    if (view) declutter(tagged, font, fmt, obstacles, -extra);
    return node("svg", {
      class: "hs-svg", viewBox: extra ? `0 ${-extra} ${SIZE} ${SIZE + 40 + extra}` : `0 0 ${SIZE} ${SIZE + 40}`, role: "img", "aria-label": describe(state, evaluated),
    }, [...layers, node("g", { class: "hs-title" }, title)]);
  }

  function plate(state, frame) {
    const { layers } = sphere(state, { ...LIVE, ...frame, plate: true });
    return node("g", { class: "hs-svg hs-plate" }, layers);
  }

  function stripScene(sizes, compact) {
    // 窄螢幕的字較大（article.css），窄的宮就不寫字，免得字超出色條。
    const numberRoom = compact ? 38 : 30;
    const degreeRoom = compact ? 70 : 56;
    const parts = [];
    let x = 0;
    sizes.forEach((size, i) => {
      const width = size * 2;
      parts.push(node("rect", { class: i % 2 ? "hs-bar hs-bar-b" : "hs-bar hs-bar-a", x: f1(x + 0.5), y: 4, width: f1(Math.max(0, width - 1)), height: 34 }));
      if (width > numberRoom) parts.push(node("text", { class: `hs-t ${i % 2 ? "hs-t-bar-b" : "hs-t-bar-a"}`, x: f1(x + width / 2), y: 30 }, String(i + 1)));
      if (width > degreeRoom) parts.push(node("text", { class: "hs-t", x: f1(x + width / 2), y: 70 }, `${Math.round(size)}°`));
      x += width;
    });
    return node("svg", { class: "hs-strip", viewBox: "0 0 720 76", "aria-hidden": "true" }, parts);
  }

  const escapeText = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const escapeAttr = (text) => escapeText(text).replace(/"/g, "&quot;");

  function toMarkup(tree, depth) {
    const pad = "  ".repeat(depth || 0);
    const attrs = Object.entries(tree.attrs).map(([key, value]) => ` ${key}="${escapeAttr(value)}"`).join("");
    if (tree.text !== null) return `${pad}<${tree.tag}${attrs}>${escapeText(tree.text)}</${tree.tag}>`;
    if (!tree.children.length) return `${pad}<${tree.tag}${attrs}/>`;
    return [`${pad}<${tree.tag}${attrs}>`, ...tree.children.map((child) => toMarkup(child, (depth || 0) + 1)),
      `${pad}</${tree.tag}>`].join("\n");
  }

  function toElement(document, tree) {
    const element = document.createElementNS(SVG_NS, tree.tag);
    for (const [key, value] of Object.entries(tree.attrs)) element.setAttribute(key, String(value));
    if (tree.text !== null) element.textContent = tree.text;
    for (const child of tree.children) element.appendChild(toElement(document, child));
    return element;
  }

  function mount(container) {
    const document = container.ownerDocument;
    const window = document.defaultView;
    const $ = (name) => container.querySelector(`[data-hs="${name}"]`);
    const live = $("live");
    const stage = $("stage");
    if (!live || !stage) return null;
    const state = { sys: "W", lat: START.lat, armc: START.armc, yaw: DEFAULT_VIEW.yaw, pitch: DEFAULT_VIEW.pitch, inside: false, playing: false };
    const reduceMotion = Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    let pending = false;
    let announceTimer = null;
    let timer = null;
    let last = 0;
    function announce(text) {
      // 只在停下來之後念一次，拖動滑桿或轉動時不連續報讀。
      window.clearTimeout(announceTimer);
      if (state.playing) return;
      announceTimer = window.setTimeout(() => { $("summary").textContent = text; }, 700);
    }
    // 圖上的字級跟著 article.css 的 --hs-font（窄螢幕較大）；量到不同就照新的字級重畫一次。
    // 字級只隨視窗寬度變：第一次畫好與視窗改變大小時才量，轉動或播放的每一幀不讀 computed style。
    const view = { font: BASE_FONT, compact: false, measured: false };
    function measureFont(svg) {
      const font = parseFloat(window.getComputedStyle(svg).getPropertyValue("--hs-font"));
      if (!(font > 0) || font === view.font) return;
      view.font = font;
      view.compact = font > BASE_FONT;
      schedule();
    }
    function render() {
      const tree = scene(state, view);
      const svg = toElement(document, tree);
      svg.setAttribute("tabindex", "0");
      svg.setAttribute("aria-describedby", $("help").id);
      svg.setAttribute("data-hs", "svg");
      const old = $("svg");
      if (old && document.activeElement === old) {
        old.replaceWith(svg);
        svg.focus({ preventScroll: true });
      } else if (old) old.replaceWith(svg);
      else stage.prepend(svg);
      bindSvg(svg);
      side();
      if (!view.measured) { view.measured = true; measureFont(svg); }
    }
    function schedule() { if (pending) return; pending = true; window.requestAnimationFrame(() => { pending = false; render(); }); }
    function side() {
      const evaluated = evaluate(state);
      const caption = CAPTIONS[state.sys];
      $("cap-title").textContent = `${NAMES[state.sys]}：${caption[0]}`;
      $("cap-body").textContent = caption[1];
      const warning = evaluated.status.reason ? WARNINGS[evaluated.status.reason] : "";
      const warn = $("warn");
      warn.hidden = !warning;
      warn.textContent = warning;
      const body = $("rows");
      body.textContent = "";
      const strip = $("strip");
      strip.textContent = "";
      if (evaluated.result.cusps) {
        evaluated.result.cusps.forEach((c, i) => {
          const row = document.createElement("tr");
          for (const [text, cls] of [[`第 ${i + 1} 宮`, ""], [fmtLon(c), "n"], [`${evaluated.sizes[i].toFixed(1)}°`, "n"]]) {
            const cell = document.createElement("td");
            cell.textContent = text;
            if (cls) cell.className = cls;
            row.appendChild(cell);
          }
          body.appendChild(row);
        });
        strip.appendChild(toElement(document, stripScene(evaluated.sizes, view.compact)));
      } else {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 3;
        cell.textContent = "這裡沒有解，不給宮頭。";
        row.appendChild(cell);
        body.appendChild(row);
      }
      $("lat-out").value = fmtLat(state.lat);
      $("lst-out").value = fmtLst(state.armc);
      $("lat").setAttribute("aria-valuetext", fmtLat(state.lat));
      $("lst").setAttribute("aria-valuetext", `地方恆星時 ${fmtLst(state.armc)}`);
      announce(warning ? `${describe(state, evaluated)}${warning}` : describe(state, evaluated));
    }
    const rotate = (dYaw, dPitch) => {
      state.yaw = Core.mod360(state.yaw + dYaw);
      state.pitch = Math.max(-85, Math.min(85, state.pitch + dPitch));
      schedule();
    };
    let drag = null;
    function bindSvg(svg) {
      svg.addEventListener("keydown", (event) => {
        const move = { ArrowLeft: [-5, 0], ArrowRight: [5, 0], ArrowUp: [0, 5], ArrowDown: [0, -5] }[event.key];
        if (move) { rotate(state.inside ? -move[0] : move[0], move[1]); event.preventDefault(); }
        if (event.key === "Home") { resetView(); event.preventDefault(); }
      });
      svg.addEventListener("pointerdown", (event) => {
        drag = [event.clientX, event.clientY];
        if (svg.setPointerCapture) svg.setPointerCapture(event.pointerId);
      });
      svg.addEventListener("pointermove", (event) => {
        if (!drag) return;
        const k = 300 / (svg.getBoundingClientRect().width || 300);
        const dx = (event.clientX - drag[0]) * 0.45 * k;
        // 觸控只拿左右的位移轉天球：上下滑交給頁面捲動（article.css 的 touch-action:pan-y），
        // 瀏覽器接手捲動之前送來的幾個 pointermove 也不該把視角拉高拉低。
        const dy = event.pointerType === "touch" ? 0 : (event.clientY - drag[1]) * 0.45 * k;
        rotate(state.inside ? dx : -dx, dy);
        drag = [event.clientX, event.clientY];
      });
      const stop = () => { drag = null; };
      svg.addEventListener("pointerup", stop);
      svg.addEventListener("pointercancel", stop);
    }
    function resetView() { state.yaw = DEFAULT_VIEW.yaw; state.pitch = DEFAULT_VIEW.pitch; schedule(); }
    container.querySelectorAll('input[name="hs-system"]').forEach((input) => {
      input.checked = input.value === state.sys;
      input.addEventListener("change", () => { state.sys = input.value; schedule(); });
    });
    $("lat").value = String(state.lat);
    $("lst").value = String(state.armc);
    $("lat").addEventListener("input", (event) => { state.lat = Number(event.target.value); schedule(); });
    $("lst").addEventListener("input", (event) => { state.armc = Number(event.target.value); schedule(); });
    container.querySelectorAll("[data-hs-lat]").forEach((button) => button.addEventListener("click", () => {
      state.lat = Number(button.getAttribute("data-hs-lat"));
      $("lat").value = String(state.lat);
      schedule();
    }));
    $("left").addEventListener("click", () => rotate(state.inside ? 15 : -15, 0));
    $("right").addEventListener("click", () => rotate(state.inside ? -15 : 15, 0));
    $("up").addEventListener("click", () => rotate(0, 10));
    $("down").addEventListener("click", () => rotate(0, -10));
    $("reset").addEventListener("click", resetView);
    $("inside").addEventListener("click", () => {
      state.inside = !state.inside;
      $("inside").setAttribute("aria-pressed", String(state.inside));
      schedule();
    });
    function step(time) {
      if (!state.playing) return;
      if (last) state.armc = Core.mod360(state.armc + (time - last) * 0.006);
      last = time;
      $("lst").value = String(state.armc);
      render();
      window.requestAnimationFrame(step);
    }
    $("play").addEventListener("click", () => {
      state.playing = !state.playing;
      $("play").setAttribute("aria-pressed", String(state.playing));
      $("play").textContent = state.playing ? "停下來" : "讓天球轉動";
      window.clearInterval(timer);
      if (!state.playing) { side(); return; }
      if (reduceMotion) {
        // 減少動態：不做連續動畫，每 1.2 秒跳 15 度。
        timer = window.setInterval(() => {
          state.armc = Core.mod360(state.armc + 15);
          $("lst").value = String(state.armc);
          render();
        }, 1200);
      } else { last = 0; window.requestAnimationFrame(step); }
    });
    window.addEventListener("resize", () => { const svg = $("svg"); if (svg) measureFont(svg); });
    live.hidden = false;
    const fallback = $("nojs");
    if (fallback) fallback.hidden = true;
    render();
    return { state, render };
  }

  function mountAll(document) {
    const start = () => document.querySelectorAll("[data-hs-figure]").forEach((container) => mount(container));
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }

  return Object.freeze({
    NAMES, CAPTIONS, WARNINGS, FLAG, DEFAULT_VIEW, START, fmtLat, fmtLst, evaluate, describe, scene, plate, toMarkup, mount, mountAll,
  });
});
